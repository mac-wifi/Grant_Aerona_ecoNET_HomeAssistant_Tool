"""Exercise the emulator through real aiohttp and the integration HTTP client."""
import pytest
from aiohttp import ClientSession, ClientTimeout

from custom_components.econet_grant.api import EconetApi, EconetClient
from custom_components.econet_grant.const import API_MAX_RETRIES
from emulator import EconetEmulator

pytestmark = [pytest.mark.enable_socket, pytest.mark.allow_hosts(["127.0.0.1"])]


def test_emulator_socket_exception_still_blocks_remote_hosts():
    import socket
    from pytest_socket import SocketConnectBlockedError

    with socket.socket() as connection:
        with pytest.raises(SocketConnectBlockedError):
            connection.connect(("192.0.2.1", 80))


async def test_write_updates_settings_and_version(aiohttp_server, monkeypatch):
    pump = EconetEmulator()
    server = await aiohttp_server(pump.app, host="127.0.0.1")
    monkeypatch.setattr("custom_components.econet_grant.api.MIN_REQUEST_GAP", 0)
    async with ClientSession() as session:
        api = EconetApi(EconetClient(str(server.make_url("")), "test", "test-only", session))
        before = await api.fetch_reg_params()
        assert await api.set_param("Circuit1ComfortTemp", 22)
        after = await api.fetch_reg_params()
        edit = await api.fetch_edit_params()
    assert edit["data"]["238"]["value"] == 22
    assert after["settingsVer"] == before["settingsVer"] + 1
    assert pump.writes == [("Circuit1ComfortTemp", 22)]


@pytest.mark.parametrize("mode", [
    "name_mismatch", "value_mismatch", "non_ok", "malformed_json", "http_error", "timeout",
])
async def test_write_failure_modes(aiohttp_server, monkeypatch, mode):
    pump = EconetEmulator()
    pump.mode = mode
    server = await aiohttp_server(pump.app, host="127.0.0.1")
    monkeypatch.setattr("custom_components.econet_grant.api.MIN_REQUEST_GAP", 0)
    async with ClientSession() as session:
        client = EconetClient(str(server.make_url("")), "test", "test-only", session)
        client._timeout = ClientTimeout(total=0.02)
        api = EconetApi(client)
        if mode == "malformed_json":
            from json import JSONDecodeError
            with pytest.raises(JSONDecodeError):
                await api.set_param("Circuit1ComfortTemp", 22)
        else:
            assert await api.set_param("Circuit1ComfortTemp", 22) is False
    assert pump.edit["data"]["238"]["value"] == 20
    assert pump.reg["settingsVer"] == 1
    assert len(pump.writes) == (API_MAX_RETRIES if mode == "timeout" else 1)
