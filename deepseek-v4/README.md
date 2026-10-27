# DeepSeek V4 Flash on 4x B70

DeepSeek-V4-Flash-0731 (llama.cpp arch `deepseek4`): 284B MoE, ~13B active, 43 layers, 256 routed experts (6 per
token), compressed sparse attention + "lightning indexer", 1M training context.

- Model file: Unsloth `DeepSeek-V4-Flash-0731-GGUF`, `UD-Q2_K_XL` (3 shards, 90.2 GiB). Despite the name, the routed
  experts are **IQ2_XS (gate/up) and IQ3_XXS (down)** plus some MXFP4, not K-quants. Every Unsloth sub-Q4 quant of this
  model has IQ gate/up experts.
- Draft model: `dspark-DeepSeek-V4-Flash-0731-Q8_0.gguf` (10.9 GB) from the same repo, for DSpark speculative decoding.
- Status: **live** on fork runtime `r52`, 131k context with DSpark.
- Next for **V4.1 Flash 1017**: [native Windows Strata port action plan](strata-v41/PLAN.md), added 2026-10-26;
  planning only, no V4.1 Intel measurements yet. The older V4 0731 expert-only parallelism proposal was
  **rejected after profiling**; its evidence remains in [PLAN-expert-parallel.md](PLAN-expert-parallel.md).

Main flags (reconstructed from my notes; the fork-only switches are explained in [../llama.cpp-sycl/](../llama.cpp-sycl/)):

```
llama-server -m <DeepSeek-V4-Flash-0731-UD-Q2_K_XL-00001-of-00003.gguf> -sm layer -np 1 -c 131072 -t 16
  -b 8192 -ub 1024 -fa on --jinja --load-mode dio -fit off -ngl 99 -ts 11,11,11,11
  --spec-type draft-dspark --spec-draft-model <dspark-...-Q8_0.gguf> --spec-draft-n-max 3 --spec-draft-p-min 0.5
  --spec-draft-ngl 99 --spec-draft-device SYCL2,SYCL1,SYCL0,SYCL3
env: GGML_SYCL_ENABLE_DNN=0  GGML_SYCL_MMID_FUSED_MAX_TOKENS=8  GGML_SYCL_MMID_SMALL_FUSED=1
     GGML_SYCL_MMID_SMALL_MAX_ROWS=8  GGML_SYCL_MKL_FA_SINKS=1  GGML_SYCL_MKL_FA_Q_TILE=2048  GGML_SYCL_SPARSE_FA=1
     GGML_SYCL_PIPELINE=1  GGML_SYCL_PIPELINE_MAX_QUEUED=4  GGML_SYCL_IDLE_HEARTBEAT_SEC=30
```

Placement is pinned (`-fit off -ts 11,11,11,11` plus an explicit draft device order): with automatic fitting the
draft's layers were split by free memory with boundaries within 1%, and ~100 MB of desktop GPU use could put two
draft layers on one card (31.5 GB) and drop prompt reads to 20-30 tok/s.

## 1. The routed-expert kernel (the main finding)

`test-backend-ops perf -o MUL_MAT_ID` on ONE card, 256 experts, top-6, random ids, 1 token. GB/s = bytes of the 6
selected experts at nominal bits per weight / time.

| Expert weight type (layout) | us / call | ~GB/s |
|---|---|---|
| MXFP4 (reordered) | 54.7 | 489 |
| Q4_K (reordered) | 70.6 | 400 |
| IQ4_XS (plain) | 77.1 | 346 |
| Q2_K (plain) | 96.8 | 170 |
| IQ3_S (plain) | 131.9 | 164 |
| Q8_0 (plain) | 420.1 | 127 |
| IQ3_XXS (plain) | 152-157 | 126 |
| IQ2_XS (plain) | 118-120 | 121 |

The generic kernel launches one 16-thread work-group per output row, cost grew linearly with tokens (no weight
sharing), and the 2-byte-aligned block types (IQ2_XS 74 B, IQ3_XXS 98 B, Q8_0 34 B) were slow even without a lookup
table.

New kernel (`fork/deepseek-moe/` in [../llama.cpp-sycl/](../llama.cpp-sycl/)): one work-group covers 8 sub-groups x R
rows of one (token, expert); rows are staged into local memory with 16-byte loads; codebooks and the entry's q8_1
activations live in local memory; v3 builds sign masks arithmetically and reads index bytes as 16-bit words.

| us / call | down IQ3_XXS 1 tok / 4 tok | gate/up IQ2_XS 1 tok / 4 tok |
|---|---|---|
| generic | 152-157 / 764-771 | 118-120 / 650-654 |
| v2, tile 8x2 | 78.3 / 324 | 74.4 / 302.5 |
| v3, best tile | 69.6 / 292 | 68.3 / 284 |

