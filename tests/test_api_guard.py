"""Dispatch-time authorisation (auto-revert transport guard), over real loopback HTTP.

The guard is checked after the request lock and the completion-based gap,
immediately before each HTTP send, including every timeout retry. A refusal
sends nothing and is never retried. Callers without a guard are unchanged.
"""
import asyncio

import pytest
from aiohttp import ClientSession

from custom_components.econet_grant import api as api_module
from custom_components.econet_grant.api import EconetApi, EconetClient, WriteCancelled
from custom_components.econet_grant.const import API_MAX_RETRIES, MIN_REQUEST_GAP
from emulator import EconetEmulator

pytestmark = pytest.mark.usefixtures("loopback_sockets")


@pytest.fixture
async def pump_api(aiohttp_server, monkeypatch):
    monkeypatch.setattr(api_module, "MIN_REQUEST_GAP", 0)
    pump = EconetEmulator()
    server = await aiohttp_server(pump.app, host="127.0.0.1")
    async with ClientSession() as session:
        client = EconetClient(str(server.make_url("")), "test", "test-only",
                              pump.session(session))
        yield pump, EconetApi(client), client


async def test_unguarded_callers_unchanged(pump_api):
    pump, api, _ = pump_api
    assert await api.set_param("HDWTSetPoint", 49) is True
    assert pump.writes == [("HDWTSetPoint", 49.0)]
    pump.mode = "timeout"
    assert await api.set_param("HDWTSetPoint", 48) is False
    assert pump.writes[1:] == [("HDWTSetPoint", 48.0)] * API_MAX_RETRIES
    assert API_MAX_RETRIES == 5 and MIN_REQUEST_GAP == 1.0


async def test_refused_guard_sends_nothing(pump_api):
    pump, api, _ = pump_api
    with pytest.raises(WriteCancelled):
        await api.set_param("HDWTSetPoint", 49, authorise=lambda: False)
    with pytest.raises(WriteCancelled):
        await api.fetch_edit_params(authorise=lambda: False)
    assert pump.writes == [] and pump.requests == []


async def test_guard_checked_before_every_timeout_retry(pump_api):
    pump, api, _ = pump_api
    pump.mode = "timeout"
    calls = []

    def authorise():
        calls.append(len(pump.writes))
        return len(calls) < 3  # refuse the third attempt

    with pytest.raises(WriteCancelled):
        await api.set_param("HDWTSetPoint", 49, authorise=authorise)
    assert pump.writes == [("HDWTSetPoint", 49.0)] * 2
    assert calls == [0, 1, 2]


async def test_guard_evaluated_after_lock_wait(pump_api):
    """A refusal that becomes true while queued behind another request is honoured."""
    pump, api, client = pump_api
    allowed = [True]
    pump.mode = "timeout"
    first = asyncio.create_task(api.set_param("HDWTSetPoint", 48))
    while not pump.writes:
        await asyncio.sleep(0)
    second = asyncio.create_task(api.set_param("HDWTSetPoint", 49,
                                               authorise=lambda: allowed[0]))
    await asyncio.sleep(0)
    allowed[0] = False  # e.g. Safe Mode switched on while the guarded write waits
    assert await first is False
    with pytest.raises(WriteCancelled):
        await second
    assert ("HDWTSetPoint", 49.0) not in pump.writes


async def test_guard_evaluated_after_the_gap(pump_api, monkeypatch):
    pump, api, client = pump_api
    monkeypatch.setattr(api_module, "MIN_REQUEST_GAP", 0.05)
    allowed = [True]
    await api.fetch_sys_params()

    async def flip():
        await asyncio.sleep(0.01)
        allowed[0] = False

    flipper = asyncio.create_task(flip())
    with pytest.raises(WriteCancelled):
        await api.set_param("HDWTSetPoint", 49, authorise=lambda: allowed[0])
    await flipper
    assert pump.writes == []
