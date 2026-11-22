# Strata on native Windows: Qwen3.8-Flash-Next on two Arc Pro B70s

[Strata](https://github.com/hotschmoe/Strata) is a SYCL inference engine with B70-specific work (two-card expert
parallel, MTP speculative decoding, int8 KV). It targets Linux. The patches here make it build and run natively on
Windows 11 with Intel's `icx` compiler, and add the fixes and the prompt-read work that the numbers below depend on.

**What this setup does (served, as of 2026-11-21):** Qwen3.8-Flash-Next, ISTA-DASLab GSQ-RCO IQ3_S, two B70s, one
slot with 200k context, int8 KV.

| Measure | Result | How it was measured |
|---|---:|---|
| Decode, 7-prompt bench through llama-swap | **130 tok/s** mean | [`bench/sbench.py`](../bench/), 512 tokens, temperature 0, thinking off (2026-11-07) |
| Decode per fresh engine start, 4-prompt set | **104-108 tok/s**, 8 of 8 starts | [`slow-starts/start_ab.py`](slow-starts/), median per start (2026-11-07) |
| Decode on code / explain / summary requests through llama-swap | 111-133 tok/s | single requests (2026-11-07) |
| Decode on real traffic, 234 requests of 256+ tokens (2026-11-18 to 11-21) | median 117, middle 80% 106-131 tok/s | the engine's own log |
| Prompt read, 32k tokens, engine bench | **2,194 tok/s** (2,260-2,267 in a second window) | stdin serve protocol, warm, timing off |
| Prompt read, 32k-65k tokens, real traffic | median 1,594, middle 80% 1,518-1,605 tok/s (25 reads) | the engine's own log |
| Prompt read, 37k tokens, before the ESIMD work (2026-11-07) | 1,476-1,570 tok/s | 4 fresh starts |
| Decode right after a 32k prompt | 106-108 tok/s | engine bench, 256 tokens |

The 2026-11-17 ESIMD prompt work did not move decode (114-116 tok/s on short prompts before and after, same
harness). The llama.cpp SYCL fork on 4 of the same cards ran this model at 60.6 tok/s decode and 748 tok/s prompt read.

## How to run it

This is the recipe for the build that is live here. Every step below was checked against that machine on
2026-11-21: the patch chain was applied to a clean checkout and compared file by file with the sources the live
`strata.exe` was built from, and the config is the live one with the paths replaced.

### 1. What you need

