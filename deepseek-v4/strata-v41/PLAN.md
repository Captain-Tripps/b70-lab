# Action plan: Strata DeepSeek V4.1 on four B70s, native Windows

Status: **planned; no DeepSeek V4.1 Intel implementation or performance measurements from this work.**
Prepared 2026-10-26. Updated for hosted DeepSeek/OpenClaw execution. Start with STEP-000, then STEP-001; later gates retain their IDs.
This is a research-only handoff, not a claim that the model can currently launch.

## Outcome and scope

Build a native Windows SYCL version of Strata's separate `strata-dsv41` engine for DeepSeek-V4.1-Flash-1017,
using four Arc Pro B70 32 GB cards, CPU overflow experts, and NVMe-backed Engram lookup.
First target: IST-DAS 2.00 bpw, text only, one request, 8,192-token context, all six routed experts.
Validate 2.25 bpw after the first configuration passes. Keep production Qwen and DeepSeek V4 0731 unchanged.

The user reports Windows 11 Pro, EPYC, ROMED8, 128 GB RAM, and a 2 TB NVMe with Gen4 x16 GPU connectivity.
The repo identifies an EPYC 7402P / ROMED8-2T, but records 112 GB and later 95.9 GB usable RAM and boot memory
errors. These are historical reports, not proof of today's condition. Capture actual usable RAM, CPU identity,
DIMM count, boot errors, free disk, and each GPU's negotiated link before sizing the port.

Not in the first deliverable: Linux migration, WSL dependence, new hardware, vision, multiple concurrent
requests, maximum context, tensor/expert parallelism, speculative decoding, or a new inference framework.
No performance target is promised before measurement. This plan does not start heavy jobs or replace servers.

## What changes from the earlier analysis

- Windows SYCL is **already running in this lab**. Reuse the native-build and shared-host-memory work in
  [strata-windows-port](../../strata-windows-port/README.md); do not budget it as a blank-slate port.
- Those patches target `hotschmoe/Strata` at abbreviated revision `1c360526`, not the new upstream DeepSeek
  engine. Resolve that full commit and the actual deployed local changes during STEP-001; do not apply blindly.
- Upstream v0.2.6 is pinned to `4b9e05a2a806a3fe24f7b2560d98626c37dade35`. Its Intel docs explicitly exclude V4.1.
  The new work is a DeepSeek engine port, not an Intel detection toggle.
- [Track A](../PLAN-expert-parallel.md) remains rejected for **V4 0731**. Its profile does not establish the
  V4.1 bottleneck. The older Track B requirement to wait for llama.cpp support is superseded for this Strata route.
- The lab already documents absent Windows peer access, a JIT/AOT correctness difference, WDDM demotion,
  and a Level Zero submission deadlock. These are version-scoped observations; re-test the intended runtime.
  Shared context alone does not make the newer queue-barrier path safe on the default v2 adapter.

## Agent execution arrangement

Use OpenClaw with `openrouter/deepseek/deepseek-v4.1-flash-1017` as the implementation agent.
The coding model runs remotely; GPU-BOX runs native Windows builds and GPU tests. No local coding-model
load/unload loop is needed. This is an operational choice, not a proven ranking of model coding ability.
Qualify the exact installed OpenClaw version, model route, reasoning/tool replay and Windows runner first.
Keep hosted API inference separate from the local V4.1 engine being ported; API answers are not same-pack
numerical reference logits. See [OpenClaw starter prompt](OPENCLAW-START.md).

The gateway can run on GPU-BOX or another machine. A separate gateway survives a GPU-BOX reboot; a gateway on
GPU-BOX does not. In either case, persist task state and artifacts on disk. If the gateway is in WSL, dispatch
builds/tests to native Windows explicitly; this does not introduce WSL as an inference dependency.

## Architecture decisions

