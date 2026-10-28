# Invoke-NativeCommand.ps1 - run one native Windows process and emit a structured result.
#
# Why this exists (STEP-000):
#   The existing arm.ps1/kill-arm.ps1 pair owns *llama-server* lifecycle: it discovers an
#   endpoint, samples PDH counters and tears a model server down. That is the wrong tool for
#   running a build or a probe, because it assumes the thing it starts is a server with a port.
#   A build runner needs the opposite properties: explicit cwd, an argument array with no shell
#   in the middle, the real exit code, both streams captured to files, a hard timeout that also
#   cleans up the children, and a machine-readable record another agent can read back.
#
# Design rules, all of them taken from failures recorded in ../hardware-and-windows-notes.md
# and from arm.ps1's comments:
#   - No shell-string assembly. Arguments are an array and are passed to ProcessStartInfo's
#     ArgumentList. A caller must never be able to inject a command by putting a quote in a
#     path. (There is no `cmd /c "<string>"` anywhere in this file.)
#   - Paths with spaces and non-ASCII characters are ordinary, not a special case.
#   - The exit code is the process's own. A timeout is a *separate* outcome, not exit code 1.
#   - stdout and stderr go to files under a unique run directory so a large build log does not
#     sit in memory and does not vanish when the caller's session dies.
#   - PowerShell 5.1 on Windows is the baseline. No ternary, no ??, no -Parallel.
#
# Usage:
#   powershell.exe -NoProfile -ExecutionPolicy Bypass -File Invoke-NativeCommand.ps1 `
#       -FilePath <exe> -Arguments <string[]> -WorkingDirectory <dir> [-TimeoutSeconds 600] `
#       -RunDirectory <dir> [-Label <name>] [-RecordArguments] [-EmitJson]
#
#   Or dot-source and call Invoke-NativeCommand directly (the mock suite does this).
#
# Output: a JSON object written to <RunDirectory>/result.json, and to stdout with -EmitJson.
# The object is the contract; logs are referenced by path, never inlined.

[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$FilePath,
    # Arguments arrive via a JSON *file*, not as a parameter value.
    # Two reasons, both learned by running this on GPU-BOX:
    #   1. `powershell.exe -File` cannot bind an array parameter from separate tokens.
    #   2. Windows PowerShell 5.1 does not escape embedded double quotes when passing an
    #      argument to a native executable, so a JSON string on the command line arrives
    #      mangled the moment an argument contains a quote or a space-heavy path.
    # A file sidesteps native quoting entirely, and a long compiler argv does not have to fit
    # in a command line. -ArgumentsJson is kept for short, quote-free argv.
    [string]$ArgumentsJsonPath = '',
    [string]$ArgumentsJson = '[]',
    [string[]]$Arguments = @(),
    [Parameter(Mandatory = $true)][string]$WorkingDirectory,
    [int]$TimeoutSeconds = 600,
    [string]$RunDirectory = '',
    [string]$Label = 'run',
    # Keep the full argv in the record only when the caller says it is safe. A build command is
    # safe; a command that carries a token is not, and the caller knows which it has.
    [switch]$RecordArguments,
    [switch]$EmitJson
)

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'

