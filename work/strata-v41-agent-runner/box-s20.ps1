# Session 20 harness: 1017 CPU-only (-dev none -ngl 0 -t 46), same warm bench as s19, to measure what the
# hybrid's GPU<->CPU hand-offs cost. No working-set trim (nothing is uploaded, the WS is the CPU weights).
# Also samples disk reads, because 129 GB of weights cannot all sit in 96 GB of page cache.
# Always restores llama-swap. Log: C:\b70-work\s20.log, memory/disk: s20-mem.log
param([int]$Threads = 46)
$ErrorActionPreference = 'Continue'
$log = 'C:\b70-work\s20.log'
$memlog = 'C:\b70-work\s20-mem.log'
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

"=== s20 start $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') threads=$Threads ===" | Set-Content $log -Encoding utf8
"=== s20 mem $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') ===" | Set-Content $memlog -Encoding utf8
$sampler = $null
try {
    L "stopping llama-swap"
    Stop-Service -Name llama-swap -Force -EA Continue
    Start-Sleep 5
    L "llama-swap: $((Get-Service llama-swap).Status)"
    Kill-Servers
    $c = (Get-CimInstance Win32_PerfRawData_PerfOS_Memory).CommittedBytes/1GB
    if ($c -gt 40) { L ("ABORT: commit {0:N1} GB > 40 GB - something foreign is running" -f $c); return }

    $sampler = Start-Job -ArgumentList $memlog -ScriptBlock {
        param($f)
        while ($true) {
            $m = Get-CimInstance Win32_PerfRawData_PerfOS_Memory
            $d = Get-CimInstance Win32_PerfFormattedData_PerfDisk_PhysicalDisk -Filter "Name='_Total'"
            $p = Get-Process -Name 'llama-server' -EA SilentlyContinue | Select-Object -First 1
            $line = "{0:HH:mm:ss} avail={1:N1} commit={2:N1} diskread={3:N0}MB/s" -f (Get-Date), ($m.AvailableBytes/1GB), ($m.CommittedBytes/1GB), ($d.DiskReadBytesPersec/1MB)
            if ($p) { $line += " ws={0:N1} priv={1:N1}" -f ($p.WorkingSet64/1GB), ($p.PrivateMemorySize64/1GB) }
            $line | Add-Content $f -Encoding utf8
            Start-Sleep 5
        }
    }

    $tag = "cpu-t$Threads"
    $bat = "C:\b70-work\s20-$tag.bat"
    $srvlog = "C:\b70-work\s20-$tag-srv.log"
    $lines = @('@echo off', 'setlocal',
        'call "C:\Program Files (x86)\Intel\oneAPI\setvars.bat" --force >nul 2>&1',
        "echo ==== start %DATE% %TIME% ==== >> $srvlog",
        "`"$bin`" ^",
        '  -m "D:\AI\Models\dsv41\DeepSeek-V4.1-Flash-1017-GSQ-RCO-IQ2_XXS-00001-of-00004.gguf" ^',
        "  -c 2048 -dev none -ngl 0 -fit off -t $Threads ^",
        '  -lm auto -np 1 --cache-ram 0 --no-warmup ^',
        "  --host 127.0.0.1 --port 9100 >> $srvlog 2>&1",
        "echo ==== exit %ERRORLEVEL% %DATE% %TIME% ==== >> $srvlog")
    [IO.File]::WriteAllText($bat, (($lines -join "`r`n") + "`r`n"), [Text.Encoding]::ASCII)
    L "[$tag] pre-launch $(Mem)"
    $r = Invoke-CimMethod -ClassName Win32_Process -MethodName Create -Arguments @{ CommandLine = "cmd.exe /c $bat" }
    $t0 = Get-Date; $ok = $false
    while (((Get-Date) - $t0).TotalSeconds -lt 1200) {
        Start-Sleep 2
        $el = [int]((Get-Date) - $t0).TotalSeconds
        $p = Get-Process -Name 'llama-server' -EA SilentlyContinue | Select -First 1
        if (-not $p) { if ($el -gt 20) { L "[$tag] t+${el}s NO PROCESS $(Mem)"; break } else { continue } }
        try {
            $h = Invoke-WebRequest 'http://127.0.0.1:9100/health' -TimeoutSec 2 -UseBasicParsing
            if ($h.StatusCode -eq 200) { $ok = $true; break }
        } catch { }
    }
    if (-not $ok) { L "[$tag] never reached health 200"; return }
    $p = Get-Process -Name 'llama-server' -EA SilentlyContinue | Select -First 1
    L ("[$tag] READY t+$([int]((Get-Date) - $t0).TotalSeconds)s ws={0:N2} {1}" -f ($p.WorkingSet64/1GB), (Mem))
    $cpu0 = $p.TotalProcessorTime; $w0 = Get-Date
    L "[$tag] === bench ==="
    & $py 'C:\b70-work\bench-port.py' 9100 --warm 2>&1 | ForEach-Object { L "[$tag]   $_" }
    $p.Refresh()
    if (-not $p.HasExited) {
        $cores = ($p.TotalProcessorTime - $cpu0).TotalSeconds / ((Get-Date) - $w0).TotalSeconds
        L ("[$tag] bench avg CPU = {0:N1} cores; after bench ws={1:N2} {2}" -f $cores, ($p.WorkingSet64/1GB), (Mem))
    } else { L "[$tag] server DIED during bench" }
}
finally {
    Kill-Servers
    if ($sampler) { Stop-Job $sampler -EA SilentlyContinue; Remove-Job $sampler -Force -EA SilentlyContinue }
    L "restoring llama-swap"
    Start-Service -Name llama-swap -EA Continue
    Start-Sleep 10
    L "llama-swap: $((Get-Service llama-swap).Status) $(Mem)"
    "=== s20 end $(Get-Date -Format 'HH:mm:ss') ===" | Add-Content $log
}
