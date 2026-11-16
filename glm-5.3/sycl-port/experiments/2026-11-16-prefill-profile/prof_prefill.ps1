param([Parameter(Mandatory=$true)][string]$Case, [string]$Tag = 'vt', [switch]$NoVtune)
# Prompt read of the live build (CLI, live env + prompt args, speculation off, 1 new token), optionally under VTune
# gpu-offload. GLM must be unloaded from llama-swap first.
$ErrorActionPreference='Stop'
$Work='<work>'
$dir="$Work\experiments\claude-glm-prefill-prof-20261116"
New-Item -ItemType Directory -Force $dir | Out-Null
$in="$Work\$Case.txt"
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
Set-Location $Work\maya
$exe="$Work\rt-glm-esimd-iq2s-20261116\generate.exe"
$gen=@('--glm-pack', "$Work\glm-m\pack", '--tokens-file', $in, '--max-new', '1', '--max-context', '131072', '--greedy',
       '--expert-cache', 'auto', '--layer-split', '14,25,36', '--prefill', '1536')
if ($NoVtune) { $file=$exe; $args=$gen }
else {
  $file='C:\Program Files (x86)\Intel\oneAPI\vtune\latest\bin64\vtune.exe'
  $args=@('-collect', 'gpu-offload', '-r', "$dir\$Case-$Tag-r", '--', $exe) + $gen
}
$t0=Get-Date
$p = Start-Process -FilePath $file -ArgumentList $args -NoNewWindow -Wait -PassThru -RedirectStandardOutput "$dir\$Case-$Tag-out.txt" -RedirectStandardError "$dir\$Case-$Tag-err.txt"
"$Case-$Tag EXIT $($p.ExitCode) wall $([int]((Get-Date)-$t0).TotalSeconds) s"
