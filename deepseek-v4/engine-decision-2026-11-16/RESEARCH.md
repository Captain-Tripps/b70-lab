# Research

## Project definition

Jon wants the full, unpruned DeepSeek-V4.1-Flash-1017 (552B sparse MoE, 1M context per the model card, MIT) running on **Zeus**: a Windows 25H2 machine with 4× Intel Arc Pro B70 (32 GB each, 128 GB aggregate VRAM) and 112 GB system RAM, using a GGUF model and the llama.cpp SYCL backend, Windows-native. The GPUs sit on the Windows side of the box, so WSL2/Docker is a fallback, not the primary path.

This run is **research-only** (REQ-002): the deliverable is a documented, source-backed recipe - exact binaries, model files, flags, env vars, fit math - plus an incremental implementation plan with acceptance checks. No builds, no model downloads, no live-service changes (llama-swap, services and scheduled tasks untouched). Non-goals: multi-host setups, distilled variants as the primary deliverable, non-GGUF stacks, posting anything to upstream repos.

Constraints: 128 GB VRAM plus ~100 GB usable of 112 GB RAM; a llama.cpp master checkout (`D:\llama-unmap2`, a worktree of `D:\llama-unmap`, pinned at `9fba51d2c9a1b5cb5f0c47986c031334e2d7663a`) and oneAPI 2026.0/2025.1 already exist on Zeus (EV-011).

## Assumptions and research questions

Assumptions:

- **REQ-003 (ASSUMPTION)**: prefer full GPU offload, but allow partial CPU offload where the smallest full quant does not fit entirely in 128 GB VRAM. The user did not fix the offload policy.
- ~100 GB usable of 112 GB RAM (~12 GB reserved by OS) - this drives the ~220-224 GB usable budget used in EV-012.
- The installed Arc driver (32.0.101.9175) is current enough for the B70s; no driver change during research.
- unsloth's listed file sizes are accurate for planning (not hash-verified on disk; verified at download time by CHECK-002).

Answered questions:

- **Q-001 - Does llama.cpp load DSV4.1-Flash-1017 GGUFs on SYCL, from which release?** Yes. PR #31086 ("model: DSV4.1 flash") merged 2026-10-25, so releases ≥ b11870 load V4.1 GGUFs (EV-004); release b12445, published 2026-11-16T20:44Z (~3:44 PM CT), ships the prebuilt `llama-b12445-bin-win-sycl-x64.zip` (EV-005, re-verified live via the GitHub API during the source audit).
- **Q-002 - Which full-model quant fits 128 GB VRAM + ~100 GB usable RAM?** Only unsloth **UD-IQ1_S (~233 GB)**, and only with partial CPU offload (EV-007, EV-012). Official ggml-org quants start at Q2_K_S (~298 GB) and do not fit (EV-008). The engram table is a documented size knob: IQ4_NL (110.6 GB), Q5_K (135.2 GB), Q6_K (161.3 GB) and MXFP8 (202.8 GB) variants plus `set_split.py` (EV-007).
- **Q-003 - Known B70/Xe2 SYCL blockers?** One known blocker - issue #26462, a SIGSEGV in the SYCL `set_rows` kernel on Arc from a missing f16→bf16 conversion - is fixed (EV-006); the fix was verified by reading the kernel at the pinned commit and at tag b12445 (EV-003).
- **Q-004 - 4-GPU configuration on Windows, and how proven is it?** Documented mechanism: `ONEAPI_DEVICE_SELECTOR='level_zero:*'` (or an explicit per-device list), `ZES_ENABLE_SYSMAN=1` (docs-recommended for `--split-mode layer`, enables free-memory queries), `--split-mode layer` (EV-002). The docs state tensor mode is optimized for 2 GPUs; all public B70 SYCL field reports are Linux (EV-009, EV-010), so a 4-card Windows layer split is an accepted second-order risk with fallbacks: 2+2 card pairs or 2-GPU tensor mode (EV-011 for the observed hardware).
- **Q-005 - Expected performance for the full 1017 on 4× B70?** No published number exists (EV-014). Anchors: Maya-XS distilled variant, 45.6 t/s prefill / 10.9 t/s decode @64K on an 88 GB Arc stack, Linux (EV-009); snailium smaller model, 470-490 t/s prefill / 41-46 t/s decode on B70, Docker/Linux (EV-010). Reasonable prior for the full 1017 with CPU-offloaded experts/engram: **single-digit to low-double-digit decode t/s** - measure, don't assume.

