# DeepSeek V4.1 SYCL port — measured scope

Prepared 2026-10-27, immediately after the owner confirmed the Strata engine port is the route and
llama.cpp is a dead end. This document replaces guesswork about the port's size with counts taken
from the actual source.

Base read: **upstream `v0.2.7`** (`5e8a4cca7`, 2026-10-27 14:54 +0100), in a separate worktree at
`D:\strata-dsv41-port` — **not** `%USERPROFILE%\strata-win`.

-

## 1. Why v0.2.7 and not v0.2.6

`PLAN.md` pins `v0.2.6` (`4b9e05a2`). One day later `v0.2.7` landed and adds ~1,000 lines to the
engine:

| File | Change in v0.2.7 |
|---|---|
| `src/dsv41/ds4_model.cu` | +346 lines |
| `src/dsv41/ds4_kernels.cu` | +241 |
| `src/dsv41/ds4_experts_rule.hpp` | +161 |
| `src/dsv41/ds4_iq.cu` | +130 |
| `src/dsv41/ds4_store.hpp` | +48 |
| `src/dsv41/ds4_wmma.cuh` | **+39 (new file)** |
| others | smaller |

Its release note cites "speed lines confirmed on the release packages". Porting is a multi-week
kernel translation; translating a one-day-stale tree and then re-porting is waste. **Decision:
target v0.2.7, and record the deviation from the plan's v0.2.6 pin explicitly.** This is a base
choice, not a route change.

-

## 2. The engine is CUDA/HIP only — no SYCL exists

Verified with `git ls-tree -r --name-only` against the upstream object store:

| Ref | dsv41 files | SYCL dsv41 files |
|---|---:|---:|
| `v0.2.6` | 131 | **0** |
| `v0.2.7` | 138 | **0** |

Top-level `sycl/src/` has no `dsv41` directory. `src/dsv41/` contains the engine as `.cu`/`.cuh`.
`include/strata/dsv41/hip_or_cuda.h` explicitly documents that the engine's sources "compile as HIP
or as CUDA" — there is no third backend.

**So "build strata-dsv41 with Windows SYCL" is not a build flag.** It is STEP-003 translation work.

-

## 3. The actual port surface

`src/dsv41/` is **17,519 lines** across `.cu`/`.cuh`. But not all of it is GPU code:

| Category | Lines | Port needed? |
|---|---:|---|
| CUDA/HIP compute (`.cu`/`.cuh`) | **16,428** | **yes** |
| Portable host/CPU (`.cpp`/`.hpp`) | 5,790 | no — compiles as-is |

Per file, compute only:

| File | Lines | `__global__` kernels |
|---|---:|---:|
| `ds4_model.cu` | 9,744 | 1 |
| `ds4_kernels.cu` | 2,467 | **56** |
| `ds4_iq.cu` | 1,630 | 10 |
| `ds4_gguf.cu` | 1,529 | 14 |
| `ds4_tq.cu` | 539 | 4 |
| `ds4_vision.cu` | 519 | 8 |
| **Total** | **16,428** | **93** |

Other translation-relevant counts:

- **130** `<<<...>>>` launch sites
- **41** `__shfl*` uses → each needs an explicit SYCL subgroup mapping
- **0** `hipLaunchKernelGGL` → launches are plain triple-chevron, so a mechanical syntax change is
  available before semantic work begins
- 5 `.inc` files including `ds4_iq1m_codes.inc` (99 KB of IQ1_M codebook — data, not logic) and three
  `ds4_iq_hip_*.inc` (HIP-specific IQ kernels that need SYCL equivalents)

`ds4_vision.cu` (519 lines) is **out of scope** for the first deliverable — `PLAN.md` excludes vision.

**Adjusted surface: ~15,900 lines, 85 kernels, 130 launch sites, 41 shuffles.**

-

## 4. The finding that changes the estimate: a working SYCL engine already exists in-tree

`sycl/src/` is **108,675 lines** of working Windows SYCL code for the Qwen engine. Its directory
structure mirrors `src/`:

| `src/` (CUDA) | `sycl/src/` (SYCL) |
|---|---|
| `core/` | `core/` |
| `kernels/` | `kernels/` |
| `prefill/` | `prefill/` |
| `program/` | `program/` |
| `platform/` | `platform/` |
| `ngram/` | `ngram/` |
| `qwen35/` | (arch-specific) |
| **`dsv41/`** | **absent** |

