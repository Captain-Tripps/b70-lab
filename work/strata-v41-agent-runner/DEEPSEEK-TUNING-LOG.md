# DEEPSEEK TUNING — session log (2026-10-27 late)

Attempt to establish a layer-vs-tensor split baseline on the DeepSeek V4 0731 pack.
**The benchmark never produced a number.** What it did produce is two real defects and a
methodology lesson. Recorded so the next attempt does not repeat it.

-

## 1. Blocking finding: `GGML_SYCL_PIPELINE=1` deadlocks in llama-bench on this MoE

First attempt (`-sm layer,tensor`, pipeline on, matching the production env):

```
[SYCL-PIPE] still waiting for device 0 (queued=2 busy=1);
  dev0: node 5300 MUL_MAT_ID; dev1: node 0 NONE; dev2: node 0 NONE; dev3: node 0 NONE;
```

Repeated forever. **Device 0 is stuck on a `MUL_MAT_ID` node while devices 1-3 sit completely
idle.** That is a pipeline scheduling deadlock on the MoE expert matmul, not a slow load:

- Disk reads: 0 B/s
- CPU: ~1 core equivalent (should be multithreaded during load)
- Only card 0 held VRAM (34 GB); cards 1-3 held nothing
- Process responsive, `SYCL-PIPE` spamming, no progress for 25+ minutes

Production uses `GGML_SYCL_PIPELINE=1` with `GGML_SYCL_PIPELINE_MAX_QUEUED=4` in llama-server and is
fine. **The deadlock appears specific to llama-bench**, but that should be confirmed — if it can also
happen in llama-server under some prompt shape, that is an outage-class bug for the production entry.

Node id 5300 and op `MUL_MAT_ID` are recorded here in case it reproduces.

## 2. Second attempt without the pipeline: still no result

`GGML_SYCL_PIPELINE=0`, `-sm layer`, same model and `-ts`. This one loaded normally — CPU climbing,
RSS growing 20.9 -> 31.1 -> 52 GB, **zero** `SYCL-PIPE` lines — so the pipeline really was the first
failure. But it then ran 35+ minutes with the log frozen at the device table, RSS oscillating
20 -> 85 GB, and ended `EXIT=-1` with no benchmark rows.

That RSS oscillation (weights being re-read, not placed) is load churn. llama-bench **reloads the
model per configuration**, and this model is ~100 GB across 3 shards. The documented load cost is
10-17 min per load. Two configs = two loads = 20-35 min *before the first measurement*, plus this
pack appears to be slower than that note.

**Conclusion: llama-bench is the wrong tool for a 100 GB model on this box.** It cannot amortise the
load, and the reload cost dominates everything we were trying to measure.

## 3. Methodology lesson (mine, not the box's)

I wasted a long stretch on a **wrong liveness probe**:

```
Get-Process llama-bench          # WRONG: PowerShell parses "-bench" as a parameter, returns nothing
Get-Process -Name 'llama-bench'  # correct
```

That bug reported "not running" while a 52 GB process was alive and loading, which made me conclude
several times that the bench had died and relaunch it — each relaunch starting another 10-35 minute
load. **Quote hyphenated process names in PowerShell.** This is the second session in a row where a
probe told me something false about a running process; verify with `tasklist /FI "IMAGENAME eq X.exe"`
when it matters.

Also: `taskkill` and `Stop-Process` both returned "no running instance" for a PID that
`Get-Process -Name` still listed. The process was in gatekeeper teardown, not alive. `tasklist` is
the authority.

## 4. State at handoff

| Item | Value |
|---|---|
| llama-bench | gone; `tasklist` confirms no tasks match |
| VRAM | all cards 0.0 GB (card 3 0.2 GB baseline) |
| Free RAM | 87.2 GB |
| Logs | `bench_split.txt`, `bench_layer.txt` — device tables only, no results |
| Production | untouched, llama-swap still running |

## 5. The right next step (not done)

**Use llama-server, not llama-bench.** Load once, then measure decode through the HTTP API with
`bench/sbench.py` (the same 7-prompt set the lab uses):

1. Start the production `deepseek-v4-flash-dspark` config as-is -> measure. That is the honest
   baseline and it is known-good (24 tok/s documented).
2. Then flip only `-sm layer` -> `-sm tensor` on the same command, reload, measure again.
3. Acceptance rate and tokens/round come from the server log, same as the Qwen work.

One load per arm, and each arm is a real serving configuration rather than a synthetic forward.
Budget ~15 min load + ~5 min measure per arm.

Alternative if the load cost itself is the thing we want to attack: that is open item **#7**
("Model load takes 10-17 min") which is already logged and is arguably higher-value than split-mode
micro-tuning, because it gates every experiment.
