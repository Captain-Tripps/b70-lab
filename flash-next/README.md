# Qwen3.8-Flash-Next on 4x B70

Qwen3.8-Flash-Next (llama.cpp arch `qwen4exp`): 180B MoE (512 experts, 10 per token; 179,999,981,459 parameters
by the Hugging Face safetensors count, including its n-gram embedding tables), hidden size 2560, 48 layers, Gated
DeltaNet + Qwen Sparse Attention layers, 262k native context, MTP head.
This is my daily-driver model.

- Model file: Unsloth `Qwen3.8-Flash-Next-GGUF`, `UD-Q4_K_XL` (4 shards, 111.3 GB) + `mmproj-F16.gguf` for vision.
  K-quants chosen over IQ4_XS because the SYCL backend has reordered (fast) kernels for K-quants.
- Status: **retired 2026-11-06** (was live on fork runtime `r62`). The daily driver is now Strata on two cards, which is
  faster at a smaller quant: see [../strata-windows-port/](../strata-windows-port/) for the full recipe. The llama.cpp
  numbers below stay as the reference.

## Current setup (live)

Main flags of the live entry (reconstructed from my notes; check `llama-server --help` on your build, MTP flag names
have changed between llama.cpp versions):

```
llama-server -m <Qwen3.8-Flash-Next UD-Q4_K_XL shard 1> --mmproj <mmproj-F16.gguf>
  -ngl 99 -ts 10,13,13,13 -c 131072 -np 1 -ub 1024 -b 8192 -fa on --jinja --load-mode dio
  --spec-type draft-mtp --spec-draft-model <mtp-Qwen3.8-Flash-Next-shared-Q8_0.gguf> --spec-draft-ngl 99
  --spec-draft-n-max 4 --spec-draft-p-min 0.1 --reasoning-budget 4000
env: ONEAPI_DEVICE_SELECTOR=level_zero:0,1,2,3  GGML_SYCL_ENABLE_DNN=0  GGML_SYCL_MMID_FUSED_MAX_TOKENS=8
     GGML_SYCL_PIPELINE=1  GGML_SYCL_PIPELINE_MAX_QUEUED=4  GGML_SYCL_IDLE_HEARTBEAT_SEC=30
```

`-ts 10,13,13,13` leaves room on card 0 for the vision projector and the MTP draft (Q8_0, 2.6 GB). The fork-only
switches are explained in [../llama.cpp-sycl/](../llama.cpp-sycl/). `GGML_SYCL_MMID_FUSED_MAX_TOKENS=8` lets the 2-8
token MTP verify batches take the device-only fused MoE path; without it MTP was not worth using.

Where the weights are (main GGUF 103.7 GB): routed experts Q4_K 41.3 GB (gate/up) and Q5_1 25.2 GB (down), Q8_0 4.15 GB
(down on 5 layers); IQ4_NL 26.8 GB is the token embedding (not read per token); dense Q8_0 ~4.2 GB.

## Decode history

4x B70, EPYC host, `UD-Q4_K_XL`, 131k context, 7-prompt A/B harness (28-42 samples per arm, MTP drafting on).

| Runtime | Change | Decode tok/s |
|---|---|---|
| r52 | starting point (MTP n 3 / p-min 0.5) | 49.2 |
| r52 | MTP n-max 4 / p-min 0.1 (args only) | +6.6% over n 3 in the same session |
| r53 | F32 mat-vec for 2-8 columns (MTP verify shapes) | 54.4 (+10.5%) |
| r56 | Q8_0 MoE expert reorder (5 `ffn_down_exps` layers are Q8_0) | 58.3 (+4.9%) |
| r62 | top-k MoE single work-group, small fusions, conv-snapshot fusion | ~61 (+4.3%) |

Same-harness numbers for the abliterated variant of the same model: 45.9 (old runtime, n 3) -> 60.3 (r62, n 4 / p 0.1).

Perplexity checks along the way: r52 4.6521, r53 4.6421 (+-0.30), r56 (ub 4) 4.6408; r59-r62 outputs bit-identical.
Fiction prompts gain less from r53 (-5% on one fiction prompt) and more from r56 (+12%); check your own mix.

## Prompt read and long context

| Change | Measured |
|---|---|
| `GGML_SYCL_ENABLE_DNN=0` | prompt 204-211 / 300-313 -> 249 / 365 tok/s (+18-20%), 4 cards, runtime b70dsv4 (2026-10-01), 5k and 17k prompts |
| `-ub 1024` (vs 512) | +25-40%; `-ub 2048` slower |
| QSA indexer gather + mean-pool fusion (r4) | decode at 58k depth 18.6 -> 22.8 tok/s |
| Cross-card pipeline (r52, `-b 8192`) | 50k-token prompt 487 -> ~770 tok/s, 87k ~685; decode unchanged |
| Driver 8805 -> 8976 (2026-10-11) | prompt reads ~1.6-2.4x on the pipeline runtimes; peak GPU power ~2x |

Depth still costs decode: each QSA layer attends densely over all cached cells with a mask (~6 us per 1k cells per
layer at 49k). Upstream's sparse flash attention (`GGML_SYCL_SPARSE_FA=1`) does not help this model: -6% at 6k
context, 0 at 50k.

## Comparisons

Same 7-prompt set (`bench/sbench.py`), temperature 0, thinking off, 2026-10-16:

| Setup | Answers | Decode | Prompt read | Decode after long prompt |
|---|---|---|---|---|
| llama.cpp r62, 4 cards, UD-Q4_K_XL | correct | 60.6 | 748 tok/s @ 33.6k | 28.6 |
| Strata (Windows port), 2 cards, IQ3_S, int8 KV, JIT build, 1 x 200k | correct | 97.6 | 1,415 tok/s @ 33.6k | 64.9 |
| Strata, IQ3_XXS, 2 x 200k (superseded) | correct | 108.2 | 599 tok/s @ 33.6k | 58.7 |
| Strata, same, fp16 KV, 32k (superseded) | correct | 67.4 | 570 tok/s @ 26.8k | 46.4 |

See [../strata-windows-port/](../strata-windows-port/). Note the Strata run uses a smaller quant and half the cards.

Three-model side by side on 11 real tasks (2026-10-14, my own task set): Flash-Next 11/11 at ~70 tok/s decode and
~600 tok/s on a ~100k prompt; DeepSeek V4 Flash 10/11, ~30, ~450; GLM-5.3 (reasoning effort max) 9/11, ~27, ~160.
The misses were token-budget exhaustion, not wrong answers.

## Things to know

- Flash-Next can think for a very long time (one request produced 80k reasoning tokens). `--reasoning-budget 4000`
  on the server caps it; per request, `reasoning_budget_tokens` or `chat_template_kwargs.enable_thinking=false`.
- Two slots (`-np 2`, 2 x 262k) fit on 4 cards but gave no throughput gain (two streams of ~11.5 tok/s instead of one
  of ~23) and later failed with device OOM on the first request. One slot at 131k is what runs now.
- 3 vs 4 cards: same single-stream decode speed with layer split (only one card works at a time without the pipeline).
- Draft settings: n-max 6 and p-min 0.7 were worse. A single-prompt "+17%" for p-min 0.1-0.3 at 2k context did not
  replicate at 20k; trust a varied prompt set.
