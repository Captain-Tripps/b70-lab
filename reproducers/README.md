# Reproducers

Small standalone programs for driver / runtime behaviour found while tuning. All are my own code (MIT, see
[../LICENSE](../LICENSE)).

## l0-deadlock: Level Zero hang with several submitting threads + oneMKL

Several host threads submitting SYCL kernels at the same time, where some submissions come from oneMKL GPU `gemm`,
can block forever inside `zeCommandListAppendLaunchKernelWithArguments` in `ze_intel_gpu64.dll`.

I hit it in my cross-card pipeline for llama.cpp (one worker thread per GPU; stock llama.cpp submits from one thread
and is not affected). The workaround there is one lock around **all** kernel submissions from all threads, released
while waiting on events. Serialising only the gemm calls was not enough.

Reported to Intel on 2026-10-17: [Intel Community forum post](https://community.intel.com/t/144119) (driver) and
[intel/llvm#23530](https://github.com/intel/llvm/issues/23530) (SYCL runtime / Level Zero v2 adapter).

System: 4x Arc Pro B70, EPYC 7402P, Windows 11 Pro 26200, oneAPI DPC++ 2026.0.0 (build 20260331), oneMKL 2026.0,
UR Level Zero v2 adapter.

Build and run (oneAPI command prompt):

```
icx -fsycl /O2 /EHsc /std:c++17 /DUSE_MKL /DMKL_ILP64 /Qmkl l0_mt_submit.cpp /Fe:l0_mt_submit_mkl.exe /link mkl_sycl_blas_dll.lib
l0_mt_submit_mkl.exe 4 60 3 32
```

Arguments: threads, seconds, mode (3 = kernels + USM memcpy + oneMKL gemm), flags (32 = single-threaded warm-up first).
Exit code 2 = a thread made no progress for 30 s. Each thread owns one in-order queue (thread t on GPU t % 4).

Results on driver 32.0.101.8805 (Level Zero 1.15.37858):

| Configuration | Runs | Outcome |
|---|---|---|
| plain kernels only, 2 and 4 threads (modes 0-2), 45-90 s | 4 | all finished |
| + oneMKL gemm, 2 threads, 60-120 s | 5 | all finished |
| + oneMKL gemm, 3 threads, 60 s | 5 | 2 finished, 3 crashed (0xC0000005 or 0xC06D007F) |
| + oneMKL gemm, 4 threads, 40-60 s, no warm-up | 13 | 3 finished, 5 hung, 5 crashed |
| same, with warm-up (flag 32) | 9 | 4 finished, 5 hung, 0 crashed |
| 4 threads all on GPU 0 (flag 1) | 3 | 2 hung, 1 crashed |
| one mutex around every gemm call only (flag 2) | 3 | 2 finished, 1 hung |

Driver 32.0.101.8976 (Level Zero 1.15.39183+4), same binaries: 4 threads with warm-up 1 of 6 finished, 5 hung;
without warm-up 2 of 3 finished, 1 crashed; 3 threads with warm-up 2 of 2 finished; plain kernels + memcpy finished.
**Still present on the newer driver.**

Observations:
- When it hangs, it hangs within the first 5-10 seconds.
- The crashes only happen without the warm-up, so there look to be two problems: a first-use race and the deadlock.
- One GPU is enough to hang (4 threads on GPU 0).
- Stacks of a hung run (`stacks-repro-utf8.txt`, no driver symbols): 2 threads in `RtlAcquireSRWLockShared` under
  oneMKL's `sgemm_sycl` -> `urEnqueueKernelLaunchWithArgsExp` -> `zeCommandListAppendLaunchKernelWithArguments`;
  2 threads in `RtlAcquireSRWLockExclusive` under the test's own `parallel_for`; one more exclusive waiter. The same two
  driver return addresses appear in the original llama.cpp hang.
- Not known: which component owns the bug (driver locking vs how oneMKL / the SYCL runtime call it), and whether
  Linux shows it.

Files: `l0_mt_submit.cpp`, run logs `run1.txt` ... `run5-driver-8976.txt`, `stacks-repro-utf8.txt`.

## Parked next step: a newer Level Zero loader under the v2 adapter

On Linux, @92es reports
([B70 Collaborate, 2026-11-14](https://github.com/Captain-Tripps/b70-lab/discussions/3#discussioncomment-19623607))
that the v2 adapter now runs their 2- and 4-buffer exchange after building the Level Zero loader 1.35.0 and the Unified
Runtime from source, the runtime linked against that loader. Their finding: the Unified Runtime binds to the loader it
was built against, so installing a newer loader alone is not enough there. A later reply in the same thread says their
integrated GPU now works under that build too. Loader v1.36.0 came out on 2026-11-13.

The Windows test machine has loader 1.33.1 (shipped with driver 32.0.101.9175) and the oneAPI 2026.0 Unified Runtime.
Two v2 problems are open here: the cross-device `ext_oneapi_submit_barrier` abort
([oneapi-src/level-zero#556](https://github.com/oneapi-src/level-zero/issues/556)) and the deadlock above.

Tested 2026-11-15, cheapest first:

1. Loader 1.35.0 next to the test executables, under the oneAPI 2026.0 runtime.
2. Then, following @92es's hint on [#50](https://github.com/Captain-Tripps/b70-lab/pull/50) (`UR_ADAPTERS_FORCE_LOAD`),
   the Unified Runtime from intel/llvm v7.2.0 (UR 0.12.0, the same API version as oneAPI 2026.0's `ur_loader`): its
   loader and Level Zero v1/v2 adapters, built against loader 1.35.0.

What it could buy: the barrier exchange for llama.cpp `-sm tensor` on the v2 adapter (the related two-staging-slot
change measured +1-2%), and dropping the GLM port's forced v1 adapter (its v1/v2 A/B showed no speed difference). So
this is mainly a bug check for #556; little speed is expected.

### Result (2026-11-15): both v2 bugs remain; the barrier abort is inside the GPU driver

A newer loader or runtime does not fix it on driver 32.0.101.9175.

What it takes to run loader 1.35.0 on Windows at all:

- The 1.35.0 Windows SDK zip has headers and `ze_loader.lib` only, no `ze_loader.dll`: build it from the v1.35.0 source
  tag (MSVC, Release). The build also gives `ze_tracing_layer.dll` and `ze_validation_layer.dll`.
- A `ze_loader.dll` next to the executable is ignored: the SYCL proxy loader loads the Level Zero adapter with a
  System32-only search. Either link the test executable against `ze_loader.lib` (Windows then maps the local DLL before
  SYCL starts and the adapter reuses it), or force adapters built against the new loader with
  `UR_ADAPTERS_FORCE_LOAD`. Each run prints the loader module actually loaded.
- The loader takes its layers from its library path, which defaults to the System32 1.33.1 install. The 1.33.1
  tracing layer (spec 1.18) rejects the spec-1.20 tables: `zeDdiTableInit` returns
  `ZE_RESULT_ERROR_UNSUPPORTED_VERSION` and SYCL sees 0 GPUs. Setting `ZEL_LIBRARY_PATH` to the folder holding the
  1.35.0 layers fixes it (a raw `zeInit` probe then reports loader 1.35.0, tracing layer 1.35.0, the driver at API
  1.17). An earlier version of this note blamed the runtime's binding to the loader; it was this layer mismatch.
- `UR_ADAPTERS_FORCE_LOAD` needs quoted paths when they contain a colon:
  `set UR_ADAPTERS_FORCE_LOAD="D:\...\ur_adapter_level_zero_v2.dll","D:\...\ur_adapter_level_zero.dll"`.
- The v7.2.0 adapters crash (access violation) under oneAPI 2026.0's `ur_loader.dll`. They run with the v7.2.0
  `ur_loader.dll` beside them (configure with `-DUR_STATIC_LOADER=OFF`; the default is a static library).

Results, v2 adapter, `UR_L0_V2_DISABLE_ZE_LAUNCH_KERNEL_WITH_ARGS` unset, same session:

| Stack | Barrier exchange, 2 cards, 200 rounds | `l0-deadlock`, 4 threads x 4 cards, 60 s |
|---|---|---|
| Loader 1.33.1 (System32), oneAPI 2026.0 runtime | aborts 9 of 9 | hangs 5 of 9 |
| Loader 1.35.0 + its layers, oneAPI 2026.0 runtime | aborts 3 of 3 | hangs 3 of 3 |
| Loader 1.35.0 + its layers, UR v7.2.0 loader + adapters built against it | aborts 3 of 3 | hangs 1 of 3 |

Every abort is `Abort was called at 3576 line in file:` (0xC0000409), before round 0 finishes. That message is the
Intel driver's own internal-error stop: the string is in `ze_intel_gpu64.dll`, not in the loader, `ur_loader` or the
adapters. So #556 is a driver bug at this version; on Linux @92es runs a newer compute runtime. The deadlock rate
moves within the noise of 3-run samples; no stack removed it.

Next: re-test when a newer Windows driver ships (the test folders and scripts stay on the test machine). Until then
the GLM port keeps its forced v1 adapter and llama.cpp `-sm tensor` keeps the host-wait exchange.

## ep-probe: can two B70s share memory on Windows?

`ep-probe/ep_probe.cpp` tests three ways for two Arc cards in one process to share memory under Windows Level Zero:

1. IPC handle across two per-device contexts (what Strata does on Linux),
2. `zeDeviceCanAccessPeer` + one context holding both devices, card 1's kernel writing card 0's device memory,
3. host USM in that shared context, read and written by both cards' kernels.

```
icx -fsycl ep_probe.cpp ze_loader.lib
set ONEAPI_DEVICE_SELECTOR=level_zero:2,3
ep_probe.exe
```

Result on two B70s (driver 8976): 1 fails (`zeMemGetIpcHandle` 0x78000003), 2 fails (peer access 0; touching the
other card's memory = `DEVICE_LOST`), **3 works**. See [../strata-windows-port/](../strata-windows-port/).

## flag-visibility: can a running kernel see a host-USM write?

`flag-visibility/flag_test4.cpp` starts a one-work-item kernel on card 1 that spins on a flag in host USM, then has
either the host or a kernel on card 0 write 256 data words and the flag. It reports whether the spinning kernel saw the
flag and how many of the data words it read were still stale. Each loop variant: a plain volatile load, a SYCL
`atomic_fence(acquire, system)` or `(seq_cst, system)` before the volatile load, and an ESIMD
`fence<global, invalidate, system>` before the load (the control). The reader touches the data first, so stale lines are
in its caches.

```
icpx -fsycl -O2 flag_test4.cpp -o flag_test4.exe
set ONEAPI_DEVICE_SELECTOR=level_zero:0,1
flag_test4.exe
```

Result on two B70s (Windows 11, driver 32.0.101.9175, oneAPI 2026.0), `flag_test4-output.txt`:

| Writer | Plain volatile load | Fence + load (any of the three) |
|---|---|---|
| host | flag never seen (2M loads) | seen 0.02-0.04 ms after the write, 0 of 256 words stale |
| card 0 | flag never seen, **256 of 256 words stale** | seen 0.27-0.34 ms after the write, 0 of 256 words stale |

Without a fence a spinning kernel keeps reading its cached copy. With a system-scope fence each turn it sees both the
flag and the data written before it. LSC uncached-hint loads and LSC atomic loads without a fence did not see a host
write in an earlier variant of the test. This is what let the DeepSeek `ds4` port wait for the other card on the
device instead of the host ([tensor parallel 2 on Windows](../deepseek-v4/maya-ds4-sycl/#tensor-parallel-2-on-windows-2026-11-23-device-side-waits)).
