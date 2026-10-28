# Handoff — session 10 checkpoint (2026-10-27 evening)

Written for a **fresh session**. Read this, then act. Do not repeat completed work.

Branch: `work/strata-v41-agent-runner`, remote `Captain-Tripps/b70-lab`.
Last commit at handoff: `d956c22`.

-

## 1. Copy-paste starter prompt

```text
Resume the Strata / Qwen work in Captain-Tripps/b70-lab on branch work/strata-v41-agent-runner.

Read, in this order:
  1. work/strata-v41-agent-runner/HANDOFF-SESSION-10.md   (this file)
  2. deepseek-v4/strata-v41/QWEN-SPEED.md                 (Qwen state, theory, next steps)
  3. deepseek-v4/strata-v41/PORT-SCOPE.md                 (dsv41 port scope + the 6 build fixes)
  4. deepseek-v4/strata-v41/PLAN.md                       (route and gates)
  5. work/strata-v41-agent-runner/FINDINGS.md             (ledger; note W-038..W-044 on variance)

Then verify artifacts on GPU-BOX before relying on them. There are TWO separate tracks — do not conflate:
  - Qwen  : sycl/src/          -> builds and runs today (12.95 tok/s, 1 card)
  - dsv41 : sycl/src/dsv41/    -> DOES NOT EXIST, 0 lines ported

Ask the owner which track before starting work. Do not start dsv41 STEP-003 without an explicit go.
```

-

## 2. What was accomplished this session

### 2a. The v0.2.7 Windows SYCL build now works

| | |
|---|---|
| Worktree | `D:\strata-dsv41-port` on v0.2.7 (`5e8a4cca7`) — **not** `%USERPROFILE%\strata-win` |
| Binary | `D:\strata-dsv41-port\build-jit\strata.exe`, 44,995,584 B |
| Engine | `strata 0.1.52`, JIT build |
| Result | `BUILD_EXIT=0`, 0 compile errors, 0 link errors |

