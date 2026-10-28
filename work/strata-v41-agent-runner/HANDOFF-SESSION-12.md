# Handoff — DeepSeek V4.1 Flash 1017 on 4x Arc Pro B70 (2026-10-28 01:00)

Written for a fresh session. Read this, then act. Do not repeat completed work.

Branch: `work/strata-v41-agent-runner`, remote `Captain-Tripps/b70-lab`.
HEAD at handoff: `6964acb`. Tree clean, all pushed.

**Read next, in order:**
1. this file
2. `work/strata-v41-agent-runner/PREFILL-MEASURED.md` — the one real number we have
3. `work/strata-v41-agent-runner/CHECKPOINT-FIX-NEGATIVE.md` — what was ruled out
4. `work/strata-v41-agent-runner/TS-SPLIT-FINDING.md` — why `-ts` cannot help here
5. `deepseek-v4/strata-v41/QWEN-SPEED.md` — the *other* track, if you are asked about Qwen

-

## 1. One-line state

**1017 loads and runs on an idle box, processes prompt tokens at 0.85 tok/s, then dies with a silent
`exit -1`. Prefill improved 2.6x over the old 0.33 figure. The crash is not a config problem.**

-

## 2. What is actually working

| Item | State |
|---|---|
| Build with `deepseek41` | `C:\llamacpp-v41\build-sycl\bin`, commit `de5122d` |
| Arch support lives in | **`llama.dll`**, not the 10 KB `.exe` launchers — scan the DLL or just try loading |
| Pack loads | yes, on an idle box, via `C:\b70-work\srv-v41.bat` |
| Fused HC ops | **pre / comb / post all `enabled`** — a prior session's patch works |
| Batching | **engages** — `graph (pp bs=512, tg bs=1): nodes = 4910 / 4844, splits = 166 / 13` |
| Prefill | **0.85 tok/s** (27 tokens / 31.75 s) |
| Decode | 3.05 tok/s (from the ledger, `tg8`) |
| Drafter | **none.** Pack has 1008 tensors, layers 0-39, zero `mtp.*` |

**The original theory — "batched prompt path is dead because HC fusion is disabled" — is FALSIFIED.**
Fusion is enabled and batching splits at 166. Do not re-investigate that.

-

## 3. The actual blocker: a silent abort

Two configurations, two different death points, same silent `exit -1`:

| Config | Outcome |
|---|---|
| `srv-v41.bat` (checkpoints on) | `model loaded` + `listening`, served a request, 27 tokens @ 0.85 tok/s, then `exit -1` |
| `srv-nockpt.bat` (`--cache-ram 0 --ctx-checkpoints 0`) | never reached `model loaded`; died at `llama_context` |

Proof the process really died at ~32 s (not still working):

| Event | Time |
|---|---|
| `prompt processing, n_tokens = 27, t = 31.75 s` | T+32 s |
| `created context checkpoint 1 of 32` | T+32.1 s |
| server `exit -1` | T+32.2 s |
| client "connection closed" | T+230.9 s (client socket timeout — **not** work time) |

**Two silent `-1`s at different stages = unhandled abort in the deepseek41 SYCL path, not a setting.**
Stop permuting flags.

### Prime suspect

The build carries **3 uncommitted local patches**:

```
M src/llama-context.cpp        (the fused-ops fix, backup: .orig-fusedprobe)
M src/llama-model-loader.cpp   (diag,   backup: .orig-diag)
M src/models/deepseek41.cpp    (keys,   backup: .orig-strata-keys)
```

At least one of them predates the successful 12:19 server run; `llama.dll` was rebuilt at **10:50**,
after that success. An interaction between these is the most likely cause.

-

## 4. What to do next, in order

1. **Get the abort site.** `GGML_SYCL_DEBUG=1`, or attach a debugger / enable Windows WER dumps. Do not
   try more flag combinations first — we have ruled out the two most plausible ones.
2. **Bisect the three patches.** `git stash` them one at a time (backups exist as `.orig-*` files) and
   see which one makes it survive past 27 tokens. This is cheap and high-information.
