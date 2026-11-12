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

Nsight Systems produced raw traces but could not import them because the importer was unavailable; Nsight Compute performance counters were admin-restricted. No profiler conclusions are claimed. The next gate is an isolated two-GPU server A/B using identical requests and speculative settings, followed by output/quality and soak checks. The modified library is an experimental artifact, not a deployment recommendation.
