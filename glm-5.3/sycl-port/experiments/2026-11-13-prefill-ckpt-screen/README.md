# Prompt read: checkpoint spacing and layer split - 2026-11-13

## Decision

Measured, nothing changed on the live server. The prompt read is already pipelined across the four cards, so the
lead "pipeline the chunks across cards" is closed. What costs time instead is the checkpoint spacing: the engine
reads a long prompt as separate calls cut every `STRATA_GLM_CKPT_EVERY` tokens (16384 by default), and each call
fills and drains the pipeline again. A 64k spacing cuts a cold 42k read from 40.3 to 37.1 s (-8%) and a cold 115k
read from 101.3 to 96.6 s (-5%), with decode unchanged. Turning mid-prompt checkpoints off (`0`) gives 37.0 / 94.9 s.
The layer split is held in place by VRAM: the one move that freed the slowest cards did not establish a gain before
the known driver crash ended it. Promoting `STRATA_GLM_CKPT_EVERY=65536` is Jon's call.

## The prompt read is already a pipeline

`Glm5Model::prefill` cuts a long prompt into equal chunks and the four parts of the layer split work on different
chunks at the same time. The Windows `GPU Engine` counters during a cold 42k read on the live server agreed: all four
compute engines at 67-109% in each 8-second sample, not one card at a time. The engine's own per-call line gives each
card's busy time (`glm prefill: <n> tokens in <ms> ... | CUDA0 <ms>, CUDA1 <ms> ...`). From the 16k control below:

| 42k read, 16k spacing | Wall | Card 0 | Card 1 | Card 2 | Card 3 |
|---|---:|---:|---:|---:|---:|
| Tokens 0-16k | 13.94 s | 12.30 s | 12.22 s | 11.16 s | 8.92 s |
| Tokens 16k-32k | 14.31 s | 12.58 s | 12.63 s | 11.58 s | 9.15 s |
| Last 13k | 11.82 s | 10.05 s | 10.11 s | 9.32 s | 7.31 s |

Cards 0 and 1 set the pace; card 3 does about 25% less work. Wall minus the busiest card is ~1.6-1.7 s per call
here (2.0-2.8 s in an earlier read on the live server): the fill and drain of the pipeline, paid once per call. At
16k spacing the 115k read was five calls (65,536 + 3 x 16,384 + 419 tokens), at 64k two (65,536 + 49,571).

## Setup

The live executable (`de2540a6...`), live config and live server tree, on port 9079, never the live server's port.
Driver 32.0.101.9175 (installed the same evening). Each arm is a fresh process: an 8.9k warm-up read, a cold 45,818-token
read, a cold 115,108-token read (distinct openings, so nothing continues a cached prefix) and two 512-token greedy
decodes. Arms in order: 16k (control), 32k, 64k, 0, then 0 again, layer split 13,24,35, layer split 14,24,35, and a
closing 16k control. GLM was unloaded from llama-swap after a quiet check, with Jon's OK, and reloaded afterwards.
Run 2026-11-13 21:38-22:07 CST. [`screen_pf.py`](screen_pf.py), [`all_pf.py`](all_pf.py), [`all_pf2.py`](all_pf2.py);
set `MAYA_WORK` to the engine checkout and `PROXY_URL` to the proxy.

## Results

Prompt time from the server's `timings`, one sample per arm and request.

| Arm | Cold 45.8k read | Cold 115.1k read | Decode 1 / 2 |
|---|---:|---:|---:|
| `STRATA_GLM_CKPT_EVERY` 16384 (live), opening control | 40.27 s | 101.30 s | 43.7 / 45.1 tok/s |
| 32768 | 38.69 s | 99.65 s | 43.7 / 45.1 |
| **65536** | **37.13 s** | **96.59 s** | 43.6 / 45.1 |
| 0 (only the last turn boundary) | 37.05 s | 94.92 s | 43.7 / 45.1 |
| Layer split 14,24,35 | 40.38 s | 101.01 s | 43.1 / 44.3 |
| Layer split 13,24,35 | crashed at 24.8k | - | - |
| 16384 (live), closing control | 40.45 s | 101.49 s | 43.6 / 45.1 |

- **Repeatability:** the two 16k controls agree within 0.18 s on the 42k read and 0.19 s on the 115k read, so the
  1.6-6.4 s differences are not drift.
- **Why the gain is smaller than the fill/drain sum:** later calls read deeper and run slower per token whatever the
  spacing, so only the per-call fill and drain is recoverable.
- **Answers:** decode outputs are identical in every arm (same hashes). The cold-read answers are all correct
  one-sentence summaries; some differ in wording from the control (42k: 32k arm; 115k: 32k, 64k and 0 arms) because the
  chunk boundaries move with the spacing.
- **Trade-off:** a mid-prompt checkpoint is where an edit inside a long fresh prompt can resume, and the engine checks
  for a cancel between calls. At 64k a 115k read keeps one mid-prompt checkpoint and a cancel point; at 0 it has neither
  for ~95 s.

## Layer split

With GLM loaded the cards have 1.5 / 2.7 / 2.7 / 3.1 GB free and a layer is about 2.6 GB, so most moves do not fit.

- **14,24,35** (one layer from card 1 to card 2): loads, no change (40.38 / 101.01 s); card 0 still sets the pace.
  Decode slightly lower (43.1 / 44.3).
- **13,24,35** (one layer onward from each of cards 0-2): loads with card 3 at 0.5-0.8 GB free. Its first 16k call
  was more even (cards 11.38 / 12.34 / 10.75 / 10.57 s, wall 13.96 s vs ~14.1 in the controls), then the engine died at
  24.8k with the driver fault below. Not established, and too little VRAM on card 3 for image prompts (they reserve 400 MB).

## Driver crash

Two of eight arms ended with the known access violation in the Intel driver, now on driver 32.0.101.9175
(`ze_intel_gpu64.dll` 1.17.39894.6, offset `0x4321b6`; it was `0x4d2d87` on 32.0.101.8976): the first `0` arm at 37.6k
into its 42k read and the 13,24,35 arm at 24.8k. Free RAM stayed above 90 GiB. The `0` arm was rerun cleanly. The
newer driver did not fix it. [`c0-crashed-prefill-lines.txt`](c0-crashed-prefill-lines.txt),
[`s13-24-35-crashed-prefill-lines.txt`](s13-24-35-crashed-prefill-lines.txt).

## Files

Per arm: `<arm>-requests.jsonl` (timings, draft counts, answer hashes) and `<arm>-prefill-lines.txt` (the engine's
per-call lines). The first arm's warm-up took 46.8 s (first prompt after the driver change); every later warm-up 9.7-9.9 s.

## Limits

- One sample per arm and request; the controls bound drift, not per-request variance.
- One 42k and one 115k document; text prompts only.
- Not covered: edits inside a long fresh prompt with a wider spacing, cancel latency, images.

## Next action

Promote `STRATA_GLM_CKPT_EVERY=65536` to the live config if Jon agrees, then a short live smoke. The prompt read's
remaining headroom is inside the kernels: the grouped XMX expert products run at ~53% tile occupancy
([XMX profile](../2026-11-10-xmx-profile/)).
