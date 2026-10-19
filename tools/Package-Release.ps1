# Package-Release.ps1
#
# Cuts the Centurion's release package (docs/RELEASE.md) from a committed build, and publishes nothing. Builds the
# plugin from HEAD's src/Centurion and the bundle (tools/Build-Centurion.ps1 -Committed, gate G0.1), checks the
# bundle holds no game mesh or texture (tools/Check-Identity.ps1, gate G1.5), then writes
# .cache/release/v<version>-<UTC time>/:
#
#   Centurion-v<version>-nomm.zip          flat; NOMM supplies the install folder. The first release asset.
#   Centurion-v<version>-plugin-only.zip   BepInEx/plugins/baanish.centurion/, extracted beside NuclearOption.exe
#   SHA256SUMS.txt
#   Centurion-v<version>-nomnom.json       the NOMNOM listing, from packaging/NOMNOM-MANIFEST.template.json
#   RELEASE-NOTES.md                      the release body, with public links at the tag
#
# Both archives hold the same allowlisted files, in sorted order with fixed timestamps: Centurion.dll, the .nobp,
# meta.json, README.md, LICENSE, and audio/CREDITS.md once the mod folder carries sounds.
#
# Refuses dirty build inputs, a build that changes tracked inputs (the bundle would not match HEAD's assets),
# versions that disagree (CenturionPlugin.Version, Centurion.csproj, modinfo.json) and the placeholder LICENSE.
# -AllowDirty turns those four into warnings for a local rehearsal: every output name then carries -LOCAL, and the
# package must never be published. A missing file, a failed build or identity check, or an archive that differs from
# its allowlist refuses in both modes. The last line is the verdict.
#
#   pwsh -NoProfile -File tools/Package-Release.ps1
#   pwsh -NoProfile -File tools/Package-Release.ps1 -AllowDirty

param(
    [switch]$AllowDirty,
    [string]$NotesFile,
    [switch]$CheckOnly
)

$ErrorActionPreference = 'Stop'
$repo = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$modId = 'baanish.centurion'
$warnings = [Collections.Generic.List[string]]::new()

function Fail([string]$why) {
    Write-Output "RELEASE FAIL: $why"
    exit 1
}

# A release refusal; under -AllowDirty a warning that marks the package local.
function Refuse([string]$why) {
    if (-not $AllowDirty) { Fail "$why (-AllowDirty packages a local rehearsal anyway)" }
    $warnings.Add($why)
    Write-Output "WARN: $why"
}

