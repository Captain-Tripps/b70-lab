# Engine decision — DeepSeek V4.1-Flash-1017 on 4×B70 Windows

Prepared 2026-11-16. Reconciles the open question "run Strata / extend llama.cpp SYCL / own engine"
against everything in `Captain-Tripps/b70-lab` (local clone read in full) and the current upstream
state of the candidate engines. This is a decision input for Jon, not a build plan.

## TL;DR

- The 2026-10-27 owner decision ("the Strata engine port is the route and llama.cpp is a dead end")
  **predates the GLM-5.3 Project-Maya SYCL port going live (2026-11-01)**. Since then the lab's
  proven "new model → live on 4×B70 native Windows" pipeline has been **Project Maya**, not Strata.
- **Project Maya already contains a DeepSeek V4.1-Flash-1017 engine** (`src/ds4/`, CUDA/HIP):
  Engram I/O, draft/MTP placement, peer/multi-GPU machinery, 1017 conformance fixtures, and a
  1017 Maya-GGUF pack on Hugging Face. The GLM port shows the exact port shape needed:
  36 numbered fix rounds, SYCLomatic/dpct, a reproducible recipe, and daily optimization since 11-01.
- The decision is therefore not "Strata vs llama.cpp" but:
  - **A — Strata `dsv41` SYCL port** (the planned, gated path; multi-GPU tier is a stub in its SYCL port)
  - **A′ — Maya `ds4` SYCL port** (new; same shape as the live GLM port; 4-card design already demonstrated)
  - **B — keep tuning the llama.cpp SYCL fork** (the measured yardstick; structural ceiling)
- **Recommendation: A′, with B retained as the yardstick** (the warm llama.cpp baseline is the ruler
  every port result must beat). Open questions for Jon are in §7.

## 1. The engine landscape today (all measured on Zeus, 4× Arc Pro B70, Windows)

| Engine (tree) | Model | Setup | Decode | Prompt | Status |
|---|---|---|---|---|---|
| llama.cpp SYCL fork (`C:\llamacpp-v41` @ `de5122d`) | V4 0731, 284B UD-Q2_K_XL | 4 cards, 131k ctx, DSpark | 26-30 tok/s | 699 @33.6k / 570 @107k | **live** |
| llama.cpp SYCL fork | **V4.1-1017, 552B IQ2_XXS 128.75 GiB** | `-ngl 38 -sm layer -t 12`, warm | **3.92 tg8** | **0.65 pp32** | loads & generates; Engram (103 GiB) **not loaded**; no drafter |
| Strata Windows port (`b70-night-20261016` @ `1c360526` + 4 patches) | Qwen3.8-Flash-Next IQ3_S 84 GB | 2 cards, EP, 200k ctx, int8 KV, `--prefill 8192`, JIT | **~106 tok/s** | ~1.4-2.7K tok/s | live |
| **Project Maya SYCL port** (v1.1.44 @ `5d20b0e8` + 36 fix rounds) | **GLM-5.3-Flash**, all experts VRAM-resident, 128k | **4 cards, layer split + 2-stage MTP decode** | **45.5-45.8** (768-tok MTP runs); 39-40 @8k; 26.5 @100k | **966-996 @8k; ~1,180 @100k** | **live since 2026-11-01, optimized daily through 11-16** |

Notes:

- The 1017 llama.cpp numbers are the **warm** ones from the 2026-11-12 placement sweep
  (`DEEPSEEK-1017-PLACEMENT-SWEEP-2026-11-12.md`): `--no-warmup -r 1` understates this build by
  1.5-3×. Any new yardstick must use warmup + `r>=2`.
- The GLM Maya port is a hybrid: it reuses the llama.cpp fork's grouped XMX GEMM for the prompt
  path's experts. Mixing engines is established lab practice.
- GLM-5.3's previous live entry was the llama.cpp fork (g10): 24-25 tok/s decode, 309 tok/s prompt.
  The Maya port is ~1.9× decode and ~3× prompt on the same model file.

