# arm.ps1 - run one llama.cpp SYCL arm on Windows, detached from the caller's session.
#
# Why this exists: hill-climb arms kept dying for reasons that were never the code under test.
#   - SSH sessions kill their child processes on disconnect, and WSL teardown kills interop
#     children (see ../hardware-and-windows-notes.md). Detaching is a mechanism, not a rule.
#   - Host RAM drains two different ways on this box (idle VRAM demotion, and silent WDDM spill
#     when a card does not fit). Neither is visible in the GPU counters alone, so the guard
#     watches available RAM and the ledger records both curves.
#   - Runtime directory names are not build identifiers, so every record carries file hashes.
#
# Invoke detached, never directly from an SSH session:
#   powershell.exe -NoProfile -Command "Invoke-WmiMethod -Class Win32_Process -Name Create \
#     -CommandLine 'powershell.exe -NoProfile -ExecutionPolicy Bypass -File C:\...\arm.ps1 ...'"
#
# Arguments one per line in -ArgsFile (no shell quoting needed; they are splatted).
#
# Lifecycle since 2026-10-21: the arm tears ITSELF down. record.md is ALWAYS written first
# (failure paths included - the handoff reads it), then the endpoint is held warm for
# -TeardownHoldMin (default 90; early release on <logdir>\<tag>.benchdone) so an external
# bench can use the warm model, then the arm stops its own child/watchdog/server with the
# same pid-reuse + --port guards as kill-arm.ps1. The GPUs are freed even if nobody remembers
# to run kill-arm. -NoAutoTeardown restores the old stay-up behavior; kill-arm still works in
# both modes.
param(
    [Parameter(Mandatory = $true)][string]$Runtime,
    [Parameter(Mandatory = $true)][string]$ArgsFile,
    [string[]]$Env = @(),
    [int]$Port = 9061,
    [Parameter(Mandatory = $true)][string]$Tag,
    [string]$LogDir = '',             # default: <scripts dir>\..\logs\arms (resolved below)
    [double]$MinFreeGB = 8,
    [double]$DemoteGB = 60,
    [int]$LoadTimeoutMin = 45,
    [int]$WatchMin = 0,
    [int]$IdleSoakSec = 240,
    # Preflight strictness, exposed as parameters so the mock-driven e2e tests
    # (test-arm-teardown.ps1) can run on any dev box. The bench box runs the strict defaults:
    # adapters above -MaxAdapterGB GB of resident VRAM mean the box is not idle, and the
    # box needs MinFreeGB + -HeadroomGB free because Maya-M peaks ~100 GB over the floor.
    [double]$MaxAdapterGB = 1.0,
    [double]$HeadroomGB = 65,
    # Auto-teardown: after record.md is written, hold the endpoint up this long for external
    # benches (squal/sbench), release early on <logdir>\<tag>.benchdone, then stop the arm's
    # own child/watchdog/server so the GPUs are freed without waiting on the operator.
    # -NoAutoTeardown restores the old stay-up behavior (kill-arm.ps1 then does the stopping).
    # Whatever happens, record.md is written BEFORE anything is stopped.
    [int]$TeardownHoldMin = 90,
    [switch]$NoAutoTeardown,
    [switch]$DryRun
)
# $PSScriptRoot is not reliably set inside param() defaults under Windows PowerShell 5.1.
if (-not $LogDir) { $LogDir = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\logs\arms')) }

# Deliberately NOT 'Stop': this script drives native commands (llama-server) and long waits, and
# in PowerShell 5.1 a native command's stderr under 2>&1 becomes an ErrorRecord that 'Stop'
# promotes into a terminating error. Every real failure here is an explicit guard below.
$ErrorActionPreference = 'Continue'
$ProgressPreference = 'SilentlyContinue'
. (Join-Path $PSScriptRoot 'find-arm-server.ps1')   # deploy this file next to arm.ps1
$exe = Join-Path $Runtime 'llama-server.exe'
if (-not (Test-Path -LiteralPath $exe)) { Write-Warning "no llama-server.exe under $Runtime"; exit 3 }
if (-not (Test-Path -LiteralPath $ArgsFile)) { Write-Warning "no args file: $ArgsFile"; exit 3 }

New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
$path = { param($ext) Join-Path $LogDir "$Tag.$ext" }

# One arm per tag. A stale arm sharing the tag writes to the same record files and makes the
# ledger unreadable (this actually happened once), so the tag is locked for the process lifetime.
# Kill the owning PID if this ever leaves a lock behind.
$lockFile = & $path 'lock'
if (Test-Path -LiteralPath $lockFile) {
    $owner = (Get-Content -LiteralPath $lockFile -ErrorAction SilentlyContinue | Select-Object -First 1)
    $ownerAlive = $false
    if ($owner -and (Get-Process -Id $owner -ErrorAction SilentlyContinue)) { $ownerAlive = $true }
    if ($ownerAlive) {
        Write-Warning "refusing to run: tag '$Tag' is locked by PID $owner ($lockFile)"
        exit 3
    }
    Write-Warning "removing stale lock for tag '$Tag' (owner PID $owner is gone)"
    Remove-Item -LiteralPath $lockFile -Force
}
$PID | Set-Content -LiteralPath $lockFile -Encoding ASCII

# A benchdone marker can only mean "the bench of THIS run is finished". One left over from an
# earlier run of the same tag (re-runs after a failure reuse tags) would end this run's hold
# before anyone benched it, so it goes now, while we hold the tag lock.
$benchdoneFile = & $path 'benchdone'
if (Test-Path -LiteralPath $benchdoneFile) {
    Write-Warning "removing stale benchdone marker from an earlier '$Tag' run ($benchdoneFile)"
    Remove-Item -LiteralPath $benchdoneFile -Force
}

# --- teardown state + one teardown path for every exit path --------------------------------------
# The default behavior (2026-10-21): the arm frees the GPUs itself - the old "leave it up and
# hope someone runs kill-arm" contract held the four cards hostage to operator memory. The
# order inside Stop-ArmRun is sacred: record.md FIRST (failure paths included - the handoff
# reads it), then stop what this run started. -NoAutoTeardown restores the stay-up contract
# for benches that want the warm endpoint; kill-arm.ps1 then does the stopping.
$script:armChildPid = 0
$script:armWatcherPid = 0
$script:armServerPid = 0
$script:armServerPort = "$Port"
$script:armRecordPath = Join-Path $LogDir "$Tag.record.md"
$script:armTornDown = $false

function Stop-ArmRun {
    param([string]$Why)
    if ($script:armTornDown) { return }
    $script:armTornDown = $true
    if (-not (Test-Path -LiteralPath $script:armRecordPath)) {
        # Belt and braces: the handoff must never face a dead arm with no record. Every real
        # exit path writes record.md before calling this; if something exotic skipped it,
        # write a minimal one now rather than stop processes silently.
        @(
            "# arm record: $Tag", "", "- ABORTED before the normal record: $Why",
            "- torn down at: $(Get-Date -Format 's')"
        ) | Set-Content -LiteralPath $script:armRecordPath -Encoding UTF8
    }
    "teardown ($Why): stopping the arm's own child/watchdog/server..."
    $notePath = & $path 'teardown.log'
    Stop-ArmOwnedServer -ServerPid $script:armServerPid -ServerPort $script:armServerPort `
        -ChildPid $script:armChildPid -NotePath $notePath
    foreach ($p in @($script:armChildPid, $script:armWatcherPid)) {
        if ($p -le 0) { continue }
        $proc = Get-Process -Id $p -ErrorAction SilentlyContinue
        if ($proc) {
            Stop-Process -Id $p -Force -ErrorAction SilentlyContinue
            "$(Get-Date -Format 'HH:mm:ss') stopped pid $p ($($proc.Name))" | Add-Content -LiteralPath $notePath -Encoding UTF8
        }
    }
    Remove-Item -LiteralPath $lockFile -Force -ErrorAction SilentlyContinue
    "teardown: GPUs released; kill-arm no longer needed for $Tag."
}

# Any terminating error from here on still releases the GPUs (errors before this point started
# no processes, so there is nothing to leak).
trap {
    Write-Warning "arm $Tag hit: $($_.Exception.Message)"
    Stop-ArmRun -Why "uncaught error: $($_.Exception.Message)"
    exit 3
}

function Get-FreeGB {
    return [math]::Round((Get-CimInstance Win32_OperatingSystem).FreePhysicalMemory / 1MB, 2)
}
function Get-AdapterVRAM {
    $byName = @{}
    foreach ($s in @(Get-Counter '\GPU Adapter Memory(*)\Dedicated Usage' -ErrorAction SilentlyContinue).CounterSamples) {
        $byName[$s.InstanceName] = [math]::Round($s.CookedValue / 1GB, 2)
    }
    return $byName
}

# Stop the arm's llama-server, re-verified before any kill, exactly like kill-arm.ps1: the pid
# must still BE a llama-server.exe (a recycled pid is never touched) and its command line must
# still carry the arm's --port (someone else's server on our port is never touched). With no
# recorded pid (discovery never succeeded) the fallback is parentage: llama-server processes
# whose DIRECT parent is the arm's child script are processes this arm started; production
# llama-swap servers are children of the service and can never match.
function Stop-ArmOwnedServer {
    param([int]$ServerPid, [string]$ServerPort, [int]$ChildPid, [string]$NotePath)
    function Note { param([string]$m) "$((Get-Date -Format 'HH:mm:ss')) $m" | Add-Content -LiteralPath $NotePath -Encoding UTF8 }
    if ($ServerPid -gt 0) {
        $proc = Get-Process -Id $ServerPid -ErrorAction SilentlyContinue
        if (-not $proc) { Note "server pid $ServerPid already gone" }
        elseif ($proc.Name -ne 'llama-server') { Note "REFUSED server pid ${ServerPid}: process is '$($proc.Name)', not llama-server (pid reuse?)" }
        else {
            $cmd = (Get-CimInstance Win32_Process -Filter "ProcessId=$ServerPid" -ErrorAction SilentlyContinue).CommandLine
            if (-not ($cmd -match ('-port\s+' + [regex]::Escape($ServerPort) + '\b'))) {
                Note "REFUSED server pid ${ServerPid}: command line no longer carries --port ${ServerPort}: $cmd"
            }
            else {
                Stop-Process -Id $ServerPid -Force -ErrorAction SilentlyContinue
                Note "stopped server pid $ServerPid (guards passed)"
            }
        }
    }
    else {
        $orphans = @(Get-CimInstance Win32_Process -Filter "Name='llama-server.exe'" |
            Where-Object { $_.ParentProcessId -eq $ChildPid })
        foreach ($o in $orphans) {
            Stop-Process -Id $o.ProcessId -Force -ErrorAction SilentlyContinue
            Note "stopped unrecorded llama-server pid $($o.ProcessId) (direct child of arm child pid $ChildPid)"
        }
        if ($orphans.Count -eq 0) { Note 'no unrecorded llama-server children of the arm child found' }
    }
}

# --- identity: directory names lie, hashes do not ---------------------------------------------
$finger = [ordered]@{}
foreach ($f in 'llama-server.exe', 'llama-server-impl.dll', 'ggml-sycl.dll', 'ggml-base.dll', 'llama.dll') {
    $p = Join-Path $Runtime $f
    if (Test-Path -LiteralPath $p) {
        $item = Get-Item -LiteralPath $p
        $finger[$f] = "$((Get-FileHash -LiteralPath $p -Algorithm SHA256).Hash.Substring(0, 16))  built $($item.LastWriteTime.ToString('yyyy-MM-dd HH:mm'))"
    }
}
# llama-server prints its version banner to stderr. Under PowerShell 5.1 the only reliable way
# to capture a native command's stderr without it becoming an ErrorRecord is to let cmd.exe do
# the merge and read the result back from a file.
$verFile = Join-Path $env:TEMP "arm-ver-$Tag.txt"
& cmd.exe /c "`"$exe`" --version > `"$verFile`" 2>&1"
$version = (Get-Content -LiteralPath $verFile -ErrorAction SilentlyContinue | Out-String).Trim()
if (-not $version) { $version = '(--version produced no output)' }

# --- preflight: refuse to run on a dirty machine ----------------------------------------------
$freeStart = Get-FreeGB
$resident = @(Get-Process | Where-Object { $_.Name -match 'llama-server|strata' })
$adaptersAtIdle = Get-AdapterVRAM
$adaptersBusy = @($adaptersAtIdle.GetEnumerator() | Where-Object { $_.Value -gt $MaxAdapterGB })
if ($resident.Count -gt 0) {
    Write-Warning "refusing to run: another inference server is resident ($($resident.Name -join ', '))"
    exit 3
}
if ($adaptersBusy.Count -gt 0) {
    Write-Warning "refusing to run: adapters already hold >1 GB of VRAM ($($adaptersBusy.Value -join ' GB, '))"
    exit 3
}
if ($freeStart -lt ($MinFreeGB + $HeadroomGB)) {
    Write-Warning "refusing to run: only $freeStart GB free, need $MinFreeGB GB floor plus $HeadroomGB GB headroom"
    exit 3
}

# --- parse the args file into real argv tokens ------------------------------------------------
# Doing this here (not in the child) means the arguments are validated before a 105 GB load
# starts, and there is exactly one copy of the parsing logic.
function Get-ArgvTokens {
    param([string]$Path)
    $tokens = @()
    foreach ($raw in (Get-Content -LiteralPath $Path)) {
        $line = $raw.Trim()
        if ($line -eq '') { continue }
        $i = 0
        while ($i -lt $line.Length) {
            $code = [int]$line[$i]
            if ($code -eq 34) {
                $end = $line.IndexOf([char]34, $i + 1)
                if ($end -lt 0) { $tokens += $line.Substring($i + 1); $i = $line.Length }
                else { $tokens += $line.Substring($i + 1, $end - $i - 1); $i = $end + 1 }
            }
            elseif ($code -eq 32 -or $code -eq 9) { $i += 1 }
            else {
                $start = $i
                while ($i -lt $line.Length -and [int]$line[$i] -ne 32 -and [int]$line[$i] -ne 9) { $i += 1 }
                $tokens += $line.Substring($start, $i - $start)
            }
        }
    }
    return $tokens
}

$argv = Get-ArgvTokens -Path $ArgsFile
if ($argv.Count -eq 0) { Write-Warning "args file produced no tokens"; exit 3 }
$modelIdx = [Array]::IndexOf($argv, '-m')
if ($modelIdx -lt 0) { $modelIdx = [Array]::IndexOf($argv, '--model') }
if ($modelIdx -lt 0) { Write-Warning 'args file has no -m/--model; refusing to launch'; exit 3 }
if ($modelIdx -eq $argv.Count - 1) { Write-Warning '-m has no value'; exit 3 }
$modelPath = $argv[$modelIdx + 1]
if (-not (Test-Path -LiteralPath $modelPath)) { Write-Warning "model file not found: $modelPath"; exit 3 }
$portIdx = [Array]::IndexOf($argv, '--port')
if ($portIdx -ge 0 -and $argv[$portIdx + 1] -ne "$Port") {
    Write-Warning "args file --port $($argv[$portIdx + 1]) disagrees with -Port $Port; using the args file"
}

# --- launch: detached child, so no session teardown can take it down --------------------------
$childScript = Join-Path $env:TEMP "arm-child-$Tag.ps1"
$watchScript = Join-Path $env:TEMP "arm-watch-$Tag.ps1"
$tokensFile = Join-Path $env:TEMP "arm-tokens-$Tag.txt"
Set-Content -LiteralPath $tokensFile -Value $argv -Encoding ASCII

$childLines = @(
    ('$exe = "{0}"' -f $exe)
    ('$tokens = @(Get-Content -LiteralPath "' + $tokensFile + '" | Where-Object { $_ -match "\S" })')
)
foreach ($kv in $Env) {
    $k, $v = $kv.Split('=', 2)
    $childLines += "`$env:$k = `"$v`""
}
$childLines += '& $exe @tokens *>&1'
Set-Content -LiteralPath $childScript -Value $childLines -Encoding UTF8

$watchLines = @(
    ('param([string]$Ledger, [string]$KillLog, [int]$Port, [double]$MinFreeGB, [double]$DemoteGB, [int]$MaxMin, [string]$Runtime)')
    '# Only the llama-server started from THIS arm''s runtime dir is ours to sample and kill. The old'
    '# "biggest llama-server on the box" pick would shoot a production llama-swap server that loaded'
    '# mid-arm (bigger working set) and leave the arm running. case13b guards this.'
    '$end = (Get-Date).AddMinutes($MaxMin)'
    '$peakVram = 0.0; $demoteNoted = $false'
    '"ts,free_gb,server_ws_gb,server_private_gb,vram_total_gb,vram_max_card_gb,health" | Add-Content -LiteralPath $Ledger'
    'while ((Get-Date) -lt $end) {'
    '    $free = [math]::Round((Get-CimInstance Win32_OperatingSystem).FreePhysicalMemory / 1MB, 2)'
    '    $p = Get-Process -Name llama-server -ErrorAction SilentlyContinue | Where-Object { $_.Path -like ($Runtime + "\*") } | Sort-Object WorkingSet64 -Descending | Select-Object -First 1'
    '    $ws = if ($p) { [math]::Round($p.WorkingSet64 / 1GB, 2) } else { 0 }'
    '    $priv = if ($p) { [math]::Round($p.PrivateMemorySize64 / 1GB, 2) } else { 0 }'
    '    $ded = @{}'
    '    foreach ($s in @(Get-Counter "\GPU Adapter Memory(*)\Dedicated Usage" -ErrorAction SilentlyContinue).CounterSamples) {'
    '        $ded[$s.InstanceName] = $s.CookedValue / 1GB'
    '    }'
    '    $total = [math]::Round(($ded.Values | Measure-Object -Sum).Sum, 2)'
    '    $maxCard = [math]::Round(($ded.Values | Measure-Object -Maximum).Maximum, 2)'
    '    $health = try { (Invoke-WebRequest -UseBasicParsing -Uri "http://127.0.0.1:$Port/health" -TimeoutSec 5).StatusCode } catch { "down" }'
    '    ((Get-Date -Format "HH:mm:ss"), $free, $ws, $priv, $total, $maxCard, $health -join ",") | Add-Content -LiteralPath $Ledger'
    '    if ($total -gt $peakVram) { $peakVram = $total }'
    '    # Demotion signature: VRAM in use falls hard while the process is alive and not idle-exiting.'
    '    if (-not $demoteNoted -and $peakVram -gt 50 -and ($peakVram - $total) -gt $DemoteGB) {'
    '        $demoteNoted = $true'
    '        "demotion detected: adapter VRAM fell from $peakVram GB to $total GB" | Add-Content -LiteralPath $KillLog'
    '    }'
    '    if ($p -and $free -lt $MinFreeGB) {'
    '        "watchdog: available RAM fell to $free GB (floor $MinFreeGB) - killing arm server pid $($p.Id)" | Add-Content -LiteralPath $KillLog'
    '        Stop-Process -Id $p.Id -Force'
    '        break'
    '    }'
    '    Start-Sleep -Seconds 2'
    '}'
)
Set-Content -LiteralPath $watchScript -Value $watchLines -Encoding UTF8

# The watcher has to outlive load + soak + bench, not just load.
if ($WatchMin -le 0) { $WatchMin = $LoadTimeoutMin + [math]::Ceiling($IdleSoakSec / 60) + 30 }

if ($DryRun) {
    $idleAdapters = (Get-AdapterVRAM).GetEnumerator() | Sort-Object Name | ForEach-Object { "$($_.Key)=$($_.Value)GB" }
    "DRY RUN: preflight passed. free=$freeStart GB, adapters=$($idleAdapters -join '; ')"
    "  argv tokens: $($argv.Count), model exists: $modelPath"
    "  tokens: $($argv -join ' ')"
    "  runtime: $Runtime"
    "  version: $version"
    "  watcher would run $WatchMin min, floor $MinFreeGB GB available, demotion threshold $DemoteGB GB"
    if ($NoAutoTeardown) {
        "  auto-teardown OFF (-NoAutoTeardown): after record.md the arm stays up indefinitely; stop it with kill-arm.ps1 -Tag $Tag"
    } else {
        "  auto-teardown ON: after record.md, hold ${TeardownHoldMin} min (early release on $(Join-Path $LogDir "$Tag.benchdone")), then stop child/watchdog/server"
    }
    exit 0
}

$child = Start-Process -FilePath 'powershell.exe' `
    -ArgumentList @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', $childScript) `
    -WorkingDirectory $Runtime -WindowStyle Hidden -PassThru `
    -RedirectStandardOutput (& $path 'out.log') -RedirectStandardError (& $path 'err.log')
# Handle inheritance, measured 2026-10-21: Start-Process WITH -Redirect* creates the process with
# bInheritHandles, so it inherits arm.ps1's own stdout. The child above needs its redirect (out.log
# / err.log), so it - and the llama-server under it - holds the invoker's pipe while it lives;
# never capture arm.ps1's output through a pipe when the arm stays up (-NoAutoTeardown), use a
# file. The watcher is started WITHOUT redirection (ShellExecute, nothing inherited) so it adds
# no second holder; its reporting goes to -Ledger/-KillLog anyway.
$watcher = Start-Process -FilePath 'powershell.exe' `
    -ArgumentList @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', $watchScript,
        '-Ledger', (& $path 'ledger.csv'), '-KillLog', (& $path 'watchdog.log'), '-Port', $Port,
        '-MinFreeGB', $MinFreeGB, '-DemoteGB', $DemoteGB, '-MaxMin', $WatchMin, '-Runtime', $Runtime) `
    -WindowStyle Hidden -PassThru

"$(Get-Date -Format 's') arm=$Tag childPID=$($child.Id) watchdogPID=$($watcher.Id) port=$Port freeStartGB=$freeStart"
$script:armChildPid = $child.Id
$script:armWatcherPid = $watcher.Id

# So an arm can be stopped cleanly from one command. Both PIDs are recorded; the watcher is what
# enforces the RAM floor, so leaving it behind would silently remove the guard.
@(
    "# stop this arm with: powershell.exe -File $(Join-Path $LogDir 'kill-arm.ps1') -Tag $Tag"
    "child=$($child.Id)"
    "watcher=$($watcher.Id)"
) | Set-Content -LiteralPath (& $path 'pids.txt') -Encoding UTF8

# --- record the arm's llama-server PID so kill-arm tears the whole arm down in one step ---------
# The server is the child's child, invisible to pids.txt until it exists. Find it by its own
# command line: the --port the argv actually carries (the args file wins over -Port, per the
# warning above), plus an executable-path check under $Runtime so a production llama-swap
# server can never be recorded as ours even if someone sets the arm's port to 9061.
$serverPort = if ($portIdx -ge 0) { $argv[$portIdx + 1] } else { "$Port" }
$script:armServerPort = "$serverPort"
$foundServer = $null
$swFind = [System.Diagnostics.Stopwatch]::StartNew()
while (-not $foundServer -and $swFind.Elapsed.TotalSeconds -lt 60) {
    $foundServer = Get-ArmServerProcess -Runtime $Runtime -Port ([int]$serverPort)
    if (-not $foundServer) {
        if (-not (Get-Process -Id $child.Id -ErrorAction SilentlyContinue)) { break }
        Start-Sleep -Seconds 2
    }
}
if ($foundServer) {
    # Get-ArmServerProcess returns a CIM Win32_Process: the PID is .ProcessId. (.Id is $null on
    # it - reading .Id is how every arm up to 2026-10-21 wrote an empty "server=" line and
    # kill-arm silently never stopped a single arm server. case10a guards this.)
    $script:armServerPid = [int]$foundServer.ProcessId
    @("server=$($script:armServerPid)", "port=$serverPort") |
        Add-Content -LiteralPath (& $path 'pids.txt') -Encoding UTF8
} else {
    "server=? arm llama-server not found within 60 s; auto-teardown will stop it by parentage, kill-arm will hold its handle" |
        Add-Content -LiteralPath (& $path 'pids.txt') -Encoding UTF8
}

# --- hold the endpoint warm while it loads: a request in flight prevents idle demotion --------
"ts,probe,elapsed_s" | Add-Content -LiteralPath (& $path 'probe.csv')
$deadline = (Get-Date).AddMinutes($LoadTimeoutMin)
$ready = $false
$sw = [System.Diagnostics.Stopwatch]::StartNew()
while ((Get-Date) -lt $deadline) {
    try {
        $body = '{"model":"arm","messages":[{"role":"user","content":"Reply with exactly: OK"}],"max_tokens":8,"temperature":0}'
        Invoke-RestMethod -Uri "http://127.0.0.1:$Port/v1/chat/completions" -Method Post `
            -ContentType 'application/json' -Body $body -TimeoutSec 600 | Out-Null
        $ready = $true
        break
    }
    catch {
        "$((Get-Date -Format 'HH:mm:ss')),waiting,$([math]::Round($sw.Elapsed.TotalSeconds, 1))" | Add-Content -LiteralPath (& $path 'probe.csv')
        Start-Sleep -Seconds 20
        if (-not (Get-Process -Id $child.Id -ErrorAction SilentlyContinue)) {
            "child script exited while waiting; probe loop stops early" | Add-Content -LiteralPath (& $path 'probe.csv')
            break
        }
    }
}
"$((Get-Date -Format 'HH:mm:ss')),$(if ($ready) { 'ready' } else { 'not-ready' }),$([math]::Round($sw.Elapsed.TotalSeconds, 1))" | Add-Content -LiteralPath (& $path 'probe.csv')

