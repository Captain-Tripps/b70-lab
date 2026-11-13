param([Parameter(Mandatory=$true)][string]$Arm)
$ErrorActionPreference = 'Stop'
$root = 'D:\maya-sycl\experiments\codex-glm-turn-trace-20261113'
$py = 'D:\AI\Training\zeus-lora\.venv\Scripts\python.exe'
$cmd = "cmd.exe /c `"`"$py`" `"$root\run_trace.py`" $Arm > `"$root\$Arm.out`" 2>&1`""
$r = Invoke-CimMethod -ClassName Win32_Process -MethodName Create -Arguments @{ CommandLine = $cmd; CurrentDirectory = $root }
"ReturnValue=$($r.ReturnValue) PID=$($r.ProcessId)"
