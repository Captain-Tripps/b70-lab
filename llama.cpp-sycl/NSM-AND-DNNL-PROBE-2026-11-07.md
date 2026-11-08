# `nsm` divisor and per-dtype oneDNN probe: Windows check (2026-11-07)

Windows results for two changes proposed by [@92es](https://github.com/92es) in
[discussion #3](https://github.com/Captain-Tripps/b70-lab/discussions/3):

1. **`nsm` divisor 8 instead of 16.** ggml-sycl sets `nsm = max_compute_units / 16`, which assumes 16 EUs per Xe core.
   Xe2 has 8, so a B70 (256 EUs, 32 Xe cores) reports `nsm = 16` instead of 32. `nsm` feeds the flash-attention split
   choice, count-equal and top-k. This fork's patch [`0008`](upstream-candidates/) worked around the undercount
   with a floor of 48 KV splits for TILE decode on BMG.
2. **Per-dtype oneDNN probe.** Stock ggml-sycl probes one 1x64x64 f16 matmul and uses the result for every dtype and
   shape. The proposal probes f16, bf16 and f32 separately at 4096 x 4096 x 512 and checks each dispatch site's own
   dtype, with `GGML_SYCL_DNNL_GEMM` (-1 auto, 0 off, 1 on) as an override.

## Setup

- One Arc Pro B70 (PCIe Gen4 x16, CPU-attached), Windows 11, Level Zero v2 adapter (default), driver 32.0.101.8976.
- Tree: the r67c fork rebase plus the #30956 exchange, with both changes added behind env switches so one build covers
  every arm: `GGML_SYCL_NSM_DIV` (16 / 8), `GGML_SYCL_FA_SPLIT_FLOOR` (48 / 0 = off), `GGML_SYCL_DNNL_PROBE=0` (old
  probe), `GGML_SYCL_DNNL_GEMM`.
- Common flags: `-ngl 99 -fa 1 -ctk q4_0 -ctv q4_0 -b 2048 -ub 1024 -t 8`, `GGML_SYCL_ENABLE_VMM=0`,
  `GGML_SYCL_DISABLE_F32_MMV=1`, graphs off.
- `llama-bench`, 3 repetitions per run. Each arm ran twice, the second round in reverse order. The two rounds agree to
  within 0.06 tok/s for decode and 4 tok/s for prompt read.
- Another model was serving on two other cards during the runs. These runs used one card only.

## Results

### `nsm` divisor vs the split floor (decode, tg64 at depth)

| Model, depth | stock (/16, no floor) | /8 | floor 48 (fork) | /8 + floor 48 |
|---|---:|---:|---:|---:|
| Mistral-Small-3.2-24B Q8_0, 8k | 17.34 | 18.26 (+5.3%) | 18.26 (+5.3%) | 18.25 (+5.2%) |
| Mistral-Small-3.2-24B Q8_0, 32k | 10.26 | 11.96 (**+16.6%**) | 12.14 (+18.4%) | 12.14 (+18.3%) |
| Qwen3.8-27B Q8_0, 8k | 16.31 | 16.51 (+1.2%) | 16.55 (+1.4%) | 16.54 (+1.4%) |
| Qwen3.8-27B Q8_0, 32k | 12.57 | 13.15 (**+4.6%**) | 13.24 (+5.4%) | 13.24 (+5.3%) |

tok/s, mean of both rounds.

- `/ 8` alone gets most of the floor's gain: all of it at 8k, and all but 0.8-1.8 points at 32k.
- Combining the two is no better than the floor alone.
- The earlier finding holds: with `/ 8` the heuristic picks fewer splits than 48, which is slightly slower at 32k
  (see the `0008` row in [README](README.md)).

### oneDNN probe (prompt read, Qwen3.8-27B Q8_0)

| Arm | pp512 | pp2048 |
|---|---:|---:|
| per-dtype probe | 1,022.8 | 1,280.3 |
| old 1x64x64 probe | 1,020.6 | 1,278.8 |
| oneDNN off (`GGML_SYCL_DNNL_GEMM=0`) | 1,011.1 | 1,227.3 |

- All three dtypes report `jit:gemm:any -> optimized` on Windows, the same as on 92es's Linux box. The old probe
  also picks `jit:gemm:any`, so on B70 it was never turning oneDNN off. The new probe gives no speedup here; it is a
  robustness fix for GPUs where the toy-sized problem picks the reference kernel.
- oneDNN is worth about 4% of prompt read at pp2048 (1% at pp512).
- Startup cost: the per-dtype probe takes 150-190 ms per card, the old one about 10 ms.

### Perplexity

Qwen3.8-27B Q8_0, fixed English text (the repository's `docs/*.md`), `-fa on -ctk q4_0 -ctv q4_0`:

| Arm | ub 1024, c 2048, 8 chunks | ub 1, c 512, 4 chunks |
|---|---|---|
| stock | 3.6146 +/- 0.08463 | 5.3324 +/- 0.38453 |
| floor 48 (fork) | 3.6146 | 5.3280 +/- 0.38407 |
| /8 | 3.6146 | 5.3280 |
| per-dtype probe | 3.6146 | - |
| old probe | 3.6146 | - |

The ub 1 run covers the decode path, where the split change applies (one query row). The stock-vs-split difference
there (0.0044) is far inside the error bar and comes from a different reduction order.

## Conclusions

- **`nsm` / 8 is the fix to send upstream.** It fixes the undercount at its source, not one kernel on one GPU, and gets
  almost all of the floor's gain. The floor can be dropped from this fork once it lands, after three checks:
  - floor vs `/ 8` at 64k-128k (the floor's gain grew with depth: +4.5% at 28k, +6.2% at 40k on Qwen)
  - the fork's 2x top-k groups-per-`nsm` factor, which should probably return to 1 once `nsm` doubles (needs an MoE
    model, since top-k only runs there)
  - 2-card `-sm tensor`
- **Per-dtype probe:** correct on B70 and no faster, with a small startup cost. Worth having for other GPUs.

Not tested here: the top-k factor, 2-card tensor split, contexts above 32k.
