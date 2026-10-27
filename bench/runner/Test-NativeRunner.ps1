# Test-NativeRunner.ps1 - CPU-only acceptance tests for Invoke-NativeCommand.ps1 and GpuTestLock.ps1.
#
# Why this exists (STEP-000 / CHECK-100):
#   The acceptance criterion is not "the script parses". It is that a runner behaves correctly
#   on the failures that actually happen on this box: a build that exits nonzero, a build that
#   hangs and leaves children behind, a path with spaces in it, two tests racing for the same
#   GPU, and a production server that must survive every cleanup path.
#
#   Everything here runs on CPU with tiny command shells. No model weights, no GPU work, no
#   downloads. A pass here does NOT qualify the Windows runner against real Strata builds -
#   it qualifies the runner's own contract. The plan is explicit that a Linux/WSL result cannot
#   be reported as a Windows pass, and by the same token this file is not a GPU result.
#
# Usage:
#   powershell.exe -NoProfile -ExecutionPolicy Bypass -File Test-NativeRunner.ps1 [-KeepArtifacts]
#
# Exit code 0 = all cases passed, 1 = at least one failed, 4 = harness error.

[CmdletBinding()]
param(
    [switch]$KeepArtifacts
)

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'

$here = $PSScriptRoot
$runner = Join-Path $here 'Invoke-NativeCommand.ps1'
$locker = Join-Path $here 'GpuTestLock.ps1'
$pwshExe = (Get-Process -Id $PID).Path

if (-not (Test-Path -LiteralPath $runner)) { Write-Error "missing $runner"; exit 4 }
if (-not (Test-Path -LiteralPath $locker)) { Write-Error "missing $locker"; exit 4 }

$workRoot = Join-Path ([System.IO.Path]::GetTempPath()) ("b70-runner-tests-" + (Get-Date).ToUniversalTime().ToString('yyyyMMddTHHmmssZ'))
New-Item -ItemType Directory -Path $workRoot -Force | Out-Null

$cases = New-Object System.Collections.ArrayList
function Add-Case {
    param([string]$Name, [string]$Status, [string]$Detail, [string]$Evidence)
    [void]$cases.Add([ordered]@{ name = $Name; status = $Status; detail = $Detail; evidence = $Evidence })
    $colour = switch ($Status) { 'PASS' { 'Green' } 'FAIL' { 'Red' } default { 'Yellow' } }
    Write-Host ("[{0}] {1} - {2}" -f $Status, $Name, $Detail) -ForegroundColor $colour
}

function Invoke-Json {
    param([string]$ScriptPath, [string[]]$ScriptArgs)
    $argv = @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', $ScriptPath) + $ScriptArgs
    $out = & $pwshExe @argv 2>&1 | Out-String
    $code = $LASTEXITCODE
    $json = $null
    try { $json = $out | ConvertFrom-Json } catch { }
    return [ordered]@{ exit = $code; json = $json; raw = $out }
}

# Helper: build the -ArgumentsJson payload. Under `powershell.exe -File` an array parameter cannot
# be bound from separate tokens, so argv travels as one JSON value.
# Windows PowerShell 5.1's ConvertTo-Json has no -AsArray (that is PS 7+), and a single-element
# array collapses to a bare string, so the brackets are assembled explicitly.
function New-ArgsJson {
    param([string[]]$Items, [string]$Path)
    $encoded = @()
    foreach ($item in @($Items)) {
        $encoded += (ConvertTo-Json -InputObject ([string]$item) -Compress)
    }
    $json = '[' + ($encoded -join ',') + ']'
    if ($Path) {
        Set-Content -LiteralPath $Path -Value $json -Encoding UTF8
        return $Path
    }
    return $json
}

