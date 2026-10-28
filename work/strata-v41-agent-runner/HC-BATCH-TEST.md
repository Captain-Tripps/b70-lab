# HC batch test — attempt log, no result (2026-10-27 21:30–21:46)

Goal: run the test the earlier session proposed and never executed — `-p 32` vs `-p 512` on 1017,
comparing **per-token** prefill, to prove whether the batched prompt path is dead.

**The test did not complete.** llama-bench never produced a row. But the failure is itself
informative and rules out one hypothesis while confirming another.

-

## 1. What was run

```bat
llama-bench.exe -m D:\AI\Models\dsv41\DeepSeek-V4.1-Flash-1017-GSQ-RCO-IQ2_XXS-00001-of-00004.gguf
  -ngl 38 -sm layer -t 12 -p 32,512 -n 8 -r 1 --no-warmup
```

via `C:\llamacpp-v41\build-sycl\bin` (commit `de5122d`, has `deepseek41` in `llama.dll`).

## 2. What happened — the CPU-starved thrash

The process ran ~10 minutes and never emitted a single benchmark row. Sampled state:

| time | CPU (s) | working set |
|---|---:|---:|
| 21:40 | 241 | 85.7 GB |
| 21:44:21 | 343 | 51.3 GB |
| 21:44:33 | 354 | 59.8 GB |
| 21:44:45 | 366 | 67.9 GB |
| 21:44:57 | 380 | 67.9 GB |
| 21:45 | 422 | 66.6 GB |

**Working set oscillates 51 -> 68 GB while CPU climbs steadily.** That is allocation churn, not
forward-pass progress: a loading model climbs and plateaus, it does not sawtooth.

Decisive measurement at 21:44:57:

```
free RAM = 1.3 GB of 95.9 GB
```

**The host ran out of RAM.** The 1017 pack is 128.74 GiB across 4 shards; llama-bench loads the full
model into host memory before/while placing layers. On a 95.9 GB box that cannot fit, so the process
thrashed against the pagefile instead of completing the load. It was killed (RAM recovered to
87.1 GB, all VRAM released).

## 3. Why the earlier 0.33 t/s number is suspect, and what it still tells us

The ledger's `pp32 = 0.33 t/s` / `tg8 = 3.05 t/s` came from `-ngl 38` on this same 95.9 GB box. If
the model cannot fit in RAM, **that run may also have been thrashing** — which would mean 0.33 t/s
is a memory-starved artifact, not a pure HC-fusion artifact.

I am NOT claiming that yet. Two candidate explanations for the 9.2x pp/tg inversion:

- **A. Batched prompt path is dead** (HC fusion disabled). The original hypothesis.
- **B. The whole run was RAM-starved**, and prefill — which touches many more weights per step than
  single-token decode — degrades far harder under thrash. This would produce exactly this inversion
  without any HC bug.

**These are distinguishable and cheaply distinguished**, which is the useful outcome of tonight.

## 4. The test that actually decides it

Run the same `-p 32` vs `-p 512` comparison **without the 128 GB pack competing for host RAM**:

1. Use `--no-mmap` / `-lm none` if the build supports it, so weights stream rather than faulting
   through the pagefile, OR
2. Use a smaller quant of 1017 (any IQ1/IQ2 single-shard variant), OR
3. Free host RAM first — llama-swap was holding 9.3 h of residency; nothing was loaded at
   measurement time here, yet 95.9 GB still could not hold the working set.

Option 2 is cheapest: a smaller pack removes the confound entirely.

If pp-per-token stays flat across batch sizes on a pack that genuinely fits, that is **A** and the
HC kernel is the target. If pp-per-token scales with batch size, the original 0.33 was **B** and
there is no batching bug — the fix is memory, not a kernel.

## 5. Second real defect found: ~1.3 GB free RAM destroys the box

Independently of 1017, this is worth logging. When the bench drove free RAM to 1.3 GB, every
PowerShell probe on the host became slow or returned parse garbage, and `tasklist` disappeared from
PATH intermittently. A run that can drive the host to 1.3 GB free is a hazard to whatever else is on
the box — including the llama-swap service. **Any 1017 experiment needs a host-RAM guard**, not just
a VRAM guard.

## 6. Operational notes (hard-won, this session)

- **A long-running `exec` gets SIGKILLed by the harness**, which kills the ssh channel and therefore
  the remote child. Short exec calls + a detached Windows `Start-Process` survive.
- **`Start-Process cmd.exe -ArgumentList "/c <bat>"` from a bash→ssh→PowerShell chain mangles quoting.**
  Build the `.cmd` on disk first, then launch it by path with no inline quoting.
- **`Get-Process llama-bench` silently returns nothing** — PowerShell parses `-bench` as a parameter.
  Use `Get-Process -Name 'llama-bench'` or `tasklist /FI "IMAGENAME eq llama-bench.exe"`.
- **`-EncodedCommand` needs UTF-16LE**, not UTF-8: `iconv -f UTF-8 -t UTF-16LE | base64 -w0`.
- **Never pipe PowerShell with `$vars` through ssh double quotes** — local expansion eats them
  (`$_` becomes `/bin/bash`). Encode the script or push it as a file.
- **Do not pipe llama output through `findstr`** — it buffers and you get a 0-byte log.
- **Check free host RAM before blaming the engine.** This one cost the whole evening.

## 7. State

| Item | Value |
|---|---|
| llama-bench | gone |
| free RAM | 87.1 GB |
| VRAM | all adapters 0 GB |
| llama-swap | running, 9.3 h uptime, no model loaded |
| Result | **none produced** — test incomplete |
