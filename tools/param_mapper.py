#!/usr/bin/env python3
"""Parameter Mapper: Diff two ecoNET JSON snapshots to identify changed parameters.

Usage:
    python param_mapper.py <before.json> <after.json> [--output param_map.json]

Takes two JSON files captured from the ecoNET API (editParams, regParams, or
sysParams) before and after a settings change in the vendor iOS app.  Reports
which parameters changed, their old/new values, and metadata.

Over time, running this repeatedly builds a mapping file (param_map.json) that
maps API parameter names/indices to human-readable descriptions.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


def flatten(obj: Any, prefix: str = "") -> dict[str, Any]:
    """Recursively flatten a nested dict into dot-separated keys."""
    items: dict[str, Any] = {}
    if isinstance(obj, dict):
        for k, v in obj.items():
            new_key = f"{prefix}.{k}" if prefix else k
            items.update(flatten(v, new_key))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            new_key = f"{prefix}[{i}]"
            items.update(flatten(v, new_key))
    else:
        items[prefix] = obj
    return items


def diff_snapshots(
    before: dict[str, Any], after: dict[str, Any]
) -> list[dict[str, Any]]:
    """Compare two flattened snapshots and return a list of changes."""
    changes: list[dict[str, Any]] = []
    all_keys = set(before.keys()) | set(after.keys())

    for key in sorted(all_keys):
        old_val = before.get(key)
        new_val = after.get(key)

        if old_val != new_val:
            changes.append(
                {
                    "key": key,
                    "old_value": old_val,
                    "new_value": new_val,
                    "added": key not in before,
                    "removed": key not in after,
                }
            )
    return changes


def print_report(changes: list[dict[str, Any]]) -> None:
    """Print a human-readable diff report."""
    if not changes:
        print("No differences found between the two snapshots.")
        return

    print(f"\n{'='*70}")
    print(f"  Parameter Changes: {len(changes)} difference(s) found")
    print(f"{'='*70}\n")

    for change in changes:
        key = change["key"]
        if change["added"]:
            print(f"  [ADDED]   {key}")
            print(f"            new = {change['new_value']}")
        elif change["removed"]:
            print(f"  [REMOVED] {key}")
            print(f"            old = {change['old_value']}")
        else:
            print(f"  [CHANGED] {key}")
            print(f"            old = {change['old_value']}")
            print(f"            new = {change['new_value']}")
        print()


def update_param_map(
    map_file: Path,
    changes: list[dict[str, Any]],
    description: str | None = None,
) -> None:
    """Append discovered parameter mappings to a cumulative JSON file."""
    existing: dict[str, Any] = {}
    if map_file.exists():
        existing = json.loads(map_file.read_text())

    for change in changes:
        key = change["key"]
        if key not in existing:
            existing[key] = {
                "first_seen_change": {
                    "old": change["old_value"],
                    "new": change["new_value"],
                },
                "description": description or "",
                "observations": 1,
            }
        else:
            existing[key]["observations"] = existing[key].get("observations", 0) + 1

    map_file.write_text(json.dumps(existing, indent=2, default=str))
    print(f"Updated parameter map: {map_file} ({len(existing)} parameters tracked)")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Diff two ecoNET API JSON snapshots to find changed parameters."
    )
    parser.add_argument("before", help="Path to the 'before' JSON snapshot")
    parser.add_argument("after", help="Path to the 'after' JSON snapshot")
    parser.add_argument(
        "--output", "-o",
        default="param_map.json",
        help="Path to the cumulative parameter map file (default: param_map.json)",
    )
    parser.add_argument(
        "--description", "-d",
        default=None,
        help="Description of what setting was changed (e.g. 'Changed DHW temp from 50 to 55')",
    )
    args = parser.parse_args()

    before_path = Path(args.before)
    after_path = Path(args.after)

    if not before_path.exists():
        print(f"Error: {before_path} not found", file=sys.stderr)
        sys.exit(1)
    if not after_path.exists():
        print(f"Error: {after_path} not found", file=sys.stderr)
        sys.exit(1)

    before = json.loads(before_path.read_text())
    after = json.loads(after_path.read_text())

    before_flat = flatten(before)
    after_flat = flatten(after)

    changes = diff_snapshots(before_flat, after_flat)
    print_report(changes)

    if changes:
        map_file = Path(args.output)
        update_param_map(map_file, changes, args.description)


if __name__ == "__main__":
    main()
