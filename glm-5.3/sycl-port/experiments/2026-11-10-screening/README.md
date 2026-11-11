# GLM Maya SYCL screens — 2026-11-10

These are **screening results**, not production changes. The live binary and config remained unchanged. The
measured setup used chunk 768, despite the stale 1024 in the earlier handoff and repository config.

- [Sub-batch comparison](sycl-screen-2026-11-10.md): a promising first-token improvement, with numerical,
  headroom, long-context and image gates still open.
- [Projection profile](projection-profile-2026-11-10.md): both per-head GEMM loops were measured; the result does
  not justify starting that rewrite yet. This is not a rigorous upper bound on every workload.
- [DSA score screen](dsa-screen-2026-11-10.md): synthetic operator parity, a warm-cache microbenchmark, and
  full-model checks at 33k and 103k. The tested setting did not meet the keep gate.

The `subbatch/` and `kernels/` directories contain the relevant text logs, timing records, configurations and
test scripts. `<work>` and `<USER>` replace local paths in these copies; expand them before using scripts.
Hashes in the reports identify the original, unredacted inputs and executables, not these path-redacted copies.
The 64-row logits files and fixed 8,192-token input are retained on the lab host rather than published; their
hashes and the numerical comparison are recorded. Raw model-output JSONL files contain the controlled benchmark
replies. The `sub768-repeat8k` cache-hit batch is explicitly excluded from the fresh-prefill comparison.

The profiler markers are in [projection-markers.patch](kernels/projection-markers.patch). The
[DSA fixture](kernels/dsa_variant_parity.cpp) exercises the translated kernel entry point directly; its timing
reuses the same buffers and cannot substitute for cold-cache or model-level measurements. The current fixture
and runner need paths and the generated SYCL build tree configured for the host.
