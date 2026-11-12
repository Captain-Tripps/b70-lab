# RAM-backed slots: multi-depth validation — 2026-11-11

**Result: promising, not yet live.** On four separate disk/RAM runs, edited follow-ups were faster with RAM-backed slots from 8k through a 130,400-token prompt. All 31 corresponding visible responses matched exactly: 30 contained 64 generated tokens and one image response contained 55. This is a small deterministic sample, not a perplexity test or proof of broad quality. A 30-minute mixed soak and broader cancellation/retry, tool-use and contention testing remain open.

This follows the [initial 115k screen and slots-disabled driver crash](../2026-11-10-slot-storage-screen/). The live executable, server and configuration were used in isolated processes, with disk slots redirected to a fresh folder on D: and RAM slots enabled using `STRATA_GLM_SLOT_RAM_GB=8`. The two arms at each depth were sequential fresh server starts, disk then RAM; no confidence interval or interleaved start-order control is claimed. Context 131072, chunk 768, default sub-batching, four B70s, resident skip on, CPU lane off, reserve 400 MB, speculation on, temperature 0. The 130k append case reached 130,475 prompt tokens and generated 64 more, below the context limit.

| Prime prompt tokens | Edited follow-up mean: disk | Edited follow-up mean: RAM | Return to long chat: disk / RAM |
|---:|---:|---:|---:|
| 8,111 | 0.772 s | 0.612 s | 0.597 / 0.181 s |
| 32,118 | 1.131 s | 0.731 s | 1.055 / 0.250 s |
| 115,116 | 2.357 s | 1.183 s | 2.734 / 0.486 s |
| 130,400 | 2.542 s | 1.245 s | 2.833 / 0.545 s |

Each mean is three edited-last-turn requests; each switch-back has one observation. The edited means are approximately 21%, 35%, 50%, and 51% lower in these samples. Corresponding [disk and RAM results](115-disk-bench.jsonl) and scripts are retained for each depth (`8`, `32`, `115`, `130` prefixes). These gains apply to this edited/switching workload, not model decode throughput or fresh prefill.

An actual appended turn after returning to the long conversation took 0.999 / 0.997 s at 115k and 1.013 / 1.013 s at 130k (disk / RAM, one each). At 32k, an edit within the large earlier user message forced a full ~32k prompt read: 30.689 / 28.964 s; retrying that same edited request took 0.091 / 0.076 s. At 8k, an image request using llama.cpp's `llama0-logo.png` (SHA-256 `4aa1256ae1b68367e8ad32d4f47d8b69c29be35a4f2c01c7fa3f45f9fdae16f8`) and a subsequent return to text succeeded and matched output in both arms; it does not substitute for a comprehensive vision test. The return-to-text first-token times after the image were 8.135 / 8.179 s, so this particular image transition did not reuse the earlier text state.

Host memory was sampled every two seconds throughout each server run. Lowest available physical memory in disk / RAM runs was 85.16 / 84.28 GiB at 8k, 84.66 / 83.46 GiB at 32k, 83.57 / 78.97 GiB at 115k, and 84.03 / 79.18 GiB at 130k. These are system-wide, non-interleaved snapshots, not isolated allocation deltas, and do not bound concurrent-workload memory pressure. Logs recorded 0.7 GB free VRAM on the tightest card after long prompts. RAM slots are ephemeral, subject to the four-slot count and 8 GiB cap, and can evict old conversations.

Raw request results, memory samples, scripts and engine slot/checkpoint extracts are in this directory. `<work>` is a placeholder for the lab-host directory. The inference runtime and live configuration were unchanged. The independent slots-disabled run's Intel driver access violation remains unexplained and was not retested.
