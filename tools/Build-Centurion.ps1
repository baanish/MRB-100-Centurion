# Build-Centurion.ps1
#
# Builds the Centurion runtime DLL and the Blueprinter bundle, to gate G0.1 in docs/GATES.md.
# Passes only when Unity exits 0 with exactly one "[Centurion] Build complete: <nobp>" line, no
# "[Centurion] Captured build error" line, and the .nobp (and DLL, once src/ exists) is newer than
# this run's start. Then copies them to build/ with SHA256SUMS.txt. Every Unity log stays in
# build/logs/. The last line is always the verdict: "G0.1 PASS: ..." or "G0.1 FAIL: ...".
#
# The build authors the aircraft first (CenturionAuthor.Author) from the blockout export in
# art/export. -Blend re-exports it from a blockout .blend (tools/export_blockout.py) before building.
# If that changes the pinned bytes, update the manifest intentionally and rerun without -Blend.
# All exports, including the AWACS mount and cockpit, must match art/export-manifest.json.
# Export intentionally with tools/export_blockout.py, then pin with tools/export_manifest.py --write.
#
#   pwsh tools/Build-Centurion.ps1 -Blend .cache/art/blockout_s3/centurion_s3_retracted.blend
#   pwsh tools/Build-Centurion.ps1                                     # reuse the last export
#   pwsh tools/Build-Centurion.ps1 -ExecuteMethod Some.Other.Method   # exercise the failure path
#   pwsh tools/Build-Centurion.ps1 -Committed                         # DLL from HEAD's src/Centurion
#
# -Committed compiles the DLL from HEAD's src/Centurion, not the working tree: workers edit src/
# in this checkout, and a playtest DLL must carry only reviewed, committed code.

param(
    [string]$ExecuteMethod = 'Centurion.Editor.CenturionBuild.Build',
    [string]$UnityPath,
    [string]$Blend,
    [string]$BlenderPath = 'D:\SteamLibrary\steamapps\common\Blender\blender.exe',
    [switch]$Committed
)

$ErrorActionPreference = 'Stop'
# One build at a time machine-wide: parallel workers share the Unity project, the export folders and build/. A build
# that dies leaves the mutex abandoned, which the next one takes.
$buildLock = [System.Threading.Mutex]::new($false, 'Global\CenturionBuild')
try { [void]$buildLock.WaitOne() }
catch {
    $e = $_.Exception
    while ($e -and $e -isnot [System.Threading.AbandonedMutexException]) { $e = $e.InnerException }
    if (-not $e) { throw }
}
$repo = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$project = Join-Path $repo 'unity'
$build = Join-Path $repo 'build'
$logs = Join-Path $build 'logs'
New-Item -ItemType Directory -Force $logs | Out-Null
$runStart = [DateTime]::UtcNow
$clock = [Diagnostics.Stopwatch]::StartNew()
$deadline = [TimeSpan]::FromMinutes(15)
$licenseFailure = 'No valid Unity Editor license found'
$maxLicenseRetries = 3

function Fail([string]$why) {
    Write-Output "G0.1 FAIL: $why ($([int]$clock.Elapsed.TotalSeconds) s)"
    exit 1
}

if ($Blend) {
    $blendFile = (Resolve-Path -LiteralPath $Blend).Path
    & $BlenderPath --background --factory-startup --python-exit-code 1 --python (Join-Path $repo 'tools/export_blockout.py') -- --blend $blendFile |
        Where-Object { $_ -match '^\[export_blockout\]|Error|Traceback' } | Out-Host
    if ($LASTEXITCODE -ne 0) { Fail "blockout export of $blendFile exited $LASTEXITCODE" }
}
if (-not (Test-Path -LiteralPath (Join-Path $repo 'art/export/blockout.json'))) {
    Fail 'no blockout export in art/export; pass -Blend <blockout .blend>'
}
& python (Join-Path $repo 'tools/export_manifest.py')
if ($LASTEXITCODE -ne 0) { Fail 'exports do not match art/export-manifest.json' }

