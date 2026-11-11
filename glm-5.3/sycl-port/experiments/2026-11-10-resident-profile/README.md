# Resident-expert prefill profile — 2026-11-10

**Result:** on this 8,128-token screen, the grouped expert matrix products dominate the previously broad
`moe_resident` interval. This is a profiling lead, not a speedup or a validated optimization. No live change.

An isolated copy of the translated source added gated event markers around the existing MMQ path. The earlier
projection markers are also present. Both sets are no-ops unless `STRATA_GLM_PREFILL_PROF` is set. The
[patch](profiling-markers.patch), [runner](run.ps1), build output and path-redacted [off](off.log), [on](on.log)
and [repeat](on2.log) logs are here. `<work>` replaces the local path. Raw logits and the fixed token input remain
on the lab host; the logits hash below allows comparison.

The isolated binary SHA-256 was `1fb0de80b3622f1880971f2892c43d279c895ad67280f958f7b3262415d09be4`.
Its profiler-off logits, both profiler-on logits and the earlier live-runtime baseline logits were byte-identical
for 64 teacher-forced positions (SHA-256
`10ecc6721c715ed452758ebd18c7140bbe11352f17d2f77463b64f98da1f5e92`). This is a narrow check, not full-model parity.
All three processes exited 0. All-expert pools were complete; logs show no staged, CPU, or disk expert work.

The fixed 8,192-token input was prefetched as 8,128 prompt tokens, followed by 64 teacher-forced decode positions;
context 131072, chunk 768, default 512 mixer sub-batches, CPU lane off, normal live runtime settings except
speculation disabled for the teacher-forced test. Device event spans include command-submission gaps and marker
overhead; they are not pure device kernel time. Values below are per card and cannot be added across the pipeline.

| Card | Gate/up + SwiGLU, ms (two runs) | Down product, ms | Input + hidden row gathers, ms |
|---|---:|---:|---:|
| 0 | 2182.5 / 2177.2 | 1269.6 / 1269.7 | 52.6 / 52.7 |
| 1 | 2619.5 / 2621.7 | 1449.7 / 1452.5 | 59.5 / 59.4 |
| 2 | 2460.6 / 2463.9 | 1395.4 / 1399.7 | 58.0 / 57.7 |
| 3 | 2249.0 / 2243.7 | 1308.9 / 1311.0 | 52.1 / 51.8 |

The port's `mmq::quantize` name is misleading here: this SYCL implementation gathers F32 rows; its grouped XMX
path handles its own packing. The gate/up marker includes SwiGLU, not just the product. The grouped implementation
can also fall back to smaller expert pieces when a grouped call declines; these data do not show how often that
happened. Nor do they distinguish packing, matrix computation and host dispatch inside the grouped calls.

The measured prompt wall times were 9.542 s profiler off and 9.297 / 9.510 s profiler on. With only one off run,
this does **not** establish an overhead bound; the on/off spread is within the observed run-to-run noise. The
previous projection-only profile also included barriers and a wait at collection. Next, inspect and instrument
the grouped XMX shim and separate the gate/up product from SwiGLU, with enough off/on repeats to measure overhead.
Do not repeat the already rejected broad int8-expert campaign without a new measured mechanism.
