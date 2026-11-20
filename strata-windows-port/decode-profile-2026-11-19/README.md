# Flash-Next decode profile on the Windows port - 2026-11-19

## Result

Neither DeepSeek round-4 lever applies to Flash-Next decode on Strata. Its dense mat-vec kernels already run on
16-lane sub-groups, and only one decode kernel spills, at about 1.3% of decode kernel time. In the live graph path
the cross-card waits cost about 0.07 ms a window, so the expert-parallel hand-off is not a lever either. A decode
window is a third routed experts, a fifth hyper-connection reads, and the rest dense projections and the head. No
build was made and nothing changed live.

## Run conditions

Served config (`win-r6-esimd`, `strata.exe` `05e6f0d4...`): GSQ-RCO IQ3_S, 2x B70 (`level_zero:2,3`, expert parallel
on the second card), int8 KV, `--spec 4` with the MTP drafter, the live env. Prompt: 256 tokens of C++ source with a
summarize instruction. Cards idle, no other model loaded. [`prof_fndec.py`](prof_fndec.py) runs the CLI decode
(`--tokens-file`, `--max-new N --greedy`) plain or under VTune `gpu-offload`, and extra `KEY=VALUE` arguments go into
the environment.

| Run | Decode |
|---|---:|
| CLI, 512 tokens, graphs (live path) | 126.0 / 126.1 / 123.5 tok/s |
| CLI under VTune, graphs | 119.5 tok/s |
| CLI, eager (`STRATA_VERIFY_EAGER=1 STRATA_BATCH_MTP_PAIR_GRAPH=0`) | 74.1 tok/s |
| CLI under VTune, eager | 31.8 tok/s |
| `--serve`, 239 tokens | 112.0 tok/s (110.5 with the stage profiler) |

## VTune does not see the decode graphs

The first capture on the live path listed only prompt kernels: decode runs as replayed SYCL graphs (the "captured
the N-token window" lines) and `gpu-offload` reports none of the kernels inside them. Running the windows eagerly
puts them on the queue, where VTune sees them. The kernels are the same code, so their spill sizes carry over, but
the eager timeline does not: it adds a host wait per stage.

## Spill table (eager capture)

The VTune report's header line carries the progress text, so strip everything before `Computing Task` before
aggregating. Decode kernel time is about 4.9 s of the 13.6 s capture; the rest is copies (the model load) and
cross-card wait kernels.

| Kernel | Share of GPU time | Spill a thread |
|---|---:|---:|
| `night_kreg<NightQ6K, 4, 2, 128>` (dense Q6_K) | 5.2% | 0 |
| `native_down_night` (experts, 120 rows) | 4.3% | 0 |
| `native_gu_night` (experts, 122 / 118 / 121 rows) | 6.7% | 0 |
| `night_hc` down2q / up2q | 3.9% | 0 |
| `ep_combine_psum_kernel<10, 0>` | 0.5% | 4,224 B |
| everything else | under 1% each | 0 |

Every dense `night_kreg` kernel already carries `reqd_sub_group_size(16)` and splits a row's blocks across lanes,
which is what DeepSeek's fx43 brought to that engine. The one spilling kernel is too small to pay for a fix, and on
GLM tonight 256 registers made the spilling kernel 3% slower ([GLM lessons](../../glm-5.3/sycl-port/experiments/2026-11-19-decode-lessons/)).

## Stage profile of the live graph path

A native IQ pack prints the decode stage profile only in serve mode: `STRATA_VERIFY_PROFILE=1 STRATA_DECODE_TIMING=1`
with `strata --serve <config args>`, then `GEN 512 <tokens>` and `QUIT` on stdin. Each stage stamp is a one-thread
kernel that reads a host-written clock, so it works inside the graphs. The run cost about 1.5% of decode speed.

94 windows, 239 tokens, 19.74 ms a window on the first card:

| Stage group | ms a window | Share |
|---|---:|---:|
| Routed experts (`VRAM hits`) | 6.34 | 32.1% |
| Attention side: q/k/v mat-vec, conv, gates, recurrence, QSA scores and attention | 5.52 | 28.0% |
| Hyper-connection reads (`hc-read0`, `hc-read1+router`) | 4.27 | 21.6% |
| Output projection | 1.58 | 8.0% |
| Head | 1.07 | 5.4% |
| Expert combine and copies | 0.45 | 2.3% |
| Shared expert + quantize | 0.36 | 1.8% |
| Cross-card waits and gaps | 0.15 | 0.8% |

Raw line: [`stages.txt`](stages.txt).

## Next

The hyper-connection reads are the one group no earlier round has looked at closely: 4.3 ms a window, about 22%.
Their kernels' bandwidth against the card's would show whether there is anything to win there.
