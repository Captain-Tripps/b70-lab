# GLM-5.3 Hill-Climb Checkpoint — 2026-10-20

> **Contamination notice (2026-10-21, later):** the "memory regression" working diagnosis in this document is
> **environmental, not software**. The bench box had logged a fatal WHEA memory error (Id 22) on every boot, visible host
> RAM dropped from ~112 GB to 95.9 GB during the sprint, and the arms idled between load and first request, which
> triggers documented idle-VRAM demotion into system RAM at ~1 GB/s (see
> [hardware-and-windows-notes.md](../hardware-and-windows-notes.md)). The `b739`-fails vs `r67c`-passes contrast
> and the 167 s "cold page-in" are artifacts of those two causes. The private-bytes figures below are commit
> charge, not resident RAM. Read the current checkpoint in [ROADMAP.md](./ROADMAP.md) before reusing anything here.
> The `r67c` 16k 23.4 tok/s result was measured warm under load and remains the reference until re-measured.

## Outcome

The first sprint found an operational memory cliff before any kernel comparison could be trusted.

- The live `g10` configuration and rebased `r67c` both cross the 6 GB RAM-watchdog floor at 128k.
- Reducing context alone does not fix the peak: inference pages roughly 98–99 GB into the process working set.
- `r67c` becomes viable at 16k with `-b 512 -ub 128`, passes the semantic quality gate, and averages **23.4 tok/s** on the fixed two-round decode harness.
- The staged current-upstream build regresses memory and dies on its first quality request under that same viable configuration.
- A 32k `r67c` arm survives only at `-b 256 -ub 64`; it averages **17.3 tok/s** and incurs a 167-second cold first-request page-in. It is not a production candidate.
- The live llama-swap entry was not changed.

## Fixed environment

- Model: `GLM-5.3-Flash-Maya-M-IQ2_S`, three shards, about 110 GB.
- Devices: 4× Intel Arc Pro B70.
- MTP: `--spec-type draft-mtp --spec-draft-n-max 4 --spec-draft-p-min 0.75`.
- Placement: `-sm layer -fit off -ngl 99 -ts 26.3,23.8,22.8,27.1`.
- CPU override: `blk\.44\.ffn_.*_exps\.weight=CPU`.
- Load mode: `dio` unless noted.
- Watchdog: kills `llama-server.exe` after two samples below 6 GB available RAM.
- Quality harness: `bench/squal.py`.
- Speed harness: `bench/sbench.py --n 128 --rounds 2 --long 0`.

## Results

| Build / configuration | Result | Peak or score |
|---|---|---|
| `g10`, 128k, b2048/u512 | First quality request killed | 5.12 GB available; 109.3 GB private; 94.3 GB working set |
| `r67c`, 128k, b2048/u512 | Killed during load | 4.55 GB available; 109.3 GB private; 95.1 GB working set |
| `r67c`, 64k, b2048/u512 | Loads; first request killed | 4.40 GB available; 120.9 GB private; 98.9 GB working set |
| `r67c`, 32k, b2048/u512 | Loads; first request killed | 4.80 GB available; 119.7 GB private; 98.6 GB working set |
| `r67c`, 32k, mmap | Killed during load | 5.31 GB available; 106.9 GB private; 97.9 GB working set |
| `r67c`, 32k, load-mode none | Loads; first request killed | Same watchdog class |
| `r67c`, 32k, no CPU override | Killed during load | 4.84 GB available; 109.3 GB private; 99.0 GB working set |
| `r67c`, 16k, b512/u128 | **Viable** | Semantic quality pass; **23.4 tok/s** mean decode |
| current build 739, 16k, b512/u128 | First quality request killed | 4.94 GB available; 118.1 GB private; 98.3 GB working set |
| `r67c`, 32k, b512/u128 | First request killed | Below watchdog floor |
| `r67c`, 32k, b256/u64 | Viable but slow | **17.3 tok/s** mean decode; 167 s cold page-in |

### Winning 16k decode sample

Round-two decode rates for the viable `r67c` arm:

| Workload | tok/s |
|---|---:|
| code explain | 20.7 |
| code write | 25.6 |
| prose summary | 25.3 |
| fiction | 20.1 |
| JSON extract | 25.7 |
| continuity edit | 23.2 |
| reasoning | 23.4 |
| **Mean** | **23.4** |

The quality prompts were semantically correct. Two strict-format blemishes remain: the JSON answer used a fenced block and the math answer used bold Markdown.

## Interpretation

1. The dominant blocker is not nominal context allocation. From 64k down to 32k, the first inference still reaches roughly the same 98–99 GB working set.
2. `mmap` is worse for this placement; the runtime itself warns that tensor overrides to CPU should use `load-mode none`, but `none` still crosses the inference peak.
3. Removing the CPU override does not fit safely. WDDM/system-memory backing begins before model load completes.
4. Batch scratch is the only tested lever that restores viability without weakening the watchdog.
5. Build 739 has a measurable memory regression versus `r67c`; do not adopt current upstream until it is attributed.
6. 16k/b512/u128 is the best throughput arm found, but it is not a replacement for the required 128k service.

## Next agent actions

Execute these in order:

1. **Automate phase-boundary telemetry.** Record available RAM, process private/working set, and per-adapter dedicated/shared GPU bytes at start, model-ready, first prefill, first decode, and warm decode.
2. **Bisect the build-702 to build-739 memory regression.** Use the 16k/b512/u128 first-request watchdog result as the binary oracle. Keep all launch flags fixed.
3. **Produce the tensor/allocation ledger.** Run with debug verbosity and capture tensor bytes/device plus non-weight buffers. Determine why a nominally all-GPU load drives a ~99 GB host working set.
4. **Search placement before kernels.** Sweep device order and `-ts` values while retaining the layer-44 CPU override. Reject any arm below 10 GB host headroom after a cold request.
5. **Retest 128k only after memory attribution.** Do not lower the watchdog or adopt 16k/32k as the live service to manufacture a passing result.
6. **Resume ESIMD/kernel work only after the 128k baseline survives.** Speed comparisons taken while paging or near the watchdog floor are not valid.

## Immediate hypothesis record

```text
Hypothesis: one upstream allocation/reorder change increased first-request host residency,
while the existing layer-44 CPU override or WDDM backing causes the common ~99 GB peak.
Affected path: model load, CPU tensor override, first prefill/decode allocation.
Measured fraction: currently an operational gate; failed arms have no valid throughput.
Expected mechanism: remove unintended host residency or redistribute VRAM allocations.
Correctness risk: low for placement-only work; standard gates still required.
Rollback: retain build 702 / r67c and the unchanged live llama-swap entry.
Go threshold: 128k cold request completes with >=10 GB host RAM free.
Stop condition: placement search cannot recover the required bytes; proceed to minimal mixed quant.
```
