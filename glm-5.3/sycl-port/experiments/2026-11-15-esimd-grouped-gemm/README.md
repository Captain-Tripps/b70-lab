# ESIMD grouped expert GEMM from llama.cpp#31428 - 2026-11-15

## Decision

Measured, not live. Lead L12: the engine's prompt read takes its grouped expert products from a fork of the llama.cpp
SYCL grouped XMX GEMM. [llama.cpp#31428](https://github.com/ggml-org/llama.cpp/pull/31428) adds an ESIMD version of
that kernel: the weights are dequantized in registers and fed straight to the matrix units, with no shared-memory
staging and no barriers. Dropped into the engine, it makes cold prompt reads about 10% faster: 45.8k 31.2 -> 28.0 s,
115k 81.3 -> 73.1 s (two runs each, A / B / joint / B / A). Decode is unchanged. Quality holds on the teacher-forced
check: true-token loss equal or slightly lower, top token as live at 60 of 64 positions on the 32k input (the 1536-chunk
change promoted on 2026-11-13 gave 62 of 64).

All of the gain comes from one product. GLM's expert down product is IQ3_XXS, which the PR covers; gate/up is IQ2_S,
which it does not, so gate/up still runs the old kernel. On the 2026-11-10 profile gate/up was the larger of the two
(2.49 vs 1.42 s of an 8k prompt on the slowest card), so an IQ2_S loader for the ESIMD kernel is the next step.

Promoting it would change the live engine, so it waits for Jon (and a soak, as for the 1536 change).

## The candidate

[`build_l12.py`](build_l12.py) copies the live (aligned Q6_K) tree and replaces `src/forkxmx/fused-gemm.cpp` with the
PR head's (`eec5c09`) `fused-gemm.cpp` plus its new `fused-gemm-esimd.cpp`. The fork files are compiled against the PR
head's headers. The engine's shim needed three changes for the newer API: the tile type's new name, the precision
argument (now a `ggml_prec` request; `GGML_PREC_UNDEFINED` is 0, the value the old `GGML_PREC_DEFAULT` passed), and
the settings reader `ggml_sycl_get_env` that `ggml-sycl.cpp` normally provides. 0 compile errors, 0 unresolved
symbols. JIT, as the live build.

One gotcha: the ESIMD path is compiled only when `GGML_SYCL_SUPPORT_XMX` is defined, which the PR's CMake sets. Without
it the file builds cleanly and the engine silently runs the PR's joint_matrix kernel. The first screen ran that way
([`requests-run1-no-esimd.jsonl`](requests-run1-no-esimd.jsonl): 45.8k in 32.2 s against live's 32.6), which is what
showed the define was missing. The same binary takes `GGML_SYCL_MMID_ESIMD=0` to turn the ESIMD path off; that is the
"joint" arm below.

## Prompt-read screen

The harness of the [1536-chunk screen](../2026-11-13-prefill-chunk-1536/): live config and server tree on a separate
port, one fresh process per arm, an 8.9k warm-up, a cold 45,818-token read, a cold 115,108-token read and two
512-token decodes. [`screen_l12.py`](screen_l12.py), [`all_l12.py`](all_l12.py), raw rows in
[`requests.jsonl`](requests.jsonl).

| Arm | Warm-up 8.9k | Cold 45.8k | Cold 115.1k | Decode 1 / 2 |
|---|---:|---:|---:|---:|
| Live, opening | 8.98 s | 31.46 s | 81.96 s | 45.2 / 46.6 tok/s |
| **ESIMD** | 10.27 s | **27.81 s** | **72.48 s** | 45.1 / 46.5 |
| Candidate, ESIMD off (`GGML_SYCL_MMID_ESIMD=0`) | 9.05 s | 31.13 s | 80.90 s | 45.3 / 46.6 |
| **ESIMD**, second run | 8.17 s | **28.26 s** | **73.61 s** | 45.2 / 46.6 |
| Live, closing | 9.04 s | 31.02 s | 80.59 s | 45.1 / 46.5 |

- ESIMD against the live mean: 45.8k -10.3%, 115k -10.1%. The joint-matrix arm matches live, so the gain is the ESIMD
  kernel, not the rest of the PR.
- The first ESIMD warm-up is slower (10.27 s), the second faster (8.17 s). The ESIMD kernels most likely compile on
  their first use under JIT; a warmed server does not pay that again.
- No arm declined a grouped product, and none copied experts in while a prompt ran (all staging totals zero).
- The decodes give the same text on every arm. The 45.8k answer is the same text on every arm; the 8.9k and 115k answers
  differ on the ESIMD arms (the prompt's numbers changed, see below), the same on both ESIMD runs.

## Logit check

The method of the [1536-chunk check](../2026-11-13-prefill-chunk-1536/#logit-check): `generate.exe` with
`STRATA_GLM_KL_DUMP=<file>,64` and speculation off reads all but the last 64 tokens of an input, then forces those 64
and writes each position's full-vocabulary logits. Live prompt arguments (`--prefill 1536`, 64k checkpoint spacing).
[`kl_l12.ps1`](kl_l12.ps1), [`kl_all.ps1`](kl_all.ps1), [`nll_l12.py`](nll_l12.py), output in
[`logit-check.txt`](logit-check.txt).

| Input | Arm | True-token log-loss (63 tokens) | True token top-ranked | Top token as live |
|---|---|---:|---:|---:|
| 32k long | live | 0.9877 | 53 / 63 | |
| 32k long | ESIMD | 0.9855 | 54 / 63 | 60 / 64 |
| 32k long | ESIMD off | 0.9877 | 53 / 63 | 64 / 64, same bytes |
| 32k long | live, again | 0.9877 | 53 / 63 | 64 / 64, same bytes |
| 8k code | live | 0.0001 | 63 / 63 | |
| 8k code | ESIMD | 0.0001 | 63 / 63 | 64 / 64 |
| 8k code | ESIMD off | 0.0001 | 63 / 63 | 64 / 64, same bytes |

ESIMD changes the numbers (it dequantizes in registers in a different order), by about as much as the 1536 chunk
did, and scores no worse against the real next tokens. With the ESIMD path off, the PR's kernel gives the live logits
byte for byte. Within what 63 tokens can show, no measurable loss.

## Next

1. An IQ2_S loader for the ESIMD kernel, for gate/up. The PR's IQ3_XXS loader is the model: per 32 values, four grid
   indices (8 bits plus 2 high bits from `qh`) into the 1,024-entry, 8-byte IQ2_S grid (8 KB in shared memory), four
   sign bytes and two 4-bit scales. `grid_signed` fits it with one change: a scale per 16-value half instead of one
   per row.
2. If Jon wants the down-product gain live first: a soak on the candidate, as for the 1536 change.

## Setup

4x Arc Pro B70, Windows 11, driver 32.0.101.9175, oneAPI 2026.0 JIT. Live executable `2c21539a...`; candidate
`7112581d...`. GLM unloaded for the runs and reloaded afterwards (it answered).
