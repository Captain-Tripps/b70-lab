# Boot entry point for the GPU keep-alive (a scheduled task: SYSTEM, at startup, restart on failure).
# Without it, ~65 s after a model's last request Windows moves its VRAM to system RAM on some of the B70s, and the next
# request waits ~50 s for it to come back. gpu_keepalive.py runs a tiny kernel on every card every 15 s; start it
# again if it ever exits. Minimal PATH: a junction on the normal PATH made torch's DLL load fail (WinError 448).
# <PY> = a Python with torch for Intel XPU (torch.xpu); <DIR> = where gpu_keepalive.py and the logs live.
$py  = '<PY>'
$dir = '<DIR>'
$log = "$dir\gpu-keepalive-boot.log"
function Log($m) { Add-Content $log ("{0:yyyy-MM-dd HH:mm:ss} {1}" -f (Get-Date), $m) }
$env:PATH = 'C:\Windows\System32;C:\Windows'
while ($true) {
    Log "starting keep-alive"
    & $py -u "$dir\gpu_keepalive.py" *>> "$dir\gpu-keepalive.out"
    Log "keep-alive exited with code $LASTEXITCODE; again in 30 s"
    Start-Sleep -Seconds 30
}
