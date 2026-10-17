"""Small boundary fixtures; integration and HA modules themselves are real."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
import pytest_socket
from pytest_homeassistant_custom_component.plugins import hass as real_hass

pytest_plugins = ["pytest_homeassistant_custom_component"]

from custom_components.econet_grant import backup, change_detector, number, select
from custom_components.econet_grant.api import EconetApi


@pytest.fixture
def loopback_sockets():
    """Opt in after both plugins' setup hooks, for this test function only."""
    pytest_socket.enable_socket()
    try:
        # Apply to the real socket class, not a plugin's GuardedSocket subclass.
        pytest_socket.socket_allow_hosts(["127.0.0.1"], allow_unix_socket=True)
        yield
    finally:
        pytest_socket.disable_socket(allow_unix_socket=True)


@pytest.fixture
def edit_params():
    # Original boundary fixture preserved independently of the sample-based emulator.
    return {"editableParamsVer": 1, "data": {
        "100": {"name": "Circuit1ComfortTemp", "value": 20, "minv": 10, "maxv": 30, "edit": True},
        "101": {"name": "HDWSETTINGS", "value": 5, "minv": 0, "maxv": 255, "edit": True},
        "102": {"name": "SyntheticReadOnly", "value": 7, "edit": False},
    }}


@pytest.fixture
def entry():
    return SimpleNamespace(
        entry_id="test-entry", options={"push_notifications": False},
        async_on_unload=Mock(), add_update_listener=Mock(return_value=Mock()),
        data={"host": "econet.invalid", "username": "test", "password": "test-only"},
    )


@pytest.fixture
def hass(tmp_path, real_hass):
    return SimpleNamespace(
        data={}, config=SimpleNamespace(config_dir=str(tmp_path)),
        bus=SimpleNamespace(async_fire=Mock(), async_listen=Mock(return_value=Mock())),
        services=SimpleNamespace(
            has_service=Mock(return_value=False), async_register=Mock(),
            async_call=AsyncMock(),
        ),
        config_entries=SimpleNamespace(
            async_forward_entry_setups=AsyncMock(),
            async_unload_platforms=AsyncMock(return_value=True),
            async_reload=AsyncMock(return_value=True),
        ),
    )


@pytest.fixture
def api(edit_params):
    api = Mock(spec=EconetApi)
    api.host = "http://econet.invalid"
    api.uid = "synthetic-test-device"
    api.fetch_edit_params.return_value = edit_params
    api.set_param.return_value = True
    return api


@pytest.fixture(autouse=True)
def notifications(monkeypatch):
    notification = Mock()
    for module in (backup, change_detector, number, select):
        monkeypatch.setattr(module, "pn_async_create", notification)
    return notification
