"""Behavioral socket-policy regressions, including real plugin registration orders."""
import os
from pathlib import Path
import socket
import subprocess
import sys

import pytest
import pytest_socket
from pytest_homeassistant_custom_component.plugins import HASocketBlockedError


def assert_tcp_blocked():
    with pytest.raises(pytest_socket.SocketBlockedError) as caught:
        with socket.socket():
            pytest.fail("TCP socket creation unexpectedly succeeded")
    # HA treats even caught socket errors as leaks. Account only for the exact
    # error deliberately triggered here, leaving any unexpected errors intact.
    if isinstance(caught.value, HASocketBlockedError):
        HASocketBlockedError.instances.remove(caught.value)


def test_default_tcp_blocked():
    assert_tcp_blocked()
    with socket.socket(socket.AF_UNIX):
        pass


@pytest.fixture
def check_loopback_teardown():
    yield
    # Runs after loopback_sockets' finalizer, before the next test's hooks can
    # mask a missing cleanup by installing a fresh guard.
    assert_tcp_blocked()


def test_loopback_fixture_teardown(check_loopback_teardown, request):
    request.getfixturevalue("loopback_sockets")
    with socket.socket() as server, socket.socket() as client:
        server.bind(("127.0.0.1", 0))
        server.listen(1)
        client.settimeout(2)
        client.connect(server.getsockname())
        connection, _ = server.accept()
        connection.close()
    for host in ("192.0.2.1", "127.0.0.2", "::1"):
        family = socket.AF_INET6 if host == "::1" else socket.AF_INET
        with socket.socket(family) as connection:
            with pytest.raises(pytest_socket.SocketConnectBlockedError):
                connection.connect((host, 80))


@pytest.mark.parametrize("plugins", [
    ("homeassistant", "socket"), ("socket", "homeassistant"),
])
def test_socket_policy_plugin_orders(plugins):
    root = Path(__file__).resolve().parents[1]
    env = os.environ.copy()
    env.pop("PYTHONPATH", None)
    env.pop("PYTHONHOME", None)
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", plugins[0], "-p", plugins[1],
         "tests/test_socket_policy.py::test_default_tcp_blocked",
         "tests/test_socket_policy.py::test_loopback_fixture_teardown",
         "tests/test_emulator.py::test_write_updates_settings_and_version",
         "tests/test_emulator.py::test_emulator_socket_exception_still_blocks_remote_hosts"],
        cwd=root, env=env, capture_output=True, text=True, timeout=90,
    )
    assert result.returncode == 0, result.stdout + result.stderr
