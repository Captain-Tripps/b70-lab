param([int]$Seconds = 60, [string]$Out = '<bench dir>\map.csv')
# dedicated VRAM per adapter once a second (4 instances: cheap)
"t,instance,gb" | Set-Content $Out
Get-Counter -Counter '\GPU Adapter Memory(*)\Dedicated Usage' -SampleInterval 1 -MaxSamples $Seconds | ForEach-Object {
  $t = $_.Timestamp.ToString('HH:mm:ss')
  $_.CounterSamples | ForEach-Object { "$t,$($_.InstanceName),$([math]::Round($_.CookedValue/1GB,2))" } | Add-Content $Out
}
"done"
