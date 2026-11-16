# Prompt-read profile after L12 - 2026-11-16

## Decision

Profiling only, nothing changed live. With the ESIMD grouped GEMM live, the grouped expert products are still the
largest cost of a prompt read (46-50% of the busiest cards' kernel time), but three other costs are now big enough
to work on. On a 115k read, on the two cards that set the pace:

| Cost | Card 0 | Card 1 | Next step |
|---|---:|---:|---|
| Grouped expert products (ESIMD kernel, packing, row gathers) | 45.6% | 47.8% | tile-shape sweep inside the ESIMD kernel |
| Attention (`maya_attn_xmx`) | 17.2% | 18.3% | already XMX; no lead yet |
| Dense projections: Q6_K dequantized to f16 per chunk, then oneMKL f16 GEMM | 11.5% | 8.0% | tried as L13: rejected, 27% slower ([dense ESIMD](../2026-11-16-dense-esimd/)) |
| DSA indexer (`dsa_score` + `dsa_select`) | 10.1% | 10.9% | L5: port [llama.cpp#31313](https://github.com/ggml-org/llama.cpp/pull/31313) |
| KDA recurrence | 4.4% | 2.8% | |

Ranked by likely gain:

1. **Dense projections on the ESIMD kernel.** The dense path dequantizes each weight slab to f16 for every chunk
   (`dequant_f16`, 12,936 calls on card 0 over the 115k read) and then runs a oneMKL f16 GEMM. The ESIMD kernel from
   L12 already has a Q6_K loader and is built into the live engine; a dense product is a grouped product with one
   group. Removing the dequant alone is 5.4% of card 0's time; the GEMM itself may get faster too. Estimate: -4 to
   -8% on cold reads. Quality can be checked the same way as L12 (mode 2 is bit-exact against the joint path).
   **Tried the same day and rejected:** the kernel dequantizes the weight again every 64 tokens, so chunks ran 27%
   slower ([dense ESIMD](../2026-11-16-dense-esimd/)). The indexer is now the next lead.
2. **The indexer (L5, prefill half).** 3% of a 32k read but 10-11% of a 115k read: it scores every earlier key, so
   it grows with depth (3.8 ms a call over the 32k read, 11.2 ms over the 115k). A 2x faster indexer is about -5% on
   115k and -1.5% on 32k.
3. **The grouped kernel's tile shape.** Still the largest item. The 2026-11-10 profile found the 32-row tiles about
   53% full; the ESIMD kernel's own tile options are untested here.

Card 3 runs 28% short of cards 0 and 1 during a prompt read (23.1 vs 32.1 s on the first 64k), so moving a layer
toward it would speed reads up. But decode waits on the tail stage (cards 2 and 3), so the same move slows decode.
It is not a free lever, and the layer split is fixed by where the weights live.

Attention costs the same per call at every depth (about 22 ms), so its share does not grow with the prompt.

## Method

The live engine (`1a628932...`, the L12 build) as a CLI run with the live environment and prompt arguments
(`--prefill 1536`, `STRATA_GLM_CKPT_EVERY=65536`, split `14,25,36`), speculation off, one new token. Inputs: the 8k
and 32k token files of the earlier logit checks, and a new 115,072-token input, the same text as the 115k screen
prompt, tokenized with the engine's tokenizer ([`mk115.py`](mk115.py); it starts with the 32k file's tokens). Each
input ran once plain and once under VTune 2026.0 `gpu-offload` ([`prof_prefill.ps1`](prof_prefill.ps1),
[`vt_report.ps1`](vt_report.ps1)).

Model load runs before the prompt and dominates the copies, so the tables subtract the 8k capture from the longer
ones ([`vt_diff.py`](vt_diff.py)): what is left is the extra prompt tokens. Per card and kernel:
[`vtune-kernels-per-card.txt`](vtune-kernels-per-card.txt). VTune numbers the cards by PCI bus: bus 3 is CUDA0 and
bus 195 is CUDA3, by their kernel counts; buses 131 and 135 are CUDA1 and CUDA2 in some order (they hold the same
work). Shares above are of each card's kernel time, copies excluded.

## Engine stage times (plain runs)

| Input | Read | Card 0 | Card 1 | Card 2 | Card 3 |
|---|---:|---:|---:|---:|---:|
| 8k (6 chunks) | 7.02 s | 4.49 s | 4.34 s | 4.04 s | 3.40 s |
| 32k (22 chunks) | 18.35 s | 16.00 s | 15.72 s | 14.51 s | 11.54 s |
| 115k, first 64k (43 chunks) | 34.76 s | 32.15 s | 31.71 s | 29.28 s | 23.08 s |
| 115k, remaining 49.5k (33 chunks) | 29.05 s | 26.41 s | 26.09 s | 24.12 s | 18.70 s |

The 115k read runs as two calls because of the 64k checkpoint spacing; each pays about 2.6 s of pipeline fill and
drain on top of the busiest card (measured on 2026-11-13). Total 63.8 s, as in the L12 screen.

## Kernel time, 115k minus 8k, card 0

| Kernel | Time | Calls | Per call |
|---|---:|---:|---:|
| `grouped_gemm_esimd_kernel<block_iq2_s>` (gate/up) | 15.30 s | 770 | 19.9 ms |
| `maya_attn_xmx` | 9.21 s | 414 | 22.2 ms |
| `dsa_score` | 4.63 s | 414 | 11.2 ms |
| `grouped_gemm_esimd_kernel<block_iq3_xxs>` (down) | 4.23 s | 490 | 8.6 ms |
| `gemm_f16f16f32` (oneMKL, dense) | 3.29 s | 10,486 | 0.31 ms |
| `dequant_f16` (dense weights) | 2.91 s | 12,936 | 0.22 ms |
| `grouped_gemm_esimd_kernel<block_iq3_s>` (down, some layers) | 2.88 s | 280 | 10.3 ms |
| `kda_rec_split#3` | 1.87 s | 1,518 | 1.2 ms |
| `grouped_gemm_pack_b` | 1.27 s | 1,540 | 0.82 ms |
| `dsa_select` | 0.79 s | 414 | 1.9 ms |
| all kernels | 53.68 s | | |

## Setup

4x Arc Pro B70, Windows 11, driver 32.0.101.9175, oneAPI 2026.0. GLM unloaded from the proxy after an idle check,
with Jon's OK, and reloaded afterwards (it answered). Expand `<work>` to the engine checkout and `<proxy>` to the
proxy.
