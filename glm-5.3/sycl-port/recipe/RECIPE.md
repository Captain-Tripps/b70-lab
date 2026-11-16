# Recipe: build the live GLM-5.3 SYCL engine

One script takes a Windows box with Intel Arc cards from nothing to the engine that is served every day here on
4x Arc Pro B70 (2026-11-16 build): sources at pinned versions, the port, the live changes, the build, the model pack, a
server config and a smoke test. It was run from an empty folder on 2026-11-16, and the engine it built gives the same
logits as the live one, byte for byte.

## Quick start

Install first:

| Tool | Version tested | Notes |
|---|---|---|
| Visual Studio Build Tools | 18 (2026) | "Desktop development with C++" (MSVC, CMake, Ninja) |
| Intel oneAPI Base Toolkit | 2026.0 | DPC++ compiler and oneMKL |
| GPU driver | 32.0.101.9175 | Arc Pro B70 |
| Python | 3.10+ (tested on 3.14) | on `PATH`, or set `PYTHON` |
| git | any | on `PATH` |

Then, from a clone of this repo:

```bash
glm-5.3\sycl-port\recipe\setup.cmd --work D:\glm --gguf D:\models\Maya-M --download
```

| Step | What it does |
|---|---|
| 1 | Fetches Project Maya `5d20b0e8`, llama.cpp `3cf0325` and llama.cpp PR #31428 at `eec5c09`, each checked by commit |
| 2 | Downloads the port base archive (2.1 MB, a release asset of this repo) and checks its sha256 |
| 3 | Applies the live changes (`apply_live_chain.py`, table below) |
| 4 | Builds static `ggml-base` + `ggml-cpu` from llama.cpp `3cf0325` |
| 5 | Builds the engine (`build.py`) and a runtime folder with the oneAPI DLLs it needs |
| 6 | Downloads the Maya-M shards from Hugging Face (`peasantsmith/GLM-5.3-Flash-Maya-GGUF`, 108 GiB; needs `pip install huggingface_hub`), checks their sha256 and builds Maya's weight pack |
| 7 | Writes `glm-maya-sycl.json` and `serve.cmd`, and applies the serving patch (`../patches/0002-...`) |
| 8 | Starts the server on the GPUs and asks it `19 * 21` |

