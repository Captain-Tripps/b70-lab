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
param(
    [Parameter(Mandatory = $true)][string]$Runtime,
    [Parameter(Mandatory = $true)][string]$ArgsFile,
    [string[]]$Env = @(),
    [int]$Port = 9061,
    [Parameter(Mandatory = $true)][string]$Tag,
    [string]$LogDir = "%USERPROFILE%\AI\logs\arms",
    [double]$MinFreeGB = 8,
    [double]$DemoteGB = 60,
    [int]$LoadTimeoutMin = 45,
    [int]$WatchMin = 0,
    [int]$IdleSoakSec = 240,
    [switch]$DryRun
)

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
$adaptersBusy = @($adaptersAtIdle.GetEnumerator() | Where-Object { $_.Value -gt 1.0 })
if ($resident.Count -gt 0) {
    Write-Warning "refusing to run: another inference server is resident ($($resident.Name -join ', '))"
    exit 3
}
if ($adaptersBusy.Count -gt 0) {
    Write-Warning "refusing to run: adapters already hold >1 GB of VRAM ($($adaptersBusy.Value -join ' GB, '))"
    exit 3
}
if ($freeStart -lt ($MinFreeGB + 65)) {
    Write-Warning "refusing to run: only $freeStart GB free, Maya-M needs roughly 100 GB of headroom"
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
    ('param([string]$Ledger, [string]$KillLog, [int]$Port, [double]$MinFreeGB, [double]$DemoteGB, [int]$MaxMin, [string]$ArgsFile)')
    '$end = (Get-Date).AddMinutes($MaxMin)'
    '$peakVram = 0.0; $demoteNoted = $false'
    '"ts,free_gb,server_ws_gb,server_private_gb,vram_total_gb,vram_max_card_gb,health" | Add-Content -LiteralPath $Ledger'
    'while ((Get-Date) -lt $end) {'
    '    $free = [math]::Round((Get-CimInstance Win32_OperatingSystem).FreePhysicalMemory / 1MB, 2)'
    '    $p = Get-Process -Name llama-server -ErrorAction SilentlyContinue | Sort-Object WorkingSet64 -Descending | Select-Object -First 1'
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
    '        "watchdog: available RAM fell to $free GB (floor $MinFreeGB) - killing arm" | Add-Content -LiteralPath $KillLog'
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
    exit 0
}

$child = Start-Process -FilePath 'powershell.exe' `
    -ArgumentList @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', $childScript) `
    -WorkingDirectory $Runtime -WindowStyle Hidden -PassThru `
    -RedirectStandardOutput (& $path 'out.log') -RedirectStandardError (& $path 'err.log')
$watcher = Start-Process -FilePath 'powershell.exe' `
    -ArgumentList @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', $watchScript,
        '-Ledger', (& $path 'ledger.csv'), '-KillLog', (& $path 'watchdog.log'), '-Port', $Port,
        '-MinFreeGB', $MinFreeGB, '-DemoteGB', $DemoteGB, '-MaxMin', $WatchMin) `
    -WindowStyle Hidden -PassThru

"$(Get-Date -Format 's') arm=$Tag childPID=$($child.Id) watchdogPID=$($watcher.Id) port=$Port freeStartGB=$freeStart"

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
$foundServer = $null
$swFind = [System.Diagnostics.Stopwatch]::StartNew()
while (-not $foundServer -and $swFind.Elapsed.TotalSeconds -lt 60) {
    $foundServer = Get-ArmServerProcess -Runtime $Runtime -Port ([int]$serverPort)
    if (-not $foundServer) { Start-Sleep -Seconds 2 }
}
if ($foundServer) {
    @("server=$($foundServer.Id)", "port=$serverPort") |
        Add-Content -LiteralPath (& $path 'pids.txt') -Encoding UTF8
} else {
    "server=? arm llama-server not found within 60 s; kill-arm will hold its handle" |
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
    }
}
"$((Get-Date -Format 'HH:mm:ss')),ready,$([math]::Round($sw.Elapsed.TotalSeconds, 1))" | Add-Content -LiteralPath (& $path 'probe.csv')

$alive = Get-Process -Name llama-server -ErrorAction SilentlyContinue
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

if (-not $ready) { Write-Warning "endpoint never answered within $LoadTimeoutMin min"; exit 2 }
if (-not $alive) { Write-Warning "server died after first answer; see $(Join-Path $LogDir "$Tag.watchdog.log")"; exit 4 }
"OK: $Tag answering on 127.0.0.1:$Port  ledger=$(Join-Path $LogDir "$Tag.ledger.csv")"
exit 0
