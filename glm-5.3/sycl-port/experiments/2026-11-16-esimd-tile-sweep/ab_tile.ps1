param([Parameter(Mandatory=$true)][string]$Case, [Parameter(Mandatory=$true)][string]$Exe,
      [Parameter(Mandatory=$true)][string]$Tag, [int]$KLN = 64)
# One CLI prompt read with the live env (L5 indexer on) and prompt args, speculation off, 1 new token, dumping the
# last $KLN teacher-forced positions' logits for a byte compare. GLM must be unloaded.
$ErrorActionPreference='Stop'
$Work='<work>'
$dir="$Work\experiments\claude-glm-l12-20261115\tile"
New-Item -ItemType Directory -Force $dir | Out-Null
$in=if ($Case -eq 'code') {"$Work\experiments\codex-sub768-validation-20261110\code.txt"} else {"$Work\$Case.txt"}
$running=Invoke-RestMethod <proxy>/running -TimeoutSec 5
if (@($running.running).Count -gt 0) { throw 'swap is in use' }
if (Get-CimInstance Win32_Process | Where-Object { $_.Name -match '^(generate|llama-server)\.exe$' }) { throw 'another GPU model is running' }
Get-ChildItem Env: | Where-Object { $_.Name -match '^(MAYA_|STRATA_|GGML_|ONEAPI_DEVICE_SELECTOR|SYCL_|ZE_|ZES_|UR_)' } | ForEach-Object { Remove-Item "Env:$($_.Name)" }
$env:PATH="$Work\rt-live;C:\Windows\System32;C:\Windows;C:\Program Files (x86)\Intel\oneAPI\mkl\2026.0\bin;C:\Program Files (x86)\Intel\oneAPI\compiler\2026.0\bin"
$env:ONEAPI_DEVICE_SELECTOR='level_zero:0,1,2,3'
$env:MAYA_SYCL_LAYER_SYNC='0'; $env:STRATA_GLM_CPU_LANE='0'; $env:STRATA_GLM_RAM_GB='40'
$env:STRATA_GLM_RESIDENT_SKIP='1'; $env:STRATA_GLM_RESERVE_MB='400'; $env:ZES_ENABLE_SYSMAN='1'
$env:STRATA_GLM_CKPT_EVERY='65536'
$env:STRATA_GLM_DSA_XMX='1'
$env:STRATA_GLM_NO_SPEC='1'
$env:STRATA_GLM_KL_DUMP="$dir\$Case-$Tag-logits.bin,$KLN"
Set-Location $Work\maya
$t0=Get-Date
$ErrorActionPreference='Continue'
cmd.exe /d /c "`"$Exe`" --glm-pack $Work\glm-m\pack --tokens-file `"$in`" --max-new 1 --max-context 131072 --greedy --expert-cache auto --layer-split 14,25,36 --prefill 1536 > `"$dir\$Case-$Tag-out.txt`" 2> `"$dir\$Case-$Tag-err.txt`""
$ec=$LASTEXITCODE
$pf=(Select-String -Path "$dir\$Case-$Tag-err.txt" -Pattern 'glm prefill: \d+ tokens in ([\d.]+) ms' | ForEach-Object { $_.Matches[0].Groups[1].Value }) -join ' + '
$h=if (Test-Path "$dir\$Case-$Tag-logits.bin") { (Get-FileHash "$dir\$Case-$Tag-logits.bin" -Algorithm SHA256).Hash.Substring(0,16) } else { 'none' }
"$Case-$Tag EXIT $ec wall $([int]((Get-Date)-$t0).TotalSeconds) s prefill_ms $pf logits $h"
