# The exterior pass

Builds the shipped aircraft's exterior from the damage parts blend (`.cache/art/m4_parts/centurion_m4_parts.blend`,
BUILD.md "Change the model" step 4): the structure under the skin, the inward skin where damage opens it, the spoiler
wells, the flap fairings on their own hinges, the UV atlas, the distant model and the one bake. `tools/export_blockout.py`
exports its last blend; `art/export-manifest.json` pins that export. How to run it, what it needs and how long it takes:
BUILD.md, "The exterior pass".

## Stages

Each stage opens the previous stage's blend and saves its own to `.cache/art/exterior_pass/<stage>.blend` with a record
`<stage>.json` (input and script hashes, Blender version, timings, report). A stage whose record is current is skipped;
`Run-Pass.ps1 -Force` reruns it.

| Stage | Does |
|---|---|
| `s1_cut.py` | seams bisected and welded across parts, flap noses cut to an arc about the hinge, aileron halves, coves, lip pullback, ruddervator ends, spoiler wells (`spoiler_well.py`), the fairing variant (`fairing.py`), paint groups from the cut's own record (damage_parts' `source_group`) |
| `s2_structure.py` | closing members on every cut (`sections.py`), trusses (`truss.py`), stations, lattice and dark backdrops behind the holes, stage sleeves, honeycomb cores in the control surfaces |
| `s3_twins.py` | an inward copy of the skin wherever the damage map can open it or a hole looks at it; in wing-like parts a liner 12 mm in |
| `s4_uv.py` | livery split, seams on the aft bay's and wing roots' sharp edges, unwrap, 6 px gutter pack at 60 px/m, twin and trim UVs, every structure slot folded onto `Centurion_trim_cut` (the stock jet_mechanical sheet) |
| `s5_lod.py` | the distant model's hulls (`render_rig.py` slides the wing stages out for them) |
| `s6_bake.py` | the bake: colour, metal, normal, AO, the damage map (`damage_field.py`), four roundel-free liveries and the record `faction_marks.json` of their maps, to which `faction_marks.py place` adds the roundels once the bake is exported; the spoiler actuators linked for export (`export_parts.py`) |

`variant.json` `fairing_hinges` switches the flap fairings' rear halves onto their own hinges (on in the shipped
aircraft); their pivots are pinned in `baselines/fairing_hinges.json`. Each rear half rides its flap's underside and
telescopes: its part under the wing stays on the wing as a lined shroud, and a slimmer sleeve slides out of it.

## Gates

`Run-Pass.ps1` stops on any failure except the three marked as recorded.

