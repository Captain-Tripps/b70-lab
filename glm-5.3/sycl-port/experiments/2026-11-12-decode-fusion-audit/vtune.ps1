param([ValidateSet('off','on')][Parameter(Mandatory=$true)][string]$Arm)
$ErrorActionPreference = 'Stop'
$root = 'D:\maya-sycl'
$dir = Join-Path $root 'experiments\codex-decode-fusion-audit-20261112'
$exe = Join-Path $dir 'fused-tree\link\generate.exe'
$vtune = 'C:\Program Files (x86)\Intel\oneAPI\vtune\2026.0\bin64\vtune.exe'
$proxy = 'http://100.89.126.50:8080'
$expected = 'a33f023ca298a628807bfc74ec715760918d175907c50a3bb8ff69ddbd6eca44'
if ((Get-FileHash -LiteralPath $exe -Algorithm SHA256).Hash -ne $expected) { throw 'Unexpected experimental executable' }
if ((Invoke-RestMethod "$proxy/running" -TimeoutSec 5).running.Count -gt 0) { throw 'Proxy has a loaded model' }
if (Get-CimInstance Win32_Process | Where-Object { $_.Name -in @('generate.exe','llama-server.exe') }) { throw 'Another model engine is active' }
$g = @((Get-Counter '\GPU Adapter Memory(*)\Dedicated Usage').CounterSamples | Where-Object { $_.InstanceName -notmatch '0x000159ed' } | ForEach-Object { $_.CookedValue / 1GB })
if ($g.Count -lt 4 -or ($g | Measure-Object -Maximum).Maximum -gt 1.2) { throw 'GPU memory is not clear' }
$out = Join-Path $dir "vtune-$Arm.out.log"; $err = Join-Path $dir "vtune-$Arm.err.log"; $result = Join-Path $dir "vtune-$Arm.result"
if ((Test-Path $out) -or (Test-Path $err) -or (Test-Path $result)) { throw 'Refusing to overwrite existing results' }
Get-ChildItem Env: | Where-Object { $_.Name -match '^(MAYA_|STRATA_|ONEAPI_DEVICE_SELECTOR|SYCL_|ZE_|ZES_|UR_)' } | ForEach-Object { Remove-Item "Env:$($_.Name)" }
$env:PATH = "$root\rt-live;C:\Windows\System32;C:\Windows;C:\Program Files (x86)\Intel\oneAPI\mkl\2026.0\bin;C:\Program Files (x86)\Intel\oneAPI\compiler\2026.0\bin"
$env:ONEAPI_DEVICE_SELECTOR='level_zero:0,1,2,3'; $env:MAYA_SYCL_LAYER_SYNC='0'; $env:STRATA_GLM_CPU_LANE='0'
$env:STRATA_GLM_RAM_GB='40'; $env:STRATA_GLM_RESIDENT_SKIP='1'; $env:STRATA_GLM_RESERVE_MB='400'; $env:ZES_ENABLE_SYSMAN='1'
$env:STRATA_GLM_SLOT_RAM_GB='12'; $env:STRATA_GLM_SLOTS='8'; $env:STRATA_GLM_SLOT_KEEP_BRANCH='1'
if ($Arm -eq 'on') { $env:MAYA_MV_Q6_BF16_FUSED='1' }
$argsList = @('-collect','gpu-hotspots','-knob','gpu-profiling-mode=characterization','-knob','dump-compute-task-binaries=false',
              '-result-dir',$result,'--',$exe,'--glm-pack',"$root\glm-m\pack",'--tokens-file',"$root\prompt1.txt",
              '--max-new','128','--max-context','131072','--greedy','--expert-cache','auto','--layer-split','14,25,36','--prefill','768')
$p = Start-Process -FilePath $vtune -ArgumentList $argsList -WorkingDirectory "$root\maya" -RedirectStandardOutput $out -RedirectStandardError $err -WindowStyle Hidden -PassThru
$null = $p.Handle
$deadline = (Get-Date).AddMinutes(12)
try {
    while (-not $p.HasExited) {
        if ((Get-Date) -gt $deadline) { throw 'Experiment timeout' }
        if (@((Invoke-RestMethod "$proxy/running" -TimeoutSec 5).running).Count -gt 0) { throw 'Proxy started a model; stopping experiment' }
        if ((Get-CimInstance Win32_OperatingSystem).FreePhysicalMemory * 1KB -lt 16GB) { throw 'Available RAM below 16 GiB' }
        Start-Sleep -Seconds 2; $p.Refresh()
    }
    $p.WaitForExit()
    if ($p.ExitCode -ne 0) { throw "VTune exited with $($p.ExitCode)" }
    Write-Output "VTUNE_COMPLETE $Arm PID=$($p.Id) EXIT=$($p.ExitCode)"
} finally {
    if (-not $p.HasExited) { & taskkill.exe /PID $p.Id /T /F | Out-Null; $p.WaitForExit() }
}