About 2.0x (down) and 1.6-1.7x (gate/up) at one token, ~2.2-2.3x at four. It is now limited by local-memory loads in
the dot products, not by DRAM. Correctness: 97/97 IQ2_XS + IQ3_XXS MUL_MAT_ID cases against the CPU backend
(78 added), greedy text and top-3 logprobs identical to 5 decimals.

## 2. End to end

4 cards, 131k context, layer split, 3,513-token ("long") / 19-token ("short") prompts, 256 generated tokens,
driver 8805.

| Runtime | Plain decode | DSpark n 3, p-min 0.5 |
|---|---|---|
| generic MoE kernels (r7) | 16.7 / 18.0 | 18.5 / 19.3 |
| + local-memory IQ kernel v2 (r9) | 18.5 / 18.7 | **24.2 / 23.9** |
| + v3 kernel + routing fusion (r17) | 19.1-19.5 | 24.3-24.9 |

Before the IQ kernel, DSpark gave no gain: a 4-token verify step cost ~3.4x a single step. Draft acceptance 73-88%
depending on depth (n 1: 88%, n 4: 73%). DSpark depth 4-5 no better than 3; p-min 0.7 worse.

Earlier steps on the way (runtime b70dsv4 / r2, preview model, driver 8805): wide-row F32 mat-vec +10% decode
(12.98 / 13.48 -> 14.3 / 14.9); per-slice Q8_0 reorder for the 3-D `attn_output_a` matmul +12% (16.3 / 17.25);
`GGML_SYCL_ENABLE_DNN=0` prompt +4-9%.

## 3. Deep context (r27)

Decode and prompt speed fell with depth (r17 plain decode 19.3 tok/s at 7k -> 13.75 at 59k; prompt 205 -> 99 tok/s)
because the compressed-attention layers attended over all compressed rows (ctx/4) though only 640 are unmasked, and
the indexer scored every compressed row one by one.

Fixes (r27): sparse flash attention works (incl. verify batches up to 8 tokens) and indexer scores go through a oneMKL
GEMM. Same session: plain decode at 59k +22%; DSpark decode at 59k 16.8 -> 21-24 tok/s; prompt read +29% at 7k,
+96% at 59k; shallow decode unchanged.

The old sparse-FA "device lost" crash was a `queue::memset` that was not ordered against the following kernels on
this stack. Reset buffers with a kernel or wait first; oneMKL calls also needed explicit waits around them.

## 4. Cross-card pipeline (r52)

Layer split runs one card at a time. With the pipeline (`GGML_SYCL_PIPELINE=1`, `-b 8192`), 4 cards, driver 8805:

| Prompt | DSpark entry | Plain entry |
|---|---|---|
| 59k tokens | 236 -> 446 tok/s | -> 531 |
| 102k tokens | 211 -> 406 | -> 482 |

Decode unchanged, perplexity equal on/off. Soaks clean (88 min). The plain (no-draft) entry needed bounded queues
(`GGML_SYCL_PIPELINE_MAX_QUEUED=4`): without them the host queued work without limit and ran out of memory on a 102k
prompt. Test both draft and no-draft configs; they behave differently. Driver 8976 (2026-10-11) raised prompt reads
further (~1.6-2.4x across models).

## 5. Routing fusion

The routing chain (softplus, sqrt, +bias, argsort, view, get_rows, sum_rows, clamp, div, scale) fused into one kernel
on the 40 learned-routing layers: 4,202 -> 3,862 launches per decode step; expert ids identical in 516/516 samples;
perplexity 6.4661 (off) vs 6.4620 (on), 16 x 512 tokens; plain decode +2%, DSpark no change. A launch costs about
3 us here; launch count is not the bottleneck.

## 6. N-gram lookup in front of DSpark

A `ngram-mod,draft-dspark` chain was 4-7x faster than plain decode on exact-copy tasks, but on a real long-document
checking workload it was slower (19-23 tok/s, 30-41% of drafts accepted) than DSpark alone (27-30 tok/s, 88-96%).
Synthetic copy tests do not predict real use. A back-off rule recovered most of the loss but was not shipped
([../rejected-ideas/](../rejected-ideas/)).

## Memory

With the draft, the fullest card is 30.3 GB at 131k. 196k and 262k crash at warmup; `-ts 11,10,9,10` at 262k spilled
to shared memory. 131k is the practical ceiling with DSpark on 4x 32 GB. Without a draft, the full 1M context fit
(fullest card 30.2 GB at ub 512; preview model on an early runtime).

## Caveats

One quant (UD-Q2_K_XL), one machine, Windows. DSpark output differs from plain greedy decode after ~20-55 characters
on 3 of 4 test prompts (batched-verify rounding), identically with old and new kernels; outputs stayed coherent.
