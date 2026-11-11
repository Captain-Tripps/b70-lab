# XMX 64-row tile screen — 2026-11-10

**Decision: reject this prototype at screening.** The larger tile did reduce tile count, but the warmed 8,128-token
prefill took 10.995 s versus 9.329 / 9.391 s for surrounding 32-row controls: about 17.5% more time than their mean.
This is one warmed candidate and two controls, not a broad benchmark. No production change was made.

## Mechanism and checks

The [32-row XMX profile](../2026-11-10-xmx-profile/) recorded roughly 53% row occupancy. This prototype sets the
compile-time tile width to 64 for `TN == 16`, including the selected `f16xf16 8x16x16 sg16` combination; other
combinations keep their original widths. It changes both grouped and non-grouped template uses, so this result is
limited to the measured path. The [one-line patch](bn64.patch) is relative to the diagnostic XMX source in the
preceding profile; use `git apply --unidiff-zero` in its source directory. The known-good executable is the
fallback; the prototype has no runtime switch.

The model-free [fixture](xmx_bn_parity.cpp) exercised IQ2_S, IQ3_XXS and IQ3_S with expert row counts
1, 15, 16, 17, 31, 32, 33, 63, 64 and 65. It checked output guards and finite values. The 32- and 64-row builds
produced bit-identical values across 4,141,056 outputs. This is one synthetic input, not exhaustive operator parity.
The candidate's full-model 64-position teacher-forced logits also matched the saved production baseline byte for
byte (SHA-256 `10ecc6721c715ed452758ebd18c7140bbe11352f17d2f77463b64f98da1f5e92`); broader quality and 128k
validation were not run after the speed screen lost.

The full-model test used the fixed 8,192-token input, 8,128 prompt tokens plus 64 forced positions, context 131072,
chunk 768, default 512 sub-batches, CPU lane off, and speculation off. Candidate executable SHA-256:
`d862d53546409463f266e75db66c6ed2ea017439914307bf303048852fea4d5a`.

| Run | Tile | Profile | Prompt time |
|---|---:|---|---:|
| Earlier control | 32 | off | 9.329 s |
| First candidate | 64 | off | 13.084 s |
| Candidate diagnostic | 64 | on | 11.029 s |
| Candidate repeat | 64 | off | 10.995 s |
| Closing control | 32 | off | 9.391 s |

The first candidate may include additional JIT warm-up and is excluded from the percentage comparison. The
diagnostic adds event barriers and is not an uninstrumented timing. All runs exited 0. Original 32-row logs are
in the linked profile and [closing control](control-off4.log); other path-redacted logs, runner and fixture are here.
`<work>` must be expanded for the host. Large logits and fixture output dumps remain on the lab host.

## Fewer tiles, more padding

On card 1, the candidate profile recorded the same 715,264 routed rows in 34,105 64-row tiles versus 42,179
32-row tiles: approximately 19.1% fewer tiles. But padded capacity increased from 1,349,728 to 2,182,720 rows, and
occupancy fell from about 53% to 33%. The gate/up matrix span increased from 2.491–2.492 s to 3.514 s, and down
from 1.417–1.418 s to 1.692 s. These event spans include submission gaps and marker overhead; they do not isolate
padding, register pressure or other causes. The one profile showed zero grouped-call declines or trace drops.

The 48-row compromise remains a separate experiment; this result does not prove every larger-tile design loses.
