# Action plan: Strata DeepSeek V4.1 on four B70s, native Windows

Status: **planned; no DeepSeek V4.1 Intel implementation or performance measurements from this work.**
Prepared 2026-10-26. Updated for hosted DeepSeek/OpenClaw execution. Start with STEP-000, then STEP-001; later gates retain their IDs.
This is a research-only handoff, not a claim that the model can currently launch.

> ### Checkpoint 2026-10-28 09:30 CDT — llama.cpp-side measurement update
>
> This plan routes through the **Strata `strata-dsv41` engine**. Parallel work in a llama.cpp
> SYCL fork (`C:\llamacpp-v41`) has meanwhile produced measurements that are **input to route
> assessment, not passed gates**. No CHECK-102..108 gate moved. Recorded here so the numbers are
> not re-derived.
>
> | Fact | Value |
> |---|---|
> | Pack | DeepSeek-V4.1-Flash-1017 GSQ-RCO IQ2_XXS, 128.74 GiB, 1008 tensors, 551.88 B params |
> | Tensor composition | **95.5% MoE experts (123.00 GiB)**; attention 3.56, dense 1.05, embd 0.85, **Engram 0.20** |
> | Engram correction | The 110 GB Engram figure is the separate `-Engram-IQ4_NL.gguf` (103 GB), **never loaded**. In-pack Engram is 0.20 GiB, so NVMe-Engram is not a capacity lever. |
> | Device buffers | 119.4 GiB across 4 cards — **fits** 130 GiB of VRAM |
> | Server status | **loads and serves** (`model loaded`, `listening`, `health 200`) on 4x B70 |
> | Outstanding | **no prefill or decode token rate has been obtained**; inference request dies at ~85.7 GB host WS |
> | Root cause of earlier `exit -1` | **not a crash** — `ram-watchdog.ps1` calls `TerminateProcess(h,-1)`; verified by control test |
>
> Full detail: `work/strata-v41-agent-runner/SESSION-13-CHECKPOINT.md` and `HANDOFF-SESSION-13.md`.
>
> **Open question that decides viability:** host RAM tracks the GPU allocation ~1:1 regardless of how
> many experts sit on CPU (`-ncmoe 5` and `-ncmoe 18` both peak at 85.7 GB WS). If a small-model
> control shows the same, the backend mirrors device memory into system RAM and 1017 needs ~160 GB
> RAM or a ~70 GB pack — independent of which engine is used.

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

## Route decision — CONFIRMED 2026-10-27 by the owner

The owner has re-confirmed that **porting the Strata engine is the intended route**, and that this is how the
project started. This is not a change of direction; it is a correction of a divergence.

A prior session (recorded in `FINDINGS.md` as SESSION 3 — ROUTE DIVERGENCE) did the work in a llama.cpp SYCL
fork at `C:\llamacpp-v41` instead. That tree crossed three boundaries this plan fences off. Its measurements
are retained as **input**, but they are not Strata-engine evidence and no CHECK-102..108 gate moved.

### Newly established scope fact — the engine is CUDA/HIP only

Verified against the upstream object store on GPU-BOX (`git ls-tree -r --name-only`):

| Ref | dsv41 files | SYCL dsv41 files |
|---|---:|---:|
| `v0.2.6` | 131 | **0** |
| `v0.2.7` | 138 | **0** |

Extensions present in `v0.2.6`: 42 `.py`, 22 `.cpp`, 17 `.hpp`, **14 `.cu`, 12 `.cuh`**, 5 `.inc`, plus scripts.
The engine lives at `src/dsv41/` as `ds4_model.cu`, `ds4_kernels.cu`, `ds4_iq.cu`, `ds4_gguf.cu` and headers.
`packaging/build_dsv41_windows.bat` and `tools/dsv41/win/*.bat` exist — so Windows is a supported *host*, but
through HIP/CUDA.

**Consequence:** "build `strata-dsv41` with Windows SYCL" is not a build-configuration change. The engine's
compute code is CUDA/HIP and has no SYCL implementation. Porting means translating that code, which is exactly
STEP-003. This plan's "Automatic CUDA translation as a complete port — Reject" decision stands: translation
tooling may scaffold, but cannot satisfy CHECK-103.

