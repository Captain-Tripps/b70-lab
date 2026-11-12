param(
    [ValidateSet(2048,32768,100000)][Parameter(Mandatory=$true)][int]$Depth,
    [ValidateSet('off','on')][Parameter(Mandatory=$true)][string]$Profile,
    [ValidateSet('mtp','target')][string]$Mode = 'mtp',
    [ValidateRange(1,9)][int]$Repeat = 1
)
$ErrorActionPreference = 'Stop'
$root = 'D:\maya-sycl'; $dir = Join-Path $root 'experiments\codex-glm-attention-depth-20261112'
$exe = Join-Path $root 'rt-glm-branch-20261112\generate.exe'; $proxy = 'http://100.89.126.50:8080'
$expected = 'f89820fe92e49ffa6e563b538d5dc5aebe9b246e95d29d523f3e76f0ed0acea8'
$inputFile = Join-Path $dir "input-$Depth.txt"
$hashes = @{2048='359bb29c58f1505af40dae1511f7290eaf40a09c053f6a03771d4765f0de73c3';32768='16d3c24eaaa0ec5e5c79239a7a198cd65f20f0c04bc414837e41594ac3387008';100000='c0300cba764e8905f4c5f5982fa29f2ff97e3922a44a9d16cbc603b4c48b6c26'}
if ((Get-FileHash -LiteralPath $exe -Algorithm SHA256).Hash -ne $expected) { throw 'Unexpected promoted executable' }
if ((Get-FileHash -LiteralPath $inputFile -Algorithm SHA256).Hash -ne $hashes[$Depth]) { throw 'Unexpected input token file' }
if (@((Invoke-RestMethod "$proxy/running" -TimeoutSec 5).running).Count -gt 0) { throw 'Proxy has a loaded model' }
if (Get-CimInstance Win32_Process | Where-Object { $_.Name -in @('generate.exe','llama-server.exe') }) { throw 'Another model engine is active' }
$g = @((Get-Counter '\GPU Adapter Memory(*)\Dedicated Usage').CounterSamples | Where-Object { $_.InstanceName -notmatch '0x000159ed' } | ForEach-Object { $_.CookedValue / 1GB })
if ($g.Count -lt 4 -or ($g | Measure-Object -Maximum).Maximum -gt 1.2) { throw 'GPU memory is not clear' }
$tag = if ($Mode -eq 'mtp') { "$Depth-$Profile" } else { "$Depth-$Mode-$Profile" }
if ($Repeat -ne 1) { $tag += "-r$Repeat" }
$out = Join-Path $dir "$tag.out.log"; $err = Join-Path $dir "$tag.err.log"
if ((Test-Path $out) -or (Test-Path $err)) { throw 'Refusing to overwrite existing logs' }
Get-ChildItem Env: | Where-Object { $_.Name -match '^(MAYA_|STRATA_|ONEAPI_DEVICE_SELECTOR|SYCL_|ZE_|ZES_|UR_)' } | ForEach-Object { Remove-Item "Env:$($_.Name)" }
$env:PATH = "$root\rt-live;C:\Windows\System32;C:\Windows;C:\Program Files (x86)\Intel\oneAPI\mkl\2026.0\bin;C:\Program Files (x86)\Intel\oneAPI\compiler\2026.0\bin"
$env:ONEAPI_DEVICE_SELECTOR='level_zero:0,1,2,3'; $env:MAYA_SYCL_LAYER_SYNC='0'
$env:STRATA_GLM_CPU_LANE='0'; $env:STRATA_GLM_RAM_GB='40'; $env:STRATA_GLM_RESIDENT_SKIP='1'
$env:STRATA_GLM_RESERVE_MB='400'; $env:ZES_ENABLE_SYSMAN='1'; $env:STRATA_GLM_SPEC_PROF='1'
$env:STRATA_GLM_SLOT_RAM_GB='12'; $env:STRATA_GLM_SLOTS='8'; $env:STRATA_GLM_SLOT_KEEP_BRANCH='1'
if ($Profile -eq 'on') { $env:STRATA_GLM_PROF='8' }
if ($Mode -eq 'target') { $env:STRATA_GLM_NO_SPEC='1' }
$argsList = @('--glm-pack',"$root\glm-m\pack",'--tokens-file',$inputFile,'--max-new','128',
              '--max-context','131072','--greedy','--expert-cache','auto','--layer-split','14,25,36','--prefill','768')
$p = Start-Process -FilePath $exe -ArgumentList $argsList -WorkingDirectory "$root\maya" -RedirectStandardOutput $out -RedirectStandardError $err -WindowStyle Hidden -PassThru
$null = $p.Handle
$deadline = (Get-Date).AddMinutes(15)
try {
    while (-not $p.HasExited) {
        if ((Get-Date) -gt $deadline) { throw 'Experiment timeout' }
        if (@((Invoke-RestMethod "$proxy/running" -TimeoutSec 5).running).Count -gt 0) { throw 'Proxy started a model; stopping isolated experiment' }
        if ((Get-CimInstance Win32_OperatingSystem).FreePhysicalMemory * 1KB -lt 16GB) { throw 'Available RAM below 16 GiB' }
        Start-Sleep -Seconds 2; $p.Refresh()
    }
    $p.WaitForExit()
    if ($p.ExitCode -ne 0) { throw "Engine exited with $($p.ExitCode)" }
    Write-Output "ARM_COMPLETE depth=$Depth mode=$Mode profile=$Profile repeat=$Repeat PID=$($p.Id) EXIT=$($p.ExitCode)"
} finally {
    if (-not $p.HasExited) { Stop-Process -Id $p.Id -Force -ErrorAction SilentlyContinue; $p.WaitForExit() }
}
