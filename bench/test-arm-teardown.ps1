# test-kill-arm.ps1 - regression tests for kill-arm.ps1 arm-server teardown.
#
# What is under test: kill-arm.ps1 must stop the llama-server that an arm *recorded*
# (server=<pid> in pids.txt), but only after re-verifying that the recorded PID is still
# a live llama-server.exe whose command line mentions the tag's --port. A llama-server it
# never recorded - e.g. the live llama-swap production service - must never be touched.
#
# The "server" here is a tiny exe compiled from mock-server source at test setup, named
# llama-server.exe: one process, no children, sleeps forever, and accepts (and echoes) any
# argv, so its command line can carry a fake --port token like a real arm's. Renamed copies
# of ping.exe (exits on unknown switches) and powershell.exe (can't locate its assemblies
# outside its home dir) both die on startup and are NOT usable mocks.
# No real GPU server is involved; nothing on this machine loads a model.
$ErrorActionPreference = 'Stop'

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$killScript = Join-Path $scriptDir 'kill-arm.ps1'
if (-not (Test-Path -LiteralPath $killScript)) { Write-Error "kill-arm.ps1 not next to the test"; exit 1 }

$mockDir = Join-Path $env:TEMP 'arm-kill-test'
$mockExe = Join-Path $mockDir 'llama-server.exe'
$logDir = Join-Path $env:TEMP 'arm-kill-test\logs'
$results = @()

function Start-MockServer {
    param([string]$PortArg)
    $p = Start-Process -FilePath $mockExe -ArgumentList @('--port', $PortArg) -WindowStyle Hidden -PassThru
    Start-Sleep -Milliseconds 600
    if (-not (Mock-Alive $p.Id)) { Write-Error "mock server for --port $PortArg died on startup"; exit 1 }
    return $p
}
function Mock-Alive { param([int]$Id) [bool](Get-Process -Id $Id -ErrorAction SilentlyContinue) }
function Run-KillArm { param([string]$Tag)
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $killScript -Tag $Tag -LogDir $logDir 2>&1 | Out-String
}
function Assert-MockKilled { param([string]$Case, [int]$Id)
    if (Mock-Alive $Id) { $script:results += "FAIL ${Case}: mock server PID $Id is still alive" }
    else { $script:results += "PASS $Case" }
}
function Assert-MockAlive { param([string]$Case, [int]$Id)
    if (-not (Mock-Alive $Id)) { $script:results += "FAIL ${Case}: mock server PID $Id was killed but must survive" }
    else { $script:results += "PASS $Case" }
}

# --- setup: clean slate, one mock that stands in for the arm's llama-server -------------------
foreach ($d in $mockDir, $logDir) { if (Test-Path -LiteralPath $d) { Remove-Item -LiteralPath $d -Recurse -Force } }
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$csc = Join-Path $env:SystemRoot 'Microsoft.NET\Framework64\v4.0.30319\csc.exe'
if (-not (Test-Path -LiteralPath $csc)) { Write-Error 'csc.exe not found; cannot build the mock server'; exit 1 }
$mockSrc = Join-Path $mockDir 'mock-server.cs'
@'
using System.Threading;
class ArmMockServer {
    static void Main(string[] args) {
        foreach (var a in args) System.Console.WriteLine("mock-arg:" + a);
        while (true) Thread.Sleep(100000);
    }
}
'@ | Set-Content -LiteralPath $mockSrc -Encoding UTF8
& $csc /nologo /out:"$mockExe" "$mockSrc" | Out-Null
if (-not (Test-Path -LiteralPath $mockExe)) { Write-Error 'mock server compile failed'; exit 1 }

# --- case 1: arm-owned server recorded in pids.txt must be stopped -----------------------------
$tag = 'tt1'
$server = Start-MockServer -PortArg '9099'
@(
    "# stop this arm with: kill-arm.ps1 -Tag $tag"
    "child=999998"
    "watcher=999999"
    "port=9099"
    "server=$($server.Id)"
) | Set-Content -LiteralPath (Join-Path $logDir "$tag.pids.txt") -Encoding UTF8
$out1 = Run-KillArm -Tag $tag
Assert-MockKilled -Case 'case1_recorded_server_is_stopped' -Id $server.Id

# --- case 2: PID reuse - recorded PID now belongs to something else, must survive --------------
# PID 4 (System) can never be a llama-server.exe; killing it would take the lab box down.
$tag = 'tt2'
@(
    "# stop this arm with: kill-arm.ps1 -Tag $tag"
    'port=9097'
    'server=4'
) | Set-Content -LiteralPath (Join-Path $logDir "$tag.pids.txt") -Encoding UTF8
$out2 = Run-KillArm -Tag $tag
if (-not (Mock-Alive -Id 4)) { $results += 'FAIL case2_pid_reuse_server_is_not_killed: System PID 4 is gone' }
else { $results += 'PASS case2_pid_reuse_server_is_not_killed' }