| Item | Version used | Notes |
|---|---|---|
| GPUs | 2x Intel Arc Pro B70 (32 GB each) | the box has 4; this setup uses 2 of them |
| GPU driver | 32.0.101.9175 | the 2026-10 numbers were on 32.0.101.8976 |
| OS | Windows 11 Pro 25H2 (build 26200) | |
| CPU / RAM | 24-core EPYC, 112 GB RAM | the PLE table needs **~27 GB of free RAM** for the OS file cache (step 6) |
| Disk | 84 GB GGUF shards, plus the pack and ~5 GB of MTP files | NVMe |
| Visual Studio Build Tools | 18 (2026), MSVC 14.51 | "Desktop development with C++" (MSVC, CMake, Ninja) |
| Intel oneAPI Base Toolkit | 2026.0 | DPC++ (`icx`), oneMKL, TBB, oneDNN |
| Level Zero SDK | 1.33.1 | installer from [oneapi-src/level-zero](https://github.com/oneapi-src/level-zero/releases); CMake finds it under `C:\Program Files\LevelZeroSDK` |
| Python | 3.14 (3.10+ works) | a venv in the Strata checkout, `pip install -r requirements.txt` |

### 2. Sources

Clone everything with `core.autocrlf=false`. The patches are LF, and a CRLF checkout makes `git apply` fail.

```bat
git -c core.autocrlf=false clone https://github.com/hotschmoe/Strata <STRATA_SOURCE_DIR>
cd <STRATA_SOURCE_DIR>
git checkout 1c360526bce659f45cec60b2e36c46b7770c5bf1
rem   (= the tip of branch b70-night-20261016, from SergiioB/b70-launcher PR #4)

git -c core.autocrlf=false clone https://github.com/ggml-org/llama.cpp <LLAMA_PR>
cd <LLAMA_PR>
git fetch origin pull/31428/head
git checkout eec5c09cef61885636ee31406855abfe2feb7a44
git apply <this repo>\strata-windows-port\esimd-prefill\esimd\llama-pr-31428-fused-gemm-tile-width.patch
```

`<LLAMA_PR>` only provides the headers for the ESIMD GEMM (step 4). Nothing in it gets built on its own.

### 3. Apply the patches

From `<STRATA_SOURCE_DIR>`, in this order. Each one applies cleanly on the one before it:

```bat
set P=<this repo>\strata-windows-port
git apply %P%\patches\0001-sycl-native-Windows-build-icx-of-the-SYCL-engine.patch
git apply %P%\patches\0002-sycl-Windows-two-card-expert-parallel-through-host-m.patch
git apply %P%\patches\0003-sycl-Windows-JIT-build-option-for-Xe2-extra-AOT-opti.patch
git apply %P%\patches\0004-sycl-Windows-optional-timer-resolution-request-STRAT.patch
git apply %P%\slow-starts\0002-ep-psum-own-rows-in-vram.patch
git apply %P%\slow-starts\0003-ep-prefill-rows-private.patch
git apply %P%\esimd-prefill\0001-prefill-grouped-iq3s-both-cards-esimd.patch
git apply %P%\patches\0005-sycl-verify-batch_poll-copy-stream-empty-check.patch
```

`git status` should then show 20 modified files under `sycl/` and one new one (`sycl/include/strata_win_undefs.h`).
The live build's sources match this tree except for comment wording in three files and one extra stderr line
("EP psum: this card's own expert rows in VRAM").

| Patch | What it does |
|---|---|
| `patches/0001` | native Windows build with `icx` (see [the patch table](#what-each-patch-does)) |
| `patches/0002` | two-card expert parallel through host memory (Windows has no peer access between B70s) |
| `patches/0003` | JIT build option for Xe2 (`STRATA_SYCL_XE2_JIT=ON`) |
| `patches/0004` | optional timer-resolution request (the config turns it off) |
| `slow-starts/0002` | card 0's own expert rows stay in VRAM: ends the per-start speed lottery |
| `slow-starts/0003` | card 1's prompt-chunk rows buffer stays in VRAM: same fix for the prompt read |
| `esimd-prefill/0001` | grouped prompt experts on IQ3_S, on both cards, on the ESIMD GEMM: +31% prompt read |
| `patches/0005` | `batch_poll` checked the copy stream's error code instead of its empty flag (correctness, no speed change) |

### 4. Build (JIT, not AOT)

Put the ESIMD kernel and the shim in one folder:

```bat
mkdir <ESIMD_DIR>
copy %P%\esimd-prefill\esimd\fused-gemm-esimd.cpp <ESIMD_DIR>\
copy %P%\esimd-prefill\esimd\fused-gemm-esimd.hpp <ESIMD_DIR>\
copy %P%\esimd-prefill\strata_esimd_shim.cpp <ESIMD_DIR>\
```

`fused-gemm-esimd.cpp` / `.hpp` are llama.cpp PR #31428's ESIMD grouped GEMM at `eec5c09`, plus an IQ2_S loader and
64-wide tiles (`MAYA_FG_BN 64`) from the [GLM-5.3 work](../glm-5.3/sycl-port/experiments/2026-11-16-esimd-tile-sweep/).
They are the files the live build used.

Then, in a `cmd` window:

```bat
call "C:\Program Files (x86)\Microsoft Visual Studio\18\BuildTools\VC\Auxiliary\Build\vcvars64.bat"
for %C in (tbb umf dnnl mkl dpl ocloc compiler) do call "C:\Program Files (x86)\Intel\oneAPI\%C\latest\env\vars.bat"

cd <STRATA_SOURCE_DIR>
cmake -B build-win -S sycl -G Ninja -DCMAKE_BUILD_TYPE=Release ^
      -DSTRATA_SYCL_AOT= -DSTRATA_SYCL_XE2_JIT=ON -DSTRATA_SYCL_PARITY=OFF ^
      -DCMAKE_C_COMPILER=cl -DCMAKE_CXX_COMPILER=icx ^
      -DSTRATA_ESIMD_DIR=<ESIMD_DIR> -DSTRATA_ESIMD_FORK=<LLAMA_PR>/ggml
cmake --build build-win --target strata
```

(In a `.cmd` file write `%%C` instead of `%C`.)

- **`-DSTRATA_SYCL_AOT=` (empty) is the important part.** It makes a JIT build: the GPU driver compiles the device
  code at first use. The oneAPI 2026.0 AOT build (`-DSTRATA_SYCL_AOT=bmg-g31`) miscompiles the batched int8 decode
  attention and gives wrong answers at a speed that looks fine. See [the int8 KV bug](#the-int8-kv-bug-an-aot-miscompile-solved).
- Without the two `STRATA_ESIMD_*` variables the build still works, but `STRATA_NIGHT_PREFILL_ESIMD` does nothing
  and the grouped prompt experts run on Strata's own `joint_matrix` kernel, which is slower.
- If CMake does not find Level Zero, pass `-DSTRATA_ZE_INCLUDE=<SDK>/include -DSTRATA_ZE_LOADER=<SDK>/lib/ze_loader.lib`.

**Runtime folder.** Copy `build-win\strata.exe` to `<STRATA_RUNTIME_DIR>` with the oneAPI DLLs it loads. The live
folder holds: `sycl9.dll`, `ur_loader.dll`, `ur_adapter_level_zero.dll`, `ur_adapter_level_zero_v2.dll`,
`ur_adapter_opencl.dll`, `ur_win_proxy_loader.dll`, `umf.dll`, `tcm.dll`, `libhwloc-15.dll`, `mkl_core.3.dll`,
`mkl_sycl_blas.6.dll`, `mkl_tbb_thread.3.dll`, `tbb12.dll`, `dnnl.dll`, `libmmd.dll`, `libiomp5md.dll`,
`svml_dispmd.dll` (from the oneAPI `compiler`, `mkl`, `tbb`, `dnnl` and `umf` folders). The config's `lib_dirs`
points at this folder.

### 5. Model files

The config points at four things besides the GGUF: a pack, the MTP draft layer, a draft vocabulary and an expert
profile. Download ISTA-DASLab's `Qwen3.8-Flash-Next-GSQ-RCO-GGUF` **IQ3_S**, both shards (84 GB), into one folder,
and check them against the sha256 sums on the model page. Then, from the Strata checkout, in its Python venv:

```bat
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
set STRATA_GGUF_PY=<STRATA_SOURCE_DIR>\build-win\_deps\strata_llamacpp-src\gguf-py
set PYTHONUTF8=1

rem pack (the dense weights, the tokenizer folder the config names, the expert index)
.venv\Scripts\python tools\iq_pack.py --gguf <MODELS_DIR>\ISTA-DASLab\Qwen3.8-Flash-Next-GSQ-RCO-GGUF\IQ3_S\Qwen3.8-Flash-Next-GSQ-RCO-IQ3_S-00001-of-00002.gguf ^
       --out <STRATA_DATA_DIR>\packs\iq3_s

rem MTP draft layer: fetch (~5 GB; the fetch can drop, so re-run it until it succeeds), verify, pack, runtime layer
.venv\Scripts\python tools\mtp_fetch.py fetch --out <STRATA_DATA_DIR>\mtp
.venv\Scripts\python tools\mtp_fetch.py verify --out <STRATA_DATA_DIR>\mtp
.venv\Scripts\python tools\mtp_pack.py --src <STRATA_DATA_DIR>\mtp --experts q2_0 --out <STRATA_DATA_DIR>\mtp\mtp-q2_0.gguf
.venv\Scripts\python tools\mtp_rt.py --gguf <STRATA_DATA_DIR>\mtp\mtp-q2_0.gguf --out <STRATA_DATA_DIR>\mtp\rt
```

`gguf-py` exists after the step 4 build has fetched Strata's pinned llama.cpp. `iq_pack.py` needs shard 2 in the same
folder as shard 1. The draft vocabulary (`data\draft_vocab_en.bin`) and the expert profile
(`data\expert-profile-sycl.bin`) ship in the Strata checkout. The config's `--mtp` is the `rt` folder, and
`tokenizer` is the pack's `tokenizer` folder.

Note the model is a quant mix, not pure IQ3_S: across the 48 MoE layers, gate/up are IQ2_S, IQ3_XXS, IQ3_S and one
IQ4_XS layer, and down is IQ4_NL plus nine Q2_0 layers. That is why the grouped prompt path needed a per-layer type
check (`esimd-prefill/0001`).

### 6. Engine config

Use [`configs/strata-iq3s-200k1-pf8k.json`](configs/strata-iq3s-200k1-pf8k.json) as it is, with the placeholders
filled in. It is the live config. The settings that matter:

| Setting | Value | Why |
|---|---|---|
| `--max-context`, `"parallel"` | `200000`, `1` | 2 x 200k does not fit IQ3_S on two 32 GB cards; 2 x 112k does but reads prompts 37% slower |
| `--kv` | `int8` | needs the JIT build |
| `--prefill` | `8192` | prompt chunk; 10240 sits at card 1's memory limit and runs ~3x slower, 12288 does not fit |
| `--ple-io` | `mmap` | `direct` reads the 27 GB PLE table from the SSD every token and drifts to ~70 tok/s |
| `--spec`, `--spec-min-p`, `--mtp-max-t` | `4`, `0`, `4` | MTP draft depth; other values were equal or worse |
| `--expert-parallel-device` | `1` | the second card holds 320 of the 512 experts per layer, card 0 the other 192 |
| `"gpu"` | `[0, 1]` | indexes into the devices that `ONEAPI_DEVICE_SELECTOR` leaves visible |
| `STRATA_NIGHT_PREFILL_GROUPED`, `_MAX`, `STRATA_NIGHT_PREFILL_ESIMD` | `1`, `1024`, `1` | the +31% prompt read; without the `esimd-prefill` patch `GROUPED` must be `0` for IQ3_S |
| `STRATA_NIGHT_EP_PSUM`, `STRATA_EP_PREFILL_REDUCE` | `1`, `1` | the expert-parallel paths the two VRAM fixes are about |
| `STRATA_VERIFY_DEVICE_PLAN`, `STRATA_VERIFY_NO_HOST` | `1`, `1` | without them verify waits on a host doorbell and hangs |
| `STRATA_WIN_TIMER_MS` | `0` | patch 0004's timer request, off (no effect measured) |
| `SYCL_CACHE_PERSISTENT` | `0` | the first request after a load JIT-compiles the kernels (see gotchas) |

The other ~80 `STRATA_*` switches are the `b70-night-20261016` branch's tuned set, unchanged. One of them,
`STRATA_BATCH_MTP_PAIR_SKIP_PROB`, is not read by this build.

Optional vision (CPU image encoder): the config's `vision` section runs `strata-vision.exe`, built from llama.cpp's
`mtmd` tool at the llama.cpp commit the engine pins, with ISTA-DASLab's BF16 mmproj. Leave the section out if you do
not need images. More in [Vision](#vision-optional-cpu-encoder).

### 7. Serve

Strata's OpenAI-compatible server reads the engine config. Pick the two cards with `ONEAPI_DEVICE_SELECTOR`
(Level Zero device numbers; on a box with only the two B70s that is `level_zero:0,1`):

```bat
set ONEAPI_DEVICE_SELECTOR=level_zero:2,3
set PYTHONUTF8=1
.venv\Scripts\python sycl\serve\server_intel.py --engine strata --config <CONFIG.json> --host 127.0.0.1 --port <PORT>
```

The engine is ready when `/health` answers. Cold loads took 42-287 s here, depending on how much of the model was
already in the file cache. The engine log should show `peer alias path on (T_max 8192)` and one `night ESIMD` line
per expert type pair.

A generic llama-swap entry (Windows):

```yaml
models:
  qwen3.8-flash-next-strata:
    cmd: >
      <STRATA_SOURCE_DIR>\.venv\Scripts\python.exe <STRATA_SOURCE_DIR>\sycl\serve\server_intel.py
      --engine strata --config <CONFIG.json> --host 127.0.0.1 --port ${PORT}
    env:
      - ONEAPI_DEVICE_SELECTOR=level_zero:2,3
      - PYTHONUTF8=1
    checkEndpoint: /health
    cmdStop: taskkill /T /F /PID ${PID}
    ttl: 0
```

`cmdStop` with `/T` ends the Python server and the `strata.exe` engine under it. If clients reach the server by a
host name other than `localhost`, add that name to `STRATA_ALLOWED_HOSTS` (the server's DNS-rebinding check) or
set an API key.

### 8. Check, then measure

1. **Answers first.** `python bench\squal.py http://127.0.0.1:<PORT> <MODEL>` asks four questions with checkable
   answers (JSON extraction, arithmetic, five capitals, count to 30). A broken build can look fast: the AOT build's
   garbage output was easy for the MTP draft to predict and showed 96.6 tok/s.
2. **Warm up once.** With `SYCL_CACHE_PERSISTENT=0` the first request after a load compiles kernels. An 11.8k first
   read ran at 903 tok/s. Throw that request away.
3. **Decode.** `python bench\sbench.py http://127.0.0.1:<PORT> <MODEL> --n 512 --rounds 2`: seven prompts (code
   explain, code write, summary, fiction, JSON extraction, continuity edit, arithmetic), streamed, temperature 0,
   thinking off. Round 1 is warm-up and is left out of the mean.
4. **Prompt read.** Add `--long 32000 --doc <a long text file>`: one long prompt, prompt tok/s = prompt tokens /
   time to first token, plus decode right after it.

What the numbers mean:
- **Decode tok/s** = (completion tokens - 1) / (time of the last token - time of the first token). The prompt read is
  not in it.
- **It depends on the text.** MTP drafts 4 tokens ahead and the main model checks them, so tok/s follows how often the
  draft is right. In one start on 2026-11-06: code 122 tok/s, math 121, a story 68. A mean over a mixed set (the 7
  prompts) is the number to compare, and only against the same prompts.
- **Thinking off** in the bench. With thinking on, the tokens are different text and the speed moves with it.
- **Prompt read through the HTTP server** (1,500-1,650 tok/s on real requests) is lower than the engine bench at 32k
  (2,194). The engine bench sends token ids straight to `strata.exe --serve` on stdin, one prompt, warm.

Interleave A/B runs and use several fresh starts. Before the slow-start fix, speed was set per engine start, and 3
starts per arm were not enough to see a difference; 8 were.

### 9. Gotchas

- **AOT build + int8 KV = wrong answers** (oneAPI 2026.0). Use the JIT build. AOT with oneAPI 2026.1 was not tested.
- **`STRATA_VERIFY_DEVICE_PLAN=1` and `STRATA_VERIFY_NO_HOST=1`** are required, or the engine hangs on its first verify.
- **`STRATA_NIGHT_PREFILL_GROUPED=1` without the `esimd-prefill` patch** stops the engine with "card 0 gate/up type
  23" on IQ3_S (the one IQ4_XS layer), then a restart.
- **Memory headroom.** `--prefill 10240` "fits" with card 1 at its limit and runs ~3x slower than 8192. 2 x 200k
  slots do not fit.
- **`--ple-io mmap` needs ~27 GB of free RAM.** Under memory pressure the PLE reads fall back to the disk and decode
  drops. Alternating two 50+ GB models in one A/B churns the file cache the same way.
- **Line endings.** Clone with `core.autocrlf=false`, or the patches do not apply.
- **`STRATA_PREFILL_TIMING=1` distorts two-card speeds** (the host waits on the peer queue every layer). Use it to see
  where time goes, not for tok/s.
- **Slow starts** (~45 instead of ~100 tok/s, fixed per start) mean `slow-starts/0002` or `0003` is missing. Both
  matter only where the exchange regions are host memory, which is the case on Windows.
- **VTune `gpu-offload`** hangs at load under `--serve` on this two-card path.

### Vision (optional, CPU encoder)

`strata-vision.exe`, built from llama.cpp's `mtmd` tool at the llama.cpp commit the engine pins, with ISTA-DASLab's
BF16 mmproj. Config section (also in the published config):

```json
"vision": {
  "exe": "<STRATA_RUNTIME_DIR>\\strata-vision.exe",
  "mmproj": "<MODELS_DIR>\\...\\mmproj-Qwen3.8-Flash-Next-BF16.gguf",
  "model": "<MODELS_DIR>\\...\\Qwen3.8-Flash-Next-GSQ-RCO-IQ3_S-00001-of-00002.gguf",
  "gpu": false,
  "max_tokens": 1024,
  "threads": 24
}
```

Use `max_tokens` 1024 for screenshots and text in images (changed from 300 on 2026-11-06). One terminal screenshot,
same two questions, temperature 0:

| `max_tokens` | Image prompt | Error line copied | Time (question 1 / 2) |
|---|---|---|---|
| 300 | 361 tokens | misread `invoice.ts` as `invoices.ts` | 9.8 s / 5.6 s |
| 1024 | 1,093 tokens | exact | 17.7 s / 7.1 s |

The CPU encode was about 4.4 s per new image at 300 tokens (24 threads).

**Abliterated variant (2026-11-06).** The same recipe runs an abliterated IQ3_S: SC117's
`Qwen3.8-Flash-Next-GSQ-RCO-abliterated-IQ3_S` shard 1 with ISTA-DASLab's shard 2 (the per-layer embedding table,
unchanged by abliteration). Build its own pack with `iq_pack.py` from the abliterated shard 1, and keep the stock MTP
`rt` folder.
- **Shard 2 location:** `iq_pack.py` and the engine expect shard 2 next to shard 1, so put a hardlink (or copy) of
  ISTA-DASLab's shard 2 in the abliterated folder, renamed `...-abliterated-IQ3_S-00002-of-00002.gguf`.
- **`--ple-gguf`:** point it at that renamed file, not ISTA-DASLab's path. The same shard reached under two names
  stops the engine with `native dense: duplicate split shard number`.
- **Other config changes:** `--native` and the vision `model` are the abliterated shard 1, and `tokenizer` is the new
  pack's.

Same 4 prompts, temperature 0, one start each:

| | Code | Math | Story | Refusal probe | Load |
|---|---|---|---|---|---|
| Stock | 122 tok/s | 121 | 68 | 83, refuses | 287 s |
| Abliterated | 115 tok/s | 116 | 69 | 90, answers | 195 s |

Speeds are within start-to-start noise, and both got the math right.

## What each patch does

Patches prepared with AI assistance. Strata is MIT (notice in [../LICENSES/Strata-LICENSE](../LICENSES/Strata-LICENSE)),
llama.cpp is MIT ([../LICENSES/llama.cpp-LICENSE](../LICENSES/llama.cpp-LICENSE)). The order to apply them is in
[step 3](#3-apply-the-patches).

| Patch | What |
|---|---|
| `patches/0001` native Windows build (icx) | CMake: `/fp:precise`, `/Qmkl:sequential`, C-safe warning flags; Level Zero SDK lookup; positioned reads with `ReadFile`; drop a CUDA-only shared-memory query; undo `<windows.h>` macros (`small`, `IN`, `OUT`, `near`, `far`) that clash with engine names; `memmem` fallback |
| `patches/0002` two-card expert parallel through host memory | every GPU shares one `sycl::context`; the shared expert-parallel regions are host USM in that context (one address for both cards). `STRATA_WIN_SHARED_CONTEXT=0` restores one context per device |
| `patches/0003` JIT build option for Xe2 | `STRATA_SYCL_XE2_JIT=ON` makes a JIT build define `STRATA_XMX_SG16` like the bmg AOT build does; `STRATA_SYCL_AOT_OPTIONS` passes extra ocloc options to an AOT build; `setenv` shim for two parity tests |
| `patches/0004` optional timer-resolution request | `STRATA_WIN_TIMER_MS=N` calls `timeBeginPeriod(N)` at engine start (default 1, 0 = off). Measured: no effect on decode (72 vs 72 tok/s); the configs set it to 0 |
| `slow-starts/0002` card 0's own expert rows in VRAM | with `STRATA_NIGHT_EP_PSUM=1` card 0 no longer aliases its row buffer to the host-memory exchange region; `STRATA_EP_PARTS_HOST=1` restores the old path. Sent upstream as [hotschmoe/Strata#1](https://github.com/hotschmoe/Strata/pull/1). Details in [slow-starts/](slow-starts/) |
| `slow-starts/0003` card 1's prompt rows buffer private | with `STRATA_EP_PREFILL_REDUCE=1` card 1's rows buffer is a private VRAM allocation (`ep_region_alloc_private`); `STRATA_EP_PREFILL_ROWS_HOST=1` restores the shared region. Rebased 2026-11-21 so it applies on top of `0002` (the old file was cut against upstream's `ep_mem.hpp`) |
| `esimd-prefill/0001` grouped prompt experts | per-layer type check, the expert-parallel card on the grouped path, the ESIMD GEMM through a C shim. Details in [esimd-prefill/](esimd-prefill/) |
| `patches/0005` `batch_poll` copy-stream check | `DPCT_CHECK_ERROR(copy_->ext_oneapi_empty())` is always 0, so the poll could report a window done while the copy stream still had work; now `empty() ? 0 : 1` like the compute-queue check above it. A/B served: speeds and draft counts identical. Live since 2026-11-17 |

`configs/` has the engine configs, with paths replaced by placeholders. `strata-iq3s-200k1-pf8k.json` is the live one.
The others are earlier setups: `strata-ep2-jit.json` (IQ3_XXS, int8, 2 x 200k), `strata-ep2-int8-32k.json`,
`strata-ep2-fp16-96k.json`.

## History

How the setup got here, oldest first. The sections after this one are the original write-ups, kept as they were;
numbers in them are from the build of their date.

- Base: `hotschmoe/Strata` branch `b70-night-20261016` @ `1c360526` (from SergiioB/b70-launcher PR #4).
- Model: ISTA-DASLab GSQ-RCO quants of Qwen3.8-Flash-Next, **IQ3_S** (84 GB, current) and IQ3_XXS (76 GB, earlier),
  sha256 checked; packs + MTP built on the same machine. Cards: two B70s (`level_zero:2,3`).
- Status (2026-10-17): **best setup = IQ3_S, 1 slot x 200k context, int8 KV, prompt chunk 8192, JIT build,
  `--ple-io mmap`**: decode ~99 tok/s, prompt read ~1,420 tok/s at 33.6k, answers correct, vision working, 2-hour
  soak through llama-swap clean. The AOT build with oneAPI 2026.0 miscompiles the int8 attention (see below).
  Not done: AOT with oneAPI 2026.1.
- Start-to-start speed lottery on the served build (78-89 vs 32-45 tok/s per start), fixed 2026-11-07: with EP psum,
  card 0's own expert rows went through the host-memory exchange region. Keeping them in VRAM gives ~106 tok/s on
  every start (8 of 8), output identical. Patch and details in [slow-starts/](slow-starts/); sent upstream as
  [hotschmoe/Strata#1](https://github.com/hotschmoe/Strata/pull/1). The 2026-11-01 file-cache guard is retired.
  The prompt read had the same kind of leak (card 1's rows buffer): ~1,550 tok/s at 37k on every start, was 775-1,552.
- Upstream Strata (Niko1221/Strata) v0.2.12 does not include this two-card expert parallel mode. Built on Windows, its
  helper-card mode (`--expert-cache-device1 auto`) decoded 32 tok/s because of an adaptive-tier check that ignores the
  helper's cache; fixed to 61 tok/s in Niko1221/Strata#5540 (2026-11-07).
- Prompt read +31%, live 2026-11-17: the grouped expert path now runs on IQ3_S (per-layer type check), on both cards
  (a `T_max == 12288` pin kept the second card off it), and on the llama.cpp fork's ESIMD grouped GEMM. 32k read
  1,680 -> 2,194 tok/s, decode unchanged. Patch, shim and numbers in [esimd-prefill/](esimd-prefill/).
- `batch_poll` copy-stream check (`patches/0005`), live 2026-11-17: a correctness cleanup found by reading the code;
  served A/B showed identical speeds and draft counts.
- 2026-11-21: this README rewritten as a recipe, checked against the live machine. `slow-starts/0003` rebased so the
  chain applies in order, the ESIMD kernel files added under `esimd-prefill/esimd/`, and the published config
  replaced with the live one (adds `STRATA_WIN_TIMER_MS=0` and the vision section).

## Results

Same 7-prompt set ([../bench/sbench.py](../bench/)), temperature 0, thinking off, 4x B70 machine, driver 8976.
Strata rows: 2 cards, MTP speculative decoding depth 4.

| Setup | Answers | Decode tok/s | Prompt read | Decode after long prompt |
|---|---|---|---|---|
| llama.cpp fork r62, 4 cards, UD-Q4_K_XL | correct | 60.6 | 748 tok/s @ 33.6k | 28.6 |
| **Strata IQ3_S, int8 KV, 1 x 200k, prefill 8192, JIT** | **correct** | **97.6 (+61%)** | **1,415 tok/s @ 33.6k (1.9x)** | **64.9 (2.3x)** |
| Strata IQ3_S, int8 KV, 2 x 112k, prefill 4096, JIT | correct | 100.8 | 881 tok/s @ 33.6k | 60.7 |
| Strata IQ3_XXS, int8 KV, 2 x 200k, prefill 12288, JIT (superseded by IQ3_S) | correct (identical to llama.cpp on 4 check prompts) | 108.2 (97.7 on a rerun) | 599-678 tok/s @ 33.6k | 58.4-58.7 |
| Strata, fp16 KV, 32k (superseded) | correct | 67.4 (+11%) | 570 tok/s @ 26.8k | 46.4 |
| Strata, int8 KV, 200k, AOT build (oneAPI 2026.0) | **wrong** (garbage) | 96.6 (invalid) | 682 @ 33.6k | 66.6 (invalid) |
| Strata, 1 card, int8 KV, AOT build | wrong | 12-20 | - | - |

The quants differ: Strata runs GSQ-RCO IQ3_S / IQ3_XXS, llama.cpp runs UD-Q4_K_XL. On the 4 check prompts
(`bench/squal.py`) the answers matched llama.cpp.

## Quant quality (IQ3_S vs IQ3_XXS)

Measured in llama.cpp (fork r62), 30 x 512-token chunks, KL divergence against UD-Q4_K_XL as the reference:

| Quant | Perplexity vs Q4 | Mean KLD | Median KLD | Same top token |
|---|---|---|---|---|
| GSQ-RCO IQ3_XXS (76 GB) | +3.5% +- 0.9% | 0.211 | 0.046 | 85.3% |
| **GSQ-RCO IQ3_S (84 GB)** | **+1.0% +- 0.7%** | **0.131** | **0.025** | **88.4%** |

The reference is itself a quant from a different family, so these KLD values overstate the distance to full
precision. IQ3_S is closer to the reference, reads prompts faster in Strata, and decodes ~7-10% slower than IQ3_XXS;
it replaced IQ3_XXS.

## Strata settings that matter

- `STRATA_NIGHT_PREFILL_GROUPED` must be **0 for IQ3_S** on the unpatched engine: the grouped prefill kernel does not
  support it (engine error "card 0 gate/up type 23", then a restart). IQ3_XXS needs it **on** (off: prompt read 239
  tok/s). With the [esimd-prefill/](esimd-prefill/) patch (2026-11-17) each layer checks its own types, so IQ3_S runs
  with it on: 32k read 1,680 -> 2,194 tok/s.
- Prompt chunk size matters a lot: IQ3_S with 4k chunks 881 tok/s, with 8k chunks 1,415 tok/s.
- IQ3_S at 2 x 200k and 2 x 131k does not fit on two 32 GB cards; 1 x 200k and 2 x 112k do.

## PLE table: use `--ple-io mmap`, not `direct` (2026-10-17)

The per-layer embedding (PLE) table of Qwen3.8-Flash-Next is 27 GB and is read on every token. With the upstream
recipe's `--ple-io direct` (unbuffered random reads straight from the SSD), decode drifted from ~98 to ~70 tok/s: first
on some starts (48, 65.6, 51.1 tok/s), then on every start, after the drive had taken ~130 GB of new writes. Same
expert split and same draft acceptance, just slower steps. The SSD's read latency had changed.

Ruled out first:
- heat: at most 66 C, no throttle reasons reported by Level Zero sysman;
- clocks: at the 2800 MHz maximum;
- CPU load (3%), system RAM, leaked GPU memory;
- the card pair (cards 0,1 also slow);
- host-memory exchange latency between the cards (56-64 us with `ep_probe`, unchanged);
- Windows timer resolution (`timeBeginPeriod(1)` A/B: no change);
- a reboot (still ~70).

llama.cpp stayed at 60.1 tok/s throughout; it keeps its PLE table in VRAM.

**Fix:** `--ple-io mmap`, so the OS file cache serves the table from RAM: 98.9 / 99.4 / 98.0 tok/s on three fresh
starts; through llama-swap 99.2 tok/s decode and 1,426 tok/s prompt read at 33.6k, vision working. It needs ~27 GB of
free system RAM for the cache; under memory pressure, reads fall back to the disk. The published
`strata-iq3s-200k1-pf8k.json` now uses `mmap`.

## Draft settings (IQ3_S)

IQ3_S, 1 x 200k, 2 cards, 7-prompt mean over 2 rounds:

| MTP draft setting | Decode tok/s |
|---|---|
| `--spec 4 --spec-min-p 0` (upstream default, kept) | 99.2 |
| `--spec 3` | 93.3 |
| `--spec 5` | 95.8 |
| `--spec 6` | 91.4 |
| `--spec 4`, p-min 0.1 | 98.7 |
| `--spec 4`, p-min 0.3 | 100.1 |

No setting beats the defaults beyond run-to-run noise.

## 2 slots vs 1 slot (IQ3_S)

IQ3_S, `--ple-io mmap`, 2 cards. Concurrency harness: 4 prompts x 512 tokens, second round counted. This harness
gives lower single-stream numbers than the 7-prompt set (~73-77 vs ~99 tok/s); compare within the table only.

| | 2 slots x 112k, prompt chunk 4096 | 1 slot x 200k, prompt chunk 8192 (default) |
|---|---|---|
| 1 stream, decode | 77.3 | 72.6 |
| 2 concurrent streams, per stream | 60.8 + 53.0 | 72.9 + 77.7 (served in turn) |
| 2 concurrent streams, aggregate | **82.2 tok/s** | 70.2 tok/s |
| Prompt read @ 33.6k | 889 tok/s | **1,421 tok/s** |

2 x 112k with prompt chunk 8192 does not fit (card 1 needs 31.38 of 30.16 GiB).

**Decision: keep 1 x 200k as the default.** Two slots only pay when requests overlap (+17% aggregate, each stream
~25% slower), and they always cost 37% of prompt speed and 88k of context. If two clients often overlap, a second
server entry with the 2-slot config is an option.

## 2-hour soak through llama-swap (2026-10-17)

IQ3_S, 1 x 200k, int8 KV, prompt chunk 8192, JIT build, 2 cards, vision on, served through llama-swap. Each cycle:
fixed-answer checks (JSON, capitals, counting), one vision request with a newly generated picture, and decode on the
prompt set; every few cycles a 112k-token prompt.

| Measure | Result |
|---|---|
| Cycles | 134, 0 errors, 0 engine restarts |
| Answer checks (JSON / capitals / counting) | 134 / 134 |
| Vision (new picture each cycle) | 134 / 134, median 4.3 s |
| Decode | 93.0 tok/s median (92.8-93.2), no drift over 2 hours |
| 112k-token prompt read (45 runs) | 1,429-1,434 tok/s, decode after it 68.7-69.0 |

One arithmetic question (17*23 + 144/12 = 403) is answered wrong with thinking off by **both** Strata (535) and the
llama.cpp UD-Q4_K_XL setup (405), and right with thinking on (403) by both: a model trait, not an engine bug.

Vision: a CPU image encoder (`strata-vision`) built from llama.cpp's `mtmd` at the engine's pinned llama.cpp commit,
with ISTA-DASLab's BF16 mmproj, 24 threads, 300 image tokens per picture.

## Prompt chunk size sweep (IQ3_S)

IQ3_S, 1 x 200k, int8 KV, JIT build, 2 cards, driver 8976; `--prefill` = prompt chunk in tokens; same 7-prompt set,
one round each. "Free" = what the engine reported free on the fuller card after loading.

| `--prefill` | Fits | Decode tok/s | Prompt read @ 33.6k | Decode after it |
|---|---|---|---|---|
| 6144 | yes (1,851 MiB free) | 102.3 | 1,247 | 70.7 |
| 7168 | yes (1,835 MiB) | 98.4 | 1,435 | 54.1 |
| **8192 (kept)** | yes (1,815 MiB) | 99.0 | 1,417 | 65.7 |
| 10240 | barely (1,778 MiB) | 35.8 | 517 | 26.2 |
| 12288 | no (card 1 needs 30.46 of 30.16 GiB) | - | - | - |

At 10240 card 1 sits at its memory limit and everything slows ~3x. Decode-after numbers vary about +-8 tok/s run to
run.

Long prompt with 8192: **112,142 tokens read in 78.3 s = 1,433 tok/s**, decode after it 72.2 tok/s. For comparison,
the llama.cpp fork (Flash-Next MTP, 4 cards, cross-card pipeline) read an ~87k prompt at ~685 tok/s.

**Lesson:** leave memory headroom. A config that "fits" with a card at its limit can be 3x slower than one step
smaller.
fp16 KV fits 96k context on two cards (1.6 GB free); 131k does not (card 1 ~0.85 GB short).

**Lesson:** a speed number only counts after an answer check. The broken AOT build looked fast (96.6 tok/s) because
garbage output is easy for the MTP draft to predict, so acceptance went up and inflated tok/s.

## The int8 KV bug: an AOT miscompile (solved)

With the AOT build (oneAPI 2026.0 `ocloc`, device `bmg-g31`), int8 KV gave wrong answers while fp16 KV was correct
with everything else equal. Ruled out on the way: the tokenizer (token ids identical to llama.cpp), the download
(sha256 match), PLE file I/O, the prompt-attention kernel (`STRATA_PROMPT_ATTN_OLD=1` still wrong), the experimental
"night" switches (minimal env still wrong, output "!!!!"). The `kv_q8`, `qsa` and `kv_steps` parity tests passed.

Cause: the AOT build miscompiles the **batched decode attention over int8 KV** used by the MTP verify step.

- `qsa_verify_batch_parity`, "one vs row": half the outputs wrong (including `inf`), 14 failures.
- `kv_hybrid_parity`: batched attention FAIL.
- The same sources JIT-compiled by the Windows driver (32.0.101.8976) pass **bitwise**, and the engine answers
  correctly.
- Adding `-ze-opt-greater-than-4GB-buffer-required` to the AOT build does not help.

Not tested: AOT with oneAPI 2026.1 (the version the upstream B70 work used).

Parity tests with the AOT build: 21 of 23 pass. Failing: `gr_parity` (fused GR read + q8_1, `STRATA_QFUSE` path:
"not written") and `s2_expert_grouped_parity` (the Q2_0 experts it covers are the MTP draft layer only). Not yet
re-run under JIT; they may be the same compiler bug.

## Windows / Level Zero findings

Measured with [../reproducers/ep-probe/](../reproducers/) on two B70s:

- No IPC: `zeMemGetIpcHandle` returns `0x78000003` (unsupported feature).
- `zeDeviceCanAccessPeer` = 0 between B70s.
- A kernel on one card touching the other card's device memory: `DEVICE_LOST`.
- Driver-imported host pointers used from another context: also `DEVICE_LOST`.
- Host USM allocated inside **one** context shared by both cards works for both cards. Patch `0002` is built on that.

So on Windows, card-to-card traffic has to go through host memory. Linux behaviour was not tested here.

## Other notes

- With default settings the engine hangs: verify waits on a host doorbell and hits a timeout. The PR's
  `STRATA_VERIFY_DEVICE_PLAN=1` + `STRATA_VERIFY_NO_HOST=1` avoid it (set in all configs).
