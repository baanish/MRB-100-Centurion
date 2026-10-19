"""Nose-up map silhouette from the retracted Centurion composite.

Run through tools/Run-Blender.ps1 --background --factory-startup --python
art/blender/aircraft_icons.py -- --blend .cache/art/m4/centurion_m4_retracted.blend
The map sprite follows Alkyon/Darkreach/Medusa's filled white convention and keeps
Darkreach's 4 px minimum margin. There is no HUD contact sprite: the HUD marker is
the stock hudIcon_aircraft triangle every aircraft shares.
"""
import argparse
import sys
from pathlib import Path

import bpy
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from m4 import texture

REPO = Path(__file__).resolve().parents[2]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--blend', type=Path, required=True)
    parser.add_argument('--out', type=Path, default=REPO / 'unity/Assets/Blueprinter/Mods/centurion/Icons')
    args = parser.parse_args(sys.argv[sys.argv.index('--') + 1:])
    bpy.ops.wm.open_mainfile(filepath=str(args.blend.resolve()))
    parts = [o for o in bpy.data.collections['Centurion'].all_objects
             if o.type == 'MESH' and o.users_collection[0].name not in ('Colliders', 'LOD1')]
    points = [o.matrix_world @ v.co for o in parts for v in o.data.vertices]
    x0, x1 = min(p.x for p in points), max(p.x for p in points)
    y0, y1 = min(p.y for p in points), max(p.y for p in points)
    scene = bpy.context.scene
    camera = bpy.data.objects.new('icon_camera', bpy.data.cameras.new('icon_camera'))
    scene.collection.objects.link(camera)
    camera.data.type = 'ORTHO'
    camera.data.clip_end = 500
    camera.location = ((x0 + x1) / 2, (y0 + y1) / 2, 100)
    camera.rotation_euler = (0, 0, np.pi)
    scene.camera = camera
    scene.render.engine = 'BLENDER_WORKBENCH'
    shading = scene.display.shading
    shading.light, shading.color_type = 'FLAT', 'OBJECT'
    shading.show_cavity = shading.show_shadows = shading.show_object_outline = shading.show_specular_highlight = False
    scene.display.render_aa = 'OFF'
    scene.view_settings.view_transform, scene.view_settings.look = 'Standard', 'None'
    scene.render.dither_intensity = 0
    scene.render.film_transparent = True
    scene.render.use_stamp = False
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = 'PNG'
    scene.render.image_settings.color_mode = 'RGBA'
    for obj in scene.objects:
        if obj.type == 'MESH':
            obj.hide_render = obj not in parts
            obj.color = (1, 1, 1, 1)
    args.out.mkdir(parents=True, exist_ok=True)
    size, extent = 256, 248
    camera.data.ortho_scale = max(x1 - x0, y1 - y0) * size / extent
    pixels = 4 * size
    scene.render.resolution_x = scene.render.resolution_y = pixels
    scene.render.filepath = str(Path(bpy.app.tempdir) / 'centurion_map_mask.png')
    bpy.ops.render.render(write_still=True)
    img = texture.load_image(Path(scene.render.filepath))
    mask = np.array(img.pixels[:], np.float32).reshape(pixels, pixels, 4)[..., 3]
    bpy.data.images.remove(img)
    coverage = mask.reshape(size, 4, size, 4).mean(axis=(1, 3))
    rgba = np.dstack([np.ones((size, size, 3)), coverage])
    texture.save_image(rgba, args.out / 'centurion_map.png', srgb=True)
    print('Centurion icon: filled 256x256 map/tile, nose up, white on transparent')


if __name__ == '__main__':
    main()
