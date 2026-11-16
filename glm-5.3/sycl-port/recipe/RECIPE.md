# Recipe: build the live GLM-5.3 SYCL engine

How to get from public sources to the engine that is served every day on 4x Arc Pro B70 (2026-11-16 build), and which
parts of it are tuned to this one machine.

The short version: it is two stages. Stage 2 (the port base -> the live engine) is scripted here and was rebuilt from
clean on 2026-11-16 with the result checked against the live engine. Stage 1 (Project Maya's CUDA source -> the port
base) is in `../tools/`, but it has not been re-run from a clean Maya checkout and is known to need hand steps.
The port base source itself is not published yet, so for now Stage 2 can only be run on top of it here.

## What carries over to other machines

| Part | Carries over? |
|---|---|
| The port itself (CUDA -> SYCL, Level Zero, Windows) | Any Intel GPU with SYCL + Level Zero; only tested on Arc Pro B70 |
| Kernel work: Q6_K aligned mat-vec, ESIMD grouped expert GEMM + IQ2_S loader, XMX indexer, 64-wide tiles | Arc B-series (Xe2) - ESIMD and `joint_matrix` shapes are picked for its XMX units |
| Slot features (branch keep, checkpoint carry / resume, buffer reuse) | Anywhere; they are host-side |
| `--layer-split 14,25,36` | 4 cards with 32 GB each. Keep at most 10 MoE layers on the last card (see the port README) |
| `--prefill 1536`, `CKPT_EVERY=65536` | Tuned for 32 GB cards at 128k context; 2048 is not deterministic and 3072+ is wrong on this build |
| `RESERVE_MB=400`, `SLOT_RAM_GB=12`, `SLOTS=8`, `RAM_GB=40` | This box: about 121-123 GB of commit for the 4-card process plus a 32 GB pagefile |

Fewer or smaller cards need a different split, and probably fewer experts resident in VRAM (`--expert-cache`), which
this build was never tested with.

## Inputs

