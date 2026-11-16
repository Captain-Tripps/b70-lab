# ESIMD grouped GEMM tile sweep (L14) and tail skip (L15) - 2026-11-16

## Decision

Measured, candidate, not live. Making the ESIMD grouped expert kernel's tiles 64 columns wide instead of 32 cuts a cold
115k read by 9.3% (58.71 -> 53.24 s), a 32k read by 8.4% and an 8k code read by 5.6%. The logits are byte for byte
the live build's on all three inputs. 48-wide tiles gain a little less. Skipping the empty column blocks of a tile
(L15) costs more than it saves, and 16 rows a thread is slower at every width. Before promotion: a soak through the
server, because speculative decoding's verify batches also go through this kernel with only a few rows an expert,
and a 64-wide tile does twice the multiplies there. Promotion waits for Jon.

## Why the tile width

In the [L12 kernel](../2026-11-15-esimd-grouped-gemm/) one thread owns MR = 32 rows of one expert's weight and one
BN = 32 column tile of the schedule (the tokens routed to that expert). Per k step it dequantizes its rows to f16 in
registers and multiplies them with BN / 16 packed-B blocks. So the dequantize cost is paid once per tile.

GLM-5.3-Flash has 288 experts and picks 8 a token, so a 1536-token prompt chunk gives an expert about 43 tokens on
average. At BN = 32 a typical expert takes two tiles, the second mostly empty, and its weights are dequantized twice.
At BN = 64 it takes one.

BN is also the width of the engine's host tile schedule and of the joint_matrix shapes the schedule is built for, so
it is set in one place for both. The shared PR header takes it from `MAYA_FG_BN` (32 when unset, so earlier builds
are unchanged).

## Variants

[`build_tile.py`](build_tile.py) copies the live tree (L5, `f72801f6...`) and sets the rows a thread
(`GROUPED_GEMM_MR`) and the tile width (`MAYA_FG_BN`); only `src/forkxmx` is recompiled.
[`build_skip.py`](build_skip.py) adds L15 on top of a 64-wide tree: each thread skips the packed-B loads and dpas of
every 16-column block at or past the tile's last real column. Those accumulators are never stored, so the output is
the same bits.

All six compiled with no errors. In the default mode each output element is still summed by one thread over the
whole K in the same order, so a different MR or BN should not change a bit. It did not.

## Speed

[`ab_tile.ps1`](ab_tile.ps1): CLI reads with the live environment (L5 indexer on) and prompt arguments, speculation
off, 64 teacher-forced positions dumped for the byte compare. Raw lines: [`results.txt`](results.txt).

Round 1 ([`gen_tilerun.py`](gen_tilerun.py)), one run each, live first and last. The first run of each new build also
compiles its ESIMD kernels (JIT), so the variants' numbers here carry that cost; the ranking holds, the size does not.

| Build (MR x BN) | 115k | 32k |
|---|---:|---:|
| live (32 x 32), mean of 2 | 58.63 s | 18.12 s |
| 32 x 64 | 57.84 s | 16.60 s |
| 32 x 48 | 57.72 s | 16.87 s |
| 16 x 64 | 58.61 s | 17.33 s |
| 32 x 64, tail skip | 59.56 s | 17.04 s |
| 16 x 64, tail skip | 58.75 s | 17.34 s |
| 16 x 32 | 63.32 s | 19.10 s |

Round 2 ([`gen_tilerun2.py`](gen_tilerun2.py)), the two leaders against live, two runs each in mirrored order,
kernels already compiled:

| Input | Live | 32 x 64 | 32 x 48 |
|---|---:|---:|---:|
| 115k | 58.68 / 58.75 s | 53.22 / 53.27 s (-9.3%) | 54.49 / 54.53 s (-7.2%) |
| 32k | 18.13 / 18.11 s | 16.61 / 16.58 s (-8.4%) | 16.91 / 16.89 s (-6.7%) |
| 8k code | 6.98 / 7.01 s | 6.58 / 6.62 s (-5.6%) | 6.71 / 6.61 s (-4.8%) |

Pairs agree within 0.1 s on the long reads. Logits: every run of every build matches live's dump byte for byte
(115k `60FC983B...`, 32k `96E9624D...`, code `2365C206...`).

The tail skip loses to the plain 64-wide tile on both inputs: the per-block branch inside the unrolled multiply loop
costs more than the dpas it saves when most tiles are mostly full. 16 rows a thread doubles the threads and the
packed-B loads per weight row and is slower everywhere.

## Next

A 30-minute soak of 32 x 64 (`tile-m32-n64`, `f27bcbf3...`) through the server, as for L12 and L5, to check decode
with speculation and the cached follow-ups; then a config change (the executable only, no new switch). Both need
Jon's OK.

## Setup

4x Arc Pro B70, Windows 11, driver 32.0.101.9175, oneAPI 2026.0 JIT. GLM unloaded from the proxy after an idle check,
with Jon's OK, and reloaded afterwards (it answered). Expand `<work>` to the engine checkout, `<proxy>` to the proxy
and `<python>` to the build Python.
