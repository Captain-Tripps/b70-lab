# Host-RAM watchdog for llama-server on GPU-BOX.
#
# When a model does not fit in VRAM, the Windows GPU driver backs the overflow with system RAM
# instead of failing the allocation. On this 31 GB machine that drains memory at ~1.5 GB/s and
# hung GPU-BOX on 2026-09-27. This kills every llama-server.exe once free RAM stays below the floor,
# turning that failure into a failed request instead of a hung machine. llama-swap reloads the
# model on the next request.
#
# 2026-10-28: a kill now needs BOTH low available RAM and commit near physical RAM. Memory-mapped
# expert offload fills the working set with clean file pages, which Windows only trims when available
# is nearly zero, so available alone killed healthy runs at any floor while commit stayed ~9 GB under
# physical. The driver-backing failure grows commit, so it still trips the second condition.
#
# Runs as the scheduled task "llama-ram-watchdog" (at startup, SYSTEM). -DryRun logs without killing.
param(
    [double]$MinAvailGB = 6.0,
    [double]$CommitMarginGB = 4.0,
    [int]$ConsecutiveSamples = 2,
    [int]$PollMs = 1000,
    [int]$CooldownSec = 30,
    [string]$LogPath = 'C:\llama-swap\ram-watchdog.log',
    [switch]$DryRun,
    [int]$MaxSeconds = 0
)

$ErrorActionPreference = 'Continue'

function Write-Log([string]$msg) {
    try {
        if ((Test-Path $LogPath) -and (Get-Item $LogPath).Length -gt 5MB) {
            Move-Item $LogPath "$LogPath.1" -Force
        }
        "{0:yyyy-MM-dd HH:mm:ss} {1}" -f (Get-Date), $msg | Add-Content -Path $LogPath -Encoding utf8
    } catch { }
}

# AvailableBytes = free + standby (reclaimable). FreePhysicalMemory excludes standby, so mmap loads
# drove it to ~0 while tens of GB were usable and healthy loads got killed (2026-10-28).
function Get-Mem {
    try {
        $m = Get-CimInstance Win32_PerfRawData_PerfOS_Memory
        @{ Avail = $m.AvailableBytes / 1GB; Commit = $m.CommittedBytes / 1GB }
    } catch { @{ Avail = [double]::NaN; Commit = [double]::NaN } }
}

$physGB = (Get-CimInstance Win32_ComputerSystem).TotalPhysicalMemory / 1GB
$commitLimitGB = $physGB - $CommitMarginGB
Write-Log ("started: floor={0} GB, commit trip={1:N1} GB (phys {2:N1} - {3}), consecutive={4}, poll={5} ms, dryRun={6}, pid={7}" -f $MinAvailGB, $commitLimitGB, $physGB, $CommitMarginGB, $ConsecutiveSamples, $PollMs, [bool]$DryRun, $PID)
$below = 0
$lastKill = [datetime]::MinValue
$lastBeat = Get-Date
$lastLowNote = [datetime]::MinValue
$start = Get-Date

while ($true) {
    $mem = Get-Mem
    $avail = $mem.Avail
    $commit = $mem.Commit
    $lowAvail = -not [double]::IsNaN($avail) -and $avail -lt $MinAvailGB
    $highCommit = [double]::IsNaN($commit) -or $commit -gt $commitLimitGB
    if ($lowAvail -and $highCommit) { $below++ } else { $below = 0 }

    if ($lowAvail -and -not $highCommit -and ((Get-Date) - $lastLowNote).TotalSeconds -ge 60) {
        Write-Log ("low avail={0:N2} GB but commit={1:N1} GB under trip {2:N1} GB (reclaimable pages); not killing" -f $avail, $commit, $commitLimitGB)
        $lastLowNote = Get-Date
    }

    if ($below -ge $ConsecutiveSamples -and ((Get-Date) - $lastKill).TotalSeconds -ge $CooldownSec) {
        $procs = @(Get-Process -Name 'llama-server' -ErrorAction SilentlyContinue)
        $detail = ($procs | ForEach-Object { "pid={0} priv={1:N1}GB ws={2:N1}GB" -f $_.Id, ($_.PrivateMemorySize64 / 1GB), ($_.WorkingSet64 / 1GB) }) -join '; '
        if ($procs.Count -gt 0) {
            if ($DryRun) {
                Write-Log ("DRY-RUN would kill {0} llama-server (avail={1:N2} GB, commit={2:N1} GB): {3}" -f $procs.Count, $avail, $commit, $detail)
            } else {
                $procs | ForEach-Object { try { Stop-Process -Id $_.Id -Force -ErrorAction Stop } catch { } }
                Write-Log ("KILLED {0} llama-server (avail={1:N2} GB below {2} GB, commit={3:N1} GB above {4:N1} GB): {5}" -f $procs.Count, $avail, $MinAvailGB, $commit, $commitLimitGB, $detail)
            }
        } else {
            Write-Log ("low RAM (avail={0:N2} GB, commit={1:N1} GB) but no llama-server running; nothing to do" -f $avail, $commit)
        }
        $lastKill = Get-Date
        $below = 0
    }

    if (((Get-Date) - $lastBeat).TotalMinutes -ge 10) {
        Write-Log ("heartbeat: avail={0:N2} GB, commit={1:N1} GB, llama-server={2}" -f $avail, $commit, @(Get-Process -Name 'llama-server' -ErrorAction SilentlyContinue).Count)
        $lastBeat = Get-Date
    }
    if ($MaxSeconds -gt 0 -and ((Get-Date) - $start).TotalSeconds -ge $MaxSeconds) {
        Write-Log "exiting after MaxSeconds=$MaxSeconds"
        break
    }
    Start-Sleep -Milliseconds $PollMs
}
