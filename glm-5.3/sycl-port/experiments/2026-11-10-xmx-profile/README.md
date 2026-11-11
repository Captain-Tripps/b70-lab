# Grouped XMX prefill profile — 2026-11-10

**Result:** the matrix execution spans dominate this workload; tile-list construction, copies and activation
packing are smaller. This is profiling, not a model speedup. No production change was made.

The [preceding resident profile](../2026-11-10-resident-profile/) identified the grouped expert products as
the large interval. This isolated build adds opt-in `MAYA_XMX_PROFILE` events around tile-list upload, activation
packing and grouped GEMM dispatch. It records host tile-list construction separately and counts declined grouped
calls. Events are read after the queue's existing wait during teardown; no new host wait is added per product.
Barrier spans include submission gaps and marker overhead, and packing spans can include a pool-allocation delay.
They are not pure kernel-only times. Instrumentation patches and path-redacted logs are in this directory. The
patches use zero context; apply each from the corresponding source directory with `git apply --unidiff-zero`.

The deleted temporary fork headers were reconstructed from llama.cpp commit `847f447c3`. Its `fused-gemm.cpp`
matches the original port source after newline normalization. The profiler-off rebuilt executable reproduced
the production baseline's full 64-row teacher-forced logits byte-for-byte. All four runs exited 0 and all their
logit hashes match the saved live baseline:
`10ecc6721c715ed452758ebd18c7140bbe11352f17d2f77463b64f98da1f5e92`. This is a narrow check, not a complete
quality guarantee. The fixed 8,192-token input and logits remain on the lab host.

One profiler-off / two profiler-on / one profiler-off runs used an 8,128-token prompt plus 64 teacher-forced
positions, context 131072, chunk 768, default 512 sub-batches, and the same all-resident configuration as the
earlier profile. Prompt wall times were 9.337 / 9.395 / 9.351 / 9.257 s. The on/off means differ by about 0.8%,
but these few samples do not establish an overhead bound. The profiler-on runs also enabled the existing prefill
markers; this comparison measures their combined effect.

On card 1, the slowest measured pipeline stage, two profiles gave:

| Grouped product | Calls | Tile copy, ms | Activation pack, ms | Matrix span, ms |
|---|---:|---:|---:|---:|
| IQ2_S, M=4096 K=4096 (gate/up) | 121 | 12.21 / 9.62 | 83.20 / 83.34 | 2491.07 / 2492.29 |
| IQ3_XXS, M=4096 K=2048 (down) | 121 | 0.69 / 0.69 | 33.61 / 33.63 | 1416.84 / 1417.58 |

The host tile-list construction totals were under 1.2 ms for these two groups in each run; that host time is not
additive with the GPU spans. There were 242 accepted grouped calls, zero declines and zero dropped trace records on
card 1 in each pass; all four cards likewise reported zero declines and drops. The event profile records no reason
for a decline, and the result applies only to this workload.

For each of those card-1 product groups, 715,264 routed rows occupied 42,179 tiles. The selected XMX combination
uses a 32-row tile, so the aggregate occupancy was approximately 53%. This suggests a narrower-tile experiment,
but it could increase tile count and repeated weight dequantization; occupancy is not itself a speed forecast.
Any such experiment needs operator parity, actual model timings, numerical quality and memory checks. It is a new
tile-width hypothesis, not a rerun of the rejected int8-expert experiment.
