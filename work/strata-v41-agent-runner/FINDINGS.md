# Strata V4.1 on B70 — findings ledger

Living document. **Winners** are decisions/facts that moved the port forward. **Losers** are
approaches that were tried or assumed and did not hold. Both are recorded, because the losers are
the expensive part to rediscover.

Append-only in spirit: when something changes, add a revision note rather than silently editing,
so a later session can see what was believed when.

Last updated: 2026-10-27 (session 2)

---

## Status at a glance

| Gate | State | Blocker |
|---|---|---|
| CHECK-100 | PARTIAL | fresh-session resume NOT_RUN |
| CHECK-101 | PARTIAL | upstream fetch, PCIe links, toolchain PATH |
| CHECK-102+ | NOT_RUN | not started |

Host is **stable-but-degraded**: 95.87 GiB usable RAM, 4× B70 present, 37.6 h clean uptime.

---

## WINNERS

### W-001 — Strata tree is `%USERPROFILE%\strata-win`
Remote `github.com/hotschmoe/Strata.git`, branch `win-port`, `v0.1.44.1-26-g1c360526`, 2200
commits, not shallow. Found by searching for directories matching `strata` and for `.git` repos,
not by trusting the plan's path list.

**Why it matters:** every later step patches this tree. Knowing it is the tree is the difference
between real work and editing a stranger's checkout.

### W-002 — `1c360526` resolves to `1c360526bce659f45cec60b2e36c46b7770c5bf1`, and it is HEAD
The plan described this as an "abbreviated base" the Windows patches target, implying an older
commit. It is not older — it is the current `win-port` tip. Date 2026-10-16.

**Consequence:** the 29 uncommitted files are local work sitting *on top of* that base. There is no
mystery commit to hunt for.

### W-003 — The 29 uncommitted files are captured and safe
`rescue/working-tree.patch` — 20,189 bytes, ASCII, 18 files, +157/−23, produced with
`git diff HEAD --output=...` so git wrote the bytes itself. Verified with
`git apply --check --reverse` → applies cleanly. Also captured: `status.txt`, `untracked.txt`,
`provenance.json`.

**Why it matters:** this was the single irreversible-if-lost item. It is now in git, off-box.

### W-004 — WHEA Id 22 is a boot-time event, not a runtime one
One event per boot, ~23 s after boot, then zero for the life of the uptime. 37.6 h continuous
uptime produced exactly one event. This supersedes the earlier "no stable baseline, pause heavy
testing" reading.

**Consequence:** heavy GPU work is not gated by expected runtime instability. 95.87 GiB is the
budget. Any future RAM change invalidates A/B comparisons across that boundary.

### W-005 — RAM reconciled: 6 × 16 GiB = 95.87 GiB usable
DIMMs: 6 × Micron `36ASF2G72PZ-2G1A2`, 2133 MT/s, channels A–F populated, 2 slots empty.
The plan's "128 GB" is board capacity, not installed memory. The historical 95.9 GB figure matches
today exactly; the 112 GB figure is not reproduced.

### W-006 — Desktop is on the BMC, so no B70 pays the compositor tax
Display adapter is `Microsoft Basic Display Adapter` (ASPEED, `VEN_1A03&DEV_2000`). All four B70s
are purely compute. The lab notes warn that a card driving the desktop loses 0.2–0.9 GB to
`dwm`/apps; that does not apply here.

### W-007 — PowerShell 5.1 / .NET Framework 4.0 changes the runner design
`ProcessStartInfo.ArgumentList` does not exist. argv quoting is implemented per
`CommandLineToArgvW`. Separately, `powershell.exe -File` cannot bind an array parameter from
separate tokens, so argv travels in a JSON file.

**Why it matters:** both were found by running the suite, and both silently corrupt paths with
spaces if you get them wrong.

