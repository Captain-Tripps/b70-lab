# GLM-5.3-Flash on 4x B70

GLM-5.3-Flash (llama.cpp arch `glm5-next`): 321B MoE, ~18B active, MLA attention, MTP (nextn) block.

- Model file: Project Maya's GGUF quants, **Maya-M** (3 shards, 108 GiB): IQ2_S / IQ3_XXS / IQ3_S routed experts,
  Q6_K / Q8_0 dense weights. Maya's own engine was CUDA-only at the time (later ported: [sycl-port/](sycl-port/)); upstream llama.cpp already had the architecture, so I
  brought GLM into my tuned SYCL fork instead (branch `glm5-fork`, runtime `g10`).
- Status: **superseded 2026-11-01** by [sycl-port/](sycl-port/): Project Maya's own engine ported to SYCL, 45.5-45.8 tok/s
  decode and ~1,000 tok/s prompt read on the same model file. This llama.cpp-fork entry ran from 2026-10-14 to 2026-11-01.

## Steps

4x B70, EPYC host, 112 GB RAM, Maya-M, driver 8976. Decode in tok/s, prompt read at short-to-medium prompts.

| Step | Decode | Prompt read | What changed |
|---|---|---|---|
| Stock upstream | 16.5 | ~230 | baseline |
| g2: fork + upstream GLM commits | 19.1 | ~75 | fork kernels; fixed a deep-context slowdown, but prompt path regressed |
| g3: grouped MoE XMX GEMM wired into the fork's MoE path | ~21 (MTP) | ~230 | prompt path back to upstream speed |
| g4: one-launch batched Q6_K mat-vec for MLA `attn_k_b` / `attn_v_b` | 24.0 (MTP n 2) | ~230 | 64 per-head launches -> 1 |
| g7 / g10: IQ2_S / IQ3_S / IQ2_XXS MoE decode kernels | 24.9 | ~240 | +4% |
| + cross-card pipeline | - | 330-370 (long prompts) | +43% on long prompts |
| + MTP n-max 4 / p-min 0.75 | 24-25 prose, 33-35 edits | - | +17-18% on copy-heavy output |

The IQ2_S / IQ3_S kernels need `GGML_SYCL_MMID_SMALL_FUSED=1 GGML_SYCL_MMID_SMALL_MAX_ROWS=8`.
The branch's changes are not exported as patches yet (see [../llama.cpp-sycl/](../llama.cpp-sycl/)).

## Quality checks

Perplexity, 12-16 chunks: g10 = stock upstream exactly (5.5565 at ub 512). Maya-S vs Maya-M: S +5.0% perplexity,
mean KL divergence 0.29, same top token 79.9% -> kept Maya-M. (For scale: a Qwen3.8-27B Q4_K_XL vs Q6_K comparison on
the same harness gave KLD 0.009.)

## Fitting 128k

- Maya-M fully in VRAM tops out around 32k context: card 0 also carries the output head and MTP block.
- With one layer's experts in system RAM it runs **128k** at 24-25 tok/s (20-23 deep), fullest card ~29.1 GB:
  `-ot "blk\.44\.ffn_.*_exps\.weight=CPU"`. This needed the RAM upgrade (64 -> 112 GB).
- `-ts 26.3,23.8,22.8,27.1`, `-b 2048 -ub 512`. On this setup the `-ts` values mapped to the cards in reverse order;
  check per-card memory after loading rather than trusting the order.
- 64k without offload and `-ub 1024` do not fit (with `-ub 1024`, prompts ran 20x slower).
- Maya-S fits 128k without offload (27.5 tok/s) but is measurably worse.
- ~2-3 GB of "shared" GPU memory in Task Manager is a fixed host buffer, not VRAM spilling.

## Reasoning settings

GLM's chat template defaults to **maximum** reasoning effort when none is given. On front-end coding prompts it
planned for 40k+ characters and never answered. The live server uses `--reasoning-effort high` (same accuracy on my
tasks, 4-10x fewer tokens) and `--reasoning-budget 8192`. Per request, `low` / `max` still work.

## Drafting

MTP accepts 98-99% of drafts on copy-heavy output (edits, reformatting). n-max 4 / p-min 0.75 gave +17-18% on edits
with prose flat; n 6 / p 0.75 was slightly better on copy but -4% on prose. Putting an n-gram lookup in front of MTP
hurt code edits.

## Where the time goes (expert overlap study, 2026-10-15)

In a 5-token MTP verify window GLM routes 40 (token, expert) assignments to 28.1 distinct experts (~30% redundant;
288 experts, 8 per token). A kernel that groups tokens by expert was tried on Flash-Next and was slower
([../rejected-ideas/](../rejected-ideas/)). Remaining GLM levers: the IQ2_S expert decode (~175 GB/s effective) and the
Q6_K attention q/output projections (estimated 5-10% together, not done).

## What did not help

`-sm tensor` (4.8 tok/s after three meta-backend fixes: ~1,000 tiny per-card graphs per token), broad small-op
fusion (+1%, and one fusion shifted perplexity 5.5565 -> 5.6031 for reasons not found, so it was reverted),
`GGML_SYCL_MKL_FA_*` (no gain, and it used 25-30 GB extra host RAM at load), IQ2_S codebook in local memory (slower).
Details in [../rejected-ideas/](../rejected-ideas/).