3. If a patch is the cause, the goal is a load that survives a full 134-token prompt so we get a real
   prefill number at batch > 27.

-

## 5. Ruled out — do not redo

| Hypothesis | Verdict | Evidence |
|---|---|---|
| HC fusion disabled | **FALSE** — enabled | `fused DeepSeek V4 HC pre/comb/post enabled` |
| Batched prompt path dead | **FALSE** — 166 splits | `sched_reserve: graph (pp bs=512...) splits = 166 / 13` |
| Context checkpoints cause the crash | **FALSE** — disabling makes it fail earlier | `CHECKPOINT-FIX-NEGATIVE.md` |
| `-ts` can fix the split boundary | **IMPOSSIBLE** — needs 65.9 GiB on one card | layer 20's readers are 21-40 |
| A smaller 1017 quant exists | **NO** — all alternatives equal or larger | 1-bit build is 224 GB and rated "fail" by its author |
| Host RAM was the limit | **only at first** — 128.74 GiB pack on 95.9 GB box thrashed; with an idle box it loads fine | `PREFILL-INVESTIGATION.md` |

-

## 6. Hard constraints (physics, not tuning)

- **The pack exceeds 4x32 GB by ~955 MiB** at `-ngl 99` (ledger L-012: 131,187 wanted vs 130,232
  available). Every working run therefore uses **`-ngl 38`** — 3 of 41 layers on CPU.
- **llama-swap must be stopped** for any 1017 run: production holds ~58 GB of VRAM. A maintenance
  window is required, and the operator has granted one before (2026-10-28 00:40).
- **Engram table is 110 GB** and cannot be resident in 95.9 GB RAM. Expect thrash unless it is
  streamed / pinned to CPU (`-ot "engram_embd.weight=CPU"` in upstream recipes).

-

## 7. Proven commands

### The working load (start here)

```bat
REM C:\b70-work\srv-v41.bat  — the config that DOES load and serve
call "C:\Program Files (x86)\Intel\oneAPI\setvars.bat" --force >nul 2>&1
"C:\llamacpp-v41\build-sycl\bin\llama-server.exe" ^
  -m "D:\AI\Models\dsv41\DeepSeek-V4.1-Flash-1017-GSQ-RCO-IQ2_XXS-00001-of-00004.gguf" ^
  -c 2048 -ngl 38 -fit off -sm layer -t 12 -lzm off -lm none -np 1 -lv 4 ^
  --no-warmup --host 127.0.0.1 --port 9063 >> C:\b70-work\srv-v41.log 2>&1
```

**Do not add** `GGML_SYCL_*`, `ONEAPI_DEVICE_SELECTOR`, or VMM overrides. `srv-v41.bat` says so in its
own comments: `GGML_SYCL_ENABLE_VMM=0` made `llama_context` construction die with -1.

Load takes **~12 minutes**. `--no-warmup` avoids another ~9 min. `/health` returns 503 until ready;
poll `/props` or watch the log for `model loaded` / `listening`.

### Stopping and restoring production

```powershell
Stop-Service -Name 'llama-swap' -Force          # frees ~58 GB VRAM
# ... test ...
Start-Service -Name 'llama-swap'                # always restore
```

Verify with `Get-Service -Name llama-swap` and `tasklist | findstr llama-server`.

-

## 8. Operational lessons — these cost a whole session

Every one of these produced a *plausible-looking* wrong conclusion. Read them.

1. **`setvars.bat` is mandatory.** Without it the binary exits `-1073740612` (`0xC00004BC`, DLL load
   failure) **with zero output**. A 0-byte log meant this, not a hang.
2. **`.cmd` files need CRLF.** Written with LF, `cmd.exe` silently does nothing.
3. **Never pipe llama output through `findstr`/`grep`** — it buffers until exit; you get a 0-byte log.
   Redirect straight to a file.
4. **`Get-Process llama-bench` silently returns nothing** — PowerShell parses `-bench` as a parameter.
   Use `Get-Process -Name 'llama-bench'` or `tasklist /FI "IMAGENAME eq llama-bench.exe"`.
5. **`tasklist | grep -i llama` can miss `llama-server.exe`** — case sensitivity. Use
   `tasklist /FI "IMAGENAME eq llama-server.exe"`.
