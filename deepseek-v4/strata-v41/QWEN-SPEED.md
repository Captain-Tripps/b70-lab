# Qwen speed on the v0.2.7 SYCL build — state, theory, next steps

Written 2026-10-27 as a session checkpoint. Companion to
[PORT-SCOPE.md](PORT-SCOPE.md) (the dsv41 port) — this file is about the **Qwen** engine that the
new build actually runs today.

Everything below is measured on GPU-BOX unless marked as theory.

-

## 1. Where we are

`D:\strata-dsv41-port` is a **v0.2.7** worktree (`5e8a4cca7`) that builds clean on Windows.

| Item | Value |
|---|---|
| Binary | `D:\strata-dsv41-port\build-jit\strata.exe`, 44,995,584 B |
| Engine version | `strata 0.1.52` |
| Build config | JIT (`-DSTRATA_SYCL_XE2_JIT=ON`), parity off |
| Build result | `BUILD_EXIT=0`, 0 compile errors, 0 link errors |
| Runtime requirement | **must** run inside `setvars.bat --force`; bare invocation dies `0xC00004BC` |

Six Windows build defects were fixed to get here; all are recorded in
[PORT-SCOPE.md §13](PORT-SCOPE.md) and issue #19. They are upstreamable and are independent of the
dsv41 port.

-

## 2. The Qwen model — measured from the GGUF header

Not inferred from file size; the tensor dimensions were summed directly out of the GGUF.

| Field | Value |
|---|---|
| Name | Qwen3.8-Flash-Next GSQ-RCO |
| Quant | IQ3_S (ISTA-DASLab), `general.file_type` 26 |
| Architecture | `qwen4exp` — *"A Preview of the Qwen4 Architecture"* |
| Weights | **125.7 B** params, 1,223 tensors |
| PLE table | **+51.2 B** (`per_layer_token_embd.weight`, shard 2) |
| Total | **~176.9 B** |
| Files | 54.81 GB + 28.80 GB = **83.62 GB / 77.88 GiB** |
| Effective bpw | **~3.8 bits/weight** |
| Layers | 48 |
| Experts | **512 per layer, 10 active** per token, +1 shared |
| Expert FFN | 640 |
| Hidden / heads | 2560, 24 heads, 2 KV heads, 4 indexer heads |
| Context | 262,144 native |
| PLE | 16 heads, ~20 M vocab each |
| Calibration | imatrix, 1000 chunks, 926 entries |

**Discrepancy worth knowing:** `general.size_label` says `512x56B`, but 512 x 56B is 28,672B while
the file is 176.9B. The label is not a parameter count. Do not quote "56B" — it contradicts the
header's own tensors by 3x.

-

## 3. What it actually runs at today

```
GPU 0: Intel(R) Arc(TM) Pro B70 Graphics, compute capability 20.2
expert cache: 10,618 slots, 20.15 GiB of VRAM, PROFILE policy (routing frequency, no eviction)
profile fill: 20.15 GiB in 21.1 s (1.02 GB/s, pipelined); 10,596 of 10,596 slots, slot 0 verified
R4 hit path ON - resident experts are computed on the GPU

decode     32 tokens in 2470.1 ms  ->  12.95 tok/s
prefill     7 tokens in 3753.0 ms  ->   1.87 tok/s  (TTFT 20003.5 ms)
EXIT=0
```

Compared to the lab's known-good run:

| Setup | Cards | Decode | Prefill |
|---|---:|---:|---:|
| Lab `win-r3-jit`, IQ3_S, int8 KV, 1x200k | **2** | **97.6 tok/s** | **1,415 tok/s @ 33.6k** |
| v0.2.7 today | **1** | **12.95 tok/s** | 1.87 tok/s @ 7 tok (not comparable) |

### Why it is 7.5x slower — and it is not an upstream regression

The lab config used `--expert-parallel-device 1` to engage the second card. **That flag no longer
exists in v0.2.7**; it was replaced by `--peer-device`, and `--peer-device` is a **stub in the SYCL
port**:

```
strata generate: --peer-device: the second-GPU expert tier is not ported to SYCL yet
EXIT=1
```

`sycl/CMakeLists.txt:280`: `remote_expert_opt_stub.cpp ... (a stub in the port: no second GPU tier
yet)`.

So this ran on **one** B70 of the four. 12.95 tok/s single-card is plausible and is not evidence that
v0.2.7 is slower than the deployed tree.

### Caveats on these numbers

