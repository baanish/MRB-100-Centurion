"""Bump the Centurion's release version: the three version sites and the bundle name where it loads build/.

    python -I tools/bump_version.py 0.1.3 0.2.0            # list what would change; changes nothing
    python -I tools/bump_version.py 0.1.3 0.2.0 --apply    # write the changes

Run from inside the repository (or pass --repo). Lists every tracked line it would change, grouped by kind, and every
tracked line that names the old version but is left alone, grouped by the reason. Refuses a dirty tree (tracked
changes), since a release bump must be one reviewable diff on top of a commit; --allow-dirty lifts that for listing
only and is refused with --apply.

Changed:
  version-site      CenturionPlugin.Version, Centurion.csproj <Version>, modinfo.json "version". Each must match once
                    and hold the old version, or the run refuses (a second run after --apply refuses here).
  bundle-current    centurion_<old>.nobp where it loads the current build in build/: a path ending in build/
                    (content:../../build/...), a pathlib join onto 'build', or a generator's --artifacts folder
                    (build/ by default).

Listed, never changed (edit by hand):
  bundle-other      centurion_<old>.nobp outside .cache/ in any other form. It may name build/ or a kept copy, so
                    the script does not guess.
  public-doc-claim  a public doc line that states which version was tested or what a section describes. A version
                    swap would make a false claim.

Skipped, never changed:
  bundle-staged     centurion_<old>.nobp under .cache/: a kept copy of an earlier build (release-<old>, build-N),
                    whose file keeps its old name on disk. Renaming the reference breaks the scenario.
  changelog         CHANGELOG.md: past entries, and the in-progress section's history (its heading is set by hand).
  archive           docs/archive.
  testing-log       docs/TESTING.md table rows.
  decisions         docs/DECISIONS.md.
  mention           any other line naming the old version: history in comments, docs and test titles
                    ("0.1.3's CG", "the 0.1.3 keys", "release-0.1.3/dotnet").

Line endings are kept byte for byte: files are read and written as bytes, split on LF only, and only the matched
version bytes inside a changed line are replaced. Standard library only.
"""

import argparse
import re
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

VERSION = re.compile(r"[0-9]+\.[0-9]+\.[0-9]+")

# (path, pattern with the version as group 'v'); each must match exactly once and hold the old version.
VERSION_SITES = (
    ("src/Centurion/CenturionPlugin.cs", rb'public const string Version = "(?P<v>[0-9.]+)";'),
    ("src/Centurion/Centurion.csproj", rb"<Version>(?P<v>[0-9.]+)</Version>"),
    ("unity/Assets/Blueprinter/Mods/centurion/modinfo.json", rb'"version": "(?P<v>[0-9.]+)"'),
)

# Files the public mirror carries as player or release docs (tools/Sync-PublicRepo.ps1).
PUBLIC_DOCS = re.compile(r"^(README\.md|BUILD\.md|docs/RELEASE\.md|docs/player/.*|docs/livery-kit/.*)$")
CLAIM = r"(?i)\bversion {v}\b(?! ?'s)|\bdescribes? {v}\b"

# A path segment that ends at one of these bytes starts a new token.
TOKEN_BREAK = re.compile(rb"[\s\"'(]")
# The bundle's path token ends in a build/ folder: content:../../build/, build/.
BUILD_PATH = re.compile(rb"(?:^|[/:])build/$")
# The text before the bundle's quoted name joins it onto build/: build / 'build' / '...', artifacts / '...'.
BUILD_JOIN = re.compile(rb"(?:'build'|\bartifacts) / '$")


def git(repo, *args):
    result = subprocess.run(["git", "-C", str(repo), *args], capture_output=True)
    if result.returncode not in (0, 1):  # git grep exits 1 when nothing matches
        sys.exit(f"BUMP FAIL: git {' '.join(args)} exited {result.returncode}: {result.stderr.decode(errors='replace')}")
    return result.stdout


def file_kind(path):
    if path.startswith("docs/archive/"):
        return "archive"
    if path == "CHANGELOG.md":
        return "changelog"
    if path == "docs/DECISIONS.md":
        return "decisions"
    return None


