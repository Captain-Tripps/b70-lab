# Source audit — PASS for research scope

Inspected 2026-10-27T02:04:49Z through the connected GitHub tools.

Snapshots: Strata 4b9e05a2a806a3fe24f7b2560d98626c37dade35; b70-lab a9e900053adc73bda351f268488318694ac49754.

- Verified upstream Intel exclusion for V4.1 and separate CUDA/BLAS DeepSeek execution.
- Checked planner constants against the DeepSeek guide; preserved decimal GB versus GiB distinction.
- Corrected the earlier generic assessment: this lab already has a native Windows Strata Qwen port.
- Inspected patch 0001 Windows compiler/I/O changes and patch 0002 shared-context host allocation.
  Their old hotschmoe base is not the v0.2.6 DeepSeek engine; adaptation is planned, not claimed complete.
- Reconciled README's 112 GB, hardware notes' 95.9 GB and user's current 128 GB report as a mandatory fresh inventory.
- Kept V4 0731 profiler rejection separate from the new V4.1 route. Did not extrapolate throughput.
- Retained the 2026-10-24/25 correction: shared context alone does not fix the Windows v2 barrier abort.
- Checked benchmark lifecycle documentation: llama-server identity rules need engine-aware adaptation.
- Inspected MIT licenses for both repositories; no third-party implementation copied in this change.
- All hardware, compilation, numerical parity, runtime and throughput checks remain NOT_RUN.

Result: source-supported planning handoff, not verified implementation readiness or a benchmark result.

## Hosted-agent planning update (2026-10-27T03:14:40Z)

- Inspected OpenClaw OpenRouter integration and exec docs, and the exact OpenRouter 1017 snapshot listing.
- Verified documented model-reference syntax and tool/reasoning support. Kept exact installed-route
  compatibility, provider selection and native Windows dispatch as CHECK-100, NOT_RUN.
- Older DeepSeek V4 replay special cases do not establish 1017 compatibility. The starter includes a real
  multi-turn fixture test and fresh-session resume rather than assuming integration from catalog metadata.
- Source licenses for the new documentation references were not audited; no implementation was copied.
- No live API usage, secret configuration, Windows runner implementation or GPU test occurred.

Result: PASS for documented planning claims only. No coding-ability ranking or price guarantee is asserted.