- **7-token prompt** — the 1.87 t/s prefill is one tiny chunk; not comparable to 1,415 t/s @ 33.6k.
- **TTFT 20.0 s** includes engine start, the 21.1 s profile fill, and PLE setup. Not a token metric.
- **One sample, no variance.** Per `FINDINGS.md` W-042, single samples on this box are unreliable
  (bimodal throughput was measured on the llama.cpp path). Treat as indicative.

### Semantic change, not a rename

`--expert-parallel-device` → `--peer-device` is **not** a straight rename. Upstream's peer is an
adaptive **expert-cache tier**; the lab's flag was symmetric **expert parallelism**. Whether
upstream's newer design reaches the same throughput is unmeasured.

-

## 4. Theory: what four cards would look like

Reasoning from measured constants, not benchmarks. Flagged as theory throughout.

### 4a. The structural fact that reframes it

```
10,618 slots = 20.15 GiB  ->  2.04 MB per expert
24,576 experts (512 x 48) x 2.04 MB  =  50.1 GB   (the whole expert set)
```

Four cards = **136.6 GB** VRAM. Two cards = ~65 GB.

**Two cards already reach effectively full expert residency.** Cards 3 and 4 buy *compute*, not
cache. Which means 97.6 t/s was never cache-limited — it is the **one-card compute ceiling**.

### 4b. Why 97.6 is arithmetic, not a tuning result

From the engine's own measured int8 kernel timings (~21 µs per expert at 16 rows):

```
480 expert calls/token (48 layers x 10 active)
x 21 us  = 10.1 ms/token  ->  99 tok/s
```

Measured 97.6. Effectively exact. **Decode on Qwen is expert-matmul-bound** once residency is
complete.

### 4c. So 4 cards divide the 480, they do not grow the cache

| Split | Expert calls/card | Expert time | Compute ceiling |
|---|---:|---:|---:|
| 1 card | 480 | 10.1 ms | ~99 t/s |
| 2 cards | 240 | 5.0 ms | ~198 t/s |
| 4 cards | 120 | 2.5 ms | ~396 t/s |

The lab's 97.6 on two cards happened because its EP was **enabling residency**, not halving expert
work. Residency alone hit the one-card ceiling.

### 4d. The binding constraint: Windows has no peer access

Measured by the lab's `ep_probe`: **56–64 µs host round trip** per exchange. Over 48 layers:

```
48 x 57 us = 2.74 ms/token  ->  365 t/s ceiling from exchange alone
```

Serialized with compute:

```
2.52 ms compute + 2.74 ms exchange = 5.26 ms  ->  ~190 t/s
```

### 4e. Prediction

| Confidence | 4-card decode | Condition |
|---|---|---|
| **Likely** | **180–220 t/s** | host exchange at ~57 µs, serialized |
| Optimistic | 300–380 t/s | device-spin on system-scope flags gets exchange <10 µs |
| Hard ceiling | ~396 t/s | exchange became free (it will not on Windows) |

Midpoint ~190 t/s is **~2x the two-card number, not 4x** — the exchange fabric eats the difference.

### 4f. What else visibly changes

- **Prefill scales better than decode** (batched, exchange amortised): **~2,200–2,700 t/s** vs 1,415
  on two cards. Four cards help most here.
- **Context**: ~50 GB experts + ~2.5 GB dense leaves ~119 GiB free across four cards. 200k
  comfortable, 400k+ plausible. The "2 x 112k does not fit" problem disappears.
- **Load**: full 50 GB profile fill at the measured 1.02 GB/s -> **~55–70 s** to first token.
- **VRAM per card**: ~15–18 GB experts + ~6–8 GB dense/KV + buffers, under 30 GB each. Real headroom —
  unlike the 1017 pack's ~955 MiB overrun.

### 4g. What breaks first

1. **Exchange latency** — everything hinges on it.
2. **RAM** — the PLE table needs ~27 GB via `--ple-io mmap`, against 95.87 GiB total. Tightest
   resource in the setup; the lab already watched decode collapse 98 -> 70 t/s when the drive got
   busy under the *unbuffered* path.
3. **Router serialisation** — routing is one card per layer. Fine at 190 t/s; the wall near 400.

-

## 5. Next steps for Qwen

Ordered by information value per unit of effort. **None started.**

### QWEN-1 — establish a real single-card baseline (cheap, do first)

The 12.95 t/s number is one sample on a 7-token prompt. Before any comparison is meaningful:

