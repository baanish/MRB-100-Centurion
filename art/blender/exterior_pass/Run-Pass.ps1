# Runs the exterior pass's Blender stages in order, stopping at the first failure, then its gates. Each stage skips
# itself when its record is current (.cache/art/exterior_pass/<stage>.json), so a rerun restarts at the first stale
# stage; -Force reruns them. Local runs go through tools/Run-Blender.ps1 (refused while a .cache/refresh/*-quiet.txt
# exists); -Remote runs each stage on the remote host through tools/Run-Remote.ps1 (docs/REMOTE.md), which sends this
# checkout, and checks each returned blend against the hash its stage recorded. BUILD.md, "The exterior pass".
# Usage: pwsh -NoProfile -File art/blender/exterior_pass/Run-Pass.ps1 [-From s1_cut] [-To s6_bake] [-Force] [-Remote [-Tree <name>]]
param([string]$From = 's1_cut', [string]$To = 's6_bake', [switch]$Force, [switch]$Remote, [string]$Tree = '')
$ErrorActionPreference = 'Stop'
$repo = (Resolve-Path "$PSScriptRoot/../../..").Path
Set-Location $repo
$stages = 's1_cut', 's2_structure', 's3_twins', 's4_uv', 's5_lod', 's6_bake'
$kit = 'art/blender/exterior_pass'
$passRel = '.cache/art/exterior_pass'
$pass = Join-Path $repo $passRel
New-Item -ItemType Directory -Force $pass | Out-Null

# The inputs git does not carry, sent with every remote run: the damage parts blend the pass starts from, the detailed
# aircraft stage 1 reads paint groups from, and the gear's maps stage 6 lists for the export.
$ship = @('.cache/art/m4_parts/centurion_m4_parts.blend', '.cache/art/m4/centurion_m4_retracted.blend') + @(
    'b', 'm', 'n' | ForEach-Object { ".cache/art/m4_parts/textures/gear_trim_$_.png" })
if ($Remote) {
    # the stock sheet's maps the stages read (pass_common.game_texture), from this machine's game export, for a host
    # that has none; game art, kept in the ignored cache
    $export = (Get-Content "$repo/tools/local-paths.json" -Raw | ConvertFrom-Json).game_export
    $local = '.cache/art/game_textures/Texture2D'
    New-Item -ItemType Directory -Force "$repo/$local" | Out-Null
    foreach ($m in 'jet_mechanical_AlbedoTransparency.png', 'jet_mechanical_MetallicSmoothness.png', 'jet_mechanical_Occlusion.png') {
        Copy-Item -LiteralPath "$export/Texture2D/$m" -Destination "$repo/$local/$m" -Force
        $ship += "$local/$m"
    }
}

function Invoke-PassBlender([string]$name, [string]$blenderArgs) {
    $log = Join-Path $pass "$name.log"
    $t0 = Get-Date
    if ($Remote) {
        $s = $ship + @(Get-ChildItem $pass -Filter 's?_*.blend' -ErrorAction SilentlyContinue | ForEach-Object { "$passRel/$($_.Name)" })
        $inner = "pwsh -NoProfile -File tools/Run-Blender.ps1 --background --factory-startup --python-exit-code 1 $blenderArgs"
        & pwsh -NoProfile -File "$PSScriptRoot/Invoke-Remote.ps1" -Ship ($s -join ',') -Run $inner -Tree $Tree *> $log
        $code = $LASTEXITCODE
    }
    else {
        if (Test-Path -Path '.cache/refresh/*-quiet.txt') { throw 'a quiet file exists: no local Blender now; use -Remote' }
        & pwsh -NoProfile -File tools/Run-Blender.ps1 --background --factory-startup --python-exit-code 1 @($blenderArgs -split ' ') *> $log
        $code = $LASTEXITCODE
    }
    if ($code -ne 0) { Get-Content $log -Tail 30; throw "$name failed (exit $code, log $log)" }
    "{0} done in {1:n0} s" -f $name, ((Get-Date) - $t0).TotalSeconds
}

