# Handoff — Session 13: 1017 loads and serves, benchmark still outstanding

**Read in this order:**

1. `SESSION-13-CHECKPOINT.md` — the state, the measured tensor inventory, the corrected history
2. `WATCHDOG-KILL-FINDING.md` — why every `exit -1` was the RAM watchdog, not a crash
3. `CONTENTION-CORRECTION.md` — why early-session numbers are untrustworthy
4. `HANDOFF-SESSION-12.md` — read only for background; its §3/§4 are marked SUPERSEDED

Branch `work/strata-v41-agent-runner`, remote `Captain-Tripps/b70-lab`.

-

## 1. The headline

1017 **loads and serves** now: `model loaded`, `listening`, `health 200`. That is new. It has never
completed an inference request, and **there is still no prefill or decode token rate for this pack**.

**Ten operational lessons from last session are still valid** (see `HANDOFF-SESSION-12.md` §8).
Four of them are load-bearing below.

-

## 2. Do these first, in this order

### 2.1 Fix the watchdog metric (10 minutes, unblocks everything)

`C:\llama-swap\ram-watchdog.ps1` line 32:

```powershell
function Get-AvailGB {
    try { (Get-CimInstance Win32_OperatingSystem).FreePhysicalMemory / 1MB } catch { [double]::NaN }
}
```

`FreePhysicalMemory` **excludes standby/reclaimable pages**. During a load the box showed
`free=0.00` while `available=58.19` — 58 GB usable, reported as zero. Healthy mmap loads are being
killed by this.

Change it to true available:

```powershell
function Get-AvailGB {
    try {
        $m = Get-CimInstance Win32_PerfRawData_PerfOS_Memory
        $m.AvailableBytes / 1GB
    } catch { [double]::NaN }
}
```

Keep the 6 GB floor; the metric is wrong, not the threshold. **Verify** with
`Get-Content C:\llama-swap\ram-watchdog.log -Tail` then a load.

### 2.2 Get the benchmark (highest value, ~15 minutes)

The benchmark script is already on GPU-BOX and already works — it just never got a live server:

```
C:\b70-work\bench-9100.py        # POSTs to http://127.0.0.1:9100
```

It sends a 1-token request then a ~160-token prompt and prints `prompt_per_second`,
`predicted_per_second`, `finish_reason`, and the content. Run it the moment `/health` returns 200.

The trick that matters: **bench inside the same script that polls health.** An external poller with
a 30 s gap missed the window twice. `box-run18.ps1` does this correctly — copy its structure.

### 2.3 Run the discriminating test (§3 below)

Once you have a number, or if load keeps dying, this single experiment decides the project's shape.

-

## 3. The one question that decides everything

Host RAM peaks at **~85.7 GB regardless of how many experts sit on CPU**:

| Config | Experts on CPU | GPU buffers | Peak WS |
|---|---:|---:|---:|
| `-ncmoe 5` | 13.8 GiB | 114.5 GiB | 86.2 GB |
| `-ncmoe 12` | 34.4 GiB | 93.6 GiB | 85.8 GB |
| `-ncmoe 18` | 52.2 GiB | ~76 GiB | 85.7 GB |

**Moving 52 GiB off the GPUs did not reduce host RAM at all.** So host RAM is not tracking CPU
weights — it tracks the GPU allocation, near 1:1. This is consistent with
`priv ≈ model_size − CPU_Mapped` in all three runs.

`ggml/src/ggml-sycl/common.cpp:95-96` claims the Level Zero path exists to avoid
"DMABUF/TTM system RAM staging in the xe kernel driver". It is compiled in
(`GGML_SYCL_SUPPORT_LEVEL_ZERO_API=ON`, runtime default 1) and the staging still appears to happen.

### The test

Load a small model on the **same build** and compare private commit to device buffers:

```
C:\Python314\python.exe  (available)
D:\AI\LLM\Models\Qwen3-Coder-30B-A3B-Q4_K_M.gguf   17.28 GB, known good, serves
```

Config: `-ngl 99 -lm auto -c 2048`, port 9080. Watch `PrivateMemorySize64` and `WorkingSet64` at
steady state.

| Result | Meaning | Consequence |
|---|---|---|
| `priv ≈ 17 GB`, `ws ≈ 18 GB` | **Backend mirrors device allocations.** | No llama.cpp flag fixes it. 1017 cannot run in 96 GB. Route changes: smaller pack (≤70 GB with `deepseek41`) or more RAM. |
| `priv` small, `ws` moderate | Pack/loader-specific. | Keep digging — `-ot` per-tensor control becomes worthwhile. |

**This is the fork in the road. Run it before any further tuning.**

-

## 4. What works — copy these configs

### 4.1 The config that reached health 200

```
C:\b70-work\opt5.bat
  -ngl 40 -ncmoe 5 -ts 35,22.5,22.5,20 -sm layer -lm none -c 2048 -t 12 --no-warmup
  -> model loaded, listening, health 200 on port 9094
  -> died on the first inference request at WS 85.4 GB
```

### 4.2 Why the flags are what they are

- **`-ngl 40`, not 38.** With `-ngl 40` all 40 layers are on GPU; the pack needs 119.4 GiB of device
  buffers and there is 130 GiB. It is the *layer split* that must be balanced — see `-ts`.
- **`-ts` must be byte-derived, never guessed.** `-ts 35,22.5,22.5,20` with `-ncmoe 5` gave
  31,568 / 29,790 / 30,210 / 25,327 MiB — all under 32,558. `-ts 32.5,...` overflowed card0
  (34,266 MiB) and lost a run.
