$ErrorActionPreference='Stop'
$dir='<work>\experiments\codex-sub768-validation-20261110'
$runner=Get-Content '<work>\experiments\codex-20261110\kl_arm.ps1' -Raw
foreach ($case in @('long32k')) {
  foreach ($arm in @('baseline','sub768')) {
    $input=if ($case -eq 'long32k') {'<work>\long32k.txt'} else {"$dir\$case.txt"}
    $script=$runner.Replace("`$dir='<work>\experiments\codex-20261110'", "`$dir='$dir'").Replace('<work>\long8k.txt',$input).Replace('"$dir\$Arm-logits.bin,64"', '"$dir\' + $case + '-repeat-$Arm-logits.bin,64"')
    $path="$dir\$case-repeat-$arm-run.ps1"; [IO.File]::WriteAllText($path,$script)
    & cmd.exe /d /c "powershell.exe -NoProfile -ExecutionPolicy Bypass -File `"$path`" -Arm $arm > `"$dir\$case-repeat-$arm.log`" 2>&1"
    $rc=$LASTEXITCODE; Add-Content "$dir\$case-repeat-$arm.log" "EXIT_CODE=$rc"
    if ($rc -ne 0) { throw "$case $arm failed $rc" }
  }
}
