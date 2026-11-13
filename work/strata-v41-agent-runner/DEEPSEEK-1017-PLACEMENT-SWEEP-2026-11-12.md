# 1017 — SYCL placement sweep: the baseline was wrong, and the disk theory is dead (2026-11-12)

Supersedes the numbers and the prime suspect in `DEEPSEEK-1017-BLOCKER.md`. That file's
conclusion — *"the batched prompt path is not engaging because the fused HC op is disabled"* —
**does not survive measurement**. The fused ops all engage; the baseline was a cold-start artifact;
and the model is not streaming weights from disk during decode.

Everything below is from `llama-bench` on Zeus against the same pack, same build, same flags, with
only one variable changed per arm.

| | |
|---|---|
| Pack | `DeepSeek-V4.1-Flash-1017-GSQ-RCO-IQ2_XXS-0000{1..4}-of-00004.gguf` |
| Size | 138,238,904,160 B = 128.75 GiB (4 shards, current generation — shard 1 carries the chat template) |
| Params | 551.88 B, IQ2_XXS 2.0625 bpw, 40 blocks / 41 offloadable |
| Build | `C:\llamacpp-v41` @ `de5122d` (50), `build-sycl\bin` |
| Flags (all arms) | `-ngl 38 -sm layer -t 12` |
| Engram | `DeepSeek-V4.1-Flash-Engram-IQ4_NL.gguf` (103.00 GiB) **never loaded** — see §4 |

-

## 1. TL;DR

| Claim in the old doc | Status |
|---|---|
| Baseline is `pp32 0.33 / tg8 3.05` | **Cold-start artifact.** Warm is `pp32 0.65 / tg8 3.92` |
| Fused DeepSeek V4 HC pre is disabled → prefill collapse | **Disproven.** All 7 fused ops report `enabled` |
| Prefill is 9.2x slower than decode | **Still inverted, but 3.9x**, not 9.2x — and not caused by HC |
| "The current run is SSD-bound" (memory-budget doc) | **Disproven.** Decode reads ~30 MB/s from disk, not ~6 GiB/s |
| Model is too big for 128 GiB VRAM | **True but irrelevant to decode.** It fits at 96%; decode is a launch-overhead problem |

The two live defects are now separable:

1. **Measurement contamination** — `--no-warmup -r 1` understates this build by 1.5–3x.
2. **A real prefill deficit plus a decode deficit** that are *not* memory-hierarchy problems. Graph
   capture is compiled in and off by default — and, critically, **structurally unavailable across 4
   devices** (§6). That is the most likely reason a single 5090 beats four B70s here.

## 2. Arms

| Arm | Change | pp32 | tg8 | Verdict |
|---|---|---|---|---|
| A | baseline, `-p 32 -n 8 -r 1 --no-warmup` | 0.22 | 2.53 | contaminated |
| F | `GGML_SYCL_ENABLE_VMM=0` | 0.12 | 2.94 | VMM exonerated |
| **G** | **warmup + `-r 3`**, otherwise = A | **0.65** | **3.92** | **the honest baseline** |
| I | decode only, `-p 1 -n 8 -r 2`, warm, + disk counter | — | **3.26** | weights are resident |
| J | `GGML_SYCL_ENABLE_GRAPH=1` | 0.64 | 3.96 | **lever inert** — graphs refused on multi-device (§6) |

### Warm-up is not optional

```
pp32:  0.22 -> 0.65   (2.95x)
tg8:   2.53 -> 3.92   (1.55x)
```

Both arms used identical flags; the only difference is warmup and rep count. **Any 1017 number
recorded with `--no-warmup -r 1` is wrong by a factor of 1.5–3x** and should be discarded, including
the `0.33 / 3.05` pair in the blocker doc and the ledger entry it came from.

### VMM is not implicated

Arm F changed placement by **zero bytes** versus A — same 128.54 GiB, same per-device split. VMM is
an allocation strategy, not a residency strategy. Prefill got worse, decode marginally better; noise.

