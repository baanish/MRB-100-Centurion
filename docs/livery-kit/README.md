# MRB-100 Centurion livery kit

This kit lets you paint your own livery for the MRB-100 Centurion mod for Nuclear Option and load it in the game. A livery is one picture, 4096 by 4096 pixels, that the game wraps around the aircraft. The kit holds a paint model of the aircraft, the four liveries the mod ships as examples, flat templates for a 2D image editor and a builder that turns your picture into a livery the game loads.

What has been tried in the game: a livery built with these steps was installed in the game's `Skins` folder and shown on the Centurion. Sharing a livery on the Steam Workshop has not been tested. That section follows the game's code.

## What is in the kit

Unzip the kit and keep its folders together. The model finds its pictures through them.

| File | What it is |
|---|---|
| `model/centurion_paint_model.blend` | The aircraft's painted skin as one object, ready to paint on in Blender. It opens with BDF Matte Gray. |
| `model/centurion_paint_model.fbx` | The same model for other 3D paint programs. |
| `examples/centurion_livery_<name>.png` | The four shipped liveries, listed below. |
| `template/layers/<name>_01_base.png` | One shipped livery's paint with its shading, mottling, edge wear and soot, without markings or panel lines. |
| `template/layers/<name>_02_markings.png` | That livery's stencils, serials, keep-clear lines and lettering on a transparent layer. |
| `template/layers/<name>_03_panel_lines.png` | That livery's panel grooves and fasteners, in black on a transparent layer. Each livery has its own. |
| `template/uv_layout.png`, `template/uv_layout.svg` | The outline of every triangle of the picture. |
| `template/part_map.png` | Each part in its own flat colour. Pale colours mark shared areas. |
| `template/part_labels.png` | A number on each part, on a transparent layer to put over the part map. |
| `template/parts.csv` | Each part's number, name, colour in the part map, and how many of its pixels are shared. |
| `maps/centurion_n.png`, `_m.png`, `_ao.png` | The aircraft's surface maps (bumps, metal and shine, shadowing) for previewing in a 3D paint program. The game supplies these itself. You never install them. |
| `atlas.json` | The kit version, the fingerprint of the aircraft's paint layout, and the hashes of the maps and layers. See [Kit version and paint layout](#kit-version-and-paint-layout). |
| `install/CenturionLiveryBuilder.cs` | Builds your picture into a livery the game can load. |
| `install/meta.json` | An example of the label file the builder writes for a Centurion livery. |
| `LICENSE.txt` | The kit's licence. |

The example liveries:

| `<name>` | Livery | Side |
|---|---|---|
| `bdf_matte_gray` | BDF Matte Gray | Boscali |
| `bdf_forest_green` | BDF Forest Green | Boscali |
| `pala_matte_black` | PALA Matte Black | Primeva |
| `pala_desert_camo` | PALA Desert Camo | Primeva |

The examples and layers carry no national roundels. The game adds none to a player livery, so your livery shows only what you paint.

## What your livery controls

Your picture is the colour of the paint. The game adds the rest from the aircraft's own maps:

- The shape of panel joints and rivets comes from the aircraft's bump map, on every livery. The dark line in each joint is paint. Keep the panel lines layer for it, or leave the layer off for a cleaner aircraft.
- Shading, wear and soot on the shipped liveries are paint too. They live in each base layer. A flat colour you paint over a base replaces them.
- Metal and shine come from the aircraft's shared metal map.
- Soot, scorches and holes come from the aircraft's damage maps and appear over your paint as parts are hit. You paint nothing for damage.

A livery also has two optional settings, both set in the builder:

- **Glossiness** sets the shine of the whole skin. The shipped liveries use 0.
- **Colors** are five main colours. The builder picks them from your picture unless you set your own. The painted parts of the AWACS radar mount are tinted with the first one.

## Paint in 2D

Use an image editor with layers. GIMP and Krita are free, and Photoshop works too.

