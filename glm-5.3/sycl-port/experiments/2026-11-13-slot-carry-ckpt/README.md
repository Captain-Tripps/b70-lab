# A RAM slot carrying its turn-start checkpoint: screen — 2026-11-13

## Decision

Keep, as a promotion candidate pending Jon's OK. When a RAM slot parks a conversation, it now keeps a copy of the
longest checkpoint that conversation starts with, and gives it back on return. The first edit with new text after
a switch to another conversation and back drops from a 102 s full re-read to the 1.25 s checkpoint path. All 33
answer hashes match the off arm. Costs: a return to the long conversation is about 60 ms slower, a switch away
from it looks up to ~50 ms slower (3 samples), and the 12 GB slot cap holds 7 slots instead of 8 in this workload.
Not promoted; the live service was not changed.

## Candidate

[`patch_ckpt_carry.py`](patch_ckpt_carry.py), `generate.cpp` only, opt-in with `STRATA_GLM_SLOT_CARRY_CKPT=1`,
RAM slots only:

- `Slot` gains a carried checkpoint: tokens, per-half buffers, position.
- `slot_carry()`, right after `slot_put("")` in `prep_prompt`: copies the longest checkpoint the parked
  conversation starts with into its slot, and counts the bytes toward the slot.
- `slot_give()`, after a take-back's `ckpt_drop_past(0)`: copies the carried checkpoint back into a free or least
  recently used checkpoint, and logs `gave back a checkpoint at <pos>`.

Built from the promoted tree (`f89820fe...`) by recompiling `generate.cpp` only ([`build_carry.py`](build_carry.py)):
candidate sha256 `76295f72...`, 0 compile errors, 0 unresolved.

## Setup

The [checkpoint screen](../2026-11-13-slot-keep-ckpts/) workload and runner with this candidate, port 9079: live
config, the [turn trace](../2026-11-13-turn-trace/) server copy, one prime and four cycles. Arm off, then on, one
executable ([`run_screen.py`](run_screen.py), [`both.py`](both.py)). llama-swap had nothing loaded and was not
touched. Run 2026-11-13 10:51–11:05 CST. Afterwards no engine or test server remained and the cards were back to
0–0.67 GB.

## Results

[`off-requests.jsonl`](off-requests.jsonl), [`on-requests.jsonl`](on-requests.jsonl).

| 115k follow-up | n per arm | Off | On |
|---|---:|---:|---:|
| First new-text edit after a switch and return (cycles 2–4) | 3 | 102.20–102.35 s, median 102.27 | 1.24–1.29 s, median 1.25 |
| Second new-text edit in the same cycle | 3 | 1.22–1.46 s, median 1.32 | 1.23–1.32 s, median 1.24 |
| New-text edit before any switch (cycle 1) | 2 | 1.13–1.17 s | 1.13–1.22 s |
| Repeated edit served from a slot (cycles 2–4) | 9 | median 0.904 s | median 0.902 s |
| Return to the long conversation | 4 | 0.356–0.441 s, median 0.373 | 0.429–0.439 s, median 0.434 |
| Append | 4 | median 0.668 s | median 0.660 s |
| 7.7k switch (cycles 2–4) | 3 | 0.66–0.75 s | 0.71–0.87 s |

- **Answers:** all 33 hashes match between arms. That includes the three edits the off arm answered after a full
  re-read and the on arm answered from a carried checkpoint. The candidate with the switch off matches the promoted
  build on all 25 requests shared with the turn-trace run.
- **Engine:** the on arm logged 16 `gave back a checkpoint` lines, at 115,103 for the long conversation and 7,673
  for the short one.
- **Slots:** the on arm kept 7 slots at 11.64 GB and evicted the least recently used to stay under the 12 GB cap.
  The off arm kept 8 at 12.47 GB.
- **RAM:** minimum free physical memory was 79.1 GiB on, 79.8 GiB off.

## Limits

- One run per arm, one synthetic document, short changed final questions. Returns are slower by about 60 ms at the
  median, but one off-arm sample overlaps the on range.
- The carried bytes count toward the cap from the next `slot_put`, so the cap can be briefly exceeded by one
  checkpoint (about 150 MB).
- Only the longest prefix checkpoint is carried. An edit further back than the last turn still falls back to an
  older checkpoint or a full read.
- Not tested: disk slots (unchanged by design), images, the several-conversation scheduler (checkpoints are off
  there), cancellation, and a long mixed soak.

## Next action

If Jon wants it live: a mixed soak with `STRATA_GLM_SLOT_CARRY_CKPT=1` on this candidate, then a promotion that
swaps the live executable and adds the variable to the live config. That needs his OK. The return cost could be
trimmed by moving buffers instead of copying them where the model's copy is about to be overwritten anyway.
