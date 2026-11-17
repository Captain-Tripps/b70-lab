# Verification

## Outcome

Research-only handoff. Nothing was built, downloaded, or installed, and no
live service (llama-swap, the Zeus llama.cpp runtime, scheduled jobs) was
touched. The deliverable is the evidence ledger (`evidence.json`), ten source
notes, and the recipe + plan above, all traceable to primary sources.

## Actual checks

<!-- rfb:checks:start -->
| ID | Criterion | Result | Method | Evidence | Tested snapshot |
| --- | --- | --- | --- | --- | --- |
| CHECK-001 | The b12445 win-sycl zip extracts to a runnable llama-server.exe with SYCL runtime DLLs present. | NOT_RUN | COMMAND | — | — |
| CHECK-002 | Model files on disk match the HF repo listing (UD-IQ1_S main ~233 GB; engram variant present, IQ4_NL ~110.6 GB). | NOT_RUN | COMMAND | — | — |
| CHECK-003 | llama-server enumerates 4 level_zero devices, loads UD-IQ1_S with --split-mode layer, and serves a test prompt with coherent output. | NOT_RUN | COMMAND | — | — |
| CHECK-004 | Prefill/decode t/s and per-device VRAM are recorded for the fixed test prompt; if the default engram overflows, the IQ4_NL engram swap (set_split.py) loads and is remeasured. | NOT_RUN | COMMAND | — | — |
| CHECK-005 | Handoff document exists with binary/file list, flags, env vars, measured speeds, fit math, known issues and fallback triggers. | NOT_RUN | MANUAL | — | — |
| CHECK-006 | Key ledger claims (EV-001..EV-011) re-audited against their original sources; no contradictions found; open unknowns recorded. | PASS | SOURCE_AUDIT | [output](checks/CHECK-006.txt) | evidence.json v1 + sources/ notes, 2026-11-16; primary re-verification against D:\llama-unmap2 at pinned commit and GitHub API for b12445 |
<!-- rfb:checks:end -->

## Tested implementation and deviations

There is no implementation to test yet, so there is no tested snapshot.
The only "snapshot" in play is the pinned llama.cpp commit
`9fba51d2c9a1b5cb5f0c47986c031334e2d7663a` in the Zeus worktree
`D:\llama-unmap2`, which was **read** (not run) to verify:

- the B70 `set_rows` BF16 dispatch fix from issue #26462
  (`ggml/src/sycl/set_rows.cpp`, F16 dispatch at lines 560-575, BF16 case
  at 344-353), and
- the SYCL documentation claims used in DEC-003 (OS table, prebuilt
  Windows package, `win-build-sycl.bat`, selector forms, tensor-mode 2-GPU
  note, `ZES_ENABLE_SYSMAN` recommendation for layer mode).

Deviations from the original plan - both found **by the source audit itself
(CHECK-006), before this handoff**, so the plan is consistent with them:

1. `ONEAPI_DEVICE_SELECTOR` documented forms are
   `"level_zero:0;level_zero:1"` and `"level_zero:*"`; the earlier
   `level_zero:0;1;2;3` shorthand was not in the docs. Corrected in
   EV-002, Q-004, DEC-003, STEP-003, CHECK-003.
2. `ZES_ENABLE_SYSMAN=1` is docs-*recommended* for `--split-mode layer`
   (layer split queries free memory per device), not merely optional.
   Reworded in EV-002 and DEC-003; and the DEC-003 fallback changed from
   `--split-mode row` (a 2024.3 changelog item, absent from the current
   SYCL split-mode table) to 2+2 card pairs or 2-GPU tensor mode.

## Rejected/deferred complexity review

- **vLLM-XPU (DEC-004)** rejected: Windows-native SYCL support is not the
  mature path the Arc docs describe; llama.cpp SYCL is the documented
  Windows route.
- **EXL3 (DEC-005)** rejected: no SYCL/Windows runtime; wrong ecosystem for
  this hardware.
- **WSL2/Docker (DEC-006)** rejected as primary: the GPUs are on the
  Windows side; a WSL2 SYCL stack adds a driver boundary the docs do not
  cover for this config.
- **ggml-org full quants (DEC-007)** rejected on budget: 298-335 GB exceeds
  ~224 GB usable.
- **Maya-XS distilled 88 GB (DEC-008)** deferred, not rejected: it is the
  fallback if the full 1017 decodes below ~5 t/s (CHECK-005).

## Not run and practical limits

- CHECK-001 through CHECK-005 are NOT_RUN (empty receipt fields); they
  require the approved download step and a window on Zeus's GPUs.
- Speed is a **prior, not a measurement**: single-digit to low-double-digit
  decode t/s for the full 1017 with CPU offload (EV-014). Anchors:
  Maya-XS 88 GB on Arc (Linux) at 45.6/10.9 t/s @64K; snailium's B70
  reports at 470-490/41-46 t/s on a much smaller model.
- The 4-card Windows layer split is **unproven in field reports** - all
  public multi-GPU Arc reports are Linux. That is the largest open risk.
- KV size at 32-64K ctx and the engram file's default-quant size are open
  unknowns, to be read from the model repo card at download time (they
  drive the DEC-002 engram-swap decision, CHECK-004).
- The b12445 win-sycl zip's fp16/bf16 handling is **undocumented**: the
  Linux SYCL assets ship fp16/fp32 variants; the Windows asset is a single
  build (verified live via GitHub API at audit time).
