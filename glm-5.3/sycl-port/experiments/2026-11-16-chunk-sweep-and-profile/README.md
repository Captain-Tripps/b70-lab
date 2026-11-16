# Prompt chunk re-sweep, profile of the live build and hand-off copy (L16) - 2026-11-16

## Decision

Keep `--prefill 1536`. Nothing changed live.

- 2048-token chunks read a cold 115k prompt about 6% faster (49.6 / 49.9 s against 53.1 s), but 32k and 8k code gain
  only 1-3%. Two runs of the same 115k or 32k input at 2048 give different logits (up to 8-10 apart on single
  positions), where 1536 is byte for byte the same every run. That is a determinism bug, so 2048 is not a config change
  to take.
- 3072 and 4096 produce wrong output, not just slow output: 3x slower, true-token loss on 115k 0.23 -> 1.34 / 3.92,
  top-1 matching live on about half the rows, and one 8k run crashed out of device resources.

The profile of the live build (L5 indexer + L14 tiles) showed the card-to-card hand-off copy (`maya_kcopy`) on the
sending cards at 37-62 ms a call, against about 5-6 ms on the L12 build this morning. Timed on the host (L16,
[below](#hand-off-copy-l16)) the copy takes 18-21 ms out and 6-9 ms in, about 1.4 s a card on a 115k read (under 3%);
VTune's per-call figure overstates it. A 16-byte-a-work-item copy is slower. Rejected; nothing changed live.

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

## Hand-off copy (L16)

In the pipelined prompt read each part copies a chunk's four residual streams (1536 x 4 x 4096 floats, 101 MB) into
one of its two pinned host slots, and the next part copies them in. Both copies are a one-word-a-work-item kernel
(`maya_kcopy`) on purpose: on B70 / Windows / Level Zero a USM host-device memcpy queued behind a running kernel blocks
every other host copy in the context until that kernel ends. The sending thread waits on its queue after the copy.

[`patch_hop.py`](patch_hop.py) routes the two copies through one helper with two switches, default unchanged:
`STRATA_GLM_HOP_TIME=1` drains the queue, copies, drains again and logs the copy's host-measured time;
`STRATA_GLM_HOP_VEC=1` copies 16 bytes a work-item. [`build_hop.py`](build_hop.py) builds it on the live tree (only
`glm_prefill.dp.cpp` recompiled). [`ab_hop.ps1`](ab_hop.ps1) / [`gen_hoprun.py`](gen_hoprun.py): live, probe, probe with
each switch, mirrored. Raw lines: [`hop-results.txt`](hop-results.txt). Every run's logits match live byte for byte.

| Read | Live | Probe, switches off | Hop timing on | 16-byte copy | Both |
|---|---:|---:|---:|---:|---:|
| 115k | 53.74 / 54.04 s | 53.97 / 54.06 s | 54.01 s | 55.03 / 55.14 s | 55.06 s |
| 32k | 16.77 / 16.73 s | 16.85 / 16.80 s | 16.82 s | 17.07 / 17.07 s | 16.95 s |

Host-measured copy, 115k read (75 chunks; the 32k read is the same per chunk):

| Part | Out (to host) median | In (from host) median | Out, 16-byte copy |
|---|---:|---:|---:|
| 0 | 18.1 ms (5.6 GB/s) | - | 32.2 ms |
| 1 | 18.7 ms | 8.8 ms (11.5 GB/s) | 34.4 ms |
| 2 | 21.0 ms | 8.7 ms | 27.7 ms |
| 3 | - | 5.7 ms (17.7 GB/s) | - |

So a sending card spends 1.3-1.6 s copying out and 0.5-0.6 s copying in over a 54 s read, and fencing the queue
around every copy costs nothing measurable: the copy is not the 40-60 ms VTune reports. The kernel span VTune
records covers more than the copy's own work. At best a copy as fast as the inbound one would save about 0.8 s a
card, 1-2%, not worth a change to a path built around a driver hazard. Wider stores make the outbound writes slower.

## Next

Prompt-read work is near the end of what is cheap. What is left on the profile is the grouped expert products (35-44%
of a card) and attention (18-19%), each a kernel project. The 2048-chunk determinism bug is worth fixing only if larger
chunks are wanted later.

## Setup

4x Arc Pro B70, Windows 11, driver 32.0.101.9175, oneAPI 2026.0 JIT, live executable `f27bcbf3...`. GLM unloaded from
the proxy after an idle check, with Jon's OK, and reloaded afterwards (it answered 19 x 21 = 399 on the live
executable). Expand `<work>` to the engine checkout and `<proxy>` to the proxy.