def classify(path, line, old, new):
    """Return (kind, new_line or None) for one line that names the old version."""
    kind = file_kind(path)
    if kind:
        return kind, None
    if path == "docs/TESTING.md" and line.lstrip().startswith(b"|"):
        return "testing-log", None
    for site, pattern in VERSION_SITES:
        if path == site:
            match = re.search(pattern, line)
            if match and match.group("v") == old.encode():
                start, end = match.span("v")
                return "version-site", line[:start] + new.encode() + line[end:]
    bundle_old = f"centurion_{old}.nobp".encode()
    bundle_new = f"centurion_{new}.nobp".encode()
    if bundle_old in line:
        out, pos, kinds = b"", 0, set()
        for match in re.finditer(re.escape(bundle_old), line):
            token_start = 0
            for brk in TOKEN_BREAK.finditer(line, 0, match.start()):
                token_start = brk.end()
            token = line[token_start:match.start()]
            if b".cache" in token:
                kinds.add("bundle-staged")
            elif BUILD_PATH.search(token) or BUILD_JOIN.search(line, 0, match.start()):
                kinds.add("bundle-current")
                out += line[pos:match.start()] + bundle_new
                pos = match.end()
            else:
                kinds.add("bundle-other")
        if len(kinds) > 1:
            return "bundle-other", None  # a line that names two kinds of bundle is edited by hand
        kind = kinds.pop()
        return kind, (out + line[pos:] if kind == "bundle-current" else None)
    if PUBLIC_DOCS.match(path) and re.search(CLAIM.format(v=re.escape(old)), line.decode("utf-8", "replace")):
        return "public-doc-claim", None
    return "mention", None


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("old")
    parser.add_argument("new")
    parser.add_argument("--apply", action="store_true", help="write the changes (default: list only)")
    parser.add_argument("--allow-dirty", action="store_true", help="list on a dirty tree; refused with --apply")
    parser.add_argument("--repo", type=Path, help="repository root (default: the one containing the working directory)")
    parser.add_argument("--all", action="store_true", help="also list every skipped line, not only its file and count")
    args = parser.parse_args()
    sys.stdout.reconfigure(errors="replace")  # a redirected Windows console cannot print every quoted line

    for value in (args.old, args.new):
        if not VERSION.fullmatch(value):
            parser.error(f"{value} is not <major>.<minor>.<patch>")
    if args.old == args.new:
        parser.error("old and new versions are the same")
    if args.apply and args.allow_dirty:
        parser.error("--allow-dirty is for listing only")

    repo = args.repo or Path(git(Path.cwd(), "rev-parse", "--show-toplevel").decode().strip())
    repo = repo.resolve()
    dirty = git(repo, "status", "--porcelain", "--untracked-files=no").decode().splitlines()
    if dirty:
        if not args.allow_dirty:
            sys.exit(f"BUMP FAIL: the tree has tracked changes ({len(dirty)} paths: {'; '.join(dirty[:5])}); "
                     "commit or stash them first")
        print(f"WARN: dirty tree, listing only ({len(dirty)} paths: {'; '.join(dirty[:5])})")

    # Text files only (-I): binary assets are never edited.
    names = [n for n in git(repo, "grep", "-I", "-l", "-z", "-F", "-e", args.old).decode().split("\0") if n]
    plans = {}  # path -> {line index: new bytes}
    groups = defaultdict(list)  # kind -> [(path, line number, text)]
    for name in sorted(names):
        data = (repo / name).read_bytes()
        lines = data.split(b"\n")
        for index, line in enumerate(lines):
            if args.old.encode() not in line:
                continue
            # A version inside a longer one (10.1.3, 0.1.30) is not this version.
            if not re.search(rb"(?<![0-9.])" + re.escape(args.old.encode()) + rb"(?![0-9])", line):
                continue
            kind, changed = classify(name, line, args.old, args.new)
            text = line.rstrip(b"\r").decode("utf-8", "replace").strip()
            groups[kind].append((name, index + 1, text))
            if changed is not None:
                plans.setdefault(name, {})[index] = changed

    # Every version site must be found once with the old version.
    for site, pattern in VERSION_SITES:
        path = repo / site
        found = re.findall(pattern, path.read_bytes()) if path.exists() else []
        if len(found) != 1 or found[0] != args.old.encode():
            sys.exit(f"BUMP FAIL: {site} holds {[f.decode() for f in found]}, expected exactly one {args.old}")

    changing = ("version-site", "bundle-current")
    by_hand = ("bundle-other", "public-doc-claim")
    skipped = ("bundle-staged", "changelog", "archive", "testing-log", "decisions", "mention")
    for kind in changing + by_hand:
        rows = groups.get(kind, [])
        files = sorted({p for p, _, _ in rows})
        verb = "change" if kind in changing else "listed, not changed (edit by hand)"
        print(f"\n== {kind}: {len(rows)} lines in {len(files)} files ({verb})")
        if kind == "bundle-current":
            by_file = defaultdict(list)
            for path, number, _ in rows:
                by_file[path].append(str(number))
            for path in files:
                print(f"  {path}: {', '.join(by_file[path])}")
        else:
            for path, number, text in rows:
                print(f"  {path}:{number}: {text[:160]}")
    for kind in skipped:
        rows = groups.get(kind, [])
        files = defaultdict(int)
        for path, _, _ in rows:
            files[path] += 1
        print(f"\n== skipped {kind}: {len(rows)} lines in {len(files)} files")
        if args.all:
            for path, number, text in rows:
                print(f"  {path}:{number}: {text[:160]}")
        elif kind == "bundle-staged":
            folders = defaultdict(int)
            for path, number, text in rows:
                m = re.search(r"\.cache/\S*?(?=/centurion_)", text)
                folders[m.group(0) if m else "?"] += 1
            for folder, count in sorted(folders.items(), key=lambda kv: -kv[1]):
                print(f"  {count:4d}  {folder}/")
        else:
            for path, count in sorted(files.items()):
                print(f"  {count:4d}  {path}")

    total = sum(len(v) for v in plans.values())
    print(f"\nSUMMARY: {total} lines in {len(plans)} files to change; "
          f"{sum(len(groups.get(k, [])) for k in by_hand)} lines to edit by hand; "
          f"{sum(len(groups.get(k, [])) for k in skipped)} lines skipped")
    if not args.apply:
        print("BUMP LIST: nothing written (pass --apply to write)")
        return

    originals = {}
    for name, changes in sorted(plans.items()):
        path = repo / name
        originals[name] = path.read_bytes()
        lines = originals[name].split(b"\n")
        for index, line in changes.items():
            lines[index] = line
        path.write_bytes(b"\n".join(lines))
    # Read back: each planned line holds its planned bytes (classify splices only the version, so the line ending
    # stays), and every other line is unchanged.
    for name, changes in sorted(plans.items()):
        after = (repo / name).read_bytes().split(b"\n")
        before = originals[name].split(b"\n")
        if len(after) != len(before):
            sys.exit(f"BUMP FAIL: {name} changed its line count")
        for index, (a, b) in enumerate(zip(after, before)):
            if a != changes.get(index, b):
                sys.exit(f"BUMP FAIL: {name}:{index + 1} differs from the plan")
    print(f"BUMP PASS: {total} lines in {len(plans)} files now name {args.new}; review with git diff --stat")


if __name__ == "__main__":
    main()
