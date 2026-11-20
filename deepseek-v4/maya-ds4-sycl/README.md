# DeepSeek V4.1 Flash 1017 on Project Maya's `ds4` engine, ported to SYCL (2026-11-17 / 19)

**Three days into the port: decode 43.7 tok/s with the drafter (36.2 plain) on the benchmark prompt, prompts read at
812 tok/s at 8k and 867 at 120k.** Served decode depends on how well the drafter guesses the text: 47-50 tok/s on warm
short prose prompts, up to ~70 on code. The llama.cpp fork yardstick on the same cards is 3.92 decode / 0.65 prompt;
the port's first working decode was 0.03 tok/s. The targets are 600+ tok/s prompt and 50+ decode: the prompt target is
met and decode is at 87% on the benchmark prompt ([round 4](#decode-round-4-2026-11-19-day)).
Since 2026-11-18 the engine has a llama-swap entry (owner's OK) that swaps with the GLM entry on demand, behind Maya's
OpenAI-compatible server.

Setup: Windows 11, four Arc Pro B70s (32 GB each), EPYC 7402P (Zen 2, AVX2 only), driver 32.0.101.9175, oneAPI DPC++
2026.0, JIT build, persistent kernel cache (`SYCL_CACHE_PERSISTENT=1`). Model: the Maya-XS IQ1_S pack of
DeepSeek-V4.1-Flash-1017 (116.8 GB model + 161.3 GB Q6_K Engram tables read from SSD + 4.25 GB DSpark drafter).
Engine: Project Maya's in-tree `src/ds4/`, run through `dpct` and then fixed by hand, the same route as the
[GLM-5.3 port](../../glm-5.3/sycl-port/). This is option A' of the [engine decision](../engine-decision-2026-11-16/ENGINE-DECISION.md).

Layout: tensor parallel falls back 2 -> 1 (an expert's n_ff 2304 is 9 blocks of 256 values, which do not split in two;
the uneven split is tested [below](#tensor-parallel-2-with-the-uneven-split-2026-11-19)), so the four cards run a
layer pipeline of about 10 layers each. All 15,360 routed experts fit in VRAM with `--reserve-mib 1024` at 12k context;
the served 128k entry needs `--reserve-mib 768` for the same (2026-11-18, below).

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

### Decode switches (2026-11-18, evening)

Same long-answer prompt, 128 generated (16 after 8k), v1 adapter, fx31 build, one executable, runtime switches only:

| Setting | Plain decode, tok/s | Drafted, tok/s | Decode after 8k, tok/s | 8k read, tok/s |
|---|---:|---:|---:|---:|
| Default | 28.45 / 28.51 | 35.92 / 36.42 | 22.99 / 23.35 | 764.1 / 761.2 |
| `DS4_HC_STREAM=0` | 31.45 / 31.41 | 37.05 | - | - |
| **`DS4_HC_STREAM=0` + `DS4_HC_FUSE=2`** | **32.08** (`=1`: 32.15) | **37.70 / 37.57** | **27.35 / 27.23** | 772.1 / 768.5 |
| + `DS4_DECODE_TRIM=3` | 31.96 | 33.78 (with `--window`, below) | - | - |
| `--threads on` (a worker thread per card) | 25.93 | - | - | - |

- `DS4_HC_STREAM=0` keeps the hyper-connection mix / split on the layer's own queue. The port ran them on a second
  queue, which costs four host event waits a layer (160 a token) on this stack. Maya's HIP build already turns the side
  stream off on Windows for the same reason. Plain tokens are identical with and without it.
- `DS4_HC_FUSE=2` merges split and pre-norm into one launch for 1-row decode and for verify windows. At load the engine checks it
  against the old kernels: bit for bit on all four cards.
- Both are in the served config since 2026-11-18. The 8k prompt read and its output are unchanged.
- Measurement trap: the CLI's `--window 65536`, needed for prompt reads, also makes drafted decode slower (32.3 vs 36.4
  tok/s, same build). Drafted decode numbers are taken without it. The server does not use the flag.
- v1 vs v2 adapter, plain decode: 28.4 vs 29.8 tok/s (+4.6% on v2); drafted equal. v2 stays off because of the deadlock.

### Prompt read (2026-11-18)

8,015-token prompt, `--window 65536` (see the measurement note), output = the 16 greedy tokens after the prompt,
compared by hash, plus a full-vocabulary logit compare against the attention-XMX build:

| Step | 8k read, tok/s | 2k read, tok/s | Output |
|---|---:|---:|---|
| Default chunk 4096 | 39.1 | 40.3-41.0 | `2e96bd4d` |
| Chunk 2048 / 1536 / 1024 / **512** | 84.5 / 94.2 / 105.3 / **112.1** | - | same |
| + XMX sparse attention (fx21) | 211.3 | 145.9 | same |
| + XMX heavy-expert gate/up (fx26c) | 265.8-272.8 | 190.3 | same |
| + XMX heavy-expert down (fx26c/27), v1 adapter | 279.4 / 280.5 / 281.2 | 195.0 | same |
| + no host wait around heavy launches (`DS4_HX_SYNC=0`) | 286 / 283 (on: 281 / 281) | 195 (on: 190) | same |
| **+ hand-off copies on the copy engine (fx31)** | **762.2 / 763.8 / 776.0** | **469.9** | same |

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
The rest looked like pipeline bubbles and host time. The timeline below shows most of it was one kernel `DS4_KT` does not time.

### Where the time went: a classified timeline (fx30)

`DS4_TL=<csv>` records every launch and host wait per card with host timestamps, and a report script sorts each gap
on a card into one of four kinds: no input yet (the previous stage has not handed over), ready but not submitted,
submitted but not running, and unclassified. Tracing costs about 3-8% (705 vs ~765 tok/s at 8k). `DS4_KT` has to stay off while tracing.

On the build above (8k read, ~280 tok/s):

| Card | Busy | Of it, the hand-off copy kernel | Largest gap |
|---|---:|---:|---|
| 0-2 | ~78% | ~16 s of a 28 s read, ~1.0 s a chunk | - |
| 3 (last stage, no outgoing hand-off) | 21% | - | 20 s waiting for input |

The cards were not idle. Cards 0-2 spent most of the read in `xfer_put_kernel`, which copies each chunk's ~33 MB
hand-off into host USM with plain kernel stores from at most 64 work-groups. Card 3 then waited for it.

### Hand-off copies on the copy engine (fx31)

fx31 replaces the kernel copy with one `queue.memcpy` per segment, then launches the same kernel with no segments so
that it only raises the flag. The queue is in order, so the flag goes up after the copies finish. `DS4_XFER_MEMCPY=0` restores the old copy.

8k read, alternating runs of one executable, 16 greedy tokens after the prompt:

| Run | Copy | 8k read, tok/s | Output |
|---|---|---:|---|
| A1 | kernel stores | 282.5 | `e80ae869` (first run of the build) |
| B1 | copy engine | 766.5 | `2e96bd4d` |
| A2 | kernel stores | 281.6 | `2e96bd4d` |
| B2 | copy engine | 763.6 | `2e96bd4d` |
| B, traced | copy engine | 705.0 | `2e96bd4d` |

Promoted to the served build the same day: 776.0 (first run), 763.8, 762.2 with the copy engine, 284.7 with
`DS4_XFER_MEMCPY=0`, all four `2e96bd4d`. Last-position logits against the old copy: rel L2 0.19-0.26, the same top
token, top-5 overlap 4-5 of 5. Two copy-engine runs differ from each other by 0.18-0.20, so this is run-to-run noise.

Each hand-off copy is now about 10 ms, plus about 1 ms of small segments, per chunk and card. The traced read takes
10.3 s, and each card is busy 57-62% of it. The gaps that are left:

| Gap | Size |
|---|---:|
| Submitted but not running, every card | 1.5-1.9 s |
| Card 3 waiting for input (pipeline fill) | 2.46 s, of it 2.07 s before the first chunk |
| Card 0 idle after its last chunk (drain) | 2.19 s |
| Card 1 idle after its last chunk | 1.07 s |

### Context length (2026-11-18)

Engine CLI, 128k-capable placement (`--max-context` as listed), prompt 1-8k short of the full context, 64 tokens
generated without the drafter, build before fx31:

| Max context | Prompt tokens | Prompt read, tok/s | Decode after, tok/s | Lowest free VRAM a card |
|---|---:|---:|---:|---:|
| 32k | 31,019 | 312.9 | 25.5 | 2.97 GB |
| 64k | 63,019 | 311.2 / 312.2 / 312.3 | 11.4 / 23.6 / 24.7 | 2.93 GB |
| 128k | 120,019 | 304.9 | 24.1 | 2.89 GB |

DeepSeek V4's attention keeps a fixed 128-token window per layer plus a compressed FP4 history, so caches are
0.01-0.05 GB a card even at 128k, and every expert stays in VRAM. The first 64k run decoded at half speed: layer time 68 ms
a token against 30-37 ms. Two reruns did not repeat it, so it is a one-off with no known cause.

**With fx31 the 120k read takes 148.6 s, 807.9 tok/s (was 393.6 s, 304.9).** One run; decode after it 21.4 tok/s on
16 tokens. The hand-off copy cost the same ~1 s a chunk at any depth, so the gain holds at long context.

### Prompt chunk re-sweep on the fx31 build

| Chunk | 8k read, tok/s (2 runs) | 2k read, tok/s (1 run) |
|---:|---:|---:|
| 256 | 752.5 (1 run) | - |
| 384 | 747.9 / 734.0 | 502.8 |
| **512** | **763.7 / 758.4** | **469.9** |
| 768 | 762.6 / 767.3 | 447.6 |
| 1024 | 735.5 / 734.6 | 379.6 |

At 8k, 512 and 768 are equal within noise. 384 is 7% faster at 2k but 2-4% slower at 8k, so the chunk stays 512.
The 2k read went from 195 to 470 tok/s with fx31. Chunk 256 hung at 8k on the slow-copy build and now finishes
(one run). The 8k output was `2e96bd4d` in 9 of 10 runs; one 512 run gave `8da9f19f`, with the same top token and
rel L2 0.19 against its pair. 2k outputs differ between runs, as before.

### Serving (2026-11-18)

Maya's `server.py` drives the engine through its stdin protocol and serves OpenAI-compatible chat completions with
streaming and prompt-prefix reuse. The engine has no `WRAP` command, so the server's wrap timer is set to 0.

- **30-minute mixed soak** (drafter on, v1 adapter, build before fx31): 67 of 67 requests answered, no hangs. Drafted
  decode 35.4 tok/s after a short prompt, 42.7-44 after 8k; prompt read 8k 288, 2k 211. Repeated requests gave the same
  tokens, except the first request after load, which differed from later identical ones at token 3 (open, below).
- **HTTP smoke test**, run before and after fx31: ready 68-70 s after start; non-streaming, streaming and a repeat all
  answered correctly with reasoning; repeats had 42 of 43 prompt tokens cached and decoded at 28-36 tok/s; stopping
  the process tree stopped the engine.

## Decode hill climb (2026-11-18 night / 19)

Goal: drafted decode from ~37 (CLI) toward 50+. Unless a row says otherwise: engine CLI, the long-answer prompt,
256 tokens, `--dspark on --dspark-conf 0.15`, `STRATA_DS4_DSPARK_CUM=0.1`, v1 adapter, warm runs, output compared by hash.

### Host launch cost is not the limit

A stand-alone benchmark of empty kernels on one card, in-order queue, Level Zero v1:

| Launch | us a launch |
|---|---:|
| `parallel_for`, no event used, profiling off | ~7.5 |
| the same, profiling on / with an event / with a queue copy | ~7.5 |
| `nd_launch` | 8.9 |
| `UR_L0_USE_IMMEDIATE_COMMANDLISTS=0` | 5.1, but decode hung in 3 of 4 runs: rejected |
| a 256-byte kernel capture | +1 |

The classified timeline agrees: inside a layer the gaps between kernels are under 1 us, so the host stays ahead of
the cards. A plain decode token is device bound: 31.2 ms span, all four cards idle at once for only 3.9 ms of it.

### Drafted rounds: two stalls found and fixed (fx33, `--reserve-mib 768`)

A drafted round (draft, then one verify window) had 12.1 ms with every card idle. Two causes:

1. **The drafter's tap copy.** The verify window copies its hidden-state taps to the host with `dpct`'s pitched
   device-to-host copy. That helper allocates a temporary buffer and frees it in a `host_task`, which stalls the
   in-order queue: about 0.74 ms, three times a round. fx33 copies up to 16 rows with one plain `queue.memcpy` each
   (`DS4_TAP_COPY=0` restores the helper).
2. **Experts spilled to the CPU lane on the last card.** With `--reserve-mib 1024` the served 128k placement left 33
   routed experts on the CPU lane (13 at 12k). No token was routed to them, but a layer that owns any CPU-lane expert
   waits for the CPU lane's answer every token, so it is no longer free of host waits. `--reserve-mib 768` puts all of
   them in VRAM (978 MiB still free on the last card).

| Build | Round, ms | All cards idle, ms | Verify window rows 2 / 3 / 4 / 5, ms | Draft, ms |
|---|---:|---:|---|---:|
| before | 60.1 | 12.1 | - | - |
| **fx33 + reserve 768** | **50.7** | **6.2** | 38.9 / 43.4 / 52.8 / 63.1 | 6.4 |

Both live since 2026-11-18. One served smoke-test prompt decoded at 43-44 tok/s warm. 120k prompt read 811.6 tok/s (814 at
reserve 1024: unchanged).

### Where a verify window's extra time goes

Device time a plain token, by kernel length (27.3 ms in all):

| Kernel length | Launches | ms |
|---|---:|---:|
| under 5 us | 838 | 2.55 |
| 5-20 us | 254 | 2.9 |
| 20-50 us | 48 | 1.5 |
| 50 us or more | 335 | 20.3 |

Extra device time of a verify window over a plain token, by rows:

| Kernel group | 2 rows, ms | 3 rows, ms | 4 rows, ms |
|---|---:|---:|---:|
| routed experts | +4.1 | +6.9 | +10.0 |
| dense Q6_K tiles | +1.6 | +2.5 | +3.5 |
| other dense mat-vec | +0.6 | +0.9 | +1.2 |
| router (`gemv_f32` rows kernel) | +1.1 | +1.2 | +1.2 |

The 6.2 ms still idle per round: next round's start 0.62, card-to-card hand-offs ~1.2, drafter seed 0.31, replicate
waits ~0.55, gaps before the MoE input quantize ~0.57, the rest spread thin.

### Verify-width kernels (fx34, fx35)

fx34 gives the dense Q6_K tiled mat-vec templates for the exact column count of a verify window (`DS4_Q6T_MC`), in
place of rounding up to 4 or 8. Dense Q6_K tile time per verify window (plain token 10.62 ms):

| `DS4_Q6T_MC` | 2 rows | 3 rows | 4 rows | 5 rows |
|---|---:|---:|---:|---:|
| 0 (old dispatch) | 12.29 | 13.13 | 14.07 | 16.23 |
| **1 (exact width)** | **11.82** | **12.90** | **13.99** | **15.05** |
| 2 (4 output rows a work-item) | 26.24 | 29.16 | 36.59 | 43.85 |

Mode 2 is about 2x slower (likely register spills). Mode 1 helps most at 2 and 5 rows. The kernel looks bound by
instruction issue, not memory, so the next step for it is XMX int8 (DPAS) rather than more rows a work-item.

fx35 makes mode 1 the default and sends router windows of 2-8 rows down the one-launch-a-token path (the rows kernel
stages an 8-row tile however few rows are live; `DS4_ROUTER_SMALL=0` restores it; prompt chunks keep the rows kernel).

| Run | Live (fx33) | fx35 |
|---|---:|---:|
| Drafted decode, 3 alternating runs | 36.58 / 36.81 / 37.00, mean 36.80 | 37.26 / 37.67 / 37.50, mean **37.48 (+1.9%)** |
| fx35 build, both switches off | - | 37.01 |
| Plain decode | 31.65 | 31.65 |
| 8k prompt read | 738.4 | 738.5 |

Drafted output identical (`f70da23b`) with the same acceptance per position. Live since 2026-11-19 (served smoke test, one easy prompt:
44.4 / 45.3 tok/s warm).

### Drafter settings re-checked

| Setting | Drafted decode, tok/s | Note |
|---|---:|---|
| `--dspark-conf 0.15`, CUM 0.1 (live) | 36.73 / 36.92 | |
| conf 0.1 / 0.15 / 0.25 with CUM 0.2 | 37.20 / 37.23 / 36.84 | within noise of live |
| CUM 0.05 (any conf) | 35.4-35.9 | 3-4% slower: longer drafts that fail |
| `DS4_DRAFT_COST=1` (cost-based cut) | 35.56-35.72 vs 36.96-37.03 | -4%, same tokens |
| `DS4_ROUTER_ROWS=0` | +1.0% decode, -1.1% prompt | led to fx35's row limit |

The draft cut is already near its best; the settings stay. The drafter keeps 53-55% of its first-position drafts.

### Tensor parallel 2 with the uneven split (2026-11-19)

`DS4_TP_GGUF_UNEVEN=1` splits each expert's 9 blocks 5 / 4 (1280 / 1024 values) between two cards. It loads: cards 0+1
run layers 0-18, cards 2+3 layers 19-39 and the head, no expert on the CPU lane, 1.5-4.2 GB free a card. **But it
hangs:** `--tp 2` also turns on threads mode (one submitting host thread per card), which this port had not run in
decode. The first cross-card flag is never raised, then every layer's CPU-lane answer flag stays 0 until the host wait
gives up (~11 s each, 86 waits in a 600 s run). Plain and drafted runs both. The engine's own source marks the uneven
split as having no flow on its groups yet. Not pursued for now: even working, TP needs at least one group exchange a
layer (~40 a token) through host USM at ~0.3-0.4 ms each on this stack, which eats most of the gain of halving each layer.

### Projection to 50+

| Lever | Expected gain |
|---|---:|
| fx35 (done) | +1.9% measured |
| XMX int8 Q6_K mat-vec for verify windows | 3-6% |
| fusing the sub-5 us kernels (838 a token) | 3-4% |
| deferring hand-off and replicate waits | 1-2% |
| verify that stops early once a draft position is rejected | 1-3% |

Stacked, +8-15%: about 40-43 tok/s on the benchmark prompt. 50 on that prompt needs more than these, most likely
cheaper routed experts in the verify window (+4.1 ms at 2 rows, the largest single cost above) or more drafts kept. Idle time alone is not enough to reach 50; device time a verify window has to fall.

## Decode round 4 (2026-11-19, day)

Five steps, each measured on the CLI bench (34-token prompt, 256 tokens, greedy; drafted with `--dspark-conf 0.15`).
Every setting got a warm-up run first (the first run of a new kernel shape includes its JIT compile), then 2-5
alternating reps. **The 256 output tokens were identical to the live build in every run of every step.**

| Step | Drafted, tok/s | Plain, tok/s |
|---|---:|---:|
| Start of the day (fx35, v1 adapter) | 37.5 | 31.7 |
| fx37 lane-packed dense Q6_K + `DS4_Q6K_RM=18`, fx38 256 registers on the prompt experts, `DS4_IQ_RP=4` | 41.4 | 34.6 |
| + Level Zero v2 adapter with `UR_L0_V2_DISABLE_ZE_LAUNCH_KERNEL_WITH_ARGS=1` | 41.55 | 34.6 |
| + fx40 IQ1_S gate / up tiles, fx41 expert-group cap, drafter cut CUM 0.4 | 42.97 | 35.0 |
| **+ fx43 16-lane dense Q6_K (`DS4_Q6K_LEAN=3`) and 256 registers for decode attention (`DS4_GRF43=1`)** | **43.6-43.7** | **36.2** |

All five steps are live (owner's OK each time). Served (warm, short prompts) runs 47-50 tok/s on prose and up to ~70
on code; the first request after a load is slow (JIT). The 8k prompt read is 812 tok/s and 120k 867 tok/s.

### fx37: a lane-packed dense Q6_K layout

A plain read on one B70 reaches 580-600 GB/s; the dense mat-vecs ran at 420-450. fx37 re-packs every dense Q6_K weight
at load into 128-row tiles laid out for sub-group block loads (each lane's words contiguous; low bits, high bits and
scales in separate planes). Bench: one layer's dense set 292 -> 249 us, `wo_b` 80 -> 63 us. In the engine it only
paid with the verify windows at 1 row x 8 sub-groups (`DS4_Q6K_RM=18`); 2 rows was 1.5% slower. Exact (same sums in
the same order). Plain +4.2%, drafted +7.1%.

### fx38: 256 registers, per kernel

The JIT option `-ze-intel-enable-auto-large-GRF-mode` gave the 8k read +14% but cost drafted decode 2.5%, so it is
applied per kernel instead, with `sycl::ext::intel::experimental::grf_size<256>`. The heavy XMX expert kernels (prompt
only) went 735 -> 782 tok/s at 8k, decode unaffected. Each launch with the property needs its own lambda, or SYCL sees
two kernels with one name.

### The v2 adapter, back on

The v2 deadlock ([below](#faster-kernels-expose-the-level-zero-v2-adapter-deadlock)) sat in exactly the call that
`UR_L0_V2_DISABLE_ZE_LAUNCH_KERNEL_WITH_ARGS=1` turns off. With it: six 8k reads, 0 stalls (about 50% before), then a
served idle soak with gaps of 2 / 5 / 10 / 20 / 30 / 45 / 60 min, 16 of 16 correct, no stall. On the bench v2's gain is
within noise (drafted 41.4 -> 41.55). Launch cost on one card: 7.96 us (v1) / 7.80 (v2) on an in-order queue with
profiling, 6.45 on v2 without profiling, 0.56 for a SYCL graph replay.

### fx40, fx41: expert tiles, a group cap, a higher draft cut

- **fx40** packs the IQ1_S gate / up weights at load into 32-sub-block tiles (`DS4_IQ1_TILES=1`, only on layers whose
  experts are all on a GPU). A micro-bench promised 1.5-2x, but its baseline layout ran at 122 GB/s against the engine's
  real 230-250 GB/s, so the engine gain was small: gate/up 86.6 -> 78.2 us a call, plain +1.2%, drafted +0.7%.
- **fx41** runs expert groups of 5-8 entries through the 4-entry build (`DS4_IQ_NE_CAP=4`); each entry keeps its sums in
  order, so it is exact.
- **Drafter cut CUM 0.1 -> 0.4.** Two-draft rounds kept only 0.6 tokens on average; a higher cut drops the weak second
  drafts. Position-1 acceptance 54% -> 67%. With fx41: drafted 41.3 -> 43.0 (+3.9%), plain +1.4%.

### Where a token's time goes (VTune, per delivered token, four cards summed)

| | plain | drafted |
|---|---:|---:|
| device time | 28.97 ms | 23.90 ms |
| wall time (from tok/s) | 28.9 | 24.0 |
| dense Q6_K mat-vec | 12.57 (43%) | 7.93 |
| IQ1_S gate / up | 3.46 | 4.1 |
| expert down | 2.13 | 2.5 |
| sparse attention | 1.54 | 0.88 |

Device time equals wall time: at batch 1 the layer pipeline runs one card at a time and host submission is hidden.
So the levers are kernel speed or real cross-card parallelism, not host overhead. Dense Q6_K is bandwidth bound
(3 columns cost about the same as 1), and the routed experts are what grow with the verify width
(gate/up 87 / 140 / 179 / 223 / 336 us at 1-5 tokens).

### Probes that closed two doors

- **No peer-to-peer on Windows.** `ext_oneapi_can_access_peer` is 0 both ways and a device-to-device `memcpy` fails.
  A host-staged hop costs +12 / +18 / +34 us over no hop for 20 / 100 / 320 KB. Tensor parallel on this stack would pay
  ~45-50 us a hop, which caps it near the current speed.
- **No same-card kernel overlap.** Two queues, or one out-of-order queue, gain at most 6%, even for two half-empty
  kernels. The shared-expert / routed-expert overlap idea is dead on this driver.
- Side finding: a 27.6 MB read repeated alone runs at ~1,100 GB/s, so the L2 holds about 28 MB.

### fx43: dense Q6_K on 16-lane sub-groups, and the spill fixes

- **Rows spill when a sub-group does more than one.** Every row carries seven 64-bit tile pointers; 4 rows a sub-group
  ran 2x slower. "Lean" addressing (one tile base + 32-bit offsets, x loaded once a chunk) removes the spill and is
  exact, but in the engine it gave only +0.6-0.8% (fx42), against -18% on the bench.
- **16 lanes is Xe2's native width.** One row per 16-lane sub-group, lane `l` doing the 32-lane kernel's lanes `l` and
  `l + 16` with separate accumulators, then `lo + hi` (the xor-16 step done in-lane) and xor 8, 4, 2, 1: the same adds
  in the same order, so the same bits (0 differences across 9 bench variants). Bench: one layer 300 -> 268 us (a plain
  read of the same bytes is 240).
- **The one-query decode attention spilled 3,968 bytes a thread** (VTune `Spill Memory Size`), ~1.5 ms a plain token.
  256 registers for that kernel alone (`DS4_GRF43=1`) removes it. 256 registers for the drafter's Q8_0 mat-vec (it spills
  too) did not pay.
- Engine: plain 34.95 -> 36.2 (+3.3-3.7%, confirmed three times), drafted +0.3 to +2.4% (noisier). Prompt read unchanged.

**Bench gains overstated engine gains 5-10x** on fx40 and fx42, and the bench's copy of the live kernel ran ~30% slower
at 3 columns than the engine's own VTune times (unexplained). Only the engine A/B decides.

### Prompt read: already past the target

| Prompt chunk | 8k, tok/s | 120k, tok/s | Output vs 512 |
|---|---:|---:|---|
| 256 | 774 | 770 | same |
| **512 (live)** | **808-817** (6 runs) | **867** | - |
| 1024 | 824 | **955** | 8k same; **120k differs from the 4th token** |

- The prompt runs as four 10-layer stages, one card each; there is no tensor-parallel all-reduce in it.
- The cards are busy ~74% of an 8k read: 16 chunks through a 4-stage pipeline leave a fill / drain bubble of about
  3 / (16 + 3). At 120k (235 chunks) the bubble is ~1%, which is why 120k reads faster than 8k.
- The prompt kernels do not spill (the worst is 1,600 bytes in a kernel at 0.8% of the time), so per-kernel registers
  have nothing left to give there. Time split: routed experts ~58%, sparse attention ~24%.
- Chunk 1024 is +10% at 120k but changes the output there. It stays off until a correctness check (repeat run,
  log-prob compare, 2048 probe); on the GLM port 2048 was not deterministic and 3072+ was wrong.
- In 1 of 6 runs of the 8k read the first two generated tokens differed and the next 14 matched. It looks like a
  near-tie after a long prompt; being watched.

### Measurement trap: a profile that includes the model load

A VTune capture of the whole process showed memory copies as 21% of the GPU time (109.5 GB device-to-host). They are
the model load: about 110 GB of experts uploaded to VRAM. A near-empty profiled run shows the same ~16k copies. Profile
a run long enough that the load is a small share, or subtract a load-only run.

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
7. **Hand-off copies on the copy engine (fx31, 8k 282 -> 765).** A ~33 MB copy into host USM from at most 64 work-groups
   of kernel stores took ~1.0 s a chunk. A queue `memcpy` takes ~10 ms. Profilers that time kernels by name will
   show this as ordinary kernel time, so it looked like work rather than a bubble. Only the classified
   timeline showed that the last stage was waiting on it.
8. **No host stalls inside a drafted round (fx33 + `--reserve-mib 768`, round 60.1 -> 50.7 ms).** `dpct`'s pitched
   copy frees its temporary buffer in a `host_task` that stalls the queue, and a layer that owns even one unused
   CPU-lane expert waits for the CPU every token. Plain per-row copies and a smaller reserve remove both.
9. **Kernels sized to the verify window (fx35, +1.9% drafted).** Exact-width dense Q6_K templates, and the router's
   one-launch-a-token path for windows of up to 8 rows.
10. **A dense Q6_K layout made for sub-group block loads (fx37, drafted +7%).** The weights are re-packed at load so
    each lane's words are contiguous. Bandwidth, not arithmetic, set the dense time.
11. **256 registers where a kernel spills, and nowhere else (fx38, fx43).** The global large-register option helped the
    prompt and hurt decode; per kernel it helps both. VTune's `Spill Memory Size` column finds them.
12. **16-lane sub-groups for the dense mat-vec (fx43, plain +3.3%).** Exact, by doing the 32-lane kernel's two lanes
    per lane and folding the xor-16 step in-lane.
13. **The v2 adapter's deadlock has an off switch** (`UR_L0_V2_DISABLE_ZE_LAUNCH_KERNEL_WITH_ARGS=1`).

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
- The teardown exception at exit: the "no helper queue" sentinel was `&dpct::get_in_order_queue()`, which returns the
  queue of the *current* device, so the comparison failed on any thread that had switched device and the cleanup
  freed a queue it did not own. The sentinel is now captured once (fx29). The exception is gone. The process still
  exits with code 116 after printing its results; the source is unknown.
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
| Host waits around every heavy launch (fx27, `DS4_HX_SYNC`) | did not stop the hang. Off is +1.5% on the v1 adapter (8k 281 -> 286 / 283), so the served config runs `DS4_HX_SYNC=0` |
| Engram reads as the hang cause | wrong; the stacks put it in the driver |
| Prompt chunk 256 | hung at 8k before fx31; finishes on the fx31 build (752 tok/s, one run), slower than 512 |
| Fewer host launches as the decode lever (launch benchmark) | ~7.5 us a launch however launched; the host already runs ahead of the cards inside a layer |
| `UR_L0_USE_IMMEDIATE_COMMANDLISTS=0` | 7.5 -> 5.1 us a launch, but decode hung in 3 of 4 runs |
| Dense Q6_K with 4 output rows a work-item (`DS4_Q6T_MC=2`) | about 2x slower than exact width at every verify size |
| Cost-based draft cut (`DS4_DRAFT_COST=1`) | -4%, same tokens |
| Looser drafter floor (CUM 0.05) | -3 to -4% |
| Replicate waits as the next lever | ~0.55 ms a round: too small to pay first, parked |
| Tensor parallel 2, uneven split (`DS4_TP_GGUF_UNEVEN=1`) | loads, then hangs in threads mode (above); parked |
| Global large-register JIT option | 8k read +14% but drafted decode -2.5%; applied per kernel instead (fx38, fx43) |
| 256 registers on the light prompt experts' 16-row form (fx38b) | 780 vs 780 tok/s |
| 256 registers on the drafter's Q8_0 mat-vec (`DS4_GRF43` bit 2) | spill gone, no speed (43.49 vs 43.74) |
| Lean dense addressing by shape / everywhere (fx42 `DS4_Q6K_LEAN=1` / `=2`) | plain -1% / +0.8%; superseded by the 16-lane kernel |
| Expert down kernel on 16-lane sub-groups (fx44, `DS4_DN16=1`, exact) | plain 36.11 / 36.16 vs 36.14 / 36.16: no gain; the gate/up 16-lane rewrite skipped with it |
| Persistent dense kernels (fixed sub-groups walking rows, with or without next-row prefetch) | 5-20% slower on the bench |
| `DS4_IQ_AHEAD=1` | drafted -25% |
| Drafter on the last card (layer split 10, 11, 10, 9) | 60 experts no longer fit VRAM and went to the CPU lane; output changed |
| IQ lookup tables in device USM instead of shared USM (fx39) | flat, tokens identical |
| `--reserve-mib` 2048 / 3500 (VRAM paging check) | 780 / 772 vs 780: not paging |
| Prompt chunk 256 on the round-4 build | 8k 774, 120k 770 vs 812 / 867 |
| Two queues, or one out-of-order queue, on one card | at most +6%: the driver serializes them |

## Measurement notes

- Prompt reads need `--window 65536` (or any window of at least one chunk) on the `ds4` CLI.
- `DS4_KT=1` per-kernel timing costs about 1% at 8k (276.7 vs ~280 tok/s). It does not time `xfer_put_kernel`, which
  is why the per-kernel table above has no hand-off copy in it.
- `DS4_TL=<csv>` (the classified timeline) costs about 3-8% and must not run together with `DS4_KT`.
- The first run of a freshly built executable is slower and can give different tokens (kernel JIT). Every A/B above
  discards it, except where the table marks it.
- The check mode for the heavy kernels (`DS4_HX_CHECK=n`) poisons the light rows of its buffer, so an end-to-end result
  in that mode is invalid. It checks kernels only.
- `DS4_WATCH=<s>` starts a thread that suspends every thread and prints its stack (`StackWalk64` + `SymFromAddr`)
  after `s` seconds without a layer starting. Driver and runtime frames resolve; the engine's own did not in this build.
- The two 2k runs of the default build gave different 16-token hashes (`70b6660b` / `6fe86dce`); the 8k hash is stable
  across every build above. Unexplained.
- On the fx33-era builds the 16 drafted tokens after the 8k prompt can also differ run to run, on every build tested,
  the live one included (live `2e96bd4d` twice, fx35 `2e96bd4d` twice, one switch-only build once `258e892f`). Treat a
  single changed hash on that test as noise until it repeats; the 256-token drafted test stays byte-stable.
- The first run of a new kernel shape is slow (JIT on first use), including after a server restart: the first served
  reply decoded at 25.9 tok/s, the next two at 44.4 / 45.3.

## Future leads

After round 4 (2026-11-19): the prompt target is met; decode needs ~15% more on the benchmark prompt.

- **Prompt chunk 1024** (+10% at 120k): needs the correctness check above before it can go live.
- **Routed experts in the verify window** are the part of a drafted token that grows with width. The exact 16-lane form
  did nothing for the down kernel, so the next try is a different load pattern, not a narrower sub-group.
- **SYCL graph replay** costs 0.56 us against ~7.8 us a launch. Device time already equals wall time at batch 1, so
  this matters only where the host is on the critical path (verify windows, the drafter).
- **Tensor parallel** stays parked: no peer-to-peer on Windows, ~45-50 us a host-staged hop.

The older list, ranked by expected gain toward 600 tok/s prompt and ~50 decode (items 1, 2 and 7 since partly done):

1. **Decode toward 50+**, in this order (see the [projection](#projection-to-50)): XMX int8 Q6_K mat-vec for verify
   windows; fusing the 838 kernels under 5 us a token; deferring hand-off and replicate waits; early stop of a verify
   window after a rejected position. Routed experts are the largest part of a verify window's extra cost (+4.1 ms at
   2 rows) and the next target after those.
2. **Prompt pipeline fill and drain.** With fx31 the largest gaps are card 3 waiting for its first chunk (~2.5 s) and
   cards 0 and 1 idle after their last (~2.2 / ~1.1 s) at 8k. A different chunk size does not recover them (see the re-sweep);
   a smaller first chunk might.
3. **Submitted but not running, 1.5-1.9 s a card.** Work is queued but the card has not started it. Next look:
   launch-to-start latency per kernel type, and whether the host waits for one hand-off flag hold up the launches behind it.
4. **Sparse attention and the light experts**, now a larger share of a shorter read. Light experts need a grouped
   kernel that batches several small experts per work-group. The ESIMD grouped GEMM that sped up
   [GLM](../../glm-5.3/sycl-port/experiments/2026-11-15-esimd-grouped-gemm/) and
   [Flash-Next](../../strata-windows-port/esimd-prefill/) is the reference.
5. **The first request after load can differ from later identical ones.** Candidates, in test order: the background GEMM
   warm-up thread, prompt-prefix reuse, the drafter's shapes on first use, the Engram row cache.
6. **Exit code 116**, the serve-mode watchdog false alarm, and a 256k context test.
7. **Whole-tensor Q6_K SoA repack** for the remaining dense shapes (wo_b, k 8192), bench -7%.
8. **Tensor parallel through threads mode**: find why the first cross-card flag of `--tp 2` is never raised. Only
   worth it if group exchanges get much cheaper than ~0.3 ms.
