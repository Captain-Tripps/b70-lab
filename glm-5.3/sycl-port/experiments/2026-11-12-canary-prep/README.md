# Zeus GLM canary preparation — 2026-11-12

**Prepared only. No canary has been started, no live configuration has been changed, and no workload has been stopped as part of this preparation.** The user will decide when to start it.

On Zeus, an exact byte copy of the current production GLM config and a separate candidate are staged in `D:\maya-sycl\experiments\codex-glm-canary-prep-20261112`. The [redacted baseline](baseline-live-config.json), [redacted candidate](candidate-config.json), [configuration diff](candidate-changes.diff), and [hash manifest](manifest.json) make the proposed change reviewable. The manifest hashes refer to the **unredacted on-machine files**, so the redacted copies in this repository will have different hashes.

The candidate changes only the executable, layer split `13,24,35` → `14,25,36`, log path, and three opt-in settings: `STRATA_GLM_SLOT_RAM_GB=12`, `STRATA_GLM_SLOTS=8`, `STRATA_GLM_SLOT_KEEP_BRANCH=1`. The staged candidate was compared structurally with the successful 30-minute experimental configuration; only its log location and the slot-directory field ignored in RAM mode differ. Executable hashes were checked against the previously tested experimental binary and the current live binary. Static configuration equivalence is not a fresh runtime test.

The staged [client-only workload](canary-client.py) is also on Zeus in that preparation directory. Its syntax and streaming parser were checked **offline** with synthetic events; it has not sent a request or been integration-tested against the live proxy. It does not start or stop a server, switch config, monitor Windows driver events continuously, or perform rollback. An operator must supervise the test and rollback separately. Before submitting each request it checks the live config hash, model readiness, host available RAM, and the original engine PID, executable and split; it waits while the service reports active or queued work. These checks cannot prevent every race with another client.

## Launch gate — do not perform until requested

1. Recheck that the live config and both executable hashes match [manifest.json](manifest.json); re-stage and review if any changed. Verify the candidate binary and its runtime libraries are still present.
2. Check proxy `/running`, active/queued requests, Windows `generate.exe` / `llama-server.exe` processes, all four GPU memory counters, and host available memory. Do not unload or interrupt another user's workload. A quiet interval and no competing GPU model are required; a brief gap between requests is not enough.
3. Preserve the exact current proxy state and config bytes. Make the candidate available to the existing GLM proxy only when the requested test starts, retaining the existing model name and port. Start the baseline or candidate through the existing proxy controls; do not overwrite the frozen live executable. Recheck the actual process executable, split, flags and readiness after startup.
4. Protect rollback: restore the saved original config and executable selection after the test or an abort. Before replacing either config, verify its current hash is still the one the test placed there; never overwrite an unrelated intervening edit. Drain the canary request first, and don't stop an unrelated model that appeared in the meantime. If the runner or controller fails, inspect service state and restore the original config before attempting any further start.

## Planned 1–2 hour test

- **Baseline, 5–10 minutes:** with the original binary/config, record a controlled subset of the same fixed-input book-style conversations, branch edits, and tool/vision requests used for the candidate. Capture first-token and end-to-end times, output/tool-call hashes, prompt and completion counts, and memory. Include the long-context branch-return trigger; allow about 103 seconds for its first read and its known cache miss.
- **Candidate, 45–90 minutes:** exercise separate conversations, repeated edited branches and returns, context truncation, synthetic tool calls and responses, same-text/different-image requests, cancellation/retry, and enough competing states to reach the eight-slot limit. The prepared client covers long and short branches, a synthetic tool round trip, two image fixtures, truncation and cancellation; it does **not** independently establish eight-slot fairness or exercise every 32k case, so supplement it with the previously validated [broader workload](../2026-11-12-branch-broad/) as needed. It targets the existing proxy and must not start a second full model alongside it. Record hashes and timings rather than private prompt contents in repo artifacts.
- **Monitoring:** sample available host RAM, GPU memory, process status, request errors, slot counts/evictions and Windows application/driver events; retain startup and shutdown timestamps. The 12 GiB slot cap is not a hard peak-memory limit: a snapshot is allocated before eviction. Treat `PrivatePageCount` as committed-byte accounting, not resident RAM. Allow for sampling gaps and startup cost.
- **Abort and roll back:** engine/driver crash or access violation; non-finite output; invalid or cross-conversation/image/tool output; an unexplained deterministic comparison mismatch; sustained service errors or unacceptable latency; available host RAM below 16 GiB; or inability to verify the intended runtime/config. Do not treat a 103-second cold 115k prefill as a hang. Stop accepting new test requests, drain safely, then restore the original config and service. Compare the restored config hash and process executable with the manifest.
- **Review, 5–10 minutes:** compare repeated like-for-like request latencies and outputs, cache-hit behavior and eviction fairness, memory minima and failures. A single clean run does not prove the periodic Intel driver crash is fixed or establish broad model quality. Keep the candidate experimental unless the user chooses a further rollout.

The isolated [8k/115k A/B and 30-minute soak](../2026-11-12-slot-branches/) and [tool/image/eviction tests](../2026-11-12-branch-broad/) are the existing reference, not a substitute for this canary. The [driver diagnosis](../2026-11-11-trim-crash/) remains open.

## Prepared client invocation

Do not run this until the test is requested and the launch gate above is satisfied. Run it on Zeus using Windows Python; use the production config's hash for the baseline and the staged candidate config's hash only after the intended config has been switched into the live config path. Use a new output filename for each arm. The client must be able to read the existing fixture and logo files, and refuses to overwrite an output file.

```powershell
$prep = 'D:\maya-sycl\experiments\codex-glm-canary-prep-20261112'
$manifest = Get-Content "$prep\manifest.json" -Raw | ConvertFrom-Json
# Select production_config_sha256 for baseline, candidate_config_sha256 for the candidate.
$expected = $manifest.production_config_sha256
& 'D:\AI\Training\zeus-lora\.venv\Scripts\python.exe' "$prep\canary-client.py" `
  --proxy 'http://100.89.126.50:8080' `
  --config 'D:\maya-sycl\configs\glm-maya-sycl-128k.json' `
  --expected-config-sha256 $expected `
  --fixture 'D:\maya-sycl\long_body.txt' `
  --media-dir 'D:\maya-sycl\maya\third_party\llama.cpp\media' `
  --output "$prep\baseline-requests.jsonl" --minutes 10
```

For the candidate, select `$manifest.candidate_config_sha256`, a distinct output filename, and the agreed duration (for example 60 minutes). The engine PID check detects a restart **between** test requests; host free RAM is sampled at request boundaries, not continuously during a long prefill. Monitor GPU memory, Windows events, service health and live users independently throughout; a controller failure requires manual inspection and rollback. The time limit is checked between complete cycles, so a long in-progress cycle may run past it.
