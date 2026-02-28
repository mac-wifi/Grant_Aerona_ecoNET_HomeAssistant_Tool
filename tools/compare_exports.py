#!/usr/bin/env python3
"""Compare two ecoNET export directories and report parameter changes.

Usage: python3 compare_exports.py exports/before_* exports/after_*
"""

import json
import sys
from pathlib import Path


def load_json(path: Path) -> dict:
    with open(path) as f:
        return json.load(f)


def compare_flat(before: dict, after: dict, prefix: str = "") -> list[dict]:
    """Recursively compare two dicts, returning a list of changes."""
    changes = []
    all_keys = sorted(set(list(before.keys()) + list(after.keys())))

    for key in all_keys:
        full_key = f"{prefix}.{key}" if prefix else key
        b_val = before.get(key)
        a_val = after.get(key)

        if b_val is None and a_val is not None:
            changes.append({"key": full_key, "before": None, "after": a_val})
        elif a_val is None and b_val is not None:
            changes.append({"key": full_key, "before": b_val, "after": None})
        elif isinstance(b_val, dict) and isinstance(a_val, dict):
            changes.extend(compare_flat(b_val, a_val, full_key))
        elif b_val != a_val:
            changes.append({"key": full_key, "before": b_val, "after": a_val})

    return changes


def main():
    if len(sys.argv) != 3:
        print(f"Usage: {sys.argv[0]} <before_dir> <after_dir>")
        sys.exit(1)

    before_dir = Path(sys.argv[1])
    after_dir = Path(sys.argv[2])

    for endpoint in ["regParams", "editParams", "sysParams"]:
        before_file = before_dir / f"{endpoint}.json"
        after_file = after_dir / f"{endpoint}.json"

        if not before_file.exists() or not after_file.exists():
            print(f"\n--- {endpoint}: SKIPPED (missing file) ---")
            continue

        before_data = load_json(before_file)
        after_data = load_json(after_file)
        changes = compare_flat(before_data, after_data)

        print(f"\n{'=' * 60}")
        print(f"  {endpoint}: {len(changes)} change(s)")
        print(f"{'=' * 60}")

        if not changes:
            print("  No changes detected.")
            continue

        for c in changes:
            print(f"\n  Key:    {c['key']}")
            print(f"  Before: {c['before']}")
            print(f"  After:  {c['after']}")

    print()


if __name__ == "__main__":
    main()
