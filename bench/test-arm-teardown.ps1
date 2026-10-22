# test-kill-arm.ps1 - regression tests for arm teardown: kill-arm.ps1 (operator one-step) and
# arm.ps1's auto-teardown (the arm stops itself after its record is written, so the GPUs are
# freed even if nobody remembers to run kill-arm).
#
# What is under test: kill-arm.ps1 must stop the llama-server that an arm *recorded*
# (server=<pid> in pids.txt), but only after re-verifying that the recorded PID is still
# a live llama-server.exe whose command line mentions the tag's --port. A llama-server it
# never recorded - e.g. the live llama-swap production service - must never be touched.
# And arm.ps1 must tear down its own child/watcher/server after writing record.md - after,
# never before - while honoring a <tag>.benchdone early-release marker and -NoAutoTeardown.
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
$armScript = Join-Path $scriptDir 'arm.ps1'
if (-not (Test-Path -LiteralPath $armScript)) { Write-Error "arm.ps1 not next to the test"; exit 1 }

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
    $ErrorActionPreference = 'Continue'   # same native-stderr containment as Invoke-Arm
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
# A crashed earlier run can leave mock servers holding the exe open; sweep them by executable
# path before touching the directory (production llama-servers live elsewhere and are untouched).
foreach ($o in @(Get-CimInstance Win32_Process -Filter "Name='llama-server.exe'" |
        Where-Object { $_.ExecutablePath -like ((Join-Path $env:TEMP 'arm-kill-test') + '*') })) {
    Stop-Process -Id $o.ProcessId -Force -ErrorAction SilentlyContinue
}
foreach ($d in $mockDir, $logDir) { if (Test-Path -LiteralPath $d) { Remove-Item -LiteralPath $d -Recurse -Force } }
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$csc = Join-Path $env:SystemRoot 'Microsoft.NET\Framework64\v4.0.30319\csc.exe'
if (-not (Test-Path -LiteralPath $csc)) { Write-Error 'csc.exe not found; cannot build the mock server'; exit 1 }
$mockSrc = Join-Path $mockDir 'mock-server.cs'
@'
using System;
using System.Net;
using System.Net.Sockets;
using System.Threading;
class ArmMockServer {
    static byte[] ballast;
    static void Main(string[] args) {
        foreach (var a in args) Console.WriteLine("mock-arg:" + a);
        // arm.ps1 fingerprint step runs `<exe> --version` synchronously; a sleep-forever mock
        // would hang the runner there. Real llama-server prints a banner and exits for --version.
        foreach (var a in args) if (a == "--version") return;
        int servePort = -1;
        for (int i = 0; i < args.Length - 1; i++)
            if (args[i] == "--serve") servePort = int.Parse(args[i + 1]);
        // --alloc-mb N: touch N MB so this mock has the biggest working set on the box. The
        // old watchdog killed "the largest llama-server", which is how a production server
        // that loaded mid-arm would have been shot; case13 uses this to make that deterministic.
        for (int i = 0; i < args.Length - 1; i++)
            if (args[i] == "--alloc-mb") {
                var blob = new byte[int.Parse(args[i + 1]) * 1024 * 1024];
                for (int j = 0; j < blob.Length; j += 4096) blob[j] = 1;
                GC.KeepAlive(blob);
                ballast = blob;
            }
        if (servePort > 0) Serve(servePort);
        while (true) Thread.Sleep(100000);
    }
    static void Serve(int port) {
        // Minimal OpenAI-ish endpoint: arm.ps1's load probe needs one HTTP 200 from
        // POST /v1/chat/completions to call the arm ready; the watchdog just watches /health.
        // Nothing is parsed, nothing is answered correctly - only liveness is mocked.
        var listener = new TcpListener(IPAddress.Loopback, port);
        listener.Start();
        while (true) {
            try {
                var client = listener.AcceptTcpClient();
                var stream = client.GetStream();
                var buf = new byte[8192];
                stream.Read(buf, 0, buf.Length);
                string body = "{\"id\":\"mock\"}";
                string resp = "HTTP/1.1 200 OK\r\nContent-Type: application/json\r\n" +
                    "Content-Length: " + body.Length + "\r\nConnection: close\r\n\r\n" + body;
                var bytes = System.Text.Encoding.ASCII.GetBytes(resp);
                stream.Write(bytes, 0, bytes.Length);
                client.Close();
            } catch { }
        }
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
Stop-Process -Id $armSrv.Id -Force -ErrorAction SilentlyContinue
Stop-Process -Id $prodSrv.Id -Force -ErrorAction SilentlyContinue

# --- cases 8-12: arm.ps1 end-to-end auto-teardown ----------------------------------------------
# arm.ps1 must free the GPUs itself after its record is written - "without waiting on the
# operator" - using the same guards as kill-arm (recorded PID re-verified as llama-server.exe
# still carrying the arm's --port). These cases run the REAL arm.ps1 (bench/ copy, the same
# bytes that deploy to the bench box) against the csc mock. The mock answers chat completions over
# loopback (--serve <port>) so the load probe goes ready without a model, and an arm run costs
# seconds instead of a 45-minute load.
# Preflight is machine-strict on the bench box (refuses a dirty box: resident servers, adapters above
# 1 GB, free RAM under MinFreeGB+65). The mock cases run on whatever dev box has the repo, so
# arm.ps1 exposes -MaxAdapterGB and -HeadroomGB; the tests pass permissive values and the
# production defaults stay strict.
$probePort = if ($env:ARM_TEST_PROBE_PORT) { [int]$env:ARM_TEST_PROBE_PORT } else { 9077 }
function Test-PortOpen { param([int]$Port)
    # A mock bound with --serve answers even a bare connect (its accept loop never stops).
    # Do NOT use Test-NetConnection: it reports success for a bound port whose accept loop
    # is dead - measured on this suite's own mock. The raw connect does not lie.
    try {
        $c = [System.Net.Sockets.TcpClient]::new()
        $c.Connect([System.Net.IPAddress]::Loopback, $Port)
        $c.Close()
        return $true
    } catch { return $false }
}
function Clear-RuntimeMocks {
    # Test hygiene between e2e cases: whatever a case left behind (an unkillable-by-guards
    # port-less mock, a -NoAutoTeardown survivor) must not poison the next preflight.
    foreach ($o in @(Get-CimInstance Win32_Process -Filter "Name='llama-server.exe'" |
            Where-Object { $_.ExecutablePath -like ($mockDir + '*') })) {
        Stop-Process -Id $o.ProcessId -Force -ErrorAction SilentlyContinue
    }
    Start-Sleep -Milliseconds 500
}
function Wait-ArmGone { param([string]$Tag, [int]$TimeoutSec)
    # Poll until every process the tag recorded (child, watcher, server) is dead.
    $end = (Get-Date).AddSeconds($TimeoutSec)
    while ((Get-Date) -lt $end) {
        $pidsFile = Join-Path $logDir "$Tag.pids.txt"
        if (-not (Test-Path -LiteralPath $pidsFile)) { return $true }
        $aliveIds = @()
        foreach ($line in (Get-Content -LiteralPath $pidsFile -ErrorAction SilentlyContinue)) {
            if ($line -match '^\s*(child|watcher)=(\d+)\s*$') {
                if (Get-Process -Id ([int]$Matches[2]) -ErrorAction SilentlyContinue) { $aliveIds += [int]$Matches[2] }
            }
            elseif ($line -match '^\s*server=(\d+)\s*$') {
                if (Get-Process -Id ([int]$Matches[1]) -ErrorAction SilentlyContinue) { $aliveIds += [int]$Matches[1] }
            }
        }
        if ($aliveIds.Count -eq 0) { return $true }
        Start-Sleep -Seconds 2
    }
    return $false
}
function Invoke-Arm { param([string[]]$Extra)
    # One arm run against the copy of arm.ps1 in this directory; returns the raw transcript.
    # The transcript goes through FILES, never a pipe: arm.ps1 starts its child with redirected
    # output, and Start-Process then creates it with handle inheritance - the child (and the
    # llama-server under it) inherit arm.ps1's own stdout. When the arm stays up
    # (-NoAutoTeardown) a piped caller (`& arm.ps1 | Out-String`, an ssh pipeline) waits for an
    # EOF that only comes when the server dies: the suite hung forever at case10 this way.
    $tagIdx = [Array]::IndexOf($Extra, '-Tag')
    $t = if ($tagIdx -ge 0) { $Extra[$tagIdx + 1] } else { 'arm' }
    $p = Start-ArmAsync -Tag $t -Extra $Extra
    if (-not $p.WaitForExit(240000)) { Stop-Process -Id $p.Id -Force -ErrorAction SilentlyContinue; return "(arm.ps1 did not exit within 240 s)" }
    $o = Get-Content -Raw -LiteralPath (Join-Path $logDir "$t.stdout.txt") -ErrorAction SilentlyContinue
    $e = Get-Content -Raw -LiteralPath (Join-Path $logDir "$t.stderr.txt") -ErrorAction SilentlyContinue
    "$o$e"
}
function Common-ArmArgs { param([string]$Tag, [string]$MinFreeGB = '0', [string]$HeadroomGB = '0')
    @(
        '-Runtime', $rtArm
        '-ArgsFile', (Join-Path $logDir "$Tag.args")
        '-Port', "$probePort"
        '-Tag', $Tag
        '-LogDir', $logDir
        # colon form: under -File a bare "-999999" token would parse as a parameter name
        "-MinFreeGB:$MinFreeGB", '-MaxAdapterGB', '999', "-HeadroomGB:$HeadroomGB"
        '-LoadTimeoutMin', '1', '-IdleSoakSec', '0'
    )
}
function Start-ArmAsync { param([string]$Tag, [string[]]$Extra)
    # Same run as Invoke-Arm, but detached so the test can act WHILE the arm is up (write a
    # marker mid-hold, start a production stand-in mid-load). Returns the arm's process.
    $argLine = (@('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', $armScript) + $Extra |
        ForEach-Object { '"' + $_ + '"' }) -join ' '
    $p = Start-Process -FilePath 'powershell.exe' -ArgumentList $argLine -WindowStyle Hidden -PassThru `
        -RedirectStandardOutput (Join-Path $logDir "$Tag.stdout.txt") `
        -RedirectStandardError (Join-Path $logDir "$Tag.stderr.txt")
    $null = $p.Handle   # .NET quirk: without touching Handle now, ExitCode reads back empty later
    $p
}
function Wait-File { param([string]$Path, [int]$TimeoutSec)
    $end = (Get-Date).AddSeconds($TimeoutSec)
    while ((Get-Date) -lt $end) { if (Test-Path -LiteralPath $Path) { return $true }; Start-Sleep -Milliseconds 250 }
    return $false
}
function Write-ServingArgs { param([string]$Tag)
    # --port is what arm.ps1 discovers and guards by; --serve is what makes the mock bind so
    # the load probe gets its 200 and the arm goes ready.
    Set-Content -LiteralPath (Join-Path $logDir "$Tag.args") -Encoding ASCII -Value @(
        '-m', (Join-Path $mockDir 'mock-server.cs'),
        '--port', "$probePort", '--serve', "$probePort"
    )
}

# The kill-arm cases leave their production/legacy stand-ins up (case5 needs them). arm.ps1's
# preflight rightly refuses to start next to ANY resident llama-server, so clear them first.
foreach ($m in $prod, $legacy) { if ($m) { Stop-Process -Id $m.Id -Force -ErrorAction SilentlyContinue } }
Clear-RuntimeMocks

# --- case 8: arm.ps1 must accept the preflight overrides (DryRun passes on a busy box) -----------
Write-ServingArgs -Tag 'tt8'
$dryOut = Invoke-Arm -Extra ((Common-ArmArgs 'tt8') + @('-DryRun'))
if ($dryOut -match 'DRY RUN: preflight passed') { $results += 'PASS case8_arm_accepts_maxadaptergb_headroomb_preflight_overrides' }
else { $results += "FAIL case8_arm_accepts_maxadaptergb_headroomb_preflight_overrides: no dry-run pass on this box. Output: $dryOut" }

# --- case 9: server never discovered -> record still written, the whole child tree still stopped -
# A --port-less mock cannot be discovered (no port token to guard), so pids.txt carries a
# server=? line. The handoff warning lives here: the failure path must NOT skip the record, and
# it must not leak processes either - the child, the watchdog, and the arm's own unrecorded
# llama-server (ownership proven by parentage: production llama-swap servers are never children
# of the arm's child script) must all be gone when the arm exits.
Set-Content -LiteralPath (Join-Path $logDir 'tt9.args') -Encoding ASCII -Value @(
    '-m', (Join-Path $mockDir 'mock-server.cs')
)
$t9 = Get-Date
$out9 = Invoke-Arm -Extra (Common-ArmArgs 'tt9')
$elapsed9 = [math]::Round(((Get-Date) - $t9).TotalSeconds)
$record9 = Test-Path -LiteralPath (Join-Path $logDir 'tt9.record.md')
$gone9 = Wait-ArmGone -Tag 'tt9' -TimeoutSec 15
$leftover9 = @(Get-CimInstance Win32_Process -Filter "Name='llama-server.exe'" |
    Where-Object { $_.ExecutablePath -like ($rtArm + '\*') })
if ($record9 -and $gone9 -and $leftover9.Count -eq 0) {
    $results += 'PASS case9_server_not_found_writes_record_then_stops_child_watchdog_and_unrecorded_server'
} else {
    $results += "FAIL case9_server_not_found_writes_record_then_stops_child_watchdog_and_unrecorded_server: elapsed=${elapsed9}s record=$record9 pidsGone=$gone9 leftoverServers=$($leftover9.Count). Output: $out9"
}
Clear-RuntimeMocks

# --- case 10: -NoAutoTeardown keeps the arm up, and kill-arm still tears it down in one command ---
# The escape hatch for "I want to bench this arm myself": after the record, the serving mock,
# the child and the watchdog must all still be up; then kill-arm.ps1 -Tag must stop all three.
Write-ServingArgs -Tag 'tt10'
$t10 = Get-Date
$out10 = Invoke-Arm -Extra ((Common-ArmArgs 'tt10') + @('-NoAutoTeardown'))
$elapsed10 = [math]::Round(((Get-Date) - $t10).TotalSeconds)
$srvId10 = 0
foreach ($l in (Get-Content -LiteralPath (Join-Path $logDir 'tt10.pids.txt') -ErrorAction SilentlyContinue)) {
    if ($l -match '^\s*server=(\d+)\s*$') { $srvId10 = [int]$Matches[1] }
}
# case 10a: the recorded server= must be the real PID of the arm's llama-server. Before this
# case existed, arm.ps1 wrote "server=" with an EMPTY value (it read .Id off the CIM object
# Get-ArmServerProcess returns, which only has .ProcessId), so kill-arm never had a server to
# stop - every arm on the bench box leaked its llama-server to the operator.
$srv10 = if ($srvId10 -gt 0) { Get-CimInstance Win32_Process -Filter "ProcessId=$srvId10" } else { $null }
if ($srv10 -and $srv10.ExecutablePath -like ($rtArm + '\*')) {
    $results += 'PASS case10a_arm_records_real_server_pid_in_pids_txt'
} else {
    $pidsText10 = (Get-Content -LiteralPath (Join-Path $logDir 'tt10.pids.txt') -ErrorAction SilentlyContinue) -join ' | '
    $results += "FAIL case10a_arm_records_real_server_pid_in_pids_txt: pids.txt = $pidsText10"
}
$up10 = ($srvId10 -gt 0) -and (Get-Process -Id $srvId10 -ErrorAction SilentlyContinue) -and (Test-PortOpen $probePort)
if ($up10) {
    $results += 'PASS case10_noautoteardown_keeps_recorded_server_child_and_watchdog_up'
} else {
    $results += "FAIL case10_noautoteardown_keeps_recorded_server_child_and_watchdog_up: arm torn down despite the flag (serverPid=$srvId10). Output: $out10"
}
$kd10 = Run-KillArm -Tag 'tt10'
$dead10 = -not (Get-Process -Id $srvId10 -ErrorAction SilentlyContinue)
for ($i = 0; $i -lt 8 -and -not $dead10; $i++) { Start-Sleep -Seconds 1; $dead10 = -not (Get-Process -Id $srvId10 -ErrorAction SilentlyContinue) }
$lockGone10 = -not (Test-Path -LiteralPath (Join-Path $logDir 'tt10.lock'))
if ($dead10 -and $lockGone10) { $results += 'PASS case10b_killarm_tears_down_noautoteardown_arm_in_one_command' }
else { $results += "FAIL case10b_killarm_tears_down_noautoteardown_arm_in_one_command: serverDead=$dead10 lockGone=$lockGone10. kill-arm said: $kd10" }
for ($i = 0; $i -lt 10 -and (Test-PortOpen $probePort); $i++) { Start-Sleep -Seconds 2 }
Clear-RuntimeMocks

# --- case 11: auto-teardown is ON by default - hold expiry frees the GPUs, no operator needed -----
# The entire point of the feature: an operator who walks away must NOT keep the GPUs hostage.
# With a 1-minute hold and no benchdone marker ever written, the arm must stop its own child,
# watchdog and recorded server by itself - and the whole run must complete in well under the
# 30-minute hold budget a forgotten arm would otherwise sit in.
if (Test-PortOpen $probePort) {
    # Case10's server outlived kill-arm (or the OS is slow releasing the socket): starting a
    # fresh serving mock on the same port would fail to bind and corrupt this case. Skip loudly.
    $results += 'SKIP case11_probe_port_still_open_after_case10'
} else {
    Write-ServingArgs -Tag 'tt11'
    $out11 = Invoke-Arm -Extra ((Common-ArmArgs 'tt11') + @('-TeardownHoldMin', '1'))
    $gone11 = Wait-ArmGone -Tag 'tt11' -TimeoutSec 15
    $post11 = -not (Test-PortOpen $probePort)
    $lockGone11 = -not (Test-Path -LiteralPath (Join-Path $logDir 'tt11.lock'))
    $record11 = Test-Path -LiteralPath (Join-Path $logDir 'tt11.record.md')
    if ($gone11 -and $post11 -and $lockGone11 -and $record11) {
        $results += 'PASS case11_default_on_hold_expiry_tears_down_child_watcher_server_and_removes_lock'
    } else {
        $results += "FAIL case11_default_on_hold_expiry_tears_down_child_watcher_server_and_removes_lock: allGone=$gone11 portFreed=$post11 lockGone=$lockGone11 record=$record11. Output: $out11"
    }
    Clear-RuntimeMocks
}

# --- case 12: a benchdone marker releases the hold early - but only a FRESH one -------------------
# Bench finished? touch <tag>.benchdone and the arm exits within its poll interval (<=15 s)
# instead of idling out the full hold on a warm GPU nobody is using. A marker left over from an
# earlier run of the same tag (re-runs after a failure reuse tags) must NOT end the new run's
# hold before anyone has benched it: the arm clears it at start. So: plant a stale marker, see
# the arm still holding 20 s after its record, then write a fresh marker and see it go.
if (Test-PortOpen $probePort) {
    $results += 'SKIP case12_probe_port_still_open_after_case11'
} else {
    Write-ServingArgs -Tag 'tt12'
    $marker12 = Join-Path $logDir 'tt12.benchdone'
    Set-Content -LiteralPath $marker12 -Value 'stale marker from an earlier tt12 run' -Encoding ASCII
    $arm12 = Start-ArmAsync -Tag 'tt12' -Extra ((Common-ArmArgs 'tt12') + @('-TeardownHoldMin', '10'))
    $rec12 = Wait-File -Path (Join-Path $logDir 'tt12.record.md') -TimeoutSec 90
    Start-Sleep -Seconds 20   # > one 15 s hold poll: a stale marker would have released by now
    $heldDespiteStale12 = $rec12 -and -not $arm12.HasExited
    Set-Content -LiteralPath $marker12 -Value 'bench done' -Encoding ASCII
    $t12 = Get-Date
    $exited12 = $arm12.WaitForExit(40000)
    $release12 = [math]::Round(((Get-Date) - $t12).TotalSeconds)
    $gone12 = Wait-ArmGone -Tag 'tt12' -TimeoutSec 10
    if ($heldDespiteStale12) { $results += 'PASS case12a_stale_benchdone_from_earlier_run_does_not_end_hold' }
    else { $results += "FAIL case12a_stale_benchdone_from_earlier_run_does_not_end_hold: record=$rec12 armExited=$($arm12.HasExited). Output: $(Get-Content -Raw -LiteralPath (Join-Path $logDir 'tt12.stdout.txt') -ErrorAction SilentlyContinue)" }
    if ($heldDespiteStale12 -and $exited12 -and $gone12) {
        $results += "PASS case12b_fresh_benchdone_releases_hold_early (released ${release12}s after marker, hold was 600s)"
    } else {
        if (-not $arm12.HasExited) { Stop-Process -Id $arm12.Id -Force -ErrorAction SilentlyContinue }
        $results += "FAIL case12b_fresh_benchdone_releases_hold_early: exited=$exited12 allGone=$gone12 after ${release12}s"
    }
    Remove-Item -LiteralPath $marker12 -Force -ErrorAction SilentlyContinue
    Clear-RuntimeMocks
}

# --- case 13: watchdog kill BEFORE the record - record first, then teardown; production lives ---
# The handoff's warning case. The arm's server never answers (no --serve), and an impossible
# RAM floor makes the watchdog kill it within seconds - so the death happens before record.md
# exists. Required: record.md is written before the teardown runs and says the watchdog killed
# the arm; the arm exits non-zero (2 = never answered); everything it started is gone.
# A production stand-in (a llama-server from ANOTHER runtime dir, with the biggest working set
# on the box) starts while the arm is loading - exactly what llama-swap does on a live request.
# It must survive both the watchdog and the teardown: unrecorded servers are never touched.
$t13Floor = '999999'
$rtProdExe13 = Join-Path $rtProd 'llama-server.exe'
Set-Content -LiteralPath (Join-Path $logDir 'tt13.args') -Encoding ASCII -Value @(
    '-m', (Join-Path $mockDir 'mock-server.cs'), '--port', "$probePort"
)
$arm13 = Start-ArmAsync -Tag 'tt13' -Extra (Common-ArmArgs 'tt13' -MinFreeGB $t13Floor -HeadroomGB "-$t13Floor")
$prod13 = $null
if (Wait-File -Path (Join-Path $logDir 'tt13.pids.txt') -TimeoutSec 60) {
    $prod13 = Start-Process -FilePath $rtProdExe13 -ArgumentList @('--port', '9061', '--alloc-mb', '400') -WindowStyle Hidden -PassThru
}
$exited13 = $arm13.WaitForExit(150000)
if (-not $exited13) { Stop-Process -Id $arm13.Id -Force -ErrorAction SilentlyContinue }
$recPath13 = Join-Path $logDir 'tt13.record.md'
$tdPath13 = Join-Path $logDir 'tt13.teardown.log'
$record13 = Test-Path -LiteralPath $recPath13
$recText13 = if ($record13) { Get-Content -Raw -LiteralPath $recPath13 } else { '' }
$order13 = $record13 -and (Test-Path -LiteralPath $tdPath13) -and
    ((Get-Item -LiteralPath $recPath13).LastWriteTime -le (Get-Item -LiteralPath $tdPath13).CreationTime)
$names13 = $recText13 -match 'watchdog: available RAM fell'
$code13 = if ($exited13) { $arm13.ExitCode } else { 'hung' }
$gone13 = Wait-ArmGone -Tag 'tt13' -TimeoutSec 15
$prodAlive13 = $prod13 -and (Mock-Alive -Id $prod13.Id)
if ($order13 -and $names13 -and $code13 -eq 2 -and $gone13) {
    $results += 'PASS case13a_watchdog_kill_before_record_writes_record_first_then_tears_down'
} else {
    $results += "FAIL case13a_watchdog_kill_before_record_writes_record_first_then_tears_down: record=$record13 recordBeforeTeardown=$order13 recordNamesKill=$names13 exit=$code13 allGone=$gone13. watchdog.log: $(Get-Content -Raw -LiteralPath (Join-Path $logDir 'tt13.watchdog.log') -ErrorAction SilentlyContinue)"
}
if ($prodAlive13) { $results += 'PASS case13b_production_server_started_mid_arm_survives_watchdog_and_teardown' }
else { $results += "FAIL case13b_production_server_started_mid_arm_survives_watchdog_and_teardown: prodStarted=$([bool]$prod13). watchdog.log: $(Get-Content -Raw -LiteralPath (Join-Path $logDir 'tt13.watchdog.log') -ErrorAction SilentlyContinue)" }
if ($prod13) { Stop-Process -Id $prod13.Id -Force -ErrorAction SilentlyContinue }
Clear-RuntimeMocks

# --- cleanup: never leave mock servers behind ---------------------------------------------------
$orphans = @(Get-CimInstance Win32_Process -Filter "Name='llama-server.exe'" |
    Where-Object { $_.CommandLine -like "*$mockDir*" -or $_.ExecutablePath -like ($mockDir + '*') })
foreach ($o in $orphans) { Stop-Process -Id $o.ProcessId -Force -ErrorAction SilentlyContinue }
Remove-Item -LiteralPath $mockDir -Recurse -Force -ErrorAction SilentlyContinue

# --- report -------------------------------------------------------------------
$results | ForEach-Object { $_ }
$out1, $out2, $out3, $out4 | ForEach-Object { "--- kill-arm output ---`n$_" } | Out-File -FilePath (Join-Path $env:TEMP 'kill-arm-test-output.txt') -Encoding UTF8
if (@($results | Where-Object { $_ -like 'FAIL*' }).Count -gt 0) { 'RESULT: FAIL'; exit 1 }
'RESULT: PASS'
exit 0