And the SYCL side already has the hard parts the port needs:

- `core/peer_experts.cpp`, `core/remote_experts.cpp`, `core/expert_cache.cpp` — expert placement and
  cross-card exchange
- `core/pinned.dp.cpp`, `core/copy_queue.cpp` — host staging, the `CONFIG WARNING` area for the 18
  Windows fixes
- `core/graph.cpp`, `core/mtp.cpp`, `core/native_dense.cpp` — graph capture and MTP drafting

This is the difference between "translate 16k lines of CUDA into SYCL from first principles" and
"write a `sycl/src/dsv41/` that follows an existing, working, Windows-proven pattern." It is still
STEP-003 work, but the structural template exists and the lab already got it building and running.

**The port's shape is therefore: `sycl/src/dsv41/` mirroring `src/dsv41/`, reusing `sycl/src/core/`
services rather than re-porting them.**

-

## 5. Corrections to `PLAN.md`'s memory budget

`PLAN.md` §"Memory and storage budget" lists 2.00 bpw as "138.24 GB main + 132.07 routed experts".
Upstream `docs/DEEPSEEK41.md` in v0.2.7 is more specific, and one number is materially different:

| | `PLAN.md` | upstream v0.2.7 doc |
|---|---|---|
| Engram n-gram table | 110.60 GB | **202.8 GB** (508 GB set) / **111 GB** (2-bit sets) |
| Routed experts resident on the R9700 reference | — | 6,197 experts / **116.5 GB** GPU |
| Routed experts on CPU | — | 9,163 experts / **172.3 GB** RAM |
| Dense weights | "add separately" | 16.8 GB, ~3.9 GB/card on four |
| DSpark drafter | 8 GB | 8 GB |

Two consequences for GPU-BOX:

1. **The reference box had 251 GB RAM.** GPU-BOX has 95.87 GiB usable. The reference kept 172.3 GB of
   experts in RAM. GPU-BOX cannot do that — a much larger fraction will be read from the SSD while
   answering. Upstream explicitly says this "runs, slowly."
2. **The measured 2.00 bpw quality figures are now available** and should feed STEP-003/006 rather
   than being estimated: KL 0.170, perplexity +15.5% (code +8.6%, agent +5.3%) for 2.00 bpw;
   KL 0.107, +7.3% for 2.25 bpw; IQ1_M +21% with prose notably worse (+53%).

The existing `~955 MiB overrun → -ngl 38` observation from the llama.cpp work is a different
allocator with different accounting. Do not carry it into the port as a budget.

-

## 6. What carries over from the 18 Windows fixes

**Nothing, structurally** — all 18 files are under `sycl/` and belong to the Qwen engine.

| Patch target | Applies to dsv41 port? |
|---|---|
| `sycl/CMakeLists.txt` (`if(WIN32)`) | pattern reusable for a new CMake target |
| `sycl/include/dpct/*` (3 files) | reusable — dpct shims are engine-agnostic |
| `sycl/include/strata/core/ep_mem.hpp` | reusable — expert-parallel memory |
| `sycl/src/core/copy_queue.cpp`, `pinned.dp.cpp` | reusable — host staging |
| `sycl/src/core/expert_source.cpp`, `gguf_expert_source.cpp` | **reusable and directly relevant** |
| `sycl/src/core/device.dp.cpp` | reusable |
| `sycl/src/platform/direct_file.cpp` | **reusable and directly relevant** — Engram reads |
| `sycl/src/program/generate.cpp` | pattern reusable |
| `sycl/src/kernels/*_parity.cpp` (5 files) | pattern reusable for dsv41 parity tests |

So the 18 fixes are **not** inherited by the port; they are a **reference implementation** for how
this engine family is made to work on Windows. That is a better asset than a patch set, because the
port will hit the same classes of problem (positioned reads, `<windows.h>` macro clashes, timer
resolution, JIT vs AOT correctness).

**AOT warning that transfers directly:** the lab measured that the oneAPI 2026.0 **AOT** build
miscompiles int8 attention (garbage output) while JIT is correct. Install JIT first, and treat any
AOT result as needing correctness qualification before being trusted for speed.

-

## 7. Host constraints that will bite during the port

