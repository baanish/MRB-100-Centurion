"""The blockout script as a library, configured as step 6.1: its SPEC numbers and shape functions (fus_profile,
fus_point, chine, st, ...) without running its build. build_centurion.py ends in a bare main() call, so the source is
executed with that last line cut off, then configure_step61() rebinds the step 5 numbers and builders to step 6.1, as
its main() does for --step 6.1."""

import types
from pathlib import Path

BUILD = Path(__file__).resolve().parents[1] / "build_centurion.py"


def load_blockout():
    src = BUILD.read_text(encoding="utf-8")
    body, tail = src.rstrip().rsplit("\n", 1)
    if tail.strip() != "main()":
        raise SystemExit(f"{BUILD.name} no longer ends in main(); update m4/blockout.py")
    mod = types.ModuleType("build_centurion")
    mod.__file__ = str(BUILD)
    exec(compile(body, str(BUILD), "exec"), mod.__dict__)
    mod.configure_step61()
    return mod