### W-008 — `git --output=` is the only reliable way to capture a patch on Windows
`git diff > file` under PowerShell 5.1 produced UTF-16 with git's stderr interleaved — a corrupt
patch that `git apply` rejected. `git diff --output=<path>` lets git write the bytes.

---

## LOSERS

### L-001 — Four directories named in the plan are not the source tree
| Path | What it actually is |
|---|---|
| `C:\llama-sycl` | prebuilt llama.cpp SYCL binaries; no `.git` |
| `C:\llama-sycl-new` | llama.cpp build/bench workspace; no `.git` |
| `C:\llama-swap` | llama-swap configs + corpus; no `.git` |
| `C:\Models` | GGUF model store |

**Why recorded:** a future session will see these names in the plan and be tempted again.

### L-002 — No DeepSeek V4.1 engine files exist in the local tree
Searched `strata_control`, `ds4_model.cu`, `ds4_kernels.cu`, `ds4_iq.cu`, `ds4_gguf.cu`,
`ds4_os.hpp`, `dsv41_fit.py`, `docs/DEEPSEEK41.md` — zero hits.

**Consequence:** there is no "patch the existing ds4 sources" shortcut. STEP-003 starts from
upstream v0.2.6. This is the single most important thing to know before planning the port.

### L-003 — Pinned upstream `4b9e05a2…` is not in the local object store
Comparing the deployed tree to pinned upstream requires a `git fetch`. Not done — the session was
read-only and a fetch is a network operation.

### L-004 — `-AsArray` is PowerShell 7+, not 5.1
`ConvertTo-Json -AsArray` does not exist on Windows PowerShell 5.1. JSON arrays are assembled
explicitly. Same family of trap as W-007.

### L-005 — scp to GPU-BOX silently failed
`scp` of a `.ps1` to `/mnt/c/...` reported nothing and copied nothing; `ssh gpu-box 'cat > file' < local`
worked. Use stdin redirection for pushing small files to the GPU-BOX WSL interop path.

### L-006 — SSH to GPU-BOX lands in WSL2 bash, not Windows
`uname -a` → `Linux GPU-BOX … microsoft-standard-WSL2`. All Windows facts must come from
`powershell.exe` / `cmd.exe`. WSL output is not Windows evidence and must never be reported as such.

### L-007 — `$id` is a PowerShell alias for `$PID`
Using `$id` as a loop variable in the process-tree walker shadowed the automatic variable and
would have broken the "do not kill myself" guard. Renamed to `$procId`.

### L-008 — `powershell.exe <script.ps1>` without `-File` is `-Command`
It parses the path as a command and exits 1. Cost several test iterations; all fixtures now pass
explicit `-File`.

### L-009 — 21 GB free padding is thin on C:
`C:` has 52.81 GB free. A 257 GB model download does not fit there. `D:` has 639 GB free,
`E:` has 298 GB. Plan model staging to `D:`.

---

## OPEN QUESTIONS

| # | Question | How to answer |
|---|---|---|
| Q-001 | Which upstream commit corresponds to v0.2.6? | fetch origin, check tags |
| Q-002 | What do the 4 `strata-stall-*.dmp` crash dumps say? | inspect with WinDbg or `dotnet-dump`; may explain current build state |
| Q-003 | PCIe link width/generation per card | vendor tooling / dxdiag; no Windows CIM exposure found |
| Q-004 | UR adapter DLLs location | `ur_loader.dll` / `ur_adapter_level_zero.dll` not in System32 |
| Q-005 | Is the 0731 work in b70-lab applicable to 1017? | survey `deepseek-v4/`, `llama.cpp-sycl/fork/deepseek-*` |
| Q-006 | What is the Maya Linux port and what transfers? | user knows this; treat as primary source |

---

## APPLICABILITY: what the 0731 / Maya work gives us for 1017

This is the section that decides how much of the port is new work.

### The three codebases, and why they are not the same thing

