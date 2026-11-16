# XMX DSA indexer for the prompt read (L5, prefill half) - 2026-11-16

## Decision

Live since 2026-11-16, after a clean 30-minute soak. An XMX version of the GLM indexer score, after the lightning
indexer of [llama.cpp#31313](https://github.com/ggml-org/llama.cpp/pull/31313), cuts a cold 115k read by 5.3% (three
pairs: -5.3, -5.4, -5.2%), a 32k read by 1-2%, and leaves an 8k read flat. Decode does not use it. Quality, over 511
teacher-forced positions: true-token loss 1.0851 -> 1.0826 on the 32k input and 0.5699 -> 0.5738 on the 115k, top
token as before at 490 and 499 of 512 positions. The shifts go both ways and are the size of the L12 change already
live. The engine config now runs the candidate executable with `STRATA_GLM_DSA_XMX=1`
([soak and promotion](#soak-and-promotion)).

The [prompt-read profile](../2026-11-16-prefill-profile/) put the indexer at 10-11% of the busiest cards' time on a
115k read and 3% on a 32k read; the gain matches that share with the score kernel about twice as fast.

## The kernel

The engine's SYCL port runs the indexer score (`dsa_score`: for each token and pooled key, the sum over 32 heads of
`relu(q . k) * w`, key size 128, one pooled key per 4 positions) on an FP32 register-tiled kernel; its CUDA
tensor-core version was never ported (a stub). [`patch_dsa.py`](patch_dsa.py) adds an XMX path behind
`STRATA_GLM_DSA_XMX=1`, modelled on the PR's XMX kernel but self-contained (the PR also moves the shared XMX code
out of `fused-gemm.cpp`, which would clash with the L12 fork):

- q is staged to f16 once a call, padded to whole 32-token blocks.
- A work-group of 4 sub-groups packs 64 pooled keys into shared memory as f16 pairs (the matrix units' packed B
  layout) once, and reuses them for every head and token block.
- Per head, each sub-group runs 16x16x16 f16 `joint_matrix` products for its 16 keys over two 16-token tiles, then
  adds `relu(dot) * w` into per-lane sums. 16x16x16 is the shape the PR measured fastest on B60.
- Work-groups whose keys no token can see yet are skipped, and only visible scores are written, as in the FP32
  kernel.

[`build_l5.py`](build_l5.py) builds it on the live tree (`1a628932...`): 0 compile errors, 0 unresolved symbols,
candidate `f72801f6...`. Unset, the candidate runs the FP32 kernel: its 32k loss (0.9915, 52 of 63) is the live
build's from the [L12 round-2 check](../2026-11-15-esimd-grouped-gemm/#round-2-an-iq2_s-format-for-gateup) (the
files were not compared byte for byte).

## Speed

[`ab_dsa.ps1`](ab_dsa.ps1): CLI reads with the live environment and prompt arguments, speculation off, the same
binary with the switch off (`c0`) and on (`c1`). Raw lines: [`results.txt`](results.txt).

| Input | Off | On | Change |
|---|---:|---:|---:|
| 115k, with 64-position logit dump | 61.90 s | 58.65 s | -5.3% |
| 115k, plain (on first, then off) | 64.02 s | 60.55 s | -5.4% |
| 115k, with 512-position logit dump | 61.56 s | 58.33 s | -5.2% |
| 32k, plain (on first, then off) | 18.44 s | 18.09 s | -1.9% |
| 32k, with 512-position logit dump | 18.02 s | 17.86 s | -0.9% |
| 8k code, with 64-position logit dump | 6.95 s | 6.98 s | flat |

The 32k pair with the 64-position dump (24.03 -> 20.03 s) is left out: it was the first run of the batch and its off
arm is 6 s slower than every other 32k read.

The gain grows with depth, as the indexer does. On the 115k read card 0 spends 32.31 -> 31.33 s on the first 64k
(-3.0%) and 26.47 -> 24.32 s on the remaining 49.5k (-8.1%).

## Quality