# A "child" script the runner and the lock can start. Kept as a real file so paths-with-spaces
# is exercised for the executable too, not only the working directory.
$childScript = @'
param([string]$Mode = 'ok', [int]$SleepSeconds = 0, [string]$OutFile = '')
switch ($Mode) {
    'ok'      { Write-Output 'child: ok'; exit 0 }
    'fail'    { Write-Output 'child: about to fail'; [Console]::Error.WriteLine('child: deliberate failure'); exit 7 }
    'sleep'   { Write-Output 'child: sleeping'; Start-Sleep -Seconds $SleepSeconds; Write-Output 'child: woke up'; exit 0 }
    'spawn'   {
        # Spawn a grandchild, report its pid, then sleep. Used to prove tree cleanup.
        $self = (Get-Process -Id $PID).Path
        $grand = Start-Process -FilePath $self -ArgumentList @('-NoProfile','-Command','Start-Sleep -Seconds 600') -PassThru
        Write-Output "grandchild=$($grand.Id)"
        Start-Sleep -Seconds $SleepSeconds
        exit 0
    }
    default   { exit 0 }
}
'@
$childPath = Join-Path $workRoot 'child.ps1'
Set-Content -LiteralPath $childPath -Value $childScript -Encoding UTF8

# ---------------------------------------------------------------------------------------------
# 1. Success: exit 0, streams captured, structured result on disk.
# ---------------------------------------------------------------------------------------------
try {
    $dir = Join-Path $workRoot 'case-success'
    $r = Invoke-Json -ScriptPath $runner -ScriptArgs @(
        '-FilePath', $pwshExe,
        '-ArgumentsJsonPath', (New-ArgsJson -Items @('-File', $childPath, '-Mode', 'ok') -Path (Join-Path $workRoot 'args-success.json')),
        '-WorkingDirectory', $workRoot,
        '-RunDirectory', $dir,
        '-Label', 'success',
        '-EmitJson'
    )
    $res = $r.json
    $stdoutFile = if ($res) { $res.stdout_path } else { $null }
    $stdoutText = if ($stdoutFile -and (Test-Path -LiteralPath $stdoutFile)) { Get-Content -LiteralPath $stdoutFile -Raw } else { '' }
    if ($r.exit -eq 0 -and $res.outcome -eq 'PASS' -and $res.exit_code -eq 0 -and $stdoutText -match 'child: ok') {
        Add-Case -Name 'success-exit-zero' -Status 'PASS' -Detail 'PASS/exit 0, stdout captured to file' -Evidence $dir
    } else {
        Add-Case -Name 'success-exit-zero' -Status 'FAIL' -Detail ("exit=$($r.exit) outcome=$($res.outcome) child_exit=$($res.exit_code) stdout=$($stdoutText.Trim())") -Evidence $dir
    }
} catch {
    Add-Case -Name 'success-exit-zero' -Status 'FAIL' -Detail $_.Exception.Message -Evidence $workRoot
}

# ---------------------------------------------------------------------------------------------
# 2. Nonzero exit: the child's own code must survive, and it must NOT be reported as a timeout.
# ---------------------------------------------------------------------------------------------
try {
    $dir = Join-Path $workRoot 'case-nonzero'
    $r = Invoke-Json -ScriptPath $runner -ScriptArgs @(
        '-FilePath', $pwshExe,
        '-ArgumentsJsonPath', (New-ArgsJson -Items @('-File', $childPath, '-Mode', 'fail') -Path (Join-Path $workRoot 'args-nonzero.json')),
        '-WorkingDirectory', $workRoot,
        '-RunDirectory', $dir,
        '-Label', 'nonzero',
        '-EmitJson'
    )
    $res = $r.json
    $stderrText = if ($res -and (Test-Path -LiteralPath $res.stderr_path)) { Get-Content -LiteralPath $res.stderr_path -Raw } else { '' }
    if ($r.exit -eq 2 -and $res.outcome -eq 'FAIL' -and $res.exit_code -eq 7 -and -not $res.timed_out) {
        Add-Case -Name 'nonzero-exit-propagates' -Status 'PASS' -Detail 'child exit 7 preserved as FAIL, not confused with timeout' -Evidence $dir
    } else {
        Add-Case -Name 'nonzero-exit-propagates' -Status 'FAIL' -Detail ("exit=$($r.exit) outcome=$($res.outcome) child_exit=$($res.exit_code) timed_out=$($res.timed_out)") -Evidence $dir
    }
    if ($stderrText -match 'deliberate failure') {
        Add-Case -Name 'nonzero-stderr-captured' -Status 'PASS' -Detail 'child stderr written to its own file' -Evidence $res.stderr_path
    } else {
        Add-Case -Name 'nonzero-stderr-captured' -Status 'FAIL' -Detail ("stderr file did not contain the child's message: '$($stderrText.Trim())'") -Evidence $dir
    }
} catch {
    Add-Case -Name 'nonzero-exit-propagates' -Status 'FAIL' -Detail $_.Exception.Message -Evidence $workRoot
}

