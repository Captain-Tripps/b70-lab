# ESIMD grouped expert GEMM from llama.cpp#31428 - 2026-11-15

## Decision

Live in two steps, both at Jon's request after a clean 30-minute soak. Cold prompt reads are about 22% faster than
before this lead: 45.8k 31.2 -> 24.3 s, 115k 81.3 -> 63.7 s. Decode is unchanged.

Lead L12: the engine's prompt read takes its grouped expert products from a fork of the llama.cpp SYCL grouped XMX
GEMM. [llama.cpp#31428](https://github.com/ggml-org/llama.cpp/pull/31428) adds an ESIMD version of that kernel: the
weights are dequantized in registers and fed straight to the matrix units, with no shared-memory staging and no
barriers.

1. **The PR's kernel as is** covers GLM's expert down product (IQ3_XXS): cold reads -10% (45.8k 31.2 -> 28.0 s, 115k
   81.3 -> 73.1 s). Promoted 2026-11-16 after its soak.
2. **An IQ2_S format added here** for the gate/up product, which the PR does not cover: a further -12.5% (45.8k 27.9
   -> 24.3 s, 115k 72.6 -> 63.7 s). In the kernel's bit-exact mode it reproduces the old build's logits byte for
   byte, so the format decodes exactly as the old kernel does. [Round 2](#round-2-an-iq2_s-format-for-gateup).

Quality, teacher-forced 32k check against the real next tokens: log-loss 0.9877 (old build), 0.9855 (step 1), 0.9915
(step 2); top token as the old build at 60 and 62 of 64 positions. These are shifts of the size the 1536-chunk change
made (0.985 vs 0.988, 62 of 64): no measurable loss within what 63 tokens can show.

The kernel's default mode (1) sums K in one pass; mode 2 reproduces the old kernel's K split and output bits but is
far slower here (45.8k 58.8 s), so the live engine runs mode 1.

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

ESIMD changes the numbers by about as much as the 1536 chunk did, and scores no worse against the real next tokens.
With the ESIMD path off, the PR's kernel gives the live logits byte for byte. Within what 63 tokens can show, no
measurable loss. The change comes from the summation order, not the dequantization: the kernel's default mode (1)
sums the whole K in one pass, while mode 2 reproduces the old kernel's four-way K split, and in mode 2 the logits are
the old build's byte for byte (round 2 below).

## Soak and promotion of step 1 (2026-11-16)

The [1536 soak](../2026-11-13-prefill-chunk-1536/#soak) mix, 30 minutes on the candidate with the live config and
server tree, only the executable changed. [`soak_esimd.py`](soak_esimd.py),
[`soak-requests.jsonl`](soak-requests.jsonl).

| Request | 1536 soak (old build), median | Step 1 soak, median |
|---|---:|---:|
| 115k first read | 82.8 s | 74.6 s |
| 31k conversation switch | 22.5 s | 20.2 s |
| Repeated 115k edits | 0.51 s | 0.53 s |
| Return to the long conversation | 0.52 s | 0.53 s |
| Short switch | 0.31 s | 0.33 s |

60 cycles, 495 requests, no errors and no driver crash; lowest free RAM 73.5 GiB. Every repeated request type gave
one answer across all cycles. 11 of the 60 straight-after-switch edits (a new question each cycle) stopped before 64
tokens, at 42-62; the 1536 soak's raw rows show the same (6 of 57, 42-63), so its README's "every answer ran its full
64 tokens" was slightly off. Those are the model ending its answer, not errors.

Promoted: the GLM engine config's `exe` now points at a copy of the candidate in its own runtime folder
(`7112581d...`, [`promote_esimd.py`](promote_esimd.py)); `GGML_SYCL_MMID_ESIMD` is not set (mode 1). Only the engine
config changed, not the llama-swap config. After promotion, through the proxy: a short arithmetic prompt answered
correctly; a cold 45.8k read took 31.0 s as the first prompt after loading (the ESIMD kernels compile on first use)
and 27.8 s on a second cold read.

## Round 2: an IQ2_S format for gate/up

[`patch_iq2s.py`](patch_iq2s.py) adds IQ2_S to the PR's ESIMD kernel; [`build_iq2s.py`](build_iq2s.py) builds it on
the step 1 tree. Per 32 values an IQ2_S block holds four grid indices (a `qs` byte plus 2 high bits from `qh`) into
a 1,024-entry grid of 8 values, four sign bytes and a scale byte (low nibble for values 0-15, high for 16-31).

- The grid is 8 KB, and the kernel runs one thread a work-group, so each thread would hold its own 8 KB of shared
  memory. Every grid value is 8, 25 or 43, so each entry packs into 16 bits of 2-bit levels: a 2 KB table, the size of
  the PR's IQ3_S table ([`iq2s_code_table.inc`](iq2s_code_table.inc), generated from ggml's grid and checked against
  it entry by entry). The kernel expands four levels to their bytes with shifts and masks: field i to byte i, level
  l to 8 + 17 l + (l >> 1).
- A is rounded as the old kernel's IQ2_S stage rounds it: f16(f32(d) * (0.5 + scale) * 0.25 * +-grid).
- Only the canonical block layout is taken (the engine never reorders the weights).

Logit check first ([`kl2_all.ps1`](kl2_all.ps1), output [`logit-check-round2.txt`](logit-check-round2.txt)):

| Arm | 32k: log-loss | 32k: true top-1 | 32k: as old build | 8k code: as old build |
|---|---:|---:|---:|---:|
| Old build (joint matrix) | 0.9877 | 53 / 63 | | |
| Step 1, mode 2 | 0.9877 | 53 / 63 | same bytes | same bytes |
| **Step 2 (IQ2_S), mode 2** | 0.9877 | 53 / 63 | **same bytes** | **same bytes** |
| Step 2, mode 1 | 0.9915 | 52 / 63 | top-1 62 / 64 | top-1 64 / 64 |
| Step 1, mode 1 (live) | 0.9855 | 54 / 63 | top-1 60 / 64 | top-1 64 / 64 |

Mode 2 giving the old bytes means the new format decodes every index, sign and scale exactly as the old kernel.

Screen, the same harness, the step 1 build as live ([`all_l12b.py`](all_l12b.py), raw rows in
[`requests-round2.jsonl`](requests-round2.jsonl)):

| Arm | Warm-up 8.9k | Cold 45.8k | Cold 115.1k | Decode 1 / 2 |
|---|---:|---:|---:|---:|
| Live (step 1), opening | 8.15 s | 27.85 s | 72.59 s | 45.2 / 46.6 tok/s |
| **Step 2, mode 1** | 7.31 s | **24.28 s** | **63.67 s** | 45.1 / 46.6 |
| Step 2, mode 2 | 14.39 s | 58.78 s | 149.27 s | 45.2 / 46.7 |
| Step 1, mode 2 | 10.12 s | 36.65 s | 94.50 s | 45.2 / 46.6 |
| **Step 2, mode 1**, second run | 7.30 s | **24.26 s** | **63.65 s** | 45.1 / 46.5 |
| Live (step 1), closing | 8.24 s | 27.86 s | 72.61 s | 45.1 / 46.6 |

Step 2 against live: 45.8k -12.9%, 115k -12.3%; against the build before this lead (31.2 / 81.3 s): -22%. No arm
declined a grouped product or copied experts in. The decodes give the same text on every arm.

## Soak and promotion of step 2 (2026-11-16)

The same soak on the step 2 build, mode 1 ([`soak-requests-iq2s.jsonl`](soak-requests-iq2s.jsonl)):

| Request | 1536 soak (old build) | Step 1 soak | Step 2 soak |
|---|---:|---:|---:|
| 115k first read | 82.8 s | 74.6 s | 65.1 s |
| 31k conversation switch | 22.5 s | 20.2 s | 17.7 s |
| Repeated 115k edits | 0.51 s | 0.53 s | 0.55 s |
| Return to the long conversation | 0.52 s | 0.53 s | 0.55 s |
| Short switch | 0.31 s | 0.33 s | 0.33 s |

Medians. 65 cycles, 535 requests, no errors and no driver crash; lowest free RAM 73.3 GiB. Every repeated request
type gave one answer across all cycles, as in the step 1 soak; 6 of the 65 straight-after-switch edits stopped
before 64 tokens (42-61). The cached-request times move by 10-20 ms, within the spread between the earlier soaks.

Promoted: the engine config's `exe` now points at the step 2 build (`1a628932...`, [`promote_iq2s.py`](promote_iq2s.py)),
mode 1. After promotion, through the proxy: a short arithmetic prompt answered correctly; cold 45.8k reads took
26.0 s (first prompt after loading) and 24.2 s.

## Setup

4x Arc Pro B70, Windows 11, driver 32.0.101.9175, oneAPI 2026.0 JIT. Executable before this lead `2c21539a...`;
step 1 `7112581d...`; step 2 `1a628932...` (live). GLM unloaded for the runs and reloaded afterwards (it answered).
Each promotion kept a backup of the engine config.
