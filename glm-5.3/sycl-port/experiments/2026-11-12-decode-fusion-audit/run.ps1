param([ValidateSet('off1b','on1','on2','off2','generic-off1','generic-on1','generic-on2','generic-off2')][Parameter(Mandatory=$true)][string]$Arm)
$ErrorActionPreference = 'Stop'
$root = 'D:\maya-sycl'
$dir = Join-Path $root 'experiments\codex-decode-fusion-audit-20261112'
$exe = Join-Path $root 'rt-glm-branch-20261112\generate.exe'
$proxy = 'http://100.89.126.50:8080'
$expected = 'f89820fe92e49ffa6e563b538d5dc5aebe9b246e95d29d523f3e76f0ed0acea8'
if ((Get-FileHash -LiteralPath $exe -Algorithm SHA256).Hash -ne $expected) { throw 'Unexpected promoted executable' }
if ((Invoke-RestMethod "$proxy/running" -TimeoutSec 5).running.Count -gt 0) { throw 'Proxy has a loaded model' }
if (Get-CimInstance Win32_Process | Where-Object { $_.Name -in @('generate.exe','llama-server.exe') }) { throw 'Another model engine is active' }
$g = @((Get-Counter '\GPU Adapter Memory(*)\Dedicated Usage').CounterSamples | Where-Object { $_.InstanceName -notmatch '0x000159ed' } | ForEach-Object { $_.CookedValue / 1GB })
if ($g.Count -lt 4 -or ($g | Measure-Object -Maximum).Maximum -gt 1.2) { throw 'GPU memory is not clear' }
$out = Join-Path $dir "$Arm.out.log"; $err = Join-Path $dir "$Arm.err.log"
if ((Test-Path $out) -or (Test-Path $err)) { throw 'Refusing to overwrite existing logs' }
Get-ChildItem Env: | Where-Object { $_.Name -match '^(MAYA_|STRATA_|ONEAPI_DEVICE_SELECTOR|SYCL_|ZE_|ZES_|UR_)' } | ForEach-Object { Remove-Item "Env:$($_.Name)" }
$env:PATH = "$root\rt-live;C:\Windows\System32;C:\Windows;C:\Program Files (x86)\Intel\oneAPI\mkl\2026.0\bin;C:\Program Files (x86)\Intel\oneAPI\compiler\2026.0\bin"
$env:ONEAPI_DEVICE_SELECTOR='level_zero:0,1,2,3'; $env:MAYA_SYCL_LAYER_SYNC='0'
$env:STRATA_GLM_CPU_LANE='0'; $env:STRATA_GLM_RAM_GB='40'; $env:STRATA_GLM_RESIDENT_SKIP='1'
$env:STRATA_GLM_RESERVE_MB='400'; $env:ZES_ENABLE_SYSMAN='1'
$env:STRATA_GLM_SLOT_RAM_GB='12'; $env:STRATA_GLM_SLOTS='8'; $env:STRATA_GLM_SLOT_KEEP_BRANCH='1'
$env:STRATA_GLM_SPEC_PROF='1'
if ($Arm -like 'on*') { $env:STRATA_GLM_PROF='8' }
if ($Arm -like 'generic-on*') { $env:STRATA_GLM_MV_GENERIC='1' }
$argsList = @('--glm-pack',"$root\glm-m\pack",'--tokens-file',"$root\prompt1.txt",'--max-new','256',
              '--max-context','131072','--greedy','--expert-cache','auto','--layer-split','14,25,36','--prefill','768')
$p = Start-Process -FilePath $exe -ArgumentList $argsList -WorkingDirectory "$root\maya" -RedirectStandardOutput $out -RedirectStandardError $err -WindowStyle Hidden -PassThru
$null = $p.Handle # Keep a process handle so PowerShell retains ExitCode after exit.
$deadline = (Get-Date).AddMinutes(12)
try {
    while (-not $p.HasExited) {
        if ((Get-Date) -gt $deadline) { throw 'Experiment timeout' }
        $running = Invoke-RestMethod "$proxy/running" -TimeoutSec 5
        if (@($running.running).Count -gt 0) { throw 'Proxy started a model; stopping isolated experiment' }
        if ((Get-CimInstance Win32_OperatingSystem).FreePhysicalMemory * 1KB -lt 16GB) { throw 'Available RAM below 16 GiB' }
        Start-Sleep -Seconds 2
        $p.Refresh()
    }
    $p.WaitForExit()
    if ($p.ExitCode -ne 0) { throw "Engine exited with $($p.ExitCode)" }
    Write-Output "ARM_COMPLETE $Arm PID=$($p.Id) EXIT=$($p.ExitCode)"
} finally {
    if (-not $p.HasExited) { Stop-Process -Id $p.Id -Force -ErrorAction SilentlyContinue; $p.WaitForExit() }
}
