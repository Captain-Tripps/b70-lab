# DeepSeek decode lessons on GLM: registers, root sync, 16-lane Q6_K - 2026-11-19

## Decision

Three ideas that helped the DeepSeek `ds4` port ([round 4](../../../../deepseek-v4/maya-ds4-sycl/#decode-round-4-2026-11-19-day))
were tried on GLM decode. Only one gains, and only a little:

| Change | Decode, 768 tokens | Status |
|---|---:|---|
| 256 registers for `glmf::moe_gate_up` (it spills 4.3-5.8 KB a thread) | -3% | rejected |
| `use_root_sync` dropped from every launch (549) | +0.3% (noise) | rejected |
| 16-lane aligned Q6_K mat-vec (`STRATA_GLM_MV_AL16=1`) | **+0.5 / +0.7%** (two rounds) | staged, not live |

Every run of every build produced the same 768 tokens. The 16-lane kernel is exact by construction (see below), so
it can go live without a quality check, but the gain is small. It is built and waiting for the owner's call.

## Run conditions

4x Arc Pro B70, Windows, live engine (`7559cf05...`, the L12 ESIMD + idle-poll build), live config env, layer split
`14,25,36`. CLI decode: the t200 code prompt, `--max-new 768 --greedy`, MTP spec decode on (the served path). Each A/B
is a warm-up of the new build, then live (A) and new (B) in the order A B B A A B; cards idle, no other model loaded.
[`ab_r3.ps1`](ab_r3.ps1) is the r3 harness (r1 and r2 differ only in the exe and the switch). Raw lines:
[`results.txt`](results.txt).

Run-to-run spread of the live build tonight was 49.87-51.00 tok/s, about 2%. A delta under 1% only counts if it
repeats and the two sets do not overlap.

## Where GLM decode time goes

The 2026-11-14 decode capture ([decode profile](../2026-11-14-decode-profile/)), aggregated per kernel with the
spill column:

| Kernel | Share of GPU time | Spill a thread |
|---|---:|---:|
| `glmf::mv` (dense mat-vec) | 35.1% | 0 |
| copies (mostly the model load) | 30.8% | - |
| `glmf::moe_gate_up` | 10.5% | 4,352 / 5,760 B |
| `glmf::moe_down` | 8.4% | 0 |
| `glmf::mla_split_attend` | 4.6% | 0 |
| `glmf::moe_route` | 1.6% | 1,728 B |

## r1: 256 registers for the expert gate/up kernel

[`glm_r1_gugrf.py`](glm_r1_gugrf.py) adds a second `moe_gate_up` launch with
`properties{grf_size<256>}`, behind `STRATA_GLM_GU_GRF=1`. Live 50.66 / 50.66 / 50.77 tok/s, r1 49.29 / 49.01 /
49.21 (-3%). The spill is real, but 256 registers halve the threads a core keeps in flight, and this kernel needs
the latency hiding more than it loses to the spill. On DeepSeek the same property paid off only where the spill sat
in the hot loop of the one-query attention.

## r2: no `use_root_sync`

`dpct` puts `use_root_sync` on every launch. [`glm_r2_noroot.py`](glm_r2_noroot.py) removes all 549 of them in 61
files (DeepSeek gained +1.4% from the same change). Live mean 50.51, r2 50.64 tok/s: +0.3%, inside the noise.

## r3: the aligned Q6_K mat-vec on 16-lane sub-groups

The live one-column Q6_K kernel (`mv_q6_al_kernel<R>`, [L7](../2026-11-14-q6k-aligned-gemv/)) runs a 32-lane warp
per R rows. Lane L sums k = L, L + 32, ... and the warp reduces with an xor butterfly 16, 8, 4, 2, 1.

[`glm_r3_al16.py`](glm_r3_al16.py) adds `mv_q6_al16_kernel<R>` on 16-lane sub-groups, as DeepSeek's fx43 did. Lane
l does the 32-lane kernel's lanes l and l + 16 and keeps their two sums apart, each in its own k order. It then adds
them (`s0 + s1`, which is lane 0's `v + xor16(v)`) and runs the butterfly 8, 4, 2, 1. Every row's sum is the 32-lane
kernel's, bit for bit. A 256-wide block now holds 16 sub-groups, so it covers 2 x 8 x R rows. Off by default;
[`build_r3.py`](build_r3.py) copies the live tree, patches `glm_fast.dp.cpp`, compiles that file only and relinks.

| Round | Live (tok/s) | 16-lane (tok/s) | Delta |
|---|---:|---:|---:|
| 1 | 50.39 / 50.17 / 50.88 | 51.03 / 50.51 / 51.02 | +0.7% |
| 2 | 50.74 / 50.70 / 50.70 | 51.08 / 50.93 / 50.87 | +0.5% |

In round 2 every 16-lane run beat every live run. The gain is about the size of DeepSeek's lean dense addressing
(+0.6-0.8%) and well under fx43's +3.3%. On DeepSeek the dense Q6_K kernel was the plain bottleneck; on GLM the
critical path is the tail stage of the spec pipeline plus the MTP draft, so a faster mat-vec moves the total less.

## Next

- Go live with r3 (exe swap + `STRATA_GLM_MV_AL16=1` in the config) or leave it staged: the owner's call.
- `moe_route` (1.6%, 1.7 KB spill) is not worth a build on these numbers.
