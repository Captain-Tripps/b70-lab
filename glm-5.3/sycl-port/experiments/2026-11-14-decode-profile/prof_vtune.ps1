param([string]$Tag = 'vtune', [int]$MaxNew = 300, [string]$Collect = 'gpu-offload')
# CLI decode of the live build under VTune; GLM must be unloaded from llama-swap first.
$dir='<work>\experiments\claude-glm-decode-prof-20261114'
$running=Invoke-RestMethod <proxy>/running -TimeoutSec 5
if (@($running.running).Count -gt 0) { throw 'swap is in use' }
if (Get-CimInstance Win32_Process | Where-Object { $_.Name -match '^(generate|llama-server)\.exe$' }) { throw 'another GPU model is running' }
Get-ChildItem Env: | Where-Object { $_.Name -match '^(MAYA_|STRATA_|ONEAPI_DEVICE_SELECTOR|SYCL_|ZE_|ZES_|UR_)' } | ForEach-Object { Remove-Item "Env:$($_.Name)" }
$env:PATH="<work>\rt-live;C:\Windows\System32;C:\Windows;C:\Program Files (x86)\Intel\oneAPI\mkl\2026.0\bin;C:\Program Files (x86)\Intel\oneAPI\compiler\2026.0\bin"
$env:ONEAPI_DEVICE_SELECTOR='level_zero:0,1,2,3'
$env:MAYA_SYCL_LAYER_SYNC='0'; $env:STRATA_GLM_CPU_LANE='0'; $env:STRATA_GLM_RAM_GB='40'
$env:STRATA_GLM_RESIDENT_SKIP='1'; $env:STRATA_GLM_RESERVE_MB='400'; $env:ZES_ENABLE_SYSMAN='1'
Set-Location <work>\maya
$vt='C:\Program Files (x86)\Intel\oneAPI\vtune\latest\bin64\vtune.exe'
$args=@('-collect', $Collect, '-r', "$dir\$Tag-r", '--', '<work>\rt-glm-slotreuse-20261113\generate.exe',
        '--glm-pack', '<work>\glm-m\pack', '--tokens-file', "$dir\t200.txt", '--max-new', "$MaxNew",
        '--max-context', '131072', '--greedy', '--expert-cache', 'auto', '--layer-split', '14,25,36', '--prefill', '1536')
$p = Start-Process -FilePath $vt -ArgumentList $args -NoNewWindow -Wait -PassThru -RedirectStandardOutput "$dir\$Tag-out.txt" -RedirectStandardError "$dir\$Tag-err.txt"
"EXIT $($p.ExitCode)"
