# Controlled production-baseline and candidate canary — 2026-11-12

The first production baseline stopped on an access violation; see [the incident](baseline-incident.md). No fresh dump identified its faulting module. The production engine restarted and passed a short health check. A repeated baseline completed four cycles and 35 requests, including two successful medium-context switches. The original failure is therefore intermittent in this sequence, not a proven deterministic prompt failure.

After 45 seconds of idle proxy traffic, the candidate was started with the staged binary, split `14,25,36`, eight RAM slots, 12 GiB cap, and branch retention enabled. Startup logs and process command line confirmed those settings. The 60-minute client completed **155 cycles and 1,137 requests**: 31 intentionally cancelled and **1,106 completed requests compared with baseline, all matching** by canonical output hash, including text, synthetic tool arguments, and two image fixtures. This is a repeated synthetic workload, not 1,106 independent quality tests or a simultaneous multi-user test.

| Request, time to first token | Baseline retry | Candidate |
| --- | --- | --- |
| Cold 115k prime | 102.55 s, one | 104.74 s, one |
| 115k branch edit 3 | 2.31, 3.58, 103.55, 103.63 s | median 1.11 s, range 0.88–1.35 s, n=155 |
| 115k long return after short switch | median 2.42 s, n=4 | median 0.47 s, n=155 |
| 31k switch | 30.05, 30.23 s | first 29.50 s; median 0.88 s across 52, including first |
| 115k return after images | 101.45 s, one | median 0.38 s, range 0.33–0.44 s, n=13 |

The post-image improvement is a comparison of one baseline observation with 13 candidate observations; the alternate split, candidate build, and RAM/branch settings were changed together, so this particular production comparison does not isolate their individual effects. Prior same-build off/on experiments isolate branch retention more narrowly. Cold prefill was not faster in this measurement, and no general tokens-per-second gain should be inferred.

The minimum sampled available host RAM was **71.21 GiB** in the candidate monitoring window. The client retained one engine PID and completed without mismatch or reported engine failure. The monitor recorded one alert **after the client completed**, when the candidate model was intentionally unloaded for rollback; there were no alerts during the workload. A monitor sample is not a peak-memory guarantee, and the event check is not proof against all driver failures. Aggregate [baseline](baseline-summary.json) and [candidate](candidate-summary.json) summaries include that post-test alert. Full JSONL and engine logs remain on Zeus in the experiment directory.

Following the canary, the candidate was unloaded, the exact original production config was restored and hash-verified, and a short request returned `READY`. The restored engine process was `D:\maya-sycl\rt-live\generate.exe` with split `13,24,35`; no canary process remained. The candidate was [subsequently promoted](promotion.md) at the user's request. The comparison does not resolve the intermittent production access violation or establish long-term stability.
