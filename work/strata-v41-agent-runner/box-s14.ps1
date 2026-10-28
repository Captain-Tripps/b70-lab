# Session 14 harness: stop llama-swap, bench 1017 (-ncmoe 18) inline with the health poll,
# then the small-model RAM control, then restore llama-swap. Log: C:\b70-work\s14.log
$ErrorActionPreference = 'Continue'
$log = 'C:\b70-work\s14.log'
$py  = 'C:\Python314\python.exe'
$bin = 'C:\llamacpp-v41\build-sycl\bin\llama-server.exe'
function L([string]$m) { "{0:HH:mm:ss} {1}" -f (Get-Date), $m | Add-Content $log -Encoding utf8 }
function Mem {
    $m = Get-CimInstance Win32_PerfRawData_PerfOS_Memory
    "avail={0:N1} commit={1:N1}" -f ($m.AvailableBytes/1GB), ($m.CommittedBytes/1GB)
}
function Kill-Servers {
    foreach ($q in @(Get-Process -Name 'llama-server' -EA SilentlyContinue)) { & taskkill.exe /F /PID $q.Id 2>&1 | Out-Null }
    for ($i = 0; $i -lt 72; $i++) {
        if (-not (Get-Process -Name 'llama-server' -EA SilentlyContinue)) { L "servers gone after $($i*5)s ($(Mem))"; return }
        Start-Sleep 5
    }
    L "WARNING llama-server still present after 6 min"
}
function Write-Bat($path, $srvlog, $argLines) {
    $lines = @('@echo off', 'setlocal',
        'call "C:\Program Files (x86)\Intel\oneAPI\setvars.bat" --force >nul 2>&1',
        "echo ==== start %DATE% %TIME% ==== >> $srvlog",
        "`"$bin`" ^") + ($argLines | ForEach-Object { "  $_ ^" })
    $lines[-1] = $lines[-1].TrimEnd(' ', '^') + " >> $srvlog 2>&1"
    $lines += "echo ==== exit %ERRORLEVEL% %DATE% %TIME% ==== >> $srvlog"
    [IO.File]::WriteAllText($path, (($lines -join "`r`n") + "`r`n"), [Text.Encoding]::ASCII)
}
# Launch, poll every 2 s, bench the moment /health is 200. Returns $true if benched.
function Run-Phase($tag, $bat, $port, $maxSec, $steadySec) {
    L "[$tag] pre-launch $(Mem)"
    $r = Invoke-CimMethod -ClassName Win32_Process -MethodName Create -Arguments @{ CommandLine = "cmd.exe /c $bat" }
    L "[$tag] launched cmd pid=$($r.ProcessId)"
    $t0 = Get-Date; $peakWs = 0; $peakPriv = 0; $minAvail = 999; $ok = $false
    while (((Get-Date) - $t0).TotalSeconds -lt $maxSec) {
        Start-Sleep 2
        $el = [int]((Get-Date) - $t0).TotalSeconds
        $p = Get-Process -Name 'llama-server' -EA SilentlyContinue | Select -First 1
        $m = Get-CimInstance Win32_PerfRawData_PerfOS_Memory
        $av = $m.AvailableBytes/1GB
        if (-not $p) { if ($el -gt 20) { L "[$tag] t+${el}s NO PROCESS avail=$('{0:N1}' -f $av)"; break } else { continue } }
        $ws = $p.WorkingSet64/1GB; $pv = $p.PrivateMemorySize64/1GB
        $peakWs = [math]::Max($peakWs, $ws); $peakPriv = [math]::Max($peakPriv, $pv); $minAvail = [math]::Min($minAvail, $av)
        if ($el % 10 -lt 2) { L ("[$tag] t+{0}s ws={1:N1} priv={2:N1} avail={3:N1} commit={4:N1}" -f $el, $ws, $pv, $av, ($m.CommittedBytes/1GB)) }
        try {
            $h = Invoke-WebRequest "http://127.0.0.1:$port/health" -TimeoutSec 2 -UseBasicParsing
            if ($h.StatusCode -eq 200) { $ok = $true; break }
        } catch { }
    }
    L ("[$tag] load peaks: ws={0:N1} priv={1:N1} minAvail={2:N1}" -f $peakWs, $peakPriv, $minAvail)
    if (-not $ok) { L "[$tag] never reached health 200"; return $false }
    L "[$tag] READY t+$([int]((Get-Date) - $t0).TotalSeconds)s"
    if ($steadySec -gt 0) { Start-Sleep $steadySec }
    $p = Get-Process -Name 'llama-server' -EA SilentlyContinue | Select -First 1
    if ($p) { L ("[$tag] steady: ws={0:N2} priv={1:N2} paged={2:N2} {3}" -f ($p.WorkingSet64/1GB), ($p.PrivateMemorySize64/1GB), ($p.PagedMemorySize64/1GB), (Mem)) }
    L "[$tag] === bench ==="
    & $py 'C:\b70-work\bench-port.py' $port 2>&1 | ForEach-Object { L "[$tag]   $_" }
    $p = Get-Process -Name 'llama-server' -EA SilentlyContinue | Select -First 1
    if ($p) { L ("[$tag] after bench: ws={0:N2} priv={1:N2} {2}" -f ($p.WorkingSet64/1GB), ($p.PrivateMemorySize64/1GB), (Mem)) } else { L "[$tag] server DIED during bench" }
    return $true
}

"=== s14 start $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') ===" | Set-Content $log -Encoding utf8
L "stopping llama-swap"
Stop-Service -Name llama-swap -Force -EA Continue
Start-Sleep 5
L "llama-swap: $((Get-Service llama-swap).Status)"
Kill-Servers
$c = (Get-CimInstance Win32_PerfRawData_PerfOS_Memory).CommittedBytes/1GB
if ($c -gt 40) { L ("ABORT: commit {0:N1} GB > 40 GB - something foreign is running" -f $c) }
else {
    # Phase A: 1017, -ncmoe 18 split from session 13, plus --cache-ram 0
    Write-Bat 'C:\b70-work\s14a.bat' 'C:\b70-work\s14a-srv.log' @(
        '-m "D:\AI\Models\dsv41\DeepSeek-V4.1-Flash-1017-GSQ-RCO-IQ2_XXS-00001-of-00004.gguf"',
        '-c 2048', '-ngl 40', '-ncmoe 18', '-ts 57.5,15,15,12.5', '-fit off', '-sm layer', '-t 12',
        '-lzm off', '-lm auto', '-np 1', '--cache-ram 0', '--no-warmup', '--host 127.0.0.1', '--port 9100')
    Run-Phase 'A-1017' 'C:\b70-work\s14a.bat' 9100 900 10 | Out-Null
    Kill-Servers
    # Phase B: small-model control, same build
    Write-Bat 'C:\b70-work\s14b.bat' 'C:\b70-work\s14b-srv.log' @(
        '-m "D:\AI\LLM\Models\Qwen3-Coder-30B-A3B-Q4_K_M.gguf"',
        '-c 2048', '-ngl 99', '-sm layer', '-t 12', '-lm auto', '-np 1', '--cache-ram 0',
        '--no-warmup', '--host 127.0.0.1', '--port 9080')
    Run-Phase 'B-qwen' 'C:\b70-work\s14b.bat' 9080 600 20 | Out-Null
    Kill-Servers
}
L "restoring llama-swap"
Start-Service -Name llama-swap -EA Continue
Start-Sleep 10
L "llama-swap: $((Get-Service llama-swap).Status) $(Mem)"
"=== s14 end $(Get-Date -Format 'HH:mm:ss') ===" | Add-Content $log