The tree had **never** compiled on Windows. Six defects were found and fixed (full detail in
`PORT-SCOPE.md` §13, issue #19):

1. `sycl/CMakeLists.txt` — GCC-style flags leaked into the fetched ggml sub-build, where MSVC `cl`
   rejects them (`D8021`). Gated on `$<COMPILE_LANGUAGE:CXX>`.
2. `sycl/CMakeLists.txt` — `-qmkl=sequential` is the GNU spelling; Windows icx ignored it, leaving
   **10 unresolved oneMKL `dpct::blas::gemm` externals**. Now `if(WIN32)` -> `/Qmkl:sequential`.
3. `sycl/include/strata_win_undefs.h` — new file, `#undef small OUT IN clamp min max`.
4. `sycl/src/core/gguf_expert_source.cpp` — Win32 `pread` shim (64-bit offsets).
5. `sycl/src/core/pinned.dp.cpp` — dropped CUDA LUID path.
6. `sycl/src/prefill/prefill.cpp` — `<direct.h>` for `_mkdir`.

**Two traps that cost hours — do not rediscover them:**
- **Never `#undef near` or `#undef far`.** `minwindef.h` has `#define FAR far` and `guiddef.h` has
  `DEFINE_GUID(...) EXTERN_C const GUID FAR name`. Undefining `far` leaves a stray token and every
  `DEFINE_GUID` in `dxgi.h` / `d3d11.h` fails with `expected ';' after top level declarator`.
- **Never include `<windows.h>` before `<dpct/dpct.hpp>`.** It breaks dpct's `math_detail.hpp`
  (`sycl::min`/`max` collide -> `too few arguments provided to function-like macro`). Put the undefs
  header **after** the include block.

**Runtime requirement:** `strata.exe` must run inside `setvars.bat --force`. Bare invocation dies
`EXIT=-1073740612` (`0xC00004BC`). llama-swap's `env:` cannot supply a DLL search path.

### 2b. Qwen runs on it — end to end

```
GPU 0: Intel(R) Arc(TM) Pro B70 Graphics, compute capability 20.2
expert cache: 10,618 slots, 20.15 GiB VRAM, PROFILE policy
profile fill: 20.15 GiB in 21.1 s (1.02 GB/s); slot 0 verified

decode  32 tokens in 2470.1 ms  ->  12.95 tok/s
EXIT=0
```

Full record, model facts and theory: **`deepseek-v4/strata-v41/QWEN-SPEED.md`**.

### 2c. The llama.cpp track was formally closed

Owner confirmed llama.cpp is a dead end; the Strata engine port is the route. Recorded in
`PLAN.md` under "Route decision — CONFIRMED". The llama.cpp measurements are retained as platform
input only, and no CHECK-102..108 gate moved.

Corrections made to earlier findings (all in `FINDINGS.md`):

| Finding | Correction |
|---|---|
| W-035 "prefill peaks at b=128+, 41.87 t/s at b=512" | **41.87 did not reproduce** (0.61 on repeat). Peak is b=128 at ~11-12 t/s. W-038 |
| #8 "flash attention is a 10x regression" | **Did not reproduce.** At r3, fa1 39.63 vs fa0 41.15 — indistinguishable. Closed. W-041 |
| #6 "b=512 is 41.87" | Dead. But **b=256 -> 0.70 reproduced twice**, and W-043 shows default ubatch is the real culprit. Closed. |

**The real finding is variance (W-042):** `pp128 = 39.63 ± 31.48` — a mean of 39.6 with SD 31.5 is
**bimodal**, not noisy. Every single-sample throughput number from this box is suspect. Use per-sample
data, never means alone. Issue #17.

### 2d. The dpct pilot — the dsv41 port is ~85% automatable

`PLAN.md` said "automatic CUDA translation as a complete port — Reject". That was decided without
running the tool. It has now been run (issue #18, `PORT-SCOPE.md` §10):

| Metric | Value |
|---|---|
| dpct | 2025.1.0, clang 20.0.0 |
| CUDA headers | from PyPI wheels into `D:\cuda-headers` — **no toolkit or GPU needed** |
| Kernels in | 93 `__global__` |
| Kernels out | **96 `parallel_for` blocks** |
| Launch sites left | **14** |
| Kernels not converted | **2** |

**One failure mode, precisely characterised:** launches wrapped in preprocessor macros don't convert.
`ds4_tq.cu` converted **zero** kernels because all 5 launches sit inside `DS4_TQ_SWITCH` macros.
Mechanical fix — expand the macros or hand-write those 5 sites.

Calibration: the **working Qwen SYCL port carries 2,020 DPCT markers** and runs in production. dsv41's
524 is a *smaller* residue than the codebase already absorbed. Translation is now the **method**; it
is still not the **acceptance** — CHECK-103 decides.

### 2e. The engine is CUDA/HIP only — this was not stated plainly before

| Ref | dsv41 files | SYCL dsv41 files |
|---|---:|---:|
| v0.2.6 | 131 | **0** |
| v0.2.7 | 138 | **0** |

`src/dsv41/` is `.cu`/`.cuh` (14 + 12 files). Windows is a supported *host* via HIP/CUDA, not SYCL.
Measured port surface: **16,428 lines of compute, 93 kernels, 130 launch sites, 41 `__shfl` shuffles.**
5,790 lines of CPU/host code compile unchanged. `ds4_vision.cu` (519 lines) is out of scope.

**The key asset:** `sycl/src/` is **108,675 lines of working Windows SYCL**, structurally mirroring
`src/`, with expert placement, host staging, graph capture and MTP already implemented. The port is
`sycl/src/dsv41/` following that pattern — not translation from first principles.

-

## 3. What is now open

| # | Item | Note |
|---|---|---|
| [#19](https://github.com/Captain-Tripps/b70-lab/issues/19) | v0.2.7 Windows build succeeds; 6 fixes | **done**, listed for upstreaming |
| [#20](https://github.com/Captain-Tripps/b70-lab/issues/20) | Qwen single-card baseline | 12.95 t/s is one 7-token sample — not a baseline |
| [#21](https://github.com/Captain-Tripps/b70-lab/issues/21) | Qwen multi-GPU tier is a SYCL stub | blocks 97.6 t/s; **affects dsv41 STEP-004** |
| [#17](https://github.com/Captain-Tripps/b70-lab/issues/17) | Throughput is bimodal (±31 on mean 39) | blocks all single-sample numbers |
| [#16](https://github.com/Captain-Tripps/b70-lab/issues/16) | Strata port is the route; engine CUDA-only | primary |
| [#18](https://github.com/Captain-Tripps/b70-lab/issues/18) | dpct pilot: ~85% auto-convert | **done** |
| [#12](https://github.com/Captain-Tripps/b70-lab/issues/12) | `-sm row` aborts (llama.cpp) | low priority, llama.cpp closed |
| [#13](https://github.com/Captain-Tripps/b70-lab/issues/13) | `-ngl 38` VRAM overrun (llama.cpp) | low priority, llama.cpp closed |
| [#14](https://github.com/Captain-Tripps/b70-lab/issues/14) | Engram/PLE skipped (llama.cpp) | **relevant to dsv41** — real question |
| [#15](https://github.com/Captain-Tripps/b70-lab/issues/15) | PCIe ~12 GB/s measured, topology unknown | affects all multi-GPU plans |
| [#5](https://github.com/Captain-Tripps/b70-lab/issues/5), [#7](https://github.com/Captain-Tripps/b70-lab/issues/7), [#9](https://github.com/Captain-Tripps/b70-lab/issues/9), [#10](https://github.com/Captain-Tripps/b70-lab/issues/10) | llama.cpp leftovers | closed or superseded |

-

## 4. The decision waiting on the owner

Two tracks, different work, different payoffs:

### Track A — Qwen speed (issues #20, #21)
Qwen builds and runs **today**. Getting it from 12.95 to ~97.6 needs the multi-GPU expert tier, which
is a **stub** in the SYCL port. Work lives in `sycl/src/core/` (`peer_experts.cpp`,
`remote_experts.cpp`), not `dsv41/`.

4-card theory (`QWEN-SPEED.md` §4), from measured constants:
- Whole expert set is only **~50 GB**; two cards already reach full residency. **Cards 3-4 buy compute, not cache.**
- 97.6 t/s is the **one-card compute ceiling** (480 expert calls x 21 us = 10.1 ms -> 99 t/s; measured 97.6).
- 4 cards => likely **180-220 tok/s**, not 400x — Windows has no peer access, and the lab measured
  **56-64 us** host round trip, which costs 2.74 ms/token over 48 layers.

### Track B — dsv41 port (issues #16, #18)
The engine you actually want for 1017. 0 lines ported. dpct gets ~85% of kernels. Multi-week.

**Dependency that must be settled first:** `PLAN.md` STEP-004 assumes a four-card split. #21
establishes the SYCL port has **no multi-GPU expert tier at all**. Either dsv41 brings up multi-GPU
itself, or Track A lands first and dsv41 reuses it. **Do not estimate STEP-004 until this is answered.**

-

## 5. GPU-BOX state at handoff

| Item | Value |
|---|---|
| Box | idle — verified **0** `strata.exe`, 0 watchers |
| Worktree | `D:\strata-dsv41-port` (v0.2.7) |
| Build | `build-jit/strata.exe`, green |
| Legacy tree | `%USERPROFILE%\strata-win` — **untouched this session**, 18 uncommitted fixes still there |
| Production | llama-swap rolled back, SHA256-verified, 9 models, **0** `v41` refs. Not touched this session. |
| Qwen pack | `D:\AI\Strata-data\packs\iq3_s` (1.5 GB) + GGUFs at `D:\AI\LLM\Models\ISTA-DASLab\...` (83.62 GB) |
| 1017 pack | `D:\AI\Models\dsv41` — 128.74 GiB, 4 shards, Engram, mmproj. **No drafter** (needs 8 GB download). |

**Do not** `git reset`, `stash -u`, `clean -fd` or branch-switch in `%USERPROFILE%\strata-win`
until a current backup is confirmed (`D:\backups\strata-win-20261027-131251`, verified).

-

## 6. Operational lessons from this session (save yourself the time)

1. **`process` tool: always pass `sessionId`.** I failed this repeatedly and hit the 3-consecutive-
   failure stop several times. Prefer plain `exec` with `timeout` over `process poll`.
2. **Never nest redirects.** `bench27.cmd` writes `build27.log`; adding `-RedirectStandardOutput
   build27.log` for the same file made the build silently do nothing while a **stale errorlevel 0**
   wrote `BUILD_EXIT=0`. I reported a false pass twice. Verify binaries, not exit codes.
3. **Local `$` expansion eats variables in ssh payloads.** `$r`, `$f`, `$B64` vanish. Write the
   script to `/tmp`, base64 it, push, verify with `md5sum`. This is the same L-034-class bug the
   ledger already documents.
4. **`.bat` files need CRLF.** Push as LF and `cmd.exe` misparses.
5. **Windows logs are UTF-16.** `iconv -f UTF-16LE` before grepping, or the output looks like garbage.
6. **A 0-byte log is not a hang** — and a growing VRAM figure means progress, not a stall.
7. **Verify a build actually produced a binary.** `BUILD_EXIT=0` with no `.exe` is possible (see 2).

-

## 7. Suggested first move for the next session

Ask the owner which track (A or B). Then:

- **Track A** -> start with **#20** (cheap, honest baseline) before touching #21. Do not port a
  multi-GPU tier to chase a number that has never been properly measured on one card.
- **Track B** -> start `sycl/src/dsv41/` with a CMake target and the dpct-converted `ds4_kernels`
  (56 kernels, **1** unresolved) so something links early. Do not start until CHECK-102 is re-run
  against this build.
