"""Offline tests for standalone export tools; HTTP is always mocked."""

import importlib.util
import base64
import json
import copy
import subprocess
import sys
from http.client import IncompleteRead
from pathlib import Path
from unittest.mock import Mock

import pytest

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = Path(__file__).parent / "fixtures"


def load_tool(name):
    path = ROOT / "scripts" / f"{name}.py"
    assert path.exists(), f"Missing standalone tool: {name}"
    spec = importlib.util.spec_from_file_location(f"scripts.{name}", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def exporter():
    return load_tool("export_econet")


@pytest.fixture
def payloads():
    return {
        endpoint: json.loads((FIXTURES / filename).read_text())
        for endpoint, filename in (
            ("regParams", "reg_params.json"),
            ("editParams", "edit_params.json"),
            ("sysParams", "sys_params.json"),
        )
    }


def mock_http(monkeypatch, exporter, payloads):
    def open_request(request, timeout):
        response = Mock()
        response.status = 200
        response.read.return_value = json.dumps(
            payloads[request.full_url.rsplit("/", 1)[-1]]
        ).encode()
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        return response

    opener = Mock()
    opener.open.side_effect = open_request
    monkeypatch.setattr(exporter, "build_opener", Mock(return_value=opener))
    monkeypatch.setattr(exporter.time, "sleep", Mock())
    return opener


def test_capture_only_three_read_endpoints(tmp_path, monkeypatch, exporter, payloads):
    opener = mock_http(monkeypatch, exporter, payloads)
    first = exporter.capture("http://econet.invalid", "fixture-user", "fixture-pass", tmp_path)
    second = exporter.capture("http://econet.invalid", "fixture-user", "fixture-pass", tmp_path)
    assert first != second
    assert first.name.startswith("econet-") and first.suffix == ".json"
    snapshot = json.loads(first.read_text())
    assert snapshot["schema_version"] == 1
    assert snapshot["captured_at"].endswith("+00:00")
    assert set(snapshot["endpoints"]) == set(payloads)
    assert snapshot["endpoints"]["editParams"] == payloads["editParams"]
    assert snapshot["endpoints"]["regParams"] == payloads["regParams"]
    assert [call.args[0].full_url for call in opener.open.call_args_list] == [
        f"http://econet.invalid/econet/{endpoint}" for endpoint in payloads
    ] * 2
    assert all(call.args[0].get_method() == "GET" for call in opener.open.call_args_list)
    assert all(call.kwargs["timeout"] == 15 for call in opener.open.call_args_list)
    assert exporter.time.sleep.call_args_list == [((1,),)] * 4


def test_credentials_and_identifiers_never_exported(tmp_path, monkeypatch, exporter, payloads):
    secret_values = ["synthetic-uid", "192.0.2.8", "device.example.invalid",
                     "synthetic-serial", "synthetic-network", "2001:db8::8",
                     "02:00:00:00:00:08", "fixture-user", "fixture-pass"]
    payloads["sysParams"].update(dict(zip(
        ["uid", "ipAddress", "hostname", "serialNumber", "ssid", "ipv6", "macAddress",
         "username", "password"], secret_values
    )))
    payloads["sysParams"]["nested"] = {"wifi": {"name": "private-network"}}
    payloads["sysParams"]["message"] = "Connected: " + " / ".join(secret_values)
    payloads["editParams"]["data"]["999"] = {"name": "WifiPassword", "value": "extra-secret"}
    payloads["regParams"]["curr"]["note"] = "extra-secret private-network"
    opener = mock_http(monkeypatch, exporter, payloads)
    path = exporter.capture("http://device.example.invalid", "fixture-user", "fixture-pass", tmp_path)
    text = path.read_text()
    for secret in secret_values + ["extra-secret", "private-network", "synthetic-controller"]:
        assert secret not in text
    assert "[REDACTED]" in text
    auth = "Basic " + base64.b64encode(b"fixture-user:fixture-pass").decode()
    assert all(call.args[0].get_header("Authorization") == auth for call in opener.open.call_args_list)
    assert auth not in text


@pytest.mark.parametrize("bad", [None, {}, [], {"error": "fixture-pass"},
                                      {"data": {"1": {"value": 20}}},
                                      {"data": {"1": {"name": "Temp"}}}])
def test_failed_or_malformed_download_creates_no_snapshot(tmp_path, monkeypatch, exporter, payloads, bad):
    payloads["editParams"] = bad
    mock_http(monkeypatch, exporter, payloads)
    with pytest.raises(ValueError, match="Capture failed"):
        exporter.capture("http://econet.invalid", "fixture-user", "fixture-pass", tmp_path)
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("failure", [TimeoutError("fixture-pass"), OSError("fixture-user")])
def test_network_failure_has_safe_error(tmp_path, monkeypatch, exporter, payloads, failure):
    opener = mock_http(monkeypatch, exporter, payloads)
    opener.open.side_effect = failure
    with pytest.raises(ValueError, match="^Capture failed; no snapshot saved.$"):
        exporter.capture("http://econet.invalid", "fixture-user", "fixture-pass", tmp_path)
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("origin", ["", "econet.invalid", "ftp://econet.invalid",
    "http://user:pass@econet.invalid", "http://econet.invalid/econet/newParam",
    "http://econet.invalid?newParamName=x", "http://econet.invalid#fragment"])
def test_origin_requires_explicit_http_origin(tmp_path, monkeypatch, exporter, origin):
    build = Mock()
    monkeypatch.setattr(exporter, "build_opener", build)
    with pytest.raises(ValueError):
        exporter.capture(origin, "fixture-user", "fixture-pass", tmp_path)
    build.assert_not_called()


def test_compare_changed_added_removed_and_unchanged():
    compare = load_tool("compare_econet")
    before = compare.load_snapshot(FIXTURES / "export_before.json")
    after = compare.load_snapshot(FIXTURES / "export_after.json")
    assert compare.compare(before, before) == []
    assert compare.compare(before, after) == [
        {"endpoint": "editParams", "name": "Circuit1ComfortTemp", "index": "238",
         "change": "changed", "old": 20, "new": 21},
        {"endpoint": "editParams", "name": "SyntheticAdded", "index": "902",
         "change": "added", "old": None, "new": None},
        {"endpoint": "editParams", "name": "SyntheticRemoved", "index": "901",
         "change": "removed", "old": None, "new": None},
        {"endpoint": "regParams", "name": "/settingsVer", "index": None,
         "change": "changed", "old": 1, "new": 2},
    ]


@pytest.mark.parametrize("raw", [None, "not json", "{}", "null", "[]",
    '{"schema_version":1,"schema_version":1}', '{"x":NaN}'])
def test_missing_malformed_snapshot_fails(tmp_path, raw):
    compare = load_tool("compare_econet")
    path = tmp_path / "snapshot.json"
    if raw is not None:
        path.write_text(raw)
    with pytest.raises(ValueError, match="Invalid or unreadable snapshot"):
        compare.load_snapshot(path)


@pytest.mark.parametrize("mutation", [
    lambda s: s["endpoints"].pop("sysParams"),
    lambda s: s["endpoints"].update(rmParams={}),
    lambda s: s.update(schema_version=2),
    lambda s: s.update(captured_at="not a date"),
    lambda s: s["endpoints"].update(regParams={"error": "private"}),
])
def test_incomplete_or_unsupported_snapshot_fails(tmp_path, mutation):
    compare = load_tool("compare_econet")
    snapshot = json.loads((FIXTURES / "export_before.json").read_text())
    mutation(snapshot)
    path = tmp_path / "snapshot.json"
    path.write_text(json.dumps(snapshot))
    with pytest.raises(ValueError, match="Invalid or unreadable snapshot"):
        compare.load_snapshot(path)


def test_export_cli_prompts_password_and_redacts_failures(tmp_path, monkeypatch, capsys, exporter, payloads):
    mock_http(monkeypatch, exporter, payloads)
    monkeypatch.setattr(exporter.getpass, "getpass", Mock(return_value="fixture-pass"))
    args = ["--origin", "http://econet.invalid", "--username", "fixture-user",
            "--output-dir", str(tmp_path)]
    assert exporter.main(args) == 0
    streams = capsys.readouterr()
    assert "fixture-pass" not in streams.out + streams.err
    assert "Review" in streams.err
    assert Path(streams.out.strip()).is_file()
    monkeypatch.setattr(exporter, "capture", Mock(side_effect=OSError("fixture-pass")))
    assert exporter.main(args) == 1
    streams = capsys.readouterr()
    assert streams.out == ""
    assert "fixture-pass" not in streams.err


@pytest.mark.parametrize("args", [[], ["--origin", "http://econet.invalid"],
    ["--origin", "http://econet.invalid", "--username", "fixture-user", "--password", "fixture-pass"]])
def test_export_cli_required_inputs_no_password_argument(exporter, args, capsys):
    with pytest.raises(SystemExit) as error:
        exporter.main(args)
    assert error.value.code == 2
    assert "fixture-pass" not in capsys.readouterr().err


def test_compare_cli_success_and_failure(capsys, tmp_path):
    compare = load_tool("compare_econet")
    assert compare.main([str(FIXTURES / "export_before.json"), str(FIXTURES / "export_after.json")]) == 0
    streams = capsys.readouterr()
    assert len(json.loads(streams.out)) == 4
    assert "Review" in streams.err
    assert compare.main([str(tmp_path / "missing"), str(FIXTURES / "export_after.json")]) == 1
    streams = capsys.readouterr()
    assert streams.out == ""
    assert "comparison aborted" in streams.err


def test_standalone_cli_does_not_need_home_assistant(tmp_path):
    for script in ("export_econet", "compare_econet"):
        result = subprocess.run([sys.executable, str(ROOT / "scripts" / f"{script}.py"), "--help"],
                                cwd=tmp_path, capture_output=True, text=True, check=False)
        assert result.returncode == 0
        assert "usage:" in result.stdout
    result = subprocess.run([sys.executable, str(ROOT / "scripts/compare_econet.py"),
                             str(FIXTURES / "export_before.json"), str(FIXTURES / "export_after.json")],
                            cwd=tmp_path, capture_output=True, text=True, check=False)
    assert result.returncode == 0
    assert len(json.loads(result.stdout)) == 4


@pytest.mark.parametrize("status,raw", [(401, b"fixture-pass"), (500, b"fixture-pass"),
    (302, b"redirect"), (200, b"not json"), (200, b'{"curr":{"x":NaN}}'),
    (200, b'{"curr":{"x":1,"x":2}}'), (200, b"\xff")])
def test_bad_http_fails_closed(tmp_path, monkeypatch, exporter, payloads, status, raw):
    opener = mock_http(monkeypatch, exporter, payloads)
    response = opener.open.side_effect(Mock(full_url="http://econet.invalid/regParams"), 15)
    response.status = status
    response.read.return_value = raw
    opener.open.side_effect = None
    opener.open.return_value = response
    with pytest.raises(ValueError, match="Capture failed"):
        exporter.capture("http://econet.invalid", "fixture-user", "fixture-pass", tmp_path)
    assert list(tmp_path.iterdir()) == []


def test_transport_disables_proxy_and_redirects(tmp_path, monkeypatch, exporter, payloads):
    mock_http(monkeypatch, exporter, payloads)
    exporter.capture("https://econet.invalid/", "fixture-user", "fixture-pass", tmp_path)
    proxy, redirect = exporter.build_opener.call_args.args
    assert proxy.proxies == {}
    assert redirect.redirect_request(None, None, 302, None, None, "http://other.invalid") is None


def test_atomic_output_failure_leaves_no_valid_snapshot(tmp_path, monkeypatch, exporter, payloads):
    mock_http(monkeypatch, exporter, payloads)
    monkeypatch.setattr(exporter.os, "link", Mock(side_effect=OSError("disk failed")))
    with pytest.raises(ValueError, match="Capture failed"):
        exporter.capture("http://econet.invalid", "fixture-user", "fixture-pass", tmp_path)
    assert list(tmp_path.iterdir()) == []


def test_comparison_nested_metadata_renames_and_redaction():
    compare = load_tool("compare_econet")
    before = compare.load_snapshot(FIXTURES / "export_before.json")
    after = copy.deepcopy(before)
    after["endpoints"]["editParams"]["data"]["238"]["maxv"] = 34
    after["endpoints"]["editParams"]["data"]["103"]["name"] = "SyntheticRenamed"
    after["endpoints"]["sysParams"].update(uid="synthetic-new-id", alarms=["synthetic-new-id"])
    after["endpoints"]["regParams"]["curr"]["nested/key"] = {"x~y": 1}
    rows = compare.compare(before, after)
    assert any(r["name"] == "/data/238/maxv" and r["new"] == 34 for r in rows)
    assert any(r["name"] == "HDWTSetPoint" and r["change"] == "removed" for r in rows)
    assert any(r["name"] == "SyntheticRenamed" and r["change"] == "added" for r in rows)
    assert any(r["name"] == "/curr/nested~1key/x~0y" for r in rows)
    assert "synthetic-new-id" not in json.dumps(rows)


def test_truncated_http_response_is_safe(tmp_path, monkeypatch, exporter, payloads):
    opener = mock_http(monkeypatch, exporter, payloads)
    opener.open.side_effect = IncompleteRead(b"fixture-pass", 100)
    with pytest.raises(ValueError, match="Capture failed"):
        exporter.capture("http://econet.invalid", "fixture-user", "fixture-pass", tmp_path)
    assert list(tmp_path.iterdir()) == []


def test_common_short_private_fields_and_echoes(exporter):
    values = {"host": "synthetic-host", "mac": "synthetic-mac", "user": "synthetic-user",
              "login": "synthetic-login", "pwd": "synthetic-pwd"}
    cleaned = exporter.sanitise({"fields": values, "echo": list(values.values())})
    for value in values.values():
        assert value not in json.dumps(cleaned)


def test_hidden_password_unavailable_fails_without_http(tmp_path, monkeypatch, exporter, capsys):
    def no_terminal(prompt):
        exporter.warnings.warn("Password may echo", exporter.getpass.GetPassWarning)
        pytest.fail("Must not fall back to visible password entry")

    monkeypatch.setattr(exporter.getpass, "getpass", no_terminal)
    network = Mock()
    monkeypatch.setattr(exporter, "build_opener", network)
    assert exporter.main(["--origin", "http://econet.invalid", "--username", "fixture-user",
                          "--output-dir", str(tmp_path)]) == 1
    network.assert_not_called()
    assert "Capture failed" in capsys.readouterr().err


def test_snapshot_is_private_and_collision_does_not_overwrite(tmp_path, monkeypatch, exporter, payloads):
    mock_http(monkeypatch, exporter, payloads)
    now = exporter.datetime.now(exporter.timezone.utc)
    monkeypatch.setattr(exporter, "datetime", Mock(now=Mock(return_value=now)))
    path = exporter.capture("http://econet.invalid", "fixture-user", "fixture-pass", tmp_path)
    original = path.read_bytes()
    assert path.stat().st_mode & 0o777 == 0o600
    with pytest.raises(ValueError, match="Capture failed"):
        exporter.capture("http://econet.invalid", "fixture-user", "fixture-pass", tmp_path)
    assert path.read_bytes() == original
    assert list(tmp_path.iterdir()) == [path]


@pytest.mark.parametrize("endpoint", ["regParams", "sysParams"])
def test_other_endpoint_failures_do_not_publish(tmp_path, monkeypatch, exporter, payloads, endpoint):
    payloads[endpoint] = {"result": "ERROR", "message": "fixture-pass"}
    mock_http(monkeypatch, exporter, payloads)
    with pytest.raises(ValueError, match="Capture failed"):
        exporter.capture("http://econet.invalid", "fixture-user", "fixture-pass", tmp_path)
    assert list(tmp_path.iterdir()) == []


def test_oversize_response_rejected(tmp_path, monkeypatch, exporter, payloads):
    mock_http(monkeypatch, exporter, payloads)
    monkeypatch.setattr(exporter, "MAX_BYTES", 10)
    with pytest.raises(ValueError, match="Capture failed"):
        exporter.capture("http://econet.invalid", "fixture-user", "fixture-pass", tmp_path)
    assert list(tmp_path.iterdir()) == []
