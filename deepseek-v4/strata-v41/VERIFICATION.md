# Verification status

This is a **research-only planning handoff**. No DeepSeek V4.1 Intel binary was built, no model was loaded,
and no GPU benchmark was run. The current implementation is unchanged.

> **Update 2026-10-27 (session 3) — the sentence above is no longer accurate for that session.**
> A 233 GB pack *was* downloaded and loaded, and four-GPU benchmarks *were* run — but in a
> **llama.cpp SYCL fork**, not in the Strata engine this plan describes, and in violation of the
> first-session boundaries at [PLAN.md](PLAN.md) line 252. The original statement is retained
> above as history rather than deleted. Details, measurements, the corrected false premise that
> caused the divergence, and the production-config rollback are in
> [FINDINGS.md "SESSION 3 — ROUTE DIVERGENCE"](../../work/strata-v41-agent-runner/FINDINGS.md)
> and `session_3_divergence` in
> [TASK-STATE.json](../../work/strata-v41-agent-runner/TASK-STATE.json).
>
> **No gate changed.** CHECK-102 through CHECK-108 remain NOT_RUN: no four-device probe, no
> quant/attention fixture, no same-pack reference-logit comparison, and no Strata engine was run.
> The session-3 measurements are llama.cpp-side, single-sample, unqualified evidence — input to
> route assessment, not a passed gate. `run.json` still records `stage: PREBUILD_CHECKED`.

> **Manual consistency review (2026-10-27).** The local research helper was **not available** in
> this environment, so it was **not run** and its validation is **not claimed** here. The ledger
> tables below were reviewed by hand and left unchanged; no rows were added, weakened or removed.
> Per [OPENCLAW-START.md](OPENCLAW-START.md), a manual review is recorded rather than a claimed
> helper pass.

The source audit checked pinned upstream and lab documents/code and recorded contradictions. Hardware and
implementation checks CHECK-102 through CHECK-108 are future gates and remain NOT_RUN. CHECK-100 and CHECK-101
are PARTIAL as of the STEP-000 session recorded in [work/strata-v41-agent-runner](../../work/strata-v41-agent-runner/TASK-STATE.json).
Publishing the plan does
not mean those gates passed. See [PLAN.md](PLAN.md) for owners, dependencies and acceptance criteria.

The research helper validates ledger structure and traceability; it does not validate the hardware or truth
of unmeasured performance estimates. Any future implementation should resume at STEP-000 and recheck sources.

## Ledger: checks

<!-- rfb:checks:start -->
| ID | Criterion | Result | Method | Evidence | Tested snapshot |
| --- | --- | --- | --- | --- | --- |
| CHECK-001 | Audit core claims and reconcile existing Windows support, hardware conflicts and V4/V4.1 scope against pinned sources. Audit hosted-agent interfaces separately from untested runtime integration. | PASS | SOURCE_AUDIT | [output](checks/SOURCE_AUDIT.md) | Strata 4b9e05a2a806a3fe24f7b2560d98626c37dade35; b70-lab a9e900053adc73bda351f268488318694ac49754; OpenClaw/OpenRouter live documentation inspected 2026-10-26 America/Chicago |
| CHECK-100 | Real tool rounds, failing-fixture repair, native Windows runner mocks, ownership/timeout/lock tests and fresh-session resume pass with saved receipts. | PARTIAL | MANUAL | Runner + lock + tool-loop: 11/11 CPU-only cases PASS on native Windows (GPU-BOX, PowerShell 5.1.26100.9711) — [suite](../../work/strata-v41-agent-runner/receipts/windows-mock-suite.json), [tool loop](../../work/strata-v41-agent-runner/receipts/tool-loop.json). Fresh-session resume: NOT_RUN. | b70-lab 881c608 + work/strata-v41-agent-runner |
| CHECK-101 | Manifest reconciles reported versus historical RAM/CPU and records hardware health and exact runtime identities. | PARTIAL | MANUAL | RAM reconciled: 6x16 GiB = 95.87 GiB installed (128 GB is board capacity); WHEA Id 22 still firing 2026-10-25; 4x B70 driver 32.0.101.8976. Compiler/L0/UR versions, Strata checkout, 1c360526 and PCIe links still unknown — [manifest](../../work/strata-v41-agent-runner/machine-manifest.json). | GPU-BOX inventory 2026-10-27 |
| CHECK-102 | Three fresh four-device probe runs pass exact transfer checksums without timeout/device loss; bounded &gt;4 GiB tests included. | NOT_RUN | MANUAL | — | — |
| CHECK-103 | Required quant/attention/routing fixtures and same-pack real-layer/logit reference comparisons pass frozen tolerances. | NOT_RUN | MANUAL | — | — |
| CHECK-104 | Complete 2.00-bit model passes three cold starts, mixed expert routing and multi-token parity within measured memory budgets. | NOT_RUN | MANUAL | — | — |
| CHECK-105 | Ownership mocks, serving checks, 300-second idle/resume and two-hour soak pass without affecting production stand-ins. | NOT_RUN | MANUAL | — | — |
| CHECK-106 | Reproducible correctness-qualified A/B results record variance, memory and latency; no unmeasured throughput promise. | NOT_RUN | MANUAL | — | — |
| CHECK-107 | Clean-directory build/launch is reproducible from pinned sources and manifests with rollback instructions. | NOT_RUN | MANUAL | — | — |
| CHECK-108 | Final implementation diff excludes rejected/deferred complexity unless a new decision and gate explicitly qualifies it. | NOT_RUN | DIFF_REVIEW | — | — |
<!-- rfb:checks:end -->
