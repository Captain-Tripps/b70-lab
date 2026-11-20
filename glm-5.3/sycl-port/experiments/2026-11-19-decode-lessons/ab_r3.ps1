param([int]$MaxNew = 768)
# GLM r3 A/B: CLI decode (t200 prompt, greedy) on the live exe vs the r3 exe + STRATA_GLM_MV_AL16=1 (16-lane Q6_K GEMV). Live config env.
# A = live, B = r3 + STRATA_GLM_MV_AL16=1. Order: warm B, then A B B A A B. Prints the decode stat line and a hash of the T lines.
$ErrorActionPreference = 'Stop'
$dir = 'D:\maya-sycl\experiments\claude-glm-r1-20261119'
$t200 = 'D:\maya-sycl\experiments\claude-glm-decode-prof-20261114\t200.txt'
$running = Invoke-RestMethod http://<swap>/running -TimeoutSec 5
if (@($running.running).Count -gt 0) { throw 'swap is in use' }
if (Get-CimInstance Win32_Process | Where-Object { $_.Name -match '^(generate|llama-server|maya-ds4|strata)\.exe$' }) { throw 'another GPU model is running' }
$cfg = Get-Content D:\maya-sycl\configs\glm-maya-sycl-128k.json -Raw | ConvertFrom-Json
$liveExe = 'D:\maya-sycl\experiments\claude-glm-l12-20261115\idlefix\link\generate.exe'
$r1Exe = "$dir\noroot\link\generate.exe"
Get-ChildItem Env: | Where-Object { $_.Name -match '^(MAYA_|STRATA_|ONEAPI_DEVICE_SELECTOR|SYCL_|ZE_|ZES_|UR_)' } | ForEach-Object { Remove-Item "Env:$($_.Name)" }
foreach ($p in $cfg.env.PSObject.Properties) { Set-Item "Env:$($p.Name)" $p.Value }
$env:PATH = ($cfg.lib_dirs -join ';') + ';C:\Windows\System32;C:\Windows'
Set-Location $cfg.cwd
$args0 = @($cfg.args) + @('--tokens-file', $t200, '--max-new', "$MaxNew", '--greedy')
function Run($tag, $exe, $grf) {
    if ($grf) { $env:STRATA_GLM_MV_AL16 = '1' } else { Remove-Item Env:STRATA_GLM_MV_AL16 -ErrorAction SilentlyContinue }
    $o = "$dir\$tag-out.txt"; $e = "$dir\$tag-err.txt"
    $p = Start-Process -FilePath $exe -ArgumentList $args0 -NoNewWindow -Wait -PassThru -RedirectStandardOutput $o -RedirectStandardError $e
    $stat = (Select-String -Path $e -Pattern 'glm stat: decode [0-9.]+ ms/tok \([0-9.]+ tok/s\)' | Select-Object -Last 1).Matches.Value
    $toks = (Get-Content $o | Where-Object { $_ -like 'T *' }) -join ','
    $h = [System.BitConverter]::ToString([System.Security.Cryptography.MD5]::Create().ComputeHash([Text.Encoding]::ASCII.GetBytes($toks))).Replace('-', '').Substring(0, 8)
    $n = @(Get-Content $o | Where-Object { $_ -like 'T *' }).Count
    "{0,-8} exit {1} | {2} | {3} tokens {4}" -f $tag, $p.ExitCode, $stat, $n, $h
}
Run 'r3warmB' $r1Exe $true
Run 'r3A1' $liveExe $false
Run 'r3B1' $r1Exe $true
Run 'r3B2' $r1Exe $true
Run 'r3A2' $liveExe $false
Run 'r3A3' $liveExe $false
Run 'r3B3' $r1Exe $true
"done $(Get-Date -Format HH:mm:ss)"