- **`-sm layer` only.** `-sm row` → `ggml-sycl.cpp:1419: fatal error`, exit `0xC0000409`.
- **`-lm none` saves ~8 GB resident** versus mmap (78.4 vs 85.6 GB WS). It is the lowest-RAM mode.
  Counter-intuitively it does **not** preserve the "experts on NVMe" property — with `-lm none`,
  CPU tensors are anonymous RAM, not file-backed. Choose knowingly:
  - `-lm auto` → CPU experts are `CPU_Mapped`, file-backed and evictable (the NVMe idea), +8 GB.
  - `-lm none` → CPU experts are anonymous, −8 GB, but pinned.
- **`-t 12`**, `--no-warmup` (warmup is minutes of dead time), `--cache-ram 0` when memory is tight.

### 4.3 Split tooling that is already on GPU-BOX

| File | What it does |
|---|---|
| `C:\b70-work\box-tensor-all.py` | dumps all four shards → `tensor-summary.json` (1008 tensors) |
| `C:\b70-work\box-solve2.py` | solves `-ncmoe` + byte-balanced `-ts` for a given VRAM headroom |
| `C:\b70-work\box-solve3.py` | same, targeting a GPU-total budget |
| `C:\b70-work\box-run18.ps1` | load + poll health + bench inline — **the correct harness pattern** |

Re-run the solver whenever `-c` or headroom changes; do not reuse a `-ts` from a different config.

-

## 5. Do NOT repeat these

1. **Do not bisect the three patches.** The `-1` was the watchdog. Nothing implicates them.
2. **Do not blame Engram.** It is 0.20 GiB in this pack. The 110 GB file is never loaded.
3. **Do not trust pre-09:00 measurements.** Foreign `llama-bench` held 129.66 GB of commit.
   **Check `CommitUsed` before every run** — it must be ~23 GB, not 150 GB.
4. **Do not leave `box-auto.ps1` in place.** It rewrites `auto-srv.bat` on every launch and silently
   reverted a corrected config, wasting two runs.
5. **Do not pipe llama output through `findstr`/`grep`.** Redirect to a file.
6. **Do not use bare `ssh gpu-box 'powershell ... "..."'`** with `$_`/`$var` — local expansion eats them.
   Heredoc to `powershell.exe -Command -`, or push a `.ps1` via base64 and run it with `-File`.
7. **Do not copy a log before re-running a script that deletes it.** (This cost the W-014 log.)

-

## 6. Box state at handoff

Restore this before you start, and leave it this way:

```powershell
# expected
llama-swap            Running
llama-server          none
llama-bench           none
FreePhysical          ~85 GB
CommitUsed            ~23 GB
```

Commands that have worked:

```powershell
# kill stragglers (a wedged process can survive taskkill for ~3 min while unwinding — wait)
taskkill /F /IM llama-server.exe
Get-Process -Name 'llama-server' -ErrorAction SilentlyContinue

# watchdog
Stop-ScheduledTask  -TaskName 'llama-ram-watchdog'
Start-ScheduledTask -TaskName 'llama-ram-watchdog'
Get-ScheduledTask   -TaskName 'llama-ram-watchdog' | Select TaskName,State

# the real kill history — check this FIRST on any death
Get-Content C:\llama-swap\ram-watchdog.log -Tail 20
```

**A process killed at the 1.5–6 GB floor can take 3–5 minutes to actually die** while it releases
~85 GB of mapped pages, and it will resist `taskkill`, `Stop-Process -Force`, and WMI `Terminate`
(rc=2) during that time. Watch `WorkingSet64` fall instead of assuming it is unkillable.

-

## 7. Paths

| What | Where |
|---|---|
| Build | `C:\llamacpp-v41\build-sycl\bin` (commit `de5122d`) |
| Pack | `D:\AI\Models\dsv41` — 4 shards, 128.74 GiB, plus an unused 103 GB Engram file |
| Test configs | `C:\b70-work\opt5.bat`, `r18.bat`, `srv-v41.bat`, `auto-srv.bat` |
| Split tooling | `C:\b70-work\box-{tensor-all,solve2,solve3}.py`, `tensor-summary.json` |
| Bench | `C:\b70-work\bench-9100.py` |
| Watchdog | `C:\llama-swap\ram-watchdog.ps1` + `.log` |
| Production | `C:\llama-swap\config.windows.yaml` — **do not edit**; restart via `nssm`/service only |

-

## 8. Boundaries

- llama-swap holds ~58 GB of VRAM. Stop it for any 1017 run; **always restore it.**
- The owner granted exclusive use of the box for this work on 2026-10-28. Re-confirm before
  stopping production, and do not kill other people's jobs without asking.
- Do not download new models or change drivers without explicit approval.

-

## 9. Honest assessment

Last session killed the wrong theory (an abort), found the real kill mechanism (the watchdog),
produced the first real tensor inventory, solved the VRAM split arithmetic, and got 1017 to
`health 200` for the first time.

What is still missing is one number: **tokens per second**. Everything downstream — whether this
track is worth pursuing, whether 4 cards + 96 GB is the right shape, whether the NVMe-expert idea
pays off — is blocked on that measurement and on the §3 discriminating test.

If load keeps dying at ~85.7 GB WS with the watchdog fixed, the honest conclusion is that this
backend mirrors device allocations into system RAM, and 1017 needs either ~160 GB of RAM or a pack
around 70 GB.