The teacher-forced check of the [1536-chunk change](../2026-11-13-prefill-chunk-1536/#logit-check): the engine reads
all but the last N tokens, forces those N and writes each position's full-vocabulary logits
([`nll_l5.py`](nll_l5.py)). The first check used 64 positions:

| Input | Off: loss | On: loss | True top-1 | Top token as off |
|---|---:|---:|---:|---:|
| 32k | 0.9915 | 1.0159 | 52 -> 52 / 63 | 61 / 64 |
| 8k code | 0.0001 | 0.0001 | 63 -> 63 / 63 | 64 / 64 |
| 115k | 0.2262 | 0.2311 | 60 -> 61 / 63 | 63 / 64 |

The 32k loss rose 2.5%, several times the shift of earlier changes, so the check was repeated over 512 positions
([`l5kl.cmd`](l5kl.cmd)):

| Input | Off: loss (first / second half) | On: loss (first / second half) | True top-1 | Top token as off |
|---|---:|---:|---:|---:|
| 32k | 1.0851 (0.697 / 1.472) | 1.0826 (0.681 / 1.483) | 392 -> 389 / 511 | 490 / 512 |
| 115k | 0.5699 (0.866 / 0.276) | 0.5738 (0.880 / 0.269) | 430 -> 432 / 511 | 499 / 512 |

Over 511 tokens the loss moves -0.2% and +0.7%, and the halves move in both directions by more than the totals: noise
at this sample size, not a trend. The 64-position 32k number was one of those swings. Top-token agreement (95.7% and
97.5%) is in the range of the L12 steps (60 and 62 of 64, 93.8% and 96.9%). The f16 operands change which pooled keys
make the top 2048 near the cut, and that is the whole effect.

## Soak and promotion

[`soak_l5.py`](soak_l5.py) is the [L12 soak](../2026-11-15-esimd-grouped-gemm/) with one change: the copied engine
config also sets `STRATA_GLM_DSA_XMX=1`. Same live config and server, candidate executable `f72801f6...`, port 9080,
the 2026-11-12 mixed request mix plus a long-conversation edit each cycle, 30 minutes. Raw rows:
[`soak-requests.jsonl`](soak-requests.jsonl).

| Request | n | Median first token, L12 soak | Median first token, L5 soak | Distinct answers |
|---|---:|---:|---:|---:|
| Cold 115k prime | 1 | 65.07 s | 61.44 s | 1 |
| Medium 31k switch | 22 | 17.66 s | 17.35 s | 1 |
| Long edits (115k, cached) | 198 | 0.548 s | 0.553 s | 3 (one per edit text) |
| Long return | 66 | 0.548 s | 0.532 s | 1 |
| Append | 66 | 0.683 s | 0.666 s | 1 |
| Short 7.7k switch | 66 | 0.327 s | 0.329 s | 1 |
| Straight edit (new text each cycle) | 66 | 0.942 s | 0.943 s | 65 |
| Extra | 32 | 5.140 s | 5.132 s | 2 |
| Cancel / retry | 13 / 13 | 1.056 / 0.053 s | 1.042 / 0.053 s | 1 / 1 |

543 requests over 66 cycles, every non-cancelled request returned its 64 tokens (the straight edits stop early on
some new texts, as in the L12 soak), each repeated request gave one answer throughout, no errors in the server log,
free RAM never below 73.5 GiB. Cached follow-ups are unchanged: they read only a few new tokens.

Promotion ([`promote_l5.py`](promote_l5.py)): the candidate copied to its own runtime folder, the config's `exe`
pointed at it and `STRATA_GLM_DSA_XMX=1` added to its environment, the old config kept as a backup beside it. The
proxy reloaded GLM on the first request (it answered 19 x 21 = 399) and the engine process runs the new executable.
Two cold 45.8k reads through the proxy: 30.56 s (first read after load) and 23.70 s, against 24.3 s on L12.

Rollback: restore the backup config and reload GLM.

## Next

The ESIMD tile-shape sweep for the grouped expert products (still 46-48% of the busiest cards' read time).

## Setup

4x Arc Pro B70, Windows 11, driver 32.0.101.9175, oneAPI 2026.0 JIT. GLM unloaded from the proxy after an idle check,
with Jon's OK, and reloaded afterwards (it answered). Expand `<work>` to the engine checkout, `<proxy>` to the proxy
and `<venv python>` to the server's Python.
