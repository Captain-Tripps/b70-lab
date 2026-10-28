# Session 14 results — watchdog fixed, discriminating test run (2026-10-28 ~10:15 CDT)

Follows `HANDOFF-SESSION-13.md` §2. Box was clean at start (commit 24 GB, no foreign processes).

-

## 1. Watchdog metric fixed (P0-1, done)

`ram-watchdog.ps1` `Get-AvailGB` now reads `Win32_PerfRawData_PerfOS_Memory.AvailableBytes`
(free + standby) instead of `Win32_OperatingSystem.FreePhysicalMemory`. Floor kept at 6 GB.
Original backed up next to it as `*.pre-availbytes-20261028.bak`. Single instance running.

-

## 2. Small-model control (P0-3) — **backend mirrors device allocations**

Same build, Qwen3-Coder-30B-A3B Q4_K_M (17.28 GB file), `-ngl 99 -sm layer -lm auto -c 2048
--cache-ram 0`, port 9080. All weights on GPU (no CPU expert offload).

| Point | WS | Private | Box commit |
|---|---:|---:|---:|
| load peak | 18.0 GB | 20.0 GB | — |
| steady (20 s after health 200) | 17.97 GB | **19.62 GB** | 44.0 GB (baseline 24) |
| after bench | 18.19 GB | 20.13 GB | 44.6 GB |

**`priv ≈ ws ≈ model size` with everything on the GPUs.** That is the first row of the handoff's
decision table: host memory mirrors device allocations roughly 1:1 on this SYCL / Level Zero path.
No loader flag explains a 17 GB host footprint for a model with ~0 GB of CPU tensors.

(Buffer-size lines were not logged — the run used default verbosity. `-ngl 99` with no
`-ncmoe`/`-ot` leaves only negligible CPU tensors, so device buffers ≈ 17 GB is inferred, not read.)

Bench (same harness, no warmup, so the first two numbers include first-run JIT):

| Request | prefill tok/s | decode tok/s |
|---|---:|---:|
| 1 token | 7.3 | — |
| ~164-token prompt | 14.0 | — |
| 20-token prompt, 125 tokens out | 117.8 | **54.3** |

Output coherent. The build and the bench harness work end to end.

-

## 3. 1017 at `-ncmoe 18` (P0-2) — killed by the watchdog, legitimately this time

