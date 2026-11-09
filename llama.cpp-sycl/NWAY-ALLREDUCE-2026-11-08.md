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

## Follow-up: kernel tweaks and the 4-buffer exchange (2026-11-08, evening)

92es suggested two changes to the reduce kernels, and asked how the Windows numbers relate to the 4-buffer N=2
exchange that #30956 uses on Windows. Patch v2,
[`nway-allreduce/nway-allreduce-on-pr30956-v2.patch`](nway-allreduce/nway-allreduce-on-pr30956-v2.patch), is v1 plus
the two kernel changes, against the same head `47ffd99ab`. It compiles there; the numbers are again from the fork
build.

- **2-D all-gather:** launch over (foreign chunk, offset) instead of one work-item per element that first works out
  which card owns it. Chunk c starts at `c*base + (c*rem)/n` (`base = ne/n`, `rem = ne%n`), which equals
  `floor(c*ne/n)`, so it matches the chunking the reduce-scatter uses. No work-items for the card's own chunk.
  `GGML_SYCL_COMM_AG2D=0` restores the 1-D kernel.
- **Fixed card count:** the sums over cards are templated on N for 3 and 4 cards, so the loop unrolls.
  `GGML_SYCL_COMM_FIXN=0` uses the runtime-N kernels.
- **4-buffer exchange, for comparison (fork only):** `GGML_SYCL_COMM_X4=1` switches the 2-card exchange to the
  #30956 Windows variant (each card's partial to its own pinned buffer, CPU `memcpy` into the other context's
  pinned buffer, upload not waited on). The fork's default does what #30956's Linux `comm_exchange_fast` does (each
  queue uploads straight from the other card's pinned buffer, no CPU copy), but with host waits instead of
  `ext_oneapi_submit_barrier`, which aborts on the Windows v2 adapter (oneapi-src/level-zero#556). The cards share
  one SYCL context here. Not in the patch, since #30956 already has both paths.

Same setup and bench as above, 5 repetitions per run, rounds in alternating order. Perplexity (ub 512, 16 chunks):
reduce-scatter 5.4807 (4 cards) / 5.4799 (3 cards), all-to-all 5.4817, 4-buffer 2-card 5.4819, all in line with the
runs above.

Six speed rounds were run. In the first three, other work on the host and a small background job on the GPUs made
the numbers noisy (samples within one run up to ~40% apart), so they are left out. The table is the mean of the
three clean rounds, with nothing else on the GPUs. In those, the 5 samples of every run agree within about 3%.

Mean of 3 clean rounds, tok/s:

| Setup | pp512 | pp2048 | tg64 |
|---|---:|---:|---:|
| 4x tensor, reduce-scatter, new / old kernels | 915 / 920 | 853 / 858 | 9.0 / 9.0 |
| 4x tensor, all-to-all, new / old kernels | 829 / 810 | 798 / 779 | 9.0 / 8.9 |
| 3x tensor, reduce-scatter, new / old kernels | 818 / 805 | 780 / 773 | 11.8 / 11.9 |
| 2x tensor, direct upload / 4-buffer | 1,005 / 852 | 951 / 810 | 15.4 / 15.5 |
| 4x layer split | 1,021 | 1,015 | 17.5 |

- **The kernel tweaks are worth 0-2% at most.** All-to-all on 4 cards, where each card sums N-1 full tensors, gains
  about 2% on prompt read and was ahead in all 3 clean rounds. 3-card reduce-scatter gains about 1-2%. 4-card
  reduce-scatter is about 0.5% behind, which is within noise. Decode is the same everywhere. That fits the profile:
  the reduce kernels are about 2% of an all-reduce here, and the rest is host round trips. Kept in v2 because they
  are simpler and cost nothing; they may matter more on a host with faster transfers.
- **Direct upload beats the 4-buffer exchange on 2-card prompt read**, ahead in every round: about +18% at pp512
  (+10 to +22% per round) and +17% at pp2048 (+13 to +20%). Decode is the same. The extra CPU copy sits on the
  critical path of every prompt all-reduce. So on Windows, a same-context check plus host waits may be a cheap way to
  get the fast path without the barrier. Not tested with an MTP draft, where #30956 says host waits conflict.
- Absolute levels still move a little between clean rounds (2-card direct upload pp512: 956, 1,033, 1,026), so the
  pairs inside a row are the comparison to trust.

## Next

- Tensor split + MTP draft: verify several tokens per all-reduce to spread the per-token syncs.
- For the v2 adapter's cross-queue barrier abort (oneapi-src/level-zero#556): try `depends_on` instead of
  `ext_oneapi_submit_barrier`.
- Check whether a 2+2 mix (tensor split inside pairs, layer split across them) is possible in the meta backend.