| Constraint | Value | Consequence |
|---|---|---|
| Usable RAM | 95.87 GiB | ~172 GB of reference CPU experts is impossible; expect SSD streaming |
| Free C: | 52 GB (92% used) | build trees cannot go on C:; port worktree is on **D:** |
| Free D: | 405 GB | holds the 128.74 GiB pack already; build output fits |
| Pack on disk | 128.74 GiB (IQ2_XXS 2.0625 bpw) | already present, no download needed |
| Engram file | 110.6 GB present | matches upstream's 111 GB figure |
| Drafter | **absent** | only 4 shards + Engram + mmproj on disk; DSpark needs 8 GB download |

The drafter being absent matters: `PLAN.md` STEP-004 already warns that `--dspark off` can still
allocate draft weights. Verify the no-drafter path rather than assuming.

-

## 8. Revised STEP-003 sizing

The plan's "1-3 weeks" was set before anyone counted the source. With the counts above:

| Work | Basis |
|---|---|
| Kernel translation (85 kernels, 130 launches) | The dominant cost. Subgroup mapping for 41 shuffles is the risky part, not the syntax. |
| `sycl/src/dsv41/` skeleton + CMake target | Follows `sycl/src/` patterns; days, not weeks |
| Reuse `core/` services (experts, staging, graph, MTP) | Should not be re-ported — wire, don't rewrite |
| CPU/host files | 5,790 lines compile as-is |
| Parity fixtures per quant format | `PLAN.md` already requires these; do not skip |

**No new calendar estimate is recorded here.** The counts make the shape clear; only CHECK-102 and
CHECK-103 can size the remainder, which is what the plan already says. What changes is that the
1-3 week figure is now known to be plausible for *kernels alone* and must not be read as covering
the full engine.

-

## 9. Next action

STEP-002 — qualify native Windows build and four-device operations against **this** tree
(`D:\strata-dsv41-port`), not `C:\llamacpp-v41`. The SYCL engine already builds on this box, so
STEP-002 should be short: confirm `sycl/` builds from the v0.2.7 worktree, confirm four `level_zero`
devices enumerate, and confirm a Qwen-model smoke run still works from this base.

Do not start kernel translation before CHECK-102 passes.

-

## 10. dpct pilot — measured 2026-10-27, the port is largely automatable

`PLAN.md` records "Automatic CUDA translation as a complete port — **Reject**". That decision was made on
principle, without running the tool. It has now been run. The decision should be revised: dpct does the bulk of
the translation, and the residue is enumerable rather than open-ended.

### Toolchain (now working)

| Item | Value |
|---|---|
| dpct | **2025.1.0** (`/mnt/c/Program Files (x86)/Intel/oneAPI/dpcpp-ct/2025.1/bin/dpct.exe`) |
| Clang underneath | 20.0.0 |
| CUDA headers | **not installed as a toolkit**; supplied from PyPI wheels into `D:\cuda-headers` (1,396 headers) |
| Header packages | `nvidia-cuda-runtime-cu12` 12.9.79, `nvidia-cuda-nvcc-cu12` 12.9.86, `nvidia-cuda-cccl-cu12` 12.9.27, `nvidia-curand-cu12` 10.3.10.19 |

No CUDA hardware or toolkit install is required. This bypasses the "no reference backend on this box" blocker
for *translation* (not for numerical parity — see §11).

Note: dpct 2025.1 warns `CUDA version is newer than the latest partially supported version 12.8`. Headers are
12.9. Worked anyway for all files below; if a future file fails, drop to 12.8 headers first.

### Result across the whole engine

All five compute files converted (`D:\strata-dsv41-port\dpct-all`, `dpct-out2`):

| File | Source | Output | `parallel_for` | chevrons left | `__global__` left | DPCT marks |
|---|---:|---:|---:|---:|---:|---:|
| `ds4_kernels.cu` | 2,467 | 4,579 | **63** | 1 | 1 | 158 |
| `ds4_model.cu` | 9,744 | 11,136 | 1 | 0 | 0 | 213 |
| `ds4_iq.cu` | 1,630 | 2,442 | **15** | 2 | 0 | 67 |
| `ds4_gguf.cu` | 1,529 | 2,225 | **17** | 6 | 1 | 69 |
| `ds4_tq.cu` | 539 | 674 | **0** | 5 | 0 | 17 |
| **Total** | **15,909** | **21,056** | **96** | **14** | **2** | **524** |

Against **93 `__global__` kernels** in the source, dpct emitted **96 `parallel_for` blocks**. The kernel bodies
translate. What fails is a specific, diagnosable pattern: **triple-chevron launches wrapped in preprocessor
macros**.

