#!/usr/bin/env python3
"""Compare two ecoNET export directories and report parameter changes.

Covers all known endpoints: legacy (regParams, editParams, sysParams)
and RM (rmCurrentDataParams, rmParamsData, etc.).

Usage:
    python3 compare_exports.py exports/before_* exports/after_*

Options:
    --settings-only   Suppress live sensor data (regParams.curr, tilesParams, etc.)
                      and focus on editable/config changes.
"""

import json
import sys
from pathlib import Path

ALL_ENDPOINTS = [
    "regParams",
    "editParams",
    "sysParams",
    "regParamsData",
    "rmCurrentDataParams",
    "rmCurrentDataParamsEdits",
    "rmParamsData",
    "rmParamsNames",
    "rmParamsDescs",
    "rmParamsEnums",
    "rmParamsUnitsNames",
    "rmStructure",
    "rmLangs",
    "rmExistingLangs",
    "rmLocksNames",
    "rmAlarmsNames",
]

NOISY_PREFIXES = {
    "curr.",
    "currUnits.",
    "currNumbers.",
    "tilesParams",
    "schemaParams",
    "settingsVer",
    "editableParamsVer",
    "alarms",
    "signal",
    "quality",
    "wlan0",
    "eth0",
}


def load_json(path: Path) -> dict | None:
    try:
        with open(path) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def flatten(obj, prefix: str = "") -> dict[str, object]:
    """Recursively flatten a nested dict/list into dot-separated keys."""
    items: dict[str, object] = {}
    if isinstance(obj, dict):
        for k, v in obj.items():
            new_key = f"{prefix}.{k}" if prefix else k
            items.update(flatten(v, new_key))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            items.update(flatten(v, f"{prefix}[{i}]"))
    else:
        items[prefix] = obj
    return items


def is_noisy(key: str) -> bool:
    return any(key.startswith(p) for p in NOISY_PREFIXES)


def compare(before: dict, after: dict, settings_only: bool) -> list[dict]:
    bf = flatten(before)
    af = flatten(after)
    all_keys = sorted(set(bf.keys()) | set(af.keys()))
    changes = []
    for key in all_keys:
        if settings_only and is_noisy(key):
            continue
        b_val = bf.get(key)
        a_val = af.get(key)
        if b_val != a_val:
            changes.append({"key": key, "before": b_val, "after": a_val})
    return changes


def main():
    settings_only = "--settings-only" in sys.argv
    args = [a for a in sys.argv[1:] if not a.startswith("--")]

    if len(args) != 2:
        print(f"Usage: {sys.argv[0]} <before_dir> <after_dir> [--settings-only]")
        sys.exit(1)

    before_dir = Path(args[0])
    after_dir = Path(args[1])

    total_changes = 0

    for endpoint in ALL_ENDPOINTS:
        before_data = load_json(before_dir / f"{endpoint}.json")
        after_data = load_json(after_dir / f"{endpoint}.json")

        if before_data is None and after_data is None:
            continue

        if before_data is None or after_data is None:
            state = "NEW" if after_data else "REMOVED"
            print(f"\n{'=' * 60}")
            print(f"  {endpoint}: {state} (only in {'after' if after_data else 'before'})")
            print(f"{'=' * 60}")
            total_changes += 1
            continue

        changes = compare(before_data, after_data, settings_only)
        if not changes:
            continue

        total_changes += len(changes)
        print(f"\n{'=' * 60}")
        print(f"  {endpoint}: {len(changes)} change(s)")
        print(f"{'=' * 60}")

        for c in changes:
            key = c["key"]
            if c["before"] is None:
                print(f"\n  [NEW]     {key}")
                print(f"            value = {c['after']}")
            elif c["after"] is None:
                print(f"\n  [GONE]    {key}")
                print(f"            was   = {c['before']}")
            else:
                print(f"\n  [CHANGED] {key}")
                print(f"            before = {c['before']}")
                print(f"            after  = {c['after']}")

    if total_changes == 0:
        print("\nNo differences found across any endpoints.")
    else:
        print(f"\n--- Total: {total_changes} change(s) across all endpoints ---")
    print()


if __name__ == "__main__":
    main()
