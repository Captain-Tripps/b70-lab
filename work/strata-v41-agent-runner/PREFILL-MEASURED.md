# 1017 prefill — MEASURED (2026-10-28 00:48)

First clean measurement on a fully idle box, with llama-swap stopped. This supersedes the
"no number produced" state in `PREFILL-INVESTIGATION.md`.

-

## 1. The number

```
slot operator(): id 0 | task 0 | new prompt, n_ctx_slot = 2048, n_keep = 0, task.n_tokens = 134
slot print_timing: id 0 | task 0 | prompt processing, n_tokens = 27, progress = 0.20,
                  t = 31.75 s / 0.85 tokens per second
```

| Metric | Value |
|---|---|
| Prompt | 134 tokens |
| Processed before crash | 27 tokens (20%) |
| Time | 31.75 s |
| **Prefill rate** | **0.85 tok/s** |
| Previous recorded rate | 0.33 tok/s |

**Prefill improved 2.6x** (0.33 -> 0.85 tok/s) versus the figure in the ledger. That is consistent
with the HC-fusion patch working: all three fused ops report `enabled` on this run.

## 2. It still crashes — and the crash point is named

```
I slot create_check: id 0 | task 0 | created context checkpoint 1 of 32
   (pos_min = 26, pos_max = 26, n_tokens = 27, size = 1.083 MiB)
==== srv-v41 exit -1 Wed 10/28/2026 0:48:25.65 ====
```

The server exits **immediately after creating a context checkpoint**. Not during inference, not at
buffer allocation — at the checkpoint write, one line after it succeeds.

This matches the earlier session's suspicion (L-021/L-022): *"`--cache-ram` / context checkpoints
machinery"* was listed as candidate #2 for the server-only crash, and probe B
(`--cache-ram 0 --ctx-checkpoints 0`) was proposed but never conclusively run.

**`srv-v41.bat` does not disable checkpoints.** The fix to try next is one flag:
`--ctx-checkpoints 0 --cache-ram 0`.

## 3. What this means

### Good news
- The pack **loads** on an idle box: `srv-v41.bat` reached `model loaded` + `listening`.
- **Fused HC ops are enabled** (pre/comb/post), so the earlier patch is live and effective.
- Prefill is **2.6x faster** than the recorded 0.33 tok/s.
- Batching **is** engaging: `sched_reserve` reports `graph (pp bs=512, tg bs=1): nodes = 4910 / 4844,
  splits = 166 / 13`. 166 splits for the pp graph versus 13 for tg is what a batched prompt path
  looks like. The "batched prompt path is dead" hypothesis is **not supported**.

### Bad news
- 0.85 tok/s is still unusable. A 4,096-token prompt would take **80 minutes**.
- The server dies at 27 tokens because of the checkpoint crash, so nothing beyond 27 tokens has ever
  been measured.

## 4. The `-ts` hypothesis was evaluated and set aside

I planned to test `-ts` to keep compressed-KV source layer 20 with its readers. The arithmetic
rules it out on this box:

- 41 layers; source 20's reader set is 21-40 (19 readers).
- Keeping 20 with all readers means card 0 holds layers 0-20 = **21/41 = 51% of weights =
  65.9 GiB**, against ~31.8 GiB per card. Impossible.
- The default even split already sits at ~29.8 GiB/card with `-ngl 38` (3 layers on CPU). There is
  no spare VRAM to shift the boundary.

So **`-ts` cannot fix the 20|21 crossing on 4x32 GB.** The upstream advice (`-ts 48,52`) is
2-GPU-specific (48%/52% boundary lands at layer 20) and does not generalize to 4 cards.

## 5. Next step, cheap and specific

Edit `srv-v41.bat` to add `--ctx-checkpoints 0 --cache-ram 0`, then one more run. If it survives past
27 tokens, we get the real prefill number for a full 134-token prompt and can judge whether 0.85
tok/s holds or improves as the batch widens.

No production impact — llama-swap is already back up and serving.

## 6. State

| Item | Value |
|---|---|
| llama-swap | **Running** (restored) |
| VRAM | all cards 0 GB (idle, no model resident) |
| Free RAM | 84.8 GB |
| 1017 processes | none |
| Log | `C:\b70-work\srv-v41.log` |

## 7. Caveat

One run, one prompt, 27 tokens. The 0.85 figure is from a single `print_timing` line and could be
affected by the crash that followed it. It is better evidence than 0.33 (which had the same
weakness) but it is not a variance-bounded measurement.
