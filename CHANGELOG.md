# Changelog

Dated entries, newest first. Results go into [STATUS.md](STATUS.md) and the topic folder; this file records what
changed and when.

## 2026-10-21
- Tested upstream PR #30956 (fast 2-device `-sm tensor` exchange) on r67c: correct on Windows Level Zero (ub-4
  perplexity bit-identical); Mistral-Small-24B tensor split prompt read +14%, decode +2%; gpt-oss-120b tensor prompt
  +5%, decode equal (3-card layer split still ~2x faster). Found: `GGML_SYCL_PIPELINE=1` + `-sm tensor` makes gpt-oss
  emit garbage (not the PR). [llama.cpp-sycl/PR30956-2026-10-21.md](llama.cpp-sycl/PR30956-2026-10-21.md).

## 2026-10-18
- r67c also live for DeepSeek V4 (no draft; DSpark + lookup), Qwen3.8-27B Q8_0 and Q6_K, and Flash-Next MTP + lookup;
  answer checks pass on every switched entry. Only GLM-5.3 and the plain Flash-Next MTP entry stay on older runtimes.
- r67c switched live for DeepSeek V4 Flash DSpark and gpt-oss-120b (smoke: 20.7k-token prompt read at 651 tok/s,
  answers correct). GLM-5.3 and the Flash-Next llama.cpp entry stay on their old runtimes (neutral).

## 2026-10-17
- llama.cpp fork rebased onto upstream master of 2026-10-17 (r67c, staged): DeepSeek V4 prompt read +36% at 33.6k and
  decode +5%, gpt-oss-120b decode +7%, GLM-5.3 and Flash-Next neutral; answers correct and perplexity equal on all
  four. Upstream's Q5_K kernel and Flash-Next MTP head replace the fork's; two local fixes let the MTP head load from
  a shared-weights draft file ([notes](llama.cpp-sycl/REBASE-2026-10-17.md)).
- Strata Windows patch set complete (0001-0004; 0004 = optional timer-resolution switch, no measured effect); a
  how-to-run recipe (JIT build, config essentials, CPU vision encoder, llama-swap entry) in strata-windows-port/.
  Current best for Flash-Next recorded at the top of STATUS.md.
- Strata 2 slots x 112k vs 1 x 200k: +17% aggregate with two concurrent streams, but -37% prompt read and 88k less
  context; 1 x 200k stays the default.
- Strata slow starts (~70 instead of ~98 tok/s) traced to `--ple-io direct`: unbuffered SSD reads of the 27 GB PLE
  table every token, slowed by drive latency after ~130 GB of writes. `--ple-io mmap` restores ~99 tok/s; the
  published best config now uses it. MTP draft sweep: upstream defaults (`--spec 4`, p-min 0) stay.
- DeepSeek Track A step A0: expert matmuls are 14% / 22% of decode op time, ceiling 1.12x plain / 1.19x DSpark;
  expert-only parallelism rejected. Track B (V4.1) stands.
- Strata 2-hour soak through llama-swap (IQ3_S, 1 x 200k, vision on): 134 cycles, 0 errors, 0 restarts, answers and
  vision 134/134, decode 93.0 tok/s median with no drift, 112k-token prompt at ~1,430 tok/s.
- DeepSeek plan updated: Track A = expert parallelism for V4 Flash 0731 in the llama.cpp fork (go / no-go after a
  1-hour profile); Track B = DeepSeek V4.1 Flash 1017 (released today, new ~510B architecture, not in llama.cpp yet),
  watching for support ([plan](deepseek-v4/PLAN-expert-parallel.md)).
- Quant quality: GSQ-RCO IQ3_S perplexity +1.0% / mean KLD 0.131 / same top token 88.4% vs IQ3_XXS +3.5% / 0.211 /
  85.3% (reference UD-Q4_K_XL).
- New best Strata setup: IQ3_S, 2 cards, 1 x 200k, int8 KV, prefill chunk 8192, JIT: decode 97.6 tok/s (+61% vs
  llama.cpp on 4 cards), prompt read 1,415 tok/s at 33.6k (1.9x), decode after it 64.9 (2.3x). IQ3_XXS superseded.
- Strata prompt chunk sweep (IQ3_S, 1 x 200k): 8192 kept (1,417 tok/s at 33.6k; 112k-token prompt at 1,433 tok/s,
  decode after 72.2); 10240 sits at card 1's memory limit and runs ~3x slower; 12288 does not fit.
