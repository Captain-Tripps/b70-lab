# Plan: Strata-style speed for DeepSeek (updated 2026-10-17)

> **2026-10-26 update:** Track A's V4 0731 rejection below still stands. For V4.1, follow the
> [Strata native Windows action plan](strata-v41/PLAN.md). It ports the separate upstream V4.1 engine
> using the lab's existing Windows foundation, so that route does not depend on waiting for llama.cpp
> support. Track B below is retained as the historical October 17 plan, not the current Strata prerequisite.

Status: **Track A rejected** after step A0 (ceiling 1.12x plain / 1.19x DSpark, see the end of this file).
**Track B historical** (its wait-for-llama.cpp prerequisite is superseded for the new Strata route). Results will go into [../STATUS.md](../STATUS.md) as they land.

## Why

Strata runs Qwen3.8-Flash-Next on **2 B70s** at ~98 tok/s decode and ~1,400 tok/s prompt read (112k-token prompt),
against the tuned llama.cpp fork on **4 cards** at ~61 / ~750 ([../strata-windows-port/](../strata-windows-port/)).
The main design difference is **expert parallelism**: every card computes its share of each layer's experts for
every token, at the same time. The fork splits models **by layers**, so during single-token decode only one of the
4 cards works at any moment (each idle ~75% of the time). The fork's cross-card pipeline helps prompt reading
(batches), not decode.

Other Strata ingredients: all experts resident in VRAM; one captured graph per decode step (near-zero launch cost);
model-specific fused kernels; MTP drafting; int8 KV. Part of its edge is also its smaller quant (IQ3_S / IQ3_XXS).

## Two targets

| | DeepSeek V4 Flash 0731 (running now) | **DeepSeek V4.1 Flash 1017 (released 2026-10-17)** |
|---|---|---|
| Architecture | `DeepseekV4ForCausalLM`, supported in llama.cpp and the fork | **new** `DeepseekV41ForCausalLM`, not in llama.cpp yet |
| Size | ~280B; UD-Q2_K_XL 90 GB fits 4 cards | **~510B** (510 GB FP8): hidden 5120, 384 experts x 2304, 40 layers |
| New parts | - | "engram" n-gram memory layers (layers 1, 14), KV shared across layers, new compressed-attention ratios, 3 MTP layers, built-in DSpark draft, vision tower |
| On the test machine (4x B70, 128 GB VRAM) | ~30 tok/s on long-document work (DSpark), 21-24 at 59k; prompt ~450 tok/s at 59k | cannot run (no llama.cpp support); ~2.7 bits/weight would be ~170 GB > 128 GB VRAM |
| License | MIT | MIT |

## Track A: expert parallelism for V4 Flash 0731 in the llama.cpp fork (first)

**A0. Measure the ceiling (~1 h, decides go / no-go).** `GGML_SYCL_PROFILE_OPS=1` on one decode step (plain and
DSpark): share of time in the expert matmuls (`MUL_MAT_ID`) vs attention / dense / other, and per-card busy / idle.
Upper bound: if experts are E% of the step and 4 cards share them, step time -> (1 - E) + E/4 (+ exchange cost).
Go if the bound is >= 1.4x.

**A1. Design (~0.5 day).**
- Placement: card 0 keeps everything non-expert (attention, dense, router, KV) plus a quarter of the experts; cards
  1-3 each hold a quarter of every layer's experts. Strata's 2-card split is the template.
- Per layer per token: card 0 routes and pushes the token's hidden state (4096 x fp16 = 8 KB) to the other cards;
  each card computes its routed experts; partial sums return and are added on card 0.
- Windows has no peer access between B70s, so the exchange goes through host memory in **one shared SYCL context**
  (as in Strata Windows patch `0002`), with device-side spinning on system-scope flags. Measured host round trip incl.
  launches ~57 us; the device-spin path should be well under that. 43 layers x ~10-30 us = 0.4-1.3 ms per token,
  against ~33 ms per token today.
- In the code: a new MoE split mode in the fork (expert tensors split by expert range across devices), either in the
  SYCL `MUL_MAT_ID` path or as per-device partial MoE nodes in the DeepSeek graph builder plus a final add.

