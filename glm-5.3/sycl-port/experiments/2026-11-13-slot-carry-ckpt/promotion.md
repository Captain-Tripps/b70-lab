# GLM slot checkpoint carry promotion — 2026-11-13

Promoted at Jon's request after the [screen and soaks](README.md), 12:46 CST. llama-swap had nothing loaded, so no
unload was needed. The llama-swap config was not edited. The candidate executable was copied into its own runtime
directory and its SHA-256 checked against the tested binary. The live config changed in two fields only: the
executable path and `STRATA_GLM_SLOT_CARRY_CKPT=1`.

- Active config: `D:\maya-sycl\configs\glm-maya-sycl-128k.json`; SHA-256
  `6508e3626e6a09efb0ff7cf152a30002f351c7b77b0003dd4fc3db1cc4f74b4f`. Copy:
  `glm-maya-sycl-128k.slotcarry-promotion-20261113.json`.
- Active executable: `D:\maya-sycl\rt-glm-slotcarry-20261113\generate.exe`; SHA-256
  `76295f72901b9d21dca17bee226c4456a9cb7f4c9adf4f1acc4f70bc904d5b8d`.
- Previous config, exact backup: `D:\maya-sycl\configs\glm-maya-sycl-128k.before-slotcarry-promotion-20261113.json`;
  SHA-256 `bd33b4f67769f5b6b0582149e39e8a09f09002ac6e5de0f907858fd9e83516f7`.
- Previous executable, untouched: `D:\maya-sycl\rt-glm-branch-20261112\generate.exe`; SHA-256
  `f89820fe92e49ffa6e563b538d5dc5aebe9b246e95d29d523f3e76f0ed0acea8`.

## Smoke test through the proxy

GLM started on the first request (51.5 s to `READY`). The process was confirmed running
`rt-glm-slotcarry-20261113\generate.exe`. Smoke script: [`smoke_live.py`](smoke_live.py), a 25.7k conversation A and
a 50-token conversation B with the same system prompt.

| Request | First token | |
|---|---:|---|
| A, first read | 24.9 s | |
| B | 1.16 s | A parked in a RAM slot with its checkpoint |
| A, last message edited straight after the switch | 23.2 s | full re-read: no slot take-back, see below |
| A, unchanged return after another switch | 0.146 s | same answer as the first read |
| A, last message edited after that return | 0.762 s | engine log: "gave back a checkpoint at 25700" |

## What the carry does not cover

A RAM slot is taken back only when its whole conversation is a prefix of the new prompt (`slot_take`). An edited last
message is not, so an edit sent straight after a switch reads the conversation again, on this build and the
previous one. The carry helps once something returns to the conversation unchanged first: a retry, an agent's next
turn, or the client resending it. The screen and both soaks always had that return before the edits, so they never
showed this case.

## Rollback

First check proxy `/running` and avoid interrupting active or queued requests. After a quiet interval, unload only
GLM via `POST /api/models/unload/glm-5.3-flash-maya-sycl` and confirm no `generate.exe` remains. Verify the active
config still has the promotion hash above and the backup still has its hash; do not overwrite an intervening edit.
Copy the backup over the active config, verify its hash, and start GLM through the proxy. Confirm the process runs
`rt-glm-branch-20261112\generate.exe` and a health request succeeds. No executable needs replacing.
