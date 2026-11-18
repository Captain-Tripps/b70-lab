# DeepSeek V4.1 Flash 1017 on Project Maya's `ds4` engine, ported to SYCL (2026-11-17 / 18)

**Two days into the port: decode 29.3 tok/s (36.8 with the drafter), an 8k prompt reads at about 280 tok/s.** The
llama.cpp fork yardstick on the same cards is 3.92 decode / 0.65 prompt. The targets are 600+ tok/s prompt and ~50
decode, so prompt reads are about halfway there. Not live: there is no llama-swap entry and none will be added without the owner's OK.

Setup: Windows 11, four Arc Pro B70s (32 GB each), EPYC 7402P (Zen 2, AVX2 only), driver 32.0.101.9175, oneAPI DPC++
2026.0, JIT build, persistent kernel cache (`SYCL_CACHE_PERSISTENT=1`). Model: the Maya-XS IQ1_S pack of
DeepSeek-V4.1-Flash-1017 (116.8 GB model + 161.3 GB Q6_K Engram tables read from SSD + 4.25 GB DSpark drafter).
Engine: Project Maya's in-tree `src/ds4/`, run through `dpct` and then fixed by hand, the same route as the
[GLM-5.3 port](../../glm-5.3/sycl-port/). This is option A' of the [engine decision](../engine-decision-2026-11-16/ENGINE-DECISION.md).

Layout: tensor parallel falls back 2 -> 1 (n_ff 2304 does not split into 256-value blocks), so the four cards run a
layer pipeline of 10 layers each. All 15,360 routed experts fit in VRAM with `--reserve-mib 1024`.

## Results

### Decode (2026-11-17)

Long-answer prompt (34 tokens), 128 generated, greedy, two or more warm runs per row:

| Build | Plain decode, tok/s | With DSpark drafter, tok/s | Output |
|---|---:|---:|---|
| llama.cpp fork (yardstick, 2026-11-12) | 3.92 | - | - |
| M1 pass (host-wait hand-offs, below) | 19.9 (64 tokens) | - | coherent |
| + `--reserve-mib 1024` (every expert in VRAM); drafter floors `--dspark-conf 0.15`, `STRATA_DS4_DSPARK_CUM=0.1` | 28.1 | 35.1 (default floors 33.5) | drafter tokens = plain tokens, 127 of 128 |
| + no `use_root_sync` on launches | 28.5 | 35.5-35.9 | identical |
| **+ dense Q6_K in 128-row SoA tiles** | **29.3** (3 ABAB rounds, off 28.4-28.6) | **36.8** (off 36.0) | identical |

### Prompt read (2026-11-18)

8,015-token prompt, `--window 65536` (see the measurement note), output = the 16 greedy tokens after the prompt,
compared by hash, plus a full-vocabulary logit compare against the attention-XMX build:

| Step | 8k read, tok/s | 2k read, tok/s | Output |
|---|---:|---:|---|
| Default chunk 4096 | 39.1 | 40.3-41.0 | `2e96bd4d` |
| Chunk 2048 / 1536 / 1024 / **512** | 84.5 / 94.2 / 105.3 / **112.1** | - | same |
| + XMX sparse attention (fx21) | 211.3 | 145.9 | same |
| + XMX heavy-expert gate/up (fx26c) | 265.8-272.8 | 190.3 | same |
| **+ XMX heavy-expert down (fx26c/27), v1 adapter** | **279.4 / 280.5 / 281.2** | **195.0** | same |

Against the attention-XMX build, the final build's last-position logits have rel L2 0.20-0.26, about the run-to-run noise.
The same top token every run, top-5 overlap 3-5 of 5. Decode after the 8k prompt is 23-24 tok/s on 16 tokens, unchanged.

Per-kernel time on the final build, 8k read, summed over the four cards (`DS4_KT=1`, one run, 276.7 tok/s):

| Kernel | ms | Share | Before this round |
|---|---:|---:|---:|
| heavy experts gate/up (XMX) | 8,457 | 27.9% | 34,800 (F32 tiles) |
| sparse attention (XMX) | 7,119 | 23.5% | |
| heavy experts down (XMX) | 4,041 | 13.3% | 7,900 (F32 tiles) |
| light experts gate/up | 4,003 | 13.2% | |
| light experts down | 3,403 | 11.2% | |
| dense GEMM | 2,918 | 9.6% | |
| light-path Q8 quantize | 383 | 1.3% | |
| **Total** | **30,323** | | |

30.3 s of kernel time over 4 cards is about 7.6 s a card against a 28.7 s wall: **each card is busy about 26% of the read.**
The rest is pipeline bubbles and host time. That is the next lever (see future leads).

## What made the difference

