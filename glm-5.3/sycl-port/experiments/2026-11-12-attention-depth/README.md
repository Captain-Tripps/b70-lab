# Long-context attention and indexer depth screen — 2026-11-12

## Decision

On these single-prompt-family screens, the indexer's score and selection intervals grow materially with context; MLA attention is nearly flat. This makes DSA scoring/selection a more evidence-backed target than a new MLA kernel, but the overall production-MTP effect is modest and depends strongly on acceptance. The screening does not establish a reliable end-to-end ceiling or justify a kernel rewrite yet. The earlier [sx2b4 screen](../2026-11-10-screening/dsa-screen-2026-11-10.md) measured only +2.58% on one 103k MTP pair and had an unexplained continuation difference; do not promote or simply repeat it as a proven fix.

## Setup

Zeus, four B70s, promoted executable SHA-256 `f89820fe92e49ffa6e563b538d5dc5aebe9b246e95d29d523f3e76f0ed0acea8`, split `14,25,36`, 131072 maximum context, chunk 768, 128 greedy generated tokens, complete resident experts, CPU lane off, existing 12 GiB/eight-slot branch flags. A fixed local source was tokenized once and the 2048/32768/100000 token inputs were prefixes of it, not identical decode positions; [make_inputs.py](make_inputs.py) records the procedure and [run.ps1](run.ps1) checks input hashes and runs an isolated process. The prompt content and full raw logs stay on Zeus. Each arm used a fresh process; there was one profiler-off and one profiler-on sample per depth, in that order. The proxy was unloaded only after a 45-second quiet check. The runner watched for a model starting on the proxy and free RAM below 16 GiB; the promoted service was restored and health-checked between the MTP and target-only batches and again afterward.

Input SHA-256: 2048 `359bb29c58f1505af40dae1511f7290eaf40a09c053f6a03771d4765f0de73c3`; 32768 `16d3c24eaaa0ec5e5c79239a7a198cd65f20f0c04bc414837e41594ac3387008`; 100000 `c0300cba764e8905f4c5f5982fa29f2ff97e3922a44a9d16cbc603b4c48b6c26`. `STRATA_GLM_PROF=8` skips eight cold tokens and adds synchronization/timing markers; its stream intervals include gaps and are not directly additive or guaranteed critical-path times. Profiler-on rates are not clean production speed.

## Whole-model decode

| Input tokens | Mode | Profiler off | Profiler on | MTP acceptance |
| ---: | --- | ---: | ---: | ---: |
| 2048 | MTP | 22.99 ms/token (43.50 tok/s) | 25.16 ms/token | 110/126 (87.3%) |
| 32768 | MTP | 27.92 ms/token (35.82 tok/s) | 30.85 ms/token | 84/126 (66.7%) |
| 100000 | MTP | 24.22 ms/token (41.28 tok/s) | 26.17 ms/token | 118/126 (93.7%) |
| 2048 | target only | 37.06 ms/token (26.98 tok/s) | 43.68 ms/token | off |
| 100000 | target only | 40.84 ms/token (24.49 tok/s) | 48.27 ms/token | off |

All 128 token IDs matched between profiler-off and profiler-on at each depth/mode. Target-only and MTP also matched at 2048 and 100000. This narrow token check does not establish broad quality. The measured target-only 100k-to-2k difference is 3.78 ms/token, or 9.3% of the deep measurement. These are **observed gaps, not hard upper bounds**: different prefix lengths lead to different continuations and MTP acceptance, and depth-independent optimizations could also help.

Two further unprofiled MTP pairs used fresh processes in 2k/100k/100k/2k order. The three 2k runs were **22.99, 23.26, 22.93 ms/token** (mean 23.06); the three 100k runs were **24.22, 24.20, 24.49 ms/token** (mean 24.30). The 1.24 ms/token mean gap is 5.1% of the deep mean. All three outputs per depth matched their corresponding original hash and acceptance counts. These repeats use the same one prompt family and short 128-token output; the original samples were interleaved with profiler-on runs and preceded the target-only batch, so this is not a six-arm alternating controlled study. A wider corpus and longer continuations remain necessary.

## Profiled GPU-stream intervals

Representative CUDA0 values in milliseconds per profiled token:

| Depth and mode | `dsa_score` | `dsa_select` | `mla_attend` |
| --- | ---: | ---: | ---: |
| 2048 MTP | 0.056 | 0.134 | 1.146 |
| 32768 MTP | 0.315 | 0.209 | 1.148 |
| 100000 MTP | 0.864 | 0.390 | 1.147 |
| 2048 target only | 0.056 | 0.135 | 1.158 |
| 100000 target only | 0.867 | 0.389 | 1.151 |

The 100k-versus-2k score-plus-selection increase is about 1.06 ms per profiled CUDA0 stream token for both modes; CUDA2 is similar. Other cards differ in layer count. These are **not four independent savings to sum**, nor a direct prediction of real response speed. They show that scoring is the largest depth-sensitive measured stage in this sample, with selection smaller; MLA stays about flat. Because target-only and MTP stream structure and token accounting differ, the values don't imply a 1:1 change in wall time.

The next useful work is a targeted scoring/selection operator investigation with exact selected-pool IDs, ties and causal masks tested, and a realistic estimate of model-level upside. A new XMX scorer would change arithmetic and may change routing; the earlier sx2b4 result demonstrates why matching a synthetic score fixture is insufficient for full-model correctness. Keep the original path and production config as fallback; require the handoff's deep-workload gain and correctness gates before considering a change.
