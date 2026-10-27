# OpenClaw starter: hosted DeepSeek, native Windows GPU-BOX

This is the first bounded implementation assignment for [PLAN.md](PLAN.md), not a request to complete the
whole GPU port in one run. STEP-000 and STEP-001 are the first deliverable. All execution checks are NOT_RUN
until the receiving agent supplies real evidence.

## Select the model

Use your existing OpenRouter credential through OpenClaw's secret/auth configuration. Do not put it in this
repo or paste it into a prompt. If authentication is not configured, use the installed version's onboarding:

```text
openclaw onboard --auth-choice openrouter-api-key
openclaw models set openrouter/deepseek/deepseek-v4.1-flash-1017
```

For an existing working installation, only select the model; do not rerun onboarding unnecessarily.
Record the effective reasoning setting supported by the installed route; do not assume an arbitrary `max`
value is accepted. Verify tools and subsequent tool-result replay. Record provider routing and any fallback.
The gateway may be local or remote, but the build/test runner must execute on native Windows on GPU-BOX.

Sources: [OpenClaw integration](https://docs.openclaw.ai/providers/openrouter),
[exec](https://docs.openclaw.ai/tools/bash),
[model](https://openrouter.ai/deepseek/deepseek-v4.1-flash-1017/providers).

## Paste this assignment into OpenClaw

```text
You are implementing the first milestone of the Strata DeepSeek V4.1 Intel port in
https://github.com/Captain-Tripps/b70-lab . Your coding model is hosted DeepSeek V4.1
Flash 1017 through OpenRouter; OpenClaw is the harness. GPU-BOX is the Windows machine
that will build and test the port. Do the bounded work below, not just a proposal.

STARTING STATE
The plan is on docs/strata-deepseek-v41-b70-plan, draft PR #4. Fetch that branch
and read deepseek-v4/strata-v41/PLAN.md and OPENCLAW-START.md before making changes.
If it has since merged, use main containing these files; otherwise branch from
the plan branch. Create a dedicated branch named work/strata-v41-agent-runner;
if it already exists, inspect and resume it rather than resetting it. Preserve
unrelated local changes. Read applicable AGENTS.md files. Never force-push.

Read RESEARCH.md, VERIFICATION.md and evidence.json in the same directory, plus
strata-windows-port/README.md, hardware-and-windows-notes.md and bench/README.md.
Inspect existing scripts before designing replacements. b70-lab is the lab
notebook; discover the actual Strata source checkout rather than assuming this
repo contains the runtime. Upstream v0.2.6 is pinned to
4b9e05a2a806a3fe24f7b2560d98626c37dade35.

YOUR FIRST DELIVERABLE
Complete STEP-000: qualify the hosted-model tool loop and implement/test a native
Windows command runner. Then perform the read-only STEP-001 hardware/source
inventory. Stop with a reviewable commit/report before STEP-002 or GPU tests.

1. Confirm where OpenClaw and commands run. Confirm GPU-BOX by hostname, OS, repo
   path and hardware inventory. Record OpenClaw version, exact model route,
   effective reasoning setting and provider policy; record actual provider if
   exposed. If credentials or host access are missing, request only that missing
   prerequisite and continue independent source/script work. Never invent a pass.
2. Demonstrate real model tool calls: inspect/edit a disposable fixture, run an
   intentionally failing test, repair the fixture without weakening the assertion,
   rerun successfully, and use that result in a subsequent tool call. Retain
   redacted receipts proving execution and reasoning/tool-result continuity.
3. Implement the smallest reusable runner under a suitable bench subdirectory.
   It must use explicit Windows cwd/arguments, discover and initialize the actual
   MSVC/oneAPI environment, preserve exit codes, capture stdout/stderr, apply a
   timeout, and emit structured results. No arbitrary JSON-to-shell interpolation.
   Keep generated output outside tracked source; commit only small useful receipts.
4. Add exclusive GPU-test locking and owned-process cleanup, even though this
   session uses CPU-only mocks. Track PID plus creation time and executable path;
   include endpoint identity when applicable. Exercise success, nonzero exit,
   timeout with child cleanup, paths with spaces, competing lock acquisition and
   an unrelated sentinel process that must survive. Never kill by process name.
   Existing production model services must cause a busy result, not auto-unload.
5. Persist task state: branch/revision, dirty diff hash if relevant, exact commands,
   result/artifact paths, gate status, failures and next action. Verify a fresh
   agent session can resume from those files without repeating completed actions.
   If you cannot arrange a real fresh session, mark that portion NOT_RUN and give
   the exact resume instruction; do not call a file reread a session-resume pass.
6. Inventory OS build, CPU, physical/available RAM, DIMMs, recent relevant WHEA
   events, NVMe/free space, four GPU identities, driver and available PCIe telemetry.
   Inventory compiler/oneMKL/Level Zero/UR versions and existing source/model paths.
   Reconcile reported 128 GB with historical 112/95.9 GB; unknown is valid telemetry.
   Resolve the Windows fork's abbreviated 1c360526 base to a full commit. Record
   availability of same-pack CUDA/HIP reference fixtures without running large jobs.

BOUNDARIES AND ACCEPTANCE
- Target remains native Windows SYCL, JIT first, AVX2-compatible host code. Do not
  migrate inference into WSL, change drivers/BIOS, reboot, or alter production.
- No GPU workload, large model download, full CUDA translation, model swapping,
  speculative decoding, tensor parallelism or performance tuning in this session.
- No silent model/provider substitution or credential/environment dumps. Never
  commit secrets, unrestricted conversations, model weights or opaque binaries.
- Hosted DeepSeek responses are not numerical reference logits for the local
  quantized engine. Future kernel tolerances and reference tests remain independent.
- Gate results must be PASS, FAIL, NOT_RUN or BLOCKED with actual evidence. Do not
  weaken checks/tolerances or hide failures to declare success. After three failed
  attempts at the same issue without new evidence, record a minimal reproduction,
  hypotheses and the specific help needed; continue only independent work.
- This task authorizes isolated edits, CPU-only fixtures, read-only inventory,
  commits and pushing the development branch. It does not authorize merging,
  deploying, stopping production services or publishing secrets/raw host logs.

DELIVER
Commit and push the development branch. Update milestone status and link small,
redacted receipts in deepseek-v4/strata-v41; keep the ledger and reports consistent.
If the local research helper is unavailable, record manual consistency review;
do not claim its validation ran. Keep per-session state in a clearly named file.
Report commit/branch, files changed, exact commands and results, CHECK-100/101
status, blockers, and the smallest next STEP-002 action. Missing host access must
remain explicit; a Linux mock result does not qualify the Windows runner.
```

## Resume after a session boundary

```text
Resume work/strata-v41-agent-runner in Captain-Tripps/b70-lab. Read the saved task
state and receipts, inspect current git status, and continue only the unfinished
STEP-000/001 work authorized in deepseek-v4/strata-v41/OPENCLAW-START.md. Verify
prior artifacts before relying on them. Do not repeat completed actions or start
GPU work. Report whether this fresh session satisfies the resume acceptance check.
```
