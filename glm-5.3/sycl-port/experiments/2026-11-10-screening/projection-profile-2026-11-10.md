# GLM projection profiling — 2026-11-10

Decision: park the per-head GEMM rewrite as the first substantial kernel project for now. Its spans are small on this workload. This is a screening result, not a rigorous proof of the maximum possible end-to-end gain: the four GPUs overlap, markers and per-half collection perturb scheduling, and only one prompt depth was profiled.

An isolated copy of sycl-raw4 added four S->mark calls around the query-absorption and MLA output projection GEMM loops; the existing STRATA_GLM_PREFILL_PROF gate controls them. The live binary/config were not changed. Copied tree <work>\experiments\codex-projection-20261110\tree; instrumented generate SHA-256 f29729566030d87364289135a3b4392d0ceb7c90bce8a7ee0cb8439b53e0a29c. The development link differed from production, so the profiler-off build was checked against the saved live baseline: both had exactly matching 64-row teacher-forced logits SHA-256 10ecc6721c715ed452758ebd18c7140bbe11352f17d2f77463b64f98da1f5e92 and single-run 8128-token prefill times 9.353 vs 9.336 seconds, respectively. This is not a complete equivalence proof.

Three profiler-on standalone runs used 128k context, chunk 768, default mixer sub-batch 512, CPU lane off, complete expert pools, the same fixed 8192-token input, 8128 prompt tokens plus 64 teacher-forced tokens. The three measured prompt wall times were 9.411, 9.289, and 9.372 seconds. A single profiler-off run took 9.353 seconds; overhead is within this small observed variation, not a well-estimated overhead bound. All profiling runs exited 0 and their logits matched the baseline byte-for-byte.

Per-card sum of qabs_gemm + out_gemm spans in milliseconds (three runs):

- GPU 0: 175.1, 180.7, 174.0
- GPU 1: 167.6, 159.2, 151.6
- GPU 2: 136.7, 127.9, 125.3
- GPU 3: 154.9, 150.4, 166.9

On GPU 1, the slowest logged pipeline stage, these spans were about 2.2–2.5% of its summed profiled stream time (6.66–6.73 seconds). Do not add percentages across cards: they run as a pipeline. Markers are barrier-to-barrier spans, including submission gaps and marker overhead, not pure kernel execution. Logs and full source diff are under the isolated experiment folder. A prior pf_prof.log ended with a crash and was not used.

The free OpenCode DeepSeek model reviewed the copied source read-only. Its observation that MKL and phase markers share F->cs was independently verified: the descriptor binds to F->cs, and this port's dpct queue defaults to in-order with profiling enabled in the relevant source. Some DeepSeek claims were unverified, including a suggestion of CPU fallback; do not treat those as facts.

L2 source finding: on the non-HIP SYCL path, warp_sum_lanes delegates to warp_sum and warp_max_lanes delegates to warp_max; L2 labels differing only in l/x select those identical source-level reductions. Do not duplicate an l/x sweep without evidence of different generated code. The remaining shape dimensions still require operator-level parity and model timing; no L2 variant has been benchmarked yet.

Zeus Qwen service was restored with swap health status OK after the GPU experiments. The previous promising 768 sub-batch candidate remains unapplied and requires a quality budget, 128k and image validation, residency evidence and soak, as documented in glm53-sycl-screen-2026-11-10.md.
