# Implementation Plan

## Goals and non-goals

Goal: a source-backed, repeatable recipe - plus an incremental build plan - for
running DeepSeek-V4.1-Flash-1017 (GGUF) on Zeus's four Intel Arc Pro B70 cards
(4x32 GB VRAM) from **Windows-native SYCL**, served by llama.cpp. Non-goals:
any implementation work (no builds, no downloads, no live-service changes),
WSL2/Docker as the primary runtime (DEC-006), vLLM-XPU (DEC-004), EXL3
(DEC-005), and the ggml-org full quants that do not fit the memory budget
(DEC-007).

## Architecture and components

Smallest coherent design, all decisions traceable to DEC IDs in
`evidence.json`:

- **Runtime** (DEC-001): the prebuilt
  `llama-b12445-bin-win-sycl-x64.zip` from llama.cpp releases, unpacked to
  `D:\llama-sycl-b12445`. The zip bundles the oneAPI/SYCL dlls it depends on,
  so no separate oneAPI install is required to run it. Fallback if the
  prebuilt fails: source build from the pinned worktree `D:\llama-unmap2`
  (commit `9fba51d2c9a1b5cb5f0c47986c031334e2d7663a`, already verified to
  contain the B70 `set_rows` BF16 fix from issue #26462) via
  `examples\sycl\win-build-sycl.bat`.
- **Model** (DEC-002): `unsloth/DeepSeek-V4.1-Flash-1017-GGUF`, UD-IQ1_S
  (~233 GB) as the only full quant inside budget. Its engram table is
  swappable (e.g. IQ4_NL at ~110.6 GB) with unsloth's `set_split.py` if the
  combined model+engram+KV does not fit.
- **Multi-GPU** (DEC-003, corrected at source audit): four-card
  `--split-mode layer` with `ONEAPI_DEVICE_SELECTOR='level_zero:*'` (the
  documented form; not `level_zero:0;1;2;3`), `ZES_ENABLE_SYSMAN=1`
  (docs-recommended for layer mode because layer split queries free memory
  per device), `--cache-type-k/q v q8_0`, 32K starting context, max offload.
  Fallbacks in order: 2+2 card pairs (two servers), or 2-GPU tensor mode -
  the only split mode the docs say is specifically optimized; other device
  counts fall back to a generic all-reduce. Note: `--split-mode row` was a
  2024.3 changelog item and is **not** in the current SYCL split-mode table;
  it was removed as a fallback at audit.
- **Model support gate** (EV-006): DeepSeek-V4.1 support landed in PR #31086,
  merged 2026-10-25, so releases at or after b11870 are eligible; b12445
  (published 2026-11-16) satisfies this.

## Data model and interfaces

No data model - this is a served-model deployment, not a new application.
The only interfaces are:

- **In:** llama-server HTTP API (OpenAI-compatible `/v1/*`) on localhost, and
  CLI flags for llama.cpp (`-m`, `--split-mode`, `--n-gpu-layers`,
  `--ctx-size`, `--cache-type-*`). No custom code is written.
- **Out:** HTTP JSON responses.
- **Environment contract:** the two env vars from DEC-003
  (`ONEAPI_DEVICE_SELECTOR`, `ZES_ENABLE_SYSMAN`) plus nothing else.
- Non-applicable: persistence, auth, external clients (localhost only for the
  first bring-up; llama-swap wiring is a separate later step and out of scope
  for this research deliverable).

## Security and deployment

- Deploy target: Zeus (Windows 25H2), localhost service, read-only model
  files under `D:\models\DeepSeek-V4.1-Flash-1017`.
- Downloads are size-verified on arrival (HF reports exact file sizes; the
  full 1017 UD-IQ1_S is ~233 GB plus a swappable engram file) - no model is
  trusted until its byte count matches the repo card.
- No secrets are introduced. No live services are touched: llama-swap, the
  existing llama.cpp runtime, and scheduled jobs stay exactly as-is until
  Jon approves integration (per the public-posts-and-live-changes rules).
- Memory budget (assumption A-001): 128 GB VRAM + ~100 GB usable of the
  112 GB system RAM, i.e. ~220-224 GB usable total. The 233 GB UD-IQ1_S
  therefore cannot fit fully on GPU: partial offload to system RAM is the
  expected steady state, which is why the decode-speed prior is only
  "single-digit to low-double-digit tokens/s" (EV-014).

## Milestones and acceptance checks

<!-- rfb:plan:start -->
| ID | Outcome | Requirements | Decisions | Acceptance |
| --- | --- | --- | --- | --- |
| STEP-001 | Working Windows SYCL runtime on Zeus: llama-b12445-bin-win-sycl-x64.zip downloaded, extracted to D:\llama-sycl-b12445, llama-server.exe runs and reports its version with the bundled SYCL runtime. | REQ-001 | DEC-001 | CHECK-001 |
| STEP-002 | Model on disk: unsloth UD-IQ1_S main GGUF plus the bundled engram file (and the IQ4_NL engram variant for swap) downloaded to D:\models\DeepSeek-V4.1-Flash-1017, sizes matching the repo listing. | REQ-001, REQ-003 | DEC-002 | CHECK-002 |
| STEP-003 | 4-card server running: ONEAPI_DEVICE_SELECTOR='level_zero:*' + ZES_ENABLE_SYSMAN=1 set; llama-server starts with --split-mode layer, -c 32768, --cache-type-k q8_0 --cache-type-v q8_0, max offload; log shows all four level_zero devices with VRAM and the model loads; a test prompt returns coherent output. | REQ-001, REQ-003 | DEC-001, DEC-003 | CHECK-003 |
| STEP-004 | Measured baseline: prefill/decode t/s and per-device VRAM recorded for the fixed test prompt; if the default engram overflows, set_split.py swaps it to IQ4_NL and the run is remeasured. | REQ-001, REQ-003 | DEC-002, DEC-003 | CHECK-004 |
| STEP-005 | Handoff document written for Jon: exact binary/files, flags, env vars, measured speeds, fit math, known issues and the fallback triggers from DEC-001/DEC-002/DEC-003. | REQ-002 | DEC-001 | CHECK-005 |
<!-- rfb:plan:end -->

## Testing and verification

Acceptance is defined by the checks in `evidence.json` (table above):

- **CHECK-001** runtime sanity: the b12445 win-sycl zip extracts to a
  runnable `llama-server.exe` with the SYCL runtime DLLs present.
- **CHECK-002** model on disk: UD-IQ1_S main (~233 GB) and the engram files
  (bundled default plus the IQ4_NL ~110.6 GB variant) match the HF repo
  listing - this also reads the default engram's real size, which is the
  open unknown that drives the DEC-002 swap decision.
- **CHECK-003** 4-card load: server enumerates four level_zero devices,
  loads UD-IQ1_S with `--split-mode layer`, and serves a test prompt with
  coherent output (documented sampling: temperature 1.0, top_p 1.0).
- **CHECK-004** measured baseline: prefill/decode t/s and per-device VRAM
  for the fixed test prompt; if the default engram overflows, swap it to
  IQ4_NL with `set_split.py` and re-measure. Decode below ~5 t/s triggers
  the DEC-008 fallback (Maya-XS distilled 88 GB build).
- **CHECK-005** handoff document: exact binaries/files, flags, env vars,
  measured speeds, fit math, known issues, fallback triggers.
- **CHECK-006 SOURCE_AUDIT** (already PASS, 2026-11-16, see
  `checks/CHECK-006.txt`): every critical claim re-verified against the
  pinned commit, SYCL docs, and live GitHub API; two ledger inaccuracies
  found and corrected (selector form, ZES_ENABLE_SYSMAN wording) and one
  fallback replaced (row mode -> 2+2/tensor).

Checks 001-005 are NOT_RUN in this research-only handoff and have empty
receipt fields; they become executable as soon as the download step is
approved.
