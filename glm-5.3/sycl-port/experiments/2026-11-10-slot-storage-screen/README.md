# Long-follow-up slot storage screen — 2026-11-10

**Finding: RAM-backed conversation slots are a promising candidate.** On one 115k-token workload, three edited follow-ups averaged 1.224 s to first token with RAM slots versus 2.334 s with disk slots, about 47.6% less. Returning to the long chat after an unrelated 7.7k-token chat took 0.519 s versus 2.582 s, one observation per arm. Arms were sequential on separate fresh server starts; this is a screen, not an interleaved or broad validation. No production setting changed.

The earlier [prompt-memo screen](../2026-11-10-prompt-memo-screen/) had already shown 2–3 s follow-up latency while restoring 115,103 tokens. The engine logs explain most of that workload's delay: before restoring an earlier checkpoint, it parked the current 115,115-token conversation, about 1.74 GB. Disk saves reported 1.7 s each; RAM saves reported 0.5–0.6 s each. After checkpoint restore, the engine reported reading the remaining 13 tokens in 0.5–0.6 s. This prompt-read figure includes the engine's prompt path and is not a separate measurement of first-sample overhead. Checkpoint-restore and first-sample time were not independently instrumented. [Disk trace](disk-engine-extract.log) and [RAM trace](ram-engine-extract.log).

## A/B details

Live `generate.exe` and the locally modified live server ran in isolated processes using the same Maya-M pack, context 131072, chunk 768, default 512 mixer sub-batches, speculation on, resident skip on, CPU lane off and 400 MB reserve. The disk control redirected `STRATA_GLM_SLOT_DIR` to a new test folder on the same D: volume as the default pack folder. The candidate additionally set `STRATA_GLM_SLOT_RAM_GB=8`, an 8 GiB slot-storage cap; the default four-slot count was unchanged. RAM slots are ephemeral and do not persist across process restarts. At most four long-conversation slots were retained; their reported total reached 6.98 GB decimal. A host-memory sample before those slots accumulated showed 86.4 GiB free of 111.9 GiB; peak host memory was not sampled. The engine's free-VRAM log showed 0.7 GB on the tightest card after the long prompt in both arms, so long-context memory and concurrent pressure still require validation.

| Request | Disk slots TTFT | RAM slots TTFT |
|---|---:|---:|
| Fresh 115,116-token prime | 107.687 s | 104.871 s |
| Edited follow-up 1 | 2.345 s | 1.234 s |
| Edited follow-up 2 | 2.316 s | 1.253 s |
| Edited follow-up 3 | 2.341 s | 1.185 s |
| Switch to separate 7,673-token chat | 9.403 s | 8.061 s |
| Return to 115,116-token chat | 2.582 s | 0.519 s |

Every edited follow-up restored 115,103 tokens; the return restored a 115,115-token slot. Engine-reported restore for the returned slot was 2.0 s from disk and 0.2 s from RAM, single observations. Requests used temperature 0, identical inputs across arms and four generated tokens; visible responses matched for each corresponding request. Four tokens per case do not establish broad quality or parity. The sample says little about ordinary append-only conversations, 8k/32k edits, cancellation, multimodal input, throughput or other workloads. The prime times were not controlled for filesystem cache and are not used as a fresh-prefill comparison. [Raw disk results](disk-bench.jsonl), [raw RAM results](ram-bench.jsonl), and [runner](slot_run.py).

## Slots-disabled incident

A third arm set `STRATA_GLM_SLOTS=0`. During its initial 115k prompt, before any follow-up, `generate.exe` exited with Windows exception `0xc0000005`; the application event named `ze_intel_gpu64.dll` version `1.15.39183.4`. It happened after approximately 49 of 86 chunks of the first 65,536-token segment. This is one occurrence; the cause and whether the setting contributed are unknown. The [client error](none-bench.jsonl), [engine tail](none-engine-tail.log), and [runner log](remaining.log) are retained. It is not a valid performance or switch-back measurement, and slots-disabled is not recommended from this result. Two complete four-card runs had succeeded before it.

A subsequent 32k disk/RAM attempt did not start: the preflight found a separate Qwen model serving on the machine. It was left undisturbed. Further work should repeat disk/RAM with interleaved starts, sample peak host and GPU memory, verify longer outputs and multi-chat switching, exercise cancellation/retry and image requests, and complete a mixed soak before any live change. Checkpoint-interval sweeps remain unmeasured and are lower priority until slot storage is accounted for.

The runtime SHA-256 is `497f1d4238a724eafbf056af33910e4e0d94e6b7571a33ae61187512b0ca7198`, live configuration SHA-256 `d46603a071083d0ba2d4aeb7e6e60f1758116f153394e2bc2e4ae5709ac2087e`, and server SHA-256 `76185526a58aa06193233b0d9d0f8b7282e6ce888b31004be9cad6dc3140971f`. These were unchanged after the screen. Scripts use `<work>` placeholders. The initial runner's immediate next-arm preflight encountered delayed teardown; `slot_run_remaining.py` waits for the GPUs to clear and ran the remaining arms. The server and GPU processes created for these tests were stopped; Qwen was not stopped or restarted.
