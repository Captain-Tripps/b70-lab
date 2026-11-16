param([Parameter(Mandatory=$true)][string]$Case, [Parameter(Mandatory=$true)][string]$Exe, [string]$Esimd = '', [Parameter(Mandatory=$true)][string]$Tag)
# Teacher-forced logit dump (64 positions, speculation off) with the live engine env and live prompt args
$ErrorActionPreference='Stop'
$Work='<work>'
$dir="$Work\experiments\claude-glm-l12-20261115\kl"
New-Item -ItemType Directory -Force $dir | Out-Null
$val="$Work\experiments\codex-sub768-validation-20261110"
$in=if ($Case -eq 'long32k') {"$Work\long32k.txt"} else {"$val\$Case.txt"}
$running=Invoke-RestMethod <proxy>/running -TimeoutSec 5
if (@($running.running).Count -gt 0) { throw 'swap is in use' }
if (Get-CimInstance Win32_Process | Where-Object { $_.Name -match '^(generate|llama-server)\.exe$' }) { throw 'another GPU model is running' }
Get-ChildItem Env: | Where-Object { $_.Name -match '^(MAYA_|STRATA_|GGML_|ONEAPI_DEVICE_SELECTOR|SYCL_|ZE_|ZES_|UR_)' } | ForEach-Object { Remove-Item "Env:$($_.Name)" }
$env:PATH="$Work\rt-live;C:\Windows\System32;C:\Windows;C:\Program Files (x86)\Intel\oneAPI\mkl\2026.0\bin;C:\Program Files (x86)\Intel\oneAPI\compiler\2026.0\bin"
$env:ONEAPI_DEVICE_SELECTOR='level_zero:0,1,2,3'
$env:MAYA_SYCL_LAYER_SYNC='0'; $env:STRATA_GLM_CPU_LANE='0'; $env:STRATA_GLM_RAM_GB='40'
$env:STRATA_GLM_RESIDENT_SKIP='1'; $env:STRATA_GLM_RESERVE_MB='400'; $env:ZES_ENABLE_SYSMAN='1'
$env:STRATA_GLM_CKPT_EVERY='65536'
$env:STRATA_GLM_NO_SPEC='1'
if ($Esimd -ne '') { $env:GGML_SYCL_MMID_ESIMD=$Esimd }
$env:STRATA_GLM_KL_DUMP="$dir\$Case-$Tag-logits.bin,64"
Set-Location $Work\maya
$t0=Get-Date
$ErrorActionPreference='Continue'; cmd.exe /d /c "`"$Exe`" --glm-pack $Work\glm-m\pack --tokens-file `"$in`" --max-new 1 --max-context 131072 --greedy --expert-cache auto --layer-split 14,25,36 --prefill 1536 > `"$dir\$Case-$Tag-out.txt`" 2> `"$dir\$Case-$Tag-err.txt`""
"$Case-$Tag EXIT $LASTEXITCODE wall $([int]((Get-Date)-$t0).TotalSeconds) s"