**A2. Build (multi-day).** Prototype without a draft model first, then DSpark verify batches (several tokens per step,
which is where Strata's batched kernels matter). Behind an environment switch, default off.

**A3. Validate.** Perplexity equal to the current fork; answer checks ([../bench/squal.py](../bench/)); a replay of
real long-document requests; a soak. Compare decode at 7k / 59k / 102k context against the current setup.

**Risks.** The ggml scheduler assumes layer placement; host-memory exchange latency under load; the prompt path
already uses the cross-card pipeline and expert parallelism must not regress it. And from the Strata AOT miscompile:
check answers, not just speed.

## Track B: DeepSeek V4.1 Flash 1017 (prepare, don't build yet)

**B0. Watch for llama.cpp support** of the new architecture (engram layers, KV sharing, new compression, 3-layer MTP).
Until it lands upstream, nothing built here can load it. Community GGUFs in custom formats need matching code.

**B1. Size plan once supported.** ~510B parameters: ~170 GB at ~2.7 bits/weight. The test machine has 128 GB VRAM
and 112 GB system RAM. Options: split experts between VRAM and RAM (hot experts resident, cold experts streamed or
computed on the CPU, as Strata / ktransformers do), or a ~2-bit quant if quality holds (KLD check against a higher
quant, as done for Flash-Next).

**B2. Reuse Track A.** Expert parallelism across 4 cards plus an expert cache for what does not fit is the same
machinery; Track A builds and validates it on a model that already works.

**B3. Quality first.** Before any speed work, compare V4.1 at the chosen quant with V4 0731 on a fixed task set, since
the release claims shorter outputs and better benchmarks.

## Order and decision points

1. A0 profile (1 h) -> go / no-go for Track A.
2. If go: A1 design note, then A2 prototype without a draft model.
3. In parallel, B0: check upstream for V4.1 support weekly.
4. When V4.1 loads in llama.cpp: B1 size / quant study, then decide whether to move from V4 0731 to V4.1.

## Caveats

- Part of Strata's speed may come from its smaller quant and model-specific fused kernels, not only from parallelism.
- DeepSeek V4's attention (compressed sparse attention + indexer) and the DSpark draft stay as they are in Track A;
  only the MoE part changes.

## A0 result (2026-10-17): no-go for expert-only parallelism

`GGML_SYCL_PROFILE_OPS=1` (serialized per-op timing, which inflates small ops), fork r52, 7k context, 4 cards, layer
split, DeepSeek V4 Flash 0731 UD-Q2_K_XL. Per-card analysis; for DSpark only the verify graphs are counted (the
drafter's small graphs are dropped).

| Op time per step, all 4 cards | Plain decode (102 ms) | DSpark verify (156 ms) |
|---|---|---|
| Expert matmuls (`MUL_MAT_ID`) | 14.8 ms = 14% | 33.9 ms = 22% |
| Dense matmuls (`MUL_MAT`: attention projections, shared experts, indexer) | ~28 ms = 28% | ~45 ms = 29% |
| Everything else (attention, norms, copies, gathers / sets, concat, ...) | ~58% | ~49% |
| Ceiling: experts split over 4 cards, zero exchange cost | **1.12x** | **1.19x** |
| Ceiling over 2 cards | 1.08x | 1.12x |

Both are below the 1.4x go threshold, so Track A as designed is **rejected**.

Why it differs from Flash-Next: DeepSeek V4 Flash's experts are small (2048 wide, low-bit). Per-token time is dominated
by dense projections and many small ops, not by expert matmuls. Strata's expert-parallel idea does not transfer as is.

What could still pay (not started; each needs its own A0-style measurement):
- **Dense + expert split per layer (tensor parallel):** ceiling ~1.6x if dense matmuls (29%) and experts (22%) both
  split 4 ways. But every layer then needs activation all-reduces across cards, and the earlier `-sm tensor` attempt on
  GLM was sync-bound at 4.8 tok/s. First measure the host-memory all-reduce cost on Windows for 43 layers x 2 per
  token; it is unmeasured.
- **Small-op overhead:** half the profiled time is many small ops (inflated by the profiler). Fusion gave Flash-Next
  only +2-4%; graph capture was 3x slower with MTP's varying shapes.
- **Track B (V4.1) stands:** it needs llama.cpp support first. Its 384 x 2304 experts are a larger share of the model,
  so A0 gets re-run on it.
