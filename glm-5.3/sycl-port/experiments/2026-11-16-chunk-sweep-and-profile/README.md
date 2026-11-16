# Prompt chunk re-sweep and profile of the live build - 2026-11-16

## Decision

Keep `--prefill 1536`. Nothing changed live.

- 2048-token chunks read a cold 115k prompt about 6% faster (49.6 / 49.9 s against 53.1 s), but 32k and 8k code gain
  only 1-3%. Two runs of the same 115k or 32k input at 2048 give different logits (up to 8-10 apart on single
  positions), where 1536 is byte for byte the same every run. That is a determinism bug, so 2048 is not a config change
  to take.
- 3072 and 4096 produce wrong output, not just slow output: 3x slower, true-token loss on 115k 0.23 -> 1.34 / 3.92,
  top-1 matching live on about half the rows, and one 8k run crashed out of device resources.

The profile of the live build (L5 indexer + L14 tiles) points to a new lead: the card-to-card hand-off copy
(`maya_kcopy`) on the sending cards now takes 37-62 ms a call, against about 5-6 ms on the L12 build this morning. On
a 115k read that is 4.6-6.7 s of each sending card's 51-55 s of kernel time ([Next](#next)).

## Chunk sweep

[`ab_chunk.ps1`](ab_chunk.ps1): one CLI read of the live executable with the live environment and prompt arguments,
only `--prefill` changed, speculation off, last 64 teacher-forced positions' logits dumped.
[`gen_chunkrun.py`](gen_chunkrun.py): a warm-up read, then each input at 1536 / 2048 / 3072 / 4096 and again in
reverse order. Raw lines: [`results.txt`](results.txt).

| Input | 1536 | 2048 | 3072 | 4096 |
|---|---:|---:|---:|---:|
| 115k | 53.12 / 56.60 s | 49.65 / 49.95 s | 161.5 / 162.4 s | 156.7 / 391.2 s |
| 32k | 17.51 / 17.68 s | 17.47 / 17.23 s | 53.62 / 53.96 s | 55.13 / 55.01 s |
| 8k code | 6.82 / 6.99 s | 6.61 / 6.87 s | 21.52 s / crash | 24.51 / 24.37 s |

The second 1536 run on 115k (56.6 s) is slower than its pair and than the L14 sweep's 53.2-53.3 s; take about 53 s.

Quality, last 63 scorable positions (true-next-token log-loss; top-1 against the 1536 run):

| Input | 1536 (both runs) | 2048 run 1 / run 2 | 3072 | 4096 |
|---|---|---|---|---|
| 115k | 0.2311, same bytes | 0.2335 / 0.2327, top-1 63/64, runs differ | 1.3357, top-1 44/64 | 3.9213, top-1 25/64 |
| 32k | 1.0159, same bytes | 1.0072 / 0.9985, top-1 61/64, runs differ | 3.1549, top-1 30/64 | 2.8270, top-1 32/64 |
| 8k code | 0.0001, same bytes | 0.0001 / 0.0001, top-1 64/64, runs agree | 2.1969, top-1 40/64 | 2.0354, top-1 41/64 |

The logit shift from a different chunk is expected (the mixer and shared-expert sub-batches change with it, as when
768 went to 1536 on 2026-11-13). Run-to-run differences at the same chunk are not. At 2048 the engine log shows card 0's
disk landing ring growing from 12 to 96 experts (823 MB pinned) as the activations borrow more of the expert pool; at
3072 and up the mixer sub-batches double to 2048, and that path is where the output breaks. The crash at 3072 was
`UR_RESULT_ERROR_OUT_OF_RESOURCES` in a dense f16 GEMM (m=512, n=2048, k=4096), then device lost.

## Profile

[`prof_l14.ps1`](prof_l14.ps1) runs one CLI read of the live executable under VTune `gpu-offload`;
[`vt_report14.ps1`](vt_report14.ps1) exports the per-card task table, summarised with the
[prefill profile](../2026-11-16-prefill-profile/)'s `vt_tasks.py`. Tables, against the morning's L12 capture:
[`vtune-kernels-per-card.txt`](vtune-kernels-per-card.txt).

115k read, kernel time per card (first card / two middle cards / last card):

| Kernel | L12 build | Live build |
|---|---:|---:|
| All kernels | 57.8 / 57.7, 53.5 / 40.5 s | 52.7 / 54.7, 51.0 / 35.3 s |
| Grouped expert products (ESIMD) | 24.1 / 25.6, 23.4 / 18.9 s | 18.4 / 20.7, 18.7 / 15.5 s |
| Attention (XMX) | 9.8 / 10.5, 9.9 / 6.4 s | 9.6 / 10.0, 9.7 / 6.5 s |
| DSA indexer score | 4.7 / 5.1, 4.6 / 2.9 s | 1.5 / 1.7, 1.5 / 1.0 s |
| Hand-off copy `maya_kcopy` | under 0.9 s each | 4.6 / 6.7, 6.6 / under 0.4 s |

Grouped expert products are now 35-44% of a card's kernel time (were 42-47%), attention 18-19%, the hand-off copy
9-13% on the three sending cards. The 32k capture shows the same: the copy is about 5 ms a call on L12 and on the last
card (which only receives), and 37-62 ms a call on the cards that send.

## Next

Find out why the sending side of the hand-off copy went from ~5 ms to ~40-60 ms, and whether it is on the critical path.
It copies a chunk's hidden state into a host buffer for the next card. Two readings fit:

- the copy kernel now overlaps the card's compute (or the expert staging traffic) and VTune counts the shared time, in
  which case it costs little; or
- device-to-host writes got slower since the L12 build, in which case restoring ~5 ms a call would save about 4-6 s a
  card on a 115k read, perhaps 5-9% of wall time.

A timed read with the hand-off on its own queue fenced, or with host timestamps around it, tells the two apart. The
2048 determinism bug is a separate lead, worth fixing only if larger chunks are wanted later.

## Setup

4x Arc Pro B70, Windows 11, driver 32.0.101.9175, oneAPI 2026.0 JIT, live executable `f27bcbf3...`. GLM unloaded from
the proxy after an idle check, with Jon's OK, and reloaded afterwards (it answered 19 x 21 = 399 on the live
executable). Expand `<work>` to the engine checkout and `<proxy>` to the proxy.