# --- case 3: unrecorded llama-server (production stand-in) must never be touched ----------------
$tag = 'tt3'
$prod = Start-MockServer -PortArg '9061'
@(
    "# stop this arm with: kill-arm.ps1 -Tag $tag"
    'child=999997'
) | Set-Content -LiteralPath (Join-Path $logDir "$tag.pids.txt") -Encoding UTF8
$out3 = Run-KillArm -Tag $tag
Assert-MockAlive -Case 'case3_unrecorded_server_survives' -Id $prod.Id

# --- case 4: legacy pids.txt (no server= line) must NOT kill anything by port-guessing ---------
# The arm ran on --port 9098 but the old file format records no port, so a safe kill is not
# derivable from the file. kill-arm must hold the handle and tell the operator to use
# kill-port-server.ps1 explicitly. Guessing by scanning command lines is how a production
# llama-server gets murdered; this test exists to make sure that never gets coded in.
$tag = 'tt4'
$legacy = Start-MockServer -PortArg '9098'
@(
    "# stop this arm with: kill-arm.ps1 -Tag $tag"
    'child=999996'
    'watcher=999995'
) | Set-Content -LiteralPath (Join-Path $logDir "$tag.pids.txt") -Encoding UTF8
$out4 = Run-KillArm -Tag $tag
Assert-MockAlive -Case 'case4_legacy_pids_without_server_line_holds_handle' -Id $legacy.Id

# --- case 5: production stand-in (port 9061) survives every case above -------------------------
Assert-MockAlive -Case 'case5_production_server_survives_all_cases' -Id $prod.Id

# --- case 6/7: find-arm-server discovery - the logic that must never pick up production --------
# arm.ps1 records its server PID using Get-ArmServerProcess (bench/find-arm-server.ps1). The
# port token alone is not enough: if an arm is misconfigured onto production's port, the
# Runtime executable-path filter is the thing that keeps the production llama-swap server from
# being recorded (and then killed) as ours.
. (Join-Path $scriptDir 'find-arm-server.ps1')
$rtArm = Join-Path $mockDir 'runtime-a'
$rtProd = Join-Path $mockDir 'runtime-b'
foreach ($rt in $rtArm, $rtProd) { New-Item -ItemType Directory -Force -Path $rt | Out-Null; Copy-Item -LiteralPath $mockExe -Destination (Join-Path $rt 'llama-server.exe') -Force }
$armSrv = Start-Process -FilePath (Join-Path $rtArm 'llama-server.exe') -ArgumentList @('--port', '9096') -WindowStyle Hidden -PassThru
$prodSrv = Start-Process -FilePath (Join-Path $rtProd 'llama-server.exe') -ArgumentList @('--port', '9095') -WindowStyle Hidden -PassThru
Start-Sleep -Milliseconds 600
$found = Get-ArmServerProcess -Runtime $rtArm -Port 9096
if ($found -and $found.ProcessId -eq $armSrv.Id) { $results += 'PASS case6_getarmsrv_with_matching_runtime_returns_arm_pid' }
else { $results += "FAIL case6_getarmsrv_with_matching_runtime_returns_arm_pid: got $(if ($found) { $found.ProcessId } else { 'nothing' }), wanted $armSrv.Id" }
$foundProd = Get-ArmServerProcess -Runtime $rtArm -Port 9095
if (-not $foundProd) { $results += 'PASS case7_getarmsrv_wrong_runtime_returns_nothing' }
else { $results += "FAIL case7_getarmsrv_wrong_runtime_returns_nothing: found PID $($foundProd.ProcessId) outside its runtime" }

# --- cleanup: never leave mock servers behind ---------------------------------------------------
$orphans = @(Get-CimInstance Win32_Process -Filter "Name='llama-server.exe'" |
    Where-Object { $_.CommandLine -like "*$mockDir*" })
foreach ($o in $orphans) { Stop-Process -Id $o.ProcessId -Force -ErrorAction SilentlyContinue }
Remove-Item -LiteralPath $mockDir -Recurse -Force -ErrorAction SilentlyContinue

# --- report -------------------------------------------------------------------
$results | ForEach-Object { $_ }
$out1, $out2, $out3, $out4 | ForEach-Object { "--- kill-arm output ---`n$_" } | Out-File -FilePath (Join-Path $env:TEMP 'kill-arm-test-output.txt') -Encoding UTF8
if (@($results | Where-Object { $_ -like 'FAIL*' }).Count -gt 0) { 'RESULT: FAIL'; exit 1 }
'RESULT: PASS'
exit 0
