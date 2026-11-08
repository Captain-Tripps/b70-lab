# 3- and 4-card `-sm tensor` all-reduce for SYCL: prototype (2026-11-08)

A first pass at the N-way all-reduce that [@92es](https://github.com/92es) asked for in
[discussion #3](https://github.com/Captain-Tripps/b70-lab/discussions/3). Until now ggml-sycl only handled 2 cards
itself (the [ggml-org/llama.cpp#30956](https://github.com/ggml-org/llama.cpp/pull/30956) exchange); with 3 or more,
`comm_init` returned null and the meta backend used its generic butterfly fallback.

Patch: [`nway-allreduce/nway-allreduce-on-pr30956.patch`](nway-allreduce/nway-allreduce-on-pr30956.patch), against
the #30956 head `47ffd99ab` (apply with `git apply`). One file, `ggml/src/ggml-sycl/ggml-sycl.cpp`. Prepared with AI
assistance; derived from llama.cpp (MIT, notice in [../LICENSES/llama.cpp-LICENSE](../LICENSES/llama.cpp-LICENSE)).

## What it does

- `comm_init` accepts 2 to `GGML_SYCL_MAX_DEVICES` cards. **N = 2 is unchanged:** same exchange functions, same
  context check. The per-card buffers became vectors so both paths share one struct.
- **N > 2, all-to-all:** each card copies its partial (BF16 for F32 tensors of 32k elements or more, as on the 2-card
  path) to pinned host memory, then uploads the other N-1 partials and sums them in card order 0..N-1, so every card
  ends with the same bits.
- **N > 2, reduce-scatter + all-gather** (BF16 tensors only, i.e. prompt batches): card j sums only chunk j (1/N of the
  elements) and shares that result. Each card uploads 2(N-1)/N tensors' worth instead of N-1, for one extra host
  wait. Card j keeps its chunk in FP32; the others receive it as BF16.
- **Opt-in direct copies** (`GGML_SYCL_COMM_P2P=1`): when all queues share one SYCL context, copy partials card to
  card instead of through host memory. Correct, but slow on this machine (see below). Kept only so others can try it.
- Env switches: `GGML_SYCL_COMM_NWAY=0` (old fallback for N > 2), `GGML_SYCL_COMM_RS=0` (all-to-all for every size),
  `GGML_SYCL_COMM_P2P=1`.

## Setup

- 4x Arc Pro B70 on an EPYC board (PCIe Gen4, CPU-attached, no peer access between cards), Windows 11, driver
  32.0.101.8976, Level Zero v2 adapter.
- Measured on this repo's fork (the 2026-10-17 rebase plus the #30956 port) with the same N-way code. The patch above
  is the same change ported to the #30956 head. It compiles there; the numbers below are from the fork build.
- Qwen3.8-27B Q8_0. `llama-bench -fa 1 -b 2048 -ub 512 -p 512,2048 -n 64`, 3 to 5 repetitions per run, 2 or 3 rounds
  (later rounds in reverse order). `GGML_SYCL_ENABLE_VMM=0`, `GGML_SYCL_DISABLE_F32_MMV=1`.
- Perplexity: this repo's docs as text, `-c 512 -b 512`, 16 chunks at ub 512 and 4 chunks at ub 4.
- During the reduce-scatter / P2P run another model on the same cards served some requests, so the third round and
  the 3-card rows are noisy. The table uses the cleaner rounds.

## Results (tok/s)

| Setup | pp512 | pp2048 | tg64 |
|---|---:|---:|---:|
| 4x layer split | 1,012-1,028 | 1,007-1,019 | 17.3 |
| 4x tensor, reduce-scatter | 949-962 | 910-924 | 9.1 |
| 4x tensor, all-to-all | 812 | 782 | 9.1 |
| 4x tensor, direct copies (P2P) | 98-110 | 97-109 | 6.4-6.5 |
| 4x tensor, old generic fallback | 110 | 109 | 6.7 |
| 3x layer split | 1,021 | 1,010 | 17.5 |
| 3x tensor, new path (either variant) | 770-850 | 790-880 | 11.3-12.0 |
| 3x tensor, direct copies (P2P) | 160-181 | 174-201 | 8.8-9.1 |
| 3x tensor, old generic fallback | 203 | 201 | 9.5 |
| 2x tensor (#30956 path) | 967-992 | 931-940 | 15.2-15.5 |

- **Prompt read:** 4 cards go from 110 to about 955 tok/s, within about 7% of layer split. Reduce-scatter is +18% over
  all-to-all on 4 cards. On 3 cards the two variants come out even within the noise.
- **Decode** is the weak spot: about 128 all-reduces per token (2 per layer), each paying a host round trip. 4-card
  tensor decodes at about half of layer split.
- **Direct copies are a dead end here:** the same speed as the old fallback. So the fallback was slow because of the
  peer copy itself, not the extra syncs, and staging through pinned host memory is about 9x faster on this board.
  A board with real peer access may differ.

## Correctness

| Arm | PPL, ub 512 | PPL, ub 4 |
|---|---:|---:|
| layer split (3 and 4 cards) | 5.4818-5.4823 | 5.3402 |
| tensor, all-to-all (3 and 4 cards) | 5.4818-5.4823 | 5.326-5.335 |
| tensor, reduce-scatter | 5.4800 (3 cards), 5.4811 (4 cards) | - |
| tensor, P2P | 5.4820-5.4821 | - |
| 2x tensor (#30956 path) | 5.482 | 5.326-5.335 |

The ub 4 gap between tensor split and layer split is the same on the existing 2-card path, so it does not come from
the N-way code. Reduce-scatter differs a little because non-owner cards receive the final sums as BF16. KLD against a
layer-split baseline is not run yet.

## Next

- Tensor split + MTP draft: verify several tokens per all-reduce to spread the per-token syncs.
- For the v2 adapter's cross-queue barrier abort (oneapi-src/level-zero#556): try `depends_on` instead of
  `ext_oneapi_submit_barrier`.
- Check whether a 2+2 mix (tensor split inside pairs, layer split across them) is possible in the meta backend.