# Runtime DLL. The bundle serializes the DLL's MonoBehaviours by assembly and type name, so Unity
# must import the same build that ships beside the .nobp.
$csproj = Join-Path $repo 'src/Centurion/Centurion.csproj'
if ($Committed) {
    $snapshot = Join-Path $repo '.cache/build-head'
    & pwsh -NoProfile -File (Join-Path $repo 'tools/Remove-Generated.ps1') $snapshot | Out-Null
    if ($LASTEXITCODE -ne 0) { Fail "could not clear $snapshot" }
    New-Item -ItemType Directory -Force $snapshot | Out-Null
    $zip = Join-Path $repo '.cache/build-head.zip'
    & git -C $repo archive --format=zip -o $zip HEAD src/Centurion
    if ($LASTEXITCODE -ne 0) { Fail "git archive of HEAD's src/Centurion exited $LASTEXITCODE" }
    Expand-Archive -LiteralPath $zip -DestinationPath $snapshot -Force
    $csproj = Join-Path $snapshot 'src/Centurion/Centurion.csproj'
    Write-Output "dotnet: building HEAD $(git -C $repo rev-parse --short HEAD)'s src/Centurion"
}
$dll = $null
if (Test-Path -LiteralPath $csproj) {
    $dotnetOut = Join-Path $build 'dotnet'
    # --no-incremental: an up-to-date skip would leave a DLL older than this run.
    & dotnet build $csproj -c Release --no-incremental -o $dotnetOut --nologo | Out-Host
    if ($LASTEXITCODE -ne 0) { Fail "dotnet build exited $LASTEXITCODE" }
    $dll = Join-Path $dotnetOut 'Centurion.dll'
    if (-not (Test-Path -LiteralPath $dll) -or (Get-Item -LiteralPath $dll).LastWriteTimeUtc -lt $runStart) {
        Fail "dotnet build produced no fresh $dll"
    }
    $plugins = Join-Path $project 'Assets/Plugins'
    New-Item -ItemType Directory -Force $plugins | Out-Null
    Copy-Item -LiteralPath $dll -Destination $plugins -Force
    # The editor unloads Centurion.dll unless BepInEx and its own references resolve, and the
    # project's imported game assemblies don't include them. Blueprinter never bundles a .dll.
    $gameDir = if ($env:NUCLEAR_OPTION_DIR) { $env:NUCLEAR_OPTION_DIR } else { 'D:\SteamLibrary\steamapps\common\Nuclear Option' }
    $references = Join-Path $plugins 'BepInEx'
    New-Item -ItemType Directory -Force $references | Out-Null
    foreach ($name in 'BepInEx.dll', '0Harmony.dll', 'Mono.Cecil.dll', 'MonoMod.Utils.dll', 'MonoMod.RuntimeDetour.dll') {
        $source = Join-Path $gameDir "BepInEx/core/$name"
        $target = Join-Path $references $name
        if (-not (Test-Path -LiteralPath $target) -or (Get-FileHash -LiteralPath $source).Hash -ne (Get-FileHash -LiteralPath $target).Hash) {
            Copy-Item -LiteralPath $source -Destination $target -Force
        }
    }
    Write-Output "dotnet: built and copied Centurion.dll to unity/Assets/Plugins"
} else {
    Write-Output 'dotnet: skipped, src/Centurion/Centurion.csproj does not exist yet'
}

$versionLine = Select-String -LiteralPath (Join-Path $project 'ProjectSettings/ProjectVersion.txt') -Pattern '^m_EditorVersion: (\S+)$'
$unityVersion = $versionLine.Matches[0].Groups[1].Value
if (-not $UnityPath) {
    $candidates = @(
        foreach ($root in 'HKLM:/SOFTWARE', 'HKLM:/SOFTWARE/WOW6432Node', 'HKCU:/SOFTWARE') {
            $icon = Get-ItemPropertyValue -LiteralPath "$root/Microsoft/Windows/CurrentVersion/Uninstall/Unity $unityVersion" -Name DisplayIcon -ErrorAction SilentlyContinue
            if ($icon) { ($icon -replace ',\s*-?\d+\s*$', '').Trim().Trim('"') }
        }
        Join-Path $env:ProgramFiles "Unity/Hub/Editor/$unityVersion/Editor/Unity.exe"
    )
    $UnityPath = $candidates | Where-Object { Test-Path -LiteralPath $_ -PathType Leaf } | Select-Object -First 1
}
if (-not $UnityPath -or ((Get-Item -LiteralPath $UnityPath).VersionInfo.ProductVersion -split '_')[0] -ne $unityVersion) {
    Fail "Unity $unityVersion not found; pass -UnityPath"
}

# A crashed batch run leaves the lockfile behind; only a held lock means an editor has the project open.
$lock = Join-Path $project 'Temp/UnityLockfile'
if (Test-Path -LiteralPath $lock) {
    try { [IO.File]::Open($lock, 'Open', 'ReadWrite', 'None').Dispose() }
    catch [IO.IOException] { Fail 'an editor holds unity/Temp/UnityLockfile; close it first' }
}

