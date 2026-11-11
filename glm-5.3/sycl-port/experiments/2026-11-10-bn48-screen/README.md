# XMX 48-row tile screen — 2026-11-10

**Decision: no demonstrated speedup at screening.** A warmed 8,128-token prefill took 9.317 s versus 9.391 / 9.346 s for surrounding 32-row controls, about 0.55% less time than their mean. One candidate run and two controls cannot establish a gain of this size. No production change was made.

The prototype changes the compile-time width to 48 for `TN == 16`, including the selected `f16xf16 8x16x16 sg16` combination. It affects grouped and non-grouped template uses; only the measured path is characterized. The [one-line patch](bn48.patch) is relative to the [diagnostic XMX source](../2026-11-10-xmx-profile/); apply with `git apply --unidiff-zero` in its source directory. The known-good executable is the fallback; the prototype has no runtime switch.

The [fixture](xmx_bn_parity.cpp) tested IQ2_S, IQ3_XXS and IQ3_S for expert counts 1, 15, 16, 17, 31, 32, 33, 63, 64 and 65. Guards and finite checks passed and all 4,141,056 outputs matched the 32-row build bit-for-bit. This is one synthetic input. All three candidate runs and the closing control also matched the saved 64-position teacher-forced baseline logits, SHA-256 `10ecc6721c715ed452758ebd18c7140bbe11352f17d2f77463b64f98da1f5e92`. Broader quality and 128k validation were not run for this screen.

The fixed 8,192-token input used 8,128 prefill tokens and 64 forced positions, context 131072, chunk 768, default 512 sub-batches, CPU lane and speculation off. Candidate executable SHA-256: `cfb52651e2da8854a53d0ca56c922acd97a77bb484b8c93e9d4766d4fdf7cd82`.

| Run | Tile | Profile | Prompt time |
|---|---:|---|---:|
| Earlier control ([BN64 screen](../2026-11-10-bn64-screen/control-off4.log)) | 32 | off | 9.391 s |
| First candidate | 48 | off | 10.971 s |
| Candidate diagnostic | 48 | on | 9.320 s |
| Candidate repeat | 48 | off | 9.317 s |
| Closing control | 32 | off | 9.346 s |

The first candidate may include JIT warm-up and is excluded from the comparison. The diagnostic adds event barriers and is not an uninstrumented timing. All runs exited 0. Logs, runner and fixture are path-redacted; expand `<work>` for the host. Large logits and fixture output dumps remain on the lab host.

On card 1, 715,264 routed rows occupied 36,525 48-row tiles versus 42,179 32-row tiles, about 13.4% fewer. Padded capacity rose from 1,349,728 to 1,753,200 rows; occupancy fell from 53.0% to 40.8%. The gate/up matrix span was 2.423 s versus about 2.491 s and down was 1.340 s versus 1.417 s. Event spans include submission gaps and marker overhead; they do not establish model-wall savings or a cause. The candidate profile reported zero grouped-call declines or trace drops.