| Gate | Holds | Script |
|---|---|---|
| Damage tree | the 45 parts, colliders, transforms and properties unchanged, but the spoiler hinges | `check_damage_tree.py` |
| Travel | each surface over its full travel: visible poke-through and coplanar flicker | `check_travel.py` (records, does not stop) |
| Seams, folds, coves, paint groups, spoiler frame | inside stage 1 | `s1_cut.py` |
| Fairings carried | every 1 degree to 30, no rear half 1 mm into its flap, the other flaps and fairings, the fixed wing (shroud included), the aileron or the spoiler, either way; its top within 6 cm of its flap; its sleeve's front 1 cm inside the shroud | `fairing.py` `gate()`, at the end of stage 1 |
| Split halves | each aileron's halves posed as the game drives them (roll 25 either way, split 0 to 50 a half): no crossing over 1 mm | `split_gate.py` `gate()`, at the end of stage 1, and on stage 5's blend (Run-Pass) |
| Every cut closed; members inside the skin; members first through the holes | inside stage 2 (the last records, does not stop) | `s2_structure.py` |
| Layout pin | every island that matches `baselines/uv_layout_pin.npz` (faces and corners within 1 mm) keeps its pinned place; stops if one moved, or if a changed island finds no gap even at 85% density; `s4_uv.json` lists the islands packed afresh per part and why | `s4_uv.py` |
| Paint density | p5 least-axis density per part at 0.85 of the shipped UVs (wing roots 46.0 px/m with the fairing variant) | `check_density.py`, `baselines/density_shipped.json` |
| Triangles | 260,000 + 3% | `check_tris.py`, `baselines/budget.json` |
| Draw calls | 214 a pass, at most two slots a part besides glass and lights | `check_draws.py`, `baselines/draw_centurion.json` |
| AO | exposed skin's dark share at most the shipped bake's + 1 point | `check_ao.py`, `baselines/ao_shipped.json` |
| Open area | per part at 60 and 0 HP, totals within 1%, parts within 3% or 0.05 m2; no straight sight line through a hole | `check_damage_area.py`, `baselines/damage_area_pin.json` |
| Stencils | every stencil decal's inked cells (its box in a grid of cells two texels across, 8 by 8 at most) reached by its painter's texels; stops on any short (build 37's clipped serial fails it) | `s6_bake.py`, `stencils_s6.json` |
| Openings | where an outer skin edge ends, rays from outside aimed just past it that see structure, honeycomb or the inside of the hull, per object by edge length (records, does not stop) | `check_openings.py` |
| Roundels | placed on the bake's export and checked there (whole, upright, mirror-symmetric, seen from above and below both wing positions, on fixed skin no other surface shares), painted, verified, no roundel in a roundel-free map | `art/textures/faction_marks.py` |
| Luma | six views' dark share at most the shipped maps' + 1 point | `check_luma.py`, `baselines/luma_shipped.json` |
| Livery kit layers | each livery split into base, markings and panel lines (`.cache/art/exterior_pass/livery_layers/`, from the bake's `textures/livery_layer_sources/`) that stack back to it within one step a channel; `layers.json` records the errors | `livery_layers.py`, after the bake |

## Baselines

- `density_shipped.json`, `ao_shipped.json`, `luma_shipped.json`: each gate run once on the damage parts blend with
  the shipped maps; rerun the gate without `--against` on that blend to remake one.
- `damage_area_pin.json`: the open area of a full build, saved by `check_damage_area.py` without `--against`. It
  follows the UV pack, which differs between machines: save it on the machine that builds the release, from a full
  build, and re-pin when a skin change reflows the pack.
- `budget.json`: triangles per part (fixed skin, structure allowance, closing members, cores, `after`), measured once
  from the source and the stock Darkreach's structure density.
- `draw_centurion.json`: the prefab's renderers at full detail, audited in game; the draw gate adds those this blend
  does not hold (the cockpit's interior, the pilots).
- `fairing_hinges.json`: each fairing's pivot, `fairing_pivots.py`'s output: the point that drifts the rear half least
  off its flap's line (a single pivot slides it along the flap and off that line by about 4.8% of the pivot's drop)
  while its tail still moves 0.1 m aft at 30 degrees, one pivot for a left fairing and its mirror. `fairing.trim` then
  cuts the rear half to clear the flap by 7 mm at its vertices; measured over the travel its top runs 1 to 51 mm under the
  flap inboard and 6 to 44 mm outboard, the spread being that drift.

## Known open

- Travel (recorded): the inner flaps' cut-through at 25 degrees, 0.135 m2 left and 0.132 right, where the inboard
  fairing's fixed half meets the cove; the ailerons' last 0.002 to 0.004 m2, edges crossing the spoiler well's rails
  (accepted).
- Members first through the holes (recorded): outer wing 33%, aft fuselage 32%, fin tip 30%, under gates of 40%, 45% and
  30%.
- The split ailerons' noses, turning towards the lips at full roll and split (75 degrees), still cross the fixed wing's
  cove by up to 8 cm (`split_gate.py` measures it with the halves; `check_travel` records it). The lip pullback leaves
  the spoiler's footprint whole for its well, as the cove does.
- The outer ruddervators' cove ends: a wedge between the surface's end and the fin's, which the hinge-line extension
  does not reach.

## Repeatability

Two runs of the pass from the same source write the same export, file for file. `Test-Repeat.ps1 -Stage <stage>` runs a
stage twice and compares the objects (`fingerprint.py`) and the maps it writes; with `PASS_TRACE` set, the stages write
each object's content hash after every step (`pass_common.trace`), so the first step that parts is named. Keep element
lists out of Python sets (their order follows memory addresses, and string hashes are seeded anew per process): build
them with `dict.fromkeys`, or sort them; put what a bmesh operator creates in a canonical order when its numbering is
its own (`s2_structure.canonical_order`).

Blender's exact-shape UV packer is the exception: it lays the same islands out differently run to run, whatever the
hash seed or thread count. Stage 4 therefore pins every unchanged island to `baselines/uv_layout_pin.npz` and packs
only new or changed islands, at the pinned islands' density, round them: into the first gap that takes the island's
box, else its own outline, else the same 2% smaller at a time down to 85% of that density. One island that fits nowhere
stops the build with its part, face, area and size; it never costs the other islands their places. Each run writes the
layout it packed to `.cache/art/exterior_pass/uv_layout.npz`; after an accepted geometry change, copy that file over the
pin and commit it. `PASS_UV_PIN=none` packs freely, for a fresh layout: it moves every groove, so the livery kit's
templates need remaking after it.

## Traps

- Edit a helper module, then `-Force` the stages that import it, if its record still reads current.
- `id()` of a bmesh wrapper is not a vertex identity: key by `index` after `index_update()`.
- A loop that edits a bmesh down a list made beforehand edits stale entries once a neighbour has changed: stage 1's
  sliver caps merge one a neighbourhood a pass (a fan of caps on an aileron's end rib, each the next one's neighbour,
  opened 0.57 m of skin).
- `bmesh.ops.holes_fill` silently skips some clean rings: use `pass_common.fill_holes` for a cap that must exist.
- Anything built after stage 2's structure allowance is outside the triangle budget: build it before.
- The aileron's halves are separate objects: anything that gathers a part's meshes from `aileron_X_visible`'s children
  must add `aileron_X_visible_lower` (as `s5_lod.own_meshes` does).
- The density gate's p5 is a count percentile: removing triangles elsewhere on a part moves it.
- Stage 1's order: coves, then spoiler wells. Wells first left 13 folds in an outer wing.
- The open-area pin hashes the owner skin: flattening faces into copies moves it without a design change.
- Hiding render objects from a live collection loop skips most of them (`render_rig.hide_helpers` snapshots first).
- Coincident inward copies in Cycles shadow the skin black: `check_luma` pushes them 2 mm in.
- `.cache/art/exterior_pass/textures_marked/` is refreshed only by `Run-Pass.ps1` after stage 6; a stopped run leaves
  old marked liveries over new maps.