## 2. What b70-lab already decided (do not re-litigate)

| Date | Decision | Record |
|---|---|---|
| 2026-10-17 | Expert parallelism for V4 0731 **rejected** after profiling: ceiling 1.12× plain / 1.19× DSpark, below the 1.4× go line. Any new EP proposal for 1017 must show why 1017 differs. | `deepseek-v4/PLAN-expert-parallel.md`, `STATUS.md` |
| 2026-10-26/27 | **"The Strata engine port is the route and llama.cpp is a dead end"** — owner-confirmed. Gated plan `strata-v41` (STEP-000…006) prepared, status planned/not started. Port scope measured: `src/dsv41/` ≈ 16.4k lines CUDA/HIP, 93 kernels; dpct pilot converts ~85% automatically (14 launch sites + 2 kernels by hand; WMMA/XMX sparse attention is real design work). | `deepseek-v4/strata-v41/PLAN.md`, `PORT-SCOPE.md` |
| 2026-11-01 | GLM-5.3 switched live from the llama.cpp fork to the **Maya SYCL port**. | `glm-5.3/sycl-port/README.md` |
| 2026-11-05 | 1017 Engram-converted GSQ-RCO pack loads and generates on the llama.cpp fork (1.505 decode / 10.287 prompt smoke). | `deepseek-v4/strata-v41/RESULTS-2026-11-05.md` |
| 2026-11-12 | 1017 placement sweep: warm baseline 0.65 pp32 / 3.92 tg8; prefill is the bottleneck (batched stage runs on effectively one device: 956 MiB compute on SYCL0 vs ~46 on the others); disk-streaming theory dead; SYCL graph capture refused on multi-device; Engram never loaded; 1.73× read amplification at load. | `work/strata-v41-agent-runner/DEEPSEEK-1017-PLACEMENT-SWEEP-2026-11-12.md` |

**The gap this reconciliation exposes:** the 10-27 Strata decision was made before the GLM Maya port
existed. `strata-v41/PLAN.md` (last updated 11-05) and the sweep (11-12) do not reference it, and
`strata/src/dsv41/` remains "0 lines ported". Meanwhile the Maya track has been the lab's most
productive engine work for two weeks (daily CHANGELOG entries 11-13…11-16).

## 3. Option A — Strata `dsv41` SYCL port (the planned path)

