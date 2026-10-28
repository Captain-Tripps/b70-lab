# Open items — updated 2026-10-28 09:30 (checkpoint)

> **2026-10-28 ~10:50 — all three P0s below are DONE; see `SESSION-14-RESULTS.md`.**
> Watchdog is commit-aware; the control showed the backend mirrors device allocations into resident
> host RAM about 1:1; 1017 benched at `-ncmoe 24`: warm prefill 7.0 tok/s, decode 0.93 tok/s
> (NVMe-bound). New P0: run the 16 GB Level Zero alloc+copy test on native Linux to find out whether
> the mirror is Windows-specific.

Ordered by value. `SESSION-13-CHECKPOINT.md` and `HANDOFF-SESSION-13.md` carry the detail.

-

## P0 — blocking, do first

| # | Item | Effort | Why it blocks |
|---|---|---|---|
| 1 | **Fix `ram-watchdog.ps1:32`** to read `AvailableBytes` instead of `FreePhysicalMemory` | 10 min | It reports `free=0.00` while `available=58.19`. Healthy mmap loads are killed. Keep the floor; fix the metric. |
| 2 | **Obtain one prefill/decode tok/s number** for 1017 | 15 min | Every downstream decision needs it. `bench-9100.py` is written and working; bench *inside* the health-poller (`box-run18.ps1` pattern). |
| 3 | **Run the small-model control** (Qwen3-Coder 17.28 GB, `-ngl 99 -lm auto`) comparing `priv` to device buffers | 10 min | Decides whether the host-RAM mirroring is the backend or the pack. This is the project fork. |

## P1 — after the fork is resolved

| # | Item | Notes |
|---|---|---|
| 4 | If backend mirrors VRAM: size the real requirement | ~160 GB RAM, or a `deepseek41` pack ≤ ~70 GB. State it as a hardware fact, not a tuning problem. |
| 5 | If pack-specific: try per-tensor `-ot` expert placement instead of `-ncmoe` | `-ncmoe` shifts whole layers and breaks `-sm layer` balance; `-ot` can be balanced per layer. |
| 6 | Re-derive `-ts` whenever `-c` or headroom changes | Use `box-solve2.py`. A `-ts` from another config overflowed a card and lost a run. |
| 7 | Decide `-lm auto` vs `-lm none` deliberately | `auto` = CPU experts file-backed/evictable (NVMe idea), +8 GB. `none` = anonymous, −8 GB, pinned. |

## P2 — hygiene

| # | Item | Notes |
|---|---|---|
| 8 | **Delete or fix `C:\b70-work\box-auto.ps1`** | It rewrites `auto-srv.bat` on every launch and silently reverted a corrected config twice. |
| 9 | Export the 4 llama.cpp patches as a commit/patch series into this repo | Currently only on the Windows build tree. The fused-ops probe fix looks like a general upstream multi-GPU bug (pp splits 166→13). |
| 10 | Pre-flight check for foreign workloads | `CommitUsed` must be ~23 GB, not ~150 GB. A foreign `llama-bench` held 129.66 GB for most of one session. |
| 11 | Investigate `LiveKernelEvent P1:141` (2,827 in 7 days) | Not TDRs, no correlation with the exits, but unexplained. See `PLAN.md`. |

-

## Settled — do not reopen

- **Patches are not the cause of the `exit -1`.** It is the RAM watchdog. Verified by control test
  and by the watchdog's own log (`Stop-Process -Force` → `TerminateProcess(h,-1)` → exit `-1`;
  MSVC `abort()` would be exit 3; no WER event was raised; no `exit(-1)` exists in the source).
- **Context checkpoints are not the cause.** Both docs that claimed this are corrected in place.
- **`0.85 tok/s` was never a prefill measurement** — 27 tokens of a starving process.
- **`-sm row` is unsupported** on this SYCL backend (`ggml-sycl.cpp:1419`, exit `0xC0000409`).
- **Engram is 0.20 GiB in this pack**, not 110 GB. It cannot be a capacity lever.
- **`-ngl 40` is correct** for VRAM capacity (119.4 GiB of buffers vs 130 GiB); the layer *split*
  must be byte-balanced with `-ts`.
- **`-ts` arithmetic from the old handoff is void.** It assumed a 2-GPU 48/52 boundary.