Measured scope, kernel counts, the in-tree SYCL template, and the base-version decision are in
[PORT-SCOPE.md](PORT-SCOPE.md). Two items there supersede this file:

- **Base is `v0.2.7` (`5e8a4cca7`), not the `v0.2.6` pin below.** v0.2.7 adds ~1,000 engine lines
  (incl. a new `ds4_wmma.cuh`) one day after v0.2.6. Porting a stale tree then re-porting is waste.
- **`sycl/src/` already contains 108,675 lines of working Windows SYCL**, structurally mirroring
  `src/`, with expert placement, host staging, graph capture and MTP already implemented. The port is
  `sycl/src/dsv41/` following that pattern — not translation from first principles.

Port surface: **16,428 lines of CUDA/HIP compute, 93 `__global__` kernels, 130 launch sites, 41
`__shfl` shuffles**; 5,790 lines of CPU/host code compile unchanged; `ds4_vision.cu` (519 lines) is
out of scope for the first deliverable.

### What the llama.cpp detour actually bought us

Retained as route-relevant input, explicitly **not** as Strata evidence:

| Finding | Value |
|---|---|
| Pack integrity | 128.74 GiB, 551.88 B params, 2.0625 bpw; loads and generates on 4x B70 |
| Prefill baseline | ~11-12 t/s at b=128; b=256 collapses to 0.70 t/s (reproduced) |
| Decode baseline | ~3.9 t/s at b=32/ub=512; ~3.65 layer split |
| Split behaviour | `-sm layer` > `-sm tensor` by 65%; `-sm row` aborts on I32/I64 |
| Memory ceiling | ~955 MiB overrun at `-ngl 99`; `-ngl 38` leaves 3/41 layers on CPU |
| Failure modes | SYCL alloc OOM at large ubatch; server `-1` at `llama_context`; pinned-host alloc failure |
| Comparison | Strata's engine does ~1,415 t/s prefill on 2 cards; the fork does ~11.4 on 4 |

That last row is the argument for the port, and it is now measured rather than assumed. It also sets the
target: a successful port should approach Strata's own numbers, not merely improve on the fork.

### Performance variance is unresolved and may invalidate several recorded numbers

A `-r 3` flash-attention-on run measured `pp128 = 39.63 ± 31.48` t/s. A standard deviation of 31 on a mean of
39 is not a measurement, it is a bimodal distribution. Earlier single-sample runs gave 0.33 for the same
configuration. Both cannot be a stable configuration. The same pattern appears in the prefill sweep
(b=512: 41.87 on one run, 0.61 on the next).

Until per-sample data exists, treat every single-sample throughput figure in this plan as **provisional**.
`llama-bench -o json` retains individual samples and should be used from here. Any optimisation retained
without variance data fails CHECK-106 by its own wording.

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
| Automatic CUDA translation as a complete port | **Partially superseded 2026-10-27** | dpct was run: it converts ~85% of 93 kernels (96 `parallel_for` emitted, 14 launch sites + 2 kernels need hand work). Translation is now the *method*; it is still not the *acceptance* — CHECK-103 alone decides. See [PORT-SCOPE.md](PORT-SCOPE.md) §10 |
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

## Measured findings (2026-10-27, GPU-BOX, 4x Arc Pro B70)

These are real measurements taken on the lab box, not planning estimates. They correct two
conclusions recorded earlier and should feed STEP-006 (profile/optimize) directly. The full
detail, with configs and raw numbers, lives in
[`work/strata-v41-agent-runner/FINDINGS.md`](../../work/strata-v41-agent-runner/FINDINGS.md)
sessions 7-8 and in [`machine-manifest.json`](../../work/strata-v41-agent-runner/machine-manifest.json).

### Prefill throughput depends on prompt length; the good setting is `-b 128`