1. Pick a shipped livery to start from. Open its `template/layers/<name>_01_base.png`.
2. Add its `<name>_02_markings.png` as a layer above, then its `<name>_03_panel_lines.png` above that. Set all three to normal blending. This stack is the shipped livery: it matches `examples/centurion_livery_<name>.png` within one colour step per channel on every painted pixel.
3. Recolour the base layer, or paint a new base. Recolouring keeps the base's shading and wear. For a new base, fill the whole picture with your main colour first, so the small and thin parts take it.
4. Edit or replace the markings. Keep or hide the panel lines.
5. Save the result as a PNG, 4096 by 4096 pixels, without transparency. Any file name works.

To find and select a part:

- Add `template/part_map.png` as a layer and select that layer. Use the tool that selects one colour across the whole picture: **Select by Color** in GIMP, **Similar Color Selection** in Krita, or the **Magic Wand** with **Contiguous** unticked in Photoshop. Set its threshold to 0 (Krita calls it fuzziness, Photoshop calls it tolerance) and turn off antialiasing. Some part colours differ by only a few steps, so a higher setting also selects other parts.
- Put `template/part_labels.png` over the part map. A part's number sits on its own colour and on each pale colour it shares. Look the number up in `template/parts.csv` for its name.
- Click a colour to select every piece of that colour. Hold Shift and click to add another colour. To select a whole part, click each colour that carries its number.
- Each colour also covers a few pixels past the part's edge. The game reads those pixels too, so paint them with the part.
- Hide the part map and paint inside the selection on your own layer.
- `template/uv_layout.png` shows the outline of every triangle. The SVG has the same outline for vector editors.

### Shared and mirrored areas

Some parts on the left and right of the aircraft use the same area of the picture. Paint in a shared area shows on both parts. Lettering in a shared area reads backwards on one side.

- A pale colour in `part_map.png` marks every shared area, one colour for each set of parts that shares it. In `parts.csv`, a part with shared areas has "(shared patches)" after its name, and the `shared_texels` column counts its shared pixels.
- These pairs have separate left and right paint: wing roots, outer wings, both telescoping wing stages, engine nacelles and outboard flaps. The fuselage, cockpit, radome, spine and tail cone sit on the centreline. Put numbers and lettering on these, outside the pale areas.
- Some parts use one area twice, so paint there shows in two places, one of them mirrored. These include a strip along the top of the centre fuselage, parts of the engine nacelles, engine nozzles and bomb bays, part of the spine cover and a small area low on the cockpit. These are pale too.
- These pairs share some or all of their area: sponsons, wing struts, ailerons, spoilers, inboard flaps, flap track fairings, bomb bay doors, main gear and gear doors, nose hatches, engine nozzles and pylons, ruddervators and the V-tail roots and tips.
- The two moving fairings on each outboard flap share one area between the left and right wing. A marking painted on one fairing appears on the matching fairing of the other wing.

## Paint in 3D

Painting on the model lets you paint where you see it, without working out where each part sits in the flat picture. Blender is free and does this. Use Blender 5.3 or later: the paint model is saved by Blender 5.3, and an older Blender may not open it. These steps use Blender.

1. Copy the example you want to start from into `examples/` under a new name, for example `my_livery.png`.
2. Open `model/centurion_paint_model.blend`. The skin is one object, `centurion_paint_model`. Click it once in the viewport if it has no orange outline.
3. Switch to the **Texture Paint** workspace with the tab at the top.
4. In the image editor on the left, choose **Image > Open** and open `my_livery.png`.
5. In the panel on the right, open the **Tool** tab. Under **Texture Slots**, set **Mode** to **Single Image** and pick `my_livery.png`. You now paint into your picture and see it on the aircraft.
6. Paint. Turn the view with the middle mouse button. Set brush colour, size and strength in the tool settings at the top.
7. Save with **Image > Save** in the image editor. Saving the .blend file does not save a painted picture.

Other 3D paint programs open `model/centurion_paint_model.fbx`. Set the document size to 4096 and export only the base colour as a PNG.

## Build the livery in Unity

The game loads a player livery from a folder built by the game developer's livery project for Unity. The kit's builder adds what the Centurion needs: it labels the livery for the Centurion, imports your picture at full size and writes the catalog file the game reads.

You need:

