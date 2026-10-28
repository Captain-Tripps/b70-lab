# The `exit -1` is the RAM watchdog, not a crash (2026-10-28)

**This corrects the central conclusion of `HANDOFF-SESSION-12.md` §3 and all of
`CHECKPOINT-FIX-NEGATIVE.md`.** The 1017 track is not blocked on an unhandled abort in the
deepseek41 SYCL path. Every `exit -1` recorded so far is the host-RAM watchdog calling
`TerminateProcess` on `llama-server.exe`.

The three local patches are not implicated. Do not bisect them.

-

## 1. How it was found

Source reading first, which ruled out the "abort" story before any run:

| Check | Result |
|---|---|
| `exit(-1)` anywhere in the tree | **none** — `src/`, `common/`, `tools/`, `ggml/` contain zero |
| `GGML_ABORT` behaviour | prints `file:line: msg` + backtrace to stderr, then `abort()` (`ggml.c:253-273`) |
| `abort()` on MSVC | exit code **3**, not -1 |
| Access violation | exit code `0xC0000005` (-1073741819), not -1 |
| WER Application Error event at 00:48 | **none** in the 00:35–01:05 window |
| WER LocalDumps | not configured (no dump either way — but no event at all is the tell) |

A process that dies with code **exactly -1**, prints nothing, raises no WER event, and has no
`exit(-1)` in its source was not aborted by its own code. It was terminated from outside.

-

## 2. The watchdog

`C:\llama-swap\ram-watchdog.ps1`, scheduled task `llama-ram-watchdog` (pid 3756), floor **6 GB**,
2 consecutive samples at 1 s, 30 s cooldown:

```powershell
$procs | ForEach-Object { Stop-Process -Id $_.Id -Force }
```

`Stop-Process -Force` → .NET `Process.Kill()` → `TerminateProcess(handle, -1)`.

**Verified on GPU-BOX by control test, not assumed:**

```
NET_KILL_EXITCODE=-1        # Start-Process -> $p.Kill() on a live ping.exe
```

Exit code `0xFFFFFFFF` renders as `-1`. That is the exact signature in the batch wrapper.

-

## 3. The kills, straight from the watchdog log

```
2026-10-28 00:48:05 KILLED 1 llama-server (avail=5.58 GB below 6 GB): pid=3120  priv=133.4GB ws=78.4GB
2026-10-28 00:54:44 KILLED 1 llama-server (avail=4.91 GB below 6 GB): pid=19612 priv=129.9GB ws=79.4GB
2026-10-28 01:22:33 KILLED 1 llama-server (avail=4.89 GB below 6 GB): pid=6532  priv=129.9GB ws=77.2GB
2026-10-28 06:48:07 KILLED 1 llama-server (avail=5.09 GB below 6 GB): pid=30952 priv=121.2GB ws=76.9GB
2026-10-28 06:48:37 KILLED 1 llama-server (avail=0.17 GB below 6 GB): pid=30952 priv=121.2GB ws=82.8GB
```

`pid 6532` at 01:22:33 is the `-ngl 40` run started at 01:19:15 — it was killed **207 s** after
start, having reached `offloaded 40/41 layers` and allocated all four model buffers. The
`exit -1` recorded at 01:23:08 is that kill.

Timeline for `srv-v41.bat`:

| Event | Time | Delta |
|---|---|---|
| `==== srv-v41 start ====` | 00:41:47 | T+0 |
| watchdog `KILLED` | 00:48:05 | **T+378 s** |
| `==== srv-v41 exit -1 ====` | 00:48:25 | T+398 s |

Timeline for `srv-nockpt.bat`:

| Event | Time | Delta |
|---|---|---|
| `==== srv-v41-nockpt start ====` | 00:51:17 | T+0 |
| last log line (`n_ctx_seq`) | internal 1:57 | — |
| watchdog `KILLED` | 00:54:44 | **T+207 s** |
| `==== exit -1 ====` | 00:55:20 | T+243 s |

Both processes were **alive at kill time**. The second did not "die at `llama_context`
construction" — it sat there for ~90 s after its last log line and was shot.

-

## 4. What this invalidates

| Claim | Source | Verdict |
|---|---|---|
| "Two silent `-1`s at different stages = unhandled abort" | HANDOFF §3 | **False.** Same external kill, twice. "Different stages" is just where each run was when RAM ran out. |
| "`srv-nockpt` never reached `model loaded`; died at `llama_context`" | CHECKPOINT-FIX-NEGATIVE §1 | **Misleading.** It reached `llama_context`, then stalled ~90 s. Disabling checkpoints did not make failure "earlier" causally. |
| "The checkpoint line is a symptom of the shutdown path" | CHECKPOINT-FIX-NEGATIVE §2 | **Wrong direction.** That line is 20 s *after* the kill — the last thing a dying process flushed. |
| "Bisect the three patches" | HANDOFF §4 | **Premature.** No evidence any patch misbehaves. |
| "Prefill = 0.85 tok/s" | PREFILL-MEASURED | **Not a prefill measurement.** 27 tokens in 31.75 s while being starved and then killed. It measures the thrash. |
| "Host RAM was the limit — only at first" | HANDOFF §5 | **Backwards.** Host RAM is the *current and only* limit. |

