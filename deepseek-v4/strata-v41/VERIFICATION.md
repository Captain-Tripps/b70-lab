# Verification status

This is a **research-only planning handoff**. No DeepSeek V4.1 Intel binary was built, no model was loaded,
and no GPU benchmark was run. The current implementation is unchanged.

The source audit checked pinned upstream and lab documents/code and recorded contradictions. Hardware and
implementation checks CHECK-101 through CHECK-108 are future gates, all NOT_RUN. Publishing the plan does
not mean those gates passed. See [PLAN.md](PLAN.md) for owners, dependencies and acceptance criteria.

The research helper validates ledger structure and traceability; it does not validate the hardware or truth
of unmeasured performance estimates. Any future implementation should resume at STEP-001 and recheck sources.

## Ledger: checks

<!-- rfb:checks:start -->
| ID | Criterion | Result | Method | Evidence | Tested snapshot |
| --- | --- | --- | --- | --- | --- |
| CHECK-001 | Audit core claims and reconcile existing Windows support, hardware conflicts and V4/V4.1 scope against pinned sources. | PASS | SOURCE_AUDIT | [output](checks/SOURCE_AUDIT.md) | Strata 4b9e05a2a806a3fe24f7b2560d98626c37dade35; b70-lab a9e900053adc73bda351f268488318694ac49754 |
| CHECK-101 | Manifest reconciles reported versus historical RAM/CPU and records hardware health and exact runtime identities. | NOT_RUN | MANUAL | — | — |
| CHECK-102 | Three fresh four-device probe runs pass exact transfer checksums without timeout/device loss; bounded &gt;4 GiB tests included. | NOT_RUN | MANUAL | — | — |
| CHECK-103 | Required quant/attention/routing fixtures and same-pack real-layer/logit reference comparisons pass frozen tolerances. | NOT_RUN | MANUAL | — | — |
| CHECK-104 | Complete 2.00-bit model passes three cold starts, mixed expert routing and multi-token parity within measured memory budgets. | NOT_RUN | MANUAL | — | — |
| CHECK-105 | Ownership mocks, serving checks, 300-second idle/resume and two-hour soak pass without affecting production stand-ins. | NOT_RUN | MANUAL | — | — |
| CHECK-106 | Reproducible correctness-qualified A/B results record variance, memory and latency; no unmeasured throughput promise. | NOT_RUN | MANUAL | — | — |
| CHECK-107 | Clean-directory build/launch is reproducible from pinned sources and manifests with rollback instructions. | NOT_RUN | MANUAL | — | — |
| CHECK-108 | Final implementation diff excludes rejected/deferred complexity unless a new decision and gate explicitly qualifies it. | NOT_RUN | DIFF_REVIEW | — | — |
<!-- rfb:checks:end -->