# ---------------------------------------------------------------------------------------------
# 3. Timeout with child cleanup: the build hangs, the runner kills it, and the grandchild dies.
# ---------------------------------------------------------------------------------------------
try {
    $dir = Join-Path $workRoot 'case-timeout'
    $r = Invoke-Json -ScriptPath $runner -ScriptArgs @(
        '-FilePath', $pwshExe,
        '-ArgumentsJsonPath', (New-ArgsJson -Items @('-File', $childPath, '-Mode', 'spawn', '-SleepSeconds', '600') -Path (Join-Path $workRoot 'args-timeout.json')),
        '-WorkingDirectory', $workRoot,
        '-RunDirectory', $dir,
        '-Label', 'timeout',
        '-TimeoutSeconds', '6',
        '-EmitJson'
    )
    $res = $r.json
    $grandPid = $null
    if ($res -and (Test-Path -LiteralPath $res.stdout_path)) {
        $text = Get-Content -LiteralPath $res.stdout_path -Raw
        if ($text -match 'grandchild=(\d+)') { $grandPid = [int]$Matches[1] }
    }
    $grandAlive = if ($grandPid) { [bool](Get-Process -Id $grandPid -ErrorAction SilentlyContinue) } else { $null }
    if ($res -and $grandAlive) {
        # The tree killer may need a moment; re-check once.
        Start-Sleep -Milliseconds 800
        $grandAlive = [bool](Get-Process -Id $grandPid -ErrorAction SilentlyContinue)
    }
    $timeoutOk = ($r.exit -eq 3) -and ($res.outcome -eq 'TIMEOUT') -and ($res.timed_out -eq $true)
    $cleanupOk = ($null -ne $grandPid) -and (-not $grandAlive)
    if ($timeoutOk -and $cleanupOk) {
        Add-Case -Name 'timeout-kills-tree' -Status 'PASS' -Detail ("TIMEOUT after 6s; grandchild $grandPid reaped; killed=$($res.killed_pids -join ',')") -Evidence $dir
    } else {
        Add-Case -Name 'timeout-kills-tree' -Status 'FAIL' -Detail ("timeout_ok=$timeoutOk cleanup_ok=$cleanupOk grandchild=$grandPid alive=$grandAlive exit=$($r.exit)") -Evidence $dir
    }
} catch {
    Add-Case -Name 'timeout-kills-tree' -Status 'FAIL' -Detail $_.Exception.Message -Evidence $workRoot
}

# ---------------------------------------------------------------------------------------------
# 4. Paths with spaces: both the working directory and the executable live under "with space".
# ---------------------------------------------------------------------------------------------
try {
    $spacedRoot = Join-Path $workRoot 'dir with space'
    New-Item -ItemType Directory -Path $spacedRoot -Force | Out-Null
    $spacedChild = Join-Path $spacedRoot 'child with space.ps1'
    Set-Content -LiteralPath $spacedChild -Value @'
Write-Output "spaced child ran in: $($PWD.Path)"
Write-Output "arg was: $($args -join '|')"
exit 0
'@ -Encoding UTF8
    $dir = Join-Path $spacedRoot 'run out'
    $r = Invoke-Json -ScriptPath $runner -ScriptArgs @(
        '-FilePath', $pwshExe,
        '-ArgumentsJsonPath', (New-ArgsJson -Items @('-File', $spacedChild, '-ValueContaining Spaces') -Path (Join-Path $spacedRoot 'args spaces.json')),
        '-WorkingDirectory', $spacedRoot,
        '-RunDirectory', $dir,
        '-Label', 'spaces',
        '-EmitJson'
    )
    $res = $r.json
    $stdoutText = if ($res -and (Test-Path -LiteralPath $res.stdout_path)) { Get-Content -LiteralPath $res.stdout_path -Raw } else { '' }
    # The argument must arrive as ONE element, spaces and all - not split into two words.
    if ($r.exit -eq 0 -and $stdoutText -match 'arg was: -ValueContaining Spaces') {
        Add-Case -Name 'paths-with-spaces' -Status 'PASS' -Detail 'spaced cwd, spaced exe path, spaced run dir; argument kept as one element' -Evidence $dir
    } else {
        Add-Case -Name 'paths-with-spaces' -Status 'FAIL' -Detail ("exit=$($r.exit) stdout=$($stdoutText.Trim())") -Evidence $dir
    }
} catch {
    Add-Case -Name 'paths-with-spaces' -Status 'FAIL' -Detail $_.Exception.Message -Evidence $workRoot
}

