# An edit straight after a switch resumes from the slot's carried checkpoint: screen — 2026-11-13

## Decision

Promoted 2026-11-13 at Jon's request, without a soak; see the [promotion record](promotion.md). With the [slot checkpoint carry](../2026-11-13-slot-carry-ckpt/)
live, an edit of the last message sent straight after switching back still read all 115k tokens again: a RAM slot
is only taken back when the new prompt contains its whole conversation. This candidate takes back the slot whose
carried checkpoint the prompt starts with instead, restores that checkpoint and reads only the rest. That edit
drops from 101.5 s to about 1 s, and all 16 answer hashes match the carry-only arm.

## Candidate

[`patch_ckpt_resume.py`](patch_ckpt_resume.py), on top of the carry patch, `generate.cpp` only, opt-in with
`STRATA_GLM_SLOT_CKPT_RESUME=1` (needs `STRATA_GLM_SLOT_CARRY_CKPT=1`), RAM slots and text prompts only:

- `slot_ck_pick()`: when the prompt goes past the model's state and its checkpoints, the slot whose carried
  checkpoint is the longest prefix of the prompt, and only if that is longer than every slot the prompt continues
  whole.
- `slot_take_ck()`: loads that slot's full state, hands its checkpoint back (`slot_give()`), restores it with
  `ckpt_restore()` and returns the checkpoint's length, the same in-place restore the model's own checkpoints use.
  Logs `took back a <n>-token conversation from RAM for its checkpoint at <pos>`. If either step fails, the prompt
  is read from token 0 as before.
- Otherwise `slot_take()` as before.

Built from the carry tree (`76295f72...`, the live executable) by recompiling `generate.cpp` only
([`build_resume.py`](build_resume.py)): candidate sha256 `16ad8a269af9004c2001b815edbf816919474532d0c2f96bdea61fa499579d21`,
0 compile errors, 0 unresolved.

## Setup

The live config with this candidate, the [turn trace](../2026-11-13-turn-trace/) server copy, port 9079. Both arms
had the carry on; the on arm added `STRATA_GLM_SLOT_CKPT_RESUME=1`. One 115k prime, then three cycles of: a 7.7k
switch, an edit of the long conversation's last message with new text, another switch, an unchanged return to that
edit, and another new-text edit ([`run_screen.py`](run_screen.py), [`both.py`](both.py)). GLM was unloaded from
llama-swap first, with Jon's OK, after 11 idle minutes, and left unloaded afterwards at his request. Run
2026-11-13 13:03–13:15 CST. Afterwards no engine or test server remained and the cards were back to 0–0.67 GB.

## Results

[`off-requests.jsonl`](off-requests.jsonl), [`on-requests.jsonl`](on-requests.jsonl).

| 115k follow-up | n per arm | Carry only | Carry + resume |
|---|---:|---:|---:|
| New-text edit straight after a switch | 3 | 101.45–101.59 s | 0.94–1.04 s |
| Unchanged return after another switch | 3 | 0.438–0.454 s | 0.433–0.450 s |
| New-text edit after that return | 3 | 1.28–1.31 s | 1.25–1.35 s |
| 7.7k switch (after its first read) | 5 | 0.58–0.61 s | 0.58–0.62 s |

- **Answers:** all 16 hashes match between arms, including the three straight edits the carry-only arm answered
  after a full re-read and the on arm answered from the carried checkpoint.
- **Engine:** the on arm logged three `took back ... for its checkpoint at 115103` lines, 0.2–0.3 s each, with 13 new
  tokens to read. The off arm logged none.
- **Slots and RAM:** both arms ended with 7 slots at 11.64 GB; minimum free physical memory 81.5 GiB off, 81.6 on.

## Limits

- Three samples per arm on one 115k conversation, one short conversation. No soak.
- Not covered: disk slots, images, the several-conversation scheduler (checkpoints are off there).
- The prompt must start with the carried checkpoint: the turn start of the parked conversation. Editing an older
  message, before that checkpoint, still reads from the slot's longest whole prefix or from token 0.

## Next action

It went live without a soak. A mixed soak with edits straight after switches is still the open check; it needs the
cards, so GLM unloaded.
