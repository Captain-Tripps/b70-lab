# MTP draft vocabulary by token frequency - 2026-11-15

## Decision

Rejected (measured 2026-11-15). Lead L8: shorten the MTP draft that the decode profile showed in series with the tail
stage. The candidate engine takes the draft vocabulary from a list of token ids ranked by frequency instead of by id.
It works as built: the draft drops 2.20 -> 1.77-1.85 ms a step, acceptance and greedy output are unchanged. Decode speed
does not move (code 54.58 -> 54.50-54.61 tok/s, prose 45.00 -> 44.88-44.97), because the step waits on the tail
stage longer by the same amount. The draft is not on the critical path the way the profile read suggested. Nothing
changed on the live server.

## Why the draft head

The [decode profile](../2026-11-14-decode-profile/) puts the MTP draft at 2.22 ms of an 18.9 ms step, in series with
the tail stage. CUDA3 runs the output head twice a token (the token and the draft): its dense mat-vec averages 110 us
a call against 73-87 us on the other cards. Since fixups35 the draft head reads only the draft vocabulary: token ids
below 98,304 (GLM's Latin and code block) plus 437 digit and control tokens, 98,741 of 154,880 rows, 316 of 496 MB a
draft (the live engine log says so). At the head's ~420 GB/s that is ~0.75 ms of the draft.

Cutting by id does not work: GLM's ids are laid out by script, not by frequency, so the 32,768 id prefix drops common
English and code tokens. That test (2026-11-01, [README](../../README.md)) gave 45.9 tok/s but acceptance 83.3 -> 81.5%.

## The frequency-ranked vocabulary

[`dvocab.py`](dvocab.py) tokenizes text with the pack's own tokenizer (byte-level BPE from `vocab.json` / `merges.txt`,
the GLM-4 split pattern, `ignore_merges`; round trip checked), splits each corpus's files 4:1 train/test by a hash of the
path, ranks ids by train frequency with each corpus weighted equally, and counts, per corpus on its test files, the
tokens outside each candidate vocabulary. Every candidate also keeps the digit-only tokens and the control /
user-defined tokens (roles, `<think>`, tool-call tags), as the live vocabulary does.

Two runs:

1. Code only: the engine tree and a llama.cpp checkout, 20.3M train / 3.55M test tokens
   ([raw](coverage-code-v1.txt)).