# ---------------------------------------------------------------------------------------------
# 5. Argument injection is impossible: a quote in an argument stays data, it does not break out.
# ---------------------------------------------------------------------------------------------
try {
    $dir = Join-Path $workRoot 'case-injection'
    $nasty = 'a" & echo INJECTED > pwned.txt & "b'
    $r = Invoke-Json -ScriptPath $runner -ScriptArgs @(
        '-FilePath', $pwshExe,
        '-ArgumentsJsonPath', (New-ArgsJson -Items @('-File', $childPath, '-Mode', 'ok', '-OutFile', $nasty) -Path (Join-Path $workRoot 'args-injection.json')),
        '-WorkingDirectory', $workRoot,
        '-RunDirectory', $dir,
        '-Label', 'injection',
        '-EmitJson'
    )
    $pwnedPath = Join-Path $workRoot 'pwned.txt'
    if ($r.exit -eq 0 -and -not (Test-Path -LiteralPath $pwnedPath)) {
        Add-Case -Name 'no-shell-injection' -Status 'PASS' -Detail 'quoted payload stayed an argument; no side-effect file created' -Evidence $dir
    } else {
        Add-Case -Name 'no-shell-injection' -Status 'FAIL' -Detail ("exit=$($r.exit) pwned_exists=$(Test-Path -LiteralPath $pwnedPath)") -Evidence $dir
    }
} catch {
    Add-Case -Name 'no-shell-injection' -Status 'FAIL' -Detail $_.Exception.Message -Evidence $workRoot
}

# ---------------------------------------------------------------------------------------------
# 6. Sentinel survival: a process we did NOT start must survive every cleanup path.
# ---------------------------------------------------------------------------------------------
$sentinel = $null
try {
    $sentinel = Start-Process -FilePath $pwshExe -ArgumentList @('-NoProfile', '-Command', 'Start-Sleep -Seconds 300') -PassThru
    Start-Sleep -Milliseconds 400

    $dir = Join-Path $workRoot 'case-sentinel'
    $r = Invoke-Json -ScriptPath $runner -ScriptArgs @(
        '-FilePath', $pwshExe,
        '-ArgumentsJsonPath', (New-ArgsJson -Items @('-File', $childPath, '-Mode', 'sleep', '-SleepSeconds', '600') -Path (Join-Path $workRoot 'args-sentinel.json')),
        '-WorkingDirectory', $workRoot,
        '-RunDirectory', $dir,
        '-Label', 'sentinel',
        '-TimeoutSeconds', '5',
        '-EmitJson'
    )
    Start-Sleep -Milliseconds 600
    $sentinelAlive = [bool](Get-Process -Id $sentinel.Id -ErrorAction SilentlyContinue)
    if ($sentinelAlive) {
        Add-Case -Name 'sentinel-survives-cleanup' -Status 'PASS' -Detail ("unrelated PID $($sentinel.Id) still running after a timed-out kill") -Evidence $dir
    } else {
        Add-Case -Name 'sentinel-survives-cleanup' -Status 'FAIL' -Detail "sentinel PID $($sentinel.Id) was killed by cleanup" -Evidence $dir
    }
} catch {
    Add-Case -Name 'sentinel-survives-cleanup' -Status 'FAIL' -Detail $_.Exception.Message -Evidence $workRoot
} finally {
    if ($sentinel) { Stop-Process -Id $sentinel.Id -Force -ErrorAction SilentlyContinue }
}