| Input | Version | Used for |
|---|---|---|
| [Project Maya](https://github.com/mw00/project-maya) | v1.1.44 @ `5d20b0e8` (MIT) | headers and the files the port did not change |
| llama.cpp | `3cf0325` | ggml headers, plus a static `ggml-base` + `ggml-cpu` build |
| llama.cpp PR #31428 | `refs/pull/31428/head` = `eec5c09` | the ESIMD grouped GEMM (`fused-gemm.cpp`, `fused-gemm-esimd.cpp`, `fused-gemm.hpp`) |
| Intel oneAPI | 2026.0 (icpx, oneMKL, TBB, UMF, DPL, ocloc) | compiler and dense GEMMs; JIT build (`-fsycl`, no AOT) |
| Visual Studio Build Tools | 18 (2026), `vcvars64` | MSVC headers, `lib.exe`, the linker |
| GPU driver | 32.0.101.9175 | what it was tested on |
| Python | 3.10+ | the scripts |
| The port base | the tree after Stage 1 | see below |

## Stage 1: Maya -> the port base

`../tools/` holds the conversion and fix rounds in the order they were run (see [Files](../README.md#files) in the
port README). Run in order on one tree, they produce the port base that went live on 2026-11-01. What is known not to
reproduce cleanly from the repo alone:

- The first migration ran per file with dpct 2025.1 and the two files it crashed on (`glm_fast.cu`, `iq_kernels.cu`)
  with SYCLomatic daily 2026-09-28 under WSL. The scripts in `../tools/` are the Strata versions of that step, not the
  exact ones used here.
- `untangle_fast.py` reads a hand-saved copy of the migrated `glm_fast` file taken before round 3.
- A few early rounds were re-run after re-migrations; every round is idempotent, but the order was not strictly linear.
- Round 37 (split `kda_rec`, live since 2026-11-08) is in the port base but not yet in `../tools/`. Round 36 was
  reverted and round 38 was rejected.
- `<work>` in the scripts is a placeholder for the work folder; fill it in before running.

So the reliable starting point is a copy of the port base source itself, not a re-run of Stage 1.

## Stage 2: the port base -> the live engine

Everything here is scripted and was checked from clean on 2026-11-16.

1. **Get the inputs.** A copy of the port base (`src/`, `include/`, `third_party/`), this repo, a Maya checkout at
   `5d20b0e8`, llama.cpp at `3cf0325`, and a separate checkout of the PR head:

   ```bash
   git init llama-pr && cd llama-pr
   git remote add origin https://github.com/ggml-org/llama.cpp
   git fetch --depth 1 origin pull/31428/head && git checkout FETCH_HEAD   # eec5c09
   ```

2. **Apply the live changes** (2026-11-12 to 2026-11-16, in the order they went live):

   ```bash
   python apply_live_chain.py <tree> <llama-pr>
   ```

   | Step | Change | Live env / arg |
   |---|---|---|
   | 1 | Keep a shorter RAM slot as a branch | `STRATA_GLM_SLOT_KEEP_BRANCH=1` |
   | 2 | Carry prompt checkpoints into a slot | `STRATA_GLM_SLOT_CARRY_CKPT=1` |
   | 3 | Resume from a slot checkpoint | `STRATA_GLM_SLOT_CKPT_RESUME=1` |
   | 4 | Reuse slot buffers | `STRATA_GLM_SLOT_REUSE=3` |
   | 5 | Aligned-load Q6_K mat-vec | - |
   | 6 | PR #31428's ESIMD grouped GEMM in `src/forkxmx`, shim moved to its API | - |
   | 7 | IQ2_S format for the ESIMD kernel | - |
   | 8 | XMX prompt indexer | `STRATA_GLM_DSA_XMX=1` |
   | 9 | 64-wide ESIMD tiles (`MAYA_FG_BN=64`) | - |

   Each step stops on the first edit anchor that does not match, so a wrong base fails loudly. It patches
   `llama-pr/ggml/src/ggml-sycl/fused-gemm.hpp` in place (step 9), so use a PR checkout of its own.

3. **Build static ggml** from llama.cpp `3cf0325`, in a `vcvars64` shell:

   ```bash
   cmake -S llama.cpp-3cf0325/ggml -B ggml-build -G Ninja -DCMAKE_BUILD_TYPE=Release -DCMAKE_C_COMPILER=cl -DCMAKE_CXX_COMPILER=cl -DBUILD_SHARED_LIBS=OFF -DGGML_STATIC=ON -DGGML_OPENMP=OFF -DGGML_BACKEND_DL=OFF -DGGML_BUILD_TESTS=OFF -DGGML_BUILD_EXAMPLES=OFF -DGGML_NATIVE=OFF -DGGML_AVX=ON -DGGML_AVX2=ON -DGGML_FMA=ON -DGGML_F16C=ON -DGGML_BMI2=ON -DCMAKE_MSVC_RUNTIME_LIBRARY=MultiThreadedDLL
   ```

   ```bash
   cmake --build ggml-build --target ggml-base ggml-cpu
   ```

4. **Compile and link** (`build.cmd` sets up `vcvars64` and the oneAPI environment, then runs `build.py`):

   ```bash
   build.cmd --tree <tree> --maya <maya> --ggml <llama.cpp-3cf0325> --ggml-build <ggml-build> --pr <llama-pr> --jobs 12
   ```

   Every translation unit is compiled on its own with icpx (`<tree>/compile/*.log`), `src/forkxmx` against the PR's
   headers with `GGML_SYCL_SUPPORT_XMX`, then one library and the link to `<tree>/link/generate.exe`. Override
   `VSVARS`, `ONEAPI` or `PYTHON` if yours are elsewhere.

5. **Run it.** [`../configs/glm-maya-sycl-128k.json`](../configs/glm-maya-sycl-128k.json) is the live engine config
   (paths redacted); [Serving it](../README.md#serving-it-added-2026-11-07) in the port README covers the server,
   the runtime folder Level Zero needs over SSH, and the weight pack. Change the split and memory settings for your
   cards first (see the table at the top).

## Verification (2026-11-16)

Stage 2 was run from clean on the build machine. Inputs: a fresh clone of this repo, a fresh fetch of the PR head
(`eec5c09`) and a copy of the port base.

- **Source.** `apply_live_chain.py --check` compared the tree after each step with the tree that step's live build
  came from. Steps 1-5 and step 9 were byte for byte the same. Steps 6-8 differed only in line endings, because the
  old PR checkout was on Windows (CRLF). The final tree is the same as the live engine's source.
- **Build.** `build.cmd` with `--jobs 12` compiled 142 of 143 units in 4.5 minutes; the 143rd is `exl3.dp.cpp`, the
  stubbed EXL3 path. The link was clean. The exe's hash does not match live (the linker stamps a time), so the check
  is on the output.
- **Logits.** One CLI prompt read per input, with the live env and args, speculation off, dumping the last 64
  teacher-forced positions' logits:

  | Input | Rebuilt exe | Live exe (same day) | Read time, rebuilt / live |
  |---|---|---|---|
  | 8k code | `2365C206D1FAA63F` | `2365C206D1FAA63F` | 6.64 / 6.62-6.68 s |
  | 32k | `96E9624D6138CAAA` | `96E9624D6138CAAA` | 16.76 / 16.73-16.77 s |
  | 115k | `60FC983BB61484E0` | `60FC983BB61484E0` | 53.89 / 53.74-54.04 s |

  Logits are byte for byte the same, at the same speed.
- Not checked separately: decode. The logits dump exits after the prompt, so the decode-only changes (the Q6_K
  mat-vec, the slot features) were checked only through the source: their files are the same bytes as live.

## Files

| File | What |
|---|---|
| `apply_live_chain.py` | Stage 2 steps 1-9; `--check <ref root>` compares each step with the reference trees on the build machine |
| `build.py` | per-file compile, library, link; same flags as the live build |
| `build.cmd` | compiler environment, then `build.py` |
