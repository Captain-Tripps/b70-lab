# Keeping checkpoints through a slot take-back: screen — 2026-11-13

## Decision

Reject. Keeping the checkpoints a restored conversation starts with, instead of dropping all of them when a slot
is taken back, does not remove the 102 s re-reads found in the [turn trace](../2026-11-13-turn-trace/). By the time
the slot is taken back, the switch to the other conversation has already dropped the checkpoint. The patch changes
no answer, so it is safe, but it does nothing useful. Not promoted. The fix has to carry the turn-start checkpoint
with the slot itself.

## Candidate

[`patch_ckpt_keep.py`](patch_ckpt_keep.py) changes one line in `generate.cpp` `prep_prompt`: after `slot_take`,
`ckpt_drop_past(0)` becomes "drop only the checkpoints that are not a prefix of the restored conversation". Opt-in
with `STRATA_GLM_SLOT_KEEP_CKPTS=1`. Built from the promoted tree (`f89820fe...`) by recompiling `generate.cpp` only
([`build_ckpt.py`](build_ckpt.py)): candidate sha256 `b0c4ce49...`, 0 compile errors, 0 unresolved.

## Setup

The [turn trace](../2026-11-13-turn-trace/) setup with the candidate executable: live config, the trace server copy
(`a304ed85...`), port 9078, a fourth cycle. Arm off, then arm on, one executable
([`run_screen.py`](run_screen.py), [`both.py`](both.py)). llama-swap had nothing loaded and was not touched. Run
2026-11-13 10:24–10:43 CST. Afterwards no engine or test server remained and the cards were back to 0–0.67 GB.

## Results

[`off-requests.jsonl`](off-requests.jsonl), [`on-requests.jsonl`](on-requests.jsonl).

| 115k follow-up | Off | On |
|---|---:|---:|
| First new-text edit after a switch and return (cycles 2–4) | 101.95–102.11 s | 102.07–102.17 s |
| Second new-text edit in the same cycle | 1.22–1.40 s | 1.19–1.24 s |
| Repeated edit served from a slot (cycles 2–4) | 0.85–1.30 s | 0.81–0.96 s |
| Return / append | 0.36–0.41 / 0.66–0.67 s | 0.37–0.38 / 0.66 s |

- All 33 answer hashes match between arms.
- The candidate with the switch off matches the promoted build's answers on all 25 requests shared with the
  turn-trace run.
- The on arm's engine log shows `SLOT_KEEP_CKPTS=1`, so the setting reached it.

The repeated-edit range is lower in the on arm. The off arm had one 1.30 s request, and the patch does not touch
that path's save or take-back, so this is not claimed as an effect.

## Why it missed

The request order is: new-text edits from the turn-start checkpoint, a 7.7k switch, a return to the 115k
conversation, an append, then repeated edits.

1. The switch reads from position 0. `prep_prompt` runs `model.reset(); ckpt_drop_past(0)`, which is correct
   because it overwrites the attention caches the checkpoints depend on.
2. The return restores those caches from a RAM slot. Slots store no checkpoints, so the one at 115,103 is gone.
3. The take-back's own `ckpt_drop_past(0)`, the line this patch changes, has nothing useful left to drop.

## Next action

Carry the turn-start checkpoint with the slot. Done the same day:
[slot carrying its checkpoint](../2026-11-13-slot-carry-ckpt/), 102 s down to 1.25 s with matching answer hashes.
