# 1017 — CORRECTED: it runs, and prefill is the bottleneck (2026-10-27)

> **This file replaces an earlier version that said "1017 cannot be tuned — the runtime does not
> exist." That was WRONG.** It was based on probing the wrong binary. Kept as a correction record.

-

## 1. What I got wrong, and why

I ran the 1017 pack through `llama-server.exe` from the **tuned r67c fork**
(`master-797de6-b70-r67c`, base `797de63b2`, 2026-10-17) and got:

```
E llama_model_load: error loading model: unknown model architecture: 'deepseek41'
```

I then checked the arch table in that build — `deepseek`, `deepseek2`, `deepseek32`, `deepseek4` — and
concluded no build on the box could load it.

**Both observations were true and the conclusion was false.** `deepseek41` landed upstream on
2026-10-25 (PR #31086), *after* the fork's base commit. There is a second, newer build on this box
that has it:

| | |
|---|---|
| Tree | `C:\llamacpp-v41` |
| Commit | `de5122d` — "ggml : relax scale to non-contiguous views (#31146)", 2026-10-27 |
| Binaries | `C:\llamacpp-v41\build-sycl\bin\` |
| Arch support | in **`llama.dll`** (9 `deepseek41` strings), not in the 10 KB `.exe` launchers |
| Source | `src/models/deepseek41.cpp`, 52,210 B, plus a `deepseek41.cpp.orig-strata-keys` variant |

**Method lesson:** the `.exe` files are launchers that link `llama.dll`; scanning only the `.exe`
produces a false negative on architecture support. Scan the DLLs, or better, just try to load the
model.

## 2. It has already run — the ledger has numbers

`work/strata-v41-agent-runner/FINDINGS.md` (W-019 / L-025) records a real llama-bench run:

```
| deepseek41 ?B IQ2_XXS - 2.0625 bpw | 128.74 GiB | 551.88 B | SYCL | 38 | 12 | pp32 | 0.33 ± 0.00 |
| deepseek41 ?B IQ2_XXS - 2.0625 bpw | 128.74 GiB | 551.88 B | SYCL | 38 | 12 | tg8  | 3.05 ± 0.00 |
```

Weight placement from the same run (`st10.log`):

```
CPU_Mapped total = 9,309.6 MiB  (~9.1 GB)     <- token_embd (q5_K), NOT the MoE experts
SYCL0..3 total   = 122,312.4 MiB (~119.4 GB)  <- ~93% GPU-resident
```

So: **it loads, it runs on the GPUs, ~93% of weights are resident.** The pack is not unrunnable.

## 3. The real finding: prompt processing is 9.2x SLOWER than token generation

```
pp32 = 0.33 t/s      (3.17 s per prompt token)
tg8  = 3.05 t/s      (0.72 s per generated token)
```

That is backwards. On any healthy backend, prefill is batched and runs 10-100x *faster* per token
than single-token decode. Here it is an order of magnitude slower, which means **the batched prompt
path is not engaging** for `deepseek41` on SYCL.

Consequence: 32 tokens took ~97 s. A 512-token prompt would take ~26 min. A 4,096-token prompt would
take **~3.4 hours**. The pack cannot serve realistic prompts as-is.

## 4. Prime suspect, already in the log

At load time:

```
W resolve_fused_ops: fused DeepSeek V4 HC pre not supported, set to disabled
```

Hyper-connection (HC) layers exist in **all 40 blocks** of this model. With the fused HC op disabled,
every block takes the unfused fallback. If that fallback is not batched on SYCL, pp collapses to
per-token speed while tg (already one-token-at-a-time by nature) degrades far less — which fits the
9.2x inversion exactly.

Other candidates, unranked:
- IQ2_XXS dequant kernels for these expert shapes pathological on SYCL
- `attn_compressor` / `indexer` ops falling back to slow generic kernels

## 5. What is genuinely still missing (unchanged)

| Item | Status |
|---|---|
| DSpark drafter for 1017 | **absent.** Pack = 1008 tensors, layers 0-39, zero `mtp.*`. Confirmed via the packer's own allocation dump. |
| Strata `sycl/src/dsv41/` | **does not exist**, 0 lines ported |
| Upstream SYCL + `deepseek41` | **present and working enough to run** (`de5122d`) |

So the tuning target is the **upstream fork build**, not the Strata port. The Strata port remains a
separate, larger track.

## 6. Corrected recommendation

**Do not tune split mode yet.** With pp at 0.33 t/s, `-sm layer` vs `-sm tensor` is measuring noise on
a path that is already broken.

The highest-value work is the **HC unfused fallback path**:

1. Confirm batching is dead: run `-p 32` vs `-p 512` and compare **per-token** pp. If pp-per-token is
   constant regardless of batch size, batching definitively is not engaging. (This is the test the
   earlier session proposed and never ran.)
2. Find where the unfused HC op is implemented and whether the SYCL backend has a batched variant.
3. If not, that is the port: a batched unfused HC kernel.

Only after pp is sane does decode tuning (`-sm`, `-ub`, `-ts`) mean anything.

## 7. Reproduce

```bat
call "C:\Program Files (x86)\Intel\oneAPI\setvars.bat" --force
cd /d C:\llamacpp-v41\build-sycl\bin
set ONEAPI_DEVICE_SELECTOR=level_zero:0,1,2,3
set ZES_ENABLE_SYSMAN=1
set UR_L0_ENABLE_RELAXED_ALLOCATION_LIMITS=1
llama-bench.exe -m "D:\AI\Models\dsv41\DeepSeek-V4.1-Flash-1017-GSQ-RCO-IQ2_XXS-00001-of-00004.gguf" ^
  -ngl 38 -sm layer -t 12 -p 32 -n 8 -r 1 --no-warmup
```

Notes learned the hard way:
- **Do not pipe llama output through `findstr`** — the pipe buffers and you get a 0-byte log.
  Redirect straight to a file.
- `Get-Process llama-bench` silently returns nothing (PowerShell parses `-bench` as a parameter).
  Use `Get-Process -Name 'llama-bench'` or `tasklist /FI "IMAGENAME eq llama-bench.exe"`.
- `-ngl 0` on a 128 GB model will OOM the host (87 GB free). Always offload.
- Production llama-swap holds VRAM on SYCL0-2; a 1017 run either tolerates ~9 GB/card less, or the
  operator pauses that arm deliberately. Leave ~1.5 GB headroom per card past 32 GB.