- `STRATA_NIGHT_PREFILL_GROUPED` must be 0 for IQ3_S (unsupported type); prompt chunk 4k -> 8k: 881 -> 1,415 tok/s.

## 2026-10-16 (late)
- Parked plan added: Strata-style expert parallelism for DeepSeek V4 Flash ([plan](deepseek-v4/PLAN-expert-parallel.md)).
- Strata int8 KV bug on Windows solved: oneAPI 2026.0's AOT build (`ocloc`, `bmg-g31`) miscompiles the batched
  decode attention over int8 KV; the same sources JIT-compiled by the driver pass parity bitwise. Patch 0003 adds a
  JIT build switch. Strata 2 cards, int8 KV, 200k x 2 slots: 108.2 tok/s vs llama.cpp r62 on 4 cards 60.6 (+79%),
  answers correct. The earlier 96.6 tok/s AOT number was invalid; the fp16-KV result is superseded.

## 2026-10-16
- Repo created from the existing notes, patches and reproducers.
- Strata engine ported to native Windows (patches 0001 / 0002). 2 cards, fp16 KV: answers correct, 67.4 tok/s vs
  llama.cpp r62 on 4 cards 60.6. int8 KV gives wrong answers on Windows (open bug). Level Zero on Windows: no IPC and
  no peer access between B70s; host USM in one shared context works.

## 2026-10-15
- Expert-overlap study (Flash-Next 42%, GLM 30%, DeepSeek V4 32% redundant expert assignments in a verify window).
  Grouped expert verification kernel: -5 to -10%, rejected.
- Client-side prompt-cache priming for long shared prefixes on recurrent-state models: ~154 s -> ~64 s of prompt
  work on a 5-request job.

## 2026-10-14
- GLM-5.3-Flash Maya-M live on the SYCL fork (g10): 16.5 -> 24-25 tok/s, 128k context with one expert layer in
  system RAM, MTP n4 / p0.75, reasoning effort high + 8k budget.

## 2026-10-12
- Flash-Next on r62 (top-k MoE single work-group, small fusions): ~61 tok/s. Q8_0 MoE reorder (r56) +4.9%.
  Qwen3.8-27B Q6_K / Q5_K wide dot (r64-r66).
- SYCL graph replay retried with an FA skip: runs, ~3x slower. Rejected.

## 2026-10-11
- r53 (F32 mat-vec for 2-8 columns): Flash-Next +10.5%. MTP n4 / p0.1 adopted.
- GPU driver 32.0.101.8805 -> 32.0.101.8976: prompt reads ~1.6-2.4x on the pipeline runtimes. Level Zero deadlock
  still reproduces.
- `set_tensor_2d` submitted upstream ([#30358](https://github.com/ggml-org/llama.cpp/pull/30358)).

## 2026-10-10
- MXFP4 SWAR decode + MoE reorder merged upstream ([#29809](https://github.com/ggml-org/llama.cpp/pull/29809)).
- Level Zero multi-thread submit deadlock reproduced in a standalone program.

## 2026-10-06
- Cross-card pipeline (r52, bounded queues) live for DeepSeek V4, Flash-Next and gpt-oss-120b: prompt reads ~1.6-2.3x.

## 2026-10-05
- DeepSeek V4 deep context: sparse FA fixed (memset ordering) + oneMKL indexer (r27).

## 2026-10-03
- Local-memory IQ2_XS / IQ3_XXS MoE kernel for DeepSeek V4: DSpark 18.5 -> 24.2 tok/s. Routing fusion +2%.

## 2026-10-01
- Idle VRAM eviction found and fixed with a GPU heartbeat. `GGML_SYCL_ENABLE_DNN=0` for prompt reads. QSA pool
  fusion for Flash-Next at depth (+23%).

## 2026-09-30
- Machine moved to 4x B70 and an EPYC 7402P host. Pinned `-sm tensor` all-reduce merged upstream
  ([#29604](https://github.com/ggml-org/llama.cpp/pull/29604)).

## 2026-09-27
- First B70 tuning on 2 cards: Q8_0 16-byte loads, flash-attention split 48, MXFP4 reorder, GLU and ADD+RMS fusions.
