# Runs Blender under a machine-wide cap of three instances, so parallel workers queue instead of thrashing (sixteen at
# once filled 85 of 96 GB and every core, and the desktop stopped responding). Each instance gets a third of the cores
# less a reserve, at below-normal priority, so the owner's desktop stays usable. Slots are named mutexes, so a killed
# run frees its slot. Usage: pwsh -File tools/Run-Blender.ps1 <blender args...>
# Blender's arguments come from the raw command line: a param block makes PowerShell parse Blender's flags (--out matches
# -OutVariable), and even $args drops the `--` that separates Blender's flags from the script's.
$raw = [Environment]::GetCommandLineArgs()
$self = [Array]::FindIndex($raw, [Predicate[string]] { param($a) $a -like '*Run-Blender.ps1' })
$BlenderArgs = if ($self -ge 0 -and $self -lt $raw.Count - 1) { $raw[($self + 1)..($raw.Count - 1)] } else { @() }

$ErrorActionPreference = 'Stop'
# The desktop pause (tools/Set-Pause.ps1) lives in the main worktree, shared by every worktree of the repository.
$common = git -C $PSScriptRoot rev-parse --path-format=absolute --git-common-dir 2>$null
$quietPattern = Join-Path (Split-Path -Parent ($common ?? $PSScriptRoot)) '.cache/refresh/*-quiet.txt'
if (Test-Path -Path $quietPattern) {
    Write-Output 'Local Blender is paused. Use tools/Run-Remote.ps1.'
    exit 1
}
$config = Join-Path $PSScriptRoot 'local-paths.json'
$paths = if (Test-Path -LiteralPath $config) { Get-Content -LiteralPath $config -Raw | ConvertFrom-Json }
$blender = $env:CENTURION_BLENDER ?? $paths.blender ?? ''
if (-not $blender) {
    $blender = (Get-Command blender -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1).Source
}
if (-not $blender) { throw 'Set blender in tools/local-paths.json or put Blender on PATH.' }
$slots = if ($env:CENTURION_REMOTE_BUILD -eq '1') { 1 } else { 3 }
$reserveCores = 4
$mutexes = [System.Threading.Mutex[]](0..($slots - 1) | ForEach-Object { [System.Threading.Mutex]::new($false, "Global\CenturionBlenderSlot$_") })
try { $held = [System.Threading.WaitHandle]::WaitAny($mutexes) }
catch {
    $e = $_.Exception
    while ($e -and $e -isnot [System.Threading.AbandonedMutexException]) { $e = $e.InnerException }
    if (-not $e) { throw }
    $held = $e.MutexIndex
}
try {
    if (Test-Path -Path $quietPattern) {
        Write-Output 'Local Blender is paused. Use tools/Run-Remote.ps1.'
        exit 1
    }
    $info = [System.Diagnostics.ProcessStartInfo]::new($blender)
    $info.UseShellExecute = $false
    $info.ArgumentList.Add('--threads')
    $info.ArgumentList.Add([string][math]::Max(1, [math]::Floor(([Environment]::ProcessorCount - $reserveCores) / $slots)))
    foreach ($a in $BlenderArgs) { $info.ArgumentList.Add($a) }
    $process = [System.Diagnostics.Process]::Start($info)
    $process.PriorityClass = [System.Diagnostics.ProcessPriorityClass]::BelowNormal
    $process.WaitForExit()
    $code = $process.ExitCode
}
finally { $mutexes[$held].ReleaseMutex() }
exit $code
