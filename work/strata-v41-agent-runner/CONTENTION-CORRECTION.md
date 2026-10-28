# Concurrency contamination — my "cannot load" verdict is WITHDRAWN (2026-10-28 08:15)

`HOST-COMMIT-CONTROL.md` concluded 1017 cannot load on this box. **That verdict is withdrawn.**
The measurements behind it were taken while another agent was running 1017 workloads on the same
machine.

Mechanism findings below survive. The 1017-specific numbers do not, and need a clean window.

-

## 1. What was running that I did not account for

Between ~07:40 and 08:10, three separate foreign workloads were active on GPU-BOX:

| Process | Parent chain | What it was doing |
|---|---|---|
| `llama-bench.exe` pid 29500 | `sshd.exe -z` → `bash.exe` → `wsl.exe` → `cmd.exe /c qual.bat` | `-m 1017 -ngl 38 -lm none -r 3 -p 512 -b 128`, 129.66 GB private |
| `cmd.exe /c final.bat` | `bash.exe -c "cd /mnt/c/b70-work/bw && ..."` | another 1017 run, port 9040 |
| `cmd.exe /c fg.bat` | same WSL path | another 1017 run, port 9034 |

None of these were mine. They were launched from a **different SSH session** (`sshd.exe -z` parent),
not from this agent's connection. `D:\strata-dsv41-port` holds 176 artifacts from that work.

**Consequence:** `CommitUsed` sat at 153–155 GB against a 154.8 GB limit for most of the session,
with 129.66 GB held by `llama-bench`. Every 1017 load I ran in that window was competing for
~130 GB of commit it did not have.

-

## 2. What this invalidates

| Claim | Status |
|---|---|
| "1017 needs ~148 GB RAM, shortfall 33–43 GB" | **Withdrawn.** Derived from contaminated peaks. |
| "priv 121–133 GB in every load mode" | **Unreliable.** Contended, and at least one run shared VRAM. |
| "`-lm auto` only reduced host cost 11%" | **Unreliable.** Same reason. |
| `HOST-COMMIT-CONTROL.md` §3 arithmetic | **Withdrawn pending re-measurement.** |

## 3. What survives

These are structural and do not depend on the contention:

**a. `-ngl 40` overflows the cards.** Buffer sizes were 33,694 / 31,952 / 33,962 / 28,627 MiB
against **32,558 MiB per card**. Cards 0 and 2 exceed capacity, so the excess spills into system
RAM. `-ngl 38` keeps all four under (31,059 / 32,121 / 30,504 / 28,627). **`-ngl 38` is correct and
`-ngl 40` is invalid on this box** — that is arithmetic, independent of contention.

**b. `-ncmoe` + `-sm layer` produces catastrophic splits.** Two runs with *identical* flags gave
wildly different placements:

```
ncmoe 12, -sm layer:  SYCL0 4363  SYCL1 32121  SYCL2 30504  SYCL3 28627
ncmoe 12, -sm layer:  SYCL0  956  SYCL1  3406  SYCL2 32121  SYCL3 59131   <- 59 GB on a 32.5 GB card
```

`-ncmoe` makes layers different sizes; `-sm layer` then packs whole layers and can hand one card
more than it holds. The split depended on free VRAM at load time — i.e. on the contention.

**c. `-sm row` is not supported in this SYCL backend.**

```
ggml-sycl.cpp:1419: fatal error
exit -1073740791 (0xC0000409)
```

So `-sm layer` is the only usable splitter, which means `-ncmoe` must be chosen so layers stay
balanced — or replaced with explicit `-ot` tensor overrides.

**d. The NVMe-resident mechanism does exist and does engage.** With `-lm auto` plus CPU-placed
tensors, the loader reported:

```
CPU_Mapped model buffer size = 35201.25 MiB
```

`CPU_Mapped` is a **file-backed, evictable** buffer, not pinned anonymous memory. 35.2 GB of
weights lived as mmap'd pages on `D:`. This is exactly the "experts and ngram on NVMe" behaviour.
The mechanism is available and works; what is unsettled is whether the remaining tensors fit.

**e. The watchdog reads the wrong metric for mmap loads.** `ram-watchdog.ps1:32` uses
`Win32_OperatingSystem.FreePhysicalMemory`, which **excludes standby/reclaimable pages**. Measured
during a load:

```
free=0.00   available=58.19   standby=58.02     <- 58 GB usable, watchdog would see 0
```

and at a kill: watchdog saw 5.28 GB while true `AvailableBytes` was ~7–8 GB. A mmap-heavy load
drives "free" toward zero while the box still has several GB usable. **The floor should read
`AvailableBytes`, not `FreePhysicalMemory`.**

**f. `priv` is anonymous commit, not resident RAM, and the control proved it.** Qwen3-Coder,
17.28 GB model: `priv = 19.66 GB` but `ws = 27.71 GB`. Working set *exceeded* private commit
because file-backed mapped pages count in WS but not in private commit. So priv ≈ model size is a
real relationship, not VRAM accounting — the earlier "WDDM counts VRAM in commit" hypothesis was
wrong.

-

## 4. What is needed to actually settle it

1. **A closed window.** No `llama-bench`, no `qual.bat`, no `final.bat`, `CommitUsed` under
   ~30 GB, and confirmed by a pre-flight check. My runs were invalid because I did not check this.
2. **Re-run the matrix** with that guarantee: `-ngl 38 -lm none`, `-ngl 38 -lm auto`,
   `-ngl 38 -ncmoe N -lm auto` for a few N, with `-sm layer` and balanced N.
3. **Prefer explicit `-ot` over `-ncmoe`.** `-ncmoe` shifts whole layers and breaks `-sm layer`
   balance. `-ot` can target expert tensors per-layer and keep the split even.
4. **Fix the watchdog floor** to `AvailableBytes` before any further 1017 run, or it will kill
   healthy mmap loads.

-

## 5. Lesson

23. **Check for concurrent workloads before benchmarking a shared box.** I read `Get-Process`
    repeatedly but only filtered for `llama-server`; a `llama-bench` holding 129 GB of commit went
    unnoticed through six runs. A pre-flight `CommitUsed` check would have caught it immediately.
    Contention does not just slow measurements — it changes tensor placement, which is the variable
    under test.
