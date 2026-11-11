# Selective prefill sub-batches — 2026-11-10

**Decision: do not promote.** Preserving original recurrent and dense sub-batches while letting the other mixer paths use 768 reduced the 32k top-token disagreement from four positions to one, but did not restore exact logits. Its single prompt-time measurement was 27.959 s versus 28.040 s for the control (0.29% less, within ordinary run variation). This does not establish a useful speedup or quality equivalence.

This tests the idea from the [numerical diagnosis](../2026-11-10-sub768-diagnosis/): keep sensitive operations at the original sub-batch size while allowing larger batches elsewhere. The [isolated patch](selective.patch) computes the original adaptive `mixer_sub` size for recurrent attention when `MAYA_DIAG_KDA_SUB512=1`, and also for dense FFNs when `MAYA_DIAG_DENSE_DEFAULT=1`. This matters for partial chunks, whose original default can be smaller than 512. The overall sub-batch is set to 768 in each candidate. DSA mixer operations remain at 768; shared-expert operations fit into one chunk in both arms. Both switches are experimental and absent from the live runtime. The earlier `MAYA_DIAG_KDA_OUT_512` switch was unset in every run.

| Arm | 32k top-1 vs baseline | Mean KL | 32,704-token prompt time |
|---|---:|---:|---:|
| Diagnostic baseline, default | 64/64, byte-identical | 0 | 28.040 s |
| Original recurrent batches only | 61/64 | 0.01569 | 27.616 s |
| Original recurrent and dense batches | 63/64 | 0.01135 | 27.959 s |

For comparison, the [earlier ordinary 768 screen](../2026-11-10-sub768-validation/) had 60/64 and mean KL 0.01354 on this same input. This is one fixed sequence and one run per candidate, not a quality evaluation; lower top-1 disagreement here does not prove a general improvement. On a separate 8,192-token code input the recurrent-plus-dense arm agreed 64/64 (mean KL 0.00000468) but logits were not bit-identical. Full results and changed row indices: [comparison](comparison.txt). Each log ends in exit code 0.

Baseline and candidate times above are sequential single CLI runs, not interleaved serving benchmarks. The diagnostic baseline logits were byte-identical to the saved production executable baseline on the 32k input. No 100k/128k, image, soak, broad quality, or peak-memory validation was run after this screen.

## Reproduction

Four B70s, 128k configured context, chunk 768, resident skip on, CPU lane off, 400 MB reserve, speculation off; the fixed inputs are the earlier [code and long source token files](../2026-11-10-sub768-validation/). The runtime patch applies after the [diagnosis](../2026-11-10-sub768-diagnosis/)'s `diagnostic.patch` and `split-output.patch`; the latter's switch stays unset. Build SHA-256 `9b27d8f021f521c5756f9e6acfa7bd91ac687bd41e237e91ce66fbbb93f9003b`. [Runner](run.ps1), comparison script, build logs and model logs are included, with `<work>` placeholders. The 38 MB-per-arm logits and token inputs remain on the lab host. The live executable and configuration were not changed; the server remains available to load models on demand.
