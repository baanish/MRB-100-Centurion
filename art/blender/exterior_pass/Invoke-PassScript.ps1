# One Blender job on the remote host over a pass blend built here: a gate rerun or a script of your own over
# .cache/art/exterior_pass/<Blend>.blend, with that blend and its maps sent along and the results returned into the
# pass's folder.
# Usage: pwsh -NoProfile -File art/blender/exterior_pass/Invoke-PassScript.ps1 -Blend s6_bake -Script check_luma.py -ScriptArgs "<args>"
param([Parameter(Mandatory)][string]$Blend, [Parameter(Mandatory)][string]$Script, [string]$ScriptArgs = '')
$ErrorActionPreference = 'Stop'
$repo = (Resolve-Path "$PSScriptRoot/../../..").Path
Set-Location $repo
$passRel = '.cache/art/exterior_pass'
$ship = @("$passRel/$Blend.blend") + @(Get-ChildItem "$repo/$passRel/textures" -File -ErrorAction SilentlyContinue | ForEach-Object { "$passRel/textures/$($_.Name)" })
$inner = "pwsh -NoProfile -File tools/Run-Blender.ps1 --background --factory-startup --python-exit-code 1 $passRel/$Blend.blend --python art/blender/exterior_pass/$Script -- $ScriptArgs"
& pwsh -NoProfile -File "$PSScriptRoot/Invoke-Remote.ps1" -Ship ($ship -join ',') -Run $inner
exit $LASTEXITCODE
