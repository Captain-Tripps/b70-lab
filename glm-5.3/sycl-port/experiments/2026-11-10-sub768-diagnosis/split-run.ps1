$ErrorActionPreference='Stop'
$dir='<work>\experiments\codex-sub768-splitout-20261110'
$runner=Get-Content '<work>\experiments\codex-20261110\kl_arm.ps1' -Raw
foreach ($arm in @('baseline','sub768')) {
 $script=$runner.Replace("`$dir='<work>\experiments\codex-20261110'", "`$dir='$dir'").Replace('<work>\long8k.txt','<work>\long32k.txt').Replace('<work>\rt-live\generate.exe','<work>\experiments\codex-sub768-diagnosis-20261110\tree\link\generate.exe')
 if ($arm -eq 'sub768') { $script=$script.Replace('Set-Location <work>\maya', "`$env:MAYA_DIAG_KDA_OUT_512='1'`r`nSet-Location <work>\maya") }
 $path="$dir\$arm-run.ps1"; [IO.File]::WriteAllText($path,$script)
 & cmd.exe /d /c "powershell.exe -NoProfile -ExecutionPolicy Bypass -File `"$path`" -Arm $arm > `"$dir\$arm.log`" 2>&1"
 $rc=$LASTEXITCODE; Add-Content "$dir\$arm.log" "EXIT_CODE=$rc"
 if ($rc -ne 0) { throw "$arm failed $rc" }
}
