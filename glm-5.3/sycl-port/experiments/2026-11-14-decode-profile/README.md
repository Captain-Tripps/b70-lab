# Decode profile: where a token's time goes, and what to try next - 2026-11-14

## Decision

Measured, nothing changed on the live server. Expert parallelism (each layer's experts spread over all four cards) is
not worth building: the routed experts are only about 27% of decode kernel time, and the cross-card exchanges it needs
would cost ~3.5-4 ms a step. Decode is a two-stage pipeline in which each card sits idle about half the time, and the
critical path is the second stage plus the MTP draft. The ranked leads at the end (L7-L11, also in the
[leads file](../../LEADS-2026-11-09.md)) are what to try instead. Which one goes first is Jon's call.

## Every expert is already in VRAM

The live engine log reports "complete: every expert" on all four cards (303-304 slots a layer), and the decode stat line
shows a 100% VRAM hit rate, 0 RAM fetches and 0 disk reads a token. Placement in the cache sense has nothing left.

## Decode is already a pipeline

The server decode takes the spec path (`glm spec`): the cards split into a head group (CUDA0 + CUDA1) and a tail group
(CUDA2 + CUDA3), with two positions in flight on two host threads. `STRATA_GLM_SPEC_HEAD` only moves that boundary.
The Windows `GPU Engine` counters during a 2000-token essay decode (42.4 tok/s, 1448/1998 drafts accepted) added up to
~255% busy across the four cards ([counters](engine-counters-decode.txt)). Those counters are not usable as a compute
measure here: CUDA1 and CUDA2 hold the same work (11 layers each) and read 88% and 41%, so the counter also counts a
queue that is waiting on another card's hop.

Adapter id to card, found by allocating 4 GB on each card in turn: level_zero 0, 1, 2, 3 = LUID `...d011`, `...c576`,
`...caf1`, `...c1db` on this driver. VTune numbers the cards by PCI bus; by their kernel counts bus 3 is CUDA0 and bus
195 is CUDA3 (buses 131 and 135 hold identical work, so the table below cannot tell CUDA1 from CUDA2).

## Kernel time per card (VTune)

VTune 2026.0 `gpu-offload` on the CLI `generate.exe` (live executable, split 14,25,36, chunk 1536), a 300-token and a
1300-token run from the same 200-token input; the difference is 1000 decode tokens with model load cancelled out. The
extra 1000 tokens took 21.3 s under VTune, so its overhead is small. Draft acceptance on this input (continued source
code) is 96.9%. [Per card and kernel](vtune-kernels-per-card.txt), [engine summary](vtune-engine-summary.txt),
[`vt_diff.py`](vt_diff.py).

| Card | Layers | Kernels, ms a token | Dense `glmf::mv#9` | MoE gate_up + down |
|---|---|---:|---:|---:|
| CUDA0 | 0-13 (3 dense) | 9.6 | 5.1 | 2.3 |
| CUDA1 | 14-24 | 8.1 | 3.5 | 2.5 |
| CUDA2 | 25-35 | 7.8 | 3.4 | 2.4 |
| CUDA3 | 36-44 + MTP + output head | 9.4 | 5.1 | 2.4 |

GLM-5.3-Flash routes each token to 8 of 288 experts a layer; an expert is 8.98 MB (gate/up IQ2_S, down IQ3_S), hidden
size 4096. A MoE layer reads ~72 MB a token, so the expert kernels run at ~316 GB/s, about 52% of the B70's 608 GB/s.
The dense matrix-vector kernel (attention projections, shared expert, output head) reads CUDA1's 1.49 GB of dense
weights in ~3.5 ms, ~420 GB/s or about 69%. About 9.9 GB of weights cross the cards' memory a token, two thirds of it
dense. Decode is bound by weight reads, and the dense weights dominate.

So expert parallelism could only spread the ~27% that is expert work, while adding two exchanges a layer.

## Cross-card exchange cost

Peer access is closed on these cards, so the engine hands the residual over through pinned host memory (one 64 KB hop
per boundary a token). [`xhop.cpp`](xhop.cpp) times that path, host-synchronous, median of 400:
[results](xhop-results.txt).

| Size | One hop, card -> host -> card | Scatter to 3 cards + gather back |
|---|---:|---:|
| 4 KB | 15 us | 74 us |
| 64 KB | 19 us | 82 us |
| 256 KB | 61 us | 147 us |

Every card pair is within 18-20 us at 64 KB: no slow link. Expert parallelism needs about two exchanges a layer, ~90 a
step, ~3.5-4 ms.

## One spec step

`STRATA_GLM_SPEC_PROF=1` on the CLI decode (the server renames `STRATA_GLM_*` switches to `MAYA_GLM_*`, and this one is
read under its raw name, so it only works from the CLI): [spec-prof.txt](spec-prof.txt).

| Phase, ms a step (18.9 ms, 52.9 tok/s) | |
|---|---:|
| Host waits for the tail's token | 9.36 |
| Host enqueues the tail's layers (overlaps the device: immediate command lists) | 7.15 |
| MTP draft for the next position | 2.22 |
| CUDA0: device time a token / idle before the next | 9.86 / 8.45 |

The step is the tail stage (~16.5 ms) plus the draft (~2.2 ms) in series. Inside each stage the two cards run one after
the other on the same position, which is where each card's ~50% idle comes from.

## Ranked leads

Ordered by expected value for the effort; none is measured as a gain yet.

| ID | Lead | Expected | Effort / risk |
|---|---|---|---|
| L7 | Faster MoE and dense kernels on the tail cards (CUDA2/3): experts at ~52% of bandwidth, dense at ~69% | ~10-15% decode | Medium; can be checked bit-exact against the current kernels |
| L8 | Shorten the MTP draft on the critical path (2.2 ms a step) | ~6% if halved | Medium |
| L9 | Four-stage spec pipeline: one card a stage, chained drafts (`STRATA_GLM_MTP_DRAFT` allows 3) | Ceiling near the busiest card + draft, ~12 ms a token on high-acceptance text; much less on prose (~72% acceptance) | High: new engine code, flushes on rejected drafts |
| L10 | Windowed MTP decode across the split: verify the drafts in one pass, reading the dense weights once for several tokens. Today `mtp_decode_wanted` refuses it on any split (`STRATA_GLM_MTP_DECODE=1` cannot override); its stated reason, experts streaming from RAM, does not hold here | Pays mainly on high-acceptance text | High: wire the verify window through the split |
| L11 | Move a layer from the tail to the head | ~1% | VRAM-locked |
| - | Expert parallelism | Not worth it | Rejected on this profile |

## Setup

4x Arc Pro B70, Windows 11, driver 32.0.101.9175, live executable `de2540a6...`, split 14,25,36, `--prefill 1536`.
GLM unloaded from the proxy after a quiet check, with Jon's OK, for the CLI and VTune runs, and reloaded afterwards.
Night of 2026-11-13 to 2026-11-14. Runners: [`prof_vtune.ps1`](prof_vtune.ps1), [`prof_spec.ps1`](prof_spec.ps1),
[`decode_probe.py`](decode_probe.py), [`xsamp.ps1`](xsamp.ps1); expand `<work>` to the engine checkout and `<proxy>`
to the proxy. The 200-token input is the first 200 tokens of the long 8k input used on 2026-11-10.
