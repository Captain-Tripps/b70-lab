# Native Windows runner (STEP-000)

Two PowerShell scripts and a CPU-only test suite. They exist because the lab already had a
*server* lifecycle tool (`../arm.ps1` + `../kill-arm.ps1`) and no way to run a one-shot build or
probe with trustworthy exit codes, argument passing and cleanup.

```
bench/runner/
  Invoke-NativeCommand.ps1   run one native process -> result.json + stdout/stderr files
  GpuTestLock.ps1            one exclusive GPU-test lease, with PID+start-time+path ownership
  Test-NativeRunner.ps1      CPU-only contract tests (11 cases)
```

## Why not reuse arm.ps1

`arm.ps1` assumes what it starts is a llama-server: it discovers a port, samples PDH counters,
holds the endpoint warm and tears down. A compiler invocation has none of those properties, and
needs three that arm.ps1 does not offer — a caller-chosen cwd, an argv that survives paths with
spaces, and a timeout that reaps the child *tree*.

## Windows-specific things that bit this implementation

Both were found by running the suite on GPU-BOX, not by reading docs.

1. **`ProcessStartInfo.ArgumentList` does not exist here.** GPU-BOX runs Windows PowerShell 5.1 on
   .NET Framework 4.0. Only the single-string `.Arguments` property exists, so argv quoting is
   implemented directly per `CommandLineToArgvW` rules (double backslashes before a closing
   quote, escape embedded quotes). Without this, a path with spaces silently becomes two
   arguments.
2. **`powershell.exe -File` cannot bind an array parameter from separate tokens.** `-Arguments a b c`
   binds only `a`. Argument vectors therefore travel in a JSON *file* (`-ArgumentsJsonPath`), which
   also keeps a long compiler command line off the command line entirely.

Invoking a `.ps1` as a child also needs an explicit `-File`; without it PowerShell treats the
path as `-Command` and exits 1.

## Contract

`Invoke-NativeCommand.ps1` writes `result.json`:

| field | meaning |
|---|---|
| `outcome` | `PASS` \| `FAIL` \| `TIMEOUT` \| `ERROR` |
| `exit_code` | the child's own exit code; `null` for TIMEOUT/ERROR |
| `timed_out` | true only for TIMEOUT — deliberately not folded into exit code 1 |
| `stdout_path` / `stderr_path` | files in the run directory |
| `run_directory` | unique per run |
| `killed_pids` | tree members reaped on timeout |
| `child_pid` | the direct child, for correlation |

Script exit code: `0` PASS, `2` FAIL, `3` TIMEOUT, `4` ERROR.

## Ownership rules

Cleanup never kills by process *name*. A process is only stopped when PID **and** creation time
**and** executable path all still match what was recorded. A recycled PID fails the check and is
left alone. This is the same guard `kill-arm.ps1` applies to `llama-server.exe`, generalised.

A lease means "I have stopped asking for the GPU", not "VRAM is free". Releasing it never
unloads or kills somebody else's model server.

## Running the tests

```
powershell.exe -NoProfile -ExecutionPolicy Bypass -File Test-NativeRunner.ps1
```

Cases: success, nonzero exit, stderr capture, timeout-with-tree-kill, paths with spaces,
shell-injection attempt, sentinel survival, competing lock, live-lease protection, stale-lease
recovery, missing-cwd-is-error.

**A pass here does not qualify the runner against real Strata builds, and it is not a GPU
result.** It qualifies the runner's own contract. The plan is explicit that a Linux/WSL
substitute cannot be reported as a Windows pass; by the same token this suite is CPU-only by
design.
