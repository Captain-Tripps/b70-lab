# GLM-5.3 on 4× B70: Hill-Climbing Roadmap

## Current checkpoint — updated 2026-10-21

The first execution sprint is recorded in [HILLCLIMB-2026-10-20.md](./HILLCLIMB-2026-10-20.md).
That document remains the detailed experiment log, but the following corrections and later findings supersede its
working diagnosis.

### Verified findings

- The known-good `r67c` result remains the best validated arm: 16k context, `-b 512 -ub 128`, semantic quality
  passing, and 23.4 tok/s mean decode on the fixed two-round benchmark.
- The staged current build (`b739`, commit `429852e27`) fails the DIO first-request memory gate at the same 16k
  settings: approximately 118.1 GB private bytes, 98.3 GB working set, and 4.94 GB available when the watchdog kills
  it.
- A minimal current-upstream build (`b735`, commit `909ca928e`) reproduces that first-request failure at
  approximately 118.1 GB private bytes and 97.0 GB working set. This makes the newer upstream base or runtime
  residency behavior more suspicious than the later MTP patch stack, but it is not yet a completed source bisect.
- Reverting upstream ESIMD restoration (#30239), or disabling ESIMD at runtime, made load residency worse. ESIMD is
  therefore not the root cause by itself and currently helps the model fit farther into initialization.
- The attempted reordered-`GET_ROWS` (#30430) isolation on October 21 is invalid: Strata had auto-started and was
  consuming about 63 GB of host RAM. Do not use that result.
- The host-memory cliff is sensitive to machine noise. With Strata stopped, a DIO arm was still killed during load
  at 4.87 GB available, 109.4 GB private bytes, and 92.9 GB working set. No A/B result is valid unless the starting
  process list and available RAM are captured and identical.
- `--load-mode none` is a verified operational fallback for the current `b739/429852e27` runtime at 16k:
  the first request returned HTTP 200, produced the exact requested answer, decoded at 17.18 tok/s, processed the
  short prompt at 1.22 tok/s, accepted 7 of 10 drafted tokens, and remained healthy. It is stable enough for
  diagnosis but is not a performance winner.
- Runtime directory names are not trustworthy identifiers. A directory labeled `r67` reported fingerprint
  `b739-429852e27`. Every arm must record `llama-server --version`, the API fingerprint, and hashes of
  `llama-server.exe`, `ggml-sycl.dll`, `llama.dll`, and `llama-server-impl.dll` before launch.
- Old source commit `14897007d` was reconstructed and built with oneAPI 2026 after applying only its required
  compile repairs. It is staged as `master-797de63-r67-rebuilt-current-toolchain`, but it has not received a valid
  clean-memory benchmark.

### Revised immediate lane

1. Inventory and hash every staged runtime; identify the genuine archived build-702 artifacts.
2. Capture an idle-machine manifest and require enough host-memory margin to remain above the 6 GB watchdog floor.
3. Run only the archived build-702 versus rebuilt-old-source A/B, with identical DLL sets and launch arguments.
4. If rebuilt old source regresses, isolate compiler/runtime artifacts before touching upstream source.
5. If rebuilt old source passes, resume a source bisect between `797de63b2` and `3bb63cbcb`.
6. Do not begin new kernel work until this attribution is complete.

### Agent operating rules learned

- Never infer activity from a launched PID; verify the process, endpoint health, and watchdog log.
- Never report a benchmark while an unrelated model server is resident.
- Do not shut down WSL after launching a Windows child from that session; it terminates the child and invalidates the
  run.
- Keep one experiment active at a time and publish a result only after survival, correctness, and fingerprint checks.

This roadmap starts from the measured `g10` / rebased `r67c` state in
[`b70-lab/glm-5.3`](https://github.com/Captain-Tripps/b70-lab/tree/main/glm-5.3): Maya-M, 4× Arc Pro B70,
128k context, one expert layer on CPU, about 24–25 tok/s on prose, 33–35 tok/s on copy-heavy edits, and
330–370 tok/s on long prompt reads.

The objective is not “try optimizations.” It is to maximize useful tokens per second while preserving quality,
128k context, and operational stability. Every experiment must have a mechanism, a ceiling, a correctness gate,
and a stop condition.

## Executive order of attack

1. **Harvest newer upstream SYCL work.** The validated rebase uses upstream `797de63b2` from October 17. Current
   upstream is 32 commits ahead and includes the restored ESIMD FFN decode path, a reordered-weight prompt fix,
   and reordered `GET_ROWS` correctness support. Test these before writing another kernel.
2. **Recover an all-VRAM Maya-M-like configuration.** Explicit placement, cache compression, or a minimally mixed
   Maya-M/Maya-S quant may eliminate the CPU expert layer. This has the best effort-to-upside ratio after upstream.
3. **Optimize the measured dense decode shapes.** Extend or replace the existing batched Q6_K MLA work for the
   remaining Q6_K query/output projections and shared/dense FFN paths.
4. **Raise IQ2_S expert bandwidth.** The routed-expert kernel is still only about 175 GB/s effective and is the
   clearest model-specific kernel target.
5. **Make MTP adaptive.** Preserve `n=4` for prose, opportunistically use deeper drafts on sustained copy-heavy
   output, and back off quickly when acceptance falls.
6. **Only then profile deep-context indexer/attention work and model-specific multi-GPU execution.** These are
   plausible but larger bets; neither should begin without an Amdahl-style ceiling.

## Definition of success

Use three scoreboards rather than one headline tok/s number:

| Scoreboard | Required workloads | Primary metric |
|---|---|---|
| Decode | prose, code generation, JSON, continuity edit, repetitive code edit | median and geometric-mean tok/s |
| Depth | decode after 32k, 64k, and 120–128k prompts | tok/s and degradation from short context |
| Prompt | 8k, 32k, and 112k prompt reads | prompt tok/s and time to first token |

Track acceptance separately from throughput. A faster-looking broken model can inflate MTP acceptance, as the lab
already saw with the bad Strata AOT build.

Adopt a candidate only when all of these hold:

- `squal.py` passes before speed testing.
- Relevant `test-backend-ops` cases pass against CPU.
- Batch-1 perplexity is identical when the change should be numerically exact. If it is intentionally non-exact,
  stop and require a pre-declared quality budget plus KLD/top-token checks.
- The same-session A/B/B/A result clears noise: at least **+3% geometric mean**, or **+8% on a declared specialist
  workload** with no material regression elsewhere.
- Each card retains practical VRAM headroom; do not accept a configuration sitting on the WDDM spill cliff.
- At least 10 GB of host RAM remains free during load and long-context operation.
- A 30-minute mixed soak passes before switching the live entry.

## Phase 0 — Freeze a reproducible baseline

**Goal:** make every later result attributable.

The agent should create one immutable experiment manifest containing:

- llama.cpp commit and local patch stack;
- exact hashes and shard names for Maya-M and the MTP draft;
- driver, oneAPI compiler/runtime, build flags, and device order;
- all server flags, tensor overrides, split values, and environment variables;
- per-card VRAM after load, host RAM after load, and model-load time;
- `sbench.py` prompt revision and the fixed perplexity corpus hash.

Run and retain these baseline arms:

| ID | Configuration | Purpose |
|---|---|---|
| B0 | g10 live settings, MTP `n=4`, `p=0.75` | production reference |
| B1 | r67c GLM settings | current unified-fork reference |
| B2 | same as B1, MTP off | expose target-model cost |
| B3 | same as B1 at 2k / 32k / 64k / 128k | isolate depth cost |
| B4 | Maya-S, all VRAM | speed/quality upper comparison, not a replacement |

For each decode request record target steps, draft steps, accepted draft length histogram, verify-batch width, output
tokens, wall time, per-card utilization/power, and peak VRAM. Do not reduce this to one average.

**Exit condition:** two repeated baseline sessions agree within 2–3% on the geometric mean.

## Phase 1 — Harvest upstream before inventing work

**Why first:** upstream after `797de63b2` contains directly relevant SYCL changes:

- [`#30239`](https://github.com/ggml-org/llama.cpp/pull/30239) restores ESIMD kernels on the FFN path and extends
  fused gate/up/GLU support to Q8_0. An Arc A770 review measured about +12% token generation on Q4_K; GLM's gain is
  unknown, but its dense/shared FFN projections make this a high-value test.
- [`#30374`](https://github.com/ggml-org/llama.cpp/pull/30374) fixes the post-reorder Q4_0/Q8_0 prompt-processing
  regression. It was verified on B70 and can matter after any decode step has reordered weights.
- [`#30430`](https://github.com/ggml-org/llama.cpp/pull/30430) makes `GET_ROWS` correct for reordered quantized
  weights. Treat it as a correctness prerequisite when shared/tied weights can be reordered.

Agent procedure:

1. Rebase the GLM patch stack onto current upstream without changing launch flags.
2. Run correctness and the full B0–B4 matrix.
3. If the aggregate changes, use feature switches or a short commit bisect to attribute it to ESIMD FFN, prompt
   reorder handling, or unrelated upstream movement.
4. Keep the new base even for a neutral GLM result if correctness is equal and it removes local divergence.

**Go condition:** any clear decode or prompt win, or neutral speed with reduced patch burden.

**Stop condition:** do not tune the older DMMV/GLU path until the ESIMD result is known.

## Phase 2 — Eliminate the CPU expert layer

This is the highest-probability system-level win. Maya-M needs one layer's expert tensors on CPU for 128k, while
Maya-S fits fully in VRAM and reaches 27.5 tok/s but loses too much quality. The right target is a minimally smaller
Maya-M, not a wholesale switch to Maya-S.

### 2A. Build a tensor and allocation ledger

Dump every tensor's name, type, bytes, and device, plus non-weight buffers by device at 2k and 128k. Identify exactly
how many bytes must move or disappear to keep `blk.44.ffn_*_exps.weight` in VRAM with at least 1–1.5 GB headroom.

Test placement-only variants first:

- move the MTP block and output head away from the fullest card with explicit tensor overrides;
- search card ordering and `-ts` values programmatically, because this setup observes reversed split mapping;
- place only the minimum necessary output/draft tensors on another GPU rather than offloading an expert layer;
- inspect whether prompt scratch, k-pool cache, or reorder extras are disproportionately allocated on card 0.

### 2B. Compress cache/state only enough to fit

Measure cache allocations by family before changing formats. If supported by the GLM hybrid cache, test Q8 cache
for the MLA latent/indexer state one component at a time. Verify deep-context answers and perplexity; do not assume a
KV format accepted by ordinary attention is valid for KDA/MLA state.

### 2C. Make a mixed quant instead of accepting Maya-S globally

Construct the smallest hybrid that saves the bytes found in 2A:

1. Keep all dense, attention, embeddings, output, and most routed experts from Maya-M.
2. Replace only one layer's routed expert tensors with the corresponding Maya-S tensors, or requantize selected
   low-sensitivity expert matrices.
3. Start with late, middle, and early-layer candidates separately; compare perplexity/KLD to locate the least
   sensitive placement.
4. If one layer is insufficient, add layers greedily by quality-cost per byte saved.

This directly tests whether “one slightly cheaper GPU layer” is better than “one full-quality CPU layer.”

**Expected upside:** potentially high single digits to low teens at decode, especially at depth. The 27.5 tok/s
Maya-S result is only an upper signal because quantization and placement both changed.

**Stop condition:** stop if the required bytes cannot be saved without exceeding the Maya-M quality budget, or if
the all-VRAM build gains less than 3% end to end.

## Phase 3 — Build a trustworthy bottleneck map

Do not use the existing serial per-op profile as a literal wall-time breakdown; the lab notes that it inflates small
ops. Add targeted event timing around only the candidate kernels, and combine it with whole-step wall time and GPU
busy traces.

Profile this matrix:

| Axis | Values |
|---|---|
| Context | 2k, 32k, 64k, 128k |
| Decode mode | no draft, MTP prose, MTP copy/edit |
| Verify width | 1, 2, 3, 4, 5, 6 tokens |
| Operator family | routed MoE, shared FFN, Q/K/V/out projections, KDA, indexer, sparse attention, copies/sync |

For every candidate family calculate:

`maximum speedup = 1 / ((1 - fraction) + fraction / proposed_kernel_speedup)`

Only open an implementation lane if its end-to-end ceiling is at least 5%, unless it also removes a correctness or
maintenance problem.

Add a memory roofline for each hot mat-vec: bytes read, useful operations, measured duration, effective GB/s, and
the same kernel with cold expert selection. MoE microbenchmarks with repeated experts are not acceptable evidence.

## Phase 4 — Dense Q6_K / Q8_0 decode lane

The lab already estimates the remaining Q6_K attention query/output projections at a combined 5–10%. The current
one-launch MLA kernel solved the 64 per-head `attn_k_b` / `attn_v_b` launch pattern, but not all dense projections.

Agent tasks, in order:

1. Inventory every hot Q6_K/Q8_0 `MUL_MAT` shape in trunk and MTP graphs, including batch widths 1–6.
2. Check which shapes now enter the upstream ESIMD path and which still fall back to generic DMMV/MMVQ.
3. Benchmark the candidate kernel on the exact model shapes with cold weights and in the full graph.
4. Extend the ESIMD/reordered path to missing `n=1..6` shapes before creating another standalone kernel.
5. For paired projections reading the same activation, test one dispatch with two accumulators only when the tensor
   layout permits coalesced reads. Keep it behind a switch.
6. Test shared-expert gate/up/GLU fusion separately from attention projections; their cache behavior differs.

Correctness gate: exact op tests for every tensor type/shape plus batch-1 perplexity. The earlier hc fusion showed
that matching one fused output is not sufficient if skipped intermediates alter scheduling or reuse.

**Stop condition:** stop after two kernel-layout attempts if the exact shape does not improve at least 8% or the
end-to-end ceiling falls below 3%.

## Phase 5 — IQ2_S routed-expert lane

The routed-expert kernel is the main original kernel target. Start with measurement, not another codebook-placement
experiment—the local-memory codebook attempt already lost.

Agent tasks:

1. Split time into weight fetch, IQ2 decode, activation fetch, reduction, and routing/launch overhead using exact
   GLM shapes and real expert sequences.
2. Determine whether 175 GB/s is limited by global reads, unpack instructions, local-memory traffic, occupancy,
   register pressure, or the small number of selected rows.
3. Inspect compiler output for scalar loads, redundant sign/codebook construction, spills, and missed vectorization.
4. Try, one variable at a time:
   - an expert-specific reordered storage layout for contiguous wide loads;
   - ESIMD/SIMD block loads with arithmetic sign derivation;
   - double-buffered activation/scale staging;
   - row-pair processing when it improves weight access without reducing occupancy;
   - separate kernels for `n=1` and MTP verify widths instead of one compromised template.
5. Re-run with randomized routed experts so L2 cannot fake the result.

Do **not** retry unchanged:

- IQ2_S codebook in local memory;
- grouping the MTP window by distinct expert;
- a microbenchmark that repeatedly hits the same experts.

**Go condition:** at least +15% on the routed-expert operator and +3% end to end on the varied harness.

## Phase 6 — Adaptive MTP policy

The current fixed policy is already good: `n=4`, `p=0.75` keeps prose flat and gives +17–18% on copy-heavy work.
`n=6` helps copy slightly but costs about 4% on prose. That is a routing opportunity, not a reason to pick one global
setting.

First collect, by workload and generation position:

- accepted draft-length histogram;
- verify cost by width;
- drafter cost per proposed token;
- target-only fallback cost;
- output entropy or top-1 probability if available cheaply.

Then implement a conservative per-request controller:

- start at `n=4`;
- move to `n=6` after a sustained high-acceptance window, such as 16–32 target tokens with mean accepted length
  above a tuned threshold;
- return immediately to `n=4` after one poor verify window;
- optionally use `n=2` or disable drafting after repeated low acceptance;
- do not add n-gram or suffix drafting in front of GLM MTP without new representative evidence.

Sweep thresholds on separate prose, code-generation, JSON, and copy/edit sets. Optimize wall time, not acceptance.

**Expected upside:** small aggregate gain but meaningful specialist gain with low implementation risk.

## Phase 7 — Deep-context lane

Short decode is 24–25 tok/s and deep decode is 20–23, so all depth-only work has a bounded ceiling. Open this lane
only after Phases 1–6 or if 128k performance is the primary product requirement.

Compare 2k versus 128k target steps and attribute only the delta. Likely suspects from the GLM graph are:

- k-pool lightning-indexer scoring;
- top-k, argsort, gather, cast, and mask construction around pool selection;
- sparse attention over the selected cells;
- host/device uploads of dynamic selection inputs;
- cache layout and extra copies in the hybrid KDA/MLA memory path.

Prioritize a fusion only if the delta profile shows it is material. A promising pattern is a single indexer-select
kernel that performs top-pool selection and emits the final indices/mask, avoiding the current chain of top-k,
gathers, argsort, casts, arithmetic, and `SET_ROWS`. Validate index order and causal masking exactly.

**Stop condition:** no work here may claim more gain than the measured 2k-to-128k gap.

## Phase 8 — Model-specific multi-GPU research gate

Generic `-sm tensor` is closed: GLM fell to 4.8 tok/s because it created roughly 1,000 tiny per-card graphs and paid
host synchronization constantly. Do not revisit it with tuning flags.

The only multi-GPU research worth considering is a model-specific path with a bounded number of exchanges:

1. Measure routed-expert, dense projection, and everything-else fractions in normal execution.
2. Compute the zero-communication ceiling for expert parallelism and dense+expert tensor parallelism.
3. Microbenchmark the proposed host-USM exchange on this exact Windows/driver stack: hidden-state broadcast and
   partial-sum gather for one layer, under load.
4. Proceed only if the communication-adjusted model predicts at least **1.3×** end-to-end speedup.
5. Prototype one layer behind a switch before changing model placement globally.

Expert parallelism may fit GLM better than it fit DeepSeek because GLM's remaining bottleneck appears more expert
heavy, but that is a hypothesis. The overlap study does not prove it; grouped verification already lost 5–10%.

## Known dead ends

An agent should not retry these unless it can state what material condition changed:

- generic `-sm tensor` for GLM;
- SYCL graph replay with changing MTP/KV shapes;
- broad small-op fusion as a strategy;
- grouped expert verification by distinct expert;
- IQ2_S codebook in local memory;
- `GGML_SYCL_MKL_FA_*` for GLM;
- `-ub 1024` in the current memory layout;
- Maya-S as a drop-in replacement for Maya-M;
- n-gram lookup ahead of GLM MTP;
- MTP `n=6` as a universal default.

## The agent's experiment loop

For each hill-climb step, the agent must produce this record before coding:

```text
Hypothesis:
Affected graph nodes and exact shapes:
Measured fraction of wall time:
Theoretical maximum end-to-end gain:
Expected mechanism:
Correctness risk:
Implementation switch / rollback:
Benchmark arms:
Go threshold:
Stop condition:
```

Then execute:

1. Check the machine is idle and freeze the baseline process list.
2. Build one candidate with an off switch; never compare unrelated patch stacks.
3. Run targeted op correctness tests.
4. Run `squal.py`.
5. Run batch-1 perplexity; run KLD/top-token checks for quant/cache changes.
6. Run same-session A/B/B/A with clean environments and 28+ samples per arm for decode work.
7. Run the depth and prompt scoreboards if the touched path can affect them.
8. Inspect VRAM, host RAM, clocks, utilization, and MTP acceptance before interpreting tok/s.
9. Keep, reject, or revise once. After two failed revisions, close the lane unless new evidence changes the model.
10. Record winners and losers in `STATUS.md`, the topic notes, `CHANGELOG.md`, and `rejected-ideas/` as appropriate.

## Suggested backlog, ranked

| Rank | Experiment | Effort | Likely value | Decision gate |
|---:|---|---:|---:|---|
| 1 | Rebase and test upstream ESIMD FFN/reorder fixes | 0.5–1 day | medium/high | full B0–B4 matrix |
| 2 | Tensor/allocation ledger + explicit placement search | 0.5–1 day | high | enough bytes for GPU expert layer |
| 3 | One-layer mixed Maya-M/Maya-S expert quant | 1–2 days | high | quality per byte saved |
| 4 | Exact-shape Q6_K/Q8_0 ESIMD coverage | 1–3 days | medium | ≥8% operator, ≥3% model |
| 5 | IQ2_S roofline and compiler inspection | 0.5 day | enabling | identify a real limiter |
| 6 | IQ2_S reordered/ESIMD kernel iterations | 2–5 days | medium/high | ≥15% operator |
| 7 | Adaptive MTP `n=4↔6` controller | 1–2 days | low/medium | mixed workload wall time |
| 8 | Deep-context indexer-select fusion | 2–4 days | medium at depth | delta profile ≥5% ceiling |
| 9 | Model-specific expert-parallel A0 | 0.5–1 day | uncertain/high | adjusted ceiling ≥1.3× |
| 10 | One-layer expert-parallel prototype | multi-day | research | A0 passes |

## First sprint

A capable agent should spend its first three working sessions as follows:

**Session 1:** freeze B0–B4, rebase current upstream, validate the three relevant SYCL changes, and report whether
ESIMD FFN is free speed for GLM.

**Session 2:** produce the tensor/allocation ledger, search explicit placement, and calculate the exact bytes needed
to return layer 44 experts to VRAM.

**Session 3:** build one minimal mixed-quant candidate and one dense Q6_K operator inventory. Whichever clears its
go gate becomes the first implementation lane; the other remains a measured backlog item.

That order should expose a realistic next target quickly: roughly 27–30 tok/s prose without accepting Maya-S's
quality loss would be an excellent near-term result. Beyond that, further gains probably require a materially better
IQ2_S expert kernel or successful model-specific multi-GPU execution.

## Sources used

- [GLM-5.3 lab notes](https://github.com/Captain-Tripps/b70-lab/tree/main/glm-5.3)
- [Repository status table](https://github.com/Captain-Tripps/b70-lab/blob/main/STATUS.md)
- [Benchmark methodology](https://github.com/Captain-Tripps/b70-lab/blob/main/bench/README.md)
- [Rejected experiments](https://github.com/Captain-Tripps/b70-lab/blob/main/rejected-ideas/README.md)
- [October 17 rebase validation](https://github.com/Captain-Tripps/b70-lab/blob/main/llama.cpp-sycl/REBASE-2026-10-17.md)
- [Current upstream GLM graph](https://github.com/ggml-org/llama.cpp/blob/master/src/models/glm5-next.cpp)
