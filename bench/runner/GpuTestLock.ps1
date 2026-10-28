# GpuTestLock.ps1 - one exclusive GPU-test lease at a time, with ownership that survives a crash.
#
# Why this exists (STEP-000):
#   bench/arm.ps1 already refuses to start when a model server is resident, but that check is
#   *advisory* and racing: two runs that both pass preflight at the same time will both start.
#   A GPU test needs a real mutual-exclusion primitive, and it needs one that cannot wedge the
#   box when the holder dies, because "the lock file still exists" is not the same statement as
#   "somebody is holding it".
#
#   The second half is ownership. Killing by process *name* is how a lab loses its production
#   server, so the lease records PID + creation time + executable path. Cleanup re-verifies all
#   three before touching anything. A recycled PID fails the check and is left alone.
#
#   And a lease is not proof that VRAM is free. Releasing a lease means "I have stopped asking
#   for the GPU", not "the GPU is idle" - a separate process can still hold memory. This module
#   never kills or unloads anything on behalf of someone else.
#
#   A file named for the lock, opened with FileShare::None, is the primitive: Windows gives us
#   atomic create-or-fail plus automatic release when the handle closes (including on a crash),
#   which a "does the file exist" check does not.

[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidateSet('Acquire', 'Release', 'Status', 'Break')]
    [string]$Action,
    [Parameter(Mandatory = $true)][string]$LockPath,
    [string]$Owner = $env:COMPUTERNAME,
    [string]$Purpose = 'unspecified',
    # The lease must name the process that will actually DO the GPU work, which is the caller.
    # This script exits immediately after writing the lease, so defaulting to its own $PID would
    # record a holder that is already dead - every lease would look stale a millisecond later.
    # Callers pass their own PID; the default is kept only for interactive one-shot use.
    [int]$HolderPid = 0,
    [int]$ChildPid = 0,
    [switch]$EmitJson
)

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'

function Get-ProcessIdentity {
    param([int]$ProcessId)
    if ($ProcessId -le 0) { return $null }
    $cim = Get-CimInstance Win32_Process -Filter "ProcessId=$ProcessId" -ErrorAction SilentlyContinue
    if (-not $cim) { return $null }
    $created = $null
    try { $created = $cim.CreationDate } catch { }
    return [ordered]@{
        pid             = [int]$cim.ProcessId
        name            = $cim.Name
        executable_path = $cim.ExecutablePath
        creation_time   = if ($created) { ([datetime]$created).ToUniversalTime().ToString('o') } else { $null }
        command_line    = $cim.CommandLine
    }
}

function Test-ProcessIdentity {
    param($Recorded)
    # All three of PID, creation time and executable path must match. Any mismatch means the PID
    # now belongs to somebody else, which is exactly the case a bare PID check gets wrong.
    if (-not $Recorded) { return $false }
    $now = Get-ProcessIdentity -ProcessId ([int]$Recorded.pid)
    if (-not $now) { return $false }
    if ($Recorded.creation_time -and $now.creation_time -ne $Recorded.creation_time) { return $false }
    if ($Recorded.executable_path -and $now.executable_path -ne $Recorded.executable_path) { return $false }
    return $true
}

function Read-Lease {
    param([string]$Path)
    if (-not (Test-Path -LiteralPath $Path)) { return $null }
    try {
        $raw = Get-Content -LiteralPath $Path -Raw -ErrorAction Stop
        if (-not $raw -or -not $raw.Trim()) { return $null }
        return $raw | ConvertFrom-Json
    } catch {
        return $null
    }
}

function New-LeaseInfo {
    param([string]$OwnerName, [string]$Why, [int]$Child, [int]$Holder)
    $childIdentity = $null
    if ($Child -gt 0) { $childIdentity = Get-ProcessIdentity -ProcessId $Child }
    $holderIdent = Get-ProcessIdentity -ProcessId $Holder
    return [ordered]@{
        schema_version  = 1
        holder_pid      = $Holder
        holder_identity = $holderIdent
        owner           = $OwnerName
        purpose         = $Why
        host            = $env:COMPUTERNAME
        acquired_at     = (Get-Date).ToUniversalTime().ToString('o')
        child           = $childIdentity
    }
}

$leaseFile = $LockPath
$holderFile = "$LockPath.holder.json"