| Track | What it is | Engine | Relevance to 1017 |
|---|---|---|---|
| **0731** (`deepseek-v4/README.md`) | DeepSeek-V4-Flash-0731 in the **llama.cpp SYCL fork** (r52) | llama.cpp | **High** — same model family, same MoE shape class, same hardware |
| **Maya** (`glm-5.3/README.md`) | GLM-5.3-Flash Maya-M **GGUF quants** on the llama.cpp fork | llama.cpp | **Medium** — quant + MMA patterns transfer, architecture does not |
| **Strata** (`strata-windows-port/README.md`) | Separate SYCL engine, currently Qwen3.8-Flash-Next | Strata | **High for Windows platform**, none for DeepSeek arch |

**Correction to an assumption worth stating plainly:** "the Maya port for Linux" in the request is not a
DeepSeek port. Maya is Project Maya's **GLM-5.3** GGUF quant set; Maya's own engine is CUDA-only and was
never ported — the lab brought GLM into the llama.cpp fork instead. What transfers from Maya is quant
selection and kernel patterns, not an architecture port.

### Transfers directly (proven on 0731, same silicon)

| Finding | Evidence | Why it applies to 1017 |
|---|---|---|
| IQ2_XS / IQ3_XXS MoE kernel (v3) | 2.0x down, 1.6–1.7x gate/up at 1 token; 2.2–2.3x at 4 | 1017's routed experts are the same block types |
| Routing fusion | 4,202 → 3,862 launches; ids identical 516/516; ppl 6.4661→6.4620 | Architecture-agnostic routing chain |
| Sparse flash attention + indexer GEMM | decode at 59k +22%, prompt +96% | 1017 has compressed sparse attention + lightning indexer |
| Cross-card pipeline | prompt 236→446 tok/s @59k, 211→406 @102k | Needs bounded queues (`PIPELINE_MAX_QUEUED=4`) |
| Shared-context host staging | Strata patch 0002, 2-card EP working on Windows | Windows has **no peer access** — this is the only path |
| WHEA/RAM budget discipline | 131k is the practical ceiling at 4x32 GB | Same 4x32 GB constraint |

### Transfers as warnings, not code

| Loser (from `rejected-ideas/`) | Number | Applies because |
|---|---|---|
| SYCL graph replay | 21.9 → 7.1 tok/s | Re-records every step; worse under MoE |
| Broad small-op fusion | ~1,000 launches = +2% | Launch cost ~1–3 us, not the bottleneck |
| Level Zero v1 adapter | decode 19.2 → 16.0 | Do not "fix" a problem by downgrading the adapter |
| Expert-only parallelism for 0731 | ceiling 1.12x plain / 1.19x DSpark < 1.4x go line | **This is the big one — see below** |
| Grouped expert verification | −5 to −10% | Cache already absorbed redundant reads |
| `ext_oneapi_memcpy2d` | 227 s vs 17 s | Copies row-by-row on Level Zero |

### The critical non-transfer: expert parallelism was measured and rejected

`deepseek-v4/PLAN-expert-parallel.md` is explicit: Track A (expert-only parallelism for 0731) reached its
go/no-go gate at A0 and **failed it** — ceiling 1.12x plain / 1.19x DSpark against a 1.4x threshold. The
profile found expert matmuls were only 14–22% of decode step time; small ops were ~50%.

**But** the Strata route is a different proposition, and the plan says so: Strata runs Qwen3.8-Flash-Next on
**2 cards** at ~98 tok/s decode / ~1,400 tok/s prompt, vs the fork on **4 cards** at ~61 / ~750. Strata wins
because it keeps all experts resident and does expert parallelism with a captured graph, not because expert
parallelism alone is faster in llama.cpp.

**Conclusion for 1017:** do not re-run the 0731 Track A experiment. The 0731 rejection does not invalidate
Strata's approach; it invalidates bolting expert parallelism onto the llama.cpp fork. Those are different
claims and the difference cost real time to establish.

