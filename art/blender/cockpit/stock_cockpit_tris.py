"""Triangle counts of the stock cockpits, by reference: reads the Blueprinter placeholder prefabs and mesh assets under
unity/Assets/Blueprinter/_donotship (YAML, never shipped) and sums, per aircraft, the triangles of the renderers its
Aircraft component lists as cockpitRenderers (drawn only in cockpit view) and of the renderers on layer 3 (the cockpit
layer: tac screen, sticks, inner glass). It reads index counts only; no mesh data is copied.

python -I art/blender/cockpit/stock_cockpit_tris.py [<_donotship folder>]"""

import re
import sys
from pathlib import Path

ROOT = Path(sys.argv[1] if len(sys.argv) > 1 else "unity/Assets/Blueprinter/_donotship")


def mesh_tris():
    """Mesh asset guid -> (name, triangles), from each asset's submesh index counts."""
    out = {}
    for meta in (ROOT / "Mesh").glob("*.asset.meta"):
        guid = re.search(r"guid: (\w+)", meta.read_text()).group(1)
        head = meta.with_suffix("").read_text(errors="ignore")[:20000]
        counts = [int(c) for c in re.findall(r"indexCount: (\d+)", head.split("m_Shapes:")[0])]
        out[guid] = (meta.name.replace("_PLACEHOLDER.asset.meta", ""), sum(counts) // 3)
    return out


def documents(text):
    parts = re.split(r"--- !u!(\d+) &(\d+)[^\n]*\n", text)
    return {parts[i + 1]: (parts[i], parts[i + 2]) for i in range(1, len(parts) - 2, 3)}


def cockpit_tris(prefab, meshes):
    docs = documents(prefab.read_text(errors="ignore"))
    go_layer, go_name, go_mesh, renderer_go = {}, {}, {}, {}
    for fid, (t, body) in docs.items():
        if t == "1":
            go_layer[fid] = int(re.search(r"m_Layer: (\d+)", body).group(1))
            go_name[fid] = re.search(r"m_Name: (.*)", body).group(1).strip()
        elif t == "33":
            g = re.search(r"m_GameObject: \{fileID: (\d+)\}", body).group(1)
            m = re.search(r"m_Mesh: \{fileID: \d+, guid: (\w+)", body)
            if m:
                go_mesh[g] = m.group(1)
        elif t in ("23", "137"):
            renderer_go[fid] = re.search(r"m_GameObject: \{fileID: (\d+)\}", body).group(1)
    listed = []
    for t, body in docs.values():
        m = re.search(r"cockpitRenderers:\n((?:  - \{fileID: \d+\}\n)*)", body)
        if t == "114" and m:
            listed = re.findall(r"fileID: (\d+)", m.group(1))
            break
    if not listed:
        return None

    def tris(go):
        return meshes.get(go_mesh.get(go), ("", 0))[1]

    cockpit_gos = {renderer_go[r] for r in listed if r in renderer_go}
    layer3 = {g for g in renderer_go.values() if go_layer.get(g) == 3}
    view = cockpit_gos | layer3
    return sum(tris(g) for g in cockpit_gos), sum(tris(g) for g in layer3), sum(tris(g) for g in view), \
        sorted((go_name.get(g, "?"), tris(g)) for g in view)


def main():
    meshes = mesh_tris()
    rows = []
    for prefab in sorted((ROOT / "GameObject").glob("*_PLACEHOLDER.prefab")):
        r = cockpit_tris(prefab, meshes)
        if r is not None and r[2] > 0:
            rows.append((prefab.name.replace("_PLACEHOLDER.prefab", ""), *r))
    print(f"{'aircraft':24} {'cockpitRenderers':>16} {'layer 3':>8} {'cockpit view':>12}")
    for name, a, b, c, parts in sorted(rows, key=lambda r: -r[3]):
        print(f"{name:24} {a:16,} {b:8,} {c:12,}   " + ", ".join(f"{n} {t:,}" for n, t in parts if t))


main()
