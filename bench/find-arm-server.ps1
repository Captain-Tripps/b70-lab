# find-arm-server.ps1 - locate the llama-server process owned by a bench arm.
#
# The --port token alone is not a safe identifier: a production llama-swap entry can collide
# with a misconfigured arm's port, and recording the wrong PID is how kill-arm would then
# murder the live service. The executable-path filter makes ownership structural: only a
# process started from inside the arm's own runtime directory can ever be recorded as ours.
function Get-ArmServerProcess {
    param(
        [Parameter(Mandatory = $true)][string]$Runtime,
        [Parameter(Mandatory = $true)][int]$Port
    )
    $candidates = @(Get-CimInstance Win32_Process -Filter "Name='llama-server.exe'" |
        Where-Object {
            $_.CommandLine -match ('-port\s+' + [regex]::Escape($Port) + '\b') -and
            $_.ExecutablePath -like ($Runtime + '*')
        })
    if ($candidates.Count -eq 0) { return $null }
    if ($candidates.Count -gt 1) {
        Write-Warning "more than one llama-server claims --port $Port under $Runtime (PIDs: $($candidates.ProcessId -join ', ')); taking the first"
    }
    return $candidates[0]
}
