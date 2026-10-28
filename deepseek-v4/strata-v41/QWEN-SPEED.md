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

### Why it is 7.5x slower — CORRECTED in session 11, see below

> **This section was wrong. Kept for the record; the correction is authoritative.**

It claimed `--expert-parallel-device` was replaced by `--peer-device`, that `--peer-device` is a
SYCL stub, and therefore that v0.2.7 cannot use a second card. **All three are false.**

Measured facts (session 11, full detail in
[`FINDINGS-SESSION-11.md`](../../work/strata-v41-agent-runner/FINDINGS-SESSION-11.md)):

| Claim | Reality |
|---|---|
| `--peer-device` is the only multi-GPU path | `--expert-cache-device1\|2\|3 N\|auto` is a **separate, live** path |
| the tier is a stub | `peer_experts.cpp` (41 lines) **is** a stub; `remote_experts.cpp` (**482 lines**) is live ported SYCL, wired at `sycl/CMakeLists.txt:200` |
| `--expert-parallel-device` was renamed | it was **removed upstream** — 0 hits in `generate.cpp`, 0 in the binary's `--help` |

`--expert-parallel-device` being gone is real and matters (the lab configs under
`strata-windows-port/configs/` still pass it, so they cannot run on v0.2.7 as written), but it does
**not** mean multi-GPU is unavailable. The successor in practice is `--expert-cache-device*`, whose
semantics are an expert-cache tier rather than symmetric expert parallelism.

So the 12.95 run used one card **by choice of flags, not by port limitation**. That distinction is
the whole reason §4 below had to be rewritten.

### Caveats on these numbers

- **7-token prompt** — the 1.87 t/s prefill is one tiny chunk; not comparable to 1,415 t/s @ 33.6k.
- **TTFT 20.0 s** includes engine start, the 21.1 s profile fill, and PLE setup. Not a token metric.
- **One sample, no variance.** Per `FINDINGS.md` W-042, single samples on this box are unreliable
  (bimodal throughput was measured on the llama.cpp path). Treat as indicative.
- **12.95 does not reproduce.** Session 11 re-ran the identical command twice: **10.92 and 11.08**
  tok/s. ~18% spread on the same binary and flags. Quote single-card as **~11 tok/s**, never 12.95.

-

## 4. MEASURED: what four cards actually do

**The previous version of this section was theory and it was wrong.** It predicted 180–220 tok/s on
four cards. Measurement says **29.78**. Everything below is measured on the v0.2.7 build, one
prompt set, only the `--expert-cache-device*` flags varied.

Full method and caveats: [`FINDINGS-SESSION-11.md`](../../work/strata-v41-agent-runner/FINDINGS-SESSION-11.md) §1.

### 4a. Decode by tier (measured)

| Cards | Devices engaged | Decode tok/s | n |
|---|---:|---|---:|
| 1 | GPU0 only, 10,618 slots | 10.92, 11.08 | 2 |
| 2 | + CUDA1, 13,958 experts | 27.75, 27.39, 29.33, 29.39 | 4 |
| 3 | + CUDA2, 6,979 | 28.26 | 1 |
| 4 | + CUDA3, 4,653 | 29.78 | 1 |

**Card 2 buys 2.5x. Cards 3 and 4 together buy +7%.**

All 24,576 experts reached full residency across cards 1-2 (10,618 + 13,958 = 24,576 exactly), so
this is measured with the whole expert set on the GPUs — the residency question is closed.

### 4b. Why 3-4 cards add almost nothing: the flat host terms

From the engine's own per-round instrumentation:

| ms/round | 1 card | 2 cards | 4 cards |
|---|---:|---:|---:|
| dispatch `run` (GPU expert work) | 9.62 | 5.77 | 3.83 |
| CPU pool call | 15.99 | 15.07 | 17.13 |
| verify window `wait for rings` | 20.00 | 19.97 | 19.81 |

GPU expert work **does** divide: 9.62 -> 5.77 -> 3.83. It is no longer the binding term. What does
not divide is the per-layer CPU pool call and the wait-for-rings, both ~flat across tiers and now
dominating the round.

### 4c. The old arithmetic, and why it failed

It reasoned: `480 expert calls x 21 us = 10.1 ms/token -> 99 tok/s`, therefore one card should hit
99 and four cards 396. Measured one card: **10.9**. Measured two cards: **27.8**, not 198.

The 480x21us term is real but it is not the critical path at this window size. The pool call and
the ring wait are. Any model of this engine's decode that omits per-layer host work will be wrong
by roughly an order of magnitude on one card.

### 4d. The 97.6 number has no working repro on v0.2.7

The lab config (`strata-windows-port/configs/strata-iq3s-200k1-pf8k.json`, 83 env vars) was
reconstructed with `--expert-parallel-device 1` remapped to `--expert-cache-device1..3 auto`:

| Config | Cards | Context | Decode |
|---|---:|---:|---:|
| plain (this pass) | 4 | 8k | **29.70** |
| lab config, 83 env vars | 4 | 8k | 21.71 |
| lab config | 4 | 200k | **REFUSED, EXIT=2** |
| **plain config** | **2** | **200k** | **22.56, EXIT=0** |

The env sweep makes it **slower**, not faster. At its own 200k the config refuses outright:

```
strata generate: REFUSED: 14754 experts are neither in VRAM nor mirrored; with
STRATA_VERIFY_NO_HOST the device plan cannot run them and generation would lack a safe
host fallback - raise STRATA_MIRROR_MIB or the free RAM, or lower --max-context
```

