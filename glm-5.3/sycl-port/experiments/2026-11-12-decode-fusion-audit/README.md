# Decode fusion audit — 2026-11-12

## Selection

The older llama.cpp [roadmap](../../../ROADMAP.md) does not rank the current Maya SYCL engine. Against the current [Maya leads](../../LEADS-2026-11-09.md), targeted decode fusion / resident routing is a useful next screen: the prior cache-retention follow-up gain has been promoted; sub-batch 768 failed a numerical check; IQ2_S reorder and 16/64-row tiles were slower; 48-row tiles did not establish a win. XMX indexer/MLA at depth and the full prompt-preparation backport remain unmeasured alternatives. This is an investigation-value choice, not a proven speedup forecast.

Source audit of the promoted candidate tree shows `fast_moe_experts` already skips both `moe_wait` and `moe_fetch` when `F->all_resident` is true. `fast_layers` submits six independent recurrent-mixer projection jobs via `gf::mv`; the common single-column path groups specialized kernels by quantization type and sends other jobs through a generic kernel. `STRATA_GLM_MV_GENERIC=1` disables the type-specialized one-column path and is a cheap existing test of combining those jobs; it does not imply every `mv` invocation or all multi-column work becomes one kernel. The promoted executable did not change.

## Decode profile

Zeus, four B70s, promoted executable SHA-256 `f89820fe92e49ffa6e563b538d5dc5aebe9b246e95d29d523f3e76f0ed0acea8`, production split `14,25,36`, context 131072, expert cache auto, prefill 768, CPU lane off, resident skip on, and the promoted RAM-slot flags. Fixed five-token `prompt1.txt` SHA-256 `741e233cd0e2a846c1342a0e8514bc3419513129eda34408fdd65ae5b6a0153c7b`; 256 greedy generated tokens, speculation enabled. Proxy was unloaded only after a 45-second quiet check; each experiment process was isolated, and the runner stopped its own recorded process if the proxy started another model, free RAM fell below 16 GiB, or the run timed out. The first preliminary off run completed its output but the runner did not retain its exit code; it is excluded. The runner was fixed before the four measured arms.

| Arm | Profiler | Decode | Accepted/proposed draft tokens |
| --- | --- | ---: | ---: |
| off1b | off | 47.80 tok/s | 216/254 |
| on1 | `STRATA_GLM_PROF=8` | 43.16 tok/s | 216/254 |
| on2 | same | 43.25 tok/s | 216/254 |
| off2 | off | 47.24 tok/s | 216/254 |

All four arms produced the same 256-token sequence (newline-joined `T ` lines SHA-256 `6ec808d075f2df5ee0d9e90eec1bbaa88e79b05652d7e46160d09b990425277e`). The profiling arms report on the two instrumented split model streams, labeled CUDA0 and CUDA2; values are not whole-model times and should not be added across streams. On CUDA0 the repeat `kda_proj_mv` was 2.354/2.357 ms per profiled token, `moe_gate_up` 1.337/1.336, `moe_down` 1.070/1.070, `router_shexp_mv` 0.542/0.541, and `moe_route` 0.243/0.243. CUDA2: `kda_proj_mv` 1.690/1.689, `moe_gate_up` 1.337/1.337, `moe_down` 1.183/1.183, `router_shexp_mv` 0.538/0.537, `moe_route` 0.242/0.242. The marker implementation uses SYCL event timing and barriers; profiling reduced model decode by roughly 9%, and stream intervals can include waits and gaps. This identifies leads, not a precise additive speedup ceiling.

## Existing generic mixed-projection path

The same process setup ran A/B/B/A without profiling, using `STRATA_GLM_MV_GENERIC=1` for B:

| Arm | Decode | Accepted/proposed |
| --- | ---: | ---: |
| A1 typed default | 43.39 tok/s | 216/254 |
| B1 generic | 37.71 tok/s | 216/254 |
| B2 generic | 47.79 tok/s | 216/254 |
| A2 typed default | 47.92 tok/s | 216/254 |

All four 256-token sequences had the same hash as the profile arms. This small, variable screen **does not establish a speedup**: the second generic run was essentially tied with the closing control, while the first pair was slower. Clock/temperature telemetry was not collected and start-order effects are not isolated; do not attribute the differences to a specific cause or treat these samples as a statistical comparison. The generic flag was not promoted. A further implementation would need exact operator correctness and enough same-session varied-prompt measurements to pass the handoff's 3% end-to-end gate.

The promoted config and executable were not modified. After both batches the live proxy was restarted with the promoted config and a `READY` health response. Raw diagnostic logs and the executed script remain on Zeus at `D:\maya-sycl\experiments\codex-decode-fusion-audit-20261112`; [run.ps1](run.ps1) is the runner. The prior unrelated Intel-driver access violation remains unresolved.

## Actual launch audit

An opt-in, bounded host trace in an isolated copy of the promoted source counted the real single-column dispatches for six-job calls. The first 64 sampled calls all had the same signature: three Q6_K (`type=14`) 4096→8192 projections and three BF16 (`type=30`) projections, 4096→128, 4096→128, and 4096→64. The normal path took **one typed Q6_K launch and one generic BF16 launch** per sampled call. With `STRATA_GLM_MV_GENERIC=1` it took **one generic launch**. This is a bounded early sample, not a census across all workloads or multi-column paths. See [instrument_mv.py](instrument_mv.py); the instrumented executable SHA-256 was `9710d81b305fd5098b2dce661645ff4679fa42afb821fc1221fcefd5d13aef25`.