# "Alive" means THIS arm's server, not any llama-server: a production server that loaded mid-arm
# must not make a dead arm look healthy.
$alive = if ($script:armServerPid -gt 0) { Get-Process -Id $script:armServerPid -ErrorAction SilentlyContinue }
         else { Get-Process -Name llama-server -ErrorAction SilentlyContinue | Where-Object { $_.Path -like ($Runtime + '\*') } }
$freeNow = Get-FreeGB
$dedNow = Get-AdapterVRAM
$dedText = ($dedNow.GetEnumerator() | Sort-Object Name | ForEach-Object { "$($_.Key)=$($_.Value)GB" })

# --- idle soak: this is the arm's real question -----------------------------------------------
# Production kept GLM warm with real traffic, so it survived; bench arms idle and died. Nothing
# but the in-process heartbeat runs during this window, so the soak isolates that one variable:
# VRAM holding flat + a fast post-idle answer means the heartbeat works, and the live entry needs it.
$soakNote = 'skipped'
$freeAfterSoak = $freeNow
$dedAfterSoak = $dedNow
$soakAnswerSec = $null
if ($IdleSoakSec -gt 0 -and $alive) {
    "soak: $IdleSoakSec s with no requests (heartbeat is the only GPU activity)" | Add-Content -LiteralPath (& $path 'probe.csv')
    Start-Sleep -Seconds $IdleSoakSec
    $freeAfterSoak = Get-FreeGB
    $dedAfterSoak = Get-AdapterVRAM
    $sw2 = [System.Diagnostics.Stopwatch]::StartNew()
    try {
        $body = '{"model":"arm","messages":[{"role":"user","content":"Reply with exactly: OK"}],"max_tokens":8,"temperature":0}'
        Invoke-RestMethod -Uri "http://127.0.0.1:$Port/v1/chat/completions" -Method Post `
            -ContentType 'application/json' -Body $body -TimeoutSec 900 | Out-Null
        $soakAnswerSec = [math]::Round($sw2.Elapsed.TotalSeconds, 1)
    }
    catch {
        $soakAnswerSec = [math]::Round($sw2.Elapsed.TotalSeconds, 1)
        "post-soak request failed: $($_.Exception.Message)" | Add-Content -LiteralPath (& $path 'probe.csv')
    }
    $soakNote = "answered in $soakAnswerSec s after ${IdleSoakSec}s idle"
}
$watchdogLines = @(Get-Content -LiteralPath (& $path 'watchdog.log') -ErrorAction SilentlyContinue | Where-Object { $_ -match '\S' })

@(
    "# arm record: $Tag"
    ""
    "- started: $(Get-Date -Format 's')"
    "- first answer after: $([math]::Round($sw.Elapsed.TotalSeconds, 1)) s (ready=$ready, serverAlive=$([bool]$alive))"
    "- host RAM free at start: $freeStart GB; at first answer: $freeNow GB; after soak: $freeAfterSoak GB"
    "- adapters at first answer: $($dedText -join '; ')"
    "- adapters after soak: $((($dedAfterSoak.GetEnumerator() | Sort-Object Name | ForEach-Object { "$($_.Key)=$($_.Value)GB" }) -join '; '))"
    "- VRAM totals: at first answer $([math]::Round(($dedNow.Values | Measure-Object -Sum).Sum, 2)) GB, after soak $([math]::Round(($dedAfterSoak.Values | Measure-Object -Sum).Sum, 2)) GB"
    "- idle soak: $soakNote"
    "- runtime: $Runtime"
    "- version: $version"
    "- env: $(if ($Env.Count) { $Env -join '  ' } else { '(none)' })"
    "- watchdog: kills below $MinFreeGB GB available; demotion noted above $DemoteGB GB of VRAM loss"
    # If the watchdog acted (RAM-floor kill, demotion), the record must say so: a record that
    # only reads "ready=False" sends the next agent hunting for a load bug that is not there.
    $(if ($watchdogLines.Count) { "- watchdog events: $($watchdogLines -join ' | ')" } else { '- watchdog events: none' })
    ""
    'launch arguments:'
    '```'
    ((Get-Content -LiteralPath $ArgsFile | Where-Object { $_ -match '\S' } | ForEach-Object { $_.Trim() }) -join "`n")
    '```'
    'fingerprints:'
    '```'
    (($finger.GetEnumerator() | ForEach-Object { "$($_.Key): $($_.Value)" }) -join "`n")
    '```'
) | Set-Content -LiteralPath (& $path 'record.md') -Encoding UTF8

# --- record.md is on disk: the handoff can read it. Now the teardown gate. -----------------------
# Order rule from the glm-5.3 handoff: a dead arm still gets its record; stopping anything is
# only allowed after the record above has been written. The exit-code lines below the gate
# keep their documented meanings (0 answered, 2 never answered, 4 died after answering).
if ($NoAutoTeardown) {
    $srvDesc = if ($script:armServerPid -gt 0) { "server=$($script:armServerPid)" } else { 'server=?' }
    "AUTO-TEARDOWN OFF: $Tag left up (child=$($child.Id) watcher=$($watcher.Id) $srvDesc port=$serverPort); the GPUs stay allocated."
    "  Bench it, then release with: powershell.exe -File $(Join-Path $LogDir 'kill-arm.ps1') -Tag $Tag -LogDir $LogDir"
}
else {
    if ($ready) {
        "READY after $([math]::Round($sw.Elapsed.TotalSeconds, 1)) s. Auto-teardown armed: holding 127.0.0.1:$serverPort for $TeardownHoldMin min so an external bench can use the warm model; write $benchdoneFile to release early; then child/watchdog/server stop automatically."
        $holdSw = [System.Diagnostics.Stopwatch]::StartNew()
        $holdEnd = (Get-Date).AddMinutes($TeardownHoldMin)
        $holdReason = 'hold window expired'
        while ((Get-Date) -lt $holdEnd) {
            if (Test-Path -LiteralPath $benchdoneFile) { $holdReason = 'benchdone marker seen'; break }
            if (-not (Get-Process -Id $child.Id -ErrorAction SilentlyContinue)) { $holdReason = 'child already exited'; break }
            Start-Sleep -Seconds 15
        }
        "HOLD ENDED: $holdReason after $([math]::Round($holdSw.Elapsed.TotalSeconds)) s."
    }
    else {
        $holdReason = 'not-ready'
        "Auto-teardown: not-ready arm, skipping the bench hold; releasing what this run started."
    }
    Stop-ArmRun -Why "auto-teardown ($holdReason)"
}

if (-not $ready) { Write-Warning "endpoint never answered within $LoadTimeoutMin min"; exit 2 }
if (-not $alive) { Write-Warning "server died after first answer; see $(Join-Path $LogDir "$Tag.watchdog.log")"; exit 4 }
"OK: $Tag answering on 127.0.0.1:$Port  ledger=$(Join-Path $LogDir "$Tag.ledger.csv")"
exit 0