**The refusal is the env pair, not the context length.** A plain config at 200k runs fine (22.56
tok/s, EXIT=0). What breaks is `STRATA_VERIFY_NO_HOST=1` + `STRATA_MIRROR_MIB=0`: no host fallback
and an explicitly zeroed mirror. Filed as issue **#22**. Narrow statement: *the published 200k lab
config is unsatisfiable on this box**, not *200k is broken*.

Caveat: a remapped config is not the lab's config, because `--expert-parallel-device` and
`--expert-cache-device*` do not have the same semantics. Read 21.71 as "the env sweep does not
close the gap", not as a measurement of the lab setup.

### 4e. What this changes for planning

- The 50 GB expert set does fit across two cards. **Cards 3-4 are not needed for residency.**
- They are not needed for throughput either, at this point — +7%.
- The 97.6 headline needs re-measuring on a configuration that actually runs before any further
  work is scoped against it.
- Multi-GPU is **not** a blocker for Qwen or for dsv41. It exists and it works.

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

### QWEN-2 — ~~identify what the SYCL port is missing for multi-GPU~~ **DONE — nothing is missing**

Answered by session 11 measurement. The tier is ported (`remote_experts.cpp`, 482 lines) and runs.
The original four bullets are kept struck for the record:

- ~~Diff `peer_experts.cpp` and `remote_experts.cpp` against the CUDA originals.~~ **Done.**
  `peer_experts.cpp` is a genuine 41-line stub; `remote_experts.cpp` is a full port and is the
  path `--expert-cache-device*` uses.
- ~~Determine whether the stub is not written / disabled / blocked on Level Zero.~~ **N/A** — the
  stub is a *different feature* (`--peer-device`) from the working one.
- ~~Re-measure the host-exchange round trip.~~ **Superseded.** Exchange latency is not the binding
  constraint; the flat per-layer CPU pool and ring wait are, and those are measured directly.
- ~~Check whether `exchange_storage.hpp` / `dma_batch.hpp` supersede `ep_mem.hpp`.~~ **Moot** — no
  port work is needed to use cards 2-4.

**Acceptance met:** the question "what is missing" has the answer **nothing**.

### QWEN-3 — REFILED: attack the flat per-layer host terms

**This replaces the old QWEN-3 ("port the peer tier to SYCL"), whose premise was false —** the
prior art it named is already ported and working.

The measured problem is not expert placement. It is that two costs are roughly constant as cards
are added, and they set the ceiling:

| ms/round | 1 card | 2 cards | 4 cards | divides? |
|---|---:|---:|---:|---|
| GPU expert work (`dispatch run`) | 9.62 | 5.77 | 3.83 | **yes** |
| CPU pool call | 15.99 | 15.07 | 17.13 | no |
| verify `wait for rings` | 20.00 | 19.97 | 19.81 | no |

Open questions worth answering before touching code:

- [ ] Why is the CPU pool call ~16 ms/round when `pool multi` reports only 0.55 + 0.01 + 0.29 ms of
      actual phase work? The gap (~15 ms) is the target.
- [ ] What is `wait for rings` waiting on? ~20 ms/round at every tier suggests a per-layer
      serialisation that is not the expert tiers.
- [ ] Is the 1.65 tok/round speculation acceptance (0.228 draft acceptance) suppressing the
      apparent decode rate? Test with `--spec 0` to get a clean non-speculative baseline.
- [ ] Re-test at a realistic prefill length; all of this is at 7 prompt / 32 new tokens.

**Acceptance:** any change that lifts 2-card decode materially above the ~29 measured here, proven
against n>=3 runs on both configs, with unchanged output on a real prompt.

-

## 6. Relationship to the dsv41 port (important)

These are **two different tracks** and must not be conflated:

| Track | Engine | Status |
|---|---|---|
| **Qwen** (this file) | `sycl/src/` — exists, builds, runs | ~11 t/s 1 card; 27.8 on 2; 29.8 on 4. Multi-GPU **works** |
| **dsv41** ([PORT-SCOPE.md](PORT-SCOPE.md)) | `sycl/src/dsv41/` — **does not exist** | 0 lines ported; ~85% of kernels convert via dpct |

**Dependency — [S11 CORRECTED, was wrong]:** `PLAN.md` STEP-004 assumed a four-card split because
this document previously claimed the SYCL port had no multi-GPU expert tier. **It does have one,
and dsv41 can inherit it.** STEP-004 is therefore *not* blocked on QWEN-3 and does not need to be
estimated against a tier that has to be built first.

What STEP-004 *should* be estimated against is the measured behaviour, not the retracted theory:
2 cards give 2.5x, cards 3-4 give +7%, and the remaining ceiling is per-layer host work.

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

**Do not pass `--expert-parallel-device`** — it was removed upstream (0 hits in `generate.cpp`, 0 in
`--help`). The lab configs under `strata-windows-port/configs/` still pass it and therefore cannot
run on v0.2.7 as written.

**`--peer-device` is a stub and exits 1.** It is *not* the multi-GPU path — see below.

### To use more than one card, add `--expert-cache-device1 N|auto` (and `2`, `3`)

This is the **live** multi-GPU path, backed by `sycl/src/core/remote_experts.cpp`:

```
  ... --expert-cache auto \
      --expert-cache-device1 auto \
      --expert-cache-device2 auto \
      --expert-cache-device3 auto \
      --vram-reserve-mib 1024 ...
```

Measured, same command otherwise:

| Flags | Cards | Median decode |
|---|---:|---:|
| (none) | 1 | 11.02 |
| `--expert-cache-device1 auto` | 2 | 28.74 |
| `+ device2` | 3 | 28.64 |
| `+ device2 + device3` | 4 | 29.70 |

Logs: `D:\strata-dsv41-port\g{1..4}_r{1..3}.txt` (n=3 each). A run that engages a second card prints
`CUDA1: N additional experts, X GiB; results return through pinned host rows`.
