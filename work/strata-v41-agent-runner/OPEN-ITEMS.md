# Open items — DeepSeek V4.1 1017 tuning on GPU-BOX

Tracked as GitHub issues on `Captain-Tripps/b70-lab`, labelled `open-item`.
This file is the in-repo mirror so the list survives independently of GitHub.

Opened 2026-10-27 during the speed-tuning session. Umbrella: **#11**.

| # | Item | Status |
|---|---|---|
| [#5](https://github.com/Captain-Tripps/b70-lab/issues/5) | OOM: SYCL alloc failure at large ubatch (b=32, ub>=128), cause unidentified | OPEN |
| [#6](https://github.com/Captain-Tripps/b70-lab/issues/6) | pp512 non-monotonic in batch: 12.25 / 0.70 / 41.87 t/s at b=128/256/512 | OPEN |
| [#7](https://github.com/Captain-Tripps/b70-lab/issues/7) | Model load takes 10-17 min: break down the cost and cut it | OPEN |
| [#8](https://github.com/Captain-Tripps/b70-lab/issues/8) | Flash attention ON is a 10x regression (0.33 vs 3.48 t/s at p128) | OPEN |
| [#9](https://github.com/Captain-Tripps/b70-lab/issues/9) | KV quant q8_0 halves prefill (3.48 -> 1.62 t/s), decode unchanged | OPEN |
| [#10](https://github.com/Captain-Tripps/b70-lab/issues/10) | llama-server cannot use the tuned batching path; llama-swap integration broken | OPEN |
| [#12](https://github.com/Captain-Tripps/b70-lab/issues/12) | `-sm row` aborts: `get_row_rounding` has no I32/I64 case | OPEN |
| [#13](https://github.com/Captain-Tripps/b70-lab/issues/13) | `-ngl 38` forced by ~955 MiB VRAM overrun; split lopsided 22/37 | OPEN |
| [#14](https://github.com/Captain-Tripps/b70-lab/issues/14) | Engram/PLE unusable: 10 tensors skipped, metadata absent | OPEN |
| [#15](https://github.com/Captain-Tripps/b70-lab/issues/15) | PCIe measured ~12 GB/s per card (x8-class), topology unconfirmed | OPEN |

## Rules for this work

1. **Single-sample numbers are not findings.** Everything above came from `-r 1` unless stated. Confirm at `-r 3` before it enters `PLAN.md` as a headline.
2. **`-fa 0` is the benchmarking default** until #8 resolves — FA-on measured 10x slower.
3. **Do not publish 41.87 t/s** as a capability claim until #6 reproduces it.
4. **No gate moves on llama.cpp evidence.** CHECK-102..108 remain NOT_RUN.
5. Numbers taken before the 2026-10-27 sweep, at default batch, were measuring a near-unbatched path. Read them as such.

## Settled — do not redo

- The `deepseek41` architecture exists in the llama.cpp fork; the pack loads and generates (exit 0).
- `-sm layer` beats `-sm tensor` for decode by 65% (3.65 vs 2.21 t/s).
- Batching does engage. The earlier "batched path never engages" conclusion was wrong.
- Production llama-swap config is rolled back and SHA256-verified: 0 `v41` references, 9 models served.

## Note on benchmark cost

`llama-bench` reloads the model **per configuration**. A three-value `-b` sweep is three full
10-17 minute loads, which is why a small sweep takes the better part of an hour. This is the
same cost that makes #7 (load time) a blocker for iteration and not just an inconvenience.
