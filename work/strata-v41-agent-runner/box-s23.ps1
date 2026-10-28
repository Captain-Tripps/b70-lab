# Session 23 harness: --adapt-every 0 A/B on the SERVED Strata build (the llama-swap entry's lab build), run as
# `strata.exe` generate with the entry's own JSON config: same exe, env, args and cards (level_zero:2,3), minus the
# serve-only conversation cache flags. Interleaved, n=3, code prompt. Always restores llama-swap.
# Log: C:\b70-work\s23.log, per-run output: C:\b70-work\s23\*.txt
param([int]$Reps = 3)
$ErrorActionPreference = 'Continue'
$log = 'C:\b70-work\s23.log'
$out = 'C:\b70-work\s23'
$cfgPath = "$env:USERPROFILE\AI\Runtimes\strata\configs\qwen38-flashnext-iq3s-200k.json"
New-Item -ItemType Directory -Force $out | Out-Null
function L([string]$m) { "{0:HH:mm:ss} {1}" -f (Get-Date), $m | Add-Content $log -Encoding utf8 }
function Kill-Strata {
    foreach ($q in @(Get-Process -Name 'strata' -EA SilentlyContinue)) { & taskkill.exe /F /T /PID $q.Id 2>&1 | Out-Null }
    Start-Sleep 3
}
$cfg = Get-Content $cfgPath -Raw | ConvertFrom-Json
$args0 = @()
$skip = 0
foreach ($a in $cfg.args) {
    if ($skip -gt 0) { $skip--; continue }
    if ($a -in @('--conversation-cache-mib', '--conversation-cache-slots')) { $skip = 1; continue }
    $args0 += $(if ($a -match '[\s\\]') { '"' + $a + '"' } else { $a })
}
$common = $args0 -join ' '
$envLines = @($cfg.env.PSObject.Properties | ForEach-Object { "set $($_.Name)=$($_.Value)" })
$prompt = '--tokens "7734,264,12654,709,421,4523,279,2542,314,660,1442,4947,303,264,1103,13,28763,2250,26864,6813,321,3579,279,4147,1103,1105,13" --max-new 64'
$configs = [ordered]@{ base = ''; noadapt = '--adapt-every 0' }
$plan = @()
for ($r = 1; $r -le $Reps; $r++) { foreach ($c in $configs.Keys) { $plan += ,@($c, $r) } }

"=== s23 start $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') runs=$($plan.Count) ===" | Set-Content $log -Encoding utf8
L "exe=$($cfg.exe) args: $common"
try {
    L "stopping llama-swap"
    Stop-Service -Name llama-swap -Force -EA Continue
    Start-Sleep 5
    L "llama-swap: $((Get-Service llama-swap).Status)"
    foreach ($q in @(Get-Process -Name 'llama-server' -EA SilentlyContinue)) { & taskkill.exe /F /PID $q.Id 2>&1 | Out-Null }
    Kill-Strata
    Start-Sleep 10
    $c = (Get-CimInstance Win32_PerfRawData_PerfOS_Memory).CommittedBytes/1GB
    if ($c -gt 40) { L ("ABORT: commit {0:N1} GB > 40 GB - something foreign is running" -f $c); return }

    foreach ($run in $plan) {
        $name, $r = $run
        $tag = "$name-r$r"
        $txt = "$out\$tag.txt"
        $bat = "$out\$tag.bat"
        $lines = @('@echo off', 'setlocal',
            'call "C:\Program Files (x86)\Intel\oneAPI\setvars.bat" --force >nul 2>&1',
            "cd /d `"$($cfg.cwd)`"",
            "set PATH=$($cfg.lib_dirs -join ';');%PATH%",
            'set ONEAPI_DEVICE_SELECTOR=level_zero:2,3') + $envLines + @(
            "`"$($cfg.exe)`" $common $($configs[$name]) $prompt > $txt 2>&1",
            "echo EXIT=%ERRORLEVEL% >> $txt")
        [IO.File]::WriteAllText($bat, (($lines -join "`r`n") + "`r`n"), [Text.Encoding]::ASCII)
        $proc = Start-Process -FilePath 'C:\Windows\System32\cmd.exe' -ArgumentList '/c', $bat -WindowStyle Hidden -PassThru
        if (-not $proc.WaitForExit(600000)) { L "[$tag] TIMEOUT after 600 s"; & taskkill.exe /F /T /PID $proc.Id 2>&1 | Out-Null; Kill-Strata; continue }
        $t = Get-Content $txt -EA SilentlyContinue
        $dec = ($t | Select-String '^decode ' | Select -Last 1).Line
        $o   = ($t | Select-String '^output' | Select -Last 1).Line
        $ex  = ($t | Select-String '^EXIT=' | Select -Last 1).Line
        $oh  = if ($o) { [BitConverter]::ToString([Security.Cryptography.MD5]::Create().ComputeHash([Text.Encoding]::ASCII.GetBytes($o))).Replace('-', '').Substring(0, 10) } else { 'none' }
        L "[$tag] $ex out=$oh | $dec"
        foreach ($pat in '^speculation', '^verify window', '^pool multi', '^dispatch ', '^adaptive tier', 'adaptive swaps off', 'tier is off') {
            $hit = ($t | Select-String $pat | Select -Last 1).Line
            if ($hit) { L "[$tag]   $hit" }
        }
        if (-not $dec) { ($t | Select -Last 6) | ForEach-Object { L "[$tag]   tail: $_" } }
        Kill-Strata
    }
}
finally {
    Kill-Strata
    L "restoring llama-swap"
    Start-Service -Name llama-swap -EA Continue
    Start-Sleep 10
    L "llama-swap: $((Get-Service llama-swap).Status)"
    "=== s23 end $(Get-Date -Format 'HH:mm:ss') ===" | Add-Content $log
}