# ---------------------------------------------------------------------------------------------
# 7. Competing lock acquisition: first holder wins, second gets BUSY and is not queued.
# ---------------------------------------------------------------------------------------------
try {
    $lockPath = Join-Path $workRoot 'gpu-test.lock'
    $first = Invoke-Json -ScriptPath $locker -ScriptArgs @(
        '-Action', 'Acquire', '-LockPath', $lockPath, '-Owner', 'case-7-first', '-Purpose', 'competing-lock-test', '-EmitJson'
    )
    # The first caller's process has exited by now, so its lease is stale by design. To test a
    # LIVE competing acquisition we hold one from this process, then ask a child to acquire.
    $holderScript = @'
param([string]$Locker, [string]$LockPath, [int]$MyPid = $PID)
$lease = & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $Locker -Action Acquire -LockPath $LockPath -Owner 'live-holder' -Purpose 'hold-for-compete' -HolderPid $MyPid -EmitJson | Out-String
Write-Output $lease
Start-Sleep -Seconds 14
'@
    $holderPath = Join-Path $workRoot 'holder.ps1'
    Set-Content -LiteralPath $holderPath -Value $holderScript -Encoding UTF8
    $holder = Start-Process -FilePath $pwshExe -ArgumentList @('-NoProfile','-ExecutionPolicy','Bypass','-File',$holderPath,$locker,$lockPath) -PassThru -RedirectStandardOutput (Join-Path $workRoot 'holder.out.txt')
    Start-Sleep -Seconds 4   # let it acquire

    $second = Invoke-Json -ScriptPath $locker -ScriptArgs @(
        '-Action', 'Acquire', '-LockPath', $lockPath, '-Owner', 'case-7-second', '-Purpose', 'should-be-refused', '-EmitJson'
    )
    $busyOk = ($second.exit -eq 10) -and ($second.json.outcome -eq 'BUSY')
    if ($busyOk) {
        Add-Case -Name 'competing-lock-busy' -Status 'PASS' -Detail ("second acquire refused with BUSY while a live holder held the lease") -Evidence $lockPath
    } else {
        Add-Case -Name 'competing-lock-busy' -Status 'FAIL' -Detail ("exit=$($second.exit) outcome=$($second.json.outcome)") -Evidence $lockPath
    }
    Stop-Process -Id $holder.Id -Force -ErrorAction SilentlyContinue
    Start-Sleep -Milliseconds 500
} catch {
    Add-Case -Name 'competing-lock-busy' -Status 'FAIL' -Detail $_.Exception.Message -Evidence $workRoot
}

# ---------------------------------------------------------------------------------------------
# 8. Stale lease is recoverable, and a live lease is not broken by -Break.
# ---------------------------------------------------------------------------------------------
try {
    $lockPath = Join-Path $workRoot 'gpu-stale.lock'
    $acquired = Invoke-Json -ScriptPath $locker -ScriptArgs @(
        '-Action', 'Acquire', '-LockPath', $lockPath, '-Owner', 'stale-test', '-Purpose', 'stale-recovery', '-HolderPid', $PID, '-EmitJson'
    )
    # The lease names THIS test process, which is very much alive - so first prove a live lease
    # cannot be broken out from under it.
    $liveBreak = Invoke-Json -ScriptPath $locker -ScriptArgs @('-Action', 'Break', '-LockPath', $lockPath, '-EmitJson')
    $liveStatus = Invoke-Json -ScriptPath $locker -ScriptArgs @('-Action', 'Status', '-LockPath', $lockPath, '-EmitJson')
    if ($liveBreak.json.outcome -eq 'REFUSED' -and $liveStatus.json.outcome -eq 'HELD') {
        Add-Case -Name 'live-lease-not-breakable' -Status 'PASS' -Detail 'Break refused while the recorded holder was alive' -Evidence $lockPath
    } else {
        Add-Case -Name 'live-lease-not-breakable' -Status 'FAIL' -Detail ("break=$($liveBreak.json.outcome) status=$($liveStatus.json.outcome)") -Evidence $lockPath
    }

    # Now make a genuinely stale lease: release the live one we hold, then let a short-lived
    # child acquire a lease naming itself and exit, so the holder is gone while the file remains.
    $released = Invoke-Json -ScriptPath $locker -ScriptArgs @('-Action', 'Release', '-LockPath', $lockPath, '-HolderPid', $PID, '-EmitJson')
    $shortHolder = @'
param([string]$Locker, [string]$LockPath)
& powershell.exe -NoProfile -ExecutionPolicy Bypass -File $Locker -Action Acquire -LockPath $LockPath -Owner 'dead-holder' -Purpose 'stale-recovery' -HolderPid $PID -EmitJson | Out-Null
'@
    $shortPath = Join-Path $workRoot 'short-holder.ps1'
    Set-Content -LiteralPath $shortPath -Value $shortHolder -Encoding UTF8
    $shortProc = Start-Process -FilePath $pwshExe -ArgumentList @('-NoProfile','-ExecutionPolicy','Bypass','-File',$shortPath,$locker,$lockPath) -PassThru -Wait

    $status = Invoke-Json -ScriptPath $locker -ScriptArgs @('-Action', 'Status', '-LockPath', $lockPath, '-EmitJson')
    $break = Invoke-Json -ScriptPath $locker -ScriptArgs @('-Action', 'Break', '-LockPath', $lockPath, '-EmitJson')
    $after = Invoke-Json -ScriptPath $locker -ScriptArgs @('-Action', 'Status', '-LockPath', $lockPath, '-EmitJson')
    if ($status.json.outcome -eq 'STALE' -and $break.json.outcome -eq 'BROKEN' -and $after.json.outcome -eq 'FREE') {
        Add-Case -Name 'stale-lease-recovery' -Status 'PASS' -Detail 'dead holder -> STALE -> Break -> FREE' -Evidence $lockPath
    } else {
        Add-Case -Name 'stale-lease-recovery' -Status 'FAIL' -Detail ("status=$($status.json.outcome) break=$($break.json.outcome) after=$($after.json.outcome)") -Evidence $lockPath
    }
} catch {
    Add-Case -Name 'stale-lease-recovery' -Status 'FAIL' -Detail $_.Exception.Message -Evidence $workRoot
}