function Get-Sha256([string]$path) { (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLowerInvariant() }

function Invoke-Git {
    $out = & git -C $repo @args
    if ($LASTEXITCODE -ne 0) { Fail "git $($args -join ' ') exited $LASTEXITCODE" }
    $out
}

# The files the package ships and the scripts behind the gates it runs. A clean tree makes each one HEAD's.
$required = @(
    'README.md', 'LICENSE', 'audio/CREDITS.md', 'packaging/NOMNOM-MANIFEST.template.json',
    'src/Centurion/Centurion.csproj', 'src/Centurion/CenturionPlugin.cs', 'unity/Assets/Blueprinter/Mods/centurion/modinfo.json',
    'tools/Build-Centurion.ps1', 'tools/Check-Identity.ps1', 'tools/Verify-Release.ps1',
    'art/export-manifest.json', 'tools/export_manifest.py', 'tools/scrub_fbx.py'
)
foreach ($path in $required) {
    if (-not (Test-Path -LiteralPath (Join-Path $repo $path) -PathType Leaf)) { Fail "$path is missing" }
}
$changes = if ($NotesFile) { Get-Content -LiteralPath $NotesFile -Raw } else { '' }

& python (Join-Path $repo 'tools/export_manifest.py')
if ($LASTEXITCODE -ne 0) { Fail 'exports do not match art/export-manifest.json' }
# Ignored exports are pinned by the committed manifest, including their JSON and textures.
$inputs = @('src', 'unity', 'tools', 'packaging', 'README.md', 'LICENSE', 'audio', 'art/export-manifest.json')
$statusBefore = @(Invoke-Git status --porcelain -- @inputs) -join "`n"
if ($statusBefore) { Refuse "the build inputs are dirty ($(@($statusBefore -split "`n").Count) paths)" }
# Unity assigns fresh prefab fileIDs. Every other tracked input must retain its bytes,
# including the copied FBX, textures, materials, modinfo and parameters.
$authored = ':(exclude,glob)unity/Assets/Blueprinter/Mods/centurion/**/*.prefab'
function Get-InputState {
    @(Invoke-Git status --porcelain -- @inputs $authored)
    foreach ($path in @(Invoke-Git ls-files -- @inputs $authored)) {
        if (Test-Path -LiteralPath (Join-Path $repo $path) -PathType Leaf) { "$path $(Get-Sha256 (Join-Path $repo $path))" }
    }
}
$stateBefore = @(Get-InputState) -join "`n"
$commit = Invoke-Git rev-parse --short HEAD

# The DLL compiles from HEAD's src/Centurion; Unity reads the working tree's modinfo.json.
$pluginVersion = [regex]::Match((Invoke-Git show HEAD:src/Centurion/CenturionPlugin.cs) -join "`n", 'const string Version = "([^"]+)"').Groups[1].Value
$csprojVersion = [regex]::Match((Invoke-Git show HEAD:src/Centurion/Centurion.csproj) -join "`n", '<Version>([^<]+)</Version>').Groups[1].Value
$bundleVersion = (Get-Content -LiteralPath (Join-Path $repo 'unity/Assets/Blueprinter/Mods/centurion/modinfo.json') -Raw | ConvertFrom-Json).version
if ($pluginVersion -notmatch '^\d+\.\d+\.\d+$') { Fail "CenturionPlugin.Version at HEAD reads '$pluginVersion'" }
if ($csprojVersion -ne $pluginVersion -or $bundleVersion -ne $pluginVersion) {
    Refuse "versions disagree: CenturionPlugin.Version $pluginVersion, Centurion.csproj $csprojVersion, modinfo.json $bundleVersion"
}
$version = $pluginVersion
if (Select-String -LiteralPath (Join-Path $repo 'LICENSE') -SimpleMatch 'TODO(owner)' -Quiet) {
    Refuse 'LICENSE is the placeholder; the owner picks the licence'
}

if ($CheckOnly) {
    Write-Output "RELEASE CHECK $(if ($warnings.Count) { 'LOCAL' } else { 'PASS' }): inputs and export manifest checked; no build performed"
    exit 0
}
Write-Output "release: $modId $version from HEAD $commit; building"
$buildLast = $null
& pwsh -NoProfile -File (Join-Path $repo 'tools/Build-Centurion.ps1') -Committed | ForEach-Object { Write-Output "  $_"; $buildLast = $_ }
if ($LASTEXITCODE -ne 0 -or $buildLast -notmatch '^G0\.1 PASS: build/(\S+) ([0-9a-f]{12}) with Centurion\.dll') { Fail "the build did not pass: $buildLast" }
$nobpName = $Matches[1]
$nobpPrefix = $Matches[2]
if ($nobpName -ne "centurion_$bundleVersion.nobp") { Fail "the build wrote $nobpName, expected centurion_$bundleVersion.nobp" }
& python (Join-Path $repo 'tools/export_manifest.py')
if ($LASTEXITCODE -ne 0) { Fail 'the build changed the pinned exports' }
if ((@(Get-InputState) -join "`n") -ne $stateBefore) { Refuse "the build changed its inputs, so the bundle does not match HEAD's assets" }

# Hold the build lock from here, so no other build replaces build/ under the identity check and the copy. A build
# that dies leaves the mutex abandoned, which this takes.
$buildLock = [System.Threading.Mutex]::new($false, 'Global\CenturionBuild')
try { [void]$buildLock.WaitOne() }
catch {
    $e = $_.Exception
    while ($e -and $e -isnot [System.Threading.AbandonedMutexException]) { $e = $e.InnerException }
    if (-not $e) { throw }
}

$build = Join-Path $repo 'build'
$sums = @{}
foreach ($line in Get-Content -LiteralPath (Join-Path $build 'SHA256SUMS.txt')) {
    if ($line -match '^([0-9a-f]{64})  (\S+)$') { $sums[$Matches[2]] = $Matches[1] }
}
if (-not $sums.ContainsKey($nobpName) -or -not $sums[$nobpName].StartsWith($nobpPrefix)) { Fail 'another build replaced build/ after this one passed' }
foreach ($name in $nobpName, 'Centurion.dll') {
    if (-not $sums.ContainsKey($name) -or (Get-Sha256 (Join-Path $build $name)) -ne $sums[$name]) { Fail "build/$name does not match build/SHA256SUMS.txt" }
}
$assembly = [Reflection.AssemblyName]::GetAssemblyName((Join-Path $build 'Centurion.dll'))
if ($assembly.Name -cne 'Centurion' -or $assembly.Version.ToString(3) -ne $csprojVersion) { Fail "build/Centurion.dll is $($assembly.FullName)" }

$identityLast = $null
& pwsh -NoProfile -File (Join-Path $repo 'tools/Check-Identity.ps1') | ForEach-Object { Write-Output "  $_"; $identityLast = $_ }
if ($LASTEXITCODE -ne 0 -or $identityLast -notmatch '^G1\.5 PASS') { Fail "the identity check did not pass: $identityLast" }

$local = if ($warnings.Count) { '-LOCAL' } else { '' }
$tag = "$version$local"
$out = Join-Path $repo ('.cache/release/v' + $tag + '-' + [DateTime]::UtcNow.ToString('yyyyMMddTHHmmssZ'))
New-Item -ItemType Directory -Path $out | Out-Null

$listingTemplate = Get-Content -LiteralPath (Join-Path $repo 'packaging/NOMNOM-MANIFEST.template.json') -Raw
$artifact = ($listingTemplate -replace '@VERSION@', $version | ConvertFrom-Json).artifacts[0]
$dllHash = Get-Sha256 (Join-Path $build 'Centurion.dll')
# NOMM matches mods by this id; locally it reads the version and the installed file's hash, and accepts no download URL.
$metaPath = Join-Path $out 'meta.json'
[ordered]@{
    id = $modId
    artifact = [ordered]@{
        fileName = 'Centurion.dll'; version = $version; category = $artifact.category; type = $artifact.type
        gameVersion = $artifact.gameVersion; downloadUrl = ''; hash = "sha256:$dllHash"; dependencies = @($artifact.dependencies)
    }
} | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $metaPath -Encoding utf8NoBOM

$sourceUrl = "https://github.com/baanish/MRB-100-Centurion/blob/v$version"
$readme = Get-Content -LiteralPath (Join-Path $repo 'README.md') -Raw
$readme = [regex]::Replace($readme, '(?<lead>!?\[[^\]]*\]\()(?<path>[^)\s]+)(?<tail>\))', {
    param($match)
    $path = $match.Groups['path'].Value
    if ($path -match '^(?:[a-z][a-z0-9+.-]*:|/|#)') { return $match.Value }
    $match.Groups['lead'].Value + "$sourceUrl/" + ($path -replace '^\./', '') + $match.Groups['tail'].Value
})
$readmePath = Join-Path $out 'README.md'
[IO.File]::WriteAllText($readmePath, $readme, [Text.UTF8Encoding]::new($false))
$files = [ordered]@{
    'Centurion.dll' = Join-Path $build 'Centurion.dll'
    $nobpName = Join-Path $build $nobpName
    'meta.json' = $metaPath
    'README.md' = $readmePath
    'LICENSE' = Join-Path $repo 'LICENSE'
}
if (@(Invoke-Git ls-files -- 'unity/Assets/Blueprinter/Mods/centurion/*.wav' 'unity/Assets/Blueprinter/Mods/centurion/*.ogg').Count) {
    $files['audio/CREDITS.md'] = Join-Path $repo 'audio/CREDITS.md'
}

# Sorted entries and fixed timestamps: the same inputs give the same archive bytes. Read back against the allowlist.
function Write-ReleaseArchive([string]$name, [string]$prefix) {
    $path = Join-Path $out $name
    $expected = @{}
    $archive = [IO.Compression.ZipFile]::Open($path, [IO.Compression.ZipArchiveMode]::Create)
    try {
        foreach ($file in @($files.Keys | Sort-Object)) {
            $entry = $archive.CreateEntry($prefix + $file, [IO.Compression.CompressionLevel]::Optimal)
            $entry.LastWriteTime = [DateTimeOffset]::new(2026, 1, 1, 0, 0, 0, [TimeSpan]::Zero)
            $expected[$entry.FullName] = Get-Sha256 $files[$file]
            $source = [IO.File]::OpenRead($files[$file])
            try {
                $target = $entry.Open()
                try { $source.CopyTo($target) } finally { $target.Dispose() }
            } finally { $source.Dispose() }
        }
    } finally { $archive.Dispose() }
    $archive = [IO.Compression.ZipFile]::OpenRead($path)
    try {
        if ($archive.Entries.Count -ne $expected.Count) { Fail "$name holds $($archive.Entries.Count) entries, expected $($expected.Count)" }
        foreach ($entry in $archive.Entries) {
            if (-not $expected.ContainsKey($entry.FullName)) { Fail "$name holds $($entry.FullName), which is not on the allowlist" }
            $stream = $entry.Open()
            try { $hash = [Convert]::ToHexString([Security.Cryptography.SHA256]::HashData($stream)).ToLowerInvariant() }
            finally { $stream.Dispose() }
            if ($hash -ne $expected[$entry.FullName]) { Fail "$name's $($entry.FullName) differs from its source" }
        }
    } finally { $archive.Dispose() }
    $path
}

$nommZip = Write-ReleaseArchive "Centurion-v$tag-nomm.zip" ''
$pluginZip = Write-ReleaseArchive "Centurion-v$tag-plugin-only.zip" "BepInEx/plugins/$modId/"
$buildLock.ReleaseMutex()

$nommHash = Get-Sha256 $nommZip
$listingTemplate -replace '@VERSION@', $tag -replace '@SHA256@', $nommHash | Set-Content -LiteralPath (Join-Path $out "Centurion-v$tag-nomnom.json") -Encoding utf8NoBOM -NoNewline
$zips = @($nommZip, $pluginZip)
$releaseUrl = "https://github.com/baanish/MRB-100-Centurion/releases/download/v$tag"
$sourceUrl = "https://github.com/baanish/MRB-100-Centurion/blob/v$tag"
$notes = @(
    "# MRB-100 Centurion v$tag", '',
    'For Nuclear Option 0.34.2. Requires BepInEx 5 and Blueprinter 2.0.1 or later.', '',
    'Every player needs the mod. Two-PC multiplayer validation is still pending; this is a prerelease.', ''
)
if ($changes) { $notes += @('## Changes', '', $changes.Trim(), '') }
$notes += @(
    '## Install', '',
    'With NOMM, install MRB-100 Centurion from the catalog after its listing is accepted. NOMM installs BepInEx and catalog dependencies. Confirm Blueprinter is enabled and at least 2.0.1.', '',
    "For manual installation, extract [Centurion-v$tag-plugin-only.zip]($releaseUrl/Centurion-v$tag-plugin-only.zip) beside NuclearOption.exe after installing BepInEx 5 and Blueprinter 2.0.1+.", '',
    "[Install instructions]($sourceUrl/README.md#install) | [Known limitations]($sourceUrl/README.md#known-limitations)", '',
    '## Assets', '',
    "- [NOMM archive]($releaseUrl/Centurion-v$tag-nomm.zip), for the catalog. Its payload is flat.",
    "- [Manual archive]($releaseUrl/Centurion-v$tag-plugin-only.zip), with BepInEx/plugins/baanish.centurion/ included.",
    "- [SHA256SUMS.txt]($releaseUrl/SHA256SUMS.txt), covering both archives, the catalog manifest and these notes.",
    "- [Catalog manifest]($releaseUrl/Centurion-v$tag-nomnom.json), for initial NOMNOM registration.", '',
    "Source: [v$tag]($sourceUrl)."
)
if ($local) { $notes = @('LOCAL REHEARSAL. NEVER PUBLISH.', '') + $notes }
$notes | Set-Content -LiteralPath (Join-Path $out 'RELEASE-NOTES.md') -Encoding utf8NoBOM
$assets = @($zips) + @((Join-Path $out "Centurion-v$tag-nomnom.json"), (Join-Path $out 'RELEASE-NOTES.md'))
[IO.File]::WriteAllLines((Join-Path $out 'SHA256SUMS.txt'), [string[]]@($assets | ForEach-Object { (Get-Sha256 $_) + '  ' + (Split-Path -Leaf $_) }))
if (-not $local) {
    & pwsh -NoProfile -File (Join-Path $repo 'tools/Verify-Release.ps1') -Directory $out -Tag "v$version"
    if ($LASTEXITCODE -ne 0) { Fail 'the packaged release failed verification' }
}

Write-Output "package: $out"
foreach ($zip in $zips) {
    Write-Output "  $(Split-Path -Leaf $zip)  sha256 $(Get-Sha256 $zip)"
    $archive = [IO.Compression.ZipFile]::OpenRead($zip)
    try { $archive.Entries | ForEach-Object { Write-Output ("    {0,12:N0}  {1}" -f $_.Length, $_.FullName) } } finally { $archive.Dispose() }
}
if ($warnings.Count) {
    Write-Output "RELEASE LOCAL (never publish): $nommZip; $($warnings -join '; ')"
} else {
    Write-Output "RELEASE PASS: $nommZip sha256 $nommHash (HEAD $commit)"
}
