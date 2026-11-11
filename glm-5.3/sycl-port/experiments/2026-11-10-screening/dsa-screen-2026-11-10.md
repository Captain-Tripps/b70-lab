# GLM DSA score variant screening — 2026-11-10

The source-level projection profile and setup are documented in glm53-projection-profile-2026-11-10.md. OpenCode's free DeepSeek model reviewed the decode variants read-only. Relevant findings were independently checked: the shape setting is parsed once per process, and l/x labels use the same source-level reduction in the non-HIP SYCL branch. No production changes were made.

## Operator parity and warm-cache microbenchmark

A new model-free SYCL fixture, dsa_variant_parity.cpp in the experiment tree, calls the real dsa_score entry point at 32 heads x 128 dimensions. It covers pool counts 1, 7, 8, 9, 15, 16, 17, 511, 7130, 28523 and 32599, validates finite values and 32 guard floats, and checks a one-pool CPU reference. Each setting runs in its own process and verifies the dispatch log. The original and sx1b4, sx2b4, rx1b4, rx2b4 yielded byte-identical 68,836 score floats, SHA-256 d80430f13ff5d9ec236b53a72118de124daeac3a6f2f336ae3c63c76c684eb91. This is one deterministic fixture, not exhaustive parity or end-to-end quality.

Each timing below is the median of seven event-timed batches of 16 calls after warmup. Buffers are reused, so this is a warm-cache operator screen, not cold-cache inference and not a model speedup.

| Label | 7,130 pools | 28,523 pools | 32,599 pools |
| --- | ---: | ---: | ---: |
| original | 83.64 us | 310.41 us | 356.99 us |
| sx2b4 | 70.82 us | 223.82 us | 267.54 us |
| rx2b4 | 75.76 us | 230.27 us | 257.70 us |

## Model comparison

Unmodified production runtime SHA-256 497f1d4238a724eafbf056af33910e4e0d94e6b7571a33ae61187512b0ca7198, context 131072, chunk 768, normal MTP. Candidate only adds STRATA_GLM_DSA_SCORE2=sx2b4. Actual dispatch on all four cards was confirmed in logs. Fixed prompts contain repeated sbench.py source; thinking off, temperature zero, 768 output tokens each. Three matched 33,104-token inputs: candidate 40.75, 40.21, 42.00 tok/s vs control 40.39, 40.10, 41.80 tok/s; candidate mean 40.99 vs 40.76 tok/s (about +0.55%). All three complete output texts and MTP accepted/proposed counts matched. Three closing controls only; no opening control and only one prompt family. Below the 3% keep threshold; do not promote on this evidence. Basic answer checks also matched.

Raw source, logs, binaries, timing data and configs: Zeus <work>\experiments\codex-projection-20261110. The model-free test binary and timing harness are isolated experiment artifacts, not a production build.

## 103k-context single-pair screen

On 103,497 prompt tokens with 768 generated tokens, the single original control measured 37.289 tok/s and candidate sx2b4 38.250 tok/s (+2.58%); first-token times were 91.319 s and 91.677 s respectively. The original was measured first and the candidate second, each in a fresh server. This is only one pair, on one repetitive prompt family, and falls below the handoff's 8% deep-workload threshold. It is not a validated model win. The two continuation texts differed; MTP acceptance was 622/766 vs 621/766. The reason for divergence was not determined; the model-free exact score fixture does not establish full-model parity on real inputs. All four devices logged the expected sx2b4 dispatch. Do not promote the setting on this evidence.
