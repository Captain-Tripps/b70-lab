param([Parameter(Mandatory=$true)][string]$Exe, [Parameter(Mandatory=$true)][string]$Tag, [string]$TokFile = '<work>\experiments\claude-glm-decode-prof-20261114\t200.txt', [int]$MaxNew = 1500, [string]$Al = '')
# CLI greedy decode (spec path, live engine env) with STRATA_GLM_SPEC_PROF=1; tokens to <Tag>-out.txt, log to <Tag>-err.txt
$ErrorActionPreference='Stop'
$dir='<work>\experiments\claude-glm-q6al-20261114\ab'
New-Item -ItemType Directory -Force $dir | Out-Null
$running=Invoke-RestMethod <proxy>/running -TimeoutSec 5
if (@($running.running).Count -gt 0) { throw 'swap is in use' }
if (Get-CimInstance Win32_Process | Where-Object { $_.Name -match '^(generate|llama-server|q6bench)\.exe$' }) { throw 'another GPU job is running' }
Get-ChildItem Env: | Where-Object { $_.Name -match '^(MAYA_|STRATA_|ONEAPI_DEVICE_SELECTOR|SYCL_|ZE_|ZES_|UR_)' } | ForEach-Object { Remove-Item "Env:$($_.Name)" }
$env:PATH="<work>\rt-live;C:\Windows\System32;C:\Windows;C:\Program Files (x86)\Intel\oneAPI\mkl\2026.0\bin;C:\Program Files (x86)\Intel\oneAPI\compiler\2026.0\bin"
$env:ONEAPI_DEVICE_SELECTOR='level_zero:0,1,2,3'
$env:MAYA_SYCL_LAYER_SYNC='0'; $env:STRATA_GLM_CPU_LANE='0'; $env:STRATA_GLM_RAM_GB='40'
$env:STRATA_GLM_RESIDENT_SKIP='1'; $env:STRATA_GLM_RESERVE_MB='400'; $env:ZES_ENABLE_SYSMAN='1'
$env:STRATA_GLM_CKPT_EVERY='65536'
$env:STRATA_GLM_SPEC_PROF='1'
if ($Al -ne '') { $env:STRATA_GLM_MV_AL=$Al }
Set-Location <work>\maya
$t0=Get-Date
$ErrorActionPreference='Continue'; cmd.exe /d /c "`"$Exe`" --glm-pack <work>\glm-m\pack --tokens-file `"$TokFile`" --max-new $MaxNew --max-context 131072 --greedy --expert-cache auto --layer-split 14,25,36 --prefill 1536 > `"$dir\$Tag-out.txt`" 2> `"$dir\$Tag-err.txt`""
"EXIT $LASTEXITCODE wall $([int]((Get-Date)-$t0).TotalSeconds) s"