## 3. The fused-op suspect is dead

`resolve_fused_ops` (`src/llama-context.cpp:610`) probes 7 fused ops for this architecture. On
`de5122d` with this pack, **all seven report `enabled`**:

```
Flash Attention, HC pre, HC comb, HC post, top-k mask   -> enabled
zero "not supported there", zero "set to disabled"
```

The blocker doc's line 73 quote — `W resolve_fused_ops: fused DeepSeek V4 HC pre not supported, set
to disabled` — is **not reproducible on the current build**. Whatever produced it (an older binary,
a different pack revision, or a stale log) is no longer the state of the world. The HC-fallback port
proposed in §6 of that doc is therefore **not the highest-value work** and should be stood down.

## 4. The Engram is not part of the run

`done_getting_tensors` (`src/llama-model-loader.cpp:1402`) logs:

```
skipping 10 Engram/PLE tensor(s) this architecture does not claim
(Engram is optional; continuing without it)
```

103.00 GiB sits on disk unused. Its metadata is present (`engram.present = true`, `layer_ids
[1,14]`, 384M embeddings/layer, `head_dim 256`, 8 heads, 16M vocab) but the fork deliberately leaves
the ISTA-DASLab Engram tensors unclaimed — the `kEngramMarks` allowlist in the loader. This is why
the run fits at all. **Any arm that sets `-lzm`/Engram flags is measuring nothing** — arms B and C
were staged on that premise and were dead weight.

## 5. Placement, and why "too big" is the wrong frame

```
SYCL1            32,121.4 MiB  (31.37 GiB)
SYCL0            31,059.7 MiB  (30.33 GiB)
SYCL2            30,504.1 MiB  (29.79 GiB)
SYCL3            28,627.3 MiB  (27.96 GiB)
CPU_Mapped        9,310.6 MiB  ( 9.09 GiB)
TOTAL           131,623.0 MiB  (128.54 GiB)   offloaded 38/41 layers
KV buffers           10.0 MiB total
compute buffers   1,108.8 MiB total
```

128.75 GiB of weights against 128 GiB of VRAM: the model is **0.75 GiB larger than total VRAM** before
a single byte of KV or compute. It lands at ~96% occupancy with 5.7 GiB headroom, which is why KV is
10 MiB. At the model's native `context_length 1,048,576` KV alone needs ~47 GB. **The model cannot run
its intended context on this box.** That part of "too big" is unambiguously true.

But it does not explain throughput, because MoE sparsity means we never touch all 128 GiB per token:

```
per token = 40 blocks x 6 of 384 experts x 35.39 M params = 8.49 G params
          = 1.86 GiB of expert traffic per token
