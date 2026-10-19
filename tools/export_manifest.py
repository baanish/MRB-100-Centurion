"""Pin every generated export consumed by Unity. Run with --write after an intentional export."""

import argparse
import hashlib
import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
MANIFEST = "art/export-manifest.json"


def export_hashes(repo):
    files = sorted(p for root in (repo / "art").glob("export*") if root.is_dir()
                   for p in root.rglob("*") if p.is_file())
    if not files:
        raise ValueError("no exports found")
    return {p.relative_to(repo).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in files}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=REPO)
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()
    actual = export_hashes(args.repo)
    path = args.repo / MANIFEST
    if args.write:
        path.write_text(json.dumps(actual, indent=2) + "\n", encoding="utf-8")
        print(f"EXPORT MANIFEST: pinned {len(actual)} files")
        return
    expected = json.loads(path.read_text(encoding="utf-8"))
    differences = [p for p in sorted(actual.keys() | expected.keys()) if actual.get(p) != expected.get(p)]
    if differences:
        for p in differences:
            print(f"  export differs: {p}")
        raise SystemExit(f"EXPORT FAIL: {len(differences)} files differ; regenerate intentionally and run tools/export_manifest.py --write")
    print(f"EXPORT PASS: {len(actual)} files match {MANIFEST}")


if __name__ == "__main__":
    main()
