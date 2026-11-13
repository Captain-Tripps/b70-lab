# Prompt preparation (L3): upside ceiling on the live config — 2026-11-13

## Decision

Do not build the full upstream `MAYA_PROMPT_MEMO` backport for speed. On the live config, a 115k-token follow-up
waits a median 0.909 s for its first token, and all measured CPU-side preparation is about 36 ms of that. The
pilot's memo pieces recover about 22.5 ms (2.5%). The rest of the upstream feature can recover at most the
remaining render time, so the full port tops out near 3.7% in the best case and is likely lower. No new
measurement was taken for this note.

## Inputs

| Measure, 115k-token follow-up | Value | Source |
|---|---:|---|
| Live-config first-token time, median of 294 long edits at 115,116 tokens | 0.909 s | [slot branches mixed soak](../2026-11-12-slot-branches/) |
| Same, 10th / 90th percentile | 0.407 / 0.944 s | same `mixed-requests.jsonl` |
| Render and tokenize, memo off / on | 13.786 / 10.926 ms | [prompt memo pilot](../2026-11-10-prompt-memo-screen/) |
| Token-ID serialization, memo off / on | 22.329 / 2.653 ms | same |

The pilot's served test measured 2.5 s first-token time, before RAM slots and `STRATA_GLM_SLOT_KEEP_BRANCH` went
live. The 0.909 s figure is the current baseline.

## Reasoning

1. Measured preparation with the memo off is 13.786 + 22.329 = 36.1 ms, 4.0% of 0.909 s.
2. The pilot ported `PromptMemo` and `join_ids_memo`. They bring it to 10.926 + 2.653 = 13.6 ms, a saving of
   22.5 ms, 2.5%.
3. The full upstream feature adds `LiteralMemo` (`serve/frontend.py`), which avoids re-marking literals in
   unchanged messages. It acts on the 10.9 ms that remains in render and tokenize. Removing all of it would make
   the total saving 33.4 ms, 3.7%. That is the ceiling, and it assumes rendering costs nothing.
4. `deepseek_restore_points_fast`, also gated on `MAYA_PROMPT_MEMO` upstream, is DeepSeek-only and does not apply.
5. The handoff's default keep threshold is 3% above observed noise. The pilot's served samples ranged
   2.245–2.989 s for one arm. A gain of 2.5–3.7% of 0.909 s, 23–33 ms, would need many paired samples to resolve.

## Limits

- HTTP receive, JSON parsing of the request body and the pipe write to the engine were not measured separately.
  They count against the 0.909 s but are not reduced by the memo.
- One synthetic long document and short changed final questions. Other conversation shapes, such as many
  tool-call messages, could spend more time in literal marking.
- The 10th-percentile first-token time is 0.407 s; requests that fast would see a larger share, still at most
  about 33 ms.

## Next action

The remaining 0.87 s of a 115k follow-up is outside prompt preparation: restore, the changed-tail prefill and
engine work. Upstream's server-side `MAYA_TURN_TRACE` marks (`http`, `json`, `rendered`, `encoded`, `gen_written`,
`first_t`) would measure that split directly. It is model-independent and about 20 lines in `serve/server.py`.
Its engine-side half exists only for DeepSeek. That split, and L4 checkpoint spacing, are the next measurements.
Both need a candidate server on the GPUs.