Leave out `--download` if you already have the shards in `--gguf`. Each step is skipped when its output exists, so a
failed run can be re-run. Put `--work` on the same drive as `--gguf` and the pack hard-links the shards instead of
needing them next to it. Afterwards, `serve.cmd <port>` starts an OpenAI / Anthropic compatible server (see
[Serving it](../README.md#serving-it-added-2026-11-07) for llama-swap, vision and the GPU keep-alive).

Options: `--layer-split`, `--prefill`, `--reserve-mb`, `--slots`, `--slot-ram-gb`, `--ram-gb`, `--devices`, `--jobs`,
`--no-smoke`. The defaults are this box's; see the next section before changing the hardware.

## What carries over to other machines

| Part | Carries over? |
|---|---|
| The port itself (CUDA -> SYCL, Level Zero, Windows) | Any Intel GPU with SYCL + Level Zero; only tested on Arc Pro B70 |
| Kernel work: Q6_K aligned mat-vec, ESIMD grouped expert GEMM + IQ2_S loader, XMX indexer, 64-wide tiles | Arc B-series (Xe2) - ESIMD and `joint_matrix` shapes are picked for its XMX units |
| Slot features (branch keep, checkpoint carry / resume, buffer reuse) | Anywhere; they are host-side |
| `--layer-split 14,25,36` | 4 cards with 32 GB each. Keep at most 10 MoE layers on the last card (see the port README) |
| `--prefill 1536`, `CKPT_EVERY=65536` | Tuned for 32 GB cards at 128k context; 2048 is not deterministic and 3072+ is wrong on this build |
| `--reserve-mb 400`, `--slot-ram-gb 12`, `--slots 8`, `--ram-gb 40` | This box: about 121-123 GB of commit for the 4-card process plus a 32 GB pagefile |

Fewer or smaller cards need a different split, and probably fewer experts resident in VRAM (`--expert-cache`), which
this build was never tested with.

## The port base

The archive in step 2 is the engine's source after the CUDA -> SYCL conversion and fix rounds 1-37 (round 36
reverted), as of 2026-11-12. Its `NOTICE.md` ([copy here](port-base-NOTICE.md)) lists what is in it and the licenses
(Maya MIT and the model licenses Maya ships, Intel's dpct headers Apache-2.0 with LLVM exception, ggml MIT).

Why an archive and not a re-run of the conversion: `../tools/` holds the conversion and fix rounds in the order they
were run, but they do not reproduce the base cleanly from the repo alone.
- The first migration ran per file with dpct 2025.1, plus SYCLomatic daily 2026-09-28 under WSL for the two files it
  crashed on (`glm_fast.cu`, `iq_kernels.cu`). The scripts in `../tools/` are the Strata versions of that step.
- `untangle_fast.py` reads a hand-saved copy of the migrated `glm_fast` file taken before round 3.
- A few early rounds were re-run after re-migrations, so the order was not strictly linear.
- Round 37 (split `kda_rec`, live since 2026-11-08) is in the base but not in `../tools/`.

## The live changes (step 3)

Applied in the order they went live, 2026-11-12 to 2026-11-16:

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

Each step stops on the first edit anchor that does not match, so a wrong base fails loudly. Step 9 patches the PR
checkout's `fused-gemm.hpp` in place.

## Verification (2026-11-16)

Two runs on the build machine (4x Arc Pro B70, Windows 11, driver 32.0.101.9175), both against the live engine:

- **`setup.cmd` from an empty folder.** Fresh clone of this branch, every source fetched, the port base from the
  archive. Steps 1-7 passed in one run; step 8, run straight after (steps 1-7 skipped as done), had the server up
  in 44 s and answering `399`.
  - Source: the tree after step 3 is the same as the live engine's source. With `apply_live_chain.py --check`, each
    step matched the tree its live build came from (steps 6-8 differ only in line endings, CRLF in the old Windows
    PR checkout).
  - Build: 142 of 143 units; the 143rd is `exl3.dp.cpp`, the EXL3 path, stubbed and unused by GLM.
  - Pack: every file the engine reads is byte for byte the same as the live pack (`index.txt`, `dense.bin`,
    `native_experts.txt`, the tokenizer). `compat-bf16.json` differs only in the source path it records.
  - The engine ran with only the new runtime folder and `System32` on `PATH`.
- **Logits.** One CLI prompt read per input with the live env and args, speculation off, dumping the last 64
  teacher-forced positions' logits:

  | Input | Built by `setup.cmd` | Live exe | Read time, setup / live |
  |---|---|---|---|
  | 8k code | `2365C206D1FAA63F` | `2365C206D1FAA63F` | 6.59 / 6.62-6.68 s |
  | 32k | `96E9624D6138CAAA` | `96E9624D6138CAAA` | 16.84 / 16.73-16.77 s |
  | 115k | `60FC983BB61484E0` | `60FC983BB61484E0` | 54.25 / 53.74-54.04 s |

  Logits are byte for byte the same at the same speed. The exe's hash differs (the linker stamps a time).
- Not checked separately: decode. The logits dump exits after the prompt, so the decode-only changes (the Q6_K
  mat-vec, the slot features) were checked only through the source, where they are the same bytes as live.

## Files

| File | What |
|---|---|
| `setup.cmd` / `setup.py` | the one-shot setup above |
| `apply_live_chain.py` | step 3; `--check <ref root>` compares each step with the reference trees on the build machine |
| `build.cmd` / `build.py` | step 5 on its own: per-file compile, library, link, same flags as the live build |
| `port-base-NOTICE.md` | the port base archive's notice |