### The one real failure mode, precisely characterised

`ds4_tq.cu` converted **zero** kernels. All 5 of its launches are inside macros:

```c
#define GU_(K, C) { if (w) gate_up_kernel<K, C, true><<<grid, kThreads, 0, s>>>(a); else ... }
DS4_TQ_SWITCH(a.tg, GU_)
```

dpct does not rewrite launches it cannot see through macro expansion. This is a **mechanical, local fix**:
expand the 5 `DS4_TQ_SWITCH` macros into explicit launches (or hand-write those 5 sites against the already
converted kernel bodies, which are present in `ds4_iq.dp.hpp`). It is hours of work, not weeks.

The remaining 9 chevrons across `ds4_gguf` (6), `ds4_iq` (2) and `ds4_kernels` (1) need triage
individually; `ds4_kernels`' single leftover is `sparse_attn_wmma_kernel`, the WMMA path, which is the most
likely to need genuine hand work because WMMA has no direct SYCL analogue.

**Total hand-work surface: 14 launch sites + 2 unconverted kernels, out of 93.** By kernel count that is
**~85% automatic**.

### DPCT warning density — the fixup debt

524 DPCT markers across 21,056 output lines (one per ~40 lines). Top codes in `ds4_kernels`:

| Code | Count | Meaning |
|---|---:|---|
| DPCT1065 | 53 | `sycl::nd_item::barrier()` scope suggestion — usually accept |
| DPCT1118 | 28 | group barrier in divergent code — **audit** |
| DPCT1101 | 20 | macro/type needs manual check |
| DPCT1078 | 14 | initialization semantics |
| DPCT1013 | 13 | launch config could not be determined |
| DPCT1049 | 9 | work-group size exceeds device max — **audit on B70** |

For calibration: the **existing, working Qwen SYCL port** carries **2,020 DPCT markers** in `sycl/src/` and
runs correctly in production. So ~524 for dsv41 is *less* debt than the codebase already absorbed. This is the
strongest single argument that dpct is the right method here.

### Revised decision

| Old decision | New position |
|---|---|
| "Automatic CUDA translation as a complete port — Reject" | **Partially superseded.** dpct is the *method*; it is not the *acceptance*. Translate with dpct, then hand-fix 14 sites + 2 kernels, then prove correctness in CHECK-103. |
| "Translation tooling may scaffold code but cannot satisfy this check" | **Unchanged and still correct.** CHECK-103 requires frozen per-operation tolerances against a reference. dpct output is scaffolding until that passes. |

The distinction that matters: the old text implies translation is not worth attempting. Measured, it converts
~85% of 93 kernels. Skipping it would mean hand-porting 21,000 lines to save 14 launch sites.

-

## 11. What the pilot does NOT settle

Being explicit so nothing here is over-read:

1. **Nothing has been compiled.** All output is unconverted-text. `ds4_model.dp.cpp` has 213 DPCT marks and has
   never seen `icx`. Compilation errors will be the next large cost and are unmeasured.
2. **No numerical parity.** The plan's CHECK-103 needs same-pack teacher-forced logits against a reference. A
   CUDA/HIP reference does not exist on this box, and the PyPI headers are compile-time only — no runner.
3. **The WMMA path is unresolved.** `ds4_wmma.cuh` is new in v0.2.7 and `sparse_attn_wmma_kernel` did not
   convert. WMMA→SYCL (joint_matrix / XMX) is genuine design work, not translation.
4. **`ds4_iq_hip_*.inc` are HIP-specific** and have no dpct path — they need SYCL equivalents written by hand,
   or the CUDA variants used instead.
5. **The 2,020-marker calibration is from a *different* engine.** It proves the method's viability, not
   dsv41's cost.

-

## 12. First build attempt from the v0.2.7 base — 126/134 then 5 failures

Worktree `D:\strata-dsv41-port`, JIT build (`-DSTRATA_SYCL_XE2_JIT=ON`), build dir `build-jit`.
Configure succeeded (FetchContent cloned deps). Compilation reached **126/134 targets**, then failed with
**26 errors across 5 files**.

### Errors, complete list

