# Check-Identity.ps1
#
# Gate G1.5's static parts (docs/GATES.md) on the last build: opens build/centurion_<version>.nobp in Unity
# (Centurion.Editor.CenturionAuthor.CheckIdentity) and checks it holds no stock mesh or texture (by name, and by
# vertex hash against the Alkyon's meshes), one pilot seat, no SwingWingController, every loadout as long as the
# hardpoint-set count, liveries and status display from the mod folder, and that the aircraft holds together
# (Centurion.Editor.PartStructureCheck: each part's joint to its parent, a collider on every part, and a parked
# settle of the simulating peer's joints with no part drifting toward the 0.5 m detach line), and that each control
# surface's +1 pitch, roll and yaw deflection turns the aircraft the right way about its centre of mass
# (Centurion.Editor.ControlMomentCheck). The last line is the verdict.
#
#   pwsh tools/Build-Centurion.ps1; pwsh tools/Check-Identity.ps1

param([string]$UnityPath)

$ErrorActionPreference = 'Stop'
$repo = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$project = Join-Path $repo 'unity'
$logs = Join-Path $repo 'build/logs'
New-Item -ItemType Directory -Force $logs | Out-Null

$unityVersion = (Select-String -LiteralPath (Join-Path $project 'ProjectSettings/ProjectVersion.txt') -Pattern '^m_EditorVersion: (\S+)$').Matches[0].Groups[1].Value
if (-not $UnityPath) {
    $UnityPath = @(
        foreach ($root in 'HKLM:/SOFTWARE', 'HKLM:/SOFTWARE/WOW6432Node', 'HKCU:/SOFTWARE') {
            $icon = Get-ItemPropertyValue -LiteralPath "$root/Microsoft/Windows/CurrentVersion/Uninstall/Unity $unityVersion" -Name DisplayIcon -ErrorAction SilentlyContinue
            if ($icon) { ($icon -replace ',\s*-?\d+\s*$', '').Trim().Trim('"') }
        }
        Join-Path $env:ProgramFiles "Unity/Hub/Editor/$unityVersion/Editor/Unity.exe"
    ) | Where-Object { Test-Path -LiteralPath $_ -PathType Leaf } | Select-Object -First 1
}
if (-not $UnityPath) { Write-Output "G1.5 FAIL: Unity $unityVersion not found; pass -UnityPath"; exit 1 }

$lock = Join-Path $project 'Temp/UnityLockfile'
if (Test-Path -LiteralPath $lock) {
    try { [IO.File]::Open($lock, 'Open', 'ReadWrite', 'None').Dispose() }
    catch [IO.IOException] { Write-Output 'G1.5 FAIL: an editor holds unity/Temp/UnityLockfile; close it first'; exit 1 }
}

$log = Join-Path $logs ('identity-' + [DateTime]::UtcNow.ToString('yyyyMMddTHHmmssZ') + '.log')
$arguments = @('-batchmode', '-quit', '-projectPath', "`"$project`"", '-executeMethod', 'Centurion.Editor.CenturionAuthor.CheckIdentity', '-logFile', "`"$log`"")
$unity = Start-Process -FilePath $UnityPath -ArgumentList $arguments -WindowStyle Hidden -PassThru
$null = $unity.Handle
if (-not $unity.WaitForExit(15 * 60 * 1000)) { $unity.Kill(); Write-Output "G1.5 FAIL: Unity passed 15 minutes; log $log"; exit 1 }

$lines = @(Select-String -LiteralPath $log -Pattern '^\[Centurion\] G1\.5 (.+)$' | ForEach-Object { $_.Matches[0].Groups[1].Value })
$lines | Where-Object { $_ -notmatch '^(PASS|FAIL)' } | ForEach-Object { Write-Output "  $_" }
$verdict = $lines | Where-Object { $_ -match '^(PASS|FAIL)' } | Select-Object -Last 1
if ($unity.ExitCode -ne 0 -or -not $verdict) {
    Select-String -LiteralPath $log -Pattern 'Exception:|error CS\d+' | Select-Object -First 5 | ForEach-Object { Write-Output "  log: $($_.Line.Trim())" }
    Write-Output "G1.5 FAIL: Unity exited $($unity.ExitCode) without a verdict; log $log"
    exit 1
}
Write-Output "G1.5 $verdict"
if ($verdict -notmatch '^PASS') { exit 1 }
