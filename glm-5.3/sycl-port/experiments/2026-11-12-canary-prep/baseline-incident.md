# Baseline canary aborted — 2026-11-12

The production baseline started after 45 seconds with no active or queued requests, with only the expected production `generate.exe` observed and the production config and executable hashes matching the manifest. The candidate was never started, and the live configuration was not changed.

The cold 115,123-token prime took 117.97 seconds to first token. Three edited branches took 2.49, 4.06 and 3.47 seconds; a 7,690-token switch took 10.90 seconds; the return to the long branch took 2.65 seconds; and the append took 0.95 seconds. The return therefore did not reproduce the previously observed approximately 102-second cache-miss case. These are single observations, not a candidate comparison.

During the subsequent 31,450-token medium-context switch, after approximately 9,984 tokens, the production engine exited with Windows status 3221225477 (`0xc0000005`, access violation). The client received a streaming error and stopped. The server's generic out-of-memory suggestion is not a diagnosis: the monitor's minimum sampled available physical RAM was 74.4 GiB. No application crash event was captured during the monitor's polling interval. No cause, including the previously observed driver failure, has been established.

After the abort the proxy still reported the GLM wrapper as ready and idle, but no `generate.exe` process was observed. The wrapper log says the next request starts the engine again; proxy readiness alone is not proof of a running engine. The config hash still matched the original. No further inference request was sent to force a restart.

The baseline request and monitor JSONL files and full engine log remain on Zeus under `D:\maya-sycl\experiments\codex-glm-canary-prep-20261112` and `D:\maya-sycl\configs\glm-maya-sycl-128k-engine.log`, respectively. The candidate is not cleared for promotion. Investigate the production crash and rerun a complete, representative baseline before resuming the A/B; the monitor is observational and does not automatically stop or roll back a test.