- [ ] Run the lab's 7-prompt set (`bench/sbench.py`) on one card, `-r 3` where applicable.
- [ ] Use a prompt long enough that prefill is measurable (>= 2k), so pp and tg are separable.
- [ ] Record per-sample, not mean-only (see `FINDINGS.md` W-042 on bimodal throughput).
- [ ] Sweep `--max-context` / `--kv` / cache size on **one** card to find the single-card optimum.

**Acceptance:** a variance-bounded single-card pp/tg figure that a later 2-card and 4-card run can
be compared against honestly.

### QWEN-2 — identify what the SYCL port is missing for multi-GPU

Read-only investigation, no code:

- [ ] Diff `sycl/src/core/peer_experts.cpp` and `remote_experts.cpp` against the CUDA originals in
      `src/core/`.
- [ ] Determine whether the stub is (a) not written, (b) written but disabled, or (c) blocked on a
      Level Zero capability.
- [ ] **Re-measure the host-exchange round trip on this build.** The 57 µs figure is from the
      lab's `ep_probe` on the win-port line. If it is materially different on v0.2.7 + this driver,
      the whole 4-card prediction in §4 moves.
- [ ] Check whether v0.2.7's `exchange_storage.hpp` / `dma_batch.hpp` supersede the lab's
      `ep_mem.hpp` shared-context design — if so, port *upstream's* version, not the lab patch.

**Acceptance:** a written answer to "what exactly is missing, and what is the measured exchange
cost", with no code changed.

### QWEN-3 — port the peer/expert tier to SYCL (only if QWEN-2 says go)

Scope lives in `sycl/src/core/`, **not** `dsv41/`. Prior art is the lab's shared-context
`ep_mem.hpp`, but that targets the win-port line and must be re-solved against v0.2.7.

**Acceptance:** two cards beat one card on decode by a margin larger than the measured variance, with
identical answers to the one-card run.

-

## 6. Relationship to the dsv41 port (important)

These are **two different tracks** and must not be conflated:

| Track | Engine | Status |
|---|---|---|
| **Qwen** (this file) | `sycl/src/` — exists, builds, runs | 12.95 t/s single-card; multi-GPU stubbed out |
| **dsv41** ([PORT-SCOPE.md](PORT-SCOPE.md)) | `sycl/src/dsv41/` — **does not exist** | 0 lines ported; ~85% of kernels convert via dpct |

**Dependency to note:** `PLAN.md` STEP-004 assumes a working four-card split. This session
established that **the SYCL port has no multi-GPU expert tier**, so the dsv41 engine cannot inherit
one. Either dsv41 brings up multi-GPU itself, or QWEN-3 lands first and dsv41 reuses it.

That is a real planning input and should be settled before STEP-004 is estimated.

-

## 7. Reproduce this session

```
# build
powershell -File D:\strata-dsv41-port\rb8.ps1        # runs build27.cmd -> build-jit
# run (must be inside the oneAPI env)
call "C:\Program Files (x86)\Intel\oneAPI\setvars.bat" --force
cd /d D:\strata-dsv41-port\build-jit
strata.exe --pack "D:\AI\Strata-data\packs\iq3_s" \
  --native   "D:\AI\LLM\Models\ISTA-DASLab\Qwen3.8-Flash-Next-GSQ-RCO-GGUF\IQ3_S\...-00001-of-00002.gguf" \
  --ple-gguf "D:\AI\LLM\Models\ISTA-DASLab\Qwen3.8-Flash-Next-GSQ-RCO-GGUF\IQ3_S\...-00002-of-00002.gguf" \
  --expert-profile "%USERPROFILE%\strata-win\data\expert-profile-sycl.bin" \
  --max-context 8192 --kv int8 --spec 4 --mtp "D:\AI\Strata-data\mtp\rt" \
  --spec-min-p 0 --mtp-draft-vocab "%USERPROFILE%\strata-win\data\draft_vocab_en.bin" \
  --ple-io mmap --stream-experts --expert-cache auto --vram-reserve-mib 1024 \
  --prefill 8192 --no-prefill-borrow \
  --tokens "9707,11,1879,13,374,264,1293,13" --max-new 32
```

Scripts: `D:\strata-dsv41-port\bench2.cmd` (run), `rb8.ps1` + `build27.cmd` (build).
Logs: `bench2.txt`, `build27.log`, `cfg27.log` in the same directory.

**Do not pass `--expert-parallel-device`** (gone in v0.2.7) and **do not pass `--peer-device`**
(a stub — exits 1).