> **CORRECTED 2026-10-27 (Session 9).** A b=512 figure of 41.87 t/s did **not** reproduce — a
> repeat measured **0.61 t/s**. Prefill peaks at **b=128 (~11-12 t/s)** and degrades above it;
> the b=256 collapse to 0.70 t/s is real and reproduced twice. "Big batch for prefill" is WRONG;
> the setting is b=128 specifically.
>
> **Not independently confirmed.** A later run at `-p 512 -b 128` gave 12.25 t/s once and
> 40.47 +/- 24.69 at r=3 — but that r=3 run was **contended** (a concurrent agent session's
> workload was resident; see `c53aad2` and FINDINGS W-056). The apparent agreement at
> "11-12 t/s" is therefore not corroboration. What survives without contention: b=128 is where
> prefill behaves best and very large batches are worse; the exact rate is unqualified.

`llama-bench`, `-ngl 38 -t 12 -lm none --no-warmup -r 1`, layer split:

| config | prefill t/s | decode t/s |
|---|---:|---:|
| `-p 32 -b 32` | 0.55 | 3.65 |
| `-p 32 -b 32 -ub 512` | 0.60 | 3.69 |
| `-p 256 -b 256` | 6.19 | 0.35 |
| `-p 512 -b 128` | **12.25** | — |

**This corrects the earlier "batching is broken / pp is 9x slower than tg" conclusion**, which was
read from `-p 32` alone. At longer prompts prefill is far faster than decode and behaves sanely.

> **All numbers in this table are single-sample and several were taken while another agent
> session was running on the same GPUs.** Treat them as directional only. Throughput on this pack
> is bimodal (one r=3 run reported 61% relative stddev), so single runs cannot separate a
> configuration change from noise. No row here should be quoted as a qualified rate.

**Caveat on mechanism:** the pp32 -> pp512 rows change prompt length *and* batch size together, so
they do not isolate batch width. `pp512 @ b=128` (12.25) also beat `pp256 @ b=256` (6.19), which
argues the gain is per-token amortisation of fixed per-batch overhead rather than batch width per
se. Do not read this table as "raise `-b` for a 22x win" — the supported setting is b=128, and
beyond it throughput falls. A clean batch sweep at fixed prompt length is still unrun because
`llama-bench` multi-value sweeps abort in this build (FINDINGS L-043); it needs separate
invocations.

### Prefill and decode want opposite configurations

> **CORRECTED 2026-10-27.** "Prefill peaks at large batch (`-b 128`+)" is wrong — b=512 measured
> 0.61 t/s on repeat. Prefill peaks at **b=128**. Decode still peaks at b=32/ub=512.

Prefill peaks at large batch (`-b 128`+). Decode collapses at `-b 256` (0.35 t/s) and peaks at
`-b 32 -ub 512` (3.69 t/s). No single configuration is optimal for both, which is a direct input
to STEP-005/006: either pick per workload, or run separate instances. This also argues against
judging the model on a single blended tok/s number.

### Split mode: layer, not tensor

At identical flags, layer split decodes at 3.65 t/s vs tensor split at 2.21 t/s, a 65% advantage.
Tensor split is not the fast path for this model on this box.

### Row split is broken for this pack, and the cause is identified

`-sm row` aborts immediately at `ggml-sycl.cpp:1419` inside `get_row_rounding()`, exit
`-1073740791` (0xC0000409). A GGUF header scan of shard 1 shows 42 tensors: 30x IQ1_M, 8x IQ2_XXS,
3x **I64**, 1x **I32**. The I32/I64 tensors are the Engram lookup tables
(`engram_token_map.weight` I32; `engram_primes/offsets/multipliers.weight` I64). The row-rounding
switch handles IQ1_M and IQ2_XXS but has no case for I32/I64, so it reaches
`default: GGML_ABORT`. Row split is unusable until those cases exist, and lookup tables
arguably should not be row-split at all.

### PCIe is ~12 GB/s per card — the "link width 1" reading was an artifact

Empirical host↔device probe (`icx-cl -fsycl`, 512 MB transfers, all four cards):

| device | H2D GB/s | D2H GB/s |
|---|---:|---:|
| 0 | 11.63 | 11.25 |
| 1 | 11.68 | 11.19 |
| 2 | 12.60 | 11.42 |
| 3 | 11.66 | 11.31 |