### The hard constraint that decides everything

From `PLAN-expert-parallel.md`, measured:

| | 0731 (running) | 1017 |
|---|---|---|
| Params | ~280B | **~510B** (FP8) |
| UD-Q2_K_XL | 90 GiB — **fits** 4x32 GB | — |
| ~2.7 bits/weight | — | **~170 GB > 128 GB VRAM** |
| llama.cpp support | yes (`deepseek4`) | **no** (`DeepseekV41ForCausalLM` unsupported) |

So 1017 cannot run in the llama.cpp fork at all, and cannot fit 4 cards at 2.7 bpw without the
Engram-off-to-NVMe and CPU-overflow-expert design the Strata plan describes. **This is why Strata is the
route and not a preference.**

### What 1017 adds that 0731 never exercised

`~510B`, hidden 5120, 384 experts × 2304, 40 layers. New: **Engram** n-gram memory layers (layers 1, 14),
KV shared across layers, new compressed-attention ratios, 3 MTP layers, built-in DSpark draft, vision tower.

None of that has a counterpart in the 0731 tree. The port is genuinely new surface, not a re-parameterisation.

---

## NEXT SESSION STARTER

Read this file, then `TASK-STATE.json`, then `rescue/provenance.json`.

**Do not reset `%USERPROFILE%\strata-win`.** `rescue/working-tree.patch` is the only backup of
29 files of in-progress work.

**Overarching goal (from the operator, 2026-10-27):** get DeepSeek V4.1 Flash 1017 running on GPU-BOX,
ported using what the lab learned from the Maya/0731 work. The 0731 tree in `b70-lab` is the prior art;
`APPLICABILITY` above maps what transfers and what was already measured and rejected.

## REVISION LOG

| Date | Change |
|---|---|
| 2026-10-27 s1 | Initial ledger: tree located, base resolved, WHEA corrected, RAM reconciled |
| 2026-10-27 s2 | Patch captured and verified valid; 0731/Maya applicability mapped; expert-parallel rejection clarified as a llama.cpp-only result |

---

# MAJOR REVISION — 2026-10-27 s3: llama.cpp now supports DeepSeek V4.1 natively

**This overturns a claim I made in session 2.** I wrote that "1017 cannot run in the llama.cpp fork
at all (`DeepseekV41ForCausalLM` unsupported)." That was true when the plan was written on
2026-10-26 and false by the time I checked upstream on 2026-10-27.

## W-009 — upstream llama.cpp has a complete `deepseek41` implementation

| Evidence | Detail |
|---|---|
| `src/models/deepseek41.cpp` | **933 lines** |
| Arch enum | `LLM_ARCH_DEEPSEEK41` → `"deepseek41"` in `llama-arch.cpp` |
| Model class | `llama_model_deepseek41`, inherits `llama_model_deepseek4` |
| Engram | **99** engram/ngram/ple references: `engram_hash()`, `build_engram()`, `engram_index()`, `LLM_KV_ENGRAM_TOKEN_MAP`, `LLM_TENSOR_ENGRAM_KV/GATE` |
| Sparse attention | `build_attention41()` with compressed KV, indexer, per-layer KV source |
| Engram storage | `TENSOR_READ_LAZY` — the big table is read lazily, i.e. disk-backed |
| Landed | PR **#31086** "model: DSV4.1 flash", 2026-10-25; review fixes **#31137** 10-26, **#31142** 10-26 |

It even carries the reference to `deepseek-ai/DeepSeek-V4.1-Flash-1017 inference/model.py, engram.py`,
so it was written against the same model we are targeting.

## W-010 — the SYCL backend covers deepseek41's op set

Checked `ggml/src/ggml-sycl/ggml-sycl.cpp` (upstream master, 8,130 lines):

