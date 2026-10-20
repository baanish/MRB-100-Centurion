"""The blockout builders configured as step 6.1, without building a scene."""

import sys
from pathlib import Path

BUILD = Path(__file__).resolve().parents[1] / "build_centurion.py"


def load_blockout():
    sys.path.insert(0, str(BUILD.parent))
    import build_centurion as mod
    mod.configure_step61()
    return mod
