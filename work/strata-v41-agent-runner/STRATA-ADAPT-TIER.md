# Strata v0.2.7, 2 cards: `--adapt-every 0` gives +49% decode (2026-10-28)

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

## Still open

- `wait for rings` (~21 ms/round) is now the largest single term: card 0's own per-layer time, flat in
  tokens per window, so overhead-dominated. Needs a per-kernel GPU profile.
- The served Strata entry is the older lab build (`--expert-parallel-device`), not v0.2.7. Whether the flag
  helps there is untested.