| Op | Present |
|---|---|
| `GGML_GLU_OP_SWIGLU_CLAMP` | **yes** (line 6220, `ggml_sycl_swiglu_clamp`) |
| `MUL_MAT_ID` | yes |
| `GET_ROWS` | yes |
| `TOP_K`, `ARGSORT`, `CONCAT`, `SUM_ROWS` | yes |
| `SOFT_MAX`, `FLASH_ATTN_EXT` | yes |

`ggml_scale_bias()` is a thin wrapper over `ggml_scale_impl()` → `GGML_OP_SCALE`, which SYCL already
implements, so it needs no new kernel.

**The two ops I initially flagged as missing were a false alarm.** `SWIGLU_CLAMP` is present under
the newer GLU-op enum rather than as a standalone op, and `SCALE_BIAS` is not a distinct op at all.

## What this means for the strategy

There are now three routes, and the ranking has changed:

| Route | Work | Risk |
|---|---|---|
| **A. Port Strata `dsv41` CUDA→SYCL** | 19,132 lines `.cu`, 119 `__global__`, 148 `__device__`, 172 `__syncthreads`, 52 `__shfl`, 253 `cudaStream_t`, 107 `cudaSetDevice` | Very high — full kernel port, no reference |
| **B. Rebase tuned SYCL fork onto upstream master** | fork base is `797de63b2` (2026-10-17); deepseek41 landed 2026-10-25 — **8 days / ~500 commits** of rebase | Medium — rebase pain, but the lab has done this before (r67c rebase, 474 commits) |
| **C. Stock upstream llama.cpp SYCL** | build `-DGGML_SYCL=ON`, run | Low, but no lab tuning |

**Route B is the recommended path to maximum pp/tps**, because it is the only one that combines:
- deepseek41 support (only upstream has it)
- the tuned IQ2_XS / IQ3_XXS MoE kernels the lab already built and measured
- sparse-FA + indexer GEMM work
- cross-card pipeline

## Why the 0731 work now applies even more directly

1017's official 2-bit sets use exactly the quant family the fork's kernels were optimised for:

| 1017 set | Experts | Fork kernel status |
|---|---|---|
| IQ2_XXS (2.00 bpw, 138 GB) | IQ2_XXS | kernel exists (0731 measured 2.0x) |
| IQ2_XS (2.25 bpw, 155 GB) | IQ2_XS | **the exact type the fork's best kernel targets** |
| IQ1_M (1.75 bpw, 121 GB) | IQ1_M | not yet tuned — new work |

The 0731 model's experts were IQ2_XS (gate/up) + IQ3_XXS (down). The 2.25 bpw 1017 set is IQ2_XS.
**That is the same kernel, already measured at 68.3 µs/call vs 118-120 for generic.**

## Memory reality check for GPU-BOX

| Set | Model | Engram | Drafter | Total disk |
|---|---:|---:|---:|---:|
| 1.75 bpw | 121 GB | 111 GB | 8 GB | 239 GB |
| 2.00 bpw | 138 GB | 111 GB | 8 GB | 257 GB |
| 2.25 bpw | 155 GB | 111 GB | 8 GB | 274 GB |

GPU-BOX free space: C: 52.81 GB, D: 639.56 GB, E: 298.85 GB. **D: fits all three.**
VRAM is 4×32 GB; the reference config (four R9700, 32 GB each, 251 GB RAM) got 48 tok/s at 2.00 bpw
and **80 tok/s at 2.25 bpw**. GPU-BOX has 95.87 GiB RAM where the reference had 251 GB, so more experts
will land on the CPU lane — expect lower, but it should run.

## Immediate next actions

1. Locate the tuned SYCL fork's *source* checkout (the runtimes on `C:\llama-sycl` are binaries; no
   `.git` was found in the obvious places) — required before any rebase.
2. Rebase or cherry-pick onto upstream master (needs the deepseek41 commits, ≥ 2026-10-26).
3. Build `-DGGML_SYCL=ON`, run `strata`… no — run `llama-cli`/`llama-server` with 1017 at 2.25 bpw.
4. Only if that fails, fall back to Strata route A.

