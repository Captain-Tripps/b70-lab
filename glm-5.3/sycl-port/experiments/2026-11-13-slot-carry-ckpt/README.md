# A RAM slot carrying its turn-start checkpoint: screen and soaks — 2026-11-13

## Decision

Keep, as a promotion candidate pending Jon's OK. When a RAM slot parks a conversation, it now keeps a copy of the
longest checkpoint that conversation starts with, and gives it back on return. The first edit with new text after
a switch to another conversation and back drops from a 102 s full re-read to the 1.25 s checkpoint path. All 33
answer hashes match the off arm.

A 30-minute soak on the 2026-11-12 request mix was clean: 96 cycles, every request type gave the same answer as
the 11-12 soak on the live build, and no re-read beyond the first medium switch in either. Cost: requests that park
or restore a slot are about 40–55 ms slower at the median, and each 115k slot is 1.90 GB instead of 1.74 GB. Not
promoted; the live service was not changed.

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

## Soaks

Both used the candidate with `STRATA_GLM_SLOT_CARRY_CKPT=1`, the live config and the live, unmodified server tree
(`76185526...`), port 9080, 30 minutes. The comparison is the
[2026-11-12 mixed soak](../2026-11-12-slot-branches/) on the live build, run a day earlier, not a paired arm.

**Control, the 11-12 mix unchanged** ([`soak_control.py`](soak_control.py),
[`soak-control-requests.jsonl`](soak-control-requests.jsonl)), 11:44–12:15 CST.

| Request, median first token | 11-12, live build (98 cycles) | Carry on (96 cycles) |
|---|---:|---:|
| Repeated edit 2 / 3 | 0.916 / 0.916 s | 0.957 / 0.959 s |
| 7.7k switch | 0.687 s | 0.726 s |
| Return to 115k | 0.412 s | 0.456 s |
| Append | 0.864 s | 0.864 s |
| 32k switch from its slot | 0.733 s | 0.787 s |
| Extra conversations 0 / 1 | 0.683 / 0.177 s | 0.726 / 0.224 s |
| Cancel / retry | 1.460 / 0.053 s | 1.466 / 0.053 s |

- All 12 request types gave one answer hash throughout, the same as the 11-12 soak.
- In both soaks the only request over 10 s besides the prime was the first 32k switch (28.7 s).
- No byte-cap evictions; 553 checkpoint hand-backs; minimum free RAM 80.9 GiB.
- No engine crash.

**First soak, the 11-12 mix plus one new-text edit per cycle** ([`soak.py`](soak.py),
[`soak-requests.jsonl`](soak-requests.jsonl)), 11:09–11:30 CST.

- All 27 new-text edits were fast: 1.13–1.24 s, median 1.21. Without the carry, each would follow a switch and
  re-read 115k.
- Every repeated request type kept one answer hash.
- 2 of 81 repeated edits re-read 115k (102.3 s), right after the two cycles with both the 32k switch and the extra
  conversations. Every 32k switch re-read (28.7 s) and every extra took about 7 s. The cause is mostly this mix: a
  new-text edit parks a ninth distinct conversation every cycle against `STRATA_GLM_SLOTS=8`, so the least recently
  used are dropped by count. The carry added to it: 6 saves evicted to stay under the 12 GB byte cap.
- After 21 minutes, during a 32k switch prefill, the engine crashed: Windows event `0xc0000005` in
  `ze_intel_gpu64.dll` 1.15.39183.4 at offset `0x4d2d87`. That is the same module and offset as the
  [driver crash](../2026-11-11-trim-crash/) already seen on builds without this patch. The production engine also
  aborted on an access violation in the [canary-prep baseline](../2026-11-12-canary-prep/baseline-incident.md). One
  more occurrence; not attributed to the patch, not ruled out. The control soak above, with the same carry and
  30 minutes of cards, did not crash.

## Limits

- One run per arm, one synthetic document, short changed final questions. Returns are slower by about 60 ms at the
  median, but one off-arm sample overlaps the on range.
- The carried bytes count toward the cap from the next `slot_put`, so the cap can be briefly exceeded by one
  checkpoint (about 150 MB).
- Only the longest prefix checkpoint is carried. An edit further back than the last turn still falls back to an
  older checkpoint or a full read.
- Not tested: disk slots (unchanged by design), images, and the several-conversation scheduler (checkpoints are off
  there).
- The soak comparison is against a soak run a day earlier, not a paired arm.
- A workload with more distinct long conversations than `STRATA_GLM_SLOTS` evicts by count with or without the
  carry. The carry makes each 115k slot about 0.16 GB larger.

## Next action

Promotion needs Jon's OK: point the live GLM entry at this executable and add `STRATA_GLM_SLOT_CARRY_CKPT=1` to the
live config. The 40–55 ms per slot switch could be trimmed by moving the checkpoint buffers instead of copying
them where the model's copy is about to be overwritten anyway.