Config as session 13's r18 plus `--cache-ram 0` (`-ngl 40 -ncmoe 18 -ts 57.5,15,15,12.5 -sm layer
-lm auto -c 2048 -t 12`).

| t | WS | Private | Available | Commit |
|---|---:|---:|---:|---:|
| +70 s | 15.6 | **77.3** | 67.2 | 102.5 |
| +100 s | 65.8 | 77.4 | 17.2 | 102.7 |
| +111 s | 76.5 | 80.4 | 6.6 | 105.6 |
| +121 s | 76.7 | 80.6 | 6.5 | 105.8 |
| kill | 77.5 | 80.8 | **5.66** | — |

- **Private commit jumps to 77.3 GB before WS moves** — i.e. equal to the ~76–77.6 GiB of GPU
  buffers at allocation time. WS then fills in as tensors are uploaded. Same mechanism as the
  Qwen control.
- True available bottomed at 5.66 GB → watchdog killed it (`exit -1`) during threadpool init,
  before `listening`.
- Session 13's r18 reached `listening` with the same config because **no watchdog was running
  between 09:24 and 09:32** (temp watchdog stopped, main one not yet restarted). Its `exit 1` at
  09:31:32 matches a `taskkill /F` during that session's cleanup, not a crash.

Still no 1017 tok/s number.

-

## 4. Correction to the session-13 "host RAM doesn't move with -ncmoe" claim

That claim was based on **WS**, which saturates near physical RAM no matter what. The
non-reclaimable number is **private commit**, and it does move:

| `-ncmoe` | GPU buffers | Private |
|---:|---:|---:|
| 5 | 114.5 GiB | 115.8 GB |
| 12 | 93.6 GiB | 95.3 GB |
| 18 | ~77 GiB | 77–81 GB |

CPU experts under `-lm auto` are file-backed and reclaimable (standby counts as available), the GPU
mirror is not. So each step of `-ncmoe` moves memory from "pinned host mirror" to "evictable page
cache", which is exactly what the 6 GB floor needs.

-

## 5. What this means / next step

- A full-GPU 1017 (119 GiB device) needs ~120 GB of host commit just for the mirror — not possible
  in 96 GB RAM without pagefile-backed thrash. **Do not try `-ncmoe` < 18 again.**
- The workable direction is **higher `-ncmoe`** (≈24–26 → GPU mirror ~55–62 GB, leaving
  ~25 GB of real headroom), with a re-solved `-ts` from `box-solve2.py`. Decode will be slower
  (more experts on CPU), but it should produce the first number.
- Alternative: lower the watchdog floor to ~2 GB for a single supervised `-ncmoe 18` run. Faster to
  a number, but the box has hung before under RAM exhaustion; needs the owner's OK.
- Upstream angle: the mirror happens even on the Level Zero allocation path that
  `ggml-sycl/common.cpp:95-96` says exists to avoid xe/TTM staging. Worth a minimal repro.

## 5b. 1017 at `-ncmoe 24` — first completed inference, then watchdog kill on mmap growth

Split from `box-solve4.py` (reproduces r18's `-ts` exactly at `-ncmoe 18`):
`-ngl 40 -ncmoe 24 -ts 67.5,12.5,10,10 -sm layer -lm auto -c 2048 -t 12 --cache-ram 0`,
predicted GPU total 57.7 GiB, CPU experts 71.1 GiB (file-backed).

| Point | WS | Private | Available | Commit |
|---|---:|---:|---:|---:|
| t+101 s | 57.6 | 61.4 | 27.1 | 85.3 |
| health 200 (t+152 s) | 59.2 | 62.2 | **25.2** | 86.3 |
| during 2nd request (kill) | **78.8** | 62.4 | 5.51 | — |

- **First 1017 inference ever completed on this box**: 31-token prompt, 1 token out, 31.7 s
  (0.98 tok/s prefill — first request, no warmup, includes JIT; not a real rate). Output was a
  sensible reasoning token.
- Private memory tracked the GPU allocation again (57.7 GiB predicted → 62 GiB) and **stayed flat**
  during inference.
- On the ~187-token request, WS grew 59 → 79 GB as the CPU experts were paged in from the
  memory-mapped file. Windows counts those pages as in-use, not available, so `AvailableBytes` fell to
  5.5 GB and the watchdog killed the server. Those pages are clean and file-backed (the memory
  manager can trim them), so this was not the runaway-commit failure the watchdog exists to stop.

**So the watchdog metric is still wrong for memory-mapped loads**, in a second way: `AvailableBytes`
excludes clean mapped pages that are in a working set. The danger signal for the original failure
(the GPU driver backing VRAM overflow with system RAM) is **private/commit growth**, and that did not
happen here.

## 5c. Same config, watchdog floor 2 GB for one supervised run — first real numbers

Temporary 2 GB watchdog for this run only; the scheduled 6 GB one was restored afterwards.

| Request | Prompt tokens | Out | prefill tok/s | decode tok/s |
|---|---:|---:|---:|---:|
| 1 token (first, JIT) | 31 | 1 | 0.98 | — |
| ~160-token prompt | 187 (160 new) | 4 | **5.43** | **0.85** (4 tokens, cold) |
| decode 128 | — | — | killed during prefill | — |

Output was coherent (`reasoning='We need answer only'`).

Memory trace (5 s samples, `s16-mem.log`): **private 62.2 → 62.5 GB and commit 86.3 → 87.3 GB, flat**.
Working set rose a steady ~0.35–0.4 GB/s (59 → 82 GB) as the CPU experts were paged in, and
available fell with it, 25 → 1.8 GB (all of it standby; free was 0). The watchdog killed the server at
1.77 GB.

What this shows:

- Windows doesn't trim the working set until available is almost gone, so **any floor-on-available
  watchdog kills a memory-mapped expert-offload run**, whatever the floor is set to. 71 GiB of CPU
  experts cannot sit in ~22 GB of headroom; steady state means paging experts from NVMe, with the
  memory manager reclaiming clean file pages near zero available.
- None of this is the failure the watchdog guards against: commit stayed 9 GB under physical RAM
  and private memory didn't grow.
- **Commit-aware watchdog is the fix:** kill only when available is below the floor **and** commit is
  near physical RAM (or private memory is climbing). Then a run could reach steady state and give
  a warm decode number.
- Cold numbers are NVMe-bound: 5.4 tok/s prefill, 0.85 tok/s decode. Warm decode is still unknown.

## 5d. Commit-aware watchdog installed — first complete 1017 bench

`ram-watchdog.ps1` now kills only when **available < 6 GB AND commit > physical − 4 GB (91.9 GB)**.
Commit unreadable → treated as high (fail-safe). It logs "low avail ... not killing" once a minute
when only the first condition holds. Previous version backed up as
`*.pre-commitaware-20261028.bak`. Dry-run tested before install.

Same 1017 config (`-ncmoe 24`, 57.7 GiB on GPU, 71 GiB experts memory-mapped):

| Request | Prompt | Out | prefill tok/s | decode tok/s |
|---|---:|---:|---:|---:|
| 1 token (first, JIT) | 31 | 1 | 0.99 | — |
| ~160-token prompt (cold) | 187 | 4 | 5.19 | 0.79 |
| decode (cold) | 16 | 86 | — | **0.90** |
| ~160-token prompt (warm) | 189 | 4 | **6.98** | 0.94 |
| decode (warm) | 16 | 124 | — | **0.93** |

Output coherent and factually right on both decode prompts.

Memory, steady state (`s17-mem.log`): available sat at **0.3–0.4 GB for 4+ minutes**, commit flat at
87.3 GB, private flat at 62.5 GB, WS capped at 83.7 GB. The box stayed responsive throughout; the
watchdog logged "not killing" each minute, as designed.

What it shows:

- **Decode is NVMe-bound at ~0.9 tok/s.** Warm ≈ cold, because 71 GiB of experts cycle through about
  21 GB of page cache, so most expert reads per token come from disk.
- **The host copy of GPU memory did not page out under pressure.** With available near zero for
  minutes, Windows trimmed the memory-mapped expert pages, not the 62.5 GB private copy, which stayed
  resident. So a bigger pagefile would not free that RAM; the copy behaves as pinned or always-hot.
  That argues for the upload path or the driver, not just a WDDM commit reservation, and leaves a
  Linux test as the decisive next step.

## 6. Box state at end

llama-swap Running, nothing loaded, no `llama-server`/`llama-bench`, available 84.4 GB,
commit 24.5 GB, one watchdog instance.

Harness used: `box-s14.ps1` (stop llama-swap → commit check → launch → 2 s health poll with inline
bench → control → restore). Bench: `bench-port.py <port>` (adds a 128-token decode request).
