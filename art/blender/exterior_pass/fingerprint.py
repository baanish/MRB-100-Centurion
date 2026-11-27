"""A stage blend's content, hashed object by object (pass_common.content_hashes), into a JSON file: Test-Repeat.ps1
compares two runs with it.
blender --background <blend> --python fingerprint.py -- <out.json>"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import pass_common as P  # noqa: E402

out = P.content_hashes()
Path(sys.argv[sys.argv.index("--") + 1]).write_text(json.dumps(out, indent=0))
print("FINGERPRINT", len(out), "objects", flush=True)
