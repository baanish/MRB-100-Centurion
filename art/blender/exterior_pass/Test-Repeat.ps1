# Runs one pass stage twice from the same input and compares the two outputs object by object (fingerprint.py), and
# the two runs' step traces (pass_common.trace), so a stage that is not repeatable shows the first step and the objects
# that drift. The stage's input must already exist.
# Usage: pwsh -NoProfile -File art/blender/exterior_pass/Test-Repeat.ps1 -Stage s1_cut
param([Parameter(Mandatory)][string]$Stage)
$ErrorActionPreference = 'Stop'
$repo = (Resolve-Path "$PSScriptRoot/../../..").Path
Set-Location $repo
$kit = 'art/blender/exterior_pass'
$pass = '.cache/art/exterior_pass'
New-Item -ItemType Directory -Force "$pass/trace" | Out-Null
Get-ChildItem "$pass/trace" -Filter "*_$Stage`_*.json" | ForEach-Object { Remove-Item -LiteralPath $_.FullName }
foreach ($run in 'a', 'b') {
    if (Test-Path -Path '.cache/refresh/*-quiet.txt') { throw 'a quiet file exists: no local Blender now' }
    $env:PASS_TRACE = $run
    & pwsh -NoProfile -File tools/Run-Blender.ps1 --background --factory-startup --python-exit-code 1 --python "$kit/$Stage.py" -- --force *> "$pass/repeat_$Stage`_$run.log"
    $code = $LASTEXITCODE
    $env:PASS_TRACE = ''
    if ($code) { Get-Content "$pass/repeat_$Stage`_$run.log" -Tail 20; throw "$Stage run $run failed" }
    & pwsh -NoProfile -File tools/Run-Blender.ps1 --background --factory-startup --python-exit-code 1 "$pass/$Stage.blend" --python "$kit/fingerprint.py" -- "$pass/repeat_$Stage`_$run.json" *> $null
    if ($LASTEXITCODE) { throw "fingerprint of run $run failed" }
    $maps = @{}  # the maps a stage writes (stage 6's bake), by file
    Get-ChildItem "$pass/textures" -File -ErrorAction SilentlyContinue | ForEach-Object { $maps[$_.Name] = (Get-FileHash -LiteralPath $_.FullName).Hash }
    $maps | ConvertTo-Json | Set-Content "$pass/repeat_$Stage`_$run`_maps.json"
}
$ma = Get-Content "$pass/repeat_$Stage`_a_maps.json" -Raw | ConvertFrom-Json -AsHashtable
$mb = Get-Content "$pass/repeat_$Stage`_b_maps.json" -Raw | ConvertFrom-Json -AsHashtable
$md = @($ma.Keys + $mb.Keys | Sort-Object -Unique | Where-Object { $ma[$_] -ne $mb[$_] })
"MAPS $Stage`: $($ma.Count) files, $($md.Count) differ" + $(if ($md.Count) { ": " + ($md -join ', ') } else { '' })
function Compare-Hashes($fa, $fb) {
    $a = Get-Content $fa -Raw | ConvertFrom-Json -AsHashtable
    $b = Get-Content $fb -Raw | ConvertFrom-Json -AsHashtable
    @($a.Keys + $b.Keys | Sort-Object -Unique | Where-Object { $a[$_] -ne $b[$_] })
}
foreach ($t in Get-ChildItem "$pass/trace" -Filter "a_$Stage`_*.json" | Sort-Object Name) {
    $d = Compare-Hashes $t.FullName (Join-Path $t.DirectoryName ('b' + $t.Name.Substring(1)))
    "  step $($t.BaseName.Substring($Stage.Length + 3)): $($d.Count) differ" + $(if ($d.Count) { ": " + (($d | Select-Object -First 12) -join ', ') } else { '' })
}
$diff = Compare-Hashes "$pass/repeat_$Stage`_a.json" "$pass/repeat_$Stage`_b.json"
"REPEAT $Stage`: $($diff.Count) objects differ" + $(if ($diff.Count) { ": " + (($diff | Select-Object -First 25) -join ', ') } else { '' })
