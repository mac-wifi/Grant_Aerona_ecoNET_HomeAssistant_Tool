#!/usr/bin/env python3
"""Read-only ecoNET snapshots, independent of Home Assistant (Python 3.10+)."""

from datetime import datetime, timezone
import argparse
import base64
import getpass
from http.client import HTTPException
import json
import os
from pathlib import Path
import re
import tempfile
import time
import sys
import warnings
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

ENDPOINTS = ("regParams", "editParams", "sysParams")
REDACTED = "[REDACTED]"
MAX_BYTES = 8 * 1024 * 1024


class SafeParser(argparse.ArgumentParser):
    """Do not echo possibly secret argument values in usage errors."""

    def error(self, message):
        self.print_usage(sys.stderr)
        self.exit(2, "Invalid arguments; see --help (passwords must not be command-line arguments).\n")


class NoRedirect(HTTPRedirectHandler):
    """Never forward credentials or follow an unexpected controller endpoint."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def read_json(raw):
    """Reject ambiguous duplicate keys and non-JSON numeric constants."""
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("Duplicate JSON key")
            result[key] = value
        return result

    def invalid_constant(value):
        raise ValueError("Invalid JSON constant")

    return json.loads(raw, object_pairs_hook=pairs, parse_constant=invalid_constant)


def validate_endpoints(endpoints):
    """Fail closed on missing endpoints, error envelopes or unsupported shapes."""
    if not isinstance(endpoints, dict) or set(endpoints) != set(ENDPOINTS):
        raise ValueError("Incomplete endpoints")
    for data in endpoints.values():
        if not isinstance(data, dict) or not data or {"error", "errors", "result"} & data.keys():
            raise ValueError("Invalid endpoint")
    if not isinstance(endpoints["regParams"].get("curr"), dict) or not endpoints["regParams"]["curr"]:
        raise ValueError("Invalid readings")
    editable = endpoints["editParams"].get("data")
    if not isinstance(editable, dict) or not editable:
        raise ValueError("Invalid settings")
    for index, record in editable.items():
        if (not index.isdecimal() or not isinstance(record, dict)
                or not isinstance(record.get("name"), str) or not record["name"]
                or "value" not in record):
            raise ValueError("Invalid parameter")
    system = endpoints["sysParams"]
    if not isinstance(system.get("remoteMenu"), bool) or not isinstance(system.get("softVer"), str):
        raise ValueError("Invalid system information")
    json.dumps(endpoints, allow_nan=False)


def sensitive(name):
    """Conservative field-name heuristic, not a guarantee of anonymisation."""
    name = re.sub(r"[^a-z0-9]", "", name.lower())
    return name in {"ip", "ipv4", "ipv6", "sn", "host", "mac", "user", "login", "pwd"} or any(part in name for part in (
        "password", "passwd", "secret", "token", "auth", "credential", "username",
        "uid", "serial", "hostname", "hostaddress", "ipaddress", "macaddress",
        "ssid", "network", "wifi", "gateway", "subnet", "dns", "controllerid",
        "deviceid", "email", "location", "latitude", "longitude",
    ))


def sanitise(data, secrets=()):
    """Redact known values everywhere, sensitive fields, and address-like text."""
    tokens = {str(value) for value in secrets if value and value != REDACTED}

    def collect(value, private=False):
        if isinstance(value, dict):
            named_private = sensitive(str(value.get("name", "")))
            for key, child in value.items():
                collect(child, private or sensitive(key) or (named_private and key != "name"))
        elif isinstance(value, list):
            for child in value:
                collect(child, private)
        elif private and isinstance(value, str) and value and value != REDACTED:
            tokens.add(value)

    collect(data)
    # RFC documentation addresses and synthetic hosts are used in tests only.
    address = re.compile(
        r"https?://[^\s\"<>]+|\b(?:\d{1,3}\.){3}\d{1,3}\b|"
        r"\b(?:[0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}\b|"
        r"(?<!\w)[0-9a-fA-F]*:[0-9a-fA-F:]+(?:%[\w-]+)?|"
        r"\b(?:[a-zA-Z0-9-]+\.)+[a-zA-Z][a-zA-Z0-9-]*\b"
    )

    def text(value):
        for token in sorted(tokens, key=len, reverse=True):
            value = value.replace(token, REDACTED)
        return address.sub(REDACTED, value)

    def clean(value):
        if isinstance(value, dict):
            result = {}
            named_private = sensitive(str(value.get("name", "")))
            for key, child in value.items():
                clean_key = text(key)
                if clean_key in result:
                    raise ValueError("Redacted key collision")
                result[clean_key] = (REDACTED if sensitive(key) or (named_private and key != "name")
                                     else clean(child))
            return result
        if isinstance(value, list):
            return [clean(child) for child in value]
        return text(value) if isinstance(value, str) else value

    return clean(data)


def validate_origin(origin):
    """Require an explicit scheme and host, with no userinfo/path/query."""
    parsed = urlsplit(origin)
    if (parsed.scheme not in {"http", "https"} or not parsed.hostname
            or parsed.username is not None or parsed.password is not None
            or parsed.path not in {"", "/"} or parsed.query or parsed.fragment
            or any(char.isspace() or ord(char) < 32 for char in origin)):
        raise ValueError("Use an explicit http(s) origin without credentials, path or query")
    parsed.port  # Reject malformed ports before any request.
    return origin.rstrip("/")


def capture(origin, username, password, output_dir):
    """Capture all supported read endpoints into a new timestamped snapshot."""
    origin = validate_origin(origin)
    if not username or not password or ":" in username:
        raise ValueError("Nonempty local credentials required; username cannot contain a colon")
    auth = "Basic " + base64.b64encode(f"{username}:{password}".encode()).decode("ascii")
    opener = build_opener(ProxyHandler({}), NoRedirect())
    endpoints = {}
    try:
        for position, endpoint in enumerate(ENDPOINTS):
            if position:
                time.sleep(1)
            request = Request(f"{origin}/econet/{endpoint}", headers={"Authorization": auth}, method="GET")
            with opener.open(request, timeout=15) as response:
                if response.status != 200:
                    raise ValueError("Unexpected HTTP status")
                raw = response.read(MAX_BYTES + 1)
                if len(raw) > MAX_BYTES:
                    raise ValueError("Response too large")
                endpoints[endpoint] = read_json(raw)
        validate_endpoints(endpoints)
        endpoints = sanitise(endpoints, (username, password, auth, auth[6:], urlsplit(origin).hostname))
        validate_endpoints(endpoints)
    except (OSError, HTTPException, ValueError, TypeError, RecursionError):
        raise ValueError("Capture failed; no snapshot saved.") from None
    now = datetime.now(timezone.utc)
    snapshot = {"schema_version": 1, "captured_at": now.isoformat(), "endpoints": endpoints}
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / f"econet-{now.strftime('%Y%m%dT%H%M%S.%fZ')}.json"
    # Write privately, then atomically publish without overwriting any capture.
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=output_dir,
                                         prefix=".econet-", suffix=".tmp", delete=False) as output:
            temporary = Path(output.name)
            json.dump(snapshot, output, indent=2, allow_nan=False)
            output.write("\n")
            output.flush()
            os.fsync(output.fileno())
        os.link(temporary, path)
    except (OSError, ValueError):
        raise ValueError("Capture failed; no snapshot saved.") from None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return path


def main(argv=None):
    parser = SafeParser(description="Read-only, best-effort sanitised ecoNET snapshot.", allow_abbrev=False)
    parser.add_argument("--origin", required=True, help="Explicit http(s)://host[:port], no path or credentials")
    parser.add_argument("--username", required=True, help="Local ecoNET username")
    parser.add_argument("--output-dir", required=True, type=Path, help="Private local snapshot directory")
    args = parser.parse_args(argv)
    try:
        validate_origin(args.origin)
        # Refuse getpass's echoing fallback when no hidden terminal is available.
        with warnings.catch_warnings():
            warnings.simplefilter("error", getpass.GetPassWarning)
            password = getpass.getpass("Local ecoNET password (hidden): ")
        path = capture(args.origin, args.username, password, args.output_dir)
    except (OSError, ValueError, EOFError, getpass.GetPassWarning):
        print("Capture failed; no snapshot saved. Check inputs, terminal, connection and output directory.", file=sys.stderr)
        return 1
    print("Review snapshot for private data before sharing; never commit captures.", file=sys.stderr)
    print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
