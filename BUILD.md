# Building the MRB-100 Centurion

The mod is two files that work only as a pair: `Centurion.dll`, the BepInEx plugin built from `src/Centurion`, and `centurion_<version>.nobp`, the Blueprinter bundle built by the Unity project in `unity/`. The build needs the mesh and texture exports in `art/export`, `art/export_awacs` and `art/export_cockpit` pinned by `art/export-manifest.json`. The public source checkout includes those exports. With the pinned files in place, Blender is needed only for model changes.

If a step fails, open an issue with the step and the error.

## What you need

- Windows, PowerShell 7, and Git with Git LFS (the skin textures are LFS files: run `git lfs pull` if a PNG opens as a short text file).
- The .NET SDK (8 or later).
- Python 3.9 or later with NumPy and Pillow (`python -m pip install numpy pillow`), available as `python`. The build uses it for the export hash check and the faction roundels (`art/textures/faction_marks.py` imports both packages).
- Unity Editor **2022.3.62f2**.
- A purchased copy of Nuclear Option **0.34.6** with BepInEx 5 installed in it. Set `game` in `tools/local-paths.json` or set `NUCLEAR_OPTION_DIR` to its install folder. The build reads the game and BepInEx assemblies there.
- An export of your game install from **AssetRipper 2.0.0** (Script Content Level **Level 1**, Script Export Format **Decompilation**). The repository holds no game assets; the build clones stock settings from your local import. Set `game_export` in `tools/local-paths.json` to that export's `ExportedProject/Assets` folder: the build paints the game's faction roundels from it.

## Prepare the Unity project (once)

1. Open the `unity` folder in Unity Hub and let Unity restore its packages. Blueprinter Editor is pinned to commit `9a4a8e509480cbcde901a577985d5e9cbc570d91` in `unity/Packages/manifest.json`.
2. Open **Blueprinter > Project Setup** and enter the version of the game you are importing.
3. Choose **Import Game Assemblies** and select your `NuclearOption.exe`. Let Unity finish compiling and reload.
4. Import the game assets from your AssetRipper export's `ExportedProject/Assets` folder through Blueprinter's importer. They land in `Assets/Blueprinter/_donotship`, where the build looks stock assets up by path.
5. Import **TMP Essentials** when Unity asks.
6. Close Unity. The build runs it in batch mode and refuses while an editor has the project open.

Imported game assets, assemblies and Unity caches stay local and are ignored by git. Never commit them.

## Build

From the repository root:

```powershell
pwsh -NoProfile -File tools/Build-Centurion.ps1
```

It checks every export against `art/export-manifest.json`, builds the plugin, copies it and BepInEx's assemblies into the Unity project, authors the aircraft from those pinned exports, and builds the bundle. It never re-exports a cached AWACS scene. The last line is the verdict, `G0.1 PASS: build/centurion_<version>.nobp ... with Centurion.dll (release build) ...` or `G0.1 FAIL: <why>`. Unity's logs stay in `build/logs`. Pass `-UnityPath <Unity.exe>` if it can't find Unity 2022.3.62f2.

The default is a release build. Pass `-Dev` for a dev build, which adds the diagnostics, the test hooks and the `Diagnostics`, `Debug` and `Capture` settings; the verdict then says `(dev build)`. Release packages are built without `-Dev`, and the test scenarios under `tests/agentic` require a dev build. A release build removes those three settings sections from a config file an earlier version wrote.

The liveries carry the game's own PALA and BDF roundels, which the repository never holds, not even inside a livery map. The exports carry the liveries without them, and `art/textures/faction_marks.json` records where each roundel goes. `python art/textures/faction_marks.py place` writes that record from the placements in the script (part, face, span, station, size) on the UVs of `art/export`, so it is rerun after every export that changes the UVs. Before Unity runs, the build checks every recorded roundel on the export (`check`: whole, upright, mirror-symmetric, seen from above and below with the wing retracted and extended, on fixed skin no other surface shares), paints the roundels from your asset export (`python art/textures/faction_marks.py`) into `unity/Assets/Blueprinter/Mods/centurion/Liveries`, which git ignores, and checks every painted livery carries them (`verify-marked`). Without `game_export` the build stops there.

The build rewrites authored prefabs under `unity/Assets/Blueprinter/Mods/centurion`. Unity regenerates their object IDs. Release checks exempt those prefab files, but check the bytes of FBX, textures and other authored assets before and after building.

## Install your build

Close the game, then copy `build/Centurion.dll` and `build/centurion_<version>.nobp` into `BepInEx/plugins/baanish.centurion/` in the game folder. Install and enable Blueprinter. Refresh builds are tested with Blueprinter 2.1.1. `BepInEx/LogOutput.log` names the version on load: `MRB-100 Centurion <version> (baanish.centurion)`.