$a = $stages.IndexOf($From); $b = $stages.IndexOf($To)
if ($a -lt 0 -or $b -lt $a) { throw "unknown stage range $From to $To" }
foreach ($s in $stages[$a..$b]) {
    $extra = if ($Force) { ' -- --force' } else { '' }
    Invoke-PassBlender $s "--python $kit/$s.py$extra"
    $rec = Get-Content (Join-Path $pass "$s.json") -Raw | ConvertFrom-Json
    $blend = Join-Path $pass "$s.blend"
    $got = (Get-FileHash -LiteralPath $blend -Algorithm SHA256).Hash.Substring(0, 16).ToLowerInvariant()
    if ($rec.output_sha -and $got -ne $rec.output_sha) { throw "$s.blend came back as $got, recorded $($rec.output_sha)" }
    "  $s.blend whole ($got)"
    # gates: the damage tree unchanged after the cut; the triangle and draw budgets after the last geometry stage
    if ($s -eq 's1_cut') {
        Invoke-PassBlender 'check_damage_tree' "--python $kit/check_damage_tree.py -- $passRel/s1_cut.blend $passRel/damage_tree_s1.json"
        $c = Get-Content (Join-Path $pass 'damage_tree_s1.json') -Raw | ConvertFrom-Json
        $moved = @($c.changed_besides_render_mesh.PSObject.Properties.Name | Where-Object { $_ -notmatch '^spoiler_[LR]$' })
        if ($c.missing.Count -or $moved.Count -or $c.parts_present -ne 45) { throw "s1_cut changed the damage tree: missing $($c.missing -join ','), changed $($moved -join ',')" }
        "  tree unchanged: 45 parts, $($c.colliders_compared) colliders; only the spoiler hinges moved"
        Invoke-PassBlender 'check_travel' "$passRel/s1_cut.blend --python $kit/check_travel.py -- $passRel/travel_s1.json --record"
        $t = Get-Content (Join-Path $pass 'travel_s1.json') -Raw | ConvertFrom-Json
        "  travel: $(if ($t.fails.Count) { "FAIL recorded, $($t.fails.Count) surfaces (travel_s1.json)" } else { 'pass' })"
    }
    if ($s -eq 's4_uv') {  # lettering on unmirrored islands; paint density per part along both axes against the shipped UVs
        Invoke-PassBlender 'check_lettering' "$passRel/s4_uv.blend --python $kit/check_lettering.py -- $passRel/lettering_s4.json"
        '  lettering: every stencil reads left to right on its own side'
        Invoke-PassBlender 'check_density' "$passRel/s4_uv.blend --python $kit/check_density.py -- $passRel/density_s4.json --against $kit/baselines/density_shipped.json"
        '  density: every part within the shipped least-axis floor'
    }
    if ($s -eq 's5_lod') {
        Invoke-PassBlender 'check_tris' "$passRel/s5_lod.blend --python $kit/check_tris.py -- $passRel/tris_s5.json"
        "  triangles: $((Get-Content (Join-Path $pass 'tris_s5.json') -Raw | ConvertFrom-Json).total)"
        Invoke-PassBlender 'check_draws' "$passRel/s5_lod.blend --python $kit/check_draws.py -- $passRel/draws_s5.json"
        $d = Get-Content (Join-Path $pass 'draws_s5.json') -Raw | ConvertFrom-Json
        "  draw calls a pass: $($d.lod0.draws_total) (today $($d.lod0.budget), Darkreach $($d.lod0.darkreach), $($d.lod0.draws_without_glass_and_lights) without glass and lights); most slots on a part $($d.lod0.max_slots_on_a_part); simple model $($d.lod1.draws) draws, $($d.lod1.tris) triangles"
        # stage 1's split gate again, now the halves carry stage 2's honeycomb core and stage 3's twins
        Invoke-PassBlender 'split_gate' "$passRel/s5_lod.blend --python $kit/split_gate.py -- --gate"
        '  split halves: no crossing over 1 mm with their structure, roll 25 either way, split 0 to 50'
    }
    if ($s -eq 's6_bake') {  # the exposed skin's AO against the shipped bake's; the damage's open skin held to its pin
        Invoke-PassBlender 'check_ao' "$passRel/s6_bake.blend --python $kit/check_ao.py -- $passRel/textures/centurion_ao.png $passRel/ao_s6.json --against $kit/baselines/ao_shipped.json"
        $ao = Get-Content (Join-Path $pass 'ao_s6.json') -Raw | ConvertFrom-Json
        "  AO on the exposed skin: $($ao.whole.dark_share) of it under 0.15, mean $($ao.whole.mean); held to the whole skin's shipped share (no shipped part): $($ao.held_to_whole -join ', ')"
        Invoke-PassBlender 'check_damage_area' "$passRel/s6_bake.blend --python $kit/check_damage_area.py -- $passRel/textures/centurion_dmg_b.png $passRel/damage_area_s6.json --against $kit/baselines/damage_area_pin.json"
        "  damage open area: every pinned part within its pin; not in the pin (totals only): $((Get-Content (Join-Path $pass 'damage_area_s6.json') -Raw | ConvertFrom-Json).not_pinned -join ', ')"
        # no skin face's UVs collapsed to a line (a streak across the atlas)
        Invoke-PassBlender 'check_uv_collapse' "$passRel/s6_bake.blend --python $kit/check_uv_collapse.py -- $passRel/uv_collapse_s6.json"
        '  skin UVs: none collapsed to a line'
        Invoke-PassBlender 'check_openings' "$passRel/s6_bake.blend --python $kit/check_openings.py -- $passRel/openings_s6.json"
        $op = @(Get-Content (Join-Path $pass 'openings_s6.json') -Raw | ConvertFrom-Json)
        "  openings (recorded): $(($op | Measure-Object m -Sum).Sum) m of skin edge sees in, on $($op.Count) objects (openings_s6.json)"
    }
}
if ($stages.IndexOf($To) -ge $stages.IndexOf('s6_bake') -and -not $Remote) {
    # the game's roundels painted onto the pass's roundel-free liveries (game art, never tracked), for the luma gate
    # placed on the bake's own export (its UVs), and checked there, first
    Invoke-PassBlender 'export_pass' "--python tools/export_blockout.py -- --blend $passRel/s6_bake.blend --out $passRel/export"
    $marks = @('--record', "$passRel/faction_marks.json", '--maps', "$passRel/textures", '--out', "$passRel/textures_marked", '--hashes', "$passRel/textures_marked/marks.json")
    python -I art/textures/faction_marks.py place @marks --export "$passRel/export" | Select-Object -Last 1
    if ($LASTEXITCODE -ne 0) { throw 'faction_marks place failed' }
    python -I art/textures/faction_marks.py check @marks --export "$passRel/export" | Where-Object { $_ -match 'FAIL|PASS' }
    if ($LASTEXITCODE -ne 0) { throw 'faction_marks check failed' }
    python -I art/textures/faction_marks.py paint @marks | Select-Object -Last 1
    if ($LASTEXITCODE -ne 0) { throw 'faction_marks paint failed' }
    python -I art/textures/faction_marks.py verify-marked @marks | Select-Object -Last 1
    if ($LASTEXITCODE -ne 0) { throw 'faction_marks verify-marked failed' }
    $clean = Get-ChildItem "$pass/textures" -Filter 'centurion_livery_*.png' | ForEach-Object FullName
    python -I art/textures/faction_marks.py check-clean @clean | Select-Object -Last 1
    if ($LASTEXITCODE -ne 0) { throw 'faction_marks check-clean failed: a roundel-free map shows a roundel' }
    # the painted skin seen whole from six directions, its dark tail against the shipped maps'
    Invoke-PassBlender 'check_luma' "$passRel/s6_bake.blend --python $kit/check_luma.py -- $passRel/luma_pass.json --against $kit/baselines/luma_shipped.json"
    $l = (Get-Content (Join-Path $pass 'luma_pass.json') -Raw | ConvertFrom-Json).views
    "  luma dark share per view: " + (($l.PSObject.Properties | ForEach-Object { "$($_.Name) $($_.Value.dark_share)" }) -join ', ')
}
elseif ($stages.IndexOf($To) -ge $stages.IndexOf('s6_bake')) {
    '  NOT RUN with -Remote: the export, the roundel place and check, and the luma gate. Run them here with -From s6_bake (the stage skips itself, its record being current) before pinning the export.'
}
