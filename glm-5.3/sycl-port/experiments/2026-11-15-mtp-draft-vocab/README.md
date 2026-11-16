# MTP draft vocabulary by token frequency - 2026-11-15

## Decision

Built, not measured on the GPUs yet. Lead L8: shorten the MTP draft that sits in series with the tail stage every
decode step. The candidate engine takes the draft vocabulary from a list of token ids ranked by frequency instead of
by id. On held-out text it misses 3.5 tokens per 1,000 at 32,928 rows, where the 32k id cut tried on 2026-11-01 missed
68. Nothing changed on the live server. The decode A/B needs the GPUs (GLM unloaded), so it waits for a quiet window.

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
the GLM-4 split pattern, `ignore_merges`; round trip checked), splits the files 4:1 train/test by a hash of the path,
ranks ids by train frequency and counts, on the test files, the share of tokens inside each candidate vocabulary.
Every candidate also keeps the digit-only tokens and the control / user-defined tokens (roles, `<think>`, tool-call
tags), as the live vocabulary does. [Raw output](coverage.txt).

Corpus for this first list: public source code and documentation only (the engine tree and a llama.cpp checkout,
C++ / Python / Markdown), 20.3M train tokens, 3.55M test tokens. So the numbers describe code and technical English.
Long-form prose (the nightly book pipeline, GLM's main daily job) is not in it yet.

| Draft vocabulary | Rows | MB a draft | Test tokens outside it, per 1,000 |
|---|---:|---:|---:|
| Live (ids below 98,304 + extras) | 98,741 | 316 | 0.38 |
| Id prefix 32,768 + extras (rejected 2026-11-01) | 33,205 | 106 | 67.8 |
| Top 16,384 by frequency + extras | 16,544 | 53 | 18.6 |
| Top 24,576 by frequency + extras | 24,736 | 79 | 7.8 |
| **Top 32,768 by frequency + extras** | 32,928 | 106 | 3.5 |
| **Top 40,960 by frequency + extras** | 41,120 | 132 | 1.9 |
| All 44,757 ids seen in training + extras | 44,917 | 144 | 1.4 |

The frequent tokens are spread over the whole id range (the longest fully covered id prefix is 95 ids), so nearly all
rows are gathered.

What to expect: the engine notes that a miss costs the round its later drafts, ~0.9% of a round's tokens per 1% of
tokens missed. Top 32k adds ~0.3% misses for ~210 MB less to read a draft (~0.5 ms of 18.9 ms, ~2.6%). So roughly
+2% decode on code if acceptance behaves as that note says. That is under the 3% keep threshold unless the A/B beats
the estimate. Measure, do not assume.

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

## A/B plan (not run)

- Arms: live exe; candidate with no list (must match live); candidate + top 32k; candidate + top 40k. Same session,
  A / B / B / A, `spec_ab.ps1` as for [aligned Q6_K](../2026-11-14-q6k-aligned-gemv/), code and prose prompts
  separately, thinking off, 768 tokens, actual output counts and acceptance recorded.
- Checks: the engine log line for the vocabulary actually loaded; CUDA3 still "complete: every expert" (the gathered
  rows take ~106 MB more VRAM there); greedy output identical to live (the verify decides every token, so output must
  not change; only speed and acceptance can).
- Prose: before deciding, rebuild the list with prose in the corpus (or measure the miss rate on prose prompts in the
  A/B) - the fallback protects other scripts, not English prose with rarer words.

## Setup

4x Arc Pro B70, Windows 11, driver 32.0.101.9175, oneAPI 2026.0 JIT. Live executable `2c21539a...` (aligned Q6_K,
2026-11-14). Tokenizing and the build ran on the CPU at below-normal priority with GLM serving; no GPU work.