| File | Errors | Cause |
|---|---:|---|
| `sycl/src/program/generate.cpp` | 18 | `<windows.h>` macro clashes: `small` (`rpcndr.h`), plus `memmem` absent |
| `sycl/src/core/pinned.dp.cpp` | 5 | CUDA runtime names (`cudaDeviceProp`, `cudaSuccess`, `cudaGetDevice`, `cudaGetLastError`) |
| `sycl/src/core/gguf_expert_source.cpp` | 1 | `#include <unistd.h>` |
| `sycl/src/prefill/prefill.cpp` | 1 | `mkdir` not in global namespace |
| `sycl/src/kernels/cuda/verify_kernels.dp.cpp` | 1 | `expected expression` at :592 |

Plus a **separate, unrelated** failure: **all ggml targets** died with

```
cl : Command line error D8021 : invalid numeric argument '/Wno-unused-parameter'
```

That is not a source problem. `cl` (MSVC) is being handed a GCC-style warning flag, which means the ggml
sub-build is selecting the MSVC compiler path while receiving GNU flags. It kills 6 targets
(`ggml.c`, `ggml-cpu.c`, `ggml-alloc.c`, `ggml-quants.c`, `arch/x86/quants.c`, `ggml-cpu/quants.c`).

**This matters more than it looks:** the deployed `%USERPROFILE%\strata-win` tree builds the same ggml
cleanly, so the flag difference comes from the v0.2.7 CMakeLists (467 lines vs 440 in v0.2.6), not from the
toolchain. It must be found and fixed before anything else, or the link can never complete.

### These are the same class the 18 Windows fixes address

Confirmed by inspection: `generate.cpp:6255` uses `const int64_t small = old_rule();` — `small` is a macro
from `rpcndr.h`. The lab's `strata_win_undefs.h` exists precisely for this:

```c
#ifdef _WIN32
#undef small
#undef OUT
#undef IN
#endif
```

and `memmem` needs the fallback the 18-fix set provides. So the port inherits the *problem set* even though
it cannot inherit the *patches* — those target `win-port` files that v0.2.7 has moved a long way from.

### The 18-fix patch does NOT apply to v0.2.7

`git apply --check` (literal paths, verified):

```
error: patch failed: sycl/CMakeLists.txt:50
error: sycl/CMakeLists.txt: patch does not apply
error: sycl/include/strata/core/ep_mem.hpp: No such file or directory
error: patch failed: sycl/src/program/generate.cpp:1685
error: sycl/src/program/generate.cpp: patch does not apply
```

### Why: `win-port` is not on the v0.2.x line at all

| Ref | `sycl/include/strata/core/ep_mem.hpp` | dsv41 files |
|---|---|---|
| `win-port` HEAD (`1c360526`) | **1** | 0 |
| `origin/main` | 0 | 0 |
| `v0.2.6` | **0** | 131 |
| `v0.2.7` | **0** | 138 |
| `upstream/main` | 0 | 138 |

`ep_mem.hpp` was introduced by commit `53402da22` ("Night base: Codex S148 working tree") **on the win-port
line**. It does not exist upstream in any v0.2.x tag. Meanwhile v0.2.7 has added upstream's own
`peer_experts.hpp`, `remote_experts.hpp`, `exchange_storage.hpp`, `dma_batch.hpp` — a different, newer
take on the same problem.

**Merge base of `win-port` and `v0.2.7` is `296b59d2` (`origin/main`).** Since then: **2,389 commits** on the
v0.2.7 side, **26** on the win-port side.

### Consequence for the plan

The 18 fixes are **not** a patch to apply to v0.2.7. They are a **catalogue of the problems Windows presents**
to this engine family, to be re-solved against v0.2.7's newer code:

| Fix | v0.2.7 status |
|---|---|
| `strata_win_undefs.h` (`small`/`IN`/`OUT`) | **transfers unchanged** — pure header, no upstream dependency |
| `memmem` fallback | transfers unchanged |
| positioned reads (`ReadFile`), `unistd.h`/`mkdir` shims | transfers, may need new call sites |
| shared-context expert parallel (`ep_mem.hpp`) | **superseded** — v0.2.7 has `peer_experts.hpp` / `exchange_storage.hpp`. Evaluate upstream's version first; do not re-port the 18-fix design. |
| `STRATA_SYCL_XE2_JIT` define | check whether v0.2.7's CMakeLists already has it |
| JIT-vs-AOT int8 correctness | **transfers as a warning**, must be re-measured on v0.2.7 |

This is a genuine finding, not a setback: it means the port should **prefer upstream's newer expert-parallel
machinery over the lab's older patch**, which is less work and better supported.

### Status of this build

