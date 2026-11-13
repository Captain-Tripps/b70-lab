# GLM slot checkpoint resume promotion — 2026-11-13

Promoted at Jon's request after the [screen](README.md), 13:46 CST, without a soak. GLM was already unloaded in
llama-swap. The llama-swap config was not edited. The candidate executable was copied into its own runtime directory
and its SHA-256 checked against the screened binary. The live config changed in two fields only: the executable
path and `STRATA_GLM_SLOT_CKPT_RESUME=1`. The [slot carry](../2026-11-13-slot-carry-ckpt/promotion.md) it builds on
stays on.

- Active config: `D:\maya-sycl\configs\glm-maya-sycl-128k.json`; SHA-256
  `357fc3eb07f155543eca5d92ae6921514cb87f8f327e878d9f9fea36c4a2e6fe`. Copy:
  `glm-maya-sycl-128k.ckptresume-promotion-20261113.json`.
- Active executable: `D:\maya-sycl\rt-glm-ckptresume-20261113\generate.exe`; SHA-256
  `16ad8a269af9004c2001b815edbf816919474532d0c2f96bdea61fa499579d21`.
- Previous config (the slot carry), exact backup:
  `D:\maya-sycl\configs\glm-maya-sycl-128k.before-ckptresume-promotion-20261113.json`; SHA-256
  `6508e3626e6a09efb0ff7cf152a30002f351c7b77b0003dd4fc3db1cc4f74b4f`.
- Previous executable, untouched: `D:\maya-sycl\rt-glm-slotcarry-20261113\generate.exe`; SHA-256
  `76295f72901b9d21dca17bee226c4456a9cb7f4c9adf4f1acc4f70bc904d5b8d`.

## Smoke test through the proxy

GLM started on the first request (51.1 s to `READY`) and the process was confirmed running
`rt-glm-ckptresume-20261113\generate.exe`. Same conversations as the carry's smoke test
([`smoke_live.py`](smoke_live.py)): A at 25.7k tokens, B at 50, same system prompt.

| Request | First token | Carry smoke, 12:49 |
|---|---:|---:|
| A, first read | 24.6 s | 24.9 s |
| B | 1.17 s | 1.16 s |
| A, last message edited straight after the switch | 0.645 s | 23.2 s (full re-read) |
| A, unchanged return to that edit after another switch | 0.168 s | |
| A, last message edited after that return | 0.765 s | 0.762 s |

- The engine logged `took back a 25712-token conversation from RAM for its checkpoint at 25700 (0.1 s); 13 new
  tokens to read` for the straight edit.
- The unchanged return gave the same answer as the straight edit. The straight edit's answer starts the same as the
  carry smoke's answer to that prompt after a full re-read; only the first 80 characters were kept there.

## Rollback

To the slot carry: first check proxy `/running` and avoid interrupting active or queued requests. After a quiet
interval, unload only GLM via `POST /api/models/unload/glm-5.3-flash-maya-sycl` and confirm no `generate.exe`
remains. Verify the active config still has the promotion hash above and the backup still has its hash; do not
overwrite an intervening edit. Copy the backup over the active config, verify its hash, start GLM through the proxy
and confirm the process runs `rt-glm-slotcarry-20261113\generate.exe`. Back to the 2026-11-12 build: the
[carry's rollback](../2026-11-13-slot-carry-ckpt/promotion.md#rollback) from there.
