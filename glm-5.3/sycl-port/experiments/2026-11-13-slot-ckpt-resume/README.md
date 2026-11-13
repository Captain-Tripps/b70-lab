# An edit straight after a switch resumes from the slot's carried checkpoint: screen — 2026-11-13

## Decision

Promoted 2026-11-13 at Jon's request, without a soak; see the [promotion record](promotion.md). A 30-minute
[soak](#soak) on the live build afterwards was clean. With the [slot checkpoint carry](../2026-11-13-slot-carry-ckpt/)
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

## Soak

The live build, live config and live server tree unchanged, port 9080, 30 minutes, 14:03–14:32 CST
([`soak_resume.py`](soak_resume.py), [`soak-requests.jsonl`](soak-requests.jsonl)). The 2026-11-12 mix plus, each
cycle, an edit of the 115k conversation's last message with new text straight after the 7.7k switch. GLM was
unloaded for it with Jon's OK and reloaded afterwards. Compared with the
[carry control soak](../2026-11-13-slot-carry-ckpt/#soaks), which had no straight edits.

| Request, median first token | Carry control (96 cycles) | Live resume build (49 cycles) |
|---|---:|---:|
| Straight edit after a switch | — | 1.026 s (0.93–1.12, n = 49) |
| Repeated edit 2 / 3 | 0.957 / 0.959 s | 0.957 / 0.941 s |
| Append | 0.864 s | 0.860 s |
| Return to 115k | 0.456 s | 0.960 s |
| 32k switch | 0.787 s | 28.78 s |
| Extra conversations 0 / 1 | 0.726 / 0.224 s | 7.40 / 6.53 s |
| Cancel / retry | 1.466 / 0.053 s | 1.082 / 0.053 s |

- All 49 straight edits used the new path: 61 `for its checkpoint` take-backs, no full re-read.
- All 12 request types shared with the control soak gave the same answer as there, and one hash each throughout.
- No engine error or crash, no byte-cap evictions, minimum free RAM 79.7 GiB.
- The return is slower because it now follows the straight edit, so the engine parks that edit first, as for a
  repeated edit.
- The 32k switch and the extras read again every time. Each straight edit has new text, so every cycle parks one
  more distinct conversation against `STRATA_GLM_SLOTS=8` and the least recently used are dropped by count, as in
  the [first carry soak](../2026-11-13-slot-carry-ckpt/#soaks). That comes from the workload: the same edits on a
  build without the resume path park the same conversations, after a full re-read each.
- Zeus dropped off the network twice during the run, at about 14:10 and 14:29. The soak ran through both with no
  gap between requests; the System log shows only a DNS timeout at 14:11, no adapter, driver or power event.

## Limits

- The A/B screen is three samples per arm on one 115k conversation, one short conversation.
- Not covered: disk slots, images, the several-conversation scheduler (checkpoints are off there).
- The prompt must start with the carried checkpoint: the turn start of the parked conversation. Editing an older
  message, before that checkpoint, still reads from the slot's longest whole prefix or from token 0.

## Next action

It went live without a soak; the 30-minute soak above, run afterwards on the live build, was clean. Workloads with
more distinct long conversations than `STRATA_GLM_SLOTS` drop slots by count; that limit, not this path, is the next
thing a heavy multi-conversation workload hits.
