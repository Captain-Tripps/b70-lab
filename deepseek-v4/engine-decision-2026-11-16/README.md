# 1017 engine decision and prebuild research (2026-11-16)

Prepared 2026-11-16, prebuild-checked (`rfb.py check --stage prebuild` -> CONTRACT_CHECKED,
[checks/CHECK-006.txt](checks/CHECK-006.txt)). Reconciles the open question "which engine runs
DeepSeek-V4.1-Flash-1017 on 4x Arc Pro B70, native Windows" against everything in this repo and
the current upstream state of the candidate engines. No build, no downloads beyond index/README/
manifest fetches, no live change; the decision awaits the owner.

- [ENGINE-DECISION.md](ENGINE-DECISION.md) - options A (Strata `dsv41` SYCL port), A' (Maya
  `ds4` SYCL port), B (llama.cpp SYCL fork, yardstick), C (own engine); the measured engine
  table, the already-decided ledger (do not re-litigate), and the recommendation: **A' with B
  retained as the yardstick**, awaiting owner sign-off. The yardstick `.bat` is in its section 8.
- [DRAFT-HEAD-FINDINGS.md](DRAFT-HEAD-FINDINGS.md) - the pre-commit gating check for A': does a
  usable drafter exist for 1017? **Cleared.** The original checkpoint ships a 3-block DSpark
  drafter (2,401 `mtp.*` tensors), the official Maya packs ship it as separate 4.3-8.0 GB files
  with tensor manifests, the ds4 engine has first-class drafter support, and the live GLM-5.3
  SYCL port already runs an MTP draft stage on these four cards.
- [RESEARCH.md](RESEARCH.md), [PLAN.md](PLAN.md), [VERIFICATION.md](VERIFICATION.md),
  [evidence.json](evidence.json), [run.json](run.json), [sources/](sources/) - the prebuild-checked
  research deliverable, copied verbatim. Do not edit these in place: the check receipt validates
  against these bytes.

Context: the 10-27 owner decision "the Strata engine port is the route"
([strata-v41/PLAN.md](../strata-v41/PLAN.md)) predates the GLM-5.3 Maya SYCL port going live on
2026-11-01 ([glm-5.3/sycl-port/](../../glm-5.3/sycl-port/)); since then the lab's proven
"new model to live on 4x B70 native Windows" pipeline has been Project Maya, and Maya already
contains a complete in-tree 1017 engine (`src/ds4/`: Engram I/O, draft placement, peer
machinery, conformance fixtures, 1017 packs on Hugging Face). This folder is a re-targeting
within the 10-27 strategy, not a reversal, so it needs the owner's explicit sign-off.

Option B's yardstick is the 2026-11-12 warm placement sweep
([DEEPSEEK-1017-PLACEMENT-SWEEP-2026-11-12.md](../../work/strata-v41-agent-runner/DEEPSEEK-1017-PLACEMENT-SWEEP-2026-11-12.md)):
pp32 0.65 / tg8 3.92 (warm; `--no-warmup -r 1` understates this build by 1.5-3x).