- Unity Hub, and Unity 2022.3.62f2. Unity Hub offers the right editor version when you open the project.
- The livery project. Download it from https://github.com/Shockfront-Studios/Nuclear-Option-Mods with **Code > Download ZIP**, and unzip it.

Then:

1. In Unity Hub, choose **Add > Add project from disk** and pick the folder that holds the `Assets` and `ProjectSettings` folders. Windows may unzip it as a folder inside a folder of the same name, so pick the inner one. Then click the project to open it. The first import and build took about 2 minutes in testing. Later builds took about 15 seconds.
2. Copy `install/CenturionLiveryBuilder.cs` from the kit into the project's `Assets/Scripts/Editor/` folder. Unity compiles it and adds a menu item.
3. Drag your `my_livery.png` into the `Assets` folder in Unity's Project window. Leave its import settings alone. The builder sets them when it builds.
4. Choose **Nuclear Option > Create Centurion Livery Builder** and save the builder in `Assets`.
5. Click the builder and fill it in, in the Inspector:
   - **Bundle Name**: the livery's folder name, in lower case letters, digits and underscores. For example `my_centurion_livery`.
   - **Copy To App Data**: ticked, so the build is copied into the game's `Skins` folder.
   - **Texture**: your `my_livery.png`.
   - **Glossiness**: 0, as the shipped liveries use.
   - **Display Name**: the name the game's livery list shows.
   - **Faction**: empty for both sides, `Boscali` for BDF only, or `Primeva` for PALA only.
   - **Aircraft**: leave it. The Centurion builder ignores it.
   - **Use Custom Colors** and **Colors**: leave them to let the builder pick the main colours from your picture. **Get Colors from Texture** fills them in to start from.
6. Press **Build**. The livery is written to the project's `Bundles/my_centurion_livery/` folder. It holds four files: `catalog_1.json`, `catalog_1.hash`, `meta.json` and `my_centurion_livery_assets_all.bundle`.

To build without opening the editor, close the project in Unity first. Then run this from a command prompt as one line. `<Unity editor folder>` is the folder that holds `Unity.exe` for Unity 2022.3.62f2. Give the full path of your PNG, because a relative path is read from the project folder.

```text
start "" /wait "<Unity editor folder>\Unity.exe" -batchmode -quit -buildTarget Win64 -projectPath "<livery project folder>" -logFile "<livery project folder>\centurion_build.log" -executeMethod CenturionLiveryBuilder.BuildFromCommandLine -centurionTexture "<full path of your png>" -centurionBundle my_centurion_livery -centurionName "My Centurion livery"
```

Unity prints nothing in the prompt. When the prompt returns, open `centurion_build.log`. The line `Bundle was built to` means the build worked. A message from the table below is in that file.

Optional additions:

- `-centurionFaction Boscali` or `-centurionFaction Primeva` for one side only.
- `-centurionGloss 0.3` for a glossiness between 0 and 1. The default is 0.
- `-centurionNoCopy` to build into `Bundles` without copying to the game's `Skins` folder.

The command copies your picture into the project's `Assets/CenturionLivery/` folder and builds from there.

Use the Centurion builder, not the project's own **Create Livery Builder**. That one lists only the game's own aircraft, so its `meta.json` does not name the Centurion.

## Install and select it

