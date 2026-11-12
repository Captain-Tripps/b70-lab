# GLM branch-preservation workload validation

This isolated Zeus experiment compared the candidate branch-retention option off and on. It used the same candidate executable, weights, four B70s, layer split, 128k context, deterministic sampling, eight RAM slots, and fresh logs for each arm. The proxy model was unloaded only after the guarded 42-second idle check, and the original proxy model was restored after testing. No live configuration was changed.

The test prompts and order lookup are synthetic. Local paths are redacted in the retained logs. The package omits the machine-specific runtime config and slot payloads.

## Results

All matched output hashes were identical across off/on: **21/21** requests in the 12 GB broad pair, **22/22** in the 1 GiB cap pair, and **21/21** in the focused count-limit fairness pair. This includes the canonical tool name and arguments, tool-response answer, text requests, image answers, and truncated-context answer.

| Workload | Option off | Option on | Finding |
|---|---:|---:|---|
| 12 GB broad B prime TTFT | 11.108 s | 10.568 s | Cold B context, 9,096 prompt tokens |
| 12 GB broad B revisit TTFT | 0.561 s | 0.556 s | Re-primed by the same source in `independent-long`; does not measure B survival |
| 12 GB broad B repeat TTFT | 0.064 s | 0.060 s | Same answer hash |
| Focused B prime TTFT | 10.404 s | 10.433 s | B source is distinct from A and later unrelated context |
| Focused B revisit TTFT | 8.975 s | 8.986 s | After 10 A edits, before any other B-derived request; near-full reread in both arms |
| Focused B repeat TTFT | 0.063 s | 0.061 s | Cached after the reread |
| 1 GiB cap B revisit TTFT | 0.554 s | 0.558 s | Confounded by the same-source `independent-long` request; not a fairness result |

The focused fairness run reached eight retained slots at A-edit-05. Subsequent A saves continued to report eight retained entries. The B revisit then took about 9 seconds and logged another B snapshot, while the immediate repeat took about 0.06 seconds. This supports a count-limit eviction and reread of B in both arms. The on/off revisit difference was 0.011 seconds, with matching hashes; this workload showed no measurable fairness regression from the option.

The 1 GiB cap logs reported **10 LRU drops per arm** to stay under the configured RAM cap. The engine reports byte totals in decimal GB: retained snapshots reached 1.07 GB before subsequent saves dropped older entries and held about 0.88 GB across three entries. These log values are post-save totals; they do not measure a transient peak above the cap. The 1 GiB cap pair had matching output hashes for all 22 calls.

For image identity, the 1 GiB cap pair sent two different images with identical prompt text, then repeated the first image. The image SHA-256 values differ (`llama0-logo.png`: `4aa1256a…16f8`; `llama1-logo.png`: `5556e495…6ac0`). The first-image and repeated-first-image output hashes matched within and across arms; the second image's output hash differed. TTFT was 9.543/9.619 s for the first image, 9.417/9.484 s for the second, and 2.073/2.076 s on the first-image revisit (off/on).

The tool round trip emitted `lookup_order({"order_id":"BB-204"})`, received the synthetic result `{"order_id":"BB-204","status":"packed"}`, and produced identical off/on hashes. Both image requests and truncation completed in all applicable runs.

## Memory and slot pressure

Host available RAM stayed between **83.59 and 85.03 GiB minimum**, depending on arm. The sampled `generate.exe` working set peaked at **5.24–6.45 GiB**. The sampled process private-page counter peaked near 121.85–123.07 GiB; it is a commit/accounting counter, not resident memory. The experiment did not approach the 16 GiB host-free-RAM abort threshold.

In the 12 GB configuration, the log retained at most eight snapshots and about 2.35 decimal GB. In the 1 GiB configuration, the byte cap caused LRU drops as snapshots accumulated. No model crash or watchdog abort occurred.

## Reproduction and artifacts

`broad_ab.py` is the path-redacted runner for the 12 GB workload. Set `GLM_WORK` to the model workspace before running it as `off` or `on`. `cap1gb_ab.py` and `fairness_ab.py` derive controlled variants from the same runner; the fairness variant revisits B before loading the third, unrelated source. The exact executed script hashes were:

- Broad runner: `0cf963376c44a4e769e4b205e26ebd428fc318acca0c96f1cdcb1dcc987b9884`
- 1 GiB wrapper: `70d769b3b4e72557a07e62371eb0c9517c355978bf7f220d1addc9746910542c`
- Focused fairness wrapper: `60ba527ae21f53aaa0cd319ccf79f6735ac79e9df9b4e162cc42afa2b93618b9`

The complete run manifest is in [`manifest.json`](manifest.json). `summarize.py` and `package_results.py` produce the report and sanitized artifact copy.

Sanitized request, memory, slot, server, and engine logs are in [`artifact-package`](artifact-package/). The transferable copy is [`results.tar.gz`](results.tar.gz). The summary includes all request hashes, TTFT values, slot-save counts, memory samples, and image input hashes.

This validates representative workload behavior and two eviction limits. It does not establish broad model quality, long-duration stability, simultaneous multi-user performance, or production readiness.
