# Flash-Next prompt read +31%: grouped experts on both cards, ESIMD GEMM (2026-11-17)

**A 32k-token prompt now reads at about 2,200 tok/s, up from 1,680 (+31%), with decode unchanged.** Live since
2026-11-17 on the stock and abliterated Flash-Next entries. On real traffic through llama-swap a 42k-token read went from
1,150-1,300 tok/s (older reads in the engine log) to 1,726.

Setup: Windows 11, two Arc Pro B70s, the Strata Windows port ([../](../)) with Qwen3.8-Flash-Next GSQ-RCO IQ3_S,
1 slot x 200k, int8 KV, `--prefill 8192`, JIT build, oneAPI 2026.0, driver 32.0.101.9175. Card 0 holds 192 experts a
layer, the expert-parallel card holds the other 320.

## What changed

One patch, [0001-prefill-grouped-iq3s-both-cards-esimd.patch](0001-prefill-grouped-iq3s-both-cards-esimd.patch),
plus [strata_esimd_shim.cpp](strata_esimd_shim.cpp). Three parts:

| Part | What | Switch |
|---|---|---|
| 1. Per-layer type check | The grouped prompt path (`STRATA_NIGHT_PREFILL_GROUPED`) checked the whole model's expert types, so IQ3_S (a quant mix: one IQ4_XS layer, some Q2_0 down layers) could not use it at all. Each layer now checks its own types and falls back alone. Chunks under 256 tokens keep the old path, so MTP verify windows are untouched | `STRATA_NIGHT_PREFILL_GROUPED=1`, `..._GROUPED_MAX=1024`, `..._GROUPED_MIN_T` (default 256) |
| 2. The second card | `peer_alias_resident` required `m.T_max == 12288`. The served config runs 8192-token chunks, so the expert-parallel card never took the grouped path. The rows buffer is `T_max*K*N*4`, so the pin was not needed; it is now `m.T_max > 0` | none (stderr prints `peer alias path on/off` once) |
| 3. ESIMD GEMM | The grouped experts' gate/up and down products run on the llama.cpp SYCL fork's ESIMD grouped dequant GEMM ([llama.cpp#31428](https://github.com/ggml-org/llama.cpp/pull/31428) plus the IQ2_S loader and 64-wide tiles from the [GLM-5.3 work](../../glm-5.3/sycl-port/experiments/2026-11-16-esimd-tile-sweep/)), in place of Strata's `joint_matrix` kernel | `STRATA_NIGHT_PREFILL_ESIMD=1` |

How part 3 fits Strata:

- **Shim.** Built as its own object library with the fork's headers, because the fork's dpct helper and Strata's
  SYCLomatic dpct headers both define `namespace dpct`. Strata calls two C entries: `strata_esimd_grouped` and
  `strata_swiglu_split`.
- **Expert addressing.** Strata keeps each expert as one blob in a slot pool with 256-byte slots. The kernel reads
  tile `t` at `base + tile.expert * expert_stride`, so the shim passes `expert_stride = 256` and
  `tile.expert = (blob - base) / 256`. The kernel itself is unchanged.
- **Gate/up.** Run as one stacked 1280-row GEMM when the up rows follow the gate rows in the blob, then a split-layout
  SwiGLU, then down.
- **Fallback.** Types the kernel does not cover (Q2_0 down layers) return "declined", and the caller runs
  `night_grouped_f16` for that product.

## Results

32k-token prompt, timing off (see the caveats), three interleaved rounds per build, ±2% spread:

| Build | 32k read, tok/s | vs base |
|---|---:|---:|
| base (live before, `GROUPED=0`) | 1,680 | - |
| part 1 (card 0 grouped) | 1,989 | +18% |
| parts 1+3 on card 0 only | 2,132 | +27% |
| **parts 1+2+3 (both cards, ESIMD)** | **2,194** | **+31%** |

A second window, base against the final build:

| Test | Base | Final build |
|---|---:|---:|
| 32k read | 1,598-1,689 tok/s | 2,260-2,267 tok/s |
| 8k read | 1,503 tok/s | 1,947 tok/s |
| Decode, short prompt (256 generated) | 113.6-114.2 tok/s | 114.4-115.7 tok/s |
| Decode after 32k (256 generated) | 104.9-106.1 tok/s | 106.8-107.8 tok/s |

Expert-parallel card, MoE time on a 32k read: about 5.3 s before part 2, 2.8 s after. Inside that, ESIMD against
Strata's `joint_matrix` kernel:

| Peer phase, 32k | ESIMD | `joint_matrix` |
|---|---:|---:|
| grouped gate/up | 1.43 s | 2.40 s |
| grouped act+down | 0.68 s | 1.20 s |

Abliterated IQ3_S (SC117 shard 1), same method, three rounds: 1,547 -> 2,091 tok/s (+35%), first 12 tokens identical.

**Output.** The first 16 tokens at 32k are identical to the base. An 8k answer rewords from token 4 on, with the same
content (rounding-level drift from the different GEMM). The engine's own `STRATA_NIGHT_PREFILL_GROUPED_CHECK` could not
run: it goes out of device memory with 1.85 GB free on the expert-parallel card.

## Tried and rejected

**Moving experts to card 0 (`STRATA_NIGHT_EP_SHARE0`).** After parts 1-3 the expert-parallel card sits idle about 11 s
of a 19 s read, so moving expert traffic to card 0 looked like the next step. Two rounds:

| Card 0 share | Round 1 | Round 2 | Peer rows/layer |
|---|---:|---:|---:|
| default | 1,816 | 1,443 | 45,454 |
| 0.40 | 1,405 | 1,387 | 50,182 |
| 0.33 | 1,467 | 1,387 | 54,132 |
| 0.25 | 1,411 | 1,370 | 58,176 |

Every other share was slower than the default in its round. Card 0's GEMM shrinks (1.9 -> 1.45 s), but its routing
and combine waits grow by more. These runs had timing on, which is why the rounds swing (see the caveats). The card 0
time left is in host routing/grouping and the combine wait, not the GEMMs. That is the next lever; not started.

## Caveats for anyone measuring this

- **`STRATA_PREFILL_TIMING` distorts two-card runs.** To fold the peer's timeline marks, the host waits on the peer
  queue at every layer. That stall lands in card 0's "host grouping" and swung it from 1.6 to 5.7 s between runs of
  the same config. Use the timeline only to see where time goes. Quote speeds from runs with timing off.
- **Page cache.** Alternating two 50+ GB models (stock and abliterated) in one A/B churns the OS page cache: the PLE
  fill drops from 2.4 to 0.84 GB/s and the next read slows. A/B one model at a time.
- **First request after a load is cold.** With `SYCL_CACHE_PERSISTENT=0` the ESIMD kernels JIT-compile on first use:
  the first 11.8k read ran at 903 tok/s. Warm up once, or set the persistent cache.
- **VTune `gpu-offload`** did not finish an 8k read in 40 minutes on this two-card path. The in-engine timeline was
  used instead.

## How to build it

The full recipe, with versions, is in [../README.md#how-to-run-it](../README.md#how-to-run-it). In short:

1. Check out llama.cpp PR #31428 at `eec5c09` as `<work>\llama-pr` and apply
   [esimd/llama-pr-31428-fused-gemm-tile-width.patch](esimd/llama-pr-31428-fused-gemm-tile-width.patch) (the tile
   width comes from `MAYA_FG_BN`). Only its headers are used.
2. Put [esimd/fused-gemm-esimd.cpp](esimd/fused-gemm-esimd.cpp), [esimd/fused-gemm-esimd.hpp](esimd/fused-gemm-esimd.hpp)
   (the PR's kernel plus the IQ2_S loader and `MAYA_FG_BN 64`, the files the live build used) and this folder's
   `strata_esimd_shim.cpp` in one folder, `<ESIMD_DIR>`. The GLM-5.3 recipe
   ([../../glm-5.3/sycl-port/recipe/RECIPE.md](../../glm-5.3/sycl-port/recipe/RECIPE.md), steps 1 and 3) produces
   the same two files.
3. In the Strata checkout with the port patches 0001-0004 and [../slow-starts/](../slow-starts/) 0002-0003 applied:

   ```
   git apply <this repo>\strata-windows-port\esimd-prefill\0001-prefill-grouped-iq3s-both-cards-esimd.patch
   cmake -B build-win -S sycl -G Ninja -DCMAKE_BUILD_TYPE=Release -DSTRATA_SYCL_AOT= -DSTRATA_SYCL_XE2_JIT=ON ^
         -DSTRATA_SYCL_PARITY=OFF -DCMAKE_C_COMPILER=cl -DCMAKE_CXX_COMPILER=icx ^
         -DSTRATA_ESIMD_DIR=<ESIMD_DIR> -DSTRATA_ESIMD_FORK=<work>/llama-pr/ggml
   cmake --build build-win --target strata
   ```

   Without the two `STRATA_ESIMD_*` variables the build is the same as before and `STRATA_NIGHT_PREFILL_ESIMD` does
   nothing.
4. In the engine config env: `STRATA_NIGHT_PREFILL_GROUPED=1`, `STRATA_NIGHT_PREFILL_GROUPED_MAX=1024`,
   `STRATA_NIGHT_PREFILL_ESIMD=1` ([../configs/strata-iq3s-200k1-pf8k.json](../configs/strata-iq3s-200k1-pf8k.json)
   has them). The engine log should show `peer alias path on (T_max 8192)` and one ESIMD note per type pair.

Strata is MIT ([../../LICENSES/Strata-LICENSE](../../LICENSES/Strata-LICENSE)), llama.cpp is MIT
([../../LICENSES/llama.cpp-LICENSE](../../LICENSES/llama.cpp-LICENSE)). Patch and shim prepared with AI assistance.
