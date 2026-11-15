# Reproducers

Small standalone programs for driver / runtime behaviour found while tuning. Both are my own code (MIT, see
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

Not run yet. On Linux, @92es reports
([B70 Collaborate, 2026-11-14](https://github.com/Captain-Tripps/b70-lab/discussions/3#discussioncomment-19623607))
that the v2 adapter now runs his 2- and 4-buffer exchange after building the Level Zero loader 1.35.0 and the Unified
Runtime from source, the runtime linked against that loader. His finding: the Unified Runtime binds to the loader it
was built against, so installing a newer loader alone is not enough there.

The Windows test machine has loader 1.33.1 (shipped with driver 32.0.101.9175) and the oneAPI 2026.0 Unified Runtime.
Two v2 problems are open here: the cross-device `ext_oneapi_submit_barrier` abort
([oneapi-src/level-zero#556](https://github.com/oneapi-src/level-zero/issues/556)) and the deadlock above.

Test, cheapest first:

1. The official loader 1.35.0 (or newer) Windows build placed next to the test executables, nothing system-wide.
   Re-run `l0-deadlock` and the standalone barrier exchange test
   ([tensor-split notes](../llama.cpp-sycl/TENSOR-SPLIT-DECODE.md)) on the v2 adapter.
2. Only if 1 changes nothing: build the Unified Runtime against that loader, as on Linux.

What it could buy: the barrier exchange for llama.cpp `-sm tensor` on the v2 adapter (the related two-staging-slot
change measured +1-2%), and dropping the GLM port's forced v1 adapter (its v1/v2 A/B showed no speed difference). So
this is mainly a bug check for #556; little speed is expected.

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
