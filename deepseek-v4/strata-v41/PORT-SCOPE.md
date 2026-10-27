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