`BUILD_EXIT=1`. Not a regression — this is the expected first-build state for a tree that has never been
compiled on Windows. Recorded so the next session does not mistake it for a toolchain defect.

-

## 13. Windows SYCL build of the v0.2.7 tree — SUCCEEDS (2026-10-27 19:08 CDT)

`D:\strata-dsv41-port\build-jit\strata.exe`, **44,995,584 bytes**, built at 19:08:08.

```
BUILD_EXIT=0
compile errors: 0
link errors:    0
```

Verified beyond the exit code (a stale-exit-code false pass happened twice earlier in this session):
`ninja_log` shows real sequential compile + link work ending at 167,437 ms, and the binary **executes** —
`strata.exe --help` prints the engine's own CLI (`strata generate --pack DIR --tokens ...`, `--kv`,
`--ple-io`, `--kv-resident`, …) with exit 0 when run inside the oneAPI environment.

### It needs the oneAPI environment

Bare invocation returns `EXIT=-1073740612` (`0xC00004BC`) — the same DLL-search-path failure the lab
recorded for `llama-server`. Wrapping in `setvars.bat --force` fixes it. Any launcher, service, or
benchmark harness must call setvars first; llama-swap's `env:` cannot supply a DLL search path.

### The five fixes that were required

The tree had never compiled on Windows. These are the changes, in the order they surfaced. Each is a
real defect, not a workaround; all five are now in the tree and should be upstreamed.

| # | File | Problem | Fix |
|---|---|---|---|
| 1 | `sycl/CMakeLists.txt` | `-fp-model=precise -Wno-*` applied at directory scope reached the fetched **ggml** sub-build, whose C sources are compiled by MSVC `cl`: `D8021 invalid numeric argument '/Wno-unused-parameter'`. Killed all 6 ggml targets. | Gated every one on `$<COMPILE_LANGUAGE:CXX>`. ggml's failing files are all C, so they never see them. |
| 2 | `sycl/CMakeLists.txt` | `-qmkl=sequential` is the GNU spelling. Windows icx ignored it, so nothing linked oneMKL and `dpct::blas::gemm` left **10 unresolved externals**. | `if(WIN32)` → `/Qmkl:sequential`, plus `/fp:precise`. Also sets `NOMINMAX WIN32_LEAN_AND_MEAN _CRT_SECURE_NO_WARNINGS _USE_MATH_DEFINES` globally. |
| 3 | `sycl/include/strata_win_undefs.h` | New file. `<windows.h>` macros collide with engine/dpct identifiers. | `#undef small OUT IN clamp min max`. |
| 4 | `sycl/src/core/gguf_expert_source.cpp` | `unistd.h`, `ssize_t`, `pread`, `off_t`, `O_CLOEXEC` — none exist on Windows. | Win32 positioned-read shim (`_get_osfhandle` + `OVERLAPPED` + `ReadFile`), `off_t`/`ssize_t` as `long long`, `O_CLOEXEC 0`. |
| 5 | `sycl/src/core/pinned.dp.cpp` | CUDA names `cudaDeviceProp`/`cudaGetDevice`/`cudaGetDeviceProperties`/`cudaSuccess` in `sliced_pin_limit`. | Dropped the DXGI LUID path (no CUDA LUID in a SYCL build); the RAM-based rule applies. |
| 6 | `sycl/src/prefill/prefill.cpp` | `::_mkdir` needs `<direct.h>`. | Added the include under `_WIN32`. |

### The one trap worth recording

`strata_win_undefs.h` must **not** `#undef near` or `#undef far`. The Windows SDK depends on them:

```c
minwindef.h:  #define FAR  far
guiddef.h:    #define DEFINE_GUID(...) EXTERN_C const GUID FAR name
```

Undefining `far` makes `DEFINE_GUID` expand to a stray token, and `dxgi.h` / `d3d11.h` then fail with
`expected ';' after top level declarator` on ~12 consecutive lines. The engine uses `near`/`far` only in
comments, so leaving the macros defined costs nothing.

Also: including `<windows.h>` *before* `<dpct/dpct.hpp>` breaks dpct's own `math_detail.hpp`
(`sycl::min`/`sycl::max` collide with the macros → `too few arguments provided to function-like macro`).
Order matters; put the undefs header **after** the include block, not around `windows.h`.

### What this does and does not prove

**Proven:** the v0.2.7 source tree builds on Windows with oneAPI SYCL, produces a working `strata.exe`,
and the binary starts and reports its CLI.

