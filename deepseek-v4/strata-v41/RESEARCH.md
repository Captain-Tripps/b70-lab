# Research: native Windows Strata DeepSeek V4.1

Prepared 2026-10-26. [Action plan](PLAN.md) is the entry point.

The user wants the Strata V4.1 capability on the existing Windows four-B70 workstation. This repository already
contains the Windows Qwen port and useful failure evidence; the action plan must build on that work.

## Comparison

| Reference mechanism | Applicability | Difference / decision |
|---|---|---|
| Upstream V4.1 CPU expert tier, Engram reader, model pack and server | Preserve model semantics and data flow | GPU code is CUDA/HIP; port required (EV-001, EV-003) |
| Lab Windows Qwen Strata JIT build and shared-context host memory | Reuse build/allocation patterns | Old fork and two-card Qwen evidence; revalidate four-card V4.1 (EV-004) |
| Existing V4 0731 layer split and expert-parallel rejection | Simpler baseline and useful counterexample | Old model's ceiling is not a V4.1 prediction (EV-006) |
| Lab driver/hardware/lifecycle notes | Turn known failures into first-class gates | Version-specific evidence, not current health certification (EV-005, EV-007, EV-008) |

## Rejected and deferred

Reject full-model FP16 expansion and treating automatic CUDA translation/emulation as completed support.
Defer tensor/expert parallelism, AOT, graph capture, per-card launch threads and speculative execution until
this model has its own correctness-qualified profile. Keep the earlier V4 expert-only rejection intact.

## Unknowns and corrections

Current usable RAM, hardware health, PCIe links and driver versions are unmeasured. The current user reports
128 GB, but historical notes include 112 GB and 95.9 GB with WHEA memory errors. No original hardware entry is
rewritten as if verified. The full Engram table need not fit host RAM and may remain I/O-sensitive.

Earlier analysis overstated Windows groundwork because it had not inspected this lab. It also treated an
ordinary peer-access probe as future discovery; existing negative results and working host staging are now
starting evidence, subject to version-specific retest.

## Rights and reuse

Both root licenses were inspected (MIT). This change adds documentation and a ledger only. Future patches
must retain upstream notices, inspect transitive dependency terms, and check model redistribution rights.

## Source audit

[Recorded manual source audit](checks/SOURCE_AUDIT.md) passed for these planning claims. Runtime acceptance
checks have not run. Generated tables below come from evidence.json.

## Ledger: references