---

# SESSION 3 PROGRESS — engine builds, model downloading

## W-011 — upstream llama.cpp builds with SYCL on GPU-BOX, clean

| Item | Value |
|---|---|
| Source | `github.com/ggml-org/llama.cpp` @ `de5122d` (2026-10-27), shallow clone depth 50 |
| Build dir | `C:\llamacpp-v41\build-sycl` |
| Result | **335/335 targets, BUILD_OK, 0 errors** |
| Artifacts | `llama-cli.exe`, `llama-bench.exe` |
| Toolchain | MSVC 19.51.36248.0 + IntelLLVM 2026.0.0 (icx) |
| CMake/Ninja | 4.4.4 / 1.13.2 (installed via `pip --user`) |
| Configure flags | `-DGGML_SYCL=ON -DGGML_SYCL_F16=OFF -DGGML_NATIVE=OFF -DLLAMA_CURL=OFF -DGGML_OPENMP=ON` |

`deepseek41.cpp` is present in that tree and compiled as part of the model set.

## W-012 — SYCL sees all four B70s

```
SYCL0: Intel(R) Arc(TM) Pro B70 Graphics (32558 MiB,  7989 MiB free)
SYCL1: Intel(R) Arc(TM) Pro B70 Graphics (32558 MiB,  9809 MiB free)
SYCL2: Intel(R) Arc(TM) Pro B70 Graphics (32558 MiB,  9691 MiB free)
SYCL3: Intel(R) Arc(TM) Pro B70 Graphics (32558 MiB, 32540 MiB free)
```

**Only 3 of 4 cards are free.** `llama-server.exe` PID 17560 (11.1 GB) is the production
llama-swap arm; it holds VRAM on SYCL0-2. Left untouched by design - production services cause a
busy result, not an unload. Any 1017 run must either tolerate ~9 GB/card on three cards, or the
operator pauses the arm deliberately.

## W-013 — the lab's tuned kernels are largely already upstream

This is the finding that makes Route B cheap. The fork patches target files that **already exist in
upstream HEAD**:

| Fork patch | Target file | Upstream status |
|---|---|---|
| `deepseek-moe/02-mmvq-iq-moe-slm-v3.patch` | `ggml/src/ggml-sycl/mmvq.cpp` | **EXISTS** |
| `deepseek-sparse/fattn-sparse.patch` | `ggml/src/ggml-sycl/fattn-sparse.cpp` | **EXISTS** |
| `deepseek-sparse/lightning-indexer.patch` | `ggml/src/ggml-sycl/lightning-indexer.cpp` | **EXISTS** |
| (route fusion) | `ggml/src/ggml-sycl/topk-moe.cpp` | **EXISTS** |

Upstream `mmvq.cpp` already carries `vec_dot_iq2_xs_q8_1_moe` and `vec_dot_iq3_xxs_q8_1_moe` and the
`mul_mat_vec_iq2_xs_q8_1_sycl` / `iq3_xxs` entry points. The sparse-FA and lightning-indexer work
has been upstreamed too.

What the v3 patch **adds on top** is the local-memory optimisation: arithmetic sign masks
(`moe_sign_mask4` / `moe_sign_masks`, parity-extended 7→8 bits), 16-bit word reads for index/scale
bytes, and per-work-group re-layout of the entry's q8_1 activations. It is **~236 added lines in
one file**, gated by `GGML_SYCL_MOE_IQ_SLM_V=2` to select v2 again. That is a very portable patch.

## W-014 — model download underway