# ---------------------------------------------------------------------------------------------
# 9. Missing working directory is an explicit ERROR, not a silent PASS.
# ---------------------------------------------------------------------------------------------
try {
    $dir = Join-Path $workRoot 'case-badcwd'
    $missing = Join-Path $workRoot 'this-directory-does-not-exist'
    $r = Invoke-Json -ScriptPath $runner -ScriptArgs @(
        '-FilePath', $pwshExe,
        '-ArgumentsJsonPath', (New-ArgsJson -Items @('-File', $childPath, '-Mode', 'ok') -Path (Join-Path $workRoot 'args-badcwd.json')),
        '-WorkingDirectory', $missing,
        '-RunDirectory', $dir,
        '-Label', 'badcwd',
        '-EmitJson'
    )
    if ($r.exit -eq 4 -and $r.json.outcome -eq 'ERROR' -and $r.json.error -match 'working directory does not exist') {
        Add-Case -Name 'missing-cwd-is-error' -Status 'PASS' -Detail 'absent cwd reported as ERROR, never PASS' -Evidence $dir
    } else {
        Add-Case -Name 'missing-cwd-is-error' -Status 'FAIL' -Detail ("exit=$($r.exit) outcome=$($r.json.outcome) error=$($r.json.error)") -Evidence $dir
    }
} catch {
    Add-Case -Name 'missing-cwd-is-error' -Status 'FAIL' -Detail $_.Exception.Message -Evidence $workRoot
}

# ---------------------------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------------------------
$passed = @($cases | Where-Object { $_.status -eq 'PASS' }).Count
$failed = @($cases | Where-Object { $_.status -eq 'FAIL' }).Count
$total = $cases.Count

$summary = [ordered]@{
    schema_version = 1
    label          = 'native-runner-mock-suite'
    host           = $env:COMPUTERNAME
    platform       = 'native-windows'
    powershell     = $PSVersionTable.PSVersion.ToString()
    started_root   = $workRoot
    total          = $total
    passed         = $passed
    failed         = $failed
    outcome        = if ($failed -eq 0) { 'PASS' } else { 'FAIL' }
    note           = 'CPU-only contract tests. Not a GPU result and not a qualification of real Strata builds.'
    cases          = $cases
}

$summaryPath = Join-Path $workRoot 'summary.json'
$summary | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $summaryPath -Encoding UTF8
Write-Host ''
Write-Host ("{0}/{1} cases passed ({2})" -f $passed, $total, $summary.outcome) -ForegroundColor $(if ($failed -eq 0) { 'Green' } else { 'Red' })
Write-Host "summary: $summaryPath"

if (-not $KeepArtifacts -and $failed -eq 0) {
    Write-Host "(artifacts kept anyway - the receipt is the point; pass -KeepArtifacts to silence this note)"
}

if ($failed -eq 0) { exit 0 } else { exit 1 }
