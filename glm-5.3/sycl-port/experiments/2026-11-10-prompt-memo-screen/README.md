# Incremental prompt preparation pilot — 2026-11-10

**Decision: no established end-to-end improvement in this small B70 screen; not live.** An isolated opt-in port of upstream prompt-token memoization and token-ID serialization saved CPU time in microbenchmarks, but three 115k-token cached follow-ups per arm showed highly variable first-token times. Mean TTFT was 2.518 s off versus 2.499 s on; ranges overlapped widely (2.279–2.752 s off, 2.245–2.989 s on). This is not evidence of a 0.75% gain. Do not generalize this small sample to every agent workload.

## Pilot scope and correctness

The [handoff's L3](../../LEADS-2026-11-09.md#l3--incremental-server-prompt-preparation) proposes Project Maya's prompt memo. This pilot extracts `common_prefix`, `PromptMemo`, and `join_ids_memo` from upstream `00655481ce2b0689ab1c2e8d67034dc5701d6511` and integrates them into a **separate server copy** based on the machine's v1.1.44 server, preserving its local media-as-text patch. It does not port the upstream `LiteralMemo` and other optimizations, so it is not a complete test of the full upstream feature. The pilot defaults off. A diagnostic mode file lets the same served process alternate arms; the file is read in both arms, so these results include its overhead. It is a test control, not a proposed production setting. Images and nonempty suffixes bypass token memoization; serialization memoization checks output in `verify` mode.

Using the actual GLM pack tokenizer and template, [tests](test_memo-result.txt) compared exact token IDs across appended, edited, truncated and alternating histories, changed system/tools, structured tool calls and results, special-token literals, 50 randomized texts, suffix fallback and an image bypass. [Serialization tests](test_join-result.txt) covered empty, appended, edited, truncated and alternating sequences and concurrent calls. These tests do not replace a complete image/vision integration test, full upstream suite, cancellation/retry coverage or a soak. All tests passed. The [patch](memo-pilot.patch), applied with `git apply --unidiff-zero`, applies to the lab machine's locally modified server, whose original SHA-256 is `76185526a58aa06193233b0d9d0f8b7282e6ce888b31004be9cad6dc3140971f`; pilot server SHA-256 `d3749e6b71ebd8abd5bfa0b267063decfa6b6163be3cdef0b72a3ab22a953b22`.

## Measurements

CPU-only `render_ids` measurements include rendering and tokenization, using separate tokenizers warmed on the same input and three sequential follow-ups per arm. Both arms retained their existing tokenizer segment caches. All IDs agreed. Means from [the log](bench-incontext.log):

| Seed prompt tokens | Memo off | Memo on | Earlier edit off / on |
|---:|---:|---:|---:|
| 8,093 | 1.190 ms | 0.959 ms | 7.871 / 8.193 ms |
| 32,100 | 3.332 ms | 2.602 ms | 30.548 / 30.617 ms |
| 115,098 | 13.786 ms | 10.926 ms | 127.839 / 127.455 ms |

These are one synthetic source document with a fixed long user message and short appended turns. An independent [serialization microbenchmark](bench_join-result.txt) on repeated token IDs averaged 22.329 ms off versus 2.653 ms on at 115,100 IDs; byte strings matched. This is serialization alone, not server TTFT, and does not include pipe transfer or the GPU.

The [served benchmark](http-bench.log) used the live executable/configuration through the isolated server at context 131072, temperature 0 and four generated tokens. After a 102.64 s fresh prime and one memo warm-up, mode order was off/on/on/off/on/off; the six measured requests each had 115,116 prompt tokens, with short differing final user questions. [Engine evidence](checkpoint-evidence.txt) records 115,103 tokens restored for every measured follow-up. TTFT includes HTTP parsing, preparation, engine transfer, checkpoint restore and GPU work. Answers are not directly comparable because final user questions differ. No claim is made about fresh-prompt throughput or about model quality from these timings.

Scripts and logs are provided with `<work>` placeholders. The original runtime, server and configuration were not changed; the isolated server and engine were stopped after the test. No 8k/32k served A/B, image request, 30-minute mixed soak, or thorough production-quality validation was run after the small 115k screen. A full upstream memo backport or a different conversation shape remains unmeasured.
