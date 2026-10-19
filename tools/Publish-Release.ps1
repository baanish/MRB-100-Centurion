param(
    [Parameter(Mandatory)][string]$Directory,
    [Parameter(Mandatory)][string]$Tag
)

$ErrorActionPreference = 'Stop'
if ($Tag -notmatch '^v\d+\.\d+\.\d+$') { throw 'Expected release tag v<major>.<minor>.<patch>' }
$Directory = (Resolve-Path -LiteralPath $Directory).Path
$repository = 'baanish/MRB-100-Centurion'
# GitHub returns assets in case-insensitive name order; NOMNOM imports the first asset.
$assets = @("Centurion-$Tag-nomm.zip", "Centurion-$Tag-nomnom.json",
    "Centurion-$Tag-plugin-only.zip", 'RELEASE-NOTES.md', 'SHA256SUMS.txt')
foreach ($name in $assets) {
    if (-not (Test-Path -LiteralPath (Join-Path $Directory $name) -PathType Leaf)) { throw "Missing release asset: $name" }
}
& pwsh -NoProfile -File (Join-Path $PSScriptRoot 'Verify-Release.ps1') -Directory $Directory -Tag $Tag
if ($LASTEXITCODE -ne 0) { throw 'Local release verification failed' }
$manifest = Get-Content -LiteralPath (Join-Path $Directory "Centurion-$Tag-nomnom.json") -Raw | ConvertFrom-Json
if ($manifest.artifacts[0].category -cne 'preRelease') { throw 'Publication requires a prerelease manifest' }

function Invoke-Gh {
    $result = & gh @args
    if ($LASTEXITCODE -ne 0) { throw "gh $($args[0]) failed (exit $LASTEXITCODE); any draft remains unpublished" }
    $result
}

# Check the remote tag before creating anything. --verify-tag also forbids implicit tag creation.
$null = Invoke-Gh api "repos/$repository/git/ref/tags/$Tag"
$null = Invoke-Gh release create $Tag --repo $repository --verify-tag --draft --prerelease --title "MRB-100 Centurion $Tag" --notes-file (Join-Path $Directory 'RELEASE-NOTES.md')
foreach ($name in $assets) {
    $null = Invoke-Gh release upload $Tag (Join-Path $Directory $name) --repo $repository
}
# The releases/tags endpoint does not return drafts, so find the draft in the release list.
$release = @((Invoke-Gh api "repos/$repository/releases") -join "`n" | ConvertFrom-Json) | Where-Object { $_.tag_name -ceq $Tag -and $_.draft } | Select-Object -First 1
if (-not $release -or -not $release.prerelease -or @($release.assets).Count -ne $assets.Count -or
    (@($release.assets.name) -join "`n") -cne ($assets -join "`n")) {
    throw 'Draft asset order or prerelease metadata mismatch; draft remains unpublished'
}
foreach ($name in $assets) {
    $uploaded = @($release.assets | Where-Object { $_.name -ceq $name })
    $path = Join-Path $Directory $name
    $digest = 'sha256:' + (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($uploaded.Count -ne 1 -or $uploaded[0].size -ne (Get-Item -LiteralPath $path).Length -or $uploaded[0].digest -cne $digest) {
        throw "Draft upload mismatch: $name; draft remains unpublished"
    }
}
$null = Invoke-Gh release edit $Tag --repo $repository --draft=false --prerelease
$jsonPath = Join-Path ([IO.Path]::GetTempPath()) ("centurion-release-" + [guid]::NewGuid() + '.json')
try {
    (Invoke-Gh api "repos/$repository/releases/tags/$Tag") | Set-Content -LiteralPath $jsonPath -Encoding utf8NoBOM
    & pwsh -NoProfile -File (Join-Path $PSScriptRoot 'Verify-Release.ps1') -Directory $Directory -Tag $Tag -ReleaseJson $jsonPath
    if ($LASTEXITCODE -ne 0) { throw 'Published release verification failed' }
} finally { Remove-Item -LiteralPath $jsonPath -ErrorAction SilentlyContinue }
Write-Output "PUBLISH PASS: https://github.com/$repository/releases/tag/$Tag"
