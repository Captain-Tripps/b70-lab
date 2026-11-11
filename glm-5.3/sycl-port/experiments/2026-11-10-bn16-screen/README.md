# XMX 16-row tile screen — 2026-11-10

**Decision: reject this prototype at screening.** A warmed 16-row run took 10.872 s to prefill 8,128 tokens,
versus 9.257 and 9.329 s for the surrounding 32-row controls. The candidate took about 17% more time than the
control mean. This is a small screen, not a broad benchmark; the loss is large enough not to spend further model
or quality testing on this implementation. No production change.

## Mechanism and setup

The preceding [XMX profile](../2026-11-10-xmx-profile/) showed that the selected `f16xf16 8x16x16 sg16`
combination uses 32-row tiles with about 53% row occupancy on the slowest card. The isolated prototype changed
the compile-time tile width to 16 when `TN == 16`; other combinations retain their original widths. This changes
both grouped and non-grouped uses of that template, so the result is limited to the measured path and configuration.
The [one-line patch](bn16.patch) is relative to the instrumented XMX source in the preceding profile. It uses zero
context and can be checked with `git apply --unidiff-zero` in that source directory. The known-good executable is
the fallback; there is no runtime switch in the prototype.

Same fixed 8,192-token input, 8,128-token prompt plus 64 teacher-forced positions, 128k context, chunk 768,
default 512 sub-batches, speculation off. The baseline and candidate builds use the same reconstructed historical
headers and diagnostic code; profiling was disabled for the wall-time comparison. The original production binary
was not overwritten. Candidate executable SHA-256:
`4451ee99200fde27a0f8d681a36d86d584f260678caf36c2b011407c4bb03cf8`.

| Run | Tile | Profile | Prompt time |
|---|---:|---|---:|
| Earlier control | 32 | off | 9.257 s |
| First candidate | 16 | off | 12.889 s |
| Candidate diagnostic | 16 | on | 11.164 s |
| Candidate repeat | 16 | off | 10.872 s |
| Closing control | 32 | off | 9.329 s |

The first candidate may include additional JIT warm-up; it is not used for the 17% comparison. This is one
warmed candidate against two adjacent controls, so it does not establish statistical bounds or performance at
other depths. The diagnostic enables barriers and is not used as an uninstrumented timing. All runs exited 0;
the candidate's 64-row logits matched the saved production baseline byte-for-byte (SHA-256
`10ecc6721c715ed452758ebd18c7140bbe11352f17d2f77463b64f98da1f5e92`). This is a narrow correctness check;
operator parity, broader quality, 128k, image and soak tests were not run.

## Why the screen lost

On card 1, the diagnostic saw 715,264 routed rows in 62,002 16-row tiles, about 72% occupancy. The 32-row
profile had the same rows in 42,179 tiles, about 53% occupancy. Thus this prototype created about 47% more
tiles. Its gate/up matrix span was 3.534 s versus 2.491–2.492 s with 32-row tiles; down was 1.816 s versus
1.417–1.418 s. These event spans include submission gaps and marker overhead, and are not pure kernel times.
The additional tile count is a plausible contributor; the measurements do not isolate repeated dequantization
from dispatch or other costs. Both diagnostic profiles reported zero grouped-call declines and trace drops.

Path-redacted logs and the runner are included; `<work>` must be expanded for the host. Large logits dumps and the
fixed token input remain on the lab host. Raw original-tile controls for the earlier profile are in its linked
folder; [control-off3.log](control-off3.log) is the closing control for this screen.
