param([ValidateSet('off','on')][string]$Arm)
$ErrorActionPreference='Stop'
$dir='<work>\experiments\codex-xmx-bn48-20261110'
$running=Invoke-RestMethod http://100.89.126.50:8080/running -TimeoutSec 5
if (@($running.running).Count -gt 0) { throw 'swap is in use' }
if (Get-CimInstance Win32_Process | Where-Object { $_.Name -match '^(generate|llama-server)\.exe$' }) { throw 'another GPU model is running' }
$gpu=@((Get-Counter '\GPU Adapter Memory(*)\Dedicated Usage').CounterSamples | Where-Object { $_.InstanceName -notmatch '0x000159ed' } | ForEach-Object { $_.CookedValue/1GB })
if ($gpu.Count -lt 4 -or ($gpu | Measure-Object -Maximum).Maximum -gt 1.2) { throw 'cards not clear' }
Get-ChildItem Env: | Where-Object { $_.Name -match '^(MAYA_|STRATA_|ONEAPI_DEVICE_SELECTOR|SYCL_|ZE_|ZES_|UR_)' } | ForEach-Object { Remove-Item "Env:$($_.Name)" }
$env:PATH="<work>\rt-live;C:\Windows\System32;C:\Windows;C:\Program Files (x86)\Intel\oneAPI\mkl\2026.0\bin;C:\Program Files (x86)\Intel\oneAPI\compiler\2026.0\bin"
$env:ONEAPI_DEVICE_SELECTOR='level_zero:0,1,2,3'
$env:MAYA_SYCL_LAYER_SYNC='0'
$env:STRATA_GLM_CPU_LANE='0'
$env:STRATA_GLM_RAM_GB='40'
$env:STRATA_GLM_RESIDENT_SKIP='1'
$env:STRATA_GLM_RESERVE_MB='400'
$env:ZES_ENABLE_SYSMAN='1'
$env:STRATA_GLM_NO_SPEC='1'
$env:STRATA_GLM_KL_DUMP="$dir\$Arm-repeat2-logits.bin,64"
if ($Arm -eq 'on') { $env:STRATA_GLM_PREFILL_PROF='1' }
if ($Arm -eq 'on') { $env:MAYA_XMX_PROFILE='1' }
Set-Location <work>\maya
& <work>\experiments\codex-xmx-bn48-20261110\tree\link\generate.exe --glm-pack <work>\glm-m\pack --tokens-file <work>\long8k.txt --max-new 1 --max-context 131072 --greedy --expert-cache auto --layer-split 13,24,35 --prefill 768
Write-Output ("EXIT_CODE={0}" -f $LASTEXITCODE)
exit $LASTEXITCODE
