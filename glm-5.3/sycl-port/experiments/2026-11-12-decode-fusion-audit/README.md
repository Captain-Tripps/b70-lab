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

## Next step

Instrument actual `gf::mv` job types and launch counts at the recurrent-mixer call in a separate, gated build, using the already-promoted runtime as control. This can establish whether the expensive stage is actually paying multiple launches and identify the exact quantization combinations; preserve the existing multi-column and fallback behavior. Only pursue a narrow mixed-type fusion if exact-shape profiling gives a plausible end-to-end ceiling, then test arithmetic parity and full-model A/B/B/A. No production setting change is justified by this screen.
