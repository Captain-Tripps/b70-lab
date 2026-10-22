# Status: winners and losers

One row per idea. Gains are decode tok/s unless the row says prompt read. Each number was measured on the test
machine (see [README](README.md)); the details link says which model file, runtime and harness. Newest first within
each status. History of changes: [CHANGELOG.md](CHANGELOG.md).

Status: **live** (running every day), **staged** (built and measured, not switched on), **upstream** (merged or in
review in llama.cpp), **rejected**, **open bug**, **fixed**, **superseded**, **planned (parked)**, **measured**, **passed**.

A speed number only counts after an answer check: the broken Strata AOT build produced garbage, the MTP draft
predicted the garbage easily, and acceptance inflated tok/s (96.6 "tok/s" that meant nothing).

## Current best per model

| Model | Best setup | Numbers | Date | Details |
|---|---|---|---|---|
| Qwen3.8-Flash-Next | **Strata (Windows port), GSQ-RCO IQ3_S, 2x B70, 1 slot x 200k, int8 KV, JIT build, `--prefill 8192`, `--ple-io mmap`** | ~99 tok/s decode, ~1,420 tok/s prompt read at 33.6k (1,433 on a 112k prompt); answers correct; vision OK; 2-hour soak clean (134 cycles, 0 errors). llama.cpp fork on 4 cards: 60.6 / 748 | 2026-10-17 | [strata-windows-port](strata-windows-port/) |

## All items