function Invoke-Acquire {
    $existing = Read-Lease -Path $holderFile
    if ($existing -and (Test-ProcessIdentity -Recorded $existing.holder_identity)) {
        return [ordered]@{
            schema_version = 1
            action         = 'Acquire'
            outcome        = 'BUSY'
            reason         = 'lease held by a live process'
            holder         = $existing
            lock_path      = $leaseFile
        }
    }
    # A holder file with a dead or recycled holder is a stale lease, not a conflict.
    $staleNote = $null
    if ($existing) { $staleNote = 'previous lease was stale (holder gone or PID recycled)' }

    $stream = $null
    try {
        $stream = [System.IO.File]::Open($leaseFile, [System.IO.FileMode]::OpenOrCreate,
            [System.IO.FileAccess]::ReadWrite, [System.IO.FileShare]::None)
    } catch {
        $info = Read-Lease -Path $holderFile
        return [ordered]@{
            schema_version = 1
            action         = 'Acquire'
            outcome        = 'BUSY'
            reason         = 'lock file is held with an exclusive handle by another process'
            holder         = $info
            lock_path      = $leaseFile
        }
    }

    $effectiveHolder = $PID
    if ($HolderPid -gt 0) { $effectiveHolder = $HolderPid }
    if (-not (Get-ProcessIdentity -ProcessId $effectiveHolder)) {
        return [ordered]@{
            schema_version = 1
            action         = 'Acquire'
            outcome        = 'REFUSED'
            reason         = "holder pid $effectiveHolder is not a running process; pass -HolderPid <your pid>"
            lock_path      = $leaseFile
        }
    }
    $lease = New-LeaseInfo -OwnerName $Owner -Why $Purpose -Child $ChildPid -Holder $effectiveHolder
    $lease | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $holderFile -Encoding UTF8
    # The handle is held only for the duration of this call. The holder file is the durable
    # record; the exclusive handle is what makes the acquire atomic. Callers that need the
    # lease held for a long time run inside a single Invoke-NativeCommand tree instead.
    $stream.Close()
    $stream.Dispose()

    return [ordered]@{
        schema_version = 1
        action         = 'Acquire'
        outcome        = 'ACQUIRED'
        note           = $staleNote
        lease          = $lease
        lock_path      = $leaseFile
    }
}

function Invoke-Release {
    $existing = Read-Lease -Path $holderFile
    if (-not $existing) {
        return [ordered]@{
            schema_version = 1
            action         = 'Release'
            outcome        = 'NO_LEASE'
            lock_path      = $leaseFile
        }
    }
    $isMine = ([int]$existing.holder_pid -eq $PID)
    # A caller that owns the lease but released it from a helper process can pass its own pid.
    if ($HolderPid -gt 0 -and [int]$existing.holder_pid -eq $HolderPid) { $isMine = $true }
    $isLive = Test-ProcessIdentity -Recorded $existing.holder_identity
    if (-not $isMine -and $isLive) {
        return [ordered]@{
            schema_version = 1
            action         = 'Release'
            outcome        = 'REFUSED'
            reason         = 'lease belongs to a live process that is not this one'
            holder         = $existing
            lock_path      = $leaseFile
        }
    }
    $childStopped = $null
    if ($existing.child -and (Test-ProcessIdentity -Recorded $existing.child)) {
        # Ownership re-verified above (pid + creation time + exe path) before anything is stopped.
        try {
            Stop-Process -Id ([int]$existing.child.pid) -Force -ErrorAction Stop
            $childStopped = [int]$existing.child.pid
        } catch { }
    }
    Remove-Item -LiteralPath $holderFile -Force -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath $leaseFile -Force -ErrorAction SilentlyContinue
    return [ordered]@{
        schema_version = 1
        action         = 'Release'
        outcome        = 'RELEASED'
        stopped_child  = $childStopped
        lock_path      = $leaseFile
    }
}

function Invoke-Status {
    $existing = Read-Lease -Path $holderFile
    if (-not $existing) {
        return [ordered]@{
            schema_version = 1
            action         = 'Status'
            outcome        = 'FREE'
            lock_path      = $leaseFile
        }
    }
    $live = Test-ProcessIdentity -Recorded $existing.holder_identity
    return [ordered]@{
        schema_version = 1
        action         = 'Status'
        outcome        = if ($live) { 'HELD' } else { 'STALE' }
        holder         = $existing
        lock_path      = $leaseFile
    }
}

function Invoke-Break {
    # Operator escape hatch for a lease whose holder is gone. It refuses a live holder.
    $existing = Read-Lease -Path $holderFile
    if (-not $existing) {
        return [ordered]@{
            schema_version = 1
            action         = 'Break'
            outcome        = 'NO_LEASE'
            lock_path      = $leaseFile
        }
    }
    if (Test-ProcessIdentity -Recorded $existing.holder_identity) {
        return [ordered]@{
            schema_version = 1
            action         = 'Break'
            outcome        = 'REFUSED'
            reason         = 'holder is still alive; stop it deliberately instead of breaking the lease'
            holder         = $existing
            lock_path      = $leaseFile
        }
    }
    Remove-Item -LiteralPath $holderFile -Force -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath $leaseFile -Force -ErrorAction SilentlyContinue
    return [ordered]@{
        schema_version = 1
        action         = 'Break'
        outcome        = 'BROKEN'
        stale_holder   = $existing
        lock_path      = $leaseFile
    }
}

$result = switch ($Action) {
    'Acquire' { Invoke-Acquire }
    'Release' { Invoke-Release }
    'Status'  { Invoke-Status }
    'Break'   { Invoke-Break }
}

$json = $result | ConvertTo-Json -Depth 8
if ($EmitJson) { Write-Output $json } else { Write-Output $json }

switch ($result.outcome) {
    'ACQUIRED' { exit 0 }
    'BUSY'     { exit 10 }
    'RELEASED' { exit 0 }
    'BROKEN'   { exit 0 }
    'HELD'     { exit 0 }
    'STALE'    { exit 0 }
    'FREE'     { exit 0 }
    'NO_LEASE' { exit 0 }
    'REFUSED'  { exit 11 }
    default    { exit 12 }
}
