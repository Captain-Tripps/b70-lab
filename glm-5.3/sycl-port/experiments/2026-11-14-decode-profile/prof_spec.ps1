param([string]$Tag = 'specprof')
$ErrorActionPreference='Stop'
$dir='<work>\experiments\claude-glm-decode-prof-20261114'
$running=Invoke-RestMethod <proxy>/running -TimeoutSec 5
if (@($running.running).Count -gt 0) { throw 'swap is in use' }
if (Get-CimInstance Win32_Process | Where-Object { $_.Name -match '^(generate|llama-server)\.exe$' }) { throw 'another GPU model is running' }
Get-ChildItem Env: | Where-Object { $_.Name -match '^(MAYA_|STRATA_|ONEAPI_DEVICE_SELECTOR|SYCL_|ZE_|ZES_|UR_)' } | ForEach-Object { Remove-Item "Env:$($_.Name)" }
$env:PATH="<work>\rt-live;C:\Windows\System32;C:\Windows;C:\Program Files (x86)\Intel\oneAPI\mkl\2026.0\bin;C:\Program Files (x86)\Intel\oneAPI\compiler\2026.0\bin"
$env:ONEAPI_DEVICE_SELECTOR='level_zero:0,1,2,3'
$env:MAYA_SYCL_LAYER_SYNC='0'; $env:STRATA_GLM_CPU_LANE='0'; $env:STRATA_GLM_RAM_GB='40'
$env:STRATA_GLM_RESIDENT_SKIP='1'; $env:STRATA_GLM_RESERVE_MB='400'; $env:ZES_ENABLE_SYSMAN='1'
$env:STRATA_GLM_SPEC_PROF='1'
Set-Location <work>\maya
$ErrorActionPreference='Continue'; cmd.exe /d /c "<work>\rt-glm-slotreuse-20261113\generate.exe --glm-pack <work>\glm-m\pack --tokens-file `"$dir\t200.txt`" --max-new 1500 --max-context 131072 --greedy --expert-cache auto --layer-split 14,25,36 --prefill 1536 > `"$dir\$Tag-out.txt`" 2> `"$dir\$Tag-err.txt`""
"EXIT $LASTEXITCODE"