| Item | Model | Gain / loss (numbers) | Status | Date | Details |
|---|---|---|---|---|---|
| Tensor-split decode gap (2 cards, small batches) | Qwen3.8-27B Q8_0 | llama-bench pp1 / pp5 / pp8 / tg: tensor -19% / -27% / -33% / -21% vs layer, PR #30956 no change at 1-8 tokens; ~40 ms per forward lost to the split; fix under investigation | measured | 2026-10-22 | [TENSOR-SPLIT-DECODE.md](llama.cpp-sycl/TENSOR-SPLIT-DECODE.md) |
| `-sm tensor` + PR #30956 for Qwen3.8-27B (MTP) | Qwen3.8-27B Q8_0 / UD-Q6_K_XL | prompt read -1% / -2%, decode -18% vs layer split | rejected | 2026-10-22 | [PR30956-qwen27](llama.cpp-sycl/PR30956-qwen27-2026-10-22.md) |
| Upstream PR #30956 (fast tensor-split exchange) | Mistral-Small-3.2-24B Q8_0 (2 cards tensor) | prompt read +14%, decode +2%, ub-4 perplexity bit-identical | live | 2026-10-22 | [PR30956](llama.cpp-sycl/PR30956-2026-10-21.md) |
| Fork rebased onto upstream (r67c), more entries | Qwen3.8-27B Q8_0 / Q6_K, DeepSeek V4 no-draft / DSpark+lookup, Flash-Next MTP+lookup | 27B decode +3% / +6%, prompt +23% / +11%, perplexity equal; DeepSeek prompt +43% / +37%; Flash-Next lookup decode +14%; answers correct | live | 2026-10-18 | [rebase notes](llama.cpp-sycl/REBASE-2026-10-17.md) |
| SYCL f16 MUL_MAT on a padded row view (test-backend-ops `k_v` cases) | - | 32 cases wrong (ERR ~1-2) on r52, r66 and r67c alike; not hit by the models tested (FA on) | open bug | 2026-10-18 | [rebase notes](llama.cpp-sycl/REBASE-2026-10-17.md) |
| SYCL SWIGLU_OAI advertised for f16 but kernel asserts f32 | - | test-backend-ops aborted; fixed locally by limiting support to f32 (gpt-oss uses f32) | fixed (locally) | 2026-10-18 | [rebase notes](llama.cpp-sycl/REBASE-2026-10-17.md) |
| Fork rebased onto upstream llama.cpp 2026-10-17 (r67c) | DeepSeek V4 Flash 0731 (DSpark) | prompt read at 33.6k 512 -> 699 tok/s (+36%), at 107k 425 -> 570 (+34%); decode 28.8 -> 30.2 (+5%), at 107k 23.1 -> 26-28; 50-min soak clean; perplexity equal (16 chunks 6.463 vs 6.479); answers correct | live | 2026-10-18 | [rebase notes](llama.cpp-sycl/REBASE-2026-10-17.md) |
| Fork rebased onto upstream llama.cpp 2026-10-17 (r67c) | gpt-oss-120b | decode 54.2 -> 57.8 (+7%); short prompts +9%; 26k-85k prompts flat (-2% at 85k); 30-min soak clean; perplexity identical; answers correct | live | 2026-10-18 | [rebase notes](llama.cpp-sycl/REBASE-2026-10-17.md) |
| Fork rebased onto upstream llama.cpp 2026-10-17 (r67c) | GLM-5.3-Flash Maya-M | decode 21.9 -> 22.5 (+3%); prompt flat; perplexity identical (5.5716 / 5.5946); one runtime instead of a separate GLM branch | staged | 2026-10-17 | [rebase notes](llama.cpp-sycl/REBASE-2026-10-17.md) |
| Fork rebased onto upstream llama.cpp 2026-10-17 (r67c) | Qwen3.8-Flash-Next (llama.cpp MTP entry) | decode 59.9 -> 59.1 (-1%, noise); prompt read at 28k 771 -> 843 (+9%); perplexity equal; answers correct. Needed two local fixes for the shared-weights MTP draft file | staged (neutral) | 2026-10-17 | [rebase notes](llama.cpp-sycl/REBASE-2026-10-17.md) |
| Upstream order-preserving Q8_0 MoE path (`GGML_SYCL_MMID_Q8_0_WIDE=0`) vs fork's 16-byte path | Qwen3.8-Flash-Next | decode 58.2 vs 59.1 (-1.5%); prompt at 28k 872 vs 843 (+3%) | measured (fork path stays default) | 2026-10-17 | [rebase notes](llama.cpp-sycl/REBASE-2026-10-17.md) |
| Upstream Qwen3.8-Flash-Next MTP cannot load a shared-weights MTP draft (no token_embd), then asserts on unused k-pool inputs | Qwen3.8-Flash-Next | load error, then `GGML_ASSERT(buffer)` on the first draft decode | fixed (locally, in r67c) | 2026-10-17 | [rebase notes](llama.cpp-sycl/REBASE-2026-10-17.md) |
| DeepSeek V4.1 Flash 1017 - watching for llama.cpp support | DeepSeek V4.1 Flash 1017 (~510B, new architecture) | none yet: not loadable until llama.cpp supports it; ~170 GB at ~2.7 bits/weight vs 128 GB VRAM, so experts must split VRAM / RAM or use a ~2-bit quant | planned | 2026-10-17 | [plan, Track B](deepseek-v4/PLAN-expert-parallel.md) |
| Expert parallelism for DeepSeek V4 Flash 0731 (Strata-style, all cards work on every token) | DeepSeek V4 Flash 0731 | A0 profile: experts are only 14% (plain) / 22% (DSpark) of decode op time; dense matmuls ~29%, small ops ~50%. Ceiling 1.12x / 1.19x, below the 1.4x go line. Dense + expert tensor parallel could reach ~1.6x but its all-reduce cost is unmeasured | rejected (A0: ceiling 1.12x plain / 1.19x DSpark) | 2026-10-17 | [plan, Track A](deepseek-v4/PLAN-expert-parallel.md) |
| Strata IQ3_S, 2 cards, int8 KV, 1 x 200k, prefill chunk 8192, JIT build | Qwen3.8-Flash-Next GSQ-RCO IQ3_S | decode 97.6 tok/s vs llama.cpp fork r62 on 4 cards (UD-Q4_K_XL) 60.6 (+61%); prompt read 1,415 vs 748 tok/s at 33.6k (1.9x); decode after that prompt 64.9 vs 28.6 (2.3x); answers correct. Variant 2 x 112k / chunk 4096: 100.8 / 881 / 60.7 | staged | 2026-10-17 | [strata-windows-port](strata-windows-port/) |
| Strata `--ple-io mmap` instead of `direct` (27 GB PLE table from the OS file cache, not unbuffered SSD reads every token) | Qwen3.8-Flash-Next IQ3_S | with `direct`, decode drifted ~98 -> ~70 tok/s once the SSD had taken ~130 GB of writes (reboot did not help); `mmap`: 98.0-99.4 on fresh starts, 99.2 decode / 1,426 prompt via llama-swap. Needs ~27 GB free RAM. The best config now uses `mmap` | live | 2026-10-17 | [strata-windows-port](strata-windows-port/) |
| Strata 2 slots x 112k vs 1 slot x 200k | Qwen3.8-Flash-Next IQ3_S | two concurrent streams: 82.2 tok/s aggregate (60.8 + 53.0) vs 70.2 served in turn (+17%); but prompt read 889 vs 1,421 tok/s (-37%) and 112k vs 200k context. 1 x 200k kept as default; 2 slots only when clients overlap | rejected as default (measured) | 2026-10-17 | [strata-windows-port](strata-windows-port/) |
| Strata MTP draft sweep (`--spec` 3 / 5 / 6, p-min 0.1 / 0.3) | Qwen3.8-Flash-Next IQ3_S | defaults (`--spec 4`, p-min 0) 99.2; spec 3 93.3, 5 95.8, 6 91.4; p-min 0.1 98.7, 0.3 100.1 (noise) | rejected (neutral or worse) | 2026-10-17 | [strata-windows-port](strata-windows-port/) |
| Strata 2-hour soak via llama-swap (IQ3_S, 1 x 200k, 2 cards, vision on) | Qwen3.8-Flash-Next IQ3_S | 134 cycles, 0 errors, 0 engine restarts; answer checks 134/134, vision 134/134 (median 4.3 s); decode 93.0 tok/s median (92.8-93.2, no drift); 112k-token prompt 1,429-1,434 tok/s, decode after 68.7-69.0 (45 runs) | passed | 2026-10-17 | [strata-windows-port](strata-windows-port/) |
| Strata prompt chunk size sweep (`--prefill` 6144 / 7168 / 8192 / 10240 / 12288) | Qwen3.8-Flash-Next IQ3_S | 8192 kept: 99.0 decode, 1,417 prompt at 33.6k; a 112k-token prompt reads at 1,433 tok/s (78 s), ~2x llama.cpp's ~685 at ~87k. 6144: 102.3 / 1,247. 10240 barely fits and slows ~3x (35.8 / 517); 12288 does not fit | measured | 2026-10-17 | [strata-windows-port](strata-windows-port/) |
| GSQ-RCO IQ3_S vs IQ3_XXS quant quality (KLD vs UD-Q4_K_XL, 30 x 512) | Qwen3.8-Flash-Next | IQ3_S: perplexity +1.0%, mean KLD 0.131, same top token 88.4%; IQ3_XXS: +3.5%, 0.211, 85.3% (reference is itself a quant, so KLD overstates the gap to full precision) | measured | 2026-10-17 | [strata-windows-port](strata-windows-port/) |
| Strata IQ3_XXS, 2 cards, int8 KV, JIT build (200k x 2 slots, MTP depth 4) | Qwen3.8-Flash-Next IQ3_XXS | 108.2 tok/s vs llama.cpp r62 on 4 cards (UD-Q4_K_XL) 60.6 (+79%); prompt read 599 vs 748 tok/s at 33.6k (-20%); decode after that prompt 58.7 vs 28.6 (2.0x); answers correct, identical to llama.cpp on 4 check prompts (97.7 on a rerun). Different quant | superseded (by IQ3_S: better quality, faster prompt, ~7-10% lower decode) | 2026-10-16 | [strata-windows-port](strata-windows-port/) |
| Strata int8 KV wrong answers on Windows | Qwen3.8-Flash-Next IQ3_XXS | cause: AOT miscompile of batched int8 decode attention (oneAPI 2026.0); fixed by a JIT build (patch 0003) | fixed | 2026-10-16 | [strata-windows-port](strata-windows-port/) |
| Strata Windows port, 2 cards, fp16 KV, 32k | Qwen3.8-Flash-Next IQ3_XXS | 67.4 tok/s, answers correct, vs 60.6 (+11%); prompt 570 vs 748 tok/s | superseded (by int8 + JIT) | 2026-10-16 | [strata-windows-port](strata-windows-port/) |
| Level Zero multi-thread submit + oneMKL deadlock | - | 5 of 6 runs hang on driver 8976 (4 threads, warm-up) | open bug (driver) | 2026-10-11 | [reproducers](reproducers/) |
| GLM-5.3 Maya-M in the SYCL fork (g10) + MTP n4 / p0.75 | GLM-5.3-Flash Maya-M | 16.5 -> 24-25 tok/s prose (+50%), 33-35 on edits; perplexity equal to upstream | live | 2026-10-14 | [glm-5.3](glm-5.3/) |
| GLM-5.3 cross-card pipeline | GLM-5.3-Flash Maya-M | long-prompt read ~240 -> 330-370 tok/s (+43%) | live | 2026-10-14 | [glm-5.3](glm-5.3/) |
| r62: top-k MoE single work-group + small fusions + conv-snapshot fusion | Qwen3.8-Flash-Next | ~+4.3% over r56 (-> ~61 tok/s); outputs bit-identical | live | 2026-10-12 | [llama.cpp-sycl](llama.cpp-sycl/) |
| r56: Q8_0 MoE expert reorder | Qwen3.8-Flash-Next | 55.6 -> 58.3 (+4.9%) | live | 2026-10-12 | [llama.cpp-sycl](llama.cpp-sycl/) |
| r53: F32 mat-vec for 2-8 columns | Qwen3.8-Flash-Next | 49.2 -> 54.4 (+10.5%) | live | 2026-10-11 | [flash-next](flash-next/) |
| MTP n-max 4 / p-min 0.1 | Qwen3.8-Flash-Next | +6.6% vs n3 / p0.1 | live | 2026-10-11 | [flash-next](flash-next/) |
| Q6_K / Q5_K wide dot (r64-r66), `-ub 1024`, MTP n4 / p0.1 | Qwen3.8-27B Q6_K | 35.8 -> 40-43 (+12-20%) | live | 2026-10-12 | [llama.cpp-sycl](llama.cpp-sycl/) |
| Cross-card pipeline (r52), `-b 8192` | DeepSeek V4 / gpt-oss-120b / Flash-Next | prompt read: DeepSeek 59k 236 -> 446; gpt-oss 47k 446 -> ~1030; Flash-Next 50k 487 -> ~770; decode unchanged | live | 2026-10-06 | [llama.cpp-sycl](llama.cpp-sycl/) |
| Sparse FA + oneMKL indexer (r27) | DeepSeek V4 Flash | at 59k: plain decode +22%, DSpark 16.8 -> 21-24; prompt +96% at 59k | live | 2026-10-05 | [deepseek-v4](deepseek-v4/) |
| Local-memory IQ2_XS / IQ3_XXS MoE kernel (r9, v3 in r17) | DeepSeek V4 Flash | DSpark 18.5 -> 24.2 (+31%); expert matmul 1.6-2.3x | live | 2026-10-03 | [deepseek-v4](deepseek-v4/) |
| DeepSeek V4 routing fusion | DeepSeek V4 Flash | plain +2%, DSpark 0; -340 launches per step | live | 2026-10-03 | [deepseek-v4](deepseek-v4/) |
| QSA indexer gather + mean-pool fusion (r4) | Qwen3.8-Flash-Next | decode at 58k depth 18.6 -> 22.8 (+23%) | live | 2026-10-01 | [llama.cpp-sycl](llama.cpp-sycl/) |
| Idle heartbeat (`GGML_SYCL_IDLE_HEARTBEAT_SEC=30`) | all | stops the driver moving idle VRAM to RAM (server was killed 3-5 min after every load) | live | 2026-10-01 | [hardware notes](hardware-and-windows-notes.md) |
| `GGML_SYCL_ENABLE_DNN=0` | Flash-Next / DeepSeek V4 | prompt +18-20% / +4-9% | live | 2026-10-01 | [llama.cpp-sycl](llama.cpp-sycl/) |
| `set_tensor_2d` for SYCL buffers ([#30358](https://github.com/ggml-org/llama.cpp/pull/30358)) | gpt-oss-120b `-sm tensor` | load ~265 s -> ~115 s | upstream (open) | 2026-10-11 | [llama.cpp-sycl](llama.cpp-sycl/) |
| MXFP4 SWAR decode + MoE reorder ([#29809](https://github.com/ggml-org/llama.cpp/pull/29809)) | gpt-oss-20b / 120b | 55.8 -> 106.6 / 33.3 -> 67.1 | upstream (merged) | 2026-10-10 | [gpt-oss](gpt-oss/) |
| Pinned `-sm tensor` all-reduce ([#29604](https://github.com/ggml-org/llama.cpp/pull/29604)) | Qwen3.8-27B Q8_0 (2 cards) | tensor prompt +37-45%, decode 18.2 -> 20.2 | upstream (merged) | 2026-09-30 | [llama.cpp-sycl](llama.cpp-sycl/) |
| Q8_0 16-byte loads, Q8_0 GLU fusion, ADD+RMS fusion, FA split 48 | Qwen3.8-27B Q8_0 (2 cards) | 15.42 -> 17.47 short; FA split +4.5-6.2% at depth | staged (patches) | 2026-09-27 | [llama.cpp-sycl](llama.cpp-sycl/) |
| `STRATA_NIGHT_PREFILL_GROUPED=1` with IQ3_S | Qwen3.8-Flash-Next IQ3_S | not supported: engine error "card 0 gate/up type 23" and restart; must be 0 for IQ3_S (IQ3_XXS needs it on: off = 239 tok/s prompt) | rejected | 2026-10-17 | [strata-windows-port](strata-windows-port/) |
| Strata AOT build (oneAPI 2026.0 ocloc, bmg-g31) | Qwen3.8-Flash-Next IQ3_XXS | int8 batched decode attention miscompiled (parity: half the outputs wrong incl. inf); its 96.6 tok/s was invalid. `-ze-opt-greater-than-4GB-buffer-required` does not help | rejected | 2026-10-16 | [strata-windows-port](strata-windows-port/) |
| Grouped expert verification | Qwen3.8-Flash-Next | -5 to -10% | rejected | 2026-10-15 | [rejected-ideas](rejected-ideas/) |
| GLM hc-gate fusion | GLM-5.3-Flash | +1%, perplexity 5.5565 -> 5.6031 | rejected | 2026-10-14 | [rejected-ideas](rejected-ideas/) |
| `-sm tensor` for GLM-5.3 | GLM-5.3-Flash | 4.8 tok/s (vs 24-25 layer split) | rejected | 2026-10-13 | [rejected-ideas](rejected-ideas/) |
| SYCL graph replay | Flash-Next / DeepSeek V4 | ~3x slower (DeepSeek 21.9 -> 7.1) | rejected | 2026-10-12 | [rejected-ideas](rejected-ideas/) |
| n-gram lookup in front of DSpark, real document checking | DeepSeek V4 Flash | 19-23 vs 27-30 tok/s | rejected | 2026-10-05 | [rejected-ideas](rejected-ideas/) |
| Level Zero v1 adapter | DeepSeek V4 Flash | 19.2 -> 16.0 | rejected | 2026-10-03 | [rejected-ideas](rejected-ideas/) |
| `-sm tensor` on the EPYC host (2 cards) | gpt-oss-120b | ~58 -> 28.7 vs Ryzen host | rejected | 2026-09-30 | [gpt-oss](gpt-oss/) |