Remaining limits (coverage): performance anchors are for smaller/distilled models; the 4-card Windows layer split is not publicly documented as stable; exact KV cache size for V4.1 compressed KV at 32-64K context is not documented in any inspected source; the b12445 win-sycl zip was not unpacked (asset list and API observation only).

## References

<!-- rfb:references:start -->
| ID | Reference | Why relevant | Mismatch | License / reuse |
| --- | --- | --- | --- | --- |
| REF-001 | [https://github.com/ggml-org/llama.cpp](https://github.com/ggml-org/llama.cpp) | The runtime and SYCL backend in question: Windows support docs, multi-GPU configuration, the DSV4.1-Flash model PR, release binaries, and the known B70 crash fix. | Generic CPU backends and other GPU families (CUDA/Metal) are irrelevant to this decision; only the SYCL/Arc parts were inspected. | INSPECTED · MIT · PATTERN_ONLY |
| REF-002 | [https://huggingface.co/unsloth/DeepSeek-V4.1-Flash-1017-GGUF](https://huggingface.co/unsloth/DeepSeek-V4.1-Flash-1017-GGUF) | Community GGUF quants; provides the only full-model quant (UD-IQ1_S, 233 GB) that fits the Zeus memory budget, plus the swappable engram table. | unsloth packaging conventions differ from the official ggml-org converter; engram-swap semantics come from their README guide, not measured runs. | DECLARED_ONLY · MIT · PATTERN_ONLY |
| REF-003 | [https://huggingface.co/ggml-org/DeepSeek-V4.1-Flash-1017-GGUF](https://huggingface.co/ggml-org/DeepSeek-V4.1-Flash-1017-GGUF) | Official GGUF conversion of the model: defines the tensor layout llama.cpp expects and sets the official quant size floor (Q2_K_S ~298 GB). | Official quants are larger than the Zeus budget allows; used for layout/size reference rather than as the load candidate. | DECLARED_ONLY · MIT · PATTERN_ONLY |
| REF-004 | [https://github.com/mw00/project-maya](https://github.com/mw00/project-maya) | Field reports of DeepSeek-V4.1 GGUFs running on multi-card Intel Arc (88 GB B70+B65+B60) via llama.cpp SYCL, including the only published Arc performance numbers for the V4.1 family. | Linux, and the headline numbers are for the distilled Maya-XS variant, not the full 1017; 88 GB stack, not 128 GB. | MISSING · unknown · PATTERN_ONLY |
| REF-005 | [https://github.com/snailium/llama.cpp-sycl-intel-b70](https://github.com/snailium/llama.cpp-sycl-intel-b70) | B70-specific SYCL tuning reference (Docker image + golden config) and small-model performance numbers on the exact card model. | Docker/Linux route (rejected as primary, DEC-006); performance numbers are for a smaller model, not the full 1017. | MISSING · unknown · PATTERN_ONLY |
<!-- rfb:references:end -->

## Source index

<!-- rfb:sources:start -->
| ID / note | Primary source | Locator | Inspection |
| --- | --- | --- | --- |
| [SRC-001](sources/SRC-001.md) | [original](https://raw.githubusercontent.com/ggml-org/llama.cpp/9fba51d2c9a1b5cb5f0c47986c031334e2d7663a/docs/backend/SYCL.md) | 9fba51d2c9a1b5cb5f0c47986c031334e2d7663a · docs/backend/SYCL.md · Sections: Windows support, oneAPI setup, multi-GPU (ONEAPI_DEVICE_SELECTOR, ZES_ENABLE_SYSMAN), Intel Arc / XMX-DPAS FA, GGML_SYCL_BMG_VRAM_CHECK | INSPECTED |
| [SRC-002](sources/SRC-002.md) | [original](https://github.com/ggml-org/llama.cpp/blob/9fba51d2c9a1b5cb5f0c47986c031334e2d7663a/ggml/src/ggml-sycl/set_rows.cpp) | 9fba51d2c9a1b5cb5f0c47986c031334e2d7663a · ggml/src/ggml-sycl/set_rows.cpp · f16-&gt;bf16 conversion in the set_rows kernel path (fix for issue #26462); also verified at tag b12445 | INSPECTED |
| [SRC-003](sources/SRC-003.md) | [original](https://github.com/ggml-org/llama.cpp/releases/tag/b12445) | Release b12445 asset list: llama-b12445-bin-win-sycl-x64.zip; published 2026-11-16T20:44Z | INSPECTED |
| [SRC-004](sources/SRC-004.md) | [original](https://github.com/ggml-org/llama.cpp/pull/31086) | PR #31086 'model: DSV4.1 flash', merged 2026-10-25; first release with support b11870 | INSPECTED |
| [SRC-005](sources/SRC-005.md) | [original](https://github.com/ggml-org/llama.cpp/issues/26462) | Issue #26462: DS4F SIGSEGV on Intel Arc (B70) in SYCL set_rows; missing f16-&gt;bf16; linked fix | INSPECTED |
| [SRC-006](sources/SRC-006.md) | [original](https://huggingface.co/unsloth/DeepSeek-V4.1-Flash-1017-GGUF) | README quant table (UD-IQ1_S ~233 GB) + engram/ folder (IQ4_NL 110.6 GB, Q5_K 135.2 GB, Q6_K 161.3 GB, MXFP8 202.8 GB) + set_split.py swap guide | INSPECTED |
| [SRC-007](sources/SRC-007.md) | [original](https://huggingface.co/ggml-org/DeepSeek-V4.1-Flash-1017-GGUF) | File tree: Q2_K ~335 GB, Q2_K_S ~298 GB, dspark draft BF16 8.5 GB / MXFP4 7.9 GB, mmproj 0.5-1.0 GB | INSPECTED |
| [SRC-008](sources/SRC-008.md) | [original](https://github.com/mw00/project-maya/blob/main/docs/INTEL_ARC.md) | docs/INTEL_ARC.md · DeepSeek-V4.1 GGUF on Arc multi-card (88 GB, B70+B65+B60, Linux) via SYCL; b11870+ expects deepseek41.ple.* layout; Maya-XS 45.6 t/s prefill, 10.9 t/s decode @64K | INSPECTED |
| [SRC-009](sources/SRC-009.md) | [original](https://github.com/snailium/llama.cpp-sycl-intel-b70) | README.md · B70 golden config (DPAS/XMX FA flags); 470-490 t/s prefill, 41-46 t/s decode (smaller model, Docker/Linux) | INSPECTED |
| [SRC-010](sources/SRC-010.md) | [original](https://github.com/ggml-org/llama.cpp) | 9fba51d2c9a1b5cb5f0c47986c031334e2d7663a · D:\llama-unmap2 (git worktree of D:\llama-unmap) · Read-only probes on Zeus (100.89.126.50): Win32_VideoController CIM query, oneAPI install check, WSL2/Docker state, worktree HEAD file; scripts probe-zeus-gpu*.ps1 via zeus-run.mjs | INSPECTED |
<!-- rfb:sources:end -->

## Evidence

<!-- rfb:evidence:start -->
| ID | Claim | Class | Sources / premises | Scope |
| --- | --- | --- | --- | --- |
| EV-001 | llama.cpp's SYCL documentation names Windows as a supported platform: prebuilt win-sycl release zips bundle the SYCL runtime (no oneAPI install required at runtime for the prebuilt path), source builds use examples\sycl\win-build-sycl.bat, and Intel Arc is covered including XMX/DPAS quantized Flash Attention on Xe2 and a GGML_SYCL_BMG_VRAM_CHECK workaround flag. | VERIFIED · documented | [SRC-001](sources/SRC-001.md), REQ-001 | llama.cpp SYCL backend, Windows + Intel Arc, at commit 9fba51d2c9a1b5cb5f0c47986c031334e2d7663a |
| EV-002 | The SYCL docs describe multi-GPU selection via ONEAPI_DEVICE_SELECTOR (documented forms: 'level_zero:0;level_zero:1' for a named pair or 'level_zero:*' for all devices), recommend ZES_ENABLE_SYSMAN=1 when --split-mode is layer (enables querying free GPU memory), default multi-device runs to --split-mode layer, and state that --split-mode tensor requires flash attention, is currently optimized for 2 GPUs, and falls back to a generic all-reduce at other device counts. | VERIFIED · documented | [SRC-001](sources/SRC-001.md), REQ-001, REQ-003 | SYCL multi-GPU configuration on any supported Level Zero device |
| EV-003 | At commit 9fba51d2c9a1b5cb5f0c47986c031334e2d7663a, ggml/src/ggml-sycl/set_rows.cpp contains the f16-&gt;bf16 conversion that fixes the DeepSeek SIGSEGV reported in issue #26462 on Arc hardware; the same fix is present at tag b12445. | VERIFIED · implementation | [SRC-002](sources/SRC-002.md), REQ-001 | SYCL set_rows kernel at the pinned commit and at b12445 |
| EV-004 | PR #31086 'model: DSV4.1 flash' (merged 2026-10-25) adds DeepSeek-V4.1-Flash model support to llama.cpp, so releases from b11870 onward can load V4.1 GGUFs. | VERIFIED · documented | [SRC-004](sources/SRC-004.md), REQ-001 | Model support in llama.cpp releases &gt;= b11870 |
| EV-005 | Release b12445, published 2026-11-16T20:44Z, lists the asset llama-b12445-bin-win-sycl-x64.zip (prebuilt Windows SYCL binaries). | OBSERVED | [SRC-003](sources/SRC-003.md), REQ-001 | llama.cpp release b12445 |
| EV-006 | Issue #26462 reports a SIGSEGV in the SYCL set_rows kernel when running a DeepSeek-V4-Flash-class model on Intel Arc (B70): the kernel was missing an f16-&gt;bf16 conversion; the issue links the fix. | VERIFIED · documented | [SRC-005](sources/SRC-005.md), REQ-001 | Known B70 SYCL bug for this model family |
| EV-007 | The unsloth DeepSeek-V4.1-Flash-1017 GGUF repo offers UD-IQ1_S at ~233 GB (smallest full quant) and a separate engram/ folder with IQ4_NL (110.6 GB), Q5_K (135.2 GB), Q6_K (161.3 GB) and MXFP8 (202.8 GB) engram variants, plus set_split.py and README guidance for swapping the engram table. | VERIFIED · documented | [SRC-006](sources/SRC-006.md), REQ-001, REQ-003 | Available full-model quant options from unsloth |
| EV-008 | The official ggml-org DeepSeek-V4.1-Flash-1017 GGUF repo offers Q2_K (~335 GB) and Q2_K_S (~298 GB) full quants, a dspark draft model (BF16 ~8.5 GB / MXFP4 ~7.9 GB) and mmproj files (~0.5-1.0 GB); no smaller full quant is published there. | VERIFIED · documented | [SRC-007](sources/SRC-007.md), REQ-001 | Official full-model quant options |
| EV-009 | project-maya's INTEL_ARC.md documents DeepSeek-V4.1 GGUFs loading and running under llama.cpp SYCL on multi-card Intel Arc (88 GB: B70+B65+B60, Linux); states that releases &gt;= b11870 expect the official deepseek41.ple.* tensor layout; reports Maya-XS (distilled) at 45.6 t/s prefill and 10.9 t/s decode at 64K context. | VERIFIED · documented | [SRC-008](sources/SRC-008.md), REQ-001 | V4.1 family on Arc SYCL, distilled variant, Linux |
| EV-010 | The snailium B70 SYCL repo documents a B70 golden config with 470-490 t/s prefill and 41-46 t/s decode for a smaller model (Docker/Linux). | VERIFIED · documented | [SRC-009](sources/SRC-009.md), REQ-001 | B70 SYCL tuning and small-model performance |
| EV-011 | Zeus (Windows 25H2, Tailscale 100.89.126.50) was observed with 4x Intel Arc Pro B70 (32 GB each, 128 GB aggregate), GPU driver 32.0.101.9175, 112 GB system RAM, WSL2 Ubuntu-24.04 running with Docker Desktop stopped, oneAPI 2026.0 + 2025.1 installed, and a llama.cpp master checkout at D:\llama-unmap2 detached at 9fba51d2c9a1b5cb5f0c47986c031334e2d7663a. | OBSERVED | [SRC-010](sources/SRC-010.md), REQ-001 | Target machine state as of 2026-11-16 |
| EV-012 | The only full 1017 quant that can fit Zeus's budget (~128 GB VRAM + ~100 GB usable RAM, ~220-224 GB after OS/runtime overhead) is unsloth UD-IQ1_S at ~233 GB, and only with partial CPU offload; official Q2_K_S (~298 GB) and larger do not fit; the engram table is a documented swap knob that can free budget. | INFERENCE | EV-007, EV-008, EV-011, REQ-001, REQ-003 | Memory fit of full-model quants on Zeus |
| EV-013 | The workable port path is: prebuilt b12445 win-sycl zip (no oneAPI needed at runtime), unsloth UD-IQ1_S with the smallest acceptable engram quant, --split-mode layer across all 4 B70s via ONEAPI_DEVICE_SELECTOR and ZES_ENABLE_SYSMAN=1, and partial CPU offload for the remainder. | INFERENCE | EV-001, EV-002, EV-003, EV-004, EV-005, EV-011, REQ-001 | Adopted recipe for REQ-001 |
| EV-014 | No published number exists for the full 1017 on B70-class hardware; the available anchors (Maya-XS distilled: 10.9 t/s decode @64K on 88 GB Arc Linux; snailium smaller model: 41-46 t/s decode on B70 Docker/Linux) bound expectations from below and above, so single-digit to low-double-digit decode t/s is a reasonable prior for the full 1017 with CPU-offloaded experts/engram. | INFERENCE | EV-009, EV-010, EV-012, REQ-001 | Performance expectation only |
<!-- rfb:evidence:end -->

## Cross-project comparison

Runtime paths (REQ-001):

| Path | Deciding facts (EV IDs) | Outcome |
|---|---|---|
| llama.cpp SYCL, Windows-native | Model loading in current releases (EV-004); prebuilt win-sycl zip bundling the SYCL runtime (EV-001, EV-005); documented multi-card config (EV-002); known B70 crash fixed (EV-003, EV-006); field reports of V4.1 GGUFs on Arc (EV-009) | ADOPT (DEC-001) |
| vLLM-XPU | No DSV4.1-Flash GGUF support found in the inspected path; no per-tensor CPU offload or engram-swap equivalent; every inspected V4.1-on-Arc report is llama.cpp SYCL (EV-001, EV-004, EV-009) | REJECT (DEC-004) |
| EXL3 / exllamav3 | CUDA-only; no Intel SYCL/Level Zero backend found in the inspected version (EV-001, EV-008) | REJECT (DEC-005) |
| WSL2/Docker Linux SYCL | B70 SYCL path proven in Docker (EV-010), but 4-card Arc visibility through WSL2 is unverified and Docker Desktop is stopped on Zeus (EV-011); GPUs sit on the Windows side (EV-011) | REJECT as primary, kept as tuning reference + fallback (DEC-006) |

Quant providers (REQ-001, REQ-003): unsloth UD-IQ1_S at ~233 GB is the only full quant below the ~224 GB usable budget and the only provider of the engram-swap knob (EV-007, EV-012); ggml-org Q2_K_S ~298 GB / Q2_K ~335 GB define the official layout reference and the size floor that does not fit (EV-008, EV-012).

Performance anchors (REQ-001): project-maya is the only published V4.1-family Arc run (distilled variant, 88 GB, Linux - EV-009); snailium is the only card-specific B70 tuning reference (smaller model, Docker - EV-010). Neither prices in CPU offload of the full 1017, so both only bound the prior (EV-014).

## Adopted, rejected and deferred patterns

<!-- rfb:decisions:start -->
| ID | Choice | Outcome | Evidence | Reason / complexity | Revisit |
| --- | --- | --- | --- | --- | --- |
| DEC-001 | llama.cpp SYCL backend, Windows-native, prebuilt win-sycl b12445 (source build from D:\llama-unmap2 via examples\sycl\win-build-sycl.bat as fallback) | ADOPT | EV-001, EV-002, EV-003, EV-004, EV-005, EV-006, EV-009, EV-011, EV-013 | Only path with (a) DSV4.1-Flash model support in current releases, (b) a Windows SYCL prebuilt that needs no oneAPI at runtime, (c) documented multi-GPU configuration, (d) the known B70 crash fixed, and (e) a field report of V4.1 GGUFs running on Arc. Complexity: Low: download, two env vars, a few flags; no compilation unless the prebuilt fails. | If the prebuilt b12445 zip fails to enumerate all 4 cards or crashes, fall back to a source build of D:\llama-unmap2 with win-build-sycl.bat (same backend, oneAPI already installed). |
| DEC-002 | unsloth UD-IQ1_S full quant (~233 GB) with swappable engram table (start with bundled default; swap to IQ4_NL 110.6 GB via set_split.py if RAM is tight) | ADOPT | EV-007, EV-008, EV-011, EV-012 | The only full quant below the usable budget; the engram swap is a documented knob that can recover tens of GB if the default engram quant is large. Complexity: Low: one ~233 GB download plus one optional engram-swap step. | If UD-IQ1_S quality is unacceptable or the fit fails after engram swap, move to a smaller engram quant, a smaller context, or the distilled variant. |
| DEC-003 | 4x B70 with --split-mode layer, ONEAPI_DEVICE_SELECTOR='level_zero:*', ZES_ENABLE_SYSMAN=1 (docs-recommended for layer mode), q8_0 KV cache, 32K starting context, maximum GPU offload | ADOPT | EV-002, EV-011, EV-013 | The documented multi-GPU configuration; q8_0 KV keeps the 32K cache small; 32K is a starting point chosen against the tight KV budget, not a ceiling. Complexity: Low: flags and env vars only. | If the 4-card layer split is unstable (crash, lopsided load), try 2+2 card pairs (two independent 2-GPU servers) or --split-mode tensor (documented 2-GPU-optimized tensor mode, requires flash attention); if 32K KV does not fit, drop to 16K. |
| DEC-004 | vLLM with the XPU (Intel GPU) backend | REJECT | EV-001, EV-004, EV-009 | No DeepSeek-V4.1-Flash GGUF support found in the inspected vLLM-XPU path, and no per-tensor CPU offload / engram swap equivalent; every inspected field report of V4.1 on Arc is llama.cpp SYCL. Complexity: Higher: XPU plugin stack, safetensors conversion, no GGUF path. | If vLLM-XPU lands DSV4.1-Flash plus MoE CPU offload on Arc and higher throughput is needed. |
| DEC-005 | EXL3 (exllamav3) quantization/runtime | REJECT | EV-001, EV-008 | EXL3 targets CUDA GPUs; no Intel SYCL/Level Zero backend was found in the inspected version, so it cannot run on the B70s at all. Complexity: Not applicable on this hardware. | An EXL3 Intel backend appears that supports DSV4.1-Flash. |
| DEC-006 | WSL2/Docker Linux SYCL route (snailium B70 image) | REJECT | EV-001, EV-010, EV-011 | The GPUs sit on the Windows side; 4-card Arc visibility through WSL2 is not publicly verified, Docker Desktop is currently stopped, and the Windows-native path is documented and one layer closer to the hardware. The snailium config remains useful as a tuning reference (flags), which is why it stays in the ledger. Complexity: Medium: WSL2 GPU setup, 4-card visibility, ~343 GB of downloads inside WSL. | If the Windows-native 4-card layer split proves unstable and WSL2 shows all 4 cards with ZES_ENABLE_SYSMAN=1. |
| DEC-007 | ggml-org Q2_K_S (~298 GB) / Q2_K (~335 GB) as the primary quant | REJECT | EV-008, EV-011, EV-012 | 298-335 GB exceeds the ~224 GB usable budget even with maximal CPU offload; higher quality than UD-IQ1_S but it does not fit this machine. Complexity: Not applicable - does not fit. | More VRAM (e.g. an 8-card build) or a smaller active-footprint configuration that makes Q2_K_S viable. |
| DEC-008 | Maya-XS distilled 88 GB variant | DEFER | EV-009, EV-012 | Fits in 2-3 of the 4 cards with a published speed (10.9 t/s decode @64K), but it is a distilled model, not the full 1017 the user asked for; keep as fallback if UD-IQ1_S proves too slow or too weak. Complexity: Low: one ~88 GB download. | Measured decode on the full 1017 below ~5 t/s, or the user accepts a distilled model for speed. |
<!-- rfb:decisions:end -->

### Rejected patterns

- **vLLM-XPU (DEC-004)**: no DSV4.1-Flash GGUF support found in the inspected path, and no per-tensor CPU offload / engram-swap equivalent; every inspected field report of V4.1 on Arc is llama.cpp SYCL. Revisit if vLLM-XPU lands DSV4.1-Flash plus MoE CPU offload on Arc.
- **EXL3 (DEC-005)**: CUDA-only in the inspected version - it cannot run on the B70s at all. Revisit on an Intel backend that supports DSV4.1-Flash.
- **WSL2/Docker SYCL (DEC-006)**: the GPUs sit on the Windows side, 4-card Arc visibility through WSL2 is not publicly verified, and Docker Desktop is currently stopped; its golden config remains a tuning reference, which is why the repo stays in the ledger. Revisit if the Windows-native 4-card split proves unstable and WSL2 shows all 4 cards with `ZES_ENABLE_SYSMAN=1`.
- **ggml-org Q2_K_S / Q2_K (DEC-007)**: 298-335 GB exceeds the ~224 GB usable budget even with maximal offload. Higher quality, but the wrong size class for this machine. Revisit on more VRAM.
- **Deferred - Maya-XS distilled 88 GB (DEC-008)**: fits 2-3 of the 4 cards with a published 10.9 t/s decode @64K, but it is a distilled model, not the full 1017 Jon asked for. Fallback if the full model measures below ~5 t/s decode.

## Risks, licenses and unknowns

Risks:

1. **4-card Windows layer split is a second-order case.** The docs optimize tensor mode for 2 GPUs (EV-002) and every public B70 field report is Linux (EV-009, EV-010). Mitigations: the documented fallbacks from DEC-003 (2+2 pairs, tensor mode, drop context 32K→16K) and the WSL2 route (DEC-006 revisit).
2. **The memory margin is tight.** UD-IQ1_S ~233 GB against ~224 GB usable (EV-012), and the KV cache size for 32-64K compressed KV is undocumented. Mitigations: q8_0 KV, 32K starting context, and the engram swap to a smaller quant (IQ4_NL is 110.6 GB; the bundled default's quant is not recorded in the inspected sources, so its on-disk size should be read at download time - CHECK-002 - before deciding whether to swap).
3. **Speed is a prior, not a promise** (EV-014): single-digit to low-double-digit decode t/s is plausible with CPU offload, and nothing inspected prices the offload penalty. If measured decode is below ~5 t/s, DEC-008's distilled fallback becomes the practical option.
4. **Prebuilt zip is a single undocumented-precision build.** The win-sycl asset has no fp16/fp32 suffix (unlike the Linux SYCL assets, which ship both); build precision is not stated on the release page (EV-005 limitation). If the prebuilt fails, the source-build fallback via `D:\llama-unmap2` + `examples\sycl\win-build-sycl.bat` is ready (oneAPI 2026.0/2025.1 installed, EV-011).

Licenses: llama.cpp is MIT - INSPECTED at the pinned commit ("MIT License, Copyright (c) 2023-2026 The ggml authors", REF-001). The unsloth and ggml-org model repos declare MIT (DECLARED_ONLY; full text not read; weights consumed by llama.cpp, no code reuse). project-maya and snailium had no LICENSE inspected at access time (MISSING); they were read for facts and numbers only, nothing reused. Reuse mode is PATTERN_ONLY across all references; no code was copied into this run.

Inspection scope: 10 sources inspected (SRC-001..SRC-010), including two pinned-commit file inspections on the Zeus local checkout (SYCL.md, set_rows.cpp), one live GitHub API re-verification (b12445 assets), two HF model-card/file-tree inspections, three GitHub doc/PR/issue inspections, two community field reports, and one read-only host observation. Zeus probes were read-only; nothing was installed, started or modified.

Unknowns (mirrored in checks/CHECK-006.txt): KV cache size at 32-64K compressed KV; 4-card Windows layer-split stability; win-sycl zip contents and build precision; full-1017 decode speed with CPU offload; engram-swap semantics (README, not measured); WMI AdapterRAM 32-bit cap (per-card 32 GB from the card model).
