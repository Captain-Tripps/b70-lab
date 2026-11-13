# Where a 115k follow-up's first-token time goes — 2026-11-13

## Decision

The server is not the cost. From the HTTP request to the token IDs written into the engine pipe takes at most
62 ms on every follow-up. The rest is engine slot and checkpoint work:

- A repeated edit of a 115k conversation (median 0.911 s here, 0.909 s on the live soak) spends 0.4–0.6 s saving
  the current conversation to a RAM slot before it starts, then 0.1–0.2 s taking a saved one back. The GPU copy
  inside that save is 150–191 ms. The remaining 0.3–0.4 s is host-side.
- An edit with new text spends the same 0.5 s on the save, then reads 13 tokens from the turn-start checkpoint
  in 0.5–0.6 s. First-token time 1.13–1.32 s.
- **Cliff:** 2 of 6 new-text edits took 102 s, a full re-read of all 115,116 tokens. Both came right after a
  request served by a slot take-back. That take-back drops every checkpoint, so the next edit that matches no
  whole slot has nothing to resume from.

Two engine leads follow: faster or skipped slot saves (up to ~0.4 s of 0.9 s), and keeping checkpoints across a
slot take-back (102 s down to ~1.2 s on the affected edits). Neither is built. The live service was not changed.

## Setup

- Live config `D:\maya-sycl\configs\glm-maya-sycl-128k.json`, unchanged except its own engine log and
  `STRATA_GLM_SLOT_TIMING=1`. Promoted executable sha256 `f89820fe...`, split `14,25,36`, RAM slots (12 GB,
  8 slots, branch keeping on), MTP, 131072 context, chunk 768.
- Server: an isolated copy of the live `serve/` tree (sha256 `76185526...`) with upstream Maya's server-side
  `MAYA_TURN_TRACE` marks ported by [`patch_trace.py`](patch_trace.py), 42 lines added, off unless the variable is
  set. Patched sha256 `a304ed85...`. Port 9077.
- llama-swap had nothing loaded (`/running` empty; the GLM entry loads on demand) and was not touched. The
  runner aborts if the proxy starts a model or free RAM falls below 16 GiB, and kills its own server tree on exit.
  Run 2026-11-13 10:07–10:15 CST. Afterwards no `generate.exe` or isolated server remained and the cards were back
  to 0–0.67 GB.
- Workload ([`run_trace.py`](run_trace.py)): `long_body.txt[:390000]` (115,116 prompt tokens), one prime, then
  three cycles of three repeated edits, two edits with new text, a 7.7k switch, a return to the long conversation
  and an append. 64 tokens each, greedy, thinking off.

## Results

Per-request first-token time is in [`requests.jsonl`](requests.jsonl); the matching server trace and engine slot
lines are in [`a1-lines.txt`](a1-lines.txt). Server marks use Python's monotonic clock, which ticks every
15.6 ms on Windows.

| Follow-up at 115k | n | First token | Server, HTTP to pipe | Engine work before the first token |
|---|---:|---:|---:|---|
| Repeated edit, served from a slot (cycles 2–3) | 6 | 0.743–0.997 s, median 0.911 | 31–47 ms | save 0.4–0.6 s, take back 0.1–0.2 s, 1 token |
| Repeated edit, from the checkpoint (cycle 1) | 3 | 1.094–1.140 s | 47 ms | save 0.5 s, checkpoint at 115,103, 13 tokens in 0.5–0.6 s |
| New-text edit, checkpoint present | 4 | 1.128–1.319 s | 31–47 ms | same as above |
| New-text edit after a slot take-back | 2 | 101.96, 102.08 s | 32–62 ms | save 0.5–0.6 s, no checkpoint, 115,116 tokens in 101.2–101.4 s |
| Return to the long conversation | 3 | 0.338–0.386 s | 31–47 ms | save of the 7.7k 0.1 s, take back 0.1 s, 1 token |
| Append, 13–14 new tokens | 3 | 0.661–0.665 s | 31–32 ms | no save, 14 tokens in 0.6 s |

Each slot save of the 115k conversation logged `sync 0 ms, copy 150–191 ms` against a 0.4–0.6 s total. Repeated
edits gave the same answer hash in all three cycles, so taking a conversation back from a slot did not change the
output.

## Reasoning

1. **The save runs inside the next request.** In `generate.cpp` `prep_prompt`, a prompt that does not extend the
   conversation in the model calls `slot_put("")` before anything else. The save is part of every diverging
   request's first-token time, however long the user paused.
2. **Most of the save is outside the GPU copy.** `Glm5Model::slot_save(std::vector<uint8_t>&)` is handed a fresh
   vector each time (`make_shared<vector>`, `reserve(1 MB)`) and `resize()`s it to 1.74 GB, which zero-fills newly
   mapped pages before the four devices copy into it one after another. `slot_put` also frees the replaced slot's
   buffer first. The 0.3–0.4 s gap between the timed copy and the logged total is consistent with that host work;
   it was not timed separately.
3. **Repeated edits save the same state again.** From cycle 2 on, each repeated edit saves a 115,115-token
   conversation that an existing slot already holds token for token. It replaces the equal slot (the count stays
   at 8) after a full save.
4. **The cliff.** After `slot_take` succeeds, `prep_prompt` runs `ckpt_drop_past(0)` ("another conversation's
   state now"), dropping the turn-start checkpoint even though the restored conversation shares its first
   115,103 tokens. A slot can only be resumed whole, because the recurrent layers' state exists only at its
   end. So a new-text edit after a slot take-back matches no slot and no checkpoint, and reads 115k again. Cycle 1's
   new-text edits followed checkpoint-served edits and did not hit it. The re-read made a new checkpoint, so the
   second new-text edit in each later cycle took 1.24–1.32 s.

## Limits

- One run, one synthetic document, short changed final questions. The ranges above are within that run.
- The 2026-11-12 mixed soak that produced the 0.909 s median only repeated identical edits, so it could not show
  the cliff. How often live traffic does a slot return followed by an edit of the last message is unknown.
- The host-side share of the save is inferred from the logged total minus the timed copy.
- Server marks are quantized to 15.6 ms.

## Next action

Two engine candidates, each to be screened against the promoted build with matching answer hashes:

1. **Slot save cost.** Skip the save when a slot already holds exactly these tokens, and reuse buffers instead of
   allocating and zero-filling a new 1.74 GB one. Ceiling about 0.4 s of a 0.91 s repeated edit and of a
   1.1–1.3 s new-text edit.
2. **Checkpoints across a slot take-back.** Keep the checkpoints whose tokens are a prefix of the restored
   conversation, or store them with the slot, instead of dropping all of them. Turns the 102 s re-read into the
   ~1.2 s checkpoint path. Needs a correctness check that the checkpoint's recurrent state at 115,103 combines
   correctly with the slot's KV below it.
