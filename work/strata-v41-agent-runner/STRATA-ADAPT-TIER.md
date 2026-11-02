# Strata, 2 cards: `--adapt-every 0` gives +49% in `generate`; no clear effect when serving (2026-10-28/29)

Qwen3.8-Flash-Next GSQ-RCO IQ3_S, Strata v0.2.7 SYCL JIT build, 2x B70, `--expert-cache auto
--expert-cache-device1 auto`, int8 KV, `--spec 4 --spec-min-p 0`, English draft vocab, 8k context.
Harnesses: `box-s21.ps1` (RemoteExperts patch A/B), `box-s22.ps1` (adaptive tier A/B).

## Result

Configs interleaved per repetition, same binary (unpatched), only the flag differs:

| Code prompt, 64 new tokens | run 1 | run 2 | run 3 | median |
|---|---:|---:|---:|---:|
| default (`--adapt-every 4`) | 51.33 | 51.20 | 51.45 | **51.3** |
| `--adapt-every 0` | 76.65 | 76.49 | 76.56 | **76.6** |

| Short prompt (7 tokens), 32 new | median of 3 |
|---|---:|
| default | 26.7 |
| `--adapt-every 0` | **45.9** |

- Code prompt: output tokens identical in every run (same hash across all 15 runs of both harnesses).
- Short prompt: output identical for the first 22 tokens, then a different but equally coherent
  continuation. With the tier off there are no CPU experts, so every expert runs in the GPU kernel instead
  of some in the CPU's AVX2 kernel; a greedy near-tie at token 23 flips. Not a correctness bug.

## Why

| ms per round (code prompt) | default | `--adapt-every 0` |
|---|---:|---:|
| adaptive tier swap | 16.5 | 0 |
| CPU pool call | 12.7 | 8.9 |
| CPU experts per layer (distinct) | 0.19 | **0.00** |
| verify `wait for rings` | 21.5 | 21.2 |

At start, all 24,576 experts are placed: 10,618 on card 0 and 13,958 on the helper card. The adaptive tier
exists to pull hot experts into VRAM when not all of them fit. Here it is pure churn: every 4 rounds it
swaps up to 480 experts into card 0, which evicts others. Evicted experts the helper does not hold fall to
the CPU, which reads each one from the GGUF (`--stream-experts`, ~2.6 MB per expert) on the critical path.

The skip check in `generate.cpp` only looks at the primary card:

```cpp
const bool all_experts_resident = !host_res.empty() &&
    std::all_of(host_res.begin(), host_res.end(), [](int32_t r) { return r >= 0; });
if (o.adapt_every > 0 && o.adapt_swaps > 0 && !all_experts_resident) ...
```

Upstream fix to suggest: count an expert as resident if card 0 **or any helper** (`RemoteExperts::holds`)
holds it, and skip the tier when the union covers every expert. Until then, pass `--adapt-every 0` whenever
the helpers' "additional experts" plus the primary cache cover the full expert set.

## Ruled out: the RemoteExperts launch/wait patch (s21)

Patched `remote_experts.cpp` behind env switches (`STRATA_REMOTE_SPIN=1`: poll the queue's last event
instead of a blocking wait; `STRATA_REMOTE_HOSTMETA=1`: kernels read the group tables from pinned host
memory, one copy fewer per layer). Code prompt, n=3 interleaved, base run 1 excluded as a cold start:

| | base | spin | host meta | both |
|---|---:|---:|---:|---:|
| decode tok/s | 51.3 | 50.5 | 51.2 | 51.5 |
| helper wait (`run`) ms/round | 4.6 | 4.7 | 4.7 | 4.9 |

No gain: the blocking wait was not sleeping, and the helper wait is real GPU + PCIe time. The patch was
reverted; the diff is kept as `remote-spin-hostmeta.patch` for the record.

## The served build: re-tested 2026-10-29

The served llama-swap entry runs the older lab build (2-card `--expert-parallel-device 1`, 200k context),
not v0.2.7.

**Correction.** The first version of this section (2026-10-28) said `--adapt-every 0` cuts served decode from ~100 to
~40 tok/s. That was one flagged start against one default start. A re-test with several fresh starts shows the served
speed is decided at start-up and then holds for that process, and it varies a lot from start to start, flag or not:

| Fresh start (alternating) | flag | default |
|---|---:|---:|
| 1 | 57.7 - 60.5 | 99.3 - 104.8 |
| 2 | 97.2 - 102.9 | 96.9 - 101.8 |
| 3 | 62.8 - 65.2 | 72.5 - 76.0 |

Each cell: the same two `swap-check.py` chat requests, run twice per start (`adapt-starts.sh`). The answers were the same in
every start. The start-up PCIe probe (9.4 - 12.8 GB/s) does not predict which speed a start gets.

So there is no clear served effect of the flag; three starts each are not enough to see a difference of this size
through the start-to-start variance. The served config stays at the default. The CLI `generate` numbers (35-64 -> ~90
with the flag) remain CLI-only, and so does the v0.2.7 +49% above.

## Same-day head-to-head (2026-10-29)

After a reboot, both through llama-swap, 4 prompts x 3 rounds, every request cold (unique first line,
`cache_prompt: false`, 0 cached tokens), `temperature 0`, thinking off for both (`enable_thinking: false`), up to 400
new tokens (`swap-ab.py`):

| Prompt | Strata lab build, IQ3_S, 2 cards | llama.cpp fork r62, UD-Q4_K_XL + MTP draft, 4 cards |
|---|---:|---:|
| code | 115.5 | 73.5 |
| prose | 72.5 | 37.6 |
| explain | 86.1 | 46.1 |
| summary | 84.1 | 50.4 |
| **median of 12** | **84.2 tok/s** | **50.4 tok/s** |

Prompt read on these short prompts was similar (~110 tok/s each). Different quantizations (IQ3_S vs Q4_K_XL), so this
compares setups, not engines at equal precision.

## Slow state and reboot (2026-10-29)

Earlier the same day, after a 4-card run that left the host with 0.4 GB of free RAM, every served Strata start ran
at ~39 tok/s. The same 232-token request with the same accepted drafts (155 of 231) took 5,920 ms, against 2,232 ms the
day before. Start-up logs, config, CPU load, driver and card status were unchanged, and re-reading the n-gram table
into the file cache did not help. A reboot restored 87-104 tok/s. Cause not found.

## Still open

- What decides a served start's speed (58-100 tok/s with identical config), and what caused the slow state that only a
  reboot cleared.
- `wait for rings` (~21 ms/round) is now the largest single term in v0.2.7 `generate`: card 0's own per-layer
  time, flat in tokens per window, so overhead-dominated. Needs a per-kernel GPU profile.