<!-- rfb:references:start -->
| ID | Reference | Why relevant | Mismatch | License / reuse |
| --- | --- | --- | --- | --- |
| REF-001 | [https://github.com/Niko1221/Strata](https://github.com/Niko1221/Strata) | Separate V4.1 engine, packing, memory planning and existing SYCL migration mechanisms. | Released DeepSeek engine lacks Intel support; upstream Intel route is Linux and Qwen-focused. | INSPECTED · MIT · PATTERN_ONLY |
| REF-002 | [https://github.com/Captain-Tripps/b70-lab](https://github.com/Captain-Tripps/b70-lab) | Same machine's Windows port, probes, benchmarks and rejected strategies. | Existing working Strata model is Qwen; DeepSeek measurements concern V4 0731 and older driver/hardware states. | INSPECTED · MIT · PATTERN_ONLY |
<!-- rfb:references:end -->

## Ledger: sources

<!-- rfb:sources:start -->
| ID / note | Primary source | Locator | Inspection |
| --- | --- | --- | --- |
| [SRC-001](sources/SRC-001.md) | [original](https://github.com/Niko1221/Strata/blob/4b9e05a2a806a3fe24f7b2560d98626c37dade35/docs/INTEL.md) | 4b9e05a2a806a3fe24f7b2560d98626c37dade35 · docs/INTEL.md · Opening scope statement | INSPECTED |
| [SRC-002](sources/SRC-002.md) | [original](https://github.com/Niko1221/Strata/blob/4b9e05a2a806a3fe24f7b2560d98626c37dade35/strata_control/dsv41_fit.py) | 4b9e05a2a806a3fe24f7b2560d98626c37dade35 · strata_control/dsv41_fit.py · ISTA_SETS, ISTA_ENGRAM_BYTES, ISTA_DSPARK_BYTES | INSPECTED |
| [SRC-003](sources/SRC-003.md) | [original](https://github.com/Niko1221/Strata/blob/4b9e05a2a806a3fe24f7b2560d98626c37dade35/src/dsv41/ds4_model.cu) | 4b9e05a2a806a3fe24f7b2560d98626c37dade35 · src/dsv41/ds4_model.cu · copy_experts, cpu_lane_fits_ram, store_gb, cuBLAS and CUDA calls | INSPECTED |
| [SRC-004](sources/SRC-004.md) | [original](https://github.com/Captain-Tripps/b70-lab/blob/a9e900053adc73bda351f268488318694ac49754/strata-windows-port/README.md) | a9e900053adc73bda351f268488318694ac49754 · strata-windows-port/README.md · Base, Windows / Level Zero findings, AOT miscompile | INSPECTED |
| [SRC-005](sources/SRC-005.md) | [original](https://github.com/Captain-Tripps/b70-lab/blob/a9e900053adc73bda351f268488318694ac49754/hardware-and-windows-notes.md) | a9e900053adc73bda351f268488318694ac49754 · hardware-and-windows-notes.md · WHEA, memory demotion, building on Windows | INSPECTED |
| [SRC-006](sources/SRC-006.md) | [original](https://github.com/Captain-Tripps/b70-lab/blob/a9e900053adc73bda351f268488318694ac49754/deepseek-v4/PLAN-expert-parallel.md) | a9e900053adc73bda351f268488318694ac49754 · deepseek-v4/PLAN-expert-parallel.md · A0 result; Track B | INSPECTED |
| [SRC-007](sources/SRC-007.md) | [original](https://github.com/Captain-Tripps/b70-lab/blob/a9e900053adc73bda351f268488318694ac49754/llama.cpp-sycl/TENSOR-SPLIT-DECODE.md) | a9e900053adc73bda351f268488318694ac49754 · llama.cpp-sycl/TENSOR-SPLIT-DECODE.md · Shared context attempt and review notes dated 2026-10-24/25 | INSPECTED |
| [SRC-008](sources/SRC-008.md) | [original](https://github.com/Captain-Tripps/b70-lab/blob/a9e900053adc73bda351f268488318694ac49754/bench/README.md) | a9e900053adc73bda351f268488318694ac49754 · bench/README.md · arm.ps1 lifecycle and ownership rules | INSPECTED |
| [SRC-009](sources/SRC-009.md) | [original](https://github.com/Niko1221/Strata/blob/4b9e05a2a806a3fe24f7b2560d98626c37dade35/src/dsv41/ds4_os.hpp) | 4b9e05a2a806a3fe24f7b2560d98626c37dade35 · src/dsv41/ds4_os.hpp · _WIN32 branches, read/mapping/allocation functions | INSPECTED |
| [SRC-010](sources/SRC-010.md) | [original](https://github.com/Niko1221/Strata/blob/4b9e05a2a806a3fe24f7b2560d98626c37dade35/docs/DEEPSEEK41.md) | 4b9e05a2a806a3fe24f7b2560d98626c37dade35 · docs/DEEPSEEK41.md · Official sets; setup; DSpark handling | INSPECTED |
<!-- rfb:sources:end -->

## Ledger: evidence

<!-- rfb:evidence:start -->
| ID | Claim | Class | Sources / premises | Scope |
| --- | --- | --- | --- | --- |
| EV-001 | Upstream v0.2.6 Intel docs explicitly exclude DeepSeek V4.1. | VERIFIED · documented | [SRC-001](sources/SRC-001.md) | Pinned upstream release. |
| EV-002 | The two target sets have 132.07/149.06 decimal GB of experts and share a 110.60 GB Engram table. | VERIFIED · implementation | [SRC-002](sources/SRC-002.md) | Constants in upstream fit planner. |
| EV-003 | The separate DeepSeek engine contains CUDA/cuBLAS orchestration and existing Windows host I/O branches. | VERIFIED · implementation | [SRC-003](sources/SRC-003.md), [SRC-009](sources/SRC-009.md) | Inspected execution/OS source. |
| EV-004 | The lab documents an existing native Windows Qwen Strata port and shared-context host exchange with JIT correctness evidence. | VERIFIED · documented | [SRC-004](sources/SRC-004.md) | Historical two-card Qwen results. |
| EV-005 | Lab notes record reduced usable RAM, WHEA boot errors, WDDM demotion and a no-AVX512 host. | VERIFIED · documented | [SRC-005](sources/SRC-005.md) | Historical lab notes. |
| EV-006 | V4 0731 expert-only parallelism was rejected in the lab; its older V4.1 route waited on llama.cpp. | VERIFIED · documented | [SRC-006](sources/SRC-006.md) | Historical strategy and profiler results. |
| EV-007 | Shared context alone did not make Windows v2 barrier exchange safe; per-card submission threads failed in serving tests. | VERIFIED · documented | [SRC-007](sources/SRC-007.md) | Dated lab tests on other workloads. |
| EV-008 | The documented benchmark lifecycle currently identifies llama-server, requiring adaptation for a Strata V4.1 wrapper. | VERIFIED · documented | [SRC-008](sources/SRC-008.md) | Harness documentation. |
| EV-009 | The compressed models plausibly fit GPU plus host tiers, but not necessarily with the entire Engram table cached. | INFERENCE | [SRC-002](sources/SRC-002.md), [SRC-005](sources/SRC-005.md), EV-002, EV-005, REQ-002 | Illustrative 110-120 GB GPU-expert budget; user-reported 128 GB host RAM. |
| EV-010 | V4.1's no-drafter baseline needs allocation verification; --dspark off is not proof of unloaded draft weights. | VERIFIED · documented | [SRC-010](sources/SRC-010.md) | Upstream setup/model notes. |
<!-- rfb:evidence:end -->

## Ledger: decisions

<!-- rfb:decisions:start -->
| ID | Choice | Outcome | Evidence | Reason / complexity | Revisit |
| --- | --- | --- | --- | --- | --- |
| DEC-001 | Port Strata V4.1 with existing Windows/SYCL patterns | ADOPT | EV-001, EV-003, EV-004 | Preserve model/pack/CPU semantics and reuse existing lab work. Complexity: Adapt old fork patches and port DeepSeek GPU operations. | An upstream Intel V4.1 implementation becomes available and passes the same gates. |
| DEC-002 | JIT, AVX2 host, explicit synchronization and isolated lifecycle | ADOPT | EV-004, EV-005, EV-007, EV-008 | Start from lab evidence while revalidating versions and hardware. Complexity: Runtime manifest, small probes, watchdog and harness adaptation. | AOT/concurrent paths independently pass parity and soak with demonstrated benefit. |
| DEC-003 | Layer split, host-staged transfers, CPU overflow, 2.00-bit 8K text baseline | ADOPT | EV-002, EV-006, EV-009, EV-010 | Minimize multi-device synchronization and establish correct execution first. Complexity: Explicit budgets and transfer lifetimes; not maximum GPU utilization. | Measured V4.1 profile and transfer costs justify another placement. |
| DEC-004 | Full-model FP16 expansion | REJECT | EV-002, EV-009 | Would invalidate the compressed-memory design. Complexity: Large temporary allocations and host spill. | Only bounded scratch experiments within recorded budgets. |
| DEC-005 | Automated CUDA translation or emulation as proof of support | REJECT | EV-003, EV-007 | Translation does not establish correctness or Windows synchronization behavior. Complexity: Review subgroup, pointer, event and allocation semantics. | A supported implementation demonstrates all required gates. |
| DEC-006 | Tensor/expert parallelism, graph capture, per-card submission threads | DEFER | EV-006, EV-007 | Prior lab results reject assuming these are unconditional speedups. Complexity: Cross-device reductions, capture limitations and possible driver deadlocks. | V4.1 profile shows sufficient ceiling and isolated proof passes. |
| DEC-007 | AOT, DSpark, vision, concurrency and extended context | DEFER | EV-004, EV-010 | Keep correctness and memory attribution clear. Complexity: More kernels, shapes, state and allocation paths. | Baseline parity, four-card execution and soak pass; each gets a separate decision. |
<!-- rfb:decisions:end -->
