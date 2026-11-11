# Prefill sub-batch 768: additional correctness screen — 2026-11-10

**Decision: retain the live default of 512.** A fixed 32,768-token input produced four different top-token choices across 64 teacher-forced positions with sub-batch 768. The two baseline runs were bit-identical to each other, as were the two candidate runs; each cross-arm comparison reproduced the same four changed positions. This establishes a repeatable numerical difference for this input, not its impact on task quality. No quality budget was declared, so this setting remains unvalidated and was not promoted.

The earlier [screen](../2026-11-10-screening/sycl-screen-2026-11-10.md) found one changed position in a different 8k test and an approximately 4.6% fresh 8k TTFT reduction. This follow-up adds two different fixed 8k inputs and a 32k input. The 8k inputs are tokenizer source code and deterministic synthetic inventory records, not a representative quality corpus. The 32k input is from the same underlying source material as the earlier 8k input, not an independent long-context corpus.

| Input | Prefill / forced | Top-1 agreement | Mean KL (baseline to candidate) | Maximum KL |
|---|---:|---:|---:|---:|
| Code | 8,128 / 64 | 64/64 | 0.000006 | 0.000133 |
| Records | 8,128 / 64 | 64/64 | <0.000001 | 0.000009 |
| Long source | 32,704 / 64 | 60/64 | 0.013540 | 0.104683 |

KL is over the full 154,880-token vocabulary. All comparisons use finite float32 logits promoted to float64 for calculation. Changed 32k rows, zero-based: 47, 49, 51, 57. The [comparison](comparison.txt) also reports maximum absolute logit differences, including in low-probability vocabulary entries; those maxima alone do not measure quality. [Repeat comparison](repeat-comparison.txt) verifies both within-arm outputs were byte-identical.

The 32k prefill times were 28.094 and 28.211 s baseline, 26.859 and 26.854 s candidate. These sequential CLI runs have only two observations per arm and are not an interleaved serving benchmark. All eight runs exited 0; chunk logs show no CPU expert rows. Startup telemetry on card 3 reported 1,118,081,024 bytes free for baseline versus 1,019,514,880 for candidate; this snapshot is not a peak-memory measurement and does not clear the memory gate. The earlier serving screen observed 0.6 GB free on the tightest card after 33k prefill.

## Reproduction and limits

Four B70s, isolated `generate.exe`, the same model pack and runtime as the earlier screen, 131072 context, chunk 768, CPU lane off, resident skip on, reserve 400 MB, speculation off, 64 teacher-forced positions. Candidate sets `STRATA_GLM_PREFILL_SUB=768`; baseline leaves it unset. Runtime SHA-256 `497f1d4238a724eafbf056af33910e4e0d94e6b7571a33ae61187512b0ca7198`. [Input generator](make_inputs.py), [arm template](kl_arm.ps1), [runner](run_all.ps1), [repeat runner](run_repeat.ps1), and comparison scripts and logs are included. Expand `<work>` for the host and place the arm template at the path expected by the runners. The generated token files and 38 MB-per-arm logits remain on the lab host; source/tokenizer versions and hashes below identify inputs, rather than claiming this record alone is self-contained.

- `code.txt`: 8,192 tokens, SHA-256 `eea769490b499d41256840b2f0609f54c39617305a2989f79a7d2c18a3234c8d`, generated from local Maya `tools/strata_tokenizer.py`, source SHA-256 `6c8af275940f0af6c350f2f316e9249305f5cb92bc2fe9c83bf1ae13ff55f464`.
- `records.txt`: 8,192 tokens, SHA-256 `b83e382133a5a4039a209cd8968fcf9b903b35f825b44b1bf596c5270d1d9243`; deterministic generator in this directory.
- `long32k.txt`: 32,768 tokens, SHA-256 `7d1dff11bc0e91bd87bb58b5dfccd7fc78db8185b59352a955f8a3f07c86a56b`; existing lab-host token file.

No 100k/128k, image, retrieval, tool-use or soak gate was run. The repeated numerical difference should be investigated or assessed against a declared quality budget before spending resources on promotion tests. The live runtime and configuration were not changed.
