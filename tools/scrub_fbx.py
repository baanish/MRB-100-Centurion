"""Blank Blender's native scene and absolute texture paths without changing mesh data.

python tools/scrub_fbx.py [ROOT ...] [--check]
Defaults to the three export folders and Unity's Centurion folder.
"""

import argparse
import hashlib
import json
import re
import struct
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
ROOTS = ("art/export", "art/export_awacs", "art/export_cockpit",
         "unity/Assets/Blueprinter/Mods/centurion")
NATIVE_FILE = b"Original|ApplicationNativeFile"
ABSOLUTE_PATH = re.compile(rb"^(?:[A-Za-z]:[\\/]|/|\\\\)")


def read_tree(data):
    if data[:23] != b"Kaydara FBX Binary  \x00\x1a\x00":
        raise ValueError("expected binary FBX")
    wide = struct.unpack_from("<I", data, 23)[0] >= 7500
    header, size = ("<QQQB", 25) if wide else ("<IIIB", 13)
    spans = []

    def node(start):
        end, count, length, name_size = struct.unpack_from(header, data, start)
        if end == 0:
            if data[start:start + size] != bytes(size):
                raise ValueError("invalid FBX terminator")
            return None, start + size
        if end <= start or end > len(data):
            raise ValueError("invalid FBX node offset")
        pos = start + size
        name = data[pos:pos + name_size]
        pos += name_size
        prop_end = pos + length
        props, strings = [], []
        for _ in range(count):
            begin = pos
            kind = chr(data[pos])
            pos += 1
            if kind in "YCFDILB":
                pos += {"Y": 2, "C": 1, "F": 4, "D": 8, "I": 4, "L": 8, "B": 1}[kind]
            elif kind in "SR":
                n = struct.unpack_from("<I", data, pos)[0]
                pos += 4
                if kind == "S":
                    strings.append((pos, pos + n))
                pos += n
            elif kind in "fdilbc":
                _, _, n = struct.unpack_from("<III", data, pos)
                pos += 12 + n
            else:
                raise ValueError(f"unknown FBX property {kind!r}")
            props.append(data[begin:pos])
        if pos != prop_end:
            raise ValueError("invalid FBX property length")
        native = name == b"P" and strings and data[slice(*strings[0])] == NATIVE_FILE
        texture = name.lower() in (b"filename", b"relativefilename") or (
            name == b"P" and strings and data[slice(*strings[0])] == b"Path")
        value = data[slice(*strings[-1])] if strings else b""
        if native or (texture and (ABSOLUTE_PATH.match(value) or not value.strip())):
            if len(strings) != count:
                raise ValueError("unexpected FBX path property")
            spans.append(strings[-1])
            props[-1] = b"blanked path metadata"
        children = []
        while pos < end:
            child, pos = node(pos)
            if child is None:
                break
            children.append(child)
        if pos != end:
            raise ValueError("invalid FBX child offset")
        return (name, tuple(props), tuple(children)), end

    pos, tree = 27, []
    while True:
        item, pos = node(pos)
        if item is None:
            break
        tree.append(item)
    return tree, spans


def scrub_file(path, check=False):
    data = path.read_bytes()
    before, spans = read_tree(data)
    if not spans:
        raise ValueError(f"{path}: missing Blender path metadata")
    result = bytearray(data)
    changed = 0
    for start, end in spans:
        # Equal-length whitespace blanks the string while preserving every other byte,
        # including absolute node offsets, compressed arrays and the FBX footer.
        blank = b" " * (end - start)
        changed += data[start:end] != blank
        result[start:end] = blank
    after, after_spans = read_tree(result)
    if before != after or spans != after_spans:
        raise ValueError(f"{path}: FBX node tree changed outside the path properties")
    if changed and not check:
        path.write_bytes(result)
    return changed


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("roots", nargs="*", type=Path)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    files = sorted({p for root in (args.roots or [REPO / r for r in ROOTS])
                    for p in ([root] if root.is_file() else root.rglob("*.fbx"))})
    if not files:
        parser.error("no FBX files found")
    changed = sum(bool(scrub_file(p, args.check)) for p in files)
    if not args.check:
        for directory in sorted({p.parent for p in files}):
            manifest = directory / "blockout.json"
            if not manifest.exists():
                continue
            raw = manifest.read_bytes().decode("utf-8")
            values = json.loads(raw)
            # Keep the exporter's per-part integrity checks valid after changing FBX metadata.
            for part in values["parts"].values():
                if part.get("fbx"):
                    digest = hashlib.sha256((directory / part["fbx"]).read_bytes()).hexdigest()
                    raw = raw.replace(part["sha256"], digest)
            manifest.write_bytes(raw.encode("utf-8"))
    print(f"FBX {'CHECK' if args.check else 'SCRUB'}: {len(files)} files, {changed} "
          f"{'need scrubbing' if args.check else 'scrubbed'}, node trees verified")
    if args.check and changed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