2. Prose + code: the lab's locally generated books (final chapters and module outputs of 31 books, 8.2M train / 2.2M
   test tokens) and a broader code set (llama.cpp, this repo, the book pipeline's Python; 15.0M / 4.1M)
   ([raw](coverage-prose-code.txt)). The book text stayed on the lab machines and was deleted after counting; only the
   id lists are kept.

Run 2, tokens outside the vocabulary per 1,000 test tokens:

| Draft vocabulary | Rows | MB a draft | Prose | Code |
|---|---:|---:|---:|---:|
| Live (ids below 98,304 + extras) | 98,741 | 316 | 0.28 | 0.45 |
| Id prefix 32,768 + extras (rejected 2026-11-01) | 33,205 | 106 | 85.5 | 81.8 |
| Top 24,576 by frequency + extras | 24,736 | 79 | 9.3 | 33.4 |
| Top 32,768 by frequency + extras | 32,928 | 106 | 3.2 | 18.4 |
| **Top 40,960 by frequency + extras** | 41,120 | 132 | 1.1 | 10.2 |
| **Top 49,152 by frequency + extras** | 49,312 | 158 | 0.40 | 5.9 |

Run 1 had top 32k at 3.5 misses per 1,000 on its narrower code set; the broader code set needs more rows. The frequent
tokens are spread over the whole id range, so nearly all rows are gathered.

What to expect: the engine notes that a miss costs the round its later drafts, ~0.9% of a round's tokens per 1% of
tokens missed, and the draft head reads at ~420 GB/s in an 18.9 ms step. Top 49k reads 158 MB less (~0.38 ms, ~2.0%)
for ~0.5% more misses on code and ~0 on prose: roughly +2% decode on prose, +1.5% on code. Top 40k: ~+2% prose, ~+1.3%
code. Both sit under the 3% keep threshold unless the A/B beats the estimate. Measure, do not assume.

## The engine change

[`patch_dvocab.py`](patch_dvocab.py) on the live (aligned Q6_K) tree, one file, `src/core/glm_mtp.dp.cpp`:

- `STRATA_GLM_MTP_DRAFT_IDS=<file>` (also read as `MAYA_GLM_MTP_DRAFT_IDS`): int32 little-endian token ids. The draft
  vocabulary is those ids plus the digit-only and control / user-defined tokens; its longest id prefix stays the
  in-place block and every other id becomes a gathered row (the existing `mtp_dx` path, one launch). Unset or an empty
  file: the live auto vocabulary, unchanged.
- The gathered rows are copied to the device with one wait at the end instead of one a row (now ~33k rows).
- The draft-miss fallback is unchanged: when the emitted tokens leave the vocabulary (EMA over ~64 tokens above 2%),
  the round drafts over the whole head.

[`build_dvocab.py`](build_dvocab.py) copies the live tree, patches, compiles that one file and relinks into a
separate candidate folder (the patch also turns that file's CRLF line ends into LF; no effect on the build). Result:
1 file compiled, 0 errors; linked, 0 unresolved; candidate `generate.exe` `166c2842...`.

## A/B (2026-11-15)

Same session, GLM unloaded, CLI greedy decode on the live engine settings with `STRATA_GLM_SPEC_PROF=1`, 1,500 new tokens
from a 200-token prompt, thinking off. Two prompts: code (the decode-profile prompt) and prose (the opening of a
locally generated book chapter). Order per prompt: live, 49k, 40k, candidate with no list, 40k, 49k, live.

| Arm | Code tok/s | Code accepted | Prose tok/s | Prose accepted | Draft ms a step (code / prose) |
|---|---:|---:|---:|---:|---:|
| Live exe, run 1 | 54.58 | 96.9% | 45.01 | 75.2% | 2.21 / 2.20 |
| Candidate + top 49k, run 1 | 54.61 | 96.9% | 44.90 | 75.2% | 1.84 / 1.85 |
| Candidate + top 40k, run 1 | 54.53 | 96.9% | 44.88 | 75.1% | 1.78 / 1.78 |
| Candidate, no list | 54.56 | 96.9% | 45.05 | 75.2% | 2.21 / 2.18 |
| Candidate + top 40k, run 2 | 54.59 | 96.9% | 44.95 | 75.1% | 1.77 / 1.76 |
| Candidate + top 49k, run 2 | 54.50 | 96.9% | 44.97 | 75.2% | 1.85 / 1.83 |
| Live exe, run 2 | 54.62 | 96.9% | 44.99 | 75.2% | 2.19 / 2.21 |

Checks, all passed:

- All 14 runs give the same 1,500 tokens as live run 1 on their prompt.
- The engine log names the list it loaded: 49,312 ids (106 in place + 49,206 gathered, 158 of 496 MB a draft) and
  41,120 ids (95 + 41,025).
- CUDA3 still holds every expert in VRAM ("complete: every expert") with the gathered rows.
- With no list, the candidate matches live (54.56 / 45.05 tok/s, draft 2.21 / 2.18 ms).

Why it does not pay: per step (ms), the draft saves 0.36-0.44 ms, and the wait for the tail token plus the tail
enqueue grow by about as much (code live 7.94-8.33 wait + 7.62-7.97 enqueue, lists 8.25-8.73 + 7.55-8.06; prose
similar). The tail stage sets the step time; the draft overlaps it rather than adding to it. So shortening the draft
further (a smaller list, a lower-bit head) would not help either. The decode levers left are the tail stage itself.

## Setup

4x Arc Pro B70, Windows 11, driver 32.0.101.9175, oneAPI 2026.0 JIT. Live executable `2c21539a...` (aligned Q6_K,
2026-11-14). Tokenizing and the build ran on the CPU at below-normal priority with GLM serving; no GPU work.
