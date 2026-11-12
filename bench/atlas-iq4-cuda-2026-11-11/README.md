# Atlas CUDA IQ4 investigation — 2026-11-11

**Finding: a two-warp IQ4_NL four-column launch is faster in isolated CUDA operator tests; whole-model impact and correctness are unmeasured.** The running Qwen server was not modified or restarted.

Atlas has two RTX 3060 12 GiB GPUs. The running llama.cpp CUDA build is based on `cd959ba` and serves a mixed-quant Qwen3.8 27B GGUF. Its header contains six IQ4_NL tensors: two FFN down matrices `(K=17408, M=5120)`, three FFN gate/up matrices `(K=5120, M=17408)`, and one attention QKV matrix `(K=5120, M=10240)`. It also contains 61 IQ4_XS tensors. Four columns are relevant to a speculative-decoding candidate but the server's actual runtime shapes and frequency have not been established.

## Experiment

The isolated [variant builder](build_variant.py) copies `mmvq.cu`, changes the generic CUDA MMVQ launch from four warps to two **only for IQ4_NL and four output columns**, compiles that single object and relinks a separate CUDA shared library against the existing build's objects. The benchmark loads either that library or the original in a separate process. No installed binaries or production sources were altered. This changes reduction order, not quantization or weight layout.

The [fixture](shape_bench.cpp) uses deterministic synthetic quantized weights and inputs, four warmups, 100 graph submissions per case, and a CPU GGML reference. Timings include graph submission and synchronization, not just a profiler-isolated kernel. Each arm was run four times in ABBA/ABBA order on GPU 0. All results passed the fixture's CPU-reference NMSE threshold of `5e-4` (observed around `9.3e-8` or less). That threshold is a screen, not a full-model quality test. Measurements were guarded against the loaded Qwen server becoming active, although polling cannot prevent every possible transient overlap.

| M × K, N=4 | Original mean µs | Two-warp mean µs | Reduction |
|---|---:|---:|---:|
| 5120 × 17408 | 250.66 | 161.32 | 35.6% |
| 17408 × 5120 | 170.59 | 157.49 | 7.7% |
| 10240 × 5120 | 102.50 | 95.49 | 6.8% |

Half-sized synthetic shapes intended to explore possible two-GPU partition effects also improved: 2560 × 17408, 110.07 → 84.61 µs; 8704 × 5120, 87.96 → 82.22 µs; 5120 × 5120, 53.81 → 51.21 µs. These are not verified to match the server's actual tensor-split graph. Results and test runners: [full FFN shapes](compare.jsonl), [attention shape](compare-attention.jsonl), [half-sized shapes](compare-shards.jsonl), [runner](compare_variant.py). Paths in scripts use `<atlas-home>` placeholders and must be adapted for reproduction. The small comparison logs are omitted because later shape runs reused some filenames; JSONL retains the validated results.

## Context and limits

An initial [baseline sweep](screen.jsonl) and [actual-shape screen](shapes.jsonl) compared IQ4_NL, IQ4_XS and other formats. On the synthetic full-size FFN case at N=4, IQ4_NL was notably slower than IQ4_XS; the two-warp result identifies launch configuration as a useful lead, not a complete explanation. Source inspection shows distinct block sizes, decode paths and per-column work. It does not establish compiler reuse or actual dispatch without a usable trace.

For the PR's 4096 × 14336 batch-one shape, Atlas IQ4_NL and IQ4_XS averaged about 101 and 95 µs respectively. Dividing the logical compressed weight bytes by elapsed time gives roughly 326–328 GB/s versus a nominal device specification near 360 GB/s; this is an indicative ratio, **not** a measured DRAM bandwidth or hard speedup limit. The B70 SYCL reorder result does not transfer to CUDA. No reordered weights were tested here.

Nsight Systems produced raw traces but could not import them because the importer was unavailable; Nsight Compute performance counters were admin-restricted. No profiler conclusions are claimed. The modified library is an experimental artifact, not a deployment recommendation.

## Two-GPU server A/B

A preliminary live-configuration comparison used the same 98,304-token context, tensor split, `ngram-mod,draft-mtp`, and three-token maximum draft as Atlas's Qwen service. The original proxy server and an isolated variant server each received the same synthetic 784-token prompt four times, generating 160 tokens at temperature zero with prompt caching disabled. The first request was treated as warmup. The server variant's library search path resolves to the isolated two-warp library (`ldd` checked); the server process's loaded library map was not independently captured. [Request runner](server_sample.py), [orchestrator](server_ab.py), [measurements](server-controlled-retry.jsonl). Paths need adaptation.

Across the three post-warmup requests, aggregate generated-token throughput was **66.3 tokens/s original versus 60.8 tokens/s variant**. Individual original rates were 46.5, 66.8 and 110.8 tokens/s; variant rates were 53.1, 49.4 and 94.5 tokens/s. These figures are **inconclusive**, not evidence of a regression: output hashes and draft acceptance differed, so the requests did not perform equivalent work. The identical-output first requests were 66.6 versus 66.1 tokens/s, but are single warmup observations. Prompt processing averaged 1281 versus 1269 ms over the post-warmups, also insufficient to infer a gain. No output-quality or soak test was performed. The planned post-variant baseline was skipped because the restored Qwen server began serving another request. The original proxy-managed server was restored; the variant was not deployed.

During the first restore, the 17 GiB model took approximately eight minutes to load. A four-second process sample attributed about 25.8 MB/s of reads to `llama-server`; concurrent `iostat` reported NVMe utilization around 99% and negligible writes. Composite NVMe temperature was 45°C (a second sensor read 62°C), PCIe link was 16 GT/s ×4, and the kernel journal showed no recent error-level entries. The model load caused the observed read pressure; the reason for the low read rate remains undetermined. A subsequent reload with a warm cache was much faster.

Before considering deployment, repeat with controlled draft behavior and matching generated tokens or teacher-forced verification, capture the actual loaded library and dispatched graph, and measure enough independent prompts. Respect active proxy requests and record a post-variant baseline.

## Retest with idle Atlas

After OpenClaw was paused, the Qwen slot was idle and a one-second `iostat` sample showed approximately 1.4% NVMe utilization before the test. We repeated the real server configuration in original → variant → original order, with one warmup and six distinct synthetic prompts per arm. Each asked for 192 tokens, temperature zero, prompt caching off. The variant server's `/proc/<pid>/maps` confirmed that the experimental CUDA library was actually loaded. The restored original completed the final baseline with no competing request. [Measurements](server-controlled-v2.jsonl), [runner](server_ab_v2.py), [prompt harness](server_sample_v2.py).

| Arm | Generated tokens | Aggregate generation rate |
|---|---:|---:|
| Original before | 1,152 | 56.78 tokens/s |
| Two-warp variant | 1,152 | 58.70 tokens/s |
| Original after | 1,152 | 56.91 tokens/s |

The baseline output hashes and draft counts matched across all six prompts, supporting a stable before/after comparison. **However, only two of the six variant outputs matched the original**, and draft counts also changed. Thus the 3.3% aggregate increase versus the midpoint of the baselines is an observed workload result, not a clean estimate of the kernel's speedup. For the two prompts with matching output hashes, aggregate rates were 54.29, 55.38 and 54.30 tokens/s respectively (about 2.0% higher for the variant), but draft counts differed slightly and two prompts are too few to establish a reliable gain. Temperature zero does not guarantee bit-identical output when floating-point reductions change. The test does not establish quality or production safety, and kernel dispatch was not captured. Qwen was restored to its original library and was idle at the final check; NVMe utilization was about 0.3% in a one-second sample.
