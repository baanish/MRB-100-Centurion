"""Build the Centurion paint kit from the manifest-pinned exterior export."""

import argparse
import colorsys
import csv
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re
import shutil
import sys
import zipfile

import numpy as np
from PIL import Image, ImageChops, ImageDraw, ImageFont
from scipy import ndimage

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "art/textures"))
from airframe import barycentric, child, fbx_nodes, fbx_triangles  # noqa: E402

ATLAS_SIZE = 4096
STACK_TOLERANCE = 1
PART_MAP_MARGIN = 6  # px: the gap the UV pack leaves between islands, which the bake fills with each island's paint
MODEL = "centurion_paint_model"
SHARED_MAPS = ("centurion_n.png", "centurion_m.png", "centurion_ao.png")
LIVERIES = ("bdf_matte_gray", "bdf_forest_green", "pala_matte_black", "pala_desert_camo")
TEMPLATES = ("uv_layout.png", "uv_layout.svg", "part_map.png", "part_labels.png", "parts.csv")
LAYER_DIR = Path(".cache/art/exterior_pass/livery_layers")
LAYERS = ("base", "markings", "panel_lines")
DOCS = Path("docs/livery-kit")
BUILDER = "CenturionLiveryBuilder.cs"


@dataclass
class PaintPart:
    vertices: np.ndarray
    faces: np.ndarray
    uv: np.ndarray
    normals: np.ndarray