1. **Cross-card flags: wait on the host, then launch (M1, decode 0.03 -> 19.9 tok/s).** Maya hands data between cards
   through flags in host USM that a kernel busy-polls. On this stack a kernel that is *already spinning* on a host-USM
   flag never sees a later write, whether it comes from the host or from another card. Volatile loads are served from its cache. A
   system-scope atomic load is worse: the host then reads the old value, because IGC lowers the load to
   `atomic_or(0)` and the stale value is written back. A kernel *launched after* the write always sees it. The fix is to wait for the flag on the host and then
   launch the consumer. It touches four sites: the layer hand-off, the flag waits, a token's CPU-lane answer, and a window's. The
   fix also makes the Windows put submit at once with `ext_oneapi_prod()`. Before it, every card-to-card hand-off cost about 15 s.
   A 3,000-round ping-pong test of 256 KiB payloads found 0 stale words.
2. **Cross-device event waits fail on Windows Level Zero, even in one shared context.** `ext_oneapi_submit_barrier`
   on another card's event reports `OUT_OF_RESOURCES` / `OUT_OF_DEVICE_MEMORY` with 3 GB free. All 25 such barriers
   are host `wait()`s now, as in the GLM port.
3. **The IQ lookup tables reached every kernel as host addresses.** `dpct` turned `.get_ptr()` into plain arrays, and that was the cause of
   the DEVICE_LOST crashes. Now each device has its own USM copy.
4. **Prompt chunk 512 (39 -> 112 tok/s at 8k).** With a 10-layer-per-card pipeline, one 4096-token chunk keeps one card
   busy at a time. N chunks overlap like a 4-stage pipeline, ideally 4n / (n + 3) of one card.
5. **XMX sparse attention (112 -> 211).** The prompt attention ran on F32 tiles because the `dpct` port of CUDA's 16x16x16 WMMA
   does not JIT on Xe2: A tiles are 8 rows there. The rewrite uses f16 `joint_matrix` 8x16x16 with sub-group 16.
6. **XMX heavy experts (211 -> 280).** Experts with 64 or more rows in a chunk now run a dequant-into-shared-memory
   `joint_matrix` GEMM in place of the F32 tiles. One work-group covers an expert and 128 output rows (8 sub-groups of 16), with B tiles
   packed in SLM, 32 rows a pass. The two IQ1_S sub-block scales are folded into B, which is exact in f16 because code x scale <= 135.
   Switch: `DS4_HEAVY_XMX` (0 off, 1 both halves, 2 gate/up only, 3 down only).

## Bugs found on the way

### JIT drops stores from size-1 `joint_matrix` arrays

The first heavy-down kernel wrote nothing. Its accumulators were `joint_matrix acc[4][1]`, one role, and the
stores from them were silently dropped. The 8k read looked fast at 267 tok/s, but the output was wrong: rel L2 0.79 and top-5
overlap 1 of 5. The same code with two roles (`acc[4][2]`) stores correctly. The down kernel now carries a dummy second
role that is never stored (fx26c). It costs nothing measurable. **Anyone porting a WMMA kernel with a single
accumulator column should check that the output is written at all.**

### Faster kernels expose the Level Zero v2 adapter deadlock