1. Put the livery folder in the game's `Skins` folder:
   `%USERPROFILE%\AppData\LocalLow\Shockfront\NuclearOption\Skins\my_centurion_livery\`
   **Build** with **Copy To App Data** ticked does this for you.
2. Start the game with the Centurion mod installed.
3. Pick the Centurion and open its livery list. Your livery is listed as its display name followed by "(app data)", on the sides its faction allows.

To give your livery to a friend, zip the folder. They unzip it into the same `Skins` folder on their PC.

In a mission file, a Centurion with a local livery has `"liveryType": "AppData"` and `"liveryName": "my_centurion_livery"`, the folder name.

## Share it on the Steam Workshop

Workshop sharing has not been tested for the Centurion. These steps follow the game's code and the game's uploader.

The game's uploader accepts a livery only for an aircraft with a Workshop tag. The Centurion mod sets the tag `MRB-100 Centurion` when the game loads it, which needs Nuclear Option 0.34.6 or later. The mod's log, `BepInEx/LogOutput.log`, shows the line `workshop tag: baanish_centurion = 'MRB-100 Centurion'`.

1. Build your livery so its folder is in the game's `Skins` folder.
2. Start the game with the Centurion mod installed and open the Workshop upload page.
3. Choose **Aircraft Livery** as the type and press **Next**.
4. Pick your livery's folder name and press **Next**.
5. Fill in the details page. The title is your livery's display name and cannot be changed here: to change it, change **Display Name** in the builder and build again. Write a description and choose a preview image, a PNG or JPG of 1 MB or less. **Create New** stays grey until both are set. Choose whether the item is public. Tick **Mod Required**, so Workshop visitors see that the livery needs a mod. The tags the livery gets are `Aircraft Livery`, `MRB-100 Centurion`, and the faction if you set one.
6. Press **Create New**. This uploads the four files in your livery's folder to the Steam Workshop under your account.

A player who subscribes needs the Centurion mod installed. The livery then appears in the Centurion's livery list with "(workshop)" after its name. A player without the mod can subscribe, but the livery appears in no aircraft's list, because its `meta.json` names only the Centurion.

## What other players see

In multiplayer, your choice of livery reaches other players as a name: the folder name for a local livery, or the item for a Workshop livery. Each player's game loads that livery from their own copy.

- A player with the same folder in their `Skins` folder, or subscribed to the same Workshop item, sees your livery.
- Any other player sees the first shipped livery for your side: BDF Matte Gray for Boscali, PALA Matte Black for Primeva.

This behaviour is read from the game's code. It has not been tested in multiplayer with a custom Centurion livery.

## Limits and troubleshooting

### The builder's messages

The builder stops with a message when an input is wrong. In the editor it is in Unity's Console. On the command line it is in the log file named by `-logFile`.

| Message | Fix |
|---|---|
| `The Centurion needs a 4096 x 4096 PNG. This PNG is <width> x <height>.` | Resize or repaint the picture at 4096 by 4096 pixels. |
| `Choose a PNG texture from the project's Assets folder.` | Save the picture as PNG and drag it into `Assets`. |
| `Bundle Name must contain only lowercase letters, digits, and underscores.` | Rename it, for example `my_centurion_livery`. |
| `Enter the name to show in the game's livery list.` | Fill in **Display Name**. |
| `Choose Boscali or Primeva, or leave Faction empty for both sides.` | Pick one of the three. |
| `Switch the Unity build target to Windows before building a livery.` | Choose **File > Build Settings**, select Windows and press **Switch Platform**. |
| `Pass -centurionTexture <png> -centurionBundle <folder name> -centurionName <display name>.` | The command line is missing one of the three. |
| `-centurionTexture must name a PNG file.` | Give the path of a .png file. |
| `-centurionGloss must be between 0 and 1.` | Give a number from 0 to 1, with a full stop for the decimal point. |
| `<option> requires a value.` | Put a value after that option. |

### The picture

- It must be 4096 by 4096 pixels. The builder refuses any other size.
- Save it without transparency. The builder checks the size but not transparency.
- Colours are read as sRGB, the default in image editors.

### A livery that does not show

- The game lists a livery only for the aircraft its `meta.json` names. A Centurion livery has `"AircraftKey": "baanish_centurion"`. Compare yours with the kit's `install/meta.json`.
- A livery with a faction appears only on that side.
- The folder must hold the four files from the build, directly inside `Skins\<folder name>\`, not in a folder inside it.
- The Centurion mod must be installed and loaded.

### Kit version and paint layout

Each kit fits one layout of the paint picture. `atlas.json` records the kit's `version` and the layout's fingerprint, `skin_uv_sha256`.

- Use the kit whose version matches your Centurion mod. This kit is for the version in its file name.
- A later mod version can move parts around in the paint picture. It then ships a new kit with a new fingerprint.
- A livery built from an older layout still loads, because the game matches a livery by aircraft and not by layout. Its paint then lands on the wrong parts.
- When a new kit comes out, compare its `skin_uv_sha256` with your old kit's. The same fingerprint means your livery still fits. A different one means repaint from the new templates.

## Licence

See `LICENSE.txt`.
