# Q6_K dense mat-vec with aligned loads: +3.5% decode, bit-exact - 2026-11-14

## Decision

Live since 2026-11-14. Lead L7 from the [decode profile](../2026-11-14-decode-profile/), dense half. The one-column
Q6_K mat-vec (`glmf::mv_kernel_t<14>`, ~55% of decode kernel time) now reads each lane's weights as aligned 32-bit
words and takes two rows a warp (four for the output head). The weight layout is unchanged and every output is the
old kernel's bit for bit: 1500 greedy decode tokens identical to live, draft acceptance unchanged. Decode on code
goes from 52.2-52.9 to 54.5-54.6 tok/s (+3.5%). `STRATA_GLM_MV_AL=0` turns it off.

## Why the old kernel was slow

A Q6_K block is 210 bytes, so blocks are only 2-aligned and the old kernel reads each lane's `ql` and `qh` ints as
two 16-bit loads (`get_int_b2`). The compiler cannot merge them. A warp takes one block an iteration, so the whole
warp's block is the same 0-3 bytes off a 4-byte boundary. Reading aligned 32-bit words and funnel-shifting by that
offset gives the same ints with half the load instructions.

## Kernel bench

[`q6bench.cpp`](q6bench.cpp): the production kernel and 11 variants on the model's real Q6_K shapes, one B70, cold
weights (copies rotated through at least 512 MB). [Full results](bench-results.txt).

| Shape (rows x cols) | Production | Aligned, 2 rows a warp (taken) | SoA repack, 2 rows a warp |
|---|---:|---:|---:|
| KDA q/k/v 24576 x 4096 | 173 us | 151 us (-13%) | 146 us |
| Dense FFN 12288 x 4096 | 88 us | 78 us (-12%) | 79 us |
| `q_b` 16384 x 1536 | 53 us | 45 us (-14%) | 42 us |
| `attn_output` 4096 x 16384 | 110 us | 100 us (-9%) | 97 us |
| Shared expert gate/up 4096 x 4096 | 31 us | 28 us (-11%) | 27 us |
| Output head 154880 x 4096 | 1033 us | 947 us (-8%, 4 rows a warp) | 873 us |
| `q_a` + `kv_a` 2048 x 4096 | 17.1 us | 17.7 us (+3%) | 15.2 us |

- The engine already has an aligned-word Q6_K kernel for the P100 (`mv_q6_p100_kernel`, shuffles plus the activation
  in shared memory). It is switched off here, and on the B70 it is about 2x slower than production.
- Repacking the weights into separate `ql` / `qh` / scales / `d` arrays is faster again (up to 596 GB/s on the head),
  but every other kernel that reads these tensors (the several-column verify paths, prompt read) would need the new
  layout too. Not taken.
- Below 4096 rows in a launch the new kernel is not faster, so those launches keep the old one.

## End to end

CLI decode on the live settings with the spec-step profiler, the 200-token code input from the decode profile,
1500 new tokens ([decode A/B](decode-ab.txt), [`spec_ab.ps1`](spec_ab.ps1)):

| | Live (4 runs) | New kernel (2 runs) |
|---|---:|---:|
| Decode | 52.2-52.9 tok/s | 54.5-54.6 tok/s |
| CUDA0 device time a token | 9.85-9.96 ms | 9.49 ms |
| Draft acceptance | 96.9% | 96.9% |
| Tokens | - | identical to live |

The gain is smaller than the kernel bench suggests because only part of each card's time is this kernel and the
spec step also waits on the other stage. On prose (~72% acceptance) it is likely smaller; there is no matched
before/after prose run.

## Two traps on the way to bit-exact

The first two engine builds diverged from live at token 52 (acceptance 83.8%), although the bench said bit-exact:

1. Some tensors in the model pack sit at odd byte offsets. The first version assumed a block is 0 or 2 bytes off.
2. The engine compiles with `-fp-model=precise`, which fuses a multiply-add only within one expression.
   `s += d * sumf` written as one expression became an FMA; production adds `dot_q6_K`'s returned product unfused.
   The bench was built with the default (fast) model, which fused both forms alike, so it could not show this.
   The fix computes the product in its own statement.

So a kernel bench has to use the engine's own compile flags to count as a bit-exact check.

## Server soak

30 minutes on a side port with the live config and only the executable changed: the same mixed request set as the
[1536-chunk soak](../2026-11-13-prefill-chunk-1536/) plus a 400-token essay each cycle. 44 cycles, 405 requests,
no errors; every repeated request gave the same answer, cancels cleared in ~1 s, essay decode 42.5-42.8 tok/s
([requests](soak-requests.jsonl)). After promotion, through the proxy: the smoke question answered correctly and
the essay decoded at 42.7 tok/s.

## Setup

4x Arc Pro B70, Windows 11, driver 32.0.101.9175. Source: the live engine tree plus [`patch_q6al.py`](patch_q6al.py),
only `glm_fast.dp.cpp` rebuilt. Executable `2c21539a...` (was `de2540a6...`); split 14,25,36, `--prefill 1536`,
`STRATA_GLM_CKPT_EVERY=65536`. GLM unloaded from the proxy after a quiet check for the bench, CLI and soak runs,
and reloaded afterwards. In the runner, expand `<work>` to the engine checkout and `<proxy>` to the proxy.