With the heavy-expert kernels on, about half of the 8k reads hung under the default (v2) adapter. That held for both halves and for gate/up only. The bug
is not in the kernel: a check mode that ran the F32 reference on every call (about 400 calls) found every result
correct, up to the hang. A watchdog (`DS4_WATCH=<s>`, below) dumped every thread's stack after 60 s without
progress. Every card's host thread was blocked in `zeCommandListAppendLaunchKernelWithArguments` on SRW locks in
`ze_intel_gpu64.dll`. This is the deadlock in [reproducers/l0-deadlock](../../reproducers/README.md#l0-deadlock-level-zero-hang-with-several-submitting-threads--onemkl),
reported as [intel/llvm#23530](https://github.com/intel/llvm/issues/23530). Here it triggers without oneMKL `gemm`,
from plain SYCL kernels on four submitting threads. The faster kernels make submissions denser, which makes the race
likelier.

**Workaround: the v1 adapter** (`SYCL_UR_USE_LEVEL_ZERO_V2=0`, plus `UR_LOADER_USE_LEVEL_ZERO_V2=0`). It passed 7 of
7 8k reads, against about 50% stalls on v2. The GLM port already runs v1. The engine's speed on v1 against v2 is not
measured, because v2 does not finish reliably. On the llama.cpp fork, v1 was slower
([rejected-ideas](../../rejected-ideas/)). **Open caveat:** on Windows, v1 has been reported to lose the device
on the first job after the GPU has idled ([lc0#2473](https://github.com/LeelaChessZero/lc0/issues/2473)). **Idle test, passed (one run):** in serve mode,
an 8k request, then 2k after 60 s idle, 8k after 300 s, 2k after 600 s. All four answered, none lost the device:
8k 281.3 / 288.1 tok/s, 2k 211.4 / 211.4, 8 generated tokens at 30.6-30.9 tok/s. The watchdog fired once while the
server sat idle (no layers to run, a false alarm in serve mode), and the process threw its known teardown exception at
`QUIT`. Longer idle gaps (hours) are still untested.
If it fails, the fallback is a process-wide lock around kernel submission on v2, the same workaround the llama.cpp
cross-card pipeline uses.

### Smaller ones

- `dpct` mapped every `cudaStreamQuery` to "done" (11 sites, `DPCT_CHECK_ERROR(q->ext_oneapi_empty())` returns the
  error code, not the bool). Real, fixed, but not the cause of the stall it was suspected of.
- `CompBatch` was passed by value at 2,820 bytes, over the 2 KB kernel-argument limit. It is now passed through a USM slot. This was the drafter's JIT crash.
- `DS4_DSPARK_CONF` is declared and never read. The drafter floor is the CLI flag `--dspark-conf`.
- The `ds4` CLI feeds the prompt `--window` tokens a call (default 16). The chunked prompt path needs one feed of at least
  512 tokens, so every CLI prompt number before 2026-11-18 was windows of 16 (about 23 tok/s at 2k and 8k).

## Tried and rejected

| Idea | Result |
|---|---|
| System-scope atomic loads for the cross-card flags (fx13, fx15) | no change / the first hand-off hangs forever (see above) |
| Host-wait spin budget and wait counters (fx18) | 28.1 -> 28.4 tok/s, noise; fewer than 4,096 waits blocked in a whole run, so decode is not waiting on hand-offs. Event hand-offs (32 us vs 213 us in the ping-pong test) would not pay for decode |
| Q6_K GEMV rewrite, 2 rows a sub-group + aligned loads (fx17) | bench -5 to -21%, engine 28.2 -> 25.3-27.1; multi-column path changed tokens. The bench was miscalibrated: a hand-written `dp4a` compiles far worse than the `dpct` form, and the engine launched with `use_root_sync` |
| Q6_K per-row and block-interleaved repacks | slower than the original layout on every shape; 128-row SoA tiles won (kept, above) |
| XMX for the light experts (fewer than 64 rows, fx22, opt-in `DS4_LIGHT_XMX`) | 8k 211 -> 199, 2k 146 -> 125: too few rows to fill the tiles |
| Restructured heavy kernel alone (fx26: scale fold, one accumulator per tile) | did not fix the empty down output; the second role (fx26c) did |
| Host waits around every heavy launch (fx27, `DS4_HX_SYNC`) | did not stop the hang; kept as an option, default on |
| Engram reads as the hang cause | wrong; the stacks put it in the driver |
| Prompt chunk 256 | hangs at 8k; not looked into, likely the same deadlock |

## Measurement notes

- Prompt reads need `--window 65536` (or any window of at least one chunk) on the `ds4` CLI.
- `DS4_KT=1` per-kernel timing costs about 1% at 8k (276.7 vs ~280 tok/s).
- The check mode for the heavy kernels (`DS4_HX_CHECK=n`) poisons the light rows of its buffer, so an end-to-end result
  in that mode is invalid. It checks kernels only.
- `DS4_WATCH=<s>` starts a thread that suspends every thread and prints its stack (`StackWalk64` + `SymFromAddr`)
  after `s` seconds without a layer starting. Driver and runtime frames resolve; the engine's own did not in this build.
- The two 2k runs of the default build gave different 16-token hashes (`70b6660b` / `6fe86dce`); the 8k hash is stable
  across every build above. Unexplained.

## Future leads

Ranked by expected gain toward 600 tok/s prompt and ~50 decode:

1. **Pipeline bubbles in the prompt read.** Each card is busy about 26% of an 8k read. Ideas: finer hand-offs (per-layer
   rather than per-card stage), overlapping the host waits with the next chunk's launches, and checking whether the
   default 4-stage schedule waits on the slowest card each chunk. With the cards never idle, today's kernels alone would read 8k at about 1,050 tok/s.
2. **Re-sweep the prompt chunk** on the XMX build: 512 was picked when the kernels were 3-4x slower.
3. **Sparse attention (23.5%) and the light experts (24% together).** Light experts need a grouped kernel that batches
   several small experts per work-group rather than per-expert XMX tiles. The ESIMD grouped GEMM that sped up
   [GLM](../../glm-5.3/sycl-port/experiments/2026-11-15-esimd-grouped-gemm/) and
   [Flash-Next](../../strata-windows-port/esimd-prefill/) is the reference.
4. **Decode attention.** About 21 of 34 ms a decode token in an earlier profile; untouched so far.
5. **Whole-tensor Q6_K SoA repack** for the remaining dense shapes (wo_b, k 8192), bench -7%.
6. **Chunk-256 hang, teardown exception** (the process exits 9 after printing results), and the 2k nondeterminism:
   all needed before a llama-swap entry.

Next step: a 30-minute mixed soak on the v1 adapter, then a llama-swap entry proposal to the owner.
