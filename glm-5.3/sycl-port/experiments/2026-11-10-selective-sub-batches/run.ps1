$ErrorActionPreference='Stop'
$dir='<work>\experiments\codex-sub768-selective-20261110'
$runner=Get-Content '<work>\experiments\codex-20261110\kl_arm.ps1' -Raw
$cases=@(@{case='long32k';label='baseline';arm='baseline';dense=$false},@{case='long32k';label='kda';arm='sub768';dense=$false},@{case='long32k';label='kda-dense';arm='sub768';dense=$true},@{case='code';label='kda-dense';arm='sub768';dense=$true})
foreach ($test in $cases) {
 $case=$test.case; $label=$test.label; $arm=$test.arm
 $input=if ($case -eq 'long32k') {'<work>\long32k.txt'} else {'<work>\experiments\codex-sub768-validation-20261110\code.txt'}
 $script=$runner.Replace("`$dir='<work>\experiments\codex-20261110'", "`$dir='$dir'").Replace('<work>\long8k.txt',$input).Replace('<work>\rt-live\generate.exe','<work>\experiments\codex-sub768-diagnosis-20261110\tree\link\generate.exe').Replace('"$dir\$Arm-logits.bin,64"', '"$dir\' + $case + '-' + $label + '-logits.bin,64"')
 if ($arm -eq 'sub768') { $extra="`$env:MAYA_DIAG_KDA_SUB512='1'`r`n"; if ($test.dense) { $extra+="`$env:MAYA_DIAG_DENSE_DEFAULT='1'`r`n" }; $script=$script.Replace('Set-Location <work>\maya', $extra+'Set-Location <work>\maya') }
 $path="$dir\$case-$label-run.ps1"; [IO.File]::WriteAllText($path,$script)
 & cmd.exe /d /c "powershell.exe -NoProfile -ExecutionPolicy Bypass -File `"$path`" -Arm $arm > `"$dir\$case-$label.log`" 2>&1"
 $rc=$LASTEXITCODE; Add-Content "$dir\$case-$label.log" "EXIT_CODE=$rc"
 if ($rc -ne 0) { throw "$case $label failed $rc" }
}