def sha256(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def paint_part(path, name, placement):
    """Read the render mesh only. Collider and distant meshes can share its FBX."""
    tree = fbx_nodes(path.read_bytes())
    objects = {node[1][0]: node for node in next(n[2] for n in tree if n[0] == "Objects")}
    links = next(n[2] for n in tree if n[0] == "Connections")
    model = next(key for key, node in objects.items() if node[0] == "Model" and node[1][1] == name)
    attached = [props[1] for _, props, _ in links if props[0] == "OO" and props[2] == model]
    materials = [objects[key][1][1] for key in attached if objects[key][0] == "Material"]
    if "Centurion_skin" not in materials:
        return None
    geometry = next(objects[key] for key in attached if objects[key][0] == "Geometry")
    index = child(geometry, "PolygonVertexIndex")[1][0]
    slots = child(child(geometry, "LayerElementMaterial"), "Materials")[1][0]
    ends = np.flatnonzero(index < 0)
    starts = np.r_[0, ends[:-1] + 1]
    skin = np.array(materials)[np.broadcast_to(slots, ends.shape)] == "Centurion_skin"
    if not skin.any():
        return None
    loops = np.array([(s, k, k + 1) for s, e in zip(starts[skin], ends[skin]) for k in range(s + 1, e)])
    vertex_index = np.where(index < 0, ~index, index)[loops]
    used, faces = np.unique(vertex_index, return_inverse=True)
    axes = placement["axes_unity"]
    basis = np.array([axes[axis] for axis in ("right", "up", "forward")])

    def blender_space(values):
        return values[..., [0, 2, 1]] * (-1, -1, 1)

    vertices = child(geometry, "Vertices")[1][0].reshape(-1, 3)[used]
    vertices = blender_space(vertices * (-1, 1, 1) @ basis + placement["pivot_unity"])

    def loop_values(layer_name, value_name, index_name, width):
        layer = child(geometry, layer_name)
        if child(layer, "MappingInformationType")[1][0] != "ByPolygonVertex":
            raise ValueError(f"{name}: unexpected {layer_name} mapping")
        values = child(layer, value_name)[1][0].reshape(-1, width)
        indices = child(layer, index_name)
        return values[(indices[1][0] if indices else np.arange(len(index)))[loops]]

    uv = loop_values("LayerElementUV", "UV", "UVIndex", 2)
    normals = loop_values("LayerElementNormal", "Normals", "NormalsIndex", 3)
    normals = blender_space(normals * (-1, 1, 1) @ basis)
    return PaintPart(vertices.astype("<f4"), faces.reshape(-1, 3), uv.astype("<f4"), normals.astype("<f4"))


def kit_inputs(root):
    manifest_path = root / "art/export-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    export = root / "art/export"

    def pinned(path):
        relative = path.relative_to(root).as_posix()
        if manifest.get(relative) != sha256(path):
            raise ValueError(f"{relative} differs from the export manifest")
        return path

    parts = {}
    blockout = json.loads(pinned(export / "blockout.json").read_text(encoding="utf-8"))
    for name, placement in sorted(blockout["parts"].items()):
        if placement.get("fbx"):
            part = paint_part(pinned(export / placement["fbx"]), name, placement)
            if part is not None:
                parts[name] = part
    if not parts:
        raise ValueError("the export has no paintable exterior")

    bake = json.loads((root / "art/textures/faction_marks.json").read_text(encoding="utf-8"))
    if bake["atlas_size"] != ATLAS_SIZE:
        raise ValueError("unexpected bake atlas size")
    textures = export / "textures"
    examples = {}
    for key in LIVERIES:
        livery = bake["liveries"][key]
        path = pinned(textures / livery["map"])
        if manifest[path.relative_to(root).as_posix()] != livery["map_sha256"]:
            raise ValueError(f"{path.name} differs from the roundel-free bake record")
        examples[key] = path
    maps = [pinned(textures / name) for name in SHARED_MAPS]
    source = {"atlas_size": ATLAS_SIZE, "bake_uv_sha256": bake["skin_uv_sha256"],
              "export_manifest_sha256": sha256(manifest_path),
              "map_sha256": {p.name: manifest[p.relative_to(root).as_posix()] for p in [*examples.values(), *maps]}}
    return parts, examples, maps, source


def triangle_keys(uv):
    """Canonical little-endian float32 triangles, preserving duplicates and ignoring loop order."""
    uv = np.asarray(uv, dtype="<f4").copy()
    uv[uv == 0] = 0  # signed zero has the same atlas address
    order = np.lexsort((uv[..., 1], uv[..., 0]), axis=1)
    return np.take_along_axis(uv, order[..., None], axis=1).reshape(-1, 6).view("V24").ravel()


def uv_fingerprint(parts):
    digest = hashlib.sha256()
    for name, part in sorted(parts.items()):
        keys = np.sort(triangle_keys(part.uv))
        digest.update(f"{name}\0{len(keys)}\n".encode())
        digest.update(keys.tobytes())
    return digest.hexdigest()


def atlas_triangles(uv, size):
    uv = uv.astype(np.float64)
    return np.stack((uv[..., 0], 1 - uv[..., 1]), axis=-1) * size


def raster_islands(triangles, size):
    """Mark texel centres inside each triangle, including its edge and excluding collapsed UV faces."""
    mask = np.zeros((size, size), bool)
    points = triangles.astype(np.float64) - 0.5
    lower = np.maximum(np.ceil(points.min(axis=1)).astype(int), 0)
    upper = np.minimum(np.floor(points.max(axis=1)).astype(int), size - 1)
    for triangle, (x0, y0), (x1, y1) in zip(points, lower, upper):
        if x0 <= x1 and y0 <= y1:
            y, x = np.ogrid[y0:y1 + 1, x0:x1 + 1]
            weights = barycentric(triangle, x, y)
            if weights is not None:
                mask[y0:y1 + 1, x0:x1 + 1] |= (weights >= -1e-9).all(axis=-1)
    return mask


def raster_reuse(triangles, size):
    """Mark texel centres strictly inside two or more triangles, so shared edges do not count."""
    hits = np.zeros((size, size), np.uint16)
    points = triangles.astype(np.float64) - 0.5
    lower = np.maximum(np.ceil(points.min(axis=1)).astype(int), 0)
    upper = np.minimum(np.floor(points.max(axis=1)).astype(int), size - 1)
    for triangle, (x0, y0), (x1, y1) in zip(points, lower, upper):
        if x0 <= x1 and y0 <= y1:
            y, x = np.ogrid[y0:y1 + 1, x0:x1 + 1]
            weights = barycentric(triangle, x, y)
            if weights is not None:
                hits[y0:y1 + 1, x0:x1 + 1] += (weights > 1e-6).all(axis=-1)
    return hits > 1


def part_label(name):
    label = {"fuselage_R": "fuselage_rear", "Centurion": "centre_fuselage"}.get(name, name)
    label = label.replace("_visible", "").replace("baydoor", "bay_door").replace("geardoor", "gear_door")
    label = re.sub(r"_(L|R)(\d*)(?=M|_|$)",
                   lambda m: ("_left" if m[1] == "L" else "_right") + ("_" + m[2] if m[2] else ""), label)
    label = re.sub(r"_(A|F)([LR]?)$", lambda m: "_" + ("aft" if m[1] == "A" else "forward")
                   + {"L": "_left", "R": "_right", "": ""}[m[2]], label)
    label = re.sub(r"^(nacelle|nozzle|pylon)_([12])$", lambda m: m[1] + ("_left" if m[2] == "1" else "_right"), label)
    label = re.sub(r"_(left|right)M$", r"_main_\1", label)
    label = re.sub(r"flap_(left|right)_([12])", lambda m: ("inboard" if m[2] == "1" else "outboard")
                   + "_flap_" + m[1], label)
    label = re.sub(r"fairing(\d)", r"track_fairing_\1", label)
    return re.sub(r"tele(\d)", r"telescoping_stage_\1", label).replace("_", " ")


def template_maps(parts, folder, size):
    count = np.zeros((size, size), np.uint16)
    owner = np.zeros_like(count)
    group = np.zeros((size, size), np.uint64)  # the parts over each texel, as digits in base len(parts) + 1
    colours = [(0, 0, 0)]
    triangles = []
    for index, (name, part) in enumerate(parts.items(), 1):
        coords = atlas_triangles(part.uv, size)
        mask = raster_islands(coords, size)
        # Mirrored halves of one part can reuse one area. Exact double-sided duplicates are not reuse.
        reused = raster_reuse(atlas_triangles(np.unique(triangle_keys(part.uv)).view("<f4").reshape(-1, 3, 2), size), size)
        for covered in (mask, reused):
            count[covered] += 1
            group[covered] = group[covered] * (len(parts) + 1) + index
        owner[mask] = index
        colours.append(tuple(round(255 * c) for c in colorsys.hsv_to_rgb(index * 0.618034 % 1, 0.68, 0.83)))
        triangles.append(coords)
    occupied = count > 0
    shared = count > 1
    palette = np.asarray(colours, dtype=np.uint8)
    rgb = palette[owner]
    # One pale colour for each set of parts that shares an area, so a colour selection can pick that area alone.
    keys, members = np.unique(group[shared], return_inverse=True)
    pale = [[round(255 * c) for c in colorsys.hsv_to_rgb(index * 0.618034 % 1, 0.3, 1)] for index in range(len(keys))]
    rgb[shared] = np.asarray(pale, dtype=np.uint8)[members]
    # Spread each colour over its island's share of the gutter, so a selection also takes the paint the game reads there.
    distance, nearest = ndimage.distance_transform_edt(~occupied, return_indices=True)
    rgb = np.where((distance <= PART_MAP_MARGIN)[..., None], rgb[tuple(nearest)], 0).astype(np.uint8)
    Image.fromarray(rgb).save(folder / "part_map.png")

    # Number each part in the atlas and put the full labels in a separate overlay and CSV.
    labels = Image.new("RGBA", (size, size))
    draw = ImageDraw.Draw(labels)
    font = ImageFont.load_default(size=22)
    label_positions = []
    with (folder / "parts.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow(("id", "export_part", "label", "colour", "shared_texels"))
        for index, (name, coords) in enumerate(zip(parts, triangles), 1):
            mask = raster_islands(coords, size)
            shared_count = np.count_nonzero(mask & shared)
            label = part_label(name) + (" (shared patches)" if shared_count else "")
            writer.writerow((index, name, label, "#%02X%02X%02X" % colours[index], shared_count))
            own = (owner == index) & ~shared
            # Number the part's own colour and each shared colour on it, so every colour it needs carries its number.
            for region in [own, *(mask & (group == key) for key in np.unique(group[mask & shared]))]:
                if not region.any():
                    continue
                rows, cols = np.nonzero(region)
                x0, x1, y0, y1 = cols.min(), cols.max(), rows.min(), rows.max()
                local = region[y0:y1 + 1, x0:x1 + 1]
                y, x = np.unravel_index(ndimage.distance_transform_edt(np.pad(local, 1))[1:-1, 1:-1].argmax(), local.shape)
                anchor = int(x0 + x), int(y0 + y)
                x, y = anchor
                while any(abs(x - a) < 34 and abs(y - b) < 24 for a, b in label_positions):
                    y += 24 if anchor[1] < size // 2 else -24
                label_positions.append((x, y))
                if (x, y) != anchor:
                    draw.line((anchor, (x, y)), fill="white", width=2)
                draw.text((x, y), str(index), fill="white", stroke_width=2, stroke_fill="black",
                          anchor="mm", font=font)
    labels.save(folder / "part_labels.png")

    all_uv = np.concatenate([part.uv for part in parts.values()])
    unique = np.unique(triangle_keys(all_uv)).view("<f4").reshape(-1, 3, 2)
    coords = atlas_triangles(unique, size)
    area = ((coords[:, 1, 0] - coords[:, 0, 0]) * (coords[:, 2, 1] - coords[:, 0, 1])
            - (coords[:, 1, 1] - coords[:, 0, 1]) * (coords[:, 2, 0] - coords[:, 0, 0]))
    coords = coords[area != 0]
    wire = Image.new("RGB", (size, size), (54, 65, 78))
    lines = ImageDraw.Draw(wire)
    with (folder / "uv_layout.svg").open("w", encoding="utf-8") as svg:
        svg.write(f'<svg xmlns="http://www.w3.org/2000/svg" width="{size}" height="{size}" '
                  f'viewBox="0 0 {size} {size}">\n<g fill="#a6b7ca" stroke="#36414e" stroke-width="0.65">\n')
        for triangle in coords:
            points = [tuple(point) for point in triangle]
            lines.polygon(points, fill=(166, 183, 202))
            svg.write('<polygon points="' + ' '.join(f'{x:.10f},{y:.10f}' for x, y in points) + '"/>\n')
        svg.write('</g>\n</svg>\n')
    for triangle in coords:
        points = [tuple(point) for point in triangle]
        lines.line([*points, points[0]], fill=(54, 65, 78))
    rgba = Image.fromarray(np.dstack((np.asarray(wire), occupied.astype(np.uint8) * 255)))
    rgba.save(folder / "uv_layout.png")
    return occupied


def read_png(path, modes):
    with Image.open(path) as image:
        if image.format != "PNG" or image.size != (ATLAS_SIZE, ATLAS_SIZE) or image.mode not in modes:
            raise ValueError(f"{path.name}: expected a {ATLAS_SIZE} square {' or '.join(modes)} PNG")
        image.load()
        return image


def baked_layers(root, examples):
    folder = root / LAYER_DIR
    record = folder / "layers.json"
    for path in (folder, record):
        if not path.exists():
            raise ValueError(f"Missing {path}. The exterior pass bake writes it.")
    liveries = json.loads(record.read_text(encoding="utf-8")).get("liveries", {})
    layers = {}
    for key, example in examples.items():
        if key not in liveries:
            raise ValueError(f"Missing livery {key} in {record}. The exterior pass bake writes it.")
        if liveries[key].get("map") != example.name:
            raise ValueError(f"{record} must list {example.name} for {key}. The exterior pass bake writes it.")
        layers[key] = [folder / f"{key}_{layer}.png" for layer in LAYERS]
        for path in layers[key]:
            if not path.is_file():
                raise ValueError(f"Missing {path}. The exterior pass bake writes it.")
    return layers


def layer_names(key):
    return [f"{key}_{index:02d}_{layer}.png" for index, layer in enumerate(LAYERS, 1)]


def write_layers(examples, layers, occupied, folder):
    destination = folder / "template/layers"
    destination.mkdir()
    errors, hashes = {}, {}
    for key, example in examples.items():
        example_copy = folder / "examples" / example.name
        shutil.copyfile(example, example_copy)
        target = read_png(example_copy, ("RGB", "RGBA"))
        if target.mode == "RGBA" and target.getchannel("A").getextrema() != (255, 255):
            raise ValueError(f"{example.name}: expected an opaque colour PNG")
        paths = [destination / name for name in layer_names(key)]
        for path, source in zip(paths, layers[key]):
            shutil.copyfile(source, path)
            hashes[path.name] = sha256(path)
        base, markings, panels = [read_png(path, (mode,)) for path, mode in zip(paths, ("RGB", "RGBA", "RGBA"))]
        painted = Image.alpha_composite(base.convert("RGBA"), markings)
        rebuilt = Image.alpha_composite(painted, panels).convert("RGB")
        difference = np.asarray(ImageChops.difference(rebuilt, target.convert("RGB")))
        error = int(difference[occupied].max(initial=0))
        if error > STACK_TOLERANCE:
            worst = occupied & (difference == error).any(axis=2)
            y, x = np.unravel_index(worst.argmax(), worst.shape)
            raise ValueError(f"{key} layer stack differs from {example.name} by {error} colour steps "
                             f"at texel (x={x}, y={y}), limit {STACK_TOLERANCE}")
        errors[key] = error
    return errors, hashes


def expected_files(examples):
    return sorted(["README.md", "LICENSE.txt", "atlas.json", f"install/{BUILDER}", "install/meta.json",
                   *(f"model/{MODEL}.{ext}" for ext in ("blend", "fbx")),
                   *(f"maps/{name}" for name in SHARED_MAPS), *(f"template/{name}" for name in TEMPLATES),
                   *(f"examples/{name}" for name in examples.values()),
                   *(f"template/layers/{name}" for key in examples for name in layer_names(key))])


def prepare_kit(root, stage, version, *, export_root=None):
    parts, examples, maps, source = kit_inputs(export_root or root)
    layers = baked_layers(root, examples)
    folder = stage / f"centurion_livery_kit_{version}"
    for name in ("examples", "install", "maps", "model", "template"):
        (folder / name).mkdir(parents=True)
    for path in maps:
        shutil.copyfile(path, folder / "maps" / path.name)
    occupied = template_maps(parts, folder / "template", ATLAS_SIZE)
    errors, hashes = write_layers(examples, layers, occupied, folder)
    source.update(version=version, skin_uv_sha256=uv_fingerprint(parts),
                  examples={key: path.name for key, path in examples.items()},
                  layer_max_error=errors, layer_sha256=hashes)
    (folder / "atlas.json").write_text(json.dumps(source, indent=2) + "\n", encoding="utf-8")
    docs = root / DOCS
    shutil.copyfile(docs / "README.md", folder / "README.md")
    for name in (BUILDER, "meta.json"):
        shutil.copyfile(docs / name, folder / "install" / name)
    (folder / "LICENSE.txt").write_bytes((docs / "LICENSE.txt").read_bytes() + (root / "LICENSE").read_bytes())

    offset = 0
    faces = []
    for part in parts.values():
        faces.append(part.faces + offset)
        offset += len(part.vertices)
    np.savez(stage / "paint_mesh.npz", vertices=np.concatenate([part.vertices for part in parts.values()]),
             faces=np.concatenate(faces), uv=np.concatenate([part.uv for part in parts.values()]),
             normals=np.concatenate([part.normals for part in parts.values()]))
    return folder


def model_image_links(example):
    return [f"../examples/{example}", *(f"../maps/{name}" for name in SHARED_MAPS[:2])]


def verify_model(folder, mesh):
    paths = model_image_links(json.loads((folder / "atlas.json").read_text())["examples"][LIVERIES[0]])
    directory = folder / "model"
    blend = (directory / f"{MODEL}.blend").read_bytes()
    if not blend.startswith(b"BLENDER") or any(("//" + path).encode() not in blend for path in paths):
        raise ValueError("Blender model is missing its relative preview links")
    fbx_path = directory / f"{MODEL}.fbx"
    fbx = fbx_path.read_bytes().replace(b"\\", b"/")
    if any(path.encode() not in fbx for path in paths) or directory.resolve().as_posix().encode() in fbx:
        raise ValueError("FBX model is missing its relative preview links or contains an absolute kit path")
    _, uv, _ = fbx_triangles(fbx_path, MODEL)
    with np.load(mesh) as expected:
        if not np.array_equal(np.sort(triangle_keys(uv)), np.sort(triangle_keys(expected["uv"]))):
            raise ValueError("paint model FBX triangles or UVs differ from the exterior export")


def write_archive(folder, output):
    source = json.loads((folder / "atlas.json").read_text(encoding="utf-8"))
    files = expected_files(source["examples"])
    for name in files:
        path = folder / name
        if name.startswith("template/layers/") and sha256(path) != source["layer_sha256"].get(path.name):
            raise ValueError(f"{path.name} differs from the verified paint layer")
    output.parent.mkdir(parents=True, exist_ok=True)
    pending = folder.parent / (output.name + ".tmp")
    try:
        with zipfile.ZipFile(pending, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for name in files:
                archive.write(folder / name, f"{folder.name}/{name}")
        with zipfile.ZipFile(pending) as archive:
            if archive.namelist() != [f"{folder.name}/{name}" for name in files] or archive.testzip() is not None:
                raise ValueError("paint kit archive failed its content check")
        pending.replace(output)
    finally:
        pending.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("prepare", "pack"))
    parser.add_argument("--stage", type=Path, required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--export-root", type=Path, default=ROOT, help="checkout containing the pinned exterior export")
    args = parser.parse_args()
    if not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", args.version):
        parser.error("--version must be a release version such as 0.2.0")
    try:
        if args.action == "prepare":
            folder = prepare_kit(ROOT, args.stage, args.version, export_root=args.export_root)
            print(f"LIVERY KIT TEMPLATES PASS: {folder}", flush=True)
        else:
            folder = args.stage / f"centurion_livery_kit_{args.version}"
            source = json.loads((folder / "atlas.json").read_text(encoding="utf-8"))
            if source["export_manifest_sha256"] != sha256(args.export_root / "art/export-manifest.json"):
                raise ValueError("the exterior export changed while the kit was building; rebuild the kit")
            for directory in ("examples", "maps"):
                for image in (folder / directory).glob("*.png"):
                    if sha256(image) != source["map_sha256"].get(image.name):
                        raise ValueError(f"{image.name} differs from the pinned export")
            verify_model(folder, args.stage / "paint_mesh.npz")
            output = ROOT / "build" / (folder.name + ".zip")
            write_archive(folder, output)
            print(f"LIVERY KIT PASS: {output} ({output.stat().st_size:,} bytes)", flush=True)
    except (OSError, ValueError) as error:
        parser.exit(1, f"LIVERY KIT FAIL: {error}\n")


if __name__ == "__main__":
    main()
