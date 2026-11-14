# A RAM slot save reuses a dropped slot's buffer: screen and promotion — 2026-11-13

## Decision

Promoted 2026-11-13 at Jon's request, without a soak; see [Promotion](#promotion). A 30-minute [soak](#soak) on the
live build afterwards was clean. A 115k RAM slot save spent
about 300 ms allocating and zero-filling a fresh 1.74 GB host buffer and about 100 ms freeing a dropped one, around
a 180 ms copy from the cards. Reusing up to three dropped buffers (`STRATA_GLM_SLOT_REUSE=3`) cut the median 115k
save from 569 ms to 199 ms. Over cycles 2–4 of the screen, total first-token time fell from 18.4 s to 13.5 s, and
all 29 answer hashes match the reuse-off arm.

## Candidate

[`patch_slot_reuse.py`](patch_slot_reuse.py), on top of the live [checkpoint resume](../2026-11-13-slot-ckpt-resume/)
build, `generate.cpp` only, RAM slots only. `STRATA_GLM_SLOT_REUSE=N` (0–8, unset: off):

- `slot_drop()` keeps a dropped RAM slot's buffer as a spare, up to N, the smallest beyond that freed. Buffers not
  kept are freed on a side thread.
- `slot_put()` hands `slot_save()` the tightest spare from a conversation 1–1.25× as long as this one. A smaller one
  would grow by reallocating and copying; a much larger one would hold RAM. Otherwise it allocates as before.
- A reused slot counts its buffer's capacity toward the 12 GB slot cap. The spares themselves sit outside the cap:
  up to N × ~1.9 GB at 115k.
- With `STRATA_GLM_SLOT_TIMING=1`, each save also logs `put <ms> - drops, save (new|reused buffer), after`.

Built from the live tree (`16ad8a26...`) by recompiling `generate.cpp` only ([`build_reuse.py`](build_reuse.py)):
sha256 `de2540a6bb3e5fc0a9b1ba63ae2979b9d927d88e97f3e37c6f2961e2ec3b603b`, 0 compile errors, 0 unresolved.

## Setup

The live config (slot carry and resume on) with this candidate and `STRATA_GLM_SLOT_TIMING=1`, the
[turn trace](../2026-11-13-turn-trace/) server copy, port 9079 ([`run_screen.py`](run_screen.py),
[`both.py`](both.py)). One 115k prime, then four cycles of three repeated edits, a 7.7k switch, a new-text edit
straight after it, a return and an append. Arms: reuse off, 1 spare, 3 spares, one executable. GLM was unloaded
from llama-swap for it with Jon's OK and reloaded afterwards. Run 2026-11-13 16:36–16:54 CST.

The 1-spare arm's first attempt crashed 16 s into the 115k prime with the known `ze_intel_gpu64.dll` access
violation at `0x4d2d87`, before any slot code ran; it was rerun. The same fault ended an earlier attempt at 15:02,
in a reuse-off arm. Across today's experiments that is two of about 17 cold 115k reads, plus one during a 32k
read in the first carry soak.

## Results

[`off-requests.jsonl`](off-requests.jsonl), [`r1-requests.jsonl`](r1-requests.jsonl),
[`r3-requests.jsonl`](r3-requests.jsonl). Medians over cycles 2–4, 3 per cell.

| 115k first token | Reuse off | 1 spare | 3 spares |
|---|---:|---:|---:|
| Repeated edit 2 / 3 | 0.926 / 0.965 s | 0.612 / 0.553 s | 0.556 / 0.566 s |
| Repeated edit 1 | 0.901 s | 0.913 s | 0.822 s |
| 7.7k switch | 0.722 s | 0.326 s | 0.327 s |
| New-text edit straight after the switch | 1.008 s | 0.951 s | 0.930 s |
| Return to 115k | 0.945 s | 0.882 s | 0.558 s |
| Append (no save) | 0.663 s | 0.665 s | 0.662 s |
| **Sum of first-token time, 21 requests** | **18.40 s** | **15.00 s** | **13.53 s** |

- **Answers:** all 29 hashes identical across the three arms.
- **Saves:** the median 115k put was 569 ms off, 469 ms with 1 spare, 199 ms with 3. A reused save is about
  190 ms, almost all of it the 160–200 ms copy from the cards. With 3 spares, 15 of 24 saves reused a buffer; most
  of the other nine came before anything had been dropped.
- **Slots and RAM:** every arm ended with 7 slots at 11.64 GB. Minimum free physical memory was 78.5 GiB off,
  78.3 with 1 spare and 77.5 with 3.

