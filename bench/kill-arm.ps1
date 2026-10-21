# kill-arm.ps1 - stop an arm and everything it started.
#
# An arm is three processes (wrapper, child running llama-server, watchdog). Stopping only the
# llama-server leaves the watchdog polling and writing to the ledger, which looks like a live
# experiment that is measuring nothing. This kills what arm.ps1 recorded, then reports anything
# still holding the GPUs.
param(
    [Parameter(Mandatory = $true)][string]$Tag,
    [string]$LogDir = "%USERPROFILE%\AI\logs\arms"
)

$pidsFile = Join-Path $LogDir "$Tag.pids.txt"
$lockFile = Join-Path $LogDir "$Tag.lock"
$armPids = @()
if (Test-Path -LiteralPath $pidsFile) {
    foreach ($line in (Get-Content -LiteralPath $pidsFile)) {
        if ($line -match '^\s*(child|watcher)=(\d+)\s*$') { $armPids += [int]$Matches[2] }
    }
} else {
    "no pids file for tag '$Tag' ($pidsFile)"
}

foreach ($armId in $armPids) {
    $running = Get-Process -Id $armId -ErrorAction SilentlyContinue
    if ($running) { "stopping arm process PID=$armId name=$($running.Name)"; Stop-Process -Id $armId -Force }
    else { "PID=$armId already gone" }
}

# llama-server is a grandchild of the wrapper, so it is not in pids.txt. It is deliberately NOT
# killed here: on this box a llama-server may be the live llama-swap service.
$servers = @(Get-CimInstance Win32_Process -Filter "Name='llama-server.exe'")
if ($servers.Count -gt 0) {
    "still running (handle deliberately):"
    foreach ($srv in $servers) { "  llama-server PID=$($srv.ProcessId)" }
} else {
    "no llama-server running"
}

if (Test-Path -LiteralPath $lockFile) { Remove-Item -LiteralPath $lockFile -Force; "removed lock $lockFile" }
"done"
