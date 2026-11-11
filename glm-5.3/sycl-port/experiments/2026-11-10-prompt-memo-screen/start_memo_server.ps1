$ErrorActionPreference='Stop'
$dir='<work>\experiments\codex-promptmemo-20261110'
$running=Invoke-RestMethod http://100.89.126.50:8080/running -TimeoutSec 5
if (@($running.running).Count -gt 0) { throw 'swap is in use' }
if (Get-CimInstance Win32_Process | Where-Object { $_.Name -match '^(generate|llama-server)\.exe$' }) { throw 'another GPU model is running' }
$gpu=@((Get-Counter '\GPU Adapter Memory(*)\Dedicated Usage').CounterSamples | Where-Object { $_.InstanceName -notmatch '0x000159ed' } | ForEach-Object { $_.CookedValue/1GB })
if ($gpu.Count -lt 4 -or ($gpu | Measure-Object -Maximum).Maximum -gt 1.2) { throw 'cards not clear' }
Get-ChildItem Env: | Where-Object { $_.Name -match '^(MAYA_|STRATA_|ONEAPI_DEVICE_SELECTOR|SYCL_|ZE_|ZES_|UR_)' } | ForEach-Object { Remove-Item "Env:$($_.Name)" }
$env:MAYA_PROMPT_MEMO_CONTROL_FILE="$dir\mode.txt"
Set-Location "$dir\overlay"
& <work>\venv\Scripts\python.exe -m serve.server --engine strata --config "$dir\server.json" --host 127.0.0.1 --port 9075
exit $LASTEXITCODE
