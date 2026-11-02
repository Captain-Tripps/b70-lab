# envrun.ps1 "K=V;K2=V2" tag : 768-token default MTP run with extra env, prints decode + spec prof lines
param([string]$Extra = "", [string]$Tag = "x", [int]$New = 768, [int]$To = 300)
$env:SEL = "level_zero:0,1,2,3"; $env:MAYA_SYCL_LAYER_SYNC = "0"; $env:STRATA_GLM_CPU_LANE = "0"; $env:STRATA_GLM_RAM_GB = "40"
$env:STRATA_GLM_NO_PREFILL = "1"; $env:STRATA_GLM_SPEC_PROF = "1"
if ($Extra) { foreach ($kv in $Extra.Split(";")) { $k, $v = $kv.Split("="); Set-Item "env:$k" $v } }
$env:MAYA_ARGS = "--glm-pack <work>\glm-m\pack --tokens-file <work>\prompt1.txt --max-new $New --max-context 2048 --greedy --expert-cache auto --layer-split 13,24,35"
$log = "<work>\env_$Tag.log"
$p = Start-Process cmd -ArgumentList '/c', "<work>\tools\maya_run_rt.cmd $log" -NoNewWindow -PassThru
if (-not $p.WaitForExit($To * 1000)) { Get-Process generate -EA SilentlyContinue | Stop-Process -Force; "[$Tag] TIMEOUT" }
$t = (Select-String -Path $log -Pattern "^T " | Measure-Object).Count
$same = ""; $ref = Get-Content <work>\hlw.log | Where-Object { $_ -match "^T " } | Select -First $t; $cur = Get-Content $log | Where-Object { $_ -match "^T " }
if ($ref.Count -gt 0) { $same = if ((Compare-Object $ref $cur -SyncWindow 0 | Measure-Object).Count -eq 0) { "tokens SAME" } else { "tokens DIFF" } }
"[$Tag] T=$t $same | " + ((Select-String -Path $log -Pattern "glm stat: decode").Line -replace "\|.*","")
(Select-String -Path $log -Pattern "glm spec prof").Line | % { "   " + $_.Substring(0,[math]::Min(170,$_.Length)) }
(Select-String -Path $log -Pattern "EXIT").Line