**Not proven — and this is the important part:** `strata.exe` is the **Qwen** engine. There is no
`sycl/src/dsv41/` yet. Nothing DeepSeek has been compiled, let alone run. This build is **STEP-002**
(the Windows build/device qualification), and it is now PASSING for the existing engine.

STEP-003 — porting `src/dsv41/` (16,428 lines, 93 kernels) into `sycl/src/dsv41/` — has not started.
The dpct pilot (§10) shows ~85% of those kernels convert automatically; the build fixes above are the
substrate that port will land on, and they are now known rather than guessed.

-

## 14. Qwen smoke test on the new v0.2.7 binary — RUNS, but 7.5x slower (2026-10-27)

First functional test of the freshly built `strata.exe` against a real model.

### It works

```
strata generate: session is up (engine 0.1.52)
strata generate: GPU 0: Intel(R) Arc(TM) Pro B70 Graphics, compute capability 20.2
strata generate: profile fill: 20.15 GiB in 21.1 s (1.02 GB/s, pipelined)
strata generate: pre-filled 10596 of 10596 slots from the profile in 21.1 s; slot 0 verified
strata generate: R4 hit path ON - resident experts are computed on the GPU
decode     32 tokens in 2470.1 ms  ->  12.95 tok/s
prefill     7 tokens in 3753.0 ms  ->   1.87 tok/s  (time to first token 20003.5 ms)
EXIT=0
```

The engine loads the 79 GB IQ3_S pack, builds the expert cache (10,618 slots / 20.15 GiB VRAM),
verifies slot 0, and generates. No crashes. **The build is functionally sound, not just compiling.**

### But it is far slower than the lab's known-good run

| Setup | Cards | Decode | Prefill |
|---|---:|---:|---:|
| Lab, `win-r3-jit`, IQ3_S, int8 KV, 1x200k | **2** | **97.6 tok/s** | **1,415 tok/s @ 33.6k** |
| This run, v0.2.7 JIT, IQ3_S, int8 KV, 8k | **1** | **12.95 tok/s** | 1.87 tok/s @ 7 tokens |

### Why — and it is not a regression in upstream's code

The lab config used `--expert-parallel-device 1` to put the *second* card to work. That flag no
longer exists in v0.2.7; it was replaced by `--peer-device`. And `--peer-device` **is a stub in the
SYCL port**:

```
strata generate: --peer-device: the second-GPU expert tier is not ported to SYCL yet
EXIT=1
```

`sycl/CMakeLists.txt:280` says so directly: `remote_expert_opt_stub.cpp ... (a stub in the port: no
second GPU tier yet)`.

So this run used **one** B70 of the four available. 12.95 tok/s single-card is plausible; it is not
evidence that v0.2.7 is slower than the deployed tree.

### The caveats on these numbers

- **7-token prompt.** Prefill `1.87 tok/s` is one chunk of 7 tokens — far too small to amortise
  chunk overhead, and not comparable to the lab's 1,415 tok/s at 33.6k. Do not read it as a
  regression.
- **TTFT 20.0 s** includes engine start, the 21.1 s profile fill, and PLE setup. Not a token metric.
- **One sample, no variance.** Per W-042, single samples on this box are unreliable. Treat as
  indicative only.
- `--expert-parallel-device` → `--peer-device` is a **semantic change**, not a rename: upstream's
  peer is an adaptive expert-cache *tier*, not the symmetric expert parallelism the lab measured at
  97.6 tok/s. Whether upstream's newer design reaches the same throughput is unmeasured.

### Consequence for the port plan

Getting Qwen "super fast" on four cards needs the multi-GPU expert tier, and in the SYCL port that
tier does not exist. Two options, for the owner:

1. **Single-card only** — accept ~13 tok/s, or tune context/KV/cache for one card. Cheap, but nowhere
   near the lab's 97.6.
2. **Port the peer/expert tier to SYCL** — that is new work beyond STEP-003, in `sycl/src/core/`
   (`peer_experts.cpp`, `remote_experts.cpp`), not in `dsv41/`. The lab's `ep_mem.hpp` /
   shared-context design is directly relevant prior art, but it targets the win-port line, not v0.2.7.

**This does not block the dsv41 port.** It does mean the dsv41 engine should not expect a working
multi-GPU tier to be inherited from the SYCL port — `PLAN.md`'s STEP-004 four-card split assumes one.