| Decision | Adopt / defer / reject | Reason |
|---|---|---|
| Hosted DeepSeek through OpenRouter; OpenClaw with a native Windows runner | Adopt | Keeps coding inference off the four B70s; qualify real tool rounds before port work |
| Extend Strata's V4.1 engine using SYCL/oneMKL and the lab's Windows patterns | Adopt | Preserves model semantics, packer, CPU experts, Engram I/O, and API integration |
| JIT build, AVX2-compatible host code, explicit synchronization | Adopt first | Existing lab evidence includes bad AOT output and EPYC illegal-instruction failures |
| Layer split with host-staged device transfers in a shared context | Adopt first | Works without assuming GPU peer access; each GPU owns a block of layers |
| Automatic CUDA translation as a complete port | Reject | Migration scaffolding does not establish numerical, subgroup, lifetime, or synchronization correctness |
| CUDA compatibility/emulation as the main strategy | Reject for this plan | No inspected evidence it implements this engine correctly on this Windows/B70 stack |
| Four-way expert/tensor parallelism, graph capture and per-card submission threads | Defer | Profile V4.1 first; current lab has measured low ceilings and crash/hang cases on other workloads |
| AOT, DSpark, 2.25-bit, longer context | Defer | Separate correctness and memory/performance campaigns after the baseline |
| Full-model dequantization to FP16 | Reject | Defeats the memory budget; use fused kernels or bounded layer/tile staging |

Use a single owning host submission thread for the initial GPU path, explicit events/waits and bounded
staging buffers. CPU expert workers and file I/O can remain parallel. Do not transplant Qwen doorbell flags,
KV settings, PLE flags or heartbeat variables into V4.1 without inspecting the receiving code.

## Memory and storage budget

