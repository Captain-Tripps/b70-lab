param([string]$Work = $env:MAYA_WORK, [string]$Proxy = $env:PROXY_URL, [Parameter(Mandatory=$true)][string]$Case, [Parameter(Mandatory=$true)][string]$Chunk, [Parameter(Mandatory=$true)][string]$Tag)
# Teacher-forced logit dump on the LIVE generate.exe with the live config's engine env (minus the slot/server-only keys).
$ErrorActionPreference='Stop'
$dir='$Work\experiments\claude-glm-chunk-screen-20261113\kl'
$val='$Work\experiments\codex-sub768-validation-20261110'
$input=if ($Case -eq 'long32k') {'$Work\long32k.txt'} else {"$val\$Case.txt"}
$running=Invoke-RestMethod $Proxy/running -TimeoutSec 5
if (@($running.running).Count -gt 0) { throw 'swap is in use' }
if (Get-CimInstance Win32_Process | Where-Object { $_.Name -match '^(generate|llama-server)\.exe$' }) { throw 'another GPU model is running' }
Get-ChildItem Env: | Where-Object { $_.Name -match '^(MAYA_|STRATA_|ONEAPI_DEVICE_SELECTOR|SYCL_|ZE_|ZES_|UR_)' } | ForEach-Object { Remove-Item "Env:$($_.Name)" }
$env:PATH="$Work\rt-live;C:\Windows\System32;C:\Windows;$env:ONEAPI_ROOT\mkl\2026.0\bin;$env:ONEAPI_ROOT\compiler\2026.0\bin"
$env:ONEAPI_DEVICE_SELECTOR='level_zero:0,1,2,3'
$env:MAYA_SYCL_LAYER_SYNC='0'
$env:STRATA_GLM_CPU_LANE='0'
$env:STRATA_GLM_RAM_GB='40'
$env:STRATA_GLM_RESIDENT_SKIP='1'
$env:STRATA_GLM_RESERVE_MB='400'
$env:ZES_ENABLE_SYSMAN='1'
$env:STRATA_GLM_NO_SPEC='1'
$env:STRATA_GLM_KL_DUMP="$dir\$Case-$Tag-logits.bin,64"
Set-Location $Work\maya
& $Work\rt-glm-slotreuse-20261113\generate.exe --glm-pack $Work\glm-m\pack --tokens-file $input --max-new 1 --max-context 131072 --greedy --expert-cache auto --layer-split 14,25,36 --prefill $Chunk
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
