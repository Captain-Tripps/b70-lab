# GLM branch retention promotion — 2026-11-12

Promoted at the user's request after the [controlled canary](canary-results.md). A 45-second idle check preceded unloading the production GLM model. The candidate executable was copied into a dedicated runtime directory; its SHA-256 was verified identical to the tested binary. The promoted config matches the tested candidate except for the permanent executable location and normal production engine log path.

- Active config: `D:\maya-sycl\configs\glm-maya-sycl-128k.json`; SHA-256 `bd33b4f67769f5b6b0582149e39e8a09f09002ac6e5de0f907858fd9e83516f7`.
- Active executable: `D:\maya-sycl\rt-glm-branch-20261112\generate.exe`; SHA-256 `f89820fe92e49ffa6e563b538d5dc5aebe9b246e95d29d523f3e76f0ed0acea8`.
- Active layer split `14,25,36`, eight slots, 12 GiB RAM slot cap, and `STRATA_GLM_SLOT_KEEP_BRANCH=1`. Startup log confirmed these values.
- Untouched previous executable: `D:\maya-sycl\rt-live\generate.exe`. Exact previous config backup: `D:\maya-sycl\configs\glm-maya-sycl-128k.before-branch-promotion-20261112.json`; SHA-256 `d46603a071083d0ba2d4aeb7e6e60f1758116f153394e2bc2e4ae5709ac2087e`.

The promoted process was confirmed as PID 18184 at startup; a short health request returned `READY`. A synthetic A/B/A cache smoke test returned the same hash for A both times, with 15.09 s cold first-token latency and 0.30 s on the return. This is a smoke test, not a production latency guarantee. The pre-existing intermittent access violation remains unresolved.

## Rollback

First check proxy `/running` and GLM's `/upstream/glm-5.3-flash-maya-sycl/status`, and avoid interrupting active or queued requests. After a sustained quiet interval, unload only the GLM model via `POST /api/models/unload/glm-5.3-flash-maya-sycl`; confirm no model or GPU inference process remains. Verify that the active config still has the promotion hash above and the backup still has the original hash; do not overwrite an intervening edit. Copy the backup to the active config path, verify its hash, and start GLM through the existing proxy. Confirm its executable is `rt-live\generate.exe`, split is `13,24,35`, and a health request succeeds. No live executable needs to be replaced.
