"""Read-only local release preflight; never creates tags or publishes a release."""

import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

MANIFEST = "custom_components/econet_grant/manifest.json"


def git(root, *args):
    """Read Git state without invoking a shell."""
    return subprocess.check_output(["git", "-C", str(root), *args], stderr=subprocess.PIPE)


def validate(root, commit, tag, version):
    """Bind actual working bytes to the explicit commit, not cached file stats."""
    if Path(git(root, "rev-parse", "--show-toplevel").decode().strip()).resolve() != root:
        raise ValueError("Run from the repository root")
    head = git(root, "rev-parse", "HEAD").decode().strip()
    if commit != head:
        raise ValueError("--commit must be the full current HEAD commit ID")
    if git(root, "status", "--porcelain", "--untracked-files=all"):
        raise ValueError("Working tree/index is dirty (including untracked files)")
    algorithm = git(root, "rev-parse", "--show-object-format").decode().strip()
    for record in git(root, "ls-tree", "-rz", "--full-tree", "HEAD").split(b"\0"):
        if not record:
            continue
        metadata, name = record.split(b"\t", 1)
        mode, kind, expected = metadata.split()
        path = root / name.decode("utf-8")
        if kind != b"blob" or mode not in (b"100644", b"100755") or path.is_symlink():
            raise ValueError(f"Unsupported tracked file type: {name!r}")
        data = path.read_bytes()
        actual = hashlib.new(algorithm, b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()
        if actual != expected.decode():
            raise ValueError(f"Actual tracked bytes differ from HEAD: {name!r}")
    raw = (root / MANIFEST).read_bytes()
    if raw != git(root, "show", f"HEAD:{MANIFEST}"):
        raise ValueError("Actual manifest bytes differ from the intended commit")
    manifest = json.loads(raw)
    if not re.fullmatch(r"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)", version):
        raise ValueError("Release version must be MAJOR.MINOR.PATCH (no prefix or leading zeros)")
    if not isinstance(manifest, dict) or manifest.get("version") != version or tag != f"v{version}":
        raise ValueError("Manifest, proposed tag and release version must agree exactly")
    return hashlib.sha256(raw).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--commit", required=True, help="Full intended HEAD commit ID")
    parser.add_argument("--tag", required=True, help="Proposed vMAJOR.MINOR.PATCH tag")
    parser.add_argument("--release-version", required=True, help="Proposed MAJOR.MINOR.PATCH release")
    args = parser.parse_args()
    root = Path.cwd().resolve()
    try:
        digest = validate(root, args.commit, args.tag, args.release_version)
        print(f"Testing commit={args.commit} with {sys.executable} -m pytest -q", flush=True)
        result = subprocess.run([sys.executable, "-m", "pytest", "-q"], cwd=root, check=False)
        if result.returncode:
            raise ValueError(f"Offline suite failed (exit {result.returncode}); no release approval")
        validate(root, args.commit, args.tag, args.release_version)
    except (OSError, ValueError, subprocess.CalledProcessError) as err:
        print(f"FAIL: {err}", file=sys.stderr)
        return 1

    print(f"PASS commit={args.commit} tag={args.tag} release={args.release_version} manifest_sha256={digest}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
