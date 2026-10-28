# Changelog

Dated entries, newest first. Results go into [STATUS.md](STATUS.md) and the topic folder; this file records what
changed and when.

## 2026-10-28
- DeepSeek V4.1 Flash 1017 on the llama.cpp SYCL fork: first real numbers. Best 2.46 tok/s decode / 12.7 prompt read
  (`-ncmoe 24 -t 46` plus one `EmptyWorkingSet` after load); CPU-only 1.65, so the CPU expert layers are the
  bottleneck. [mirror-probe](work/strata-v41-agent-runner/mirror-probe/README.md).
- Found why Windows holds ~1 GB of host RAM per GB on the GPUs: llama.cpp's Windows `unmap_fragment()` is a no-op;
  the driver only reserves commit (standalone Level Zero probe). RAM watchdog made commit-aware.
- Strata `--adapt-every 0`: +49% in CLI `generate` (v0.2.7) but served decode on the lab build drops 99-104 -> 38-40;
  served config unchanged. RemoteExperts spin/host-metadata patch: no gain.
  [STRATA-ADAPT-TIER](work/strata-v41-agent-runner/STRATA-ADAPT-TIER.md).

## 2026-10-26
- Added STEP-000 to qualify DeepSeek V4.1 Flash 1017 through OpenRouter/OpenClaw with a native Windows runner,
  CPU-only lifecycle mocks and session resume. Added a copyable [agent starter prompt](deepseek-v4/strata-v41/OPENCLAW-START.md).
  Coding inference is remote; no coding-model swapping is required. Integration and hardware checks remain NOT_RUN.
- Added the [Strata DeepSeek V4.1 four-B70 Windows action plan](deepseek-v4/strata-v41/PLAN.md) with pinned upstream/lab
  evidence, source-backed decisions, ordered work packages and acceptance gates. It reuses the existing Windows
  port and records known driver/compilation failures; no GPU tests or performance measurements were run.
- Superseded the old Track B wait-for-llama.cpp prerequisite for this Strata route, retained the V4 0731
  expert-parallel rejection, and made current RAM/hardware reconciliation the first gate. Historical hardware
  entries and production configurations are unchanged.

## 2026-10-25
- Review notes on @92es's startup-selected barrier exchange: the context check alone would select the barrier path on
  Windows and crash on the default L0 v2 adapter; the trailing upload waits are needed with one staging pair (safe to
  drop with two); `nsm` undercounts Xe2 cores (arch-aware fix + re-measure); the oneDNN probe is fine on B70.
  [TENSOR-SPLIT-DECODE.md](llama.cpp-sycl/TENSOR-SPLIT-DECODE.md#review-notes-on-the-startup-selected-barrier-exchange-2026-10-25).

## 2026-10-24
- Queue-barrier exchange on Windows, cause found: the two devices already share one SYCL context; the abort comes from
  the Level Zero v2 UR adapter, and the legacy adapter (`SYCL_UR_USE_LEVEL_ZERO_V2=0`) runs it (standalone test).
  **Corrects** an earlier entry today that blamed separate contexts / `SYCL_ENABLE_DEFAULT_CONTEXTS` being off on
  Windows. No speed numbers yet.
  [TENSOR-SPLIT-DECODE.md](llama.cpp-sycl/TENSOR-SPLIT-DECODE.md#shared-context-attempt-windows-2026-10-24).
- @92es (Linux): `SYCL_ENABLE_DEFAULT_CONTEXTS` flips shared vs separate contexts there; KL divergence of the barrier
  patch vs stock identical at ub 4, within noise at ub 512.

## 2026-10-23
- Graph cache validated in llama-server and switched live for the 2-card dense models: Mistral-24B decode +45%,
  Qwen3.8-27B Q8 / Q6 +18-21% (now tensor split instead of layer), PPL ub4 bit-exact. Record-size gate must be 512
  (8 loses most of the gain; recording large batches crashes on the oneMKL flash-attention path).
- New SYCL get_tensor_2d removes 10-35 s slot-save stalls in tensor split (slot save at ~15k tokens 35 s -> 1.1 s).
- Cache + per-card launch threads rejected for serving (1 exit + 1 hang in 6 runs).
- Long-form generation workload: Qwen3.8-27B Q6 1 card -> 2-card tensor + cache, decode +26-41%, wall -24%. The
  paired Gemma 4 26B-A4B moved to the rebased runtime on its single card: decode +30-40%.
  [TENSOR-SPLIT-DECODE.md](llama.cpp-sycl/TENSOR-SPLIT-DECODE.md).
- Community results from @92es (Linux, single SYCL context): the queue-barrier exchange runs there, ub-4 PPL
  identical to stock, +15% at ub 512. Retested the exact peer-only wiring on Windows: still aborts (separate
  contexts per device).

## 2026-10-22
- Mistral-Small-3.2-24B (the only 2-card tensor-split entry) switched live to r67c + PR #30956.
  [PR30956-2026-10-21.md](llama.cpp-sycl/PR30956-2026-10-21.md).
- Qwen3.8-27B 2-card `-sm tensor` + PR #30956 vs layer split (MTP, A/B/B/A): prompt read equal, decode -18%; both
  entries stay on layer split. [PR30956-qwen27-2026-10-22.md](llama.cpp-sycl/PR30956-qwen27-2026-10-22.md).
- New working page on the tensor-split decode gap: llama-bench by batch size shows tensor split 19-33% slower than
  layer at 1-8 tokens with or without #30956 (the PR only helps pp512); ~40 ms per forward lost to the split vs an
  ideal ~28 ms. Theory (host waits per all-reduce), candidate fixes and an MTP A/B method.
  [TENSOR-SPLIT-DECODE.md](llama.cpp-sycl/TENSOR-SPLIT-DECODE.md).
- Timers: the tensor-split decode gap is single-thread kernel launch (41.5 ms per forward), not the exchange waits;
  exchange fixes cap at layer parity. A per-subgraph SYCL graph cache (prototype, env-gated) removes ~30 ms of it:
  2-card tensor split pp1 / pp5 / tg +35% / +32% / +30% over layer on Qwen3.8-27B, ub-4 perplexity bit-identical.
  Stock graph mode crashes in the Level Zero driver. Server and MoE tests pending.
- Per-card launch threads now run with `UR_L0_V2_DISABLE_ZE_LAUNCH_KERNEL_WITH_ARGS=1` (avoids the Level Zero
  two-thread launch deadlock). On top of the graph cache: pp1 +40-42%, pp5 +35-37%, pp512 +31%, tg +38% over layer
  split; ub-4 perplexity bit-identical, four bench loops clean. Without the cache: one oneMKL crash in four loops.

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