A first version with one spare and no size rule ([`first-try-off-requests.jsonl`](first-try-off-requests.jsonl),
[`first-try-on-requests.jsonl`](first-try-on-requests.jsonl)) showed the same saving but two faults: a buffer from
a 115,115-token conversation handed to a 115,128-token save reallocated and copied (928 ms), and a 7.7k conversation
took a 1.74 GB buffer. The 1–1.25× rule fixes both.

## Promotion

At 16:56 CST, the live config was pointed at a copy of the screened executable with `STRATA_GLM_SLOT_REUSE=3`
added; nothing else changed and the llama-swap config was not touched.

- Active config: `D:\maya-sycl\configs\glm-maya-sycl-128k.json`; SHA-256
  `d17bc8e56a02ddeda4be547ee4cf14ae09017eaea73c194da03508f3ff291064`. Copy:
  `glm-maya-sycl-128k.slotreuse-promotion-20261113.json`.
- Active executable: `D:\maya-sycl\rt-glm-slotreuse-20261113\generate.exe`; SHA-256 `de2540a6...` as above.
- Previous config, exact backup: `glm-maya-sycl-128k.before-slotreuse-promotion-20261113.json`; SHA-256
  `357fc3eb07f155543eca5d92ae6921514cb87f8f327e878d9f9fea36c4a2e6fe`.
- Previous executable, untouched: `D:\maya-sycl\rt-glm-ckptresume-20261113\generate.exe` (`16ad8a26...`).

Live smoke test through llama-swap ([`smoke_reuse.py`](smoke_reuse.py), [`smoke-live.jsonl`](smoke-live.jsonl)): GLM
started on the new executable (50.1 s to `READY`), read the 115k conversation in 102.3 s, and answered alternating
edits of its last message in 1.18 s on the first round, then 0.54–0.86 s. A return after a 7.7k switch took 0.43 s.
The engine logged 115k saves at 0.2 s, against 0.5–0.6 s before. Each repeated edit gave the same answer every time,
and the first read's answer matches the screen's.

**Rollback:** check `/running` and avoid interrupting requests; after a quiet interval, unload only GLM via
`POST /api/models/unload/glm-5.3-flash-maya-sycl` and confirm no `generate.exe` remains. Verify the active config
still has the promotion hash and the backup its hash, copy the backup over the active config, start GLM through the
proxy and confirm it runs `rt-glm-ckptresume-20261113\generate.exe`.

## Soak

The live build, live config and live server tree unchanged, port 9080, 30 minutes, 20:10-20:40 CST
([`soak_reuse.py`](soak_reuse.py), [`soak-requests.jsonl`](soak-requests.jsonl)): the
[checkpoint resume soak](../2026-11-13-slot-ckpt-resume/#soak)'s mix, with a check that the live config has
`STRATA_GLM_SLOT_REUSE=3`. Set `MAYA_WORK` to the engine checkout and `PROXY_URL` to the proxy. GLM was unloaded for
it with Jon's OK. Driver 32.0.101.8976.

| Request, median first token | Resume soak (49 cycles) | Live reuse build (52 cycles) |
|---|---:|---:|
| Repeated edit 1 / 2 / 3 | - / 0.957 / 0.941 s | 0.557 / 0.558 / 0.555 s |
| Straight edit after a switch | 1.026 s | 0.973 s |
| Return to 115k | 0.960 s | 0.562 s |
| 7.7k switch | - | 0.333 s |
| Append | 0.860 s | 0.863 s |
| 32k switch | 28.78 s | 28.32 s |
| Extra conversations 0 / 1 | 7.40 / 6.53 s | 7.00 / 6.48 s |
| Cancel / retry | 1.082 / 0.053 s | 1.081 / 0.053 s |

- 428 requests. Every request type gave one answer throughout, and all 11 types shared with the resume soak gave the
  same answer as there.
- No engine error or crash, minimum free RAM 78.1 GiB. 64 `for its checkpoint` take-backs: every straight edit used
  the resume path.
- The 32k switch and the extra conversations still read again every time: each cycle parks another distinct
  conversation against `STRATA_GLM_SLOTS=8`, as in the resume soak. That is the slot count, not this change.

## Limits

- Three samples per cell in the screen, one 115k and one 7.7k conversation.
- Up to ~5.7 GB of spare buffers can sit outside the 12 GB slot cap.
- The 160–200 ms copy from the cards is untouched: it runs card after card, into pageable memory.

## Next action

The soak was clean. The remaining save cost is the copy: overlapping the four cards' copies, or pinned host buffers,
could take part of the ~180 ms. Workloads with more distinct long conversations than `STRATA_GLM_SLOTS` hit the slot
count first; RAM has room for more (78 GiB free at the soak's low point).
