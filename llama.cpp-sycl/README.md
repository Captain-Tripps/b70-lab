# llama.cpp SYCL backend changes

Changes to llama.cpp's SYCL backend (`ggml/src/ggml-sycl/`) made while tuning the B70 machine described in the
[top-level README](../README.md). Three groups:

1. **Upstream**: merged into llama.cpp or in review there. Use upstream, not the files here.
2. **Upstream candidates** (`upstream-candidates/`): clean patches against a pinned upstream commit, not submitted.
3. **Fork** (`fork/`): changes in a local fork, which is an upstream master snapshot (`66041e`, end of September
   2026) plus everything below. These do **not** apply to a fresh clone without porting work. They are here so
   people can read the kernels and the reasoning, and port what they need.

2026-10-17: the fork was rebased onto upstream master `797de63b2`; what changed and the per-model validation are in
[REBASE-2026-10-17.md](REBASE-2026-10-17.md). The patch files here still target the older base.

All patches: prepared with AI assistance; derived from llama.cpp (MIT, notice in
[../LICENSES/llama.cpp-LICENSE](../LICENSES/llama.cpp-LICENSE)).

## 1. Upstream

These changes were submitted to upstream llama.cpp as the PRs below (by this repo's owner); use upstream rather
than anything here. Numbers are from this test machine unless noted.

| Change | What | Measured | Upstream status (2026-10-16) |
|---|---|---|---|
| [ggml-org/llama.cpp#29604](https://github.com/ggml-org/llama.cpp/pull/29604): `-sm tensor` all-reduce | persistent pinned host buffers, async copies, one host wait (was: fresh pageable buffers, blocking copies) | 2x B70 (earlier Ryzen host), Qwen3.8-27B Q8_0: tensor-split prompt +37-45%, decode 18.2 -> 20.2 tok/s, perplexity equal. An upstream reviewer on 2x A770, Llama-2-7B: prompt 157 -> 1018, decode 30.9 -> 45.7 | merged 2026-09-30 |
| [ggml-org/llama.cpp#29809](https://github.com/ggml-org/llama.cpp/pull/29809): MXFP4 | SWAR decode of E2M1 nibbles + reordered MoE expert layout (MXFP4 had no reorder "extra", so the reorder path never ran) | EPYC host, gpt-oss-20b decode 55.8 -> 106.6 tok/s, gpt-oss-120b 33.3 -> 67.1; with the multi-token reorder fix: prompt +20-27%, op tests and perplexity equal to master | merged 2026-10-10 |
| [ggml-org/llama.cpp#30358](https://github.com/ggml-org/llama.cpp/pull/30358): `set_tensor_2d` for SYCL buffers | the meta backend's per-row uploads fell back to one blocking copy per row | 2x B70, gpt-oss-120b `-sm tensor` load ~265 s -> ~115 s, perplexity equal, 26.8M rows read back with 0 mismatches | open (in review) |

## 2. Upstream candidates (`upstream-candidates/`, base: master `4da6337`, 2026-09-27)

Measured on 2x B70 with the earlier Ryzen host, Qwen3.8-27B Q8_0, `-sm layer`, q4_0 KV, flash attention on,
`llama-bench` decode at short / 32k context.

| Patch | What | Measured | Notes |
|---|---|---|---|
| `0005` 16-byte loads in the reordered Q8_0 MMVQ | `sycl::int4` loads instead of 8x uint16 in the Q8_0 reorder dot | op perf n=1 120.9 -> 109.2 us (~94% of peak bandwidth), n=8 -19%; model decode 15.42 -> 17.47 short, 11.18 -> 12.97 at 32k | Mostly superseded upstream by #29186 (Q8_0 ESIMD / wide loads, not my work) |
| `0006` fuse Q8_0 FFN gate/up mat-vec with GLU | lets the existing Q4_K-only gate+up+GLU fusion take Q8_0 pairs | -128 launches per token; decode 17.24 -> 17.53 | perplexity at ub 8: 3.8887 vs 3.8802 unfused (small, deterministic, not explained) |
| `0007` fuse residual ADD -> RMS_NORM -> MUL | one kernel for the residual add + norm, keeps the ADD output | -127 launches; decode 17.64, prompt 961 -> 974 | perplexity bit-identical |
| `0008` raise the TILE flash-attention decode split | B70 decode with deep context: parallel blocks at least 48 | Qwen3.8-27B decode +4.5% at 28k, +5.5% at 32k, +6.2% at 40k; Mistral-Small-3.2 +17% at 32k | Marked RFC. Root cause: `nsm = max_compute_units / 16` assumes 16 EUs per Xe core; Xe2 has 8. Fixing only that makes the heuristic pick 32, which is slower. **2026-11-07:** the `/ 8` fix alone gets most of this gain (Mistral +16.6% vs +18.4% at 32k, Qwen +4.6% vs +5.4%), so the floor can go once `/ 8` is upstream; see [NSM-AND-DNNL-PROBE-2026-11-07.md](NSM-AND-DNNL-PROBE-2026-11-07.md) |

## 3. Fork (`fork/`)

Fork runtimes are numbered (`r4`, `r9`, `r27`, `r52`, `r62`, ...); each is the previous one plus the listed change.
Every change has an environment switch to turn it off, so A/B runs use one binary.

| Folder / file | What | Measured | Shipped in | Off switch |
|---|---|---|---|---|
| `misc/patch_f32mmv.py` | dedicated F32 mat-vec kernel (Flash-Next's and DeepSeek V4's small F32 matmuls otherwise take a slow generic path) | Flash-Next (b11190 base, 3 cards) decode 22 -> 25 tok/s (+14%). A later wide-row version (rows split across a 16-sub-group work-group, in the fork only): DeepSeek V4 `hc_*_fn` matmuls 100-114 -> 22-37 us, decode +10% | b70f32, r2 | `GGML_SYCL_DISABLE_F32_MMV=1` |
| `flash-next/r52-to-r53-f32-wide-n.diff` | same kernel for 2-8 columns (MTP verify batches) and few-row / long-K shapes | Flash-Next 49.2 -> 54.4 tok/s (+10.5%), perplexity 4.6521 -> 4.6421 | r53 | `GGML_SYCL_F32_MMV_WIDE_N=0` |
| `flash-next/r53-to-r56-q8_0-moe-reorder.diff` | Q8_0 MoE experts get the reordered layout (Flash-Next's Q8_0 `ffn_down_exps`) | 55.6 -> 58.3 tok/s (+4.9%) | r56 | `GGML_SYCL_MMID_Q8_0_REORDER=0` |
| `flash-next/r56-to-r62-fusions-and-graph-dump.diff` | top-k MoE in one work-group, three small fusions, conv-snapshot fusion, graph dump tool (`GGML_SYCL_DUMP_GRAPH`) | +2.5%, +0.8%, +2.3%; r62 ~+4.3% over r56; outputs bit-identical to r59 | r59-r62 | `GGML_SYCL_DISABLE_HC_POST_GATE`, `_SSM_GATE_FUSION`, `_SHEXP_GATE_FUSION`, `_MOE_SUM_FUSION`, `_CONV_SNAP_FUSION` (all `GGML_SYCL_DISABLE_...=1`) |
| `flash-next/patch_qsa_pool.py` | fused gather + mean-pool for Qwen Sparse Attention's indexer keys | Flash-Next decode at 58k depth 18.6 -> 22.8 tok/s; batch-1 perplexity bit-identical | r4 | `GGML_SYCL_DISABLE_QSA_POOL_FUSION=1` |
| `deepseek-moe/01..04` | local-memory MUL_MAT_ID kernel for IQ2_XS / IQ3_XXS experts (v2, then v3), DeepSeek V4 routing fusion, extra op tests | see [../deepseek-v4/](../deepseek-v4/): expert matmul 1.6-2.3x faster, DSpark decode 18.5 -> 24 tok/s | r9, r17 | `GGML_SYCL_MOE_IQ_SLM=0`, `GGML_SYCL_DISABLE_DSV4_ROUTE_FUSION=1`; the kernel also falls back by itself when shapes do not fit |
| `deepseek-sparse/fattn-sparse.patch`, `lightning-indexer.patch` | sparse flash attention made usable (fixed device-lost crash; verify batches up to 8 tokens) + indexer scores through oneMKL GEMM | DeepSeek V4 at 59k: plain decode +22%, DSpark 16.8 -> 21-24 tok/s; prompt read +29% at 7k, +96% at 59k | r27 | `GGML_SYCL_SPARSE_FA=1` to enable; `GGML_SYCL_LID_GEMM=0` |
| `deepseek-sparse/ggml-sycl-get-tensor*.patch` | drain the queue before device -> host reads | no speed cost | r29 / r32 | `GGML_SYCL_GET_TENSOR_WAIT` |
| `deepseek-sparse/speculative-invalid-draft-token-guard.patch` | drop a draft with an invalid token id instead of aborting (seen once in ~35 runs) | - | r29 | - |
| `pipeline/` | cross-card pipeline for layer split: one worker thread + FIFO per card, so card N+1 starts on the next prompt batch while card N works; one submission lock (Level Zero deadlock, see [../reproducers/](../reproducers/)); bounded queues | prompt read, 4 cards: DeepSeek V4 DSpark 59k 236 -> 446 tok/s, gpt-oss-120b 47k 446 -> ~1030, Flash-Next 50k 487 -> ~770; decode unchanged; perplexity equal on/off | r47-r52 | `GGML_SYCL_PIPELINE=1` to enable; use `GGML_SYCL_PIPELINE_MAX_QUEUED=4` and `-b 8192` |
| `misc/patch_idle_heartbeat.py` | background thread submits a trivial kernel to each used queue after 30 s without work | stops the Windows driver from moving an idle server's VRAM to system RAM (see [../hardware-and-windows-notes.md](../hardware-and-windows-notes.md)) | r3, b70fu-hb | `GGML_SYCL_IDLE_HEARTBEAT_SEC=30` to enable |

Measurement context for the fork table: 4x B70, EPYC host, driver 8805 (8976 for runs after 2026-10-11).
Flash-Next = Unsloth `UD-Q4_K_XL`, 131k context, MTP n-max 4 / p-min 0.1, 7-prompt A/B harness with 28-42 samples per
arm ([../bench/](../bench/)). DeepSeek V4 = Unsloth `DeepSeek-V4-Flash-0731 UD-Q2_K_XL`, 131k, DSpark n 3 / p-min 0.5.

### How the pipeline patchers apply

`pipeline/` holds Python scripts that edit the fork's `ggml-sycl.cpp` in stages; each one documents its input and
output in its docstring. Order: `patch_pipe.py` -> `patch_pipe_lock.py` -> `patch_pipe_p2.py` ... `patch_pipe_p11.py`
(p4, p5, p7, p8, p10 are diagnostics; p9 is a crash reporter). `patch_restore_pin.py` is a separate DeepSeek V4
placement fix in `llama.cpp`'s model code. The pipeline also needs two small changes in `ggml-backend.cpp` and
`llama-context.cpp` (skip host-side waits when the backend pipelines); those exist only as full-file copies in the
local tree and are not exported yet. The plan is to rebuild the pipeline on stock upstream and measure it there first.

### Not exported yet

- GLM-5.3 branch changes (grouped MoE XMX GEMM wiring, one-launch batched Q6_K MLA mat-vec, IQ2_S / IQ3_S / IQ2_XXS
  MoE kernels): live, see [../glm-5.3/](../glm-5.3/).
- DeepSeek V4 `attn_output_a` per-slice Q8_0 reorder (+12% decode) and the multi-token MUL_MAT_ID prompt path.

## Useful switches that need no patch

| Setting | Effect on this machine |
|---|---|
| `GGML_SYCL_ENABLE_DNN=0` (oneMKL GEMM instead of oneDNN for prompt matmuls) | Flash-Next prompt +18-20%, DeepSeek V4 +4-9%; decode same; perplexity within noise |
| `-ub 1024` | prompt +25-40% on Flash-Next and DeepSeek V4; `-ub 2048` was worse for Flash-Next |
| `--load-mode dio` (llama-server) / `-lm dio` (llama-bench) | avoids mmap; Task Manager otherwise shows file-backed pages as "RAM full" |
| Level Zero v2 adapter (default) | forcing v1 (`SYCL_UR_USE_LEVEL_ZERO_V2=0`): DeepSeek V4 decode 19.2 -> 16.0 |

## Testing

- `test-backend-ops test -o <OP> -b SYCL0` against the CPU backend for every kernel change.
- Perplexity: a batch-1 run (`-ub 8`) is deterministic on this backend and makes a good exactness check; batched
  prompt reads are not bit-reproducible run to run on any runtime here, so compare perplexity, not output text.
- Pre-existing upstream test failures seen on unpatched builds too: some `FLASH_ATTN_EXT` batched cases
  (hsk=256, kv=8192) and `MUL_MAT_ID` q8_0 n_mats=8 batched cases.