| Item | Value |
|---|---|
| Source | `ISTA-DASLab/DeepSeek-V4.1-Flash-1017-GSQ-RCO-GGUF` |
| Set chosen | **IQ2_XXS (2.00 bpw)** - the plan's first target |
| Destination | `D:\AI\Models\dsv41` (D: has 640 GB free) |
| Sizes | IQ2_XXS 4 shards = 36.39 + 36.68 + 36.55 + 19.12 = **128.7 GB**; Engram IQ4_NL **103 GB**; mmproj BF16 |
| Measured rate | **17 MB/s** |
| ETA | **~3.8 h** for ~230 GB |

Tooling: `huggingface_hub` 1.24.0, `snapshot_download` with `allow_patterns` filter, 4 workers.
Launched detached via WMI so it survives session teardown.

## L-010 — `nohup cmd.exe` does NOT survive SSH teardown here
First build attempt used `nohup cmd.exe /c ... &` and produced an empty log and no build dir.
The lab's own `arm.ps1` comment says the answer: create through WMI
(`Invoke-CimMethod -ClassName Win32_Process -MethodName Create`). That worked immediately.

## L-011 — CMake 4.4.4 + upstream llama.cpp is fine, but MSVC is at a non-standard path
Visual Studio lives at `C:\Program Files (x86)\Microsoft Visual Studio\18\BuildTools` (VS "18", not
2022). `vswhere -latest -products * -property installationPath` finds it; hardcoded 2022 paths fail.

## Immediate next moves (queued)

1. Wait for the download (~3.8 h), verifying SHA-256 as it lands.
2. Apply `02-mmvq-iq-moe-slm-v3.patch` to the fresh clone and rebuild - it targets a file that
   exists and adds one self-contained kernel path.
3. Test 1017 with a small context on the free card (SYCL3) first, CPU-lane experts only.
4. Only then negotiate the production arm pause for a real 4-card run.

## W-015 — the v2/v3 MoE kernel port is scoped and tractable

Read both patches in full. The port shape:

| Patch | Added lines | What |
|---|---:|---|
| `01-mmvq-iq-moe-slm-v2.patch` | **187** | `moe_iq_traits<IQ2_XS>` + `moe_iq_traits<IQ3_XXS>`, `mul_mat_vec_q_moe_iq_slm`, `launch_moe_iq_slm_cfg`, `launch_moe_iq_slm`, `MOE_IQ_CASE` macro |
| `02-mmvq-iq-moe-slm-v3.patch` | **236** | arithmetic sign masks (`moe_sign_mask4`/`moe_sign_masks`), 16-bit index/scale reads, per-work-group q8_1 re-layout |

**Integration point verified present upstream**: `ggml_sycl_mul_mat_vec_q_id()` at
`ggml/src/ggml-sycl/mmvq.cpp:2709`, with `launch_mul_mat_vec_q_moe` at :2689 and the existing
per-type dispatch switch (`Q4_0`, `Q4_1`, `Q5_0`, `Q5_1`, `Q8_0`, `Q2_0`, ...). The patch inserts
`case GGML_TYPE_IQ2_XS:` and `case GGML_TYPE_IQ3_XXS:` arms into that switch and calls the new
launcher.

So the work is: add ~190 lines of new functions to `mmvq.cpp`, add two switch arms, rebuild.
No fork merge, no 500-commit rebase. Env-gated by `GGML_SYCL_MOE_IQ_SLM` (default on) and
`GGML_SYCL_MOE_IQ_SLM_CFG` (default 82 = 8 sub-groups x 2 rows).

**Caveat recorded honestly**: both patch headers state "This is NOT stock upstream: it will not
apply to a fresh clone without porting." True — the diffs name scratch files (`mmvq-new.cpp`,
`mmvq-v3.cpp`) and their hunk offsets are against a local tree. But the *content* is
self-contained and the integration point exists, so this is a port, not a rewrite.

**Next after the download completes**: apply the v2 + v3 content to
`C:\llamacpp-v41\ggml\src\ggml-sycl\mmvq.cpp`, rebuild, and verify correctness against the
`ds4_cpu_bench` reference before trusting any number.
