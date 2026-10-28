# 1017 cannot be tuned — the runtime does not exist (verified 2026-10-27)

Prompt asked to tune "the new deepseek 1017 version". This is a blocker report, not a tuning plan.
Every claim below is measured on GPU-BOX, this evening.

-

## 1. The blocker, in one line

**`deepseek41` is an architecture no llama.cpp build on this box can load, and the only engine that
targets it — Strata's `sycl/src/dsv41/` — does not exist (0 lines ported).**

## 2. Proof: the binary refuses it

`llama-server.exe` (r67c, the current production build) on the 1017 pack:

```
load_model: loading model 'D:\AI\Models\dsv41\DeepSeek-V4.1-Flash-1017-GSQ-RCO-IQ2_XXS-00001-of-00004.gguf'
E llama_model_load: error loading model: unknown model architecture: 'deepseek41'
E llama_model_load_from_file_impl: failed to load model
EXIT=1
```

Fails at **metadata parse**, ~0.3 s in. It is not a memory or VRAM problem — the loader simply has no
`deepseek41` in its arch table. Nothing to tune.

## 3. Why 0731 works and 1017 does not

The two packs declare different architectures:

| Pack | `general.architecture` | Runtime that knows it |
|---|---|---|
| `DeepSeek-V4-Flash-0731-UD-Q2_K_XL` (3 shards, unsloth) | **`deepseek4`** | llama.cpp fork (`b70dsv4-r*` builds) — **works** |
| `DeepSeek-V4.1-Flash-1017-GSQ-RCO-IQ2_XXS` (4 shards, ISTA-DASLab) | **`deepseek41`** | Strata `sycl/src/dsv41/` — **does not exist** |

`deepseek4` vs `deepseek41` is one character in the name and a completely different model graph. The
fork's `b70dsv4` line was built for the former.

## 4. DSpark: available on 0731, absent on 1017

| | 0731 | 1017 |
|---|---|---|
| Drafter file | `dspark-DeepSeek-V4-Flash-0731-Q8_0.gguf`, **10.9 GB, present** | **none** — pack has 1008 tensors, layers 0-39, zero `mtp.*` |
| DSpark in engine | yes (`--spec-type draft-dspark`, live in production) | would need a DSpark impl in the port |

## 5. What the config already does (0731, production)

`deepseek-v4-flash-dspark` in `config.windows.yaml`, 4 B70, 131k, layer split:

```
-sm layer -fit off -ngl 99 -ts 11,11,11,11 -c 131072 -b 8192 -ub 1024 -fa on --load-mode dio
--spec-type draft-dspark --spec-draft-model <10.9 GB Q8_0>
--spec-draft-n-max 3 --spec-draft-ngl 99
--spec-draft-device SYCL2,SYCL1,SYCL0,SYCL3 --spec-draft-p-min 0.5
```

Documented baseline (`deepseek-v4/README.md`, driver 8805, r9 kernels): **24.2 tok/s** long prompt,
**23.9** short, draft acceptance 73-88%. Later r17: 24.3-24.9.

## 6. The tensor-split work is real, and it is 0731-shaped

`llama.cpp-sycl/TENSOR-SPLIT-DECODE.md` — this is genuinely strong work and directly usable **on
0731**:

- Tensor split used to lose 19-33% at decode batch sizes. Root cause: **kernel launch on a single
  host thread** (~41.5 ms/forward), not the all-reduce or host waits.
- **Per-subgraph SYCL graph cache** (`GGML_SYCL_ENABLE_GRAPH=1 GGML_SYCL_GRAPH_CACHE=1`) recovers
  ~30 of those 41.5 ms. Qwen 2-card tensor split became **+27-37% over layer split**.
- llama-server validated: Qwen +18-21%, Mistral +45%.
- Correctness: perplexity bit-identical at ub 4; greedy output identical.
- **Per-card launch threads: NOT safe for serving** (silent exit / hang under mixed traffic). Use the
  cache alone.
- Caveat for this box: `-sm layer` reaches 24 tok/s on 0731 at 131k, and the doc notes layer split
  gains nothing from the cache because its launch time is already hidden. **So the graph cache may
  buy little on a 4-card layer-split MoE** — it was measured on 2-card dense models.

## 7. The decision this forces

"Tune 1017" is not a tuning task on this box. It is one of:

**Option A — Tune 0731 (tractable, today).**
Same model family, DSpark present and working, tensor-split work applies, production config exists.
Real levers: graph cache on/off, layer vs tensor split on a 4-card MoE, `-ts` rebalance, ub/batch
sweep, draft depth/p-min. Expected: single-digit to low-double-digit percent, with the graph cache
being the uncertain one (see §6 caveat).

**Option B — Make 1017 runnable (a port, not tuning).**
Needs `sycl/src/dsv41/` built from 138 CUDA files (~16.4k lines of compute, 93 kernels), plus a
DSpark drafter in GGUF form for 1017 (does not exist) and a SYCL DSpark implementation. dpct gets
~85% of kernels. Multi-week. That is the Strata track, already scoped in `PORT-SCOPE.md`.

**Option C — Bridge: run 1017 nowhere, but tune the 0731 config that 1017 will inherit.**
Any flag that helps 0731 (split mode, ub, draft depth, kv) is likely to transfer to dsv41, since the
config surface is the same engine family. Cheapest way to bank knowledge before the port lands.

## 8. Recommendation

**C, via A.** Tune 0731 now and bank the settings. Do not spend this session on 1017 — there is
nothing to measure until the port exists, and the port is a separate multi-week track.

If the intent really is 1017 specifically, the honest next step is not tuning: it is a
`sycl/src/dsv41/` CMake target plus the dpct-converted kernels, per `PORT-SCOPE.md`.
