# tools/export_blockout.py on the remote host over this checkout's .cache/art/exterior_pass/s6_bake.blend (and its
# maps), the export returned into .cache/art/exterior_pass/<Out>: to compare exports made on the host, without a
# local Blender.
# Usage: pwsh -NoProfile -File art/blender/exterior_pass/Export-Remote.ps1 -Out export_a [-Tree <name>]
param([Parameter(Mandatory)][ValidatePattern('^[A-Za-z0-9_-]+$')][string]$Out, [string]$Tree = '')
$ErrorActionPreference = 'Stop'
$repo = (Resolve-Path "$PSScriptRoot/../../..").Path
Set-Location $repo
$passRel = '.cache/art/exterior_pass'
$ship = @("$passRel/s6_bake.blend") + @(Get-ChildItem "$repo/$passRel/textures" -File | ForEach-Object { "$passRel/textures/$($_.Name)" })
$inner = "pwsh -NoProfile -File tools/Run-Blender.ps1 --background --factory-startup --python-exit-code 1 --python tools/export_blockout.py -- --blend $passRel/s6_bake.blend --out $passRel/$Out"
& pwsh -NoProfile -File "$PSScriptRoot/Invoke-Remote.ps1" -Ship ($ship -join ',') -Run $inner -Tree $Tree
exit $LASTEXITCODE
