# kill-arm.ps1 - stop an arm and everything it started.
#
# An arm is three processes (wrapper, child running llama-server, watchdog). Stopping only the
# llama-server leaves the watchdog polling and writing to the ledger, which looks like a live
# experiment that is measuring nothing. This kills what arm.ps1 recorded, then reports anything
# still holding the GPUs.
param(
    [Parameter(Mandatory = $true)][string]$Tag,
    [string]$LogDir = ''   # default: <scripts dir>\..\logs\arms
)
# $PSScriptRoot is not reliably set inside param() defaults under Windows PowerShell 5.1.
if (-not $LogDir) { $LogDir = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\logs\arms')) }

$pidsFile = Join-Path $LogDir "$Tag.pids.txt"
$lockFile = Join-Path $LogDir "$Tag.lock"
$armPids = @()
$armPort = $null
$serverPid = $null
if (Test-Path -LiteralPath $pidsFile) {
    foreach ($line in (Get-Content -LiteralPath $pidsFile)) {
        if ($line -match '^\s*(child|watcher)=(\d+)\s*$') { $armPids += [int]$Matches[2] }
        elseif ($line -match '^\s*port=(\d+)\s*$') { $armPort = [int]$Matches[1] }
        elseif ($line -match '^\s*server=(\d+)\s*$') { $serverPid = [int]$Matches[1] }
    }
} else {
    "no pids file for tag '$Tag' ($pidsFile)"
}

foreach ($armId in $armPids) {
    $running = Get-Process -Id $armId -ErrorAction SilentlyContinue
    if ($running) { "stopping arm process PID=$armId name=$($running.Name)"; Stop-Process -Id $armId -Force }
    else { "PID=$armId already gone" }
}

# The arm's llama-server is now in pids.txt (arm.ps1 records it once the endpoint is discovered),
# so teardown is one command. The kill is conditional on two re-verifications, because a bare
# PID from a file is not a safe kill target on a box that also runs the production server:
#   1. the PID must still be named llama-server.exe (PID reuse guard - a recycled PID belongs
#      to some unrelated process and must never be touched), and
#   2. its command line must still mention this arm's --port (a recycled or rebound
#      llama-server on a different port - e.g. a llama-swap reload - must never be touched).
# A pids.txt without a server= line predates this format; nothing safe is derivable from it,
# so the handle is held and the operator uses kill-port-server.ps1 explicitly, as before.
if ($null -ne $serverPid) {
    $srvProc = Get-CimInstance Win32_Process -Filter "ProcessId=$serverPid" -ErrorAction SilentlyContinue
    if (-not $srvProc) {
        "arm server PID=$serverPid already gone"
    }
    elseif ($srvProc.Name -ne 'llama-server.exe') {
        "server PID=$serverPid is now '$($srvProc.Name)', not llama-server.exe (PID reuse) - not killing it"
    }
    elseif ($null -eq $armPort) {
        "arm server PID=$serverPid recorded but pids.txt has no port= line - holding; use kill-port-server.ps1"
    }
    elseif ($srvProc.CommandLine -notmatch '-port\s+' + $armPort + '\b') {
        "arm server PID=$serverPid no longer on --port $armPort - not killing it"
    }
    else {
        "stopping arm server PID=$serverPid (--port $armPort)"; Stop-Process -Id $serverPid -Force
    }
}

# Any llama-server still running is NOT this arm's (everything it recorded was handled above).
# Report it so a production reload or a forgotten manual server is visible without being touched.
$servers = @(Get-CimInstance Win32_Process -Filter "Name='llama-server.exe'")
if ($servers.Count -gt 0) {
    "still running (not owned by tag '$Tag', left alone):"
    foreach ($srv in $servers) { "  llama-server PID=$($srv.ProcessId)" }
} else {
    "no llama-server running"
}

if (Test-Path -LiteralPath $lockFile) { Remove-Item -LiteralPath $lockFile -Force; "removed lock $lockFile" }
"done"