The tracing-disabled, tracing-enabled and generic-tracing runs generated 256 identical tokens (same hash as above) and took 48.17, 47.36 and 47.75 tok/s respectively. These single samples check behavior and tracing viability, not a statistical overhead or performance claim.

## Exact-shape mixed-kernel prototype

An isolated, off-by-default `MAYA_MV_Q6_BF16_FUSED` prototype dispatches one kernel only for the six exact shapes above, retaining the specialized Q6_K dot product and BF16 dot product; all other shapes and multi-column work follow the original path. The single fused kernel uses a per-job type branch. The source modification is reproducible with [prepare_fused.py](prepare_fused.py); it is experimental and not part of the live binary. Its source SHA-256 was `581dc3b6e855f367d643e441e50eaa95560e4ae732c298d87972fba1fb06b039`, binary SHA-256 `a33f023ca298a628807bfc74ec715760918d175907c50a3bb8ff69ddbd6eca44`. Runtime logs confirmed the fused dispatch was active in both candidate arms.

| Arm | Decode | Prompt ms/token | Accepted/proposed |
| --- | ---: | ---: | ---: |
| A1 fused off | 34.93 tok/s | 3763.5 | 216/254 |
| B1 fused on | 14.89 tok/s | 261.6 | 216/254 |
| B2 fused on | 14.89 tok/s | 120.5 | 216/254 |
| A2 fused off | 48.04 tok/s | 60.8 | 216/254 |

All 256 generated tokens matched across the four arms (same hash as above). A1 exhibited a much higher prompt time, consistent with a cold-start effect but without independently measured JIT timing. Even after the B repeat, its decode was about 69% slower than the closing control. This is a decisive rejection for this prototype on this short workload, not a finding about every possible fusion. The cause of the slowdown has not been profiled; register pressure, scheduling, compilation, or another mechanism are hypotheses, not established causes. No longer quality, deep-context, or multi-user claims follow from this one token-parity check.

All candidate runs used separate processes following a proxy-idle guard, with the production promoted binary/config untouched. The promoted service was restarted and returned `READY` afterward. Raw logs remain in the Zeus experiment directory. The existing driver-crash issue remains open.

## Fused regression diagnosis

The same prototype and fixed input were profiled in A/B/B/A order with `STRATA_GLM_PROF=8`. The profiling markers affect performance and include queue timing/gaps, so these are diagnostic comparisons, not clean model throughput measurements. All arms generated the same 256-token hash and accepted 216/254 drafts.

| Arm | Profiled decode | CUDA0 `kda_proj_mv` | CUDA2 `kda_proj_mv` |
| --- | ---: | ---: | ---: |
| A1 fused off | 43.16 tok/s | 2.358 ms/profiled token | 1.689 ms/profiled token |
| B1 fused on | 14.26 tok/s | 25.253 ms/profiled token | 18.350 ms/profiled token |
| B2 fused on | 14.29 tok/s | 25.239 ms/profiled token | 18.365 ms/profiled token |
| A2 fused off | 43.32 tok/s | 2.353 ms/profiled token | 1.690 ms/profiled token |

The regression is localized to the projection interval, which increased roughly tenfold on both measured split streams. The intervals are per-stream and not additive model-wall times.

Intel VTune 2026.0 GPU-hotspots characterization then collected one off and one on run, 128 generated tokens each, all four B70s. Both collected successfully and generated the same token hash `f398f5cb9783baf8d7e4cf7342afe64d40bda6475a433f35a3728e2c390058b7`; both accepted 102/126 drafts. VTune off/on model decode was 41.01/14.24 tok/s, including collection overhead. The instrumented fused dispatch has global/local work sizes 796672/256: `(3*8192 + 128 + 128 + 64) / 8 * 256`. Its matched VTune task reported 4,963 instances averaging **2.301 ms**. The original Q6 task of 786432/256 reported 5,434 instances averaging **0.201 ms**; the original BF16 task of 10240/256 reported 4,963 instances averaging **0.010 ms**. The Q6 task count includes 471 additional instances, so its average is not strictly limited to the six-job calls. These are observed task averages under VTune, not independent precision benchmarks.

VTune reported **0 bytes of spill memory** for the three identified task rows. That does not establish the exact register count or rule out every occupancy/resource issue, but the captured spill field does not support claiming a spill caused the regression. The slower fused task's 78.3% occupancy figure in VTune's summary is not directly comparable to overall occupancy; collection spans model load and unrelated kernels. Determine compiler code generation or memory behavior before attributing a precise cause. Raw VTune results and kernel reports remain on Zeus in the experiment directory; [vtune.ps1](vtune.ps1) records the guarded invocation. VTune could not locate private debug information for the Intel driver, which limits attribution.

After each batch the promoted GLM service was restored and returned `READY`. No live executable or config changed. The fusion prototype remains rejected; the evidence points to its expensive fused projection kernel rather than overhead elsewhere, while the underlying code-generation reason remains open.

## Next step

The generic one-launch alternative did not establish a speedup, and the narrow specialized attempt was substantially slower. Per the handoff's two-attempt stop rule, do not continue this fusion lane without new measured evidence. The still-unmeasured depth-specific MLA/indexer path is a separate candidate; first establish its model-wall-time ceiling before investing in a kernel rewrite.