function ConvertTo-Win32ArgumentString {
    param([string[]]$ArgList)
    # ProcessStartInfo.ArgumentList is a .NET Core API. GPU-BOX runs Windows PowerShell 5.1 on
    # .NET Framework 4.0, where only the single-string .Arguments property exists, so the argv
    # has to be quoted here according to the rules CommandLineToArgvW actually uses:
    #   - an argument containing space, tab or a quote is wrapped in double quotes
    #   - a run of backslashes immediately before a closing quote is doubled, plus one more
    #   - an embedded double quote is escaped with a backslash
    # Getting this wrong is how a path with spaces silently becomes two arguments, so it is
    # implemented rather than avoided by forbidding spaces.
    if (-not $ArgList -or $ArgList.Count -eq 0) { return '' }

    $parts = New-Object System.Collections.ArrayList
    foreach ($rawArg in $ArgList) {
        $arg = [string]$rawArg
        $needsQuote = ($arg -eq '') -or ($arg -match '[\s"]')
        if (-not $needsQuote) {
            [void]$parts.Add($arg)
            continue
        }

        $sb = New-Object System.Text.StringBuilder
        [void]$sb.Append('"')
        $backslashes = 0
        foreach ($ch in $arg.ToCharArray()) {
            if ($ch -eq '\\') {
                $backslashes += 1
                continue
            }
            if ($ch -eq '"') {
                # Double the pending backslashes, then escape the quote itself.
                [void]$sb.Append('\' * ($backslashes * 2 + 1))
                [void]$sb.Append('"')
                $backslashes = 0
                continue
            }
            if ($backslashes -gt 0) {
                [void]$sb.Append('\' * $backslashes)
                $backslashes = 0
            }
            [void]$sb.Append($ch)
        }
        # Trailing backslashes precede the closing quote, so they must all be doubled.
        if ($backslashes -gt 0) { [void]$sb.Append('\' * ($backslashes * 2)) }
        [void]$sb.Append('"')
        [void]$parts.Add($sb.ToString())
    }
    return ($parts -join ' ')
}

function New-RunDirectory {
    param([string]$Base, [string]$Tag)
    if ($Base) {
        $dir = $Base
    } else {
        $stamp = (Get-Date).ToUniversalTime().ToString('yyyyMMddTHHmmssZ')
        $safeTag = ($Tag -replace '[^A-Za-z0-9_.-]', '_')
        $dir = Join-Path ([System.IO.Path]::GetTempPath()) ("b70-run-$safeTag-$stamp-$PID")
    }
    if (-not (Test-Path -LiteralPath $dir)) {
        New-Item -ItemType Directory -Path $dir -Force | Out-Null
    }
    return (Resolve-Path -LiteralPath $dir).ProviderPath
}

function Resolve-Executable {
    param([string]$Path, [string]$WorkingDir)
    # Accept an absolute path, a path relative to the working directory, or a bare name on PATH.
    if ([System.IO.Path]::IsPathRooted($Path)) { return $Path }
    $joined = Join-Path $WorkingDir $Path
    if (Test-Path -LiteralPath $joined) { return (Resolve-Path -LiteralPath $joined).ProviderPath }
    $onPath = Get-Command $Path -ErrorAction SilentlyContinue
    if ($onPath) { return $onPath.Source }
    return $Path
}

function Get-ProcessTreeIds {
    param([int]$RootId)
    # Windows has no process groups, so children are discovered by walking ParentProcessId.
    # This is deliberately NOT `Stop-Process -Name ...`: a name match would kill an unrelated
    # production server that happens to share the executable name.
    # NB: the loop variable is $procId, never $id - $id is a built-in alias for $PID and
    # shadowing it here would make the "do not kill myself" guard compare against a child.
    $all = @(Get-CimInstance Win32_Process -ErrorAction SilentlyContinue)
    $byParent = @{}
    foreach ($p in $all) {
        $parent = [int]$p.ParentProcessId
        if (-not $byParent.ContainsKey($parent)) {
            $byParent[$parent] = New-Object System.Collections.ArrayList
        }
        [void]$byParent[$parent].Add([int]$p.ProcessId)
    }
    $ordered = New-Object System.Collections.ArrayList
    $stack = New-Object System.Collections.Stack
    $stack.Push($RootId)
    while ($stack.Count -gt 0) {
        $cur = $stack.Pop()
        [void]$ordered.Add($cur)
        if ($byParent.ContainsKey($cur)) {
            foreach ($c in $byParent[$cur]) { $stack.Push($c) }
        }
    }
    return @($ordered)
}

function Stop-ProcessTree {
    param([int]$RootId)
    $tree = @(Get-ProcessTreeIds -RootId $RootId)
    [array]::Reverse($tree)   # deepest-first, so a parent cannot respawn a child
    $killed = New-Object System.Collections.ArrayList
    foreach ($procId in $tree) {
        if ($procId -eq $PID) { continue }
        $proc = Get-Process -Id $procId -ErrorAction SilentlyContinue
        if ($proc) {
            try {
                Stop-Process -Id $procId -Force -ErrorAction Stop
                [void]$killed.Add($procId)
            } catch { }
        }
    }
    return @($killed)
}

# Buffers are created outside try/finally so the finally block always has something to write,
# even when an exception fires before the child starts.
$stdoutBuf = New-Object System.Text.StringBuilder
$stderrBuf = New-Object System.Text.StringBuilder
$proc = $null
$subscribers = New-Object System.Collections.ArrayList

# Resolve the effective argv once. Precedence: file, then inline JSON, then array.
$effectiveArgs = @()
$jsonSource = $null
$jsonText = $null
if ($ArgumentsJsonPath) {
    if (-not (Test-Path -LiteralPath $ArgumentsJsonPath)) {
        Write-Error "ArgumentsJsonPath does not exist: $ArgumentsJsonPath"
        exit 4
    }
    $jsonSource = 'file'
    $jsonText = Get-Content -LiteralPath $ArgumentsJsonPath -Raw -Encoding UTF8
} elseif ($ArgumentsJson -and $ArgumentsJson.Trim() -ne '' -and $ArgumentsJson.Trim() -ne '[]') {
    $jsonSource = 'inline'
    $jsonText = $ArgumentsJson
}

if ($jsonSource) {
    try {
        $parsed = $jsonText | ConvertFrom-Json
        if ($null -ne $parsed) { $effectiveArgs = @($parsed) }
    } catch {
        Write-Error "argument JSON is not valid ($jsonSource): $($_.Exception.Message)"
        exit 4
    }
} elseif ($Arguments -and $Arguments.Count -gt 0) {
    $effectiveArgs = @($Arguments)
}

$runDir = New-RunDirectory -Base $RunDirectory -Tag $Label
$stdoutPath = Join-Path $runDir 'stdout.log'
$stderrPath = Join-Path $runDir 'stderr.log'
$resultPath = Join-Path $runDir 'result.json'

$resolvedExe = Resolve-Executable -Path $FilePath -WorkingDir $WorkingDirectory
$startedAt = (Get-Date).ToUniversalTime()
$sw = [System.Diagnostics.Stopwatch]::StartNew()

$result = [ordered]@{
    schema_version = 1
    label          = $Label
    executable     = $resolvedExe
    working_dir    = $WorkingDirectory
    arguments      = if ($RecordArguments) { @($effectiveArgs) } else { $null }
    arguments_note = if ($RecordArguments) { $null } else { 'omitted; pass -RecordArguments when argv is not secret-bearing' }
    run_directory  = $runDir
    stdout_path    = $stdoutPath
    stderr_path    = $stderrPath
    started_at     = $startedAt.ToString('o')
    finished_at    = $null
    duration_ms    = $null
    exit_code      = $null
    timed_out      = $false
    outcome        = 'NOT_RUN'
    error          = $null
    killed_pids    = @()
    child_pid      = $null
}

try {
    if (-not (Test-Path -LiteralPath $WorkingDirectory)) {
        throw "working directory does not exist: $WorkingDirectory"
    }
    if (-not (Test-Path -LiteralPath $resolvedExe)) {
        throw "executable not found: $resolvedExe"
    }

    $psi = New-Object System.Diagnostics.ProcessStartInfo
    $psi.FileName = $resolvedExe
    $psi.WorkingDirectory = (Resolve-Path -LiteralPath $WorkingDirectory).ProviderPath
    $psi.UseShellExecute = $false
    $psi.CreateNoWindow = $true
    $psi.RedirectStandardOutput = $true
    $psi.RedirectStandardError = $true
    # One quoted command line, built by the Win32 rules above. There is still no shell involved:
    # CreateProcess receives this string and the child parses it with CommandLineToArgvW.
    $psi.Arguments = ConvertTo-Win32ArgumentString -ArgList $effectiveArgs

    $proc = New-Object System.Diagnostics.Process
    $proc.StartInfo = $psi

    # Async reads keep a chatty build from deadlocking on a full pipe buffer. The handlers run
    # in the same runspace, so appending to the script-scope buffers is safe here.
    $outSub = Register-ObjectEvent -InputObject $proc -EventName OutputDataReceived -MessageData $stdoutBuf -Action {
        if ($null -ne $Event.SourceEventArgs.Data) {
            [void]$Event.MessageData.AppendLine($Event.SourceEventArgs.Data)
        }
    }
    $errSub = Register-ObjectEvent -InputObject $proc -EventName ErrorDataReceived -MessageData $stderrBuf -Action {
        if ($null -ne $Event.SourceEventArgs.Data) {
            [void]$Event.MessageData.AppendLine($Event.SourceEventArgs.Data)
        }
    }
    [void]$subscribers.Add($outSub)
    [void]$subscribers.Add($errSub)

    [void]$proc.Start()
    $result.child_pid = $proc.Id
    $proc.BeginOutputReadLine()
    $proc.BeginErrorReadLine()

    $completed = $proc.WaitForExit($TimeoutSeconds * 1000)

    if (-not $completed) {
        $result.timed_out = $true
        $result.outcome = 'TIMEOUT'
        $result.killed_pids = @(Stop-ProcessTree -RootId $proc.Id)
        [void]$proc.WaitForExit(5000)
    } else {
        $result.exit_code = $proc.ExitCode
        if ($proc.ExitCode -eq 0) { $result.outcome = 'PASS' } else { $result.outcome = 'FAIL' }
    }
}
catch {
    $result.outcome = 'ERROR'
    $result.error = $_.Exception.Message
}
finally {
    $sw.Stop()
    $result.finished_at = (Get-Date).ToUniversalTime().ToString('o')
    $result.duration_ms = [int]$sw.ElapsedMilliseconds

    foreach ($sub in $subscribers) {
        Unregister-Event -SourceIdentifier $sub.Name -ErrorAction SilentlyContinue
    }

    # Streams are written after the fact from the captured buffers. If the process was killed
    # mid-line the last partial line is still useful, so it is written as-is.
    try { Set-Content -LiteralPath $stdoutPath -Value $stdoutBuf.ToString() -Encoding UTF8 } catch { }
    try { Set-Content -LiteralPath $stderrPath -Value $stderrBuf.ToString() -Encoding UTF8 } catch { }

    $json = $result | ConvertTo-Json -Depth 6
    try { Set-Content -LiteralPath $resultPath -Value $json -Encoding UTF8 } catch { }
    if ($EmitJson) { Write-Output $json }
}

# Exit code of THIS script reflects the outcome so a shell caller can branch on it:
#   0 = child exited 0, 2 = child exited nonzero, 3 = timeout, 4 = error before/around the child.
switch ($result.outcome) {
    'PASS'    { exit 0 }
    'FAIL'    { exit 2 }
    'TIMEOUT' { exit 3 }
    default   { exit 4 }
}
