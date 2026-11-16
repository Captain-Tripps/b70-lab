param([Parameter(Mandatory=$true)][string]$Run)
# Per card, per kernel GPU time table of one VTune gpu-offload result
$dir='<work>\experiments\claude-glm-prefill-prof-20261116'
$vt='C:\Program Files (x86)\Intel\oneAPI\vtune\latest\bin64\vtune.exe'
cmd.exe /d /c "`"$vt`" -report hotspots -group-by gpu-adapter,computing-task -format csv -csv-delimiter tab -r `"$dir\$Run-r`" > `"$dir\$Run-tasks.tsv`" 2> `"$dir\$Run-report-err.txt`""
cmd.exe /d /c "`"$vt`" -report summary -report-knob show-issues=false -r `"$dir\$Run-r`" > `"$dir\$Run-summary.txt`" 2>&1"
"report $Run exit $LASTEXITCODE"