Peaks 12.1-13.2 GB/s. PCIe 4.0 x16 is ~25-28 GB/s and x8 is ~12-14 GB/s, so this is **PCIe 4.0
x8 per card**, decisively not x1 (~0.9-1 GB/s). Windows PnP reported `link width = 1` for all
four endpoints, which measurement contradicts; treat that reading as a reporting artifact.
Caveat: this is bandwidth evidence, not a negotiated-link-state read. A x16 slot bifurcated to
two x8 links, or a chipset x8 uplink, produces the same numbers.

At ~12 GB/s per card, host-staged weight streaming is first-order for a 128.74 GiB pack, which
supports the CPU-overflow/placement decisions already in the architecture table.

### The serving path is blocked by an intermittent ~9.1 GiB host buffer allocation

`llama-server` consistently places 38/41 layers and needs a **SYCL_Host buffer of 9,762,838,016 B
(9.09 GiB)**. That allocation is unreliable:

| env | outcome |
|---|---|
| `GGML_SYCL_ENABLE_HOST_PINNED_MEM=1` (default) | `ggml_backend_sycl_host_malloc: failed to allocate 9310.57 MiB of pinned memory` |
| `GGML_SYCL_ENABLE_HOST_PINNED_MEM=0` | **sometimes succeeds** — model loads, `/health` returns 200, `listening on :9036`, all slots idle |
| `GGML_SYCL_ENABLE_HOST_PINNED_MEM=0`, retried | falls back to `ggml_backend_cpu_buffer_type_alloc_buffer: failed to allocate buffer of size 9762838016` |

So the pinned-memory path is a real and separate defect, and disabling it is necessary but **not
sufficient** — the plain host allocation also fails intermittently.

**This is host-RAM exhaustion, and the cause is the RAM watchdog.** An earlier note in this
section claimed otherwise from a `FreePhysicalGB=84.65` reading — that reading was taken *after*
the process died and released memory, so it described the idle box, not the failure. Corrected.

The authoritative account is `WATCHDOG-KILL-FINDING.md` and `HOST-COMMIT-CONTROL.md`:

- `C:\llama-swap\ram-watchdog.ps1` kills `llama-server` when available RAM drops below **6 GB**,
  using `Stop-Process -Force` -> `TerminateProcess(h,-1)` -> **exit code -1**. Every recorded
  `exit -1` on this track is that kill, not an abort in the deepseek41 code.
- Private commit tracks **~1.0-1.14x model size** on this SYCL path, established against a
  17.28 GB control model that loads and serves normally (priv 19.66 GB, ratio 1.138, `health 200`).
- 1017 therefore needs roughly **148 GB** of host commitment against **95.9 GB** installed. The
  shortfall is 33-43 GB and no load-mode or offload flag closes it.

Direct confirmation from `ram-watchdog.log` at 2026-10-28 07:45:52:
`KILLED 1 llama-server (avail=5.28 GB below 6 GB): pid=12604 priv=95.1GB ws=79.1GB`.

Also confirmed: omitting `-fit off` fails differently and worse, attempting a 19.1 GiB
allocation on SYCL0. `-fit off` is mandatory for this model on this box.

So the serving path is **not** blocked on a fixable allocation defect. It is blocked on arithmetic:
this pack does not fit in this machine's RAM. Viable directions are a pack of ~<=70 GB with
`deepseek41` support, or ~160 GB of RAM. `GGML_SYCL_ENABLE_HOST_PINNED_MEM=0` changing the failure
signature is a symptom of *when* the watchdog fires, not a fix.

### GPU health: TDR count is genuinely zero, but the "clean" framing needs nuance

Confirmed independently: **`Display` provider TDR (Event 4101) = 0 over 7 days.** The handoff's
claim holds.

However, the Application log also carries **3,790 LiveKernelEvent entries in 7 days**, dominated
by `P1: 141` (2,827) with `P1: 193` (455), `P1: 124` (262). These are not TDRs and did not
correlate with any of today's llama-server exits, but "zero TDRs" should not be read as "no GPU
diagnostic events at all". Worth identifying what 0x141 is on this driver before a long soak.

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
