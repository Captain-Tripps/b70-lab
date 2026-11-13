param([Parameter(Mandatory=$true)][string]$Script, [string]$Arg = '', [Parameter(Mandatory=$true)][string]$Log)
$ErrorActionPreference = 'Stop'
$root = 'D:\maya-sycl\experiments\codex-glm-ckpt-keep-20261113'
$py = 'D:\AI\Training\zeus-lora\.venv\Scripts\python.exe'
$cmd = "cmd.exe /c `"`"$py`" `"$root\$Script`" $Arg > `"$root\$Log`" 2>&1`""
$r = Invoke-CimMethod -ClassName Win32_Process -MethodName Create -Arguments @{ CommandLine = $cmd; CurrentDirectory = $root }
"ReturnValue=$($r.ReturnValue) PID=$($r.ProcessId)"