6. **`$_` and `$var` are eaten by local expansion** in `ssh "..."` double quotes (`$_` becomes
   `/bin/bash`). Push a script and run it, or use
   `powershell -EncodedCommand $(iconv -f UTF-8 -t UTF-16LE file | base64 -w0)` — **UTF-16LE**, not UTF-8.
7. **`$F` in `ssh '... $F ...'` gives "ambiguous redirect"** — use literal paths.
8. **Long `exec` calls get SIGKILLed by the harness**, which kills the ssh channel and the remote child.
   Use `exec(background=true)` or `Start-Process` on the Windows side.
9. **`-fit` is a `llama-cli` flag, not a `llama-bench` flag** — bench rejects it with
   `error: invalid parameter for argument: -fit`.
10. **`llama-bench` is wrong for this model** — it reloads per configuration, so N configs = N × 12 min
    before the first measurement. Use `llama-server` once and measure over HTTP.
11. **Log size is not a liveness signal.** A 12-minute load sits at a fixed byte count, then jumps.
    Judge by process CPU, working set, and VRAM deltas — never by log growth.
12. **Quote hyphenated process names** and prefer `tasklist /FI` when it matters.
13. **A `sleep`-based waiter left over ssh becomes a phantom** — the gateway's `process list` shows it
    running while `/proc/<pid>` is absent to your shell (different PID namespace). It is inert. Do not
    burn turns chasing it; my memory notes record this exact artifact.
14. **Copy a log before re-running a script that deletes it.** I destroyed the W-014 success log
    (`C:\b70-work\st10.log`) by running `st10.bat`, which starts with `del /q`. Do not repeat this.

-

## 9. Files and paths

| What | Where |
|---|---|
| Build | `C:\llamacpp-v41\build-sycl\bin` (`de5122d`) |
| 1017 pack | `D:\AI\Models\dsv41` — 4 shards + 110 GB Engram + mmproj, 233 GB total |
| Working server script | `C:\b70-work\srv-v41.bat` (+ `.bak-cp` backup) |
| Checkpoint-off variant | `C:\b70-work\srv-nockpt.bat` |
| Server log | `C:\b70-work\srv-v41.log` |
| Other build (no `deepseek41`) | `%USERPROFILE%\AI\Runtimes\llama.cpp\master-797de6-b70-r67c` — production, do not confuse |
| Production config | `C:\llama-swap\config.windows.yaml` (has `deepseek-v4-flash-dspark` on 0731) |
| Ledger | `work/strata-v41-agent-runner/FINDINGS.md` |

-

## 10. Raw material worth knowing

- **0731 works and has DSpark.** `deepseek-v4-flash-dspark` in the production config runs a 10.9 GB
  Q8_0 drafter across all 4 cards at ~24 tok/s. 0731 is `general.architecture = deepseek4`; 1017 is
  `deepseek41`. Different graphs. Do not conflate them.
- **DSpark's 8.04 GiB drafter is the "missing 8 GB"** the old handoff referred to for 1017. It is
  DeepSeek's own ~14B semi-autoregressive drafter. It does **not** ship for 1017 in GGUF form and
  upstream Intel docs state V4.1-Flash "does not run on Intel" — yet it does here, because the fork has
  `deepseek41`. Treat vendor support matrices as unreliable; measure.
- **Qwen is a separate, finished track.** Best measured: **50.80 tok/s** (code, `--spec-min-p 0`) and
  **36.73** (prose, `--spec-min-p 0.5`). 2 cards give 2.6x; cards 3-4 add +3%. Full detail in
  `QWEN-SPEED.md`. Do not re-run that sweep.

-

## 11. Honest assessment

The 1017 track is blocked on a crash, not on performance. 0.85 tok/s prefill is unusable (a 4K prompt
would take 80 minutes), but **we cannot evaluate prefill performance until the process survives a full
prompt** — 27 tokens is the most it has ever done.

The highest-value next move is the patch bisect (§4.2), because it is cheap, the backups already exist,
and the build was rebuilt at 10:50 *after* the last known success at 08:56.
