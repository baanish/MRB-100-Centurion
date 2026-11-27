param(
    [Parameter(Mandatory)][string]$Directory,
    [Parameter(Mandatory)][string]$Tag,
    [string]$ReleaseJson
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
if ($Tag -notmatch '^v(\d+\.\d+\.\d+)$') { throw 'Expected release tag v<major>.<minor>.<patch>' }
$version = $Matches[1]
$Directory = (Resolve-Path -LiteralPath $Directory).Path
$modId = 'baanish.centurion'
$repository = 'baanish/MRB-100-Centurion'
$nommName = "Centurion-$Tag-nomm.zip"
$manualName = "Centurion-$Tag-plugin-only.zip"
$manifestName = "Centurion-$Tag-nomnom.json"
$kitName = "centurion_livery_kit_$version.zip"
$assetNames = @($nommName, $manualName, $manifestName, $kitName, 'RELEASE-NOTES.md')
# GitHub returns assets in case-insensitive name order; NOMNOM imports the first asset.
$releaseAssetNames = [string[]]($assetNames + 'SHA256SUMS.txt')
[Array]::Sort($releaseAssetNames, [StringComparer]::OrdinalIgnoreCase)
if ($releaseAssetNames[0] -cne $nommName) { throw 'Release asset names must sort with the NOMM archive first' }

function Get-Sha256([string]$Path) {
    (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
}

function Assert-BlueprinterDependency($Artifact) {
    $dependencies = @($Artifact.dependencies)
    if ($dependencies.Count -ne 1 -or $dependencies[0].id -cne 'com.nikkorap.blueprinter' -or
        $dependencies[0].version -cne '2.0.1') {
        throw 'Expected the Blueprinter catalog dependency com.nikkorap.blueprinter, minimum 2.0.1'
    }
    # BepInEx is installed by NOMM itself. extends would move this plugin under another mod's addons folder.
    if ($Artifact.PSObject.Properties['extends']) { throw 'Centurion must be a standalone plugin with dependencies, without extends' }
}

$sums = @{}
foreach ($line in Get-Content -LiteralPath (Join-Path $Directory 'SHA256SUMS.txt')) {
    if ($line -cnotmatch '^([0-9a-f]{64})  ([A-Za-z0-9._-]+)$') { throw "Invalid checksum line: $line" }
    $name = $Matches[2]
    if ($name -cnotin $assetNames -or $sums.ContainsKey($name)) { throw "Unexpected or duplicate checksum: $name" }
    $sums[$name] = $Matches[1]
    if ((Get-Sha256 (Join-Path $Directory $name)) -cne $sums[$name]) { throw "Checksum mismatch: $name" }
}
if ($sums.Count -ne $assetNames.Count) { throw 'SHA256SUMS.txt must cover both archives, the livery kit, the manifest and release notes' }

$manifest = Get-Content -LiteralPath (Join-Path $Directory $manifestName) -Raw | ConvertFrom-Json
if ($manifest.id -cne $modId -or $manifest.githubOwner -cne 'baanish' -or
    $manifest.githubRepoName -cne 'MRB-100-Centurion' -or $manifest.autoUpdateArtifacts -cne 'True') {
    throw 'Manifest must identify the public Centurion repository with automatic updates enabled'
}
if (@($manifest.urls | Where-Object { $_.name -ceq 'info' -and $_.url -ceq "https://github.com/$repository#readme" }).Count -ne 1) {
    throw 'Manifest info URL must point at the public README'
}
if (@($manifest.artifacts).Count -ne 1) { throw 'Expected one artifact in the release manifest' }
$artifact = $manifest.artifacts[0]
if ($artifact.fileName -cne $nommName -or $artifact.version -cne $version -or
    $artifact.type -cne 'plugin' -or $artifact.gameVersion -cne '0.34.6' -or
    $artifact.category -cnotin @('preRelease', 'release') -or
    $artifact.downloadUrl -cne "https://github.com/$repository/releases/download/$Tag/$nommName" -or
    $artifact.hash -cne "sha256:$($sums[$nommName])") {
    throw 'Manifest artifact does not match the release tag, NOMM archive, checksum or supported game version'
}
Assert-BlueprinterDependency $artifact

$payloadHashes = @{}
foreach ($name in @($nommName, $manualName)) {
    $archive = [IO.Compression.ZipFile]::OpenRead((Join-Path $Directory $name))
    try {
        $prefix = if ($name -ceq $manualName) { "BepInEx/plugins/$modId/" } else { '' }
        $required = @('Centurion.dll', "centurion_$version.nobp", 'meta.json', 'README.md', 'LICENSE')
        $seen = [Collections.Generic.HashSet[string]]::new([StringComparer]::Ordinal)
        foreach ($entry in $archive.Entries) {
            if (-not $entry.FullName.StartsWith($prefix, [StringComparison]::Ordinal)) { throw "Unexpected path in ${name}: $($entry.FullName)" }
            $relative = $entry.FullName.Substring($prefix.Length)
            if (($relative -cnotin $required -and $relative -cnotin @('audio/CREDITS.md', 'CREDITS-audio.md')) -or -not $seen.Add($relative)) {
                throw "Unexpected or duplicate entry in ${name}: $relative"
            }
            $stream = $entry.Open()
            try { $hash = [Convert]::ToHexString([Security.Cryptography.SHA256]::HashData($stream)).ToLowerInvariant() }
            finally { $stream.Dispose() }
            if ($name -ceq $nommName) { $payloadHashes[$relative] = $hash }
            elseif (-not $payloadHashes.ContainsKey($relative) -or $payloadHashes[$relative] -cne $hash) {
                throw "Archives disagree on $relative"
            }
        }
        foreach ($requiredName in $required) {
            if (-not $seen.Contains($requiredName)) { throw "$name is missing $requiredName" }
        }
        if ($seen.Count -ne $payloadHashes.Count) { throw 'Archives have different payloads' }
        if ($name -ceq $nommName) {
            $reader = [IO.StreamReader]::new($archive.GetEntry('meta.json').Open())
            try { $meta = $reader.ReadToEnd() | ConvertFrom-Json } finally { $reader.Dispose() }
            if ($meta.id -cne $modId -or $meta.artifact.fileName -cne 'Centurion.dll' -or
                $meta.artifact.version -cne $version -or $meta.artifact.downloadUrl -cne '' -or
                $meta.artifact.hash -cne "sha256:$($payloadHashes['Centurion.dll'])" -or
                $meta.artifact.type -cne $artifact.type -or $meta.artifact.category -cne $artifact.category -or
                $meta.artifact.gameVersion -cne $artifact.gameVersion) { throw 'Packaged meta.json does not match the payload and manifest' }
            Assert-BlueprinterDependency $meta.artifact
        }
    } finally { $archive.Dispose() }
}

# The livery kit must fit the packaged aircraft: atlas.json pins the export manifest the bundle was built from, and
# the kit's examples and maps must be that export's textures. The kit's layout fingerprint was taken from that export.
$exportManifestPath = Join-Path $PSScriptRoot '../art/export-manifest.json'
$exportManifest = Get-Content -LiteralPath $exportManifestPath -Raw | ConvertFrom-Json -AsHashtable
$kitPrefix = "centurion_livery_kit_$version/"
$archive = [IO.Compression.ZipFile]::OpenRead((Join-Path $Directory $kitName))
try {
    $atlasEntry = $archive.GetEntry("${kitPrefix}atlas.json")
    if (-not $atlasEntry) { throw "$kitName is missing atlas.json" }
    $reader = [IO.StreamReader]::new($atlasEntry.Open())
    try { $atlas = $reader.ReadToEnd() | ConvertFrom-Json -AsHashtable } finally { $reader.Dispose() }
    foreach ($field in 'examples', 'map_sha256', 'layer_sha256') {
        if ($atlas[$field] -isnot [Collections.IDictionary] -or -not $atlas[$field].Count) { throw "$kitName's atlas.json has no $field" }
    }
    if ($atlas['version'] -cne $version -or $atlas['atlas_size'] -ne 4096 -or $atlas['skin_uv_sha256'] -cnotmatch '^[0-9a-f]{64}$' -or
        $atlas['export_manifest_sha256'] -cne (Get-Sha256 $exportManifestPath)) {
        throw "$kitName was not built from $Tag's exterior export"
    }
    # Relative path -> expected SHA-256, or $null for a file whose content atlas.json does not pin.
    $kitFiles = @{}
    foreach ($name in 'README.md', 'LICENSE.txt', 'atlas.json', 'install/CenturionLiveryBuilder.cs', 'install/meta.json',
        'model/centurion_paint_model.blend', 'model/centurion_paint_model.fbx', 'template/uv_layout.png',
        'template/uv_layout.svg', 'template/part_map.png', 'template/part_labels.png', 'template/parts.csv') {
        $kitFiles[$name] = $null
    }
    $textures = @(@($atlas['examples'].Values | ForEach-Object { "examples/$_" }) +
        @('centurion_n.png', 'centurion_m.png', 'centurion_ao.png' | ForEach-Object { "maps/$_" }))
    foreach ($path in $textures) {
        $name = Split-Path -Leaf $path
        $hash = $atlas['map_sha256'][$name]
        if (-not $hash -or $exportManifest["art/export/textures/$name"] -cne $hash) { throw "$kitName's $name is not the packaged aircraft's" }
        $kitFiles[$path] = $hash
    }
    $layerNames = @($atlas['examples'].Keys | ForEach-Object { "${_}_01_base.png", "${_}_02_markings.png", "${_}_03_panel_lines.png" })
    if ($atlas['layer_sha256'].Count -ne $layerNames.Count) { throw "$kitName's atlas.json lists other paint layers than base, markings and panel lines per livery" }
    foreach ($name in $layerNames) {
        if (-not $atlas['layer_sha256'][$name]) { throw "$kitName's atlas.json has no hash for $name" }
        $kitFiles["template/layers/$name"] = $atlas['layer_sha256'][$name]
    }
    $seen = [Collections.Generic.HashSet[string]]::new([StringComparer]::Ordinal)
    foreach ($entry in $archive.Entries) {
        if (-not $entry.FullName.StartsWith($kitPrefix, [StringComparison]::Ordinal)) { throw "Unexpected path in ${kitName}: $($entry.FullName)" }
        $relative = $entry.FullName.Substring($kitPrefix.Length)
        if (-not $kitFiles.ContainsKey($relative) -or -not $seen.Add($relative)) { throw "Unexpected or duplicate entry in ${kitName}: $relative" }
        if ($kitFiles[$relative]) {
            $stream = $entry.Open()
            try { $hash = [Convert]::ToHexString([Security.Cryptography.SHA256]::HashData($stream)).ToLowerInvariant() }
            finally { $stream.Dispose() }
            if ($hash -cne $kitFiles[$relative]) { throw "$kitName's $relative differs from atlas.json" }
        }
    }
    foreach ($name in $kitFiles.Keys) {
        if (-not $seen.Contains($name)) { throw "$kitName is missing $name" }
    }
} finally { $archive.Dispose() }

if ($ReleaseJson) {
    $release = Get-Content -LiteralPath $ReleaseJson -Raw | ConvertFrom-Json
    if ($release.tag_name -cne $Tag -or $release.draft -or $release.html_url -cne "https://github.com/$repository/releases/tag/$Tag") {
        throw 'Expected a published release in the public repository at the requested tag'
    }
    $category = if ($release.prerelease) { 'preRelease' } else { 'release' }
    if ($artifact.category -cne $category) { throw 'Manifest category disagrees with the GitHub prerelease flag' }
    $uploaded = @($release.assets)
    if ($uploaded.Count -ne $releaseAssetNames.Count -or
        (@($uploaded.name) -join "`n") -cne ($releaseAssetNames -join "`n")) {
        throw 'Upload exactly the checksummed assets and SHA256SUMS.txt in case-insensitive name order, with the NOMM archive first'
    }
    $seen = [Collections.Generic.HashSet[string]]::new([StringComparer]::Ordinal)
    foreach ($asset in $uploaded) {
        if (($asset.name -cnotin $assetNames -and $asset.name -cne 'SHA256SUMS.txt') -or -not $seen.Add($asset.name)) {
            throw "Unexpected or duplicate release asset: $($asset.name)"
        }
        $path = Join-Path $Directory $asset.name
        if ($asset.browser_download_url -cne "https://github.com/$repository/releases/download/$Tag/$($asset.name)" -or
            $asset.size -ne (Get-Item -LiteralPath $path).Length) { throw "Release metadata mismatch: $($asset.name)" }
        if ($asset.digest -and $asset.digest -cne "sha256:$(Get-Sha256 $path)") { throw "GitHub digest mismatch: $($asset.name)" }
    }
}
Write-Output "RELEASE VERIFY PASS: $Tag checksums, manifest, dependencies, paired archives, livery kit and sorted asset names$(if ($ReleaseJson) { ', including published asset order and metadata' })"
