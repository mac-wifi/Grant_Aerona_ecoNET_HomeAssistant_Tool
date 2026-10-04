#!/usr/bin/env python3
"""Compare complete ecoNET export snapshots offline (Python 3.10+)."""

from datetime import datetime
import json
from pathlib import Path
import sys

if __package__:
    from .export_econet import MAX_BYTES, SafeParser, read_json, sanitise, validate_endpoints
else:
    from export_econet import MAX_BYTES, SafeParser, read_json, sanitise, validate_endpoints


def load_snapshot(path):
    """Load only complete schema-v1 snapshots; never treat failures as empty."""
    try:
        with Path(path).open("rb") as source:
            raw = source.read(3 * MAX_BYTES + 1)
        if len(raw) > 3 * MAX_BYTES:
            raise ValueError("Snapshot too large")
        snapshot = read_json(raw)
        if (not isinstance(snapshot, dict)
                or set(snapshot) != {"schema_version", "captured_at", "endpoints"}
                or type(snapshot["schema_version"]) is not int
                or snapshot["schema_version"] != 1):
            raise ValueError("Unsupported snapshot")
        stamp = datetime.fromisoformat(snapshot["captured_at"])
        if stamp.utcoffset() is None:
            raise ValueError("Timestamp must include timezone")
        validate_endpoints(snapshot["endpoints"])
        return snapshot
    except (OSError, ValueError, TypeError, RecursionError):
        raise ValueError("Invalid or unreadable snapshot; comparison aborted.") from None


def flatten(endpoints):
    """Index values by endpoint, API name/index or a JSON Pointer path."""
    rows = {}

    def walk(endpoint, value, path):
        if isinstance(value, dict) and value:
            for key, child in value.items():
                escaped = key.replace("~", "~0").replace("/", "~1")
                walk(endpoint, child, f"{path}/{escaped}")
        else:
            # Arrays are compared as whole values, not unstable positional IDs.
            rows[(endpoint, path, None)] = value

    for endpoint, payload in endpoints.items():
        if endpoint != "editParams":
            walk(endpoint, payload, "")
            continue
        for key, value in payload.items():
            if key != "data":
                walk(endpoint, value, "/" + key.replace("~", "~0").replace("/", "~1"))
        for index, record in payload["data"].items():
            rows[(endpoint, record["name"], index)] = record["value"]
            for key, value in record.items():
                if key not in {"name", "value"}:
                    walk(endpoint, value, f"/data/{index}/" + key.replace("~", "~0").replace("/", "~1"))
    return rows


def compare(before, after):
    """Return only differences; change kind distinguishes absent from null."""
    validate_endpoints(before["endpoints"])
    validate_endpoints(after["endpoints"])
    # Collect sensitive values across BOTH captures, including cross-field echoes.
    cleaned = sanitise([before["endpoints"], after["endpoints"]])
    old, new = (flatten(endpoints) for endpoints in cleaned)
    differences = []
    for key in sorted(old.keys() | new.keys(), key=lambda key: (key[0], key[1], key[2] or "")):
        if key not in old:
            change = "added"
        elif key not in new:
            change = "removed"
        elif old[key] == new[key] and type(old[key]) is type(new[key]):
            continue
        else:
            change = "changed"
        endpoint, name, index = key
        differences.append({"endpoint": endpoint, "name": name, "index": index,
                            "change": change, "old": old.get(key), "new": new.get(key)})
    return differences


def main(argv=None):
    parser = SafeParser(description="Offline comparison of two complete ecoNET snapshots.", allow_abbrev=False)
    parser.add_argument("before", type=Path)
    parser.add_argument("after", type=Path)
    args = parser.parse_args(argv)
    try:
        rows = compare(load_snapshot(args.before), load_snapshot(args.after))
        output = json.dumps(rows, indent=2, allow_nan=False)
    except (OSError, ValueError, TypeError, RecursionError):
        print("Invalid or unreadable snapshot; comparison aborted.", file=sys.stderr)
        return 1
    print("Review comparison for private data before sharing; never commit real outputs.", file=sys.stderr)
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
