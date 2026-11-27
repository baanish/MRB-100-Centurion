# Build the Centurion player paint kit against the export pinned in art/export-manifest.json.
param([ValidatePattern('^[0-9]+\.[0-9]+\.[0-9]+$')][string]$Version = '0.2.0')

$ErrorActionPreference = 'Stop'
$repo = Split-Path -Parent $PSScriptRoot
if (Test-Path -Path (Join-Path $repo '.cache/refresh/*-quiet.txt')) {
    throw 'Local Blender is paused. Build the kit when Blender is available.'
}
$build = New-Item -ItemType Directory -Path (Join-Path $repo 'build') -Force
$stage = New-Item -ItemType Directory -Path (Join-Path $build.FullName ('.livery-kit-' + [guid]::NewGuid()))
$kit = Join-Path $stage.FullName "centurion_livery_kit_$Version"
$generator = Join-Path $PSScriptRoot 'livery_kit.py'
try {
    & python -I $generator prepare --stage $stage.FullName --version $Version
    if ($LASTEXITCODE -ne 0) { throw 'The livery kit templates failed.' }
    & pwsh -NoProfile -File (Join-Path $PSScriptRoot 'Run-Blender.ps1') --background --factory-startup --python-exit-code 1 `
        --python (Join-Path $PSScriptRoot 'livery_kit_model.py') -- (Join-Path $stage.FullName 'paint_mesh.npz') $kit
    if ($LASTEXITCODE -ne 0) { throw 'The livery kit paint model failed.' }
    & python -I $generator pack --stage $stage.FullName --version $Version
    if ($LASTEXITCODE -ne 0) { throw 'The livery kit packing check failed.' }
}
finally {
    $resolved = (Resolve-Path -LiteralPath $stage.FullName).Path
    if ([IO.Path]::GetDirectoryName($resolved) -eq $build.FullName -and $stage.Name -like '.livery-kit-*') {
        Remove-Item -LiteralPath $resolved -Recurse -Force
    }
}