-

## 5. The load-mode matrix (new)

All four runs, same pack, same `-ngl 38` except where noted. Every one was killed by the watchdog.

| Run | `-lm` | Peak priv | Peak WS | Outcome |
|---|---|---|---|---|
| `srv-v41.bat` | `none` | 133.4 GB | 78.4 GB | killed at T+378 s |
| `srv-ngl40.bat` | `none`, `-ngl 40` | 129.9 GB | 77.2 GB | killed at T+207 s |
| `srv-lmauto.bat` | `auto` (mmap) | 121.2 GB | 85.6 GB | killed, took 2 attempts |
| `srv-dio.bat` | `dio` | 129.9 GB | 82.9 GB | killed |

Private commit is **≈ the model size in every mode** (~121–133 GB against a 128.74 GB pack).
Changing the load mode does not change the host cost. This is the finding that matters.

Measured memory curve during the `-lm auto` load (10 s cadence):

```
06:58:59  avail=78.92  ws=5.75
06:59:39  avail=50.69  ws=33.96
07:00:19  avail=13.92  ws=70.70
07:00:39  avail=0.56   ws=84.61
07:00:49  avail=0.53   ws=85.59
```

`AvailableBytes` and `StandbyCacheNormalPriorityBytes` were identical at every sample, and both
reached zero. **The watchdog is not a false positive** — the box genuinely has no usable memory
left at that point.

-

## 6. The real blocker, restated

| Fact | Value |
|---|---|
| 1017 pack on disk | 128.74 GB (4 shards) |
| Physical RAM | 95.9 GB |
| Commit limit | 151.02 GB (55.1 GB pagefile) |
| Device buffers (4 cards) | 119.4 GB — **fits** in 128 GB VRAM |
| Private commit at kill | 121–133 GB |
| Free RAM at kill | 0.2–5.6 GB |

The weights fit VRAM. What does not fit is a **host-side commitment equal to the model size**.
The `-ot`/`-ngl` arithmetic in the handoff was never the binding constraint; host commit is.

`ggml/src/ggml-sycl/common.cpp:95-96` states the intent directly:

> Use Level Zero `zeMemAllocDevice` to avoid `sycl::malloc_device` triggering DMA-buf/TTM system
> RAM staging in the xe kernel driver during multi-GPU inference.

`GGML_SYCL_SUPPORT_LEVEL_ZERO_API:BOOL=ON` in this build and `ggml-sycl.cpp:458` defaults
`GGML_SYCL_USE_LEVEL_ZERO_API` to 1 — so that mitigation is compiled in and nominally on, yet
host commit still tracks model size. Whether the remaining host cost is the loader's staging of
each tensor before the device copy, or xe/TTM staging underneath Level Zero, is **not yet
settled**. That is the one open question, and it decides whether 1017 can run here at all.

-

## 7. Next steps, in order

1. **Do not bisect the patches.** Nothing points at them.
2. **Settle the host-commit question** before any further tuning: run a small model with the same
   build and watch `PrivateMemorySize64`. If priv ≈ model size there too, the host staging is a
   property of this SYCL path and no flag fixes it.
3. **If it is staging:** the only paths are a pack small enough that 2× its size fits in 96 GB
   (i.e. ≤ ~45 GB, well under the current 128.74 GB), or a box with more RAM.
4. **If it is xe/TTM staging:** `GGML_SYCL_USE_LEVEL_ZERO_API=1` is already the default; the
   remaining lever would be the driver, not llama.cpp.
5. **Always check `ram-watchdog.log` first** on any future 1017 death. It timestamps, pids, and
   sizes every kill.

-

## 8. Operational lessons

15. **Exit code `-1` is not `abort()`.** MSVC `abort()` → 3. `TerminateProcess(h, -1)` → -1.
16. **A missing WER event is evidence.** Silent death + no Application Error = nothing faulted.
    Look for an external killer before a bug.
17. **Check for watchdogs before diagnosing any "silent" process death.** GPU-BOX has one that logs
    pid, private bytes and free RAM on every kill. One grep answered what a whole session of flag
    permutation could not.
18. **`Stop-Process -Force` reports -1.** Verified by control test, not assumed.
19. **Read the log's internal clock against the file's wall clock.** The internal timer stopped at
    `3:18` while the wrapper stamped `6:38` — that 3-minute gap *is* the death notice.
20. **A silent `-1` where the source has no `exit(-1)` is externally imposed.** Absence of a
    matching call site is a positive finding.
21. **A process can outlive `Stop-Process -Force` and WMI `Terminate` (rc=2) while unwinding.**
    It was stuck releasing ~85 GB of mapped pages; it took ~3 minutes and a second kill to die.
    Do not conclude "unkillable" — check WS trend and wait.
22. **`Ram-watchdog` cannot kill an unwinding process either.** Its `Stop-Process` calls failed
    the same way, twice, 30 s apart. The floor protects against the ramp, not against teardown.
