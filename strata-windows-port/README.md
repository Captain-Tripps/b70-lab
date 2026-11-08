# Strata on native Windows

[Strata](https://github.com/hotschmoe/Strata) is a SYCL inference engine with B70-specific work (two-card expert
parallel, MTP, int8 KV). It targets Linux. These four patches make it build and run natively on Windows 11 with
Intel's `icx` compiler, including two-card expert parallel and int8 KV.

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
- Upstream Strata (Niko1221/Strata) v0.2.12 does not include this two-card expert parallel mode. Built on Windows, its
  helper-card mode (`--expert-cache-device1 auto`) decoded 32 tok/s because of an adaptive-tier check that ignores the
  helper's cache; fixed to 61 tok/s in Niko1221/Strata#5540 (2026-11-07).

Patches (prepared with AI assistance; Strata is MIT, notice in
[../LICENSES/Strata-LICENSE](../LICENSES/Strata-LICENSE)). Apply in order with `git apply`:

| Patch | What |
|---|---|
| `0001` native Windows build (icx) | CMake: `/fp:precise`, `/Qmkl:sequential`, C-safe warning flags; Level Zero SDK lookup; positioned reads with `ReadFile`; drop a CUDA-only shared-memory query; undo `<windows.h>` macros (`small`, `IN`, `OUT`, `near`, `far`) that clash with engine names; `memmem` fallback |
| `0002` two-card expert parallel through host memory | every GPU shares one `sycl::context`; the shared expert-parallel regions are host USM in that context (one address for both cards). `STRATA_WIN_SHARED_CONTEXT=0` restores one context per device |
| `0003` JIT build option for Xe2 | `STRATA_SYCL_XE2_JIT=ON` makes a JIT build define `STRATA_XMX_SG16` like the bmg AOT build does; `STRATA_SYCL_AOT_OPTIONS` passes extra ocloc options to an AOT build; `setenv` shim for two parity tests |
| `0004` optional timer-resolution request | `STRATA_WIN_TIMER_MS=N` calls `timeBeginPeriod(N)` at engine start (default 1, 0 = off). Measured: no effect on decode (72 vs 72 tok/s); the configs set it to 0 |

`configs/` has the engine configs used below (paths replaced with placeholders): `strata-iq3s-200k1-pf8k.json` (the
current best setup), `strata-ep2-jit.json` (IQ3_XXS, int8, 2 x 200k), `strata-ep2-int8-32k.json`, `strata-ep2-fp16-96k.json`.

## How to run it

**1. Build (JIT).** In a `vcvars64` (MSVC) environment plus the oneAPI 2026.0 component `env\vars.bat` files
(tbb, umf, dnnl, mkl, dpl, ocloc, compiler), with patches 0001-0004 applied:

```
cmake -B build-win -S sycl -G Ninja -DCMAKE_BUILD_TYPE=Release -DSTRATA_SYCL_AOT= -DSTRATA_SYCL_XE2_JIT=ON ^
      -DSTRATA_SYCL_PARITY=OFF -DCMAKE_C_COMPILER=cl -DCMAKE_CXX_COMPILER=icx
cmake --build build-win --target strata
```

An empty `STRATA_SYCL_AOT` means the GPU driver compiles the device code at first use. Do not use the oneAPI 2026.0
AOT build with int8 KV (wrong answers). On driver 32.0.101.8976 the engine was ready in under a minute. Put the oneAPI
runtime DLLs next to `strata.exe` or on `PATH`.

**2. Model files.** The config points at four things besides the GGUF: a pack, the MTP draft layer, a draft
vocabulary and an expert profile. Download ISTA-DASLab's `Qwen3.8-Flash-Next-GSQ-RCO-GGUF` IQ3_S, both shards, into one
folder (check them against the sha256 sums on the model page). Then, from the Strata checkout, in its Python venv:

```
set STRATA_GGUF_PY=<STRATA_SOURCE_DIR>\build-win\_deps\strata_llamacpp-src\gguf-py
set PYTHONUTF8=1

rem pack (the dense weights, the tokenizer folder the config names, the expert index)
python tools\iq_pack.py --gguf <MODELS_DIR>\...\IQ3_S\Qwen3.8-Flash-Next-GSQ-RCO-IQ3_S-00001-of-00002.gguf ^
       --out <STRATA_DATA_DIR>\packs\iq3_s

rem MTP draft layer: fetch (~5 GB; the fetch can drop, so re-run it until it succeeds), verify, pack, runtime layer
python tools\mtp_fetch.py fetch --out <STRATA_DATA_DIR>\mtp
python tools\mtp_fetch.py verify --out <STRATA_DATA_DIR>\mtp
python tools\mtp_pack.py --src <STRATA_DATA_DIR>\mtp --experts q2_0 --out <STRATA_DATA_DIR>\mtp\mtp-q2_0.gguf
python tools\mtp_rt.py --gguf <STRATA_DATA_DIR>\mtp\mtp-q2_0.gguf --out <STRATA_DATA_DIR>\mtp\rt
```

`gguf-py` exists after the step 1 build has fetched Strata's pinned llama.cpp. `iq_pack.py` needs shard 2 in the same
folder as shard 1. The draft vocabulary (`data\draft_vocab_en.bin`) and the expert profile
(`data\expert-profile-sycl.bin`) ship in the Strata checkout; nothing to build. The config's `--mtp` is the `rt`
folder, `tokenizer` is the pack's `tokenizer` folder.

**3. Engine config essentials** (full file: `configs/strata-iq3s-200k1-pf8k.json`):

| Setting | Value | Why |
|---|---|---|
| `--max-context` / slots | `200000`, 1 slot (`"parallel": 1`) | 2 x 200k does not fit IQ3_S on two 32 GB cards |
| `--kv` | `int8` | needs the JIT build |
| `--prefill` | `8192` | prompt chunk; 10240 sits at card 1's memory limit and runs ~3x slower |
| `--ple-io` | `mmap` | `direct` reads the 27 GB PLE table from the SSD every token; needs ~27 GB free RAM |
| `--spec` / `--spec-min-p` | `4` / `0` (upstream defaults) | other values were equal or worse |
| `--expert-parallel-device` | `1` | the second card |
| `STRATA_NIGHT_PREFILL_GROUPED` | `0` | the grouped prefill kernel does not support IQ3_S (IQ3_XXS needs it on) |
| `STRATA_VERIFY_DEVICE_PLAN`, `STRATA_VERIFY_NO_HOST` | `1`, `1` | without them verify waits on a host doorbell and hangs |
| `ONEAPI_DEVICE_SELECTOR` | e.g. `level_zero:2,3` | the two cards to use |

**4. Vision (optional, CPU encoder).** `strata-vision.exe`, built from llama.cpp's `mtmd` tool at the llama.cpp
commit the engine pins, with ISTA-DASLab's BF16 mmproj. Config section:

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

**5. Serve.** Strata's OpenAI-compatible server reads the engine config:

```
python sycl\serve\server_intel.py --engine strata --config <CONFIG.json> --host 127.0.0.1 --port <PORT>
```

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

`cmdStop` with `/T` ends the Python server and the `strata.exe` engine under it. One model swap logged
`stop signal failed: exit status 255` although both processes did end; check the process list after a swap if in doubt.

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

- `STRATA_NIGHT_PREFILL_GROUPED` must be **0 for IQ3_S**: the grouped prefill kernel does not support it (engine
  error "card 0 gate/up type 23", then a restart). IQ3_XXS needs it **on** (off: prompt read 239 tok/s).
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
