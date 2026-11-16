# IQ2_S expert gate/up kernel: instruction-issue bound, no in-place variant beats it - 2026-11-15

## Decision

Rejected at the kernel bench; nothing changed live. Lead L7, expert half, gate/up product
(`glmf::moe_gate_up`, ~117 us a call in the engine, 10-11 calls a token on each card). Twenty in-place variants, all
bit-exact or within float rounding of the live kernel, land between 0.77x and 1.03x of it on card 2. The kernel is limited by
the number of instructions it issues, not by memory and not by the codebook. The ~45 us gap to the read floor is
only reachable with a different work split; a first row-per-lane attempt was 2.4-6x slower.

Also measured: in isolation all four cards run this kernel in the same 126-127 us, including card 3, which takes
147 us inside the engine. Card 3's in-engine slowdown is not the card or its power limit.

## Run conditions

Four Arc Pro B70s, Windows 11, driver 32.0.101.9175, oneAPI 2026.0 (JIT build, default fp model). The GLM server was
unloaded for the 4-card run (cards idle, nothing else on them); the later single-card runs (row-per-lane, IMM) ran
on card 2 beside the idle, reloaded server. Bench: [`gu2.cpp`](gu2.cpp), the model's shapes (k = 8 experts, n_embd
4096, n_ff 2048, IQ2_S rows of 1312 bytes, 43 MB of weights a call), experts rotated through a 48-expert pool
(258 MB, far over L2) so weights come from DRAM. 400 timed launches an arm, median, each arm timed twice (forward,
then reverse order). Per-launch time between in-order barriers from profiling events. [Raw output](bench-results.txt).

The two passes of an arm agree within 1% on cards 0, 2 and 3; card 1's pass 1 and pass 2 differ by up to 9% on
some arms (slower second pass), so read its row with that drift in mind.

## Results (card 2; cards 0 and 3 within 1.5%)

| Arm | us a call | vs live | Output vs live |
|---|---:|---:|---|
| Live replica (16 sub-groups, 2 gate + 2 up rows each, 8 KB grid in SLM) | 126.7 | 1.00x | - |
| 2 chunks a work-group (grid load amortized) | 125.9 | 1.01x | bit-exact |
| 4 gate + 4 up rows a sub-group | 126.3 | 1.00x | bit-exact |
| Grid split into lo / hi u32 planes in SLM | 130.3 | 0.97x | bit-exact |
| 2 KB grid as 16-bit codes in SLM (bytes are only 8, 25, 43) | 150.0 | 0.85x | bit-exact |
| 16-bit codes from global memory | 160.1 | 0.79x | bit-exact |
| Aligned u32 loads + funnel shift (AL), 2+2 rows | 134.3 | 0.94x | bit-exact |
| AL without 32x32 multiplies, 4+4 rows | 129.5 | 0.98x | bit-exact |
| Per-lane bases, constant offsets (IMM), 4+4 rows | 123.6 | 1.03x | float rounding only (fp contraction) |
| One row a lane (RPL), sub-group 16 / 32, K split 1-4 | 303-849 | 0.15-0.42x | max diff 1.9e-7 of max value |
| Diagnostic: grid lookup removed (wrong results) | 119.3 | 1.06x | - |
| Diagnostic: read the same bytes with 16-byte loads, nothing else | 81.7 | 1.55x | - |

Per card, live replica / read floor: card 0 127.0 / 81.8, card 1 132.0 / 81.9, card 2 126.7 / 81.7, card 3 128.3 /
81.5 us (bus 3 / 131 / 135 / 195; `level_zero:N` follows bus order). The power limits read back as 275 W (bus 3,
capped 2026-10-25), 230 W (bus 131, Intel reference) and 275 W (bus 135).

## Why the kernel is slow

The B70 ISA (offline: `icpx -fsycl-device-only -fsycl-device-obj=spirv`, then `ocloc compile -device bmg-g31` and
`ocloc disasm`, no GPU needed) shows ~1,105 instructions in the loop body for one step of 4 rows x 32 weights, of
which 32 are `dp4a`. 320 are `mov`, mostly packing 64-bit per-lane addresses; ~200 are `mul` / `macl` / `mach`
(Xe2 emulates 32x32 and 64-bit multiplies). Each row-step does 7 small gathers (`qs` and the signs as two u16 halves
each, `qh`, `scales`, `d`), each behind its own 64-bit add. Removing the codebook lookup altogether saves only 6%.

At ~1,105 SIMD32 instructions x 32,768 sub-group steps a call on 256 vector engines at ~2.8 GHz, the issue time is
~127 us, which matches the measurement. Every variant that cut loads added shift or unpack work and landed at the
same total. IGC does not fold constant offsets into these a64 loads: the IMM variant still emits one 64-bit add per
load.

`dpct::dp4a` was checked first: SYCLomatic's generic fallback (four byte extracts and multiplies) compiles to the
native `dp4a` instruction, identical to `__builtin_IB_dp4a_ss` ([probe](dp4a_isa.cpp)). No gain available there.

## Row per lane

All lanes of a sub-group on the same block, so the activation is uniform and each lane reads its own row's block
pair with wide loads. Numerically fine, but the first version spills (138 scratch loads) and the compiler splits
the 41-word block read into 107 scalar loads; it also issues ~235 instructions per row and sub-block, not far below
the live kernel's ~275. It would need a spill-free rewrite before its speed says anything about the idea.

## Next

- Card 3's in-engine 147 us (vs 117 elsewhere, same shapes) is an engine effect, likely work overlapping on that
  card (the MTP draft and output head live there). Worth a look under L8 before more kernel work.
- The down product (`moe_down`, IQ3_S) has the same lane-strided structure and likely the same limit; not benched
  here.
- A spill-free row-per-lane gate/up kernel is the remaining structural idea for L7's expert half. Expected value is
  modest: even reaching the read floor saves ~45 us a call, ~0.45 ms a token a card.