**Already done:** gated plan; dpct pilot (~85% auto-convert; the one failure mode is macro-wrapped
launches — mechanical); v0.2.7 tree builds on Windows (JIT) and runs Qwen; the 18 Windows fixes are
catalogued as a reference, not a patch (they don't apply to v0.2.7).

**What's missing, and why it matters for 1017:**

1. **Multi-GPU tier.** The v0.2.7 SYCL port's `--peer-device` (second-GPU expert tier) is a **stub**
   (`remote_expert_opt_stub.cpp`); the Qwen smoke run on the fresh build was single-card at
   12.95 tok/s. The 1017 pack (128.75 GiB) needs all four cards. The old win-port line has working
   2-card EP but is 2,389 commits behind v0.2.7, and its EP design targets 2 cards, not 4.
2. **Engram.** Strata SYCL has `ngram/` + `--ple-io mmap` (used by Flash-Next), but that is the Qwen
   PLE path; the dsv41 Engram (103 GiB on disk; upstream's 2-bit sets are ~111 GB) needs dsv41
   wiring and pack-builder support.
3. **Base-tree fork.** v0.2.7 (newer, builds, peer tier stubbed) vs win-port (2-card EP works, far
   behind upstream). Unresolved in the plan.
4. The Strata Windows track has been static since 2026-10-17 (Flash-Next numbers unchanged).

## 4. Option A′ — Maya `ds4` SYCL port (revealed by this reconciliation)

**Why it exists as an option:** Maya (`mw00/project-maya`) ships a complete DeepSeek
V4.1-Flash-1017 engine in-tree:

- `src/ds4/` — `ds4_model.cu`, `ds4_kernels.cu`, `ds4_iq.cu`, `ds4_gguf.cu`, plus
  `ds4_engram_io.hpp` (Engram), `ds4_draft_placement.hpp` (MTP/draft), `ds4_peer_calibrate.cu` /
  `ds4_par_exp.h` (peer/multi-GPU), `ds4_vision.cu`.
- `./setup.sh --model DeepSeek-V4.1-Flash-1017`; 1017 conformance fixtures
  (`serve/fixtures/deepseek_v41/`, DeepSeek's own encoding tests); CHANGELOG performance entries for
  V4.1-Flash decode (e.g. 36.8 → 43.5) and prompt (293 → 901 tok/s) on other hardware.
- 1017 packs on HF: `peasantsmith/DeepSeek-V4.1-Flash-1017-Maya-GGUF` (a "maya-xs" variant) and
  turboderp's EXL3 2.25 bpw 1017.

**Why it is the strongest path:**

1. **The port template is fresh and proven.** The GLM Maya SYCL port went from first build to live in
   one week (10-31 → 11-01), then held ~45.5 tok/s decode + ~1K tok/s prompt read on four cards, with
   a reproducible recipe (run from an empty folder on 11-16, logits byte-identical) and daily
   kernel-level optimization since. The 36 fix rounds and the documented Windows rules are the
   playbook for doing the same to `ds4`.
2. **The 4-card design is already demonstrated.** GLM runs layer split + 2-stage MTP decode on all
   four cards (head/tail split, draft on the head while the tail verifies). That is the design a
   128.75 GiB 4-card 1017 run needs. Expert parallelism was rejected after profiling on both 0731
   and GLM, which is consistent with not betting on it for 1017.
3. **The model support is in-tree, not to be invented.** Engram I/O, draft placement, peer
   machinery, conformance fixtures — the CUDA/HIP reference already implements 1017. The port is
   "make Maya's existing 1017 engine run on SYCL/Windows", the same shape as the GLM port.
4. **The kernel surface is the same lineage.** `ds4` and Strata's `dsv41` share file names
   (`ds4_model.cu`, `ds4_kernels.cu`, `ds4_iq.cu`, `ds4_gguf.cu`, `ds4_vision.cu`); the dpct
   findings, the 2,020-marker debt calibration, and the Windows build substrate knowledge transfer
   either way.
5. The target (≥50 tok/s decode) sits just above the demonstrated GLM number (45.5) with two weeks
   of optimization still in front, and the same engine family has done 106 on Strata (Flash-Next).

**Unknowns to resolve before committing (all checkable cheaply):**

- Does the 1017 Maya pack include a draft/MTP head usable by the 2-stage decode? (The llama.cpp
  lab pack has zero `mtp.*`; `ds4_draft_placement` may assume a draft that doesn't exist for 1017.)
- 1017 Maya-GGUF pack size/format vs the 128 GiB VRAM budget, and where the Engram lives
  (`ds4_engram_io` + `--ple-io`-equivalent; the 103 GiB IQ4_NL Engram file is on disk).
- Which Maya base: v1.1.44 @ `5d20b0e8` (pinned by the GLM port) or a newer release; whether the
  `ds4` engine moved since.
- `ds4`'s multi-GPU design on reference hardware (APU/GPU-box) vs the GLM layer-split+2-stage design
  the lab actually runs on Windows.

## 5. Option B — keep tuning the llama.cpp SYCL fork

**Where it stands (warm, 11-12 sweep):** pp32 0.65 / tg8 3.92. Prefill is ~6× slower than decode,
and the batched prefill stage puts 956 MiB of compute on SYCL0 and ~46 MiB on each other device —
it runs on effectively one device. Decode is 307 ms/token = launch-overhead bound; weights are
resident (decode reads ~30 MB/s from disk); the model sits at 96% VRAM occupancy (KV 10 MiB at
2048 ctx).

**Open, cheap leads (from the sweep §8):** the prefill single-device arm (highest value),
`GGML_SYCL_DEV2DEV_MEMCPY=1` (arm K, staged — Windows stages dev2dev through host memory by
default), `-ngl 39/40` dose-response, the 1.73× load read-amplification fix.

**The structural ceiling:** SYCL graph capture is hard-refused on multi-device
(`check_graph_compatibility`, `ggml-sycl.cpp:6860`); the graph-cache path is tensor-split-only and
"layer split stays for the 3-4 card MoE models"; layer split does not aggregate bandwidth. Closing
a 12.8× decode gap (3.92 → 50) on this path means reworking llama.cpp's multi-device SYCL backend —
upstream issues #31871, #31313, #31505, #30944, #31292 remain open. And 1017 there is still
incomplete: Engram skipped (103 GiB unused), no drafter, ~2-bit quant.

**What B is for:** the yardstick. The warm baseline is reproducible (the sweep has the exact
`.bat`/flags and the launch gotchas) and is the ruler every port result must beat. B is also where
the live 0731 daily driver runs — it is not going away.

## 6. Option C — own engine

Largely subsumed. The Maya SYCL port **is** an own-engine in practice: a third-party engine
portable-ported, 36 fix rounds, daily kernel work, a recipe. Strata Windows port likewise. A fourth
from-scratch engine would be a multi-month bet starting at zero 1017 progress.

## 7. Recommendation and open questions

**Recommendation: A′ (Maya `ds4` SYCL port for 1017), with B retained as the yardstick.**

Rationale in one line: the lab's proven 4-card Windows porting pipeline is Maya, Maya already
implements 1017 (Engram, draft, conformance), the GLM port demonstrates the exact target envelope,
and the planned Strata path has an unresolved 4-card multi-GPU gap in its SYCL port.

This is a **re-targeting within the 10-27 strategy** ("port the model to a dedicated SYCL engine,
llama.cpp is the dead end/yardstick"), not a reversal — but it does move the named engine from
Strata to Maya, so it needs Jon's explicit sign-off.

**Questions for Jon:**

1. **A′ vs A:** re-target the strata-v41 workstream to Maya `ds4`, or keep the Strata plan as
   written? (If A: the first job is the 4-card tier decision — the v0.2.7 SYCL peer tier is a
   stub, and EP was rejected on both 0731 and GLM after profiling.)
2. **Drafter:** is an MTP/DSpark draft for 1017 available in the Maya pack (or to be built)?
   The 2-stage decode that carries GLM to 45.5 tok/s needs it.
3. **Pack:** Maya-GGUF 1017 (size/format on HF) vs the on-disk GSQ-RCO IQ2_XXS 128.75 GiB +
   103 GiB IQ4_NL Engram — which quant/Engram layout does the port target?
4. **Base:** pin Maya at v1.1.44 @ `5d20b0e8` (as GLM does) or take a newer release?
5. **Cheap pre-port arms:** run the two staged llama.cpp arms first (prefill single-device,
   `DEV2DEV_MEMCPY=1`) for information, or go straight to the port? Both are cheap and keep the
   yardstick warm.

## 8. The yardstick (do not lose it)

```bat
cd /d C:\llamacpp-v41\build-sycl\bin
set "PATH=C:\Program Files (x86)\Intel\oneAPI\2026.0\bin;%PATH%"
REM warmup and r=3 are mandatory - without them the build reports 1.5-3x low.
llama-bench.exe -m D:\AI\Models\dsv41\DeepSeek-V4.1-Flash-1017-GSQ-RCO-IQ2_XXS-00001-of-00004.gguf ^
  -ngl 38 -sm layer -t 12 -p 32 -n 8 -r 3 -v
```

Warm reference: **pp32 0.65 / tg8 3.92** (2026-11-12, `de5122d`, IQ2_XXS 128.75 GiB, 4 cards).
Launch gotchas (`.bat` via `cmd.exe /c`, Windows paths, fresh base64 transfer, no
`SYCL_CACHE_PERSISTENT=1`, no `--mlock`) are in the sweep's §9.