Upstream [planner](https://github.com/Niko1221/Strata/blob/4b9e05a2a806a3fe24f7b2560d98626c37dade35/strata_control/dsv41_fit.py) and [model guide](https://github.com/Niko1221/Strata/blob/4b9e05a2a806a3fe24f7b2560d98626c37dade35/docs/DEEPSEEK41.md):

| Set | Main model files, decimal GB | Routed experts, decimal GB | Engram, decimal GB | Download incl. drafter, approx. GB |
|---|---:|---:|---:|---:|
| 2.00 bpw | 138.24 | 132.07 | 110.60 | 257 |
| 2.25 bpw | 155.23 | 149.06 | 110.60 | 274 |

Nominal 4 x 32 GB GPU capacity is not a runtime allocation budget. Record raw bytes, GiB and decimal GB
separately. As an illustrative conservative budget only, 110-120 decimal GB for GPU experts leaves
12-22 GB (2.00) or 29-39 GB (2.25) outside VRAM. Add dense weights, KV/state, prompt buffers, staging,
driver/display use, and any drafter allocation separately. Inspect every card; aggregate fit is insufficient.

128 GB host RAM appears sufficient for overflow experts, but does **not** imply the full 111 GB Engram table
also fits in RAM. Reserve OS/engine headroom and measure cached vs cold lookup latency. The older 508 GB
set is out of scope. A 2 TB drive has nominal capacity; free space and temporary model-preparation usage
still need checking. Do not download duplicate packs before inspecting existing files and their hashes.

## Work packages and acceptance gates

### STEP-000 — Qualify the hosted agent and native Windows test runner

Owner: OpenClaw implementation agent with access to GPU-BOX. No model weights or GPU workload required.
Deliverables: runner scripts/tests, a redacted execution manifest, receipt artifacts and a resumable task record.
Use [OPENCLAW-START.md](OPENCLAW-START.md) for the first session.

- [ ] Record OpenClaw version, gateway host, execution host identity, exact model ID, effective reasoning
  setting, provider policy and actual provider when exposed. Use existing secret storage; never log API keys.
  Do not silently fall back to a local model or a different model/provider; record any approved change.
- [ ] Confirm repo/worktree identity, current branch, dirty files and applicable AGENTS.md instructions.
  Create a dedicated development branch without resetting user work. Preserve the plan branch as a handoff.
- [ ] Prove the complete tool loop: inspect/edit a disposable fixture, observe an intentional failing test,
  fix the fixture (not its assertion), rerun successfully and perform a subsequent tool call using its result.
  Record evidence of actual execution and reasoning/tool-message continuity; a chat-only answer is insufficient.
- [ ] Implement a native Windows command runner with explicit cwd, argument handling, toolchain initialization,
  exit-code propagation, stdout/stderr files, timeout, and a machine-readable result. Do not assemble arbitrary
  shell strings from JSON. Avoid secret-bearing environment dumps. Cache artifacts under a unique run ID.
- [ ] Add a cross-process lock for GPU tests and ownership tracking for child processes (PID, creation time,
  executable path and endpoint where applicable). Existing model services cause a busy result; do not unload
  or kill them automatically. A GPU-test lease alone does not prove that production services released VRAM.
- [ ] Exercise CPU-only mocks: success, nonzero exit, timeout with child cleanup, paths with spaces,
  competing lock acquisition and an unrelated sentinel process that must survive every cleanup case.
  A Windows Job Object or equivalent verified ownership mechanism may manage spawned process trees.
- [ ] Save code SHA plus dirty diff hash when relevant, commands, toolchain identity, timestamps, exit status,
  logs, acceptance results and next action. Reopen task state in a fresh agent session and resume without
  repeating completed actions. No credentials or unrestricted transcripts go into Git.

CHECK-100 passes only when the real OpenRouter/OpenClaw tool loop and all CPU-only runner mocks pass,
including session resume. A stand-alone runner test does not prove the agent integration. Missing GPU-BOX access
leaves the Windows portions BLOCKED; a Linux/WSL substitute cannot be reported as a Windows pass.
Keep GPU benchmark concurrency at one. No unattended multi-agent GPU testing is part of this milestone.

### STEP-001 — Reconcile the actual machine and establish provenance

Depends on STEP-000 for automated host execution. Owner: implementation agent with access to the B70 host.
Read-only inventory and source inspection can proceed while STEP-000 is being qualified.
Planning allowance: 0.5-1 engineering day. No heavy GPU work before this gate.

- [ ] Save OS build, CPU model, actual physical/available RAM, DIMM count, relevant recent WHEA boot events,
  NVMe model/free bytes, adapter PCI identities/driver, and per-card link generation/width.
- [ ] Record compiler, oneMKL, Level Zero loader and UR adapter versions, full paths and hashes of deployed binaries.
- [ ] Resolve the old Windows-port base and local patch history; pin v0.2.6 and compare required changes.
- [ ] Locate existing Strata/model checkouts and available reference hardware; inventory files, do not change production.
- [ ] Create an isolated development checkout/output path and a proposed unused test endpoint.

CHECK-101: saved manifest explains the 128/112/96 GB discrepancy, explicitly records any unresolved hardware
fault, and identifies a stable baseline. If usable RAM or hardware health is uncertain, pause heavy testing;
source analysis and small fixtures can continue. Record unavailable link telemetry as unknown, not x16.

### STEP-002 — Reuse the Windows foundation and qualify device operations

Depends on STEP-001. Owner: runtime/build implementer. Planning allowance: 1-3 days.

- [ ] Adapt only applicable parts of patches 0001-0003 onto the pinned tree. Preserve notices.
- [ ] Add a separate development SYCL target for V4.1; compile host code without AVX-512 on the recorded Zen 2 CPU.
  Start JIT; package an explicit runtime DLL manifest. Do not imply an existing upstream SYCL DeepSeek target.
- [ ] Extend the lab's existing `ep_probe.cpp` or add a focused probe: enumerate four devices, validate bounded
  host/device allocations, canary round trips, all 12 directed device-pair paths, and repeatable cleanup.
- [ ] Use shared-context host staging by default. Do not dereference remote device memory without capability
  evidence. Exercise explicit ordering with oneMKL; include a process timeout for deadlock cases.
- [ ] Keep v1/v2 adapter experiments isolated and record exact effective environment values.

CHECK-102: three fresh process runs complete on all four devices with exact transfer checksums, no device loss,
no timeout, and logged latency/bandwidth. Include >4 GiB addressing tests with a measured memory cap after
small tests pass. If a candidate requires unbounded spinning or undocumented peer access, reject that path.

### STEP-003 — Port model operations and prove numerical behavior

Depends on STEP-002. Owner: kernel implementer. Planning allowance: 1-3 weeks; revise after inventory.

- [ ] Inventory the transitive V4.1 call graph and actual tensor types in the chosen 2.00-bit files.
  A file's IQ2_XXS label does not imply every tensor uses that type.
- [ ] Port runtime/BLAS calls in `ds4_model.cu`; implement required operations in `ds4_kernels.cu`,
  `ds4_iq.cu`, `ds4_gguf.cu` and their headers. Include reachable vendor sampling/model paths.
  Map CUDA warps/shuffles to explicit SYCL subgroup operations; audit 64-bit indexing and atomic visibility.
- [ ] Reuse `ds4_os.hpp`, CPU kernels and Engram/pack semantics where compatible. Audit CPU ISA flags.
  Exclude unused vision/EXL3/trellis paths only after dependency analysis; fail clearly on unsupported formats.
- [ ] Create small CPU-reference fixtures for each required quant format and operation, including tails,
  non-contiguous rows, router ties, attention/compression state, mixed expert placement and zero-length cases.
- [ ] Compare a real layer and teacher-forced logits with a supported CUDA/HIP build using the **same**
  model/pack/token IDs. Store the provenance of the reference outputs.
- [ ] Define per-operation absolute/relative tolerances before results are evaluated. Require finite values;
  track worst errors, top-k agreement and logit KL. Do not make exact generated-text equality the sole gate.

CHECK-103: every required operation passes its frozen tolerance; a real-layer comparison and reference logits
pass. Missing reference access leaves this gate incomplete. A successful build or a sensible sentence alone
does not pass it. Translation tooling may scaffold code but cannot satisfy this check.

### STEP-004 — Run the complete model across four cards

Depends on STEP-003. Owner: engine implementer. Planning allowance: 1-2 weeks.

- [ ] Implement a V4.1 layer split, initially about ten layers/card, then adjust for head weights and actual budgets.
  Use explicit ownership, bounded staging and CPU overflow expert computation.
- [ ] Preserve the all-or-none CPU-expert preload policy where applicable; account for actual available RAM/commit.
  Avoid duplicate resident expert copies and unintended WDDM spill.
- [ ] Bring up 2.00 bpw, 8K context, one request, six experts, no speculative execution, no vision.
  Inspect DSpark handling: upstream `--dspark off` can still allocate draft weights, so verify the no-drafter
  memory path rather than assume the switch means unloaded.
- [ ] Validate first token, multi-token decode, prompt chunks, context boundaries, repeat requests and cancellation.
  Exercise mixed GPU/CPU expert routing, not just all-resident synthetic cases.

CHECK-104: all four devices participate; same-pack teacher-forced parity passes; three cold starts and a
mixed-prompt batch complete without invalid numbers or restart. Per-card residency and host headroom stay
inside the recorded budgets. Capture dedicated/shared GPU memory, available RAM, working set and commit
separately. Do not interpret private bytes alone as physical RAM.

### STEP-005 — Integrate serving and safe benchmark lifecycle

Depends on STEP-004. Owner: serving/harness implementer. Planning allowance: 2-5 days.

- [ ] Add explicit development engine selection to Strata's V4.1 setup/server path, with actionable unsupported
  backend/format diagnostics. Preserve upstream pack integrity and production engine selection.
- [ ] Reuse STEP-000 runner ownership, lock, timeout and artifact conventions. Then extend the lab benchmark harness for `strata-dsv41.exe` and its Python wrapper. Existing `arm.ps1`
  ownership/discovery/teardown assumes llama-server; it is not a drop-in V4.1 harness.
- [ ] Retain executable path + PID + port identity checks and process-owned cleanup. Add mock lifecycle tests
  for the new engine so unrelated production services cannot be killed.
- [ ] Test streaming, tool calls/DSML, cancellation, restart, max-context rejection, and repeated sessions.
- [ ] Run a request-free 300-second idle/resume test to detect WDDM demotion; if needed, implement an engine-local
  idle heartbeat and repeat. Do not assume the llama.cpp heartbeat environment variable controls Strata.
- [ ] Finish a two-hour mixed-workload soak, including idle periods and cold/warm Engram access.

CHECK-105: lifecycle mocks pass, production stand-in survives, endpoint answers correctly, idle/resume is
recorded, and the soak has no crash, hang, silent corruption or unbounded memory growth.
No deployment switch is part of this planning change.

### STEP-006 — Profile, optimize, and expand the validated configuration

Depends on STEP-005. Owner: performance implementer. Planning allowance: 2-4+ weeks.

- [ ] Break time down into dense/attention, quantized experts, CPU lane, Engram I/O, transfers, launch overhead,
  and synchronization. Separate prefill, decode and client latency.
- [ ] Optimize the measured dominant costs: fused quantized XMX/ESIMD kernels, bounded dequantization,
  prompt chunking or expert placement. Change one variable per experiment.
- [ ] Use at least three comparable runs and paired A/B/B/A where feasible; archive prompts, hashes,
  flags, warm/cold state, correctness results, timings and variance.
- [ ] Qualify 2.25 bpw against its own supported-backend reference and assess task quality vs 2.00 separately
  from port-induced numerical differences. Increase context only after recalculating budgets.
- [ ] Revisit deferred DSpark, graphs, AOT or parallelism through a new decision and gate, not by enabling
  all of them together. For DSpark report draft acceptance and verify cost separately.

CHECK-106: publish only correctness-qualified results with variance and memory/latency data.
An optimization is retained only for a repeatable benefit on the nominated workload without stability or
quality regression. No fixed tok/s claim is an acceptance criterion.

### STEP-007 — Package a reproducible lab handoff

Depends on STEP-005 and the selected STEP-006 experiments. Owner: release/documentation implementer.

- [ ] Publish a pinned patch series or fork revision, build recipe, DLL/version manifest, configuration template,
  regression fixtures and measured hardware/model matrix. Include MIT attribution and inspect model licenses
  before any distribution; do not commit weights or opaque binaries to this notebook.
- [ ] Update STATUS, CHANGELOG and the topic page with measured results; preserve failed experiments and causes.
- [ ] Document rollback to the existing Qwen/V4 entries. Keep the new backend opt-in until qualification.
- [ ] Reconcile the final diff with adopted/deferred/rejected decisions.

CHECK-107: a clean development directory can reproduce the qualified build and launch; no production configuration
is overwritten. CHECK-108: final diff contains no unqualified deferred features.

## First implementation session

Execute STEP-000 and the read-only STEP-001 inventory. The first session ends with a committed runner and
CPU-only mock tests, redacted execution/machine manifests, tool-loop and resume evidence, and updated gate
status. Record missing access or telemetry explicitly. Stop at this reviewable milestone before STEP-002;
do not start a 257 GB download, GPU workload, production service change or complete CUDA translation.
The prompt authorizes bounded development edits/tests and pushing the new development branch, not a merge
or production deployment. Future STEP-002 work starts from the recorded readiness evidence.

This is not a calendar promise: the initial reconciliation/probe is roughly 2-4 engineering days, while a
correct full engine plus qualification is a multi-week effort. Compiler/runtime failures may extend it.
Re-estimate after CHECK-102 and CHECK-103 instead of treating the earlier generic estimate as a commitment.

## Evidence and status

[Research and decisions](RESEARCH.md), [verification state](VERIFICATION.md), and [canonical ledger](evidence.json)
record the inspected revisions. Reported lab experiments remain documented evidence, not tests rerun by this
planning task. All implementation checks start NOT_RUN.

## Ledger: plan

<!-- rfb:plan:start -->
| ID | Outcome | Requirements | Decisions | Acceptance |
| --- | --- | --- | --- | --- |
| STEP-000 | Qualify hosted agent tool loop and native Windows runner without GPU loads | REQ-004 | DEC-008 | CHECK-100 |
| STEP-001 | Reconcile hardware, runtime and source provenance | REQ-001, REQ-002, REQ-003 | DEC-002 | CHECK-101 |
| STEP-002 | Qualify native Windows build and four-device operations | REQ-001, REQ-002, REQ-003 | DEC-001, DEC-002, DEC-003 | CHECK-102 |
| STEP-003 | Port required model operations and validate numerical behavior | REQ-001, REQ-002, REQ-003 | DEC-001, DEC-002 | CHECK-103 |
| STEP-004 | Complete four-card V4.1 execution with CPU overflow | REQ-001, REQ-002, REQ-003 | DEC-001, DEC-003 | CHECK-104 |
| STEP-005 | Integrate serving, lifecycle isolation, idle/resume and soak | REQ-001, REQ-002, REQ-003 | DEC-001, DEC-002, DEC-003 | CHECK-105 |
| STEP-006 | Profile and optimize the qualified baseline | REQ-001, REQ-002, REQ-003 | DEC-001, DEC-002, DEC-003 | CHECK-106 |
| STEP-007 | Publish reproducible build/patch/configuration handoff | REQ-001, REQ-002, REQ-003 | DEC-001, DEC-002, DEC-003 | CHECK-107 |
<!-- rfb:plan:end -->