for ($attempt = 1; ; $attempt++) {
    $log = Join-Path $logs ('unity-' + [DateTime]::UtcNow.ToString('yyyyMMddTHHmmssZ') + "-try$attempt.log")
    $arguments = @('-batchmode', '-quit', '-projectPath', "`"$project`"", '-executeMethod', $ExecuteMethod, '-logFile', "`"$log`"")
    $unityClock = [Diagnostics.Stopwatch]::StartNew()
    $unity = Start-Process -FilePath $UnityPath -ArgumentList $arguments -WindowStyle Hidden -PassThru
    $null = $unity.Handle  # cache the handle, or ExitCode reads back empty after exit
    Write-Output "unity: attempt $attempt, pid $($unity.Id), log $log"
    if (-not $unity.WaitForExit([int]$deadline.TotalMilliseconds)) {
        $unity.Kill()
        $unity.WaitForExit()
        Fail "Unity passed the $($deadline.TotalMinutes) minute deadline and was killed; log $log"
    }
    $exitCode = $unity.ExitCode
    Write-Output "unity: exit $exitCode after $([int]$unityClock.Elapsed.TotalSeconds) s"
    $licensed = -not (Select-String -LiteralPath $log -SimpleMatch $licenseFailure -Quiet)
    if ($exitCode -eq 0 -or $licensed -or $attempt -gt $maxLicenseRetries) { break }
    Write-Output "unity: license check failed, retrying in 30 s ($attempt of $maxLicenseRetries retries)"
    Start-Sleep -Seconds 30
}

$problems = @()
if ($exitCode -ne 0) { $problems += "Unity exited $exitCode" }
if (-not $licensed) { $problems += "license not found after $maxLicenseRetries retries" }
$markers = @(Select-String -LiteralPath $log -Pattern '^\[Centurion\] Build complete: (.+)$')
if ($markers.Count -ne 1) { $problems += "$($markers.Count) completion lines, expected 1" }
$captured = @(Select-String -LiteralPath $log -SimpleMatch '[Centurion] Captured build error')
if ($captured.Count -gt 0) { $problems += "$($captured.Count) captured build errors" }
# Logged at editor startup, before the build method's capture exists; a prefab bound to an
# unloaded assembly's scripts would ship with missing components.
$unloaded = @(Select-String -LiteralPath $log -Pattern "^Assembly '(.+)' will not be loaded due to errors", '^Unloading broken assembly (\S+)')
if ($unloaded.Count -gt 0) { $problems += 'Unity did not load ' + (($unloaded | ForEach-Object { $_.Matches[0].Groups[1].Value } | Sort-Object -Unique) -join ', ') }
$nobp = if ($markers.Count -eq 1) { $markers[0].Matches[0].Groups[1].Value.Trim() }
if ($nobp -and -not (Test-Path -LiteralPath $nobp)) { $problems += "no .nobp at $nobp" }
elseif ($nobp -and (Get-Item -LiteralPath $nobp).LastWriteTimeUtc -lt $runStart) { $problems += "stale .nobp, last written $((Get-Item -LiteralPath $nobp).LastWriteTime) before this run" }
if ($problems) {
    Select-String -LiteralPath $log -Pattern 'error CS\d+|Captured build error|executeMethod (class|method)|Exception:|will not be loaded|Unable to resolve reference|broken assembly' |
        Select-Object -First 5 | ForEach-Object { Write-Output "  log: $($_.Line.Trim())" }
    Fail (($problems -join '; ') + "; log $log")
}

$outputs = @($nobp) + @($dll | Where-Object { $_ })
$sums = foreach ($file in $outputs) {
    Copy-Item -LiteralPath $file -Destination $build -Force
    $name = Split-Path -Leaf $file
    (Get-FileHash -LiteralPath (Join-Path $build $name) -Algorithm SHA256).Hash.ToLowerInvariant() + '  ' + $name
}
[IO.File]::WriteAllLines((Join-Path $build 'SHA256SUMS.txt'), [string[]]$sums)
$dllNote = if ($dll) { 'with Centurion.dll' } else { 'no DLL (src/Centurion not present yet)' }
Write-Output "G0.1 PASS: build/$(Split-Path -Leaf $nobp) $($sums[0].Substring(0, 12)) $dllNote, $attempt Unity attempt(s) ($([int]$clock.Elapsed.TotalSeconds) s)"
