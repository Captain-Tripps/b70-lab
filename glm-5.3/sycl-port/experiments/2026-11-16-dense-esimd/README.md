# Dense prompt projections on the ESIMD grouped GEMM (L13) - 2026-11-16

## Decision

Rejected. Routing the dense prompt projections through the ESIMD grouped kernel from L12 makes each 1,408-token
chunk 27% slower on card 0 (651-666 -> 822-836 ms steady state), and the whole 8k read 7.00 -> 9.27 s. Nothing
changed live.

The [prompt-read profile](../2026-11-16-prefill-profile/) put the dense projections at 8-12% of the busiest cards'
time: each weight slab is dequantized to f16 for every chunk (`dequant_f16`), then a oneMKL f16 GEMM runs. The idea
was to drop the dequant pass by letting the ESIMD kernel, which already has a Q6_K loader, read the quantized weight
directly.

Why it loses: the grouped kernel dequantizes the weight again for every tile of at most 64 tokens. In the MoE products
each expert gets about one tile per chunk, so that costs nothing extra; a dense product over a 1,408-token chunk is
22 tiles, so every dense weight is dequantized 22 times instead of once. The fork's own comment on its plain fused
GEMM says the same: "every BN columns dequantize A again, so wide N is left to the library GEMM". Its shape gates
(at most 64 rows an active expert on average) are there for that reason.

What is left of the dense cost is the per-chunk dequant itself (about 5% of card 0 on a 115k read). Keeping f16 copies
of the dense weights would remove it, but they would take several GB a card and the cards have 1.2-2.6 GB free during
a read. Not pursued.

## What was tried

[`patch_dense.py`](patch_dense.py) adds an opt-in path to the prompt path's `hgemm_q`: with
`STRATA_GLM_DENSE_ESIMD=1`, a quantized dense weight (not BF16 or EXL3, `beta = 0`, `ldy == N`, which covers every
call) goes to the fork's grouped entry as one product whose "experts" are 64-token pieces of the chunk, all reading
the same weight (expert stride 0). The f16 activations are widened to f32 first (the fork packs f32 itself). A
declined call falls back to the old path. Unset, the binary runs the old path. [`build_l13.py`](build_l13.py) builds
it on the live tree: 0 compile errors, 0 unresolved symbols.

[`ab_dense.ps1`](ab_dense.ps1): one CLI read of the 8k input, live environment and prompt arguments, speculation off,
the same binary with the switch off and on. No grouped call declined.

| Arm | 8k read | Card 0 chunk 1 | Card 0 chunks 2-5 | Card 0 / 1 / 2 / 3 busy |
|---|---:|---:|---:|---:|
| Switch off (old path) | 7.00 s | 1,248 ms | 651-666 ms | 4.49 / 4.33 / 4.03 / 3.41 s |
| Switch on (dense on ESIMD) | 9.27 s | 1,804 ms | 822-836 ms | 5.81 / 5.44 / 5.15 / 3.84 s |

The slowdown holds on every chunk, not just the first (where the new kernel shapes compile), so it is the kernel, not
JIT. With a clear loss on speed, the logit check was not run.

## Setup

4x Arc Pro B70, Windows 11, driver 32.0.101.9175, oneAPI 2026.0 JIT. Candidate `a8cc2484...` (the live
`1a628932...` tree plus the patch). GLM unloaded from the proxy after an idle check and reloaded afterwards (it
answered). Expand `<work>` to the engine checkout and `<proxy>` to the proxy.