## Change the model

The model is generated by Python scripts in `art/blender` that run in Blender 5.3 (another version can build a different mesh, which the manifest check below shows). Each script's docstring has its full options. From the repository root, in order:

1. `blender --background --factory-startup --python art/blender/build_centurion.py -- --step 6.1 --span retracted,extended` writes the blockout to `.cache/art/blockout_s61`.
2. `blender --background --factory-startup --python art/blender/detail_centurion.py -- --group all --span retracted` writes the detailed aircraft to `.cache/art/m4`.
3. `blender --background --factory-startup --python art/blender/awacs_mount.py` writes the AWACS beam to `.cache/art/awacs_mount`.
4. Re-cut the detailed aircraft into its damage parts (the 45-part tree in `art/blender/damage_tree.py`), which writes `.cache/art/m4_parts/centurion_m4_parts.blend`:
   - `blender --background .cache/art/m4/centurion_m4_retracted.blend --python art/blender/damage_parts.py -- --stage cut --work .cache/art/m4_parts`
   - `python -I art/blender/damage_finalize.py .cache/art/m4_parts` (it needs SciPy: `python -m pip install scipy`)
   - `blender --background .cache/art/m4/centurion_m4_retracted.blend --python art/blender/damage_parts.py -- --stage build --work .cache/art/m4_parts --out .cache/art/m4_parts/centurion_m4_parts.blend`
5. `blender --background --factory-startup --python art/blender/status_silhouette.py` redraws the cockpit and HUD line art into the mod folder; add `--damage-blend .cache/art/m4_parts/centurion_m4_parts.blend` to redraw the damage diagram from the damage parts.
6. Run the exterior pass on the damage parts (below, "The exterior pass"), which writes `.cache/art/exterior_pass/s6_bake.blend`. Export the aircraft with `blender --background --factory-startup --python tools/export_blockout.py -- --blend .cache/art/exterior_pass/s6_bake.blend`. Export an intentionally changed AWACS or cockpit scene with the same command, adding `--out art/export_awacs` or `--out art/export_cockpit` and its scene's `--blend` path. All three use the same FBX metadata scrubber.
7. Run `python art/textures/faction_marks.py place`, `python tools/scrub_fbx.py` to clean existing Unity copies too, then `python tools/export_manifest.py --write`. Review and commit the regenerated `art/textures/faction_marks.json` and `art/export-manifest.json` with the changed source and exports. Run `pwsh -NoProfile -File tools/Build-Centurion.ps1` to build from the pinned files.

## The exterior pass

`art/blender/exterior_pass` turns the damage parts into the shipped exterior: structure under the skin, inward skin where damage opens it, spoiler wells, flap fairings on their own hinges, the UV atlas, the distant model and the bake. Its README lists the stages, gates and baselines.

- Needs: Blender 5.3 (`blender` in `tools/local-paths.json`); Python 3 with Pillow and NumPy for the roundel step; `game_export` in `tools/local-paths.json`, the game's asset export (its `Assets` folder), from which the pass reads the stock `jet_mechanical` maps and the roundels; the damage parts from steps 1, 2 and 4 above (`.cache/art/m4_parts/centurion_m4_parts.blend` with its `textures/`, `.cache/art/m4/centurion_m4_retracted.blend`).
- Run: `pwsh -NoProfile -File art/blender/exterior_pass/Run-Pass.ps1` (stages 1 to 6 with their gates, then the bake's export, the roundels placed and checked on it, painted, and the luma gate). `-From` and `-To` run part of the chain, and `-Force` reruns stages whose records read current. Output and logs go to `.cache/art/exterior_pass/`.
- Time: about 20 minutes on a desktop (stages 1 to 5 about 4 minutes, stage 6's bake about 15, the gates 1).
- Checking a rebuild: the pass and the export are repeatable, so a rebuild from the same source and the same Blender writes the export the manifest pins, file for file: `python -I tools/export_manifest.py` passes. A difference there is a change in the source, the pass, the export tool or Blender. The pass's gates are what they always were: they hold the design (triangles, draws, density, AO, open area, luma, travel), not the bytes.
- A stage that stops repeating: `pwsh -NoProfile -File art/blender/exterior_pass/Test-Repeat.ps1 -Stage <stage>` runs it twice from the same input and names the first step and the objects that differ. Order that comes from Python sets or from a bmesh operator's own numbering is the usual cause.
- Repeatability is proven with Blender 5.3.0 on two Windows machines (two runs in one folder, a fresh checkout, and the second machine's export equal to the first's, file for file). Another Blender version has not been compared; if its export differs, its open-area baseline (`baselines/damage_area_pin.json`, which follows the UV pack) and the manifest belong to whichever machine builds the release.
