# GLM-5.3-Flash: Project Maya's engine ported to SYCL (4x B70, Windows)

A port of [Project Maya](https://github.com/mw00/project-maya)'s GLM-5.3-Flash engine (CUDA/HIP) to SYCL / Level Zero,
running natively on Windows 11 across four Arc Pro B70s. Same model file as the llama.cpp setup in
[../README.md](../README.md) (Maya-M: IQ2_S / IQ3_XXS / IQ3_S experts, Q6_K / Q8_0 dense, MTP block), all experts
resident in VRAM, 128k context.

- Base: Project Maya v1.1.44 @ `5d20b0e8` (MIT), converted with SYCLomatic (daily build 2026-09-28 for the two files
  dpct 2025.1 crashed on), built with icpx 2026.0 (JIT, `-fsycl`), oneMKL for the dense GEMMs, and the llama.cpp
  SYCL fork's grouped XMX GEMM for the prompt path's experts.
- Status (2026-11-01): **live** (served through llama-swap every day since 2026-11-01).
- Work: 2026-10-31 to 2026-11-01, 36 numbered fix rounds (`tools/maya_fixups*.py`), prepared with AI assistance.

## Next optimization work

[Agent handoff and ranked leads — 2026-11-09](LEADS-2026-11-09.md) and
[2026-11-10 screens](experiments/2026-11-10-screening/): the first profiling, DSA-variant and sub-batch results.
The screens found a promising sub-batch setting that still needs quality and memory validation; no live setting changed.
The follow-up [resident-expert profile](experiments/2026-11-10-resident-profile/) separates the dominant grouped
gate/up and down spans from row gathers.
The [grouped XMX profile](experiments/2026-11-10-xmx-profile/) further splits tile copy, activation packing and
matrix spans and records tile occupancy.
The first [16-row tile screen](experiments/2026-11-10-bn16-screen/) increased occupancy but was slower and was
rejected at screening.

## Result

| | llama.cpp SYCL fork (`g10`, the previous live entry) | This port |
|---|---|---|
| Decode, short prompt (MTP) | 24-25 tok/s | **45.5-45.8 tok/s** (768-token runs), peaks of 49 served |
| Decode at 8k deep | 24.7 | 39-40 |
| Decode at 100k deep | - | 26.5 |
| Prompt read, 8k | 309 tok/s | **966-996 tok/s** |
| Prompt read, 100k | - | ~1,180 tok/s (85 s) |
| Real coding session (24k prompt + 4k thinking) | - | ~36 tok/s decode, ~1,040 tok/s prompt |

Answers checked: greedy output matches the token path run to run (tokens SAME after every decode change below);
against llama.cpp on the same GGUF the first tokens match and later ones differ at numeric near-ties (fp16 XMX / bf16
vs llama.cpp's q8 dot products). Teacher-forced KL on 64 rows vs llama.cpp top-20: 0.098-0.106, top-1 53-54 of 64,
for both this port's paths.

## How the decode got from 24 to 46

Decode is a 2-stage pipeline: cards 0,1 (the head) run position q+3 on the MTP draft while cards 2,3 (the tail) run
q+2. A step costs about (all four cards' GPU time + draft + hops) / 2, so after the host stopped being the long pole,
only less GPU work per card helped.

| Step | Decode (768-token MTP run) | What changed |
|---|---|---|
| First real tokens, 1 card, syncs everywhere | 2.3-4.3 | fixups 6-11: the port runs at all (see the Windows rules below) |
| 4 cards, layer split | 24.3 | ties llama.cpp |
| fixups16: IQ2_S / IQ3_S sign expansion as integer bit tricks | 24.9 | expert gate/up 183 -> 129 us a layer, bit-exact |
| fixups21: safe blocking card hop | 28.6 | |
| fixups24: Level Zero v1 adapter, overlapped card hop | 37.1-38.1 | the v2 adapter deadlocks (below) |
| fixups25: card hop as a device-side barrier, not a host task | 38.7-39.3 | |
| fixups26: tail and head cards enqueued from two threads | 42.0-42.3 | |
| fixups32: per-thread `getenv` cache | 42.5-43.0 | 70% of host samples sat in the CRT's getenv lock |
| fixups34: shared expert's down projection as its own mat-vec | 44.4-44.7 | it straggled as a fused extra grid row |
| fixups35: MTP draft over the auto draft vocabulary in split decode | 45.5-45.6 | draft 2.66 -> 2.23 ms, acceptance unchanged |
| `STRATA_GLM_RESIDENT_SKIP=1` (pool complete on every card) | 45.75 | skips no-op fetch/wait launches |

Prompt read: token by token ~21 tok/s -> batched prefill on the fork's grouped XMX GEMM 712 -> immediate command lists
on v1 711 -> layer split 13,24,35 instead of auto 741 -> **fixups29: prompt (DSA) attention on the XMX engines**
(new `joint_matrix` kernel, fp16 operands, F32 accumulate + online softmax; 97.6 -> 28.0 ms in the bench) **996**.

## Level Zero on Windows: rules found the hard way (B70, driver 32.0.101.8976)

These cost most of the two days. Each one has a standalone reproducer in `kbench/` or is described in the fix round.

1. **A running kernel never sees a host thread's store to `malloc_host` or shared memory** - not with `volatile`,
   atomic or acquire loads. A copy-engine memcpy into *device* memory from a second queue is seen at once, even with
   every core spinning. Fix: device mirrors for anything a kernel spins on (fixups 8, 9).
2. **`volatile` device spin loads can be served from the non-coherent L1.** Use `sycl::atomic_ref` loads (device scope
   for device words, system scope for host words) and release stores (fixups7).
3. **A USM host<->device copy queued behind a running kernel blocks every other host<->device copy in the context**
   until that kernel ends (any size, either direction, copy engine on or off). Token readbacks and card hops became
   one-thread kernels writing pinned memory (fixups 11, 12).
4. **A pending `host_task` in an in-order queue blocks the submitting thread on every later submit** (280-950 us per
   kernel). A "host task waits for the other card" overlap does not overlap anything (fixups25, `kbench/bench_hop2.cpp`).
5. **Cross-device `ext_oneapi_submit_barrier` aborts on the v2 adapter** (default) even in one shared context; it works
   on the v1 adapter at ~18 us a submit (fixups 13, 25).
6. **The v2 adapter deadlocks under kernel launches from two threads** (both inside
   `zeCommandListAppendLaunchKernelWithArguments`, blocked on driver locks; cf. intel/compute-runtime#1034). The port
   sets `SYCL_UR_USE_LEVEL_ZERO_V2=0` and `UR_L0_USE_IMMEDIATE_COMMANDLISTS=1` at static init (fixups 24, 27): 16/16
   long runs clean. v1's default batched lists cost prompt read 14%.
7. **SYCL graph replay on v1 + immediate lists is not ordered against later work on the same in-order queue.** Back-to-
   back layer graphs overlapped and their grid barriers deadlocked; a barrier after each replay fixes it but is slower
   (see rejected).
8. **Every dependent kernel costs ~7 us of GPU time** on an in-order queue (v1 or v2; `kbench/bench_gap.cpp`). At
   ~180 kernels a token a card that is ~1.3 ms a card; fusion is the structural lever.

SYCLomatic output that compiled but was wrong at run time:

- `cudaFreeHost` became a bare CRT `free()` on `sycl::malloc_host` memory: Windows heap corruption (`0xC0000374`) (fixups6).
- dpct's `device.hpp` gated the free-memory query on `__SYCL_COMPILER_VERSION`, which icpx 2026 no longer defines:
  free memory always 0 (fixups6).
- `get_major_version()` parses the Level Zero IP version (>= 7) and every launcher picked a tensor-core arm the port
  had stubbed (fixups5).
- CUDA's default stream maps to the device's own in-order queue; members defaulting to it were destroyed at
  teardown, and every later free on that queue crashed at exit (fixups 30, 31).
- oneMKL `gemm_batch` rejects cuBLAS's interleaved head strides (status 999 every layer): one gemm a head (fixups14).
- `getenv` in hot loops (debug hooks, per-launch env checks) serialized four threads on the CRT lock (fixups32).

## Rejected

| Idea | Result |
|---|---|
| SYCL graphs for the KDA layers in split / MTP decode (fixups28) | needs a barrier after each replay (rule 7): 36.75 vs 41.6 tok/s |
| int8 XMX expert GEMM for the prompt path | 40.4 ms vs 30.3 for the fp16 fork kernel a layer: IQ2_S / IQ3_S scales per 16 / 32 force a float apply after every int8 matrix op |
| Multi-token draft (batched verify windows, `--parallel 2` + `STRATA_GLM_MULTI_MTP`) | works (2.58 tokens a verify step, 80% accepted) but ~0.5 s a step = 4.8 tok/s a request; the rows path is ~10x slower a token. Do not enable `--parallel` |
| Batched command lists (`UR_L0_USE_IMMEDIATE_COMMANDLISTS=0`) | 5.3 vs 7 us a kernel in the bench, but decode hangs (2/2) |
| Expert split across all 4 cards on every layer | hop floor ~60 us x 45 layers x 2 > the best-case gain; layer split stays |
| Load-time weight repack for 16-byte loads | no gain: per-weight ALU and SLM codebook gathers limit, not loads |
| Early tail (draft overlapped with the tail, fixups33) | no gain: the pipeline cycle spans two steps |
| Sub-group 16 / large GRF / dropping SYCLomatic's `use_root_sync` | -20% / slower / no change |
| MTP draft vocabulary 32k | 45.9 tok/s but acceptance 83.3 -> 81.5% |
| IQ3_S `moe_down` variants (8 lanes a row, unroll, sg16) | all slower than the production kernel (87 us) |
| Level Zero v2 adapter A/B on the safe build | no difference (33.06 vs 33.01) before the threading changes |

## Files

- `tools/` - the conversion and fix pipeline, run in order:
  1. `migrate.sh` / `normalize.sh` (from the Strata SYCL port) - dpct over every CUDA-touching translation unit,
     one run per file (dpct 2025.1 writes files unconverted after an internal error in a whole-tree run).
  2. `strata_fixups.py` (from the Strata SYCL port, MIT) - the generic dpct fixes Strata needed.
  3. `maya_fixups.py` .. `maya_fixups4.py` + `untangle_fast.py` - compile fixes: `include/maya_compat.hpp` shims
     (streams, events, host functions, device attributes, `clock64`), cuBLAS -> oneMKL, ggml tables (use the
     original `ggml-common.h` with `GGML_COMMON_DECL/IMPL_SYCL`, not dpct's converted copy), tensor-core PTX -> stubs.
  4. `maya_fixups5.py` .. `maya_fixups31.py` - run-time fixes and speed work; each file's docstring says what and why.
     `fix9b/c.py`, `fix28*.py`, `fixnl.py` are small follow-ups to rounds 9 and 28 (round 28 itself is rejected).
  5. `patches/0001-post-fixups31-hand-edits.patch` - rounds 32, 34 and 35 (getenv cache, shared-expert split, draft
     vocabulary), applied by hand; round 33 was reverted. Base = the tree after round 31.
  6. `compile_each.py` / `link_each.py` - icpx per translation unit (135 TUs; the EXL3 path stays stubbed) and the
     link against static ggml from llama.cpp `3cf0325`. `pack.ps1` / `tok.py` build Maya's weight pack and tokenize.
  7. `envrun.ps1` - a 768-token MTP run with a token check against a reference log.
- `include/maya_compat.hpp` - the CUDA -> SYCL shim header (final state).
- `kbench/` - standalone SYCL benchmarks and reproducers: `bench_gap` (per-kernel dispatch gap), `bench_hop` /
  `bench_hop2` (card-to-card hand-off, host task blocking), `bench_submit` (host submit cost), `bench_graph` (graph
  replay), `bench_h2d` (host USM bandwidth), `bench_gu` / `bench_dn*` (IQ2_S gate/up and IQ3_S down), `bench_fg` +
  `fg_*.cpp` (the fork's grouped XMX GEMM), `clk.cpp` (sub-group clock).
- `configs/glm-maya-sycl-128k.json` - the served engine config (paths replaced with placeholders; vision block and
  `STRATA_GLM_RESERVE_MB` added 2026-11-03).
- `patches/0002-serve-pictures-as-text-without-vision.patch`, `tools/gpu_keepalive.py`, `tools/start-gpu-keepalive.ps1`
  - the serving pieces, see [Serving it](#serving-it-added-2026-11-07).

Not re-verified end to end from a clean Maya checkout: the scripts are the ones that produced the live build, applied
in this order to one tree, but a few early rounds were re-run after re-migrations. Every round is idempotent.

## Running notes

- Windows charges device allocations to commit: the 4-card process holds ~121-123 GB; the test machine needed a
  32 GB pagefile on top of its RAM.
- `STRATA_GLM_CPU_LANE=0` (the CPU-lane calibration hangs: the native CPU experts lack IQ3_S) and
  `STRATA_GLM_RAM_GB=40`. Keep at most 10 MoE layers on the last card, or its pool is incomplete and the staged-expert
  prompt path hits a latent bug (invalid expert ID).
- The first run of a new binary pays ~4.5 s of JIT inside the first prompt; SYCL's persistent cache makes later runs fast.
- Over SSH, Level Zero only loaded from a self-contained runtime folder (the engine plus the oneAPI DLLs it needs, PATH =
  that folder + System32); from the oneAPI install path the loader failed with error 448 and SYCL fell back to OpenCL.

## Serving it (added 2026-11-07)

What the daily setup added after 2026-11-01. None of it changes the engine.

**1. Server.** Maya's own server, run as a script with a Python that has `jinja2` and `tokenizers`:

```
python <work>\maya\serve\server.py --engine strata --config <work>\configs\glm-maya-sycl-128k.json --host 127.0.0.1 --port <PORT>
```

It serves the OpenAI and Anthropic APIs (`/v1/chat/completions`, `/v1/messages`, `/v1/models`). The config sets
`reasoning_effort` high and `thinking_budget` 8192. A llama-swap entry (Windows):

```yaml
models:
  glm-5.3-flash-maya-sycl:
    cmd: <PY> <work>\maya\serve\server.py --engine strata --config <work>\configs\glm-maya-sycl-128k.json --host 127.0.0.1 --port ${PORT}
    env:
      - PYTHONUTF8=1
    checkEndpoint: /health
    cmdStop: taskkill /T /F /PID ${PID}
    ttl: 0
```

A venv's `python.exe` on Windows is a launcher with a child Python. Stop it with `taskkill /T` on the launcher, or a
stale server keeps the port and answers the next start. Load plus the first request takes about 75 s.

**2. Pictures without a vision encoder.** `patches/0002-serve-pictures-as-text-without-vision.patch` (against
`serve/server.py` at `5d20b0e8`) replaces each picture or video with a short text note when no vision encoder is
configured, and logs it. Agents such as OpenCode read back their own screenshots, and before this one picture in the
history failed every later request of the session. With vision configured (next step), it does nothing.

**3. Vision (CPU encoder, 2026-11-03).**
- **Files:** Maya's published vision files from Hugging Face `peasantsmith/GLM-5.3-Flash-Maya-GGUF`, folder `vision/`:
  `mmproj-GLM-5.3-Flash-F16.gguf` (1.13 GB) and `GLM-5.3-Flash-vocab.gguf`. Check their sha256.
- **Encoder build:** Maya's `tools/vision` CMake project (`strata_vision`), on llama.cpp `3cf0325` in
  `third_party/llama.cpp` patched with `tools/vision/glm5next_patch.py`. Build it for the CPU, Release, with MSVC and
  Ninja, which gives `maya-vision.exe`.
- **Config:** the `"vision"` block in `configs/glm-maya-sycl-128k.json` (`"gpu": false`, `"threads": 24`).
- **Measured:** a 1264x625 screenshot encodes to 990 tokens in 6.4 s at 24 threads (30 s at the default thread count;
  48 threads is the same as 24). The text in it was read correctly, with decode at 46 tok/s afterwards.

**4. `STRATA_GLM_RESERVE_MB=400` (in the config).** Image prompts need the last card's expert pool complete (300 slots
a layer). With the default reserve (700), a little more VRAM in use on that card left 288 slots. The first image
prompt's scratch then borrowed experts and hit the staged-expert bug: `glm router: prompt layer 36 invalid expert ID
or non-finite score`.
- **Direction:** a bigger reserve makes the pool smaller (1100 was worse).
- **What to check in the engine log:** `CUDA3 layers [35,45) expert pool ... 300-300 slots/layer ... complete` and
  `0 experts more lent`.

**5. GPU keep-alive (`tools/gpu_keepalive.py`, `tools/start-gpu-keepalive.ps1`).** About 65 s after a request, Windows
moved the engine's VRAM to system RAM on 2 of the 4 cards (which 2 varied), and the next request waited about 49 s for
it to come back.
- **What it does:** runs a tiny kernel on every card every 15 s through `torch.xpu`. It holds about 0.24 GB a card, so
  it stops itself whenever llama-swap reports a model starting, and restarts once all are ready.
- **Running it:** the `.ps1` is a boot task (SYSTEM, at startup) with a minimal `PATH`. Set `LLAMA_SWAP_RUNNING` if
  llama-swap is not on `127.0.0.1:8080`.
- **Result:** the 30-45 s first-request delay is gone.

## Credits and license

Project Maya (https://github.com/mw00/project-maya), Copyright (c) 2026 Peasant Smith and the Project Maya
contributors, MIT, which builds on Strata (https://github.com/Niko1221/Strata), Copyright (c) 2026 Niko1221 and the
Strata contributors, MIT: notices in [../../LICENSES/Project-Maya-LICENSE](../../LICENSES/Project-Maya-LICENSE). The
scripts here modify Maya's source; Maya's license applies to the result. The prompt path's expert GEMM is the
llama.cpp SYCL fork's (MIT). Maya-M quants by peasantsmith. The CUDA -> SYCL conversion started from Intel's SYCLomatic.
