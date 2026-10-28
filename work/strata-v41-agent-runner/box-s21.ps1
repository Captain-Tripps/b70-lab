# Session 21 harness: Strata v0.2.7 2-card A/B for the RemoteExperts patch (spin wait / host metadata).
# base = the unpatched binary (strata.base-s11.exe); spin / meta / both = the patched strata.exe with
# STRATA_REMOTE_SPIN=1 / STRATA_REMOTE_HOSTMETA=1 / both. Configs are interleaved per repetition.
# Always restores llama-swap. Log: C:\b70-work\s21.log, per-run output: C:\b70-work\s21\*.txt
param([int]$Reps = 3)
$ErrorActionPreference = 'Continue'
$log = 'C:\b70-work\s21.log'
$out = 'C:\b70-work\s21'
$bld = 'D:\strata-dsv41-port\build-jit'
New-Item -ItemType Directory -Force $out | Out-Null
function L([string]$m) { "{0:HH:mm:ss} {1}" -f (Get-Date), $m | Add-Content $log -Encoding utf8 }
function Kill-Strata {
    foreach ($q in @(Get-Process -Name 'strata','strata.base-s11' -EA SilentlyContinue)) { & taskkill.exe /F /T /PID $q.Id 2>&1 | Out-Null }
    Start-Sleep 3
}
$common = '--pack "D:\AI\Strata-data\packs\iq3_s" ' +
    '--native "D:\AI\LLM\Models\ISTA-DASLab\Qwen3.8-Flash-Next-GSQ-RCO-GGUF\IQ3_S\Qwen3.8-Flash-Next-GSQ-RCO-IQ3_S-00001-of-00002.gguf" ' +
    '--ple-gguf "D:\AI\LLM\Models\ISTA-DASLab\Qwen3.8-Flash-Next-GSQ-RCO-GGUF\IQ3_S\Qwen3.8-Flash-Next-GSQ-RCO-IQ3_S-00002-of-00002.gguf" ' +
    '--expert-profile "%USERPROFILE%\strata-win\data\expert-profile-sycl.bin" ' +
    '--max-context 8192 --kv int8 --spec 4 --mtp "D:\AI\Strata-data\mtp\rt" --spec-min-p 0 ' +
    '--mtp-draft-vocab "%USERPROFILE%\strata-win\data\draft_vocab_en.bin" --ple-io mmap --stream-experts ' +
    '--expert-cache auto --expert-cache-device1 auto --vram-reserve-mib 1024 --prefill 8192 --no-prefill-borrow'
$prompts = @{
    code  = '--suffix-draft 0 --tokens "7734,264,12654,709,421,4523,279,2542,314,660,1442,4947,303,264,1103,13,28763,2250,26864,6813,321,3579,279,4147,1103,1105,13" --max-new 64'
    short = '--tokens "9707,11,1879,13,374,264,1293,13" --max-new 32'
}
$configs = [ordered]@{
    base = @{ exe = 'strata.base-s11.exe'; env = @() }
    spin = @{ exe = 'strata.exe'; env = @('set STRATA_REMOTE_SPIN=1') }
    meta = @{ exe = 'strata.exe'; env = @('set STRATA_REMOTE_HOSTMETA=1') }
    both = @{ exe = 'strata.exe'; env = @('set STRATA_REMOTE_SPIN=1', 'set STRATA_REMOTE_HOSTMETA=1') }
}
$plan = @()
for ($r = 1; $r -le $Reps; $r++) { foreach ($c in $configs.Keys) { $plan += ,@('code', $c, $r) } }
for ($r = 1; $r -le $Reps; $r++) { foreach ($c in @('base', 'both')) { $plan += ,@('short', $c, $r) } }

"=== s21 start $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') runs=$($plan.Count) ===" | Set-Content $log -Encoding utf8
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
        $p, $cfg, $r = $run
        $tag = "$p-$cfg-r$r"
        $txt = "$out\$tag.txt"
        $bat = "$out\$tag.bat"
        $lines = @('@echo off', 'setlocal',
            'call "C:\Program Files (x86)\Intel\oneAPI\setvars.bat" --force >nul 2>&1',
            "cd /d $bld",
            'set SYCL_CACHE_PERSISTENT=0', 'set STRATA_NIGHT_PREFILL_GROUPED=0', 'set STRATA_KV_ROT=0',
            'set STRATA_WIN_TIMER_MS=0', 'set STRATA_MMVQ_WIDE=1', 'set STRATA_NIGHT_MMVQ=1', 'set STRATA_NIGHT_BF16=1',
            'set STRATA_NIGHT_HC=q8', 'set STRATA_PREFILL_FIRST=0') + $configs[$cfg].env + @(
            "$($configs[$cfg].exe) $common $($prompts[$p]) > $txt 2>&1",
            "echo EXIT=%ERRORLEVEL% >> $txt")
        [IO.File]::WriteAllText($bat, (($lines -join "`r`n") + "`r`n"), [Text.Encoding]::ASCII)
        $proc = Start-Process -FilePath 'C:\Windows\System32\cmd.exe' -ArgumentList '/c', $bat -WindowStyle Hidden -PassThru
        if (-not $proc.WaitForExit(300000)) { L "[$tag] TIMEOUT after 300 s"; & taskkill.exe /F /T /PID $proc.Id 2>&1 | Out-Null; Kill-Strata; continue }
        $t = Get-Content $txt -EA SilentlyContinue
        $dec = ($t | Select-String '^decode ' | Select -Last 1).Line
        $vw  = ($t | Select-String '^verify window' | Select -Last 1).Line
        $pm  = ($t | Select-String '^pool multi' | Select -Last 1).Line
        $dp  = ($t | Select-String '^dispatch ' | Select -Last 1).Line
        $sp  = ($t | Select-String '^speculation' | Select -Last 1).Line
        $hl  = ($t | Select-String 'helper: zero-copy' | Select -Last 1).Line
        $o   = ($t | Select-String '^output' | Select -Last 1).Line
        $ex  = ($t | Select-String '^EXIT=' | Select -Last 1).Line
        $oh  = if ($o) { [BitConverter]::ToString([Security.Cryptography.MD5]::Create().ComputeHash([Text.Encoding]::ASCII.GetBytes($o))).Replace('-', '').Substring(0, 10) } else { 'none' }
        L "[$tag] $ex out=$oh | $dec"
        L "[$tag]   $sp"
        L "[$tag]   $vw"
        L "[$tag]   $pm"
        L "[$tag]   $dp"
        if ($hl) { L "[$tag]   $hl" }
        Kill-Strata
    }
}
finally {
    Kill-Strata
    L "restoring llama-swap"
    Start-Service -Name llama-swap -EA Continue
    Start-Sleep 10
    L "llama-swap: $((Get-Service llama-swap).Status)"
    "=== s21 end $(Get-Date -Format 'HH:mm:ss') ===" | Add-Content $log
}