```

`3.92 tok/s x 1.86 GiB = 7.3 GiB/s` — which is **2.5x above** the ~3 GB/s NVMe ceiling that the
SSD-bound theory assigned. That alone rules the theory out. §7 measures it directly.

The 9.09 GiB `CPU_Mapped` is `token_embd.weight` (q5_K) plus 79 others, the tail of `-ngl 38` of 41.
The loader message about it is DEBUG-level and is **expected partial-offload behaviour, not a defect**:

```
tensor 'token_embd.weight' (q5_K) (and 79 others) cannot be used with
preferred buffer type SYCL_Host, using CPU instead
```

## 6. Kernel launch overhead: the lever is structurally unavailable (arm J)

The arithmetic that motivated the arm:

```
3.26 tok/s  ->  307 ms per token
max_nodes   =   31,936   (sched_reserve)
307 ms / 31,936  =  9.6 microseconds per node
```

9.6 us per node is textbook launch overhead, and the backend banner says capture is compiled in but
off:

```
GGML_SYCL_ENABLE_GRAPH: 0     <- off
GGML_SYCL_GRAPH: yes          <- supported
```

So arm J set `GGML_SYCL_ENABLE_GRAPH=1`, identical to G otherwise. Result:

| Arm | pp32 | tg8 |
|---|---|---|
| G (baseline) | 0.65 | 3.92 |
| **J (GRAPH=1)** | **0.64** | **3.96** |

**Zero effect — because the feature declined to engage.** The log contains **343** occurrences of

```
check_graph_compatibility: disabling SYCL graphs due to multiple devices
```

and **zero** `enabling SYCL graphs`. The cause is a hard architectural refusal at
`ggml/src/ggml-sycl/ggml-sycl.cpp:6860`:

```cpp
static bool check_graph_compatibility(ggml_backend_sycl_context * ctx, ggml_cgraph * cgraph) {
    if (ggml_sycl_info().active_device_count > 1) {
        // A sycl_ex::command_graph object can only be created for a single device
        GGML_LOG_DEBUG("%s: disabling SYCL graphs due to multiple devices\n", __func__);
        return false;
    }
```

`sycl_ex::command_graph` cannot span devices. **Therefore graph capture and multi-GPU splitting are
mutually exclusive on this backend.** The 1017 cannot be a single-device run (128.75 GiB of weights,
32 GiB per card), so it can never use graphs — every one of 31,936 nodes is submitted individually,
every token, forever, on this hardware.

This is the sharpest form of the "Intel/Windows quirk" question. A single 5090 pays the launch
overhead once per node on one device and can hide it behind CUDA graphs; a four-card `-sm layer` run
pays it per node *plus* 38 device-boundary copies per token, and can hide neither.

### How to actually test the hypothesis

The 1017 cannot answer this, so don't spend card cycles trying. Use a model that fits **one** card and
A/B `GGML_SYCL_ENABLE_GRAPH=0` vs `1` on it. If graphs give a large win there, the launch-overhead
theory is confirmed and the 1017's ceiling is explained by §6's refusal rather than by its size. This
is cheap and does not require the big pack.

### Corroborating asymmetry

`sched_reserve` compute buffers at the pp32 shape are wildly lopsided, suggesting a serial
single-device prefill stage:

```
SYCL0 956.69 MiB  |  SYCL1 60.29  |  SYCL2 45.97  |  SYCL3 45.88
```

at the tg8 shape all four drop to ~15 MiB.

### Second lever, still worth an arm: `GGML_SYCL_DEV2DEV_MEMCPY`

With `-sm layer` across four devices, activations cross a device boundary at every layer split —
**38 crossings per token**. The default is `DEV2DEV_MEMCPY_SYCL` (0, "SYCL API"), which on Windows
stages through host memory; 1 selects Level Zero. Unlike graph capture, this lever is *not* refused on
multi-device, so it is a real candidate. Arm K (`GRAPH=1` + `DEV2DEV_MEMCPY=1`) is staged; the
`GRAPH=1` half is now known to be a no-op, so read it as a `DEV2DEV_MEMCPY` test.

## 7. Disk measurement: decode does not read disk

Instrument: `\PhysicalDisk(_Total)\Disk Read Bytes/sec`, sampled every 5 s via `typeperf` for the whole
of arm I (`-p 1 -n 8 -r 2`, warm, wall 20:01:49 → 20:08:07 = 378 s). `typeperf -q` fails on this box
("The specified object was not found"), but direct sampling works.

| Phase | Window | Mean | GB |
|---|---|---|---|
| burst | 20:01:57–20:02:47 | 2.6–5.2 GB/s | ~104 |
| sustained | 20:03:02–20:05:12 | 707 MB/s | 92.1 |
| trough | 20:05:17–20:05:37 | 137 MB/s | 2.8 |
| sustained | 20:05:42–20:06:47 | 449 MB/s | 29.2 |
| **decode** | **20:06:57–20:07:43** | **~30 MB/s** | **1.4** |
| teardown | 20:07:48–20:08:43 | 1.1 MB/s | 0.06 |

**Decode is disk-idle.** If it were streaming experts it would need ~6 GiB/s; it reads ~30 MB/s, and
that 1.4 GB is a single blip at 20:07:38 consistent with first-touch page faults of the CPU-mapped
tensors rather than per-token traffic. The weights are genuinely resident in the cards.

### Two corrections this measurement forces

**(a) "SSD-bound" is retired.** The conclusion in the memory-budget analysis — `1.5 tok/s x 1.86 GiB =
2.8 GiB/s`, "a single NVMe drive's random-read throughput" — was a coincidence, not a mechanism. We
measure 3.26–3.92 tok/s, *above* the 1.6 tok/s ceiling that theory predicts.

**(b) Load is not 0.4 GB/s.** An earlier read of the same counter claimed load was disk-bound at
~0.4 GB/s. Wrong: it is **~807 MB/s average with 2.6–5.2 GB/s bursts**. 138 GB at 0.4 GB/s would be
345 s; the observed load window is ~295 s, which does not fit.

### New finding: 1.73x read amplification

```
bytes read during arm I : 239.8 GB
model size              : 138.2 GB
amplification           : 1.73x
```

The loader reads the pack **1.7 times over**. The mechanism is almost certainly that the model
(138.2 GB) is larger than system RAM (112 GB), so the mmap→device copy pass evicts its own page cache
and re-reads from NVMe. This is why load takes ~295 s even though the drive peaks at 5 GB/s, and it is
an independent target: any fix that avoids the double pass cuts every arm's wall time by ~40%.

## 8. What is genuinely still open

| Item | Status |
|---|---|
| Arm J — `GGML_SYCL_ENABLE_GRAPH=1` | **done, null** — lever refused on multi-device (§6) |
| Single-device graph A/B (model that fits one card) | **not run — the only way to test §6** |
| Arm K — `GRAPH=1` + `DEV2DEV_MEMCPY=1` | staged; effectively a DEV2DEV test now, the GRAPH half is a no-op |
| Dose-response `-ngl 39` / `-ngl 40` | not run; tests whether the 3 CPU-resident layers bound decode |
| Load read-amplification fix | not started (§7) |
| IQ1_M (112.4 GiB) as a fits-properly alternative | not run |
| Strata `sycl/src/dsv41/` | still 0 lines ported — unchanged |
| DSpark drafter for 1017 | still absent (zero `mtp.*` in the pack) — unchanged |

Upstream items still open: #31871 (SYCL FP8 ops), #31313, #31505, #30944 (DSV4.1 output corruption on
cached prefix), #31292.

## 9. Reproduce

```bat
cd /d C:\llamacpp-v41\build-sycl\bin
set "PATH=C:\Program Files (x86)\Intel\oneAPI\2026.0\bin;%PATH%"
REM warmup and r=3 are mandatory - without them the build reports 1.5-3x low.
llama-bench.exe -m D:\AI\Models\dsv41\DeepSeek-V4.1-Flash-1017-GSQ-RCO-IQ2_XXS-00001-of-00004.gguf ^
  -ngl 38 -sm layer -t 12 -p 32 -n 8 -r 3 -v
```

Launch notes learned the hard way on Zeus:

- Run arms as **`.bat` via `cmd.exe /c`**. Invoking `llama-bench.exe` directly from WSL bash yields
  `rc=188` (`0xBC`, `STATUS_INVALID_DISPOSITION`) with **zero output** — a launch artifact, not a
  binary fault.
- Redirect targets must be **Windows paths**. `/mnt/d/...` fails with "The system cannot find the
  path specified."
- `cmd.exe` leaves a phantom lock on `D:` scripts; base64-transfer each `.bat` fresh rather than
  overwriting in place.
- `typeperf -q` cannot resolve counter paths on this box, but direct sampling
  (`typeperf "\PhysicalDisk(_Total)\Disk Read Bytes/sec" -sc N -si 5`) works fine.
- Do not set `SYCL_CACHE_PERSISTENT=1` — upstream first-decode SIGSEGV.
- Do not use `--mlock` here: it would try to lock ~128 GiB of mmap'd pages and OOM the host.
