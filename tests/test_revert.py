"""Offline manual-action boundaries: no controller or mobile delivery."""
import asyncio
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from custom_components.econet_grant import revert
from custom_components.econet_grant.change_detector import ChangeDetector


@pytest.fixture
def actions(hass, entry, api, monkeypatch):
    entry.options.update(safe_mode=False, push_notifications=True,
                         revert_notify_service="mobile_app_test")
    hass.bus.async_listen = Mock(return_value=Mock())
    hass.services.has_service.return_value = True
    tasks = []

    def create_task(coro):
        task = asyncio.create_task(coro)
        tasks.append(task)
        return task

    hass.async_create_task = create_task
    notice = Mock()
    monkeypatch.setattr(revert, "pn_async_create", notice)
    db = SimpleNamespace(async_log_change=AsyncMock())
    manager = revert.RevertActions(hass, entry, api, db, ChangeDetector(hass, entry))
    manager.start()
    return manager, db, tasks, notice


async def offer(manager, tasks, edit_params):
    manager.observe(edit_params, [])
    changed = deepcopy(edit_params)
    changed["data"]["100"]["value"] = 24
    manager.observe(changed, [{"index": "100", "name": "Circuit1ComfortTemp",
                             "old_value": 20, "new_value": 24, "source": "external"}])
    await asyncio.gather(*tasks)
    return changed


def action(hass):
    return hass.services.async_call.call_args.args[2]["data"]["actions"][0]["action"]


async def test_only_explicit_action_writes_old_value_and_audits(
    actions, hass, api, edit_params,
):
    manager, db, tasks, notice = actions
    api.fetch_edit_params.return_value = await offer(manager, tasks, edit_params)
    api.set_param.assert_not_awaited()
    token = action(hass)
    listener = hass.bus.async_listen.call_args.args[1]
    await listener(SimpleNamespace(data={"action": token, "param_name": "untrusted",
                                        "old_value": 99}))
    api.set_param.assert_awaited_once_with("Circuit1ComfortTemp", 20)
    db.async_log_change.assert_awaited_once_with(
        hass, {"name": "Circuit1ComfortTemp", "index": "100",
               "old_value": 24, "new_value": 20}, source="revert",
    )
    await listener(SimpleNamespace(data={"action": token}))
    assert api.set_param.await_count == 1
    assert "accepted" in notice.call_args.kwargs["message"].lower()


async def test_revert_label_message_preserves_raw_write(actions, hass, api):
    manager, db, tasks, _ = actions
    before = {"data": {"236": {"name": "Circuit1WorkState", "value": 3,
                               "minv": 0, "maxv": 3, "edit": True}}}
    manager.observe(before, [])
    after = deepcopy(before)
    after["data"]["236"]["value"] = 1
    manager.observe(after, [{"index": "236", "name": "Circuit1WorkState",
                            "old_value": 3, "new_value": 1, "source": "external"}])
    await asyncio.gather(*tasks)
    assert hass.services.async_call.call_args.args[2]["message"] == "CH Operation Mode: Schedule → Day"
    token = action(hass)
    assert manager._pending[token].old_value == 3
    assert manager._pending[token].new_value == 1
    api.set_param.assert_not_awaited()
    api.fetch_edit_params.return_value = after
    await manager._handle_action(SimpleNamespace(data={"action": token}))
    api.set_param.assert_awaited_once_with("Circuit1WorkState", 3)
    db.async_log_change.assert_awaited_once_with(
        hass, {"name": "Circuit1WorkState", "index": "236",
               "old_value": 1, "new_value": 3}, source="revert",
    )


@pytest.mark.parametrize("case", ["safe", "expired", "changed", "renamed", "duplicate",
                                  "failed", "exception", "missing", "disabled", "closed"])
async def test_rejects_unsafe_or_failed_actions(actions, hass, entry, api, edit_params, monkeypatch, case):
    manager, db, tasks, notice = actions
    current = await offer(manager, tasks, edit_params)
    token = action(hass)
    api.fetch_edit_params.return_value = current
    if case == "safe":
        entry.options["safe_mode"] = True
    elif case == "expired":
        monkeypatch.setattr(revert, "monotonic", lambda: float("inf"))
    elif case == "changed":
        current["data"]["100"]["value"] = 25
    elif case == "renamed":
        current["data"]["100"]["name"] = "HDWTSetPoint"
    elif case == "duplicate":
        current["data"]["999"] = current["data"]["100"]
    elif case == "failed":
        api.set_param.return_value = False
    elif case == "exception":
        api.set_param.side_effect = OSError("offline test")
    elif case == "missing":
        api.fetch_edit_params.return_value = None
    elif case == "disabled":
        entry.options["push_notifications"] = False
    elif case == "closed":
        manager.close()
        hass.bus.async_listen.return_value.assert_called_once()
    await manager._handle_action(SimpleNamespace(data={"action": token}))
    db.async_log_change.assert_not_awaited()
    if case == "exception":
        assert "no automatic retry was made" not in notice.call_args.kwargs["message"]
        assert "Check the controller state" in notice.call_args.kwargs["message"]
    if case not in ("failed", "exception"):
        api.set_param.assert_not_awaited()
    await manager._handle_action(SimpleNamespace(data={"action": token}))
    assert api.set_param.await_count <= 1


@pytest.mark.parametrize("case", ["unknown", "wrong_entry", "unload_during_fetch", "safe_during_fetch"])
async def test_action_identity_and_inflight_guards(actions, hass, entry, api, edit_params, case):
    manager, db, tasks, _ = actions
    current = await offer(manager, tasks, edit_params)
    token = action(hass)
    target = manager
    if case == "unknown":
        token = "econet_grant_revert_unknown"
    elif case == "wrong_entry":
        other = SimpleNamespace(entry_id="other", options=entry.options)
        target = revert.RevertActions(hass, other, api, db, ChangeDetector(hass, other))
        target.start()

    async def fetch():
        if case == "unload_during_fetch":
            manager.close()
        elif case == "safe_during_fetch":
            entry.options["safe_mode"] = True
        return current

    api.fetch_edit_params.side_effect = fetch
    await target._handle_action(SimpleNamespace(data={"action": token}))
    api.set_param.assert_not_awaited()
    db.async_log_change.assert_not_awaited()
    target.close()


@pytest.mark.parametrize("case", ["unknown", "bitmask", "volatile", "readonly", "invalid_old", "rename"])
async def test_ineligible_changes_do_not_offer_actions(actions, hass, edit_params, case):
    manager, _, tasks, _ = actions
    before = deepcopy(edit_params)
    param = before["data"]["100"]
    if case in ("unknown", "bitmask", "volatile"):
        param["name"] = {"unknown": "UnknownSetting", "bitmask": "Circuit1Settings",
                         "volatile": "Circuit1boosttimeleft"}[case]
    elif case == "readonly":
        param["edit"] = False
    elif case == "invalid_old":
        param["value"] = 100
    manager.observe(before, [])
    after = deepcopy(before)
    after["data"]["100"]["value"] = 24
    if case == "rename":
        after["data"]["100"]["name"] = "HDWTSetPoint"
    manager.observe(after, [{"index": "100", "name": after["data"]["100"]["name"],
                             "old_value": param["value"], "new_value": 24, "source": "external"}])
    await asyncio.gather(*tasks)
    hass.services.async_call.assert_not_awaited()
    assert manager._pending == {}


async def test_pending_actions_bounded_superseded_and_expiring(actions, hass, edit_params, monkeypatch):
    manager, _, tasks, _ = actions
    monkeypatch.setattr(revert, "MAX_PENDING", 1)
    current = await offer(manager, tasks, edit_params)
    first = action(hass)
    current["data"]["103"] = {"name": "HDWTSetPoint", "value": 45,
                                "minv": 35, "maxv": 55, "edit": True}
    manager.observe(current, [])
    current["data"]["103"]["value"] = 50
    manager.observe(current, [{"index": "103", "name": "HDWTSetPoint", "old_value": 45,
                              "new_value": 50, "source": "external"}])
    await asyncio.gather(*tasks)
    assert len(manager._pending) == 1
    assert first not in manager._pending
    current["data"]["103"]["value"] = 51
    manager.observe(current, [])
    assert manager._pending == {}
    await offer(manager, tasks, edit_params)
    assert manager._pending
    monkeypatch.setattr(revert, "monotonic", lambda: float("inf"))
    manager.observe(edit_params, [])
    assert manager._pending == {}


async def test_poll_during_preflight_invalidates_inflight_action(actions, hass, api, edit_params):
    manager, db, tasks, _ = actions
    current = await offer(manager, tasks, edit_params)

    async def fetch():
        manager.observe(current, [])
        return current

    api.fetch_edit_params.side_effect = fetch
    await manager._handle_action(SimpleNamespace(data={"action": action(hass)}))
    api.set_param.assert_not_awaited()


async def test_setup_wires_trusted_poll_and_cleanup(hass, entry, api, monkeypatch, edit_params):
    import custom_components.econet_grant as integration
    manager = Mock()
    monkeypatch.setattr(integration, "RevertActions", Mock(return_value=manager))
    monkeypatch.setattr(integration, "make_api", AsyncMock(return_value=api))
    monkeypatch.setattr(integration, "async_get_clientsession", Mock())
    coordinator = SimpleNamespace(
        data={"editParams": edit_params}, async_config_entry_first_refresh=AsyncMock(),
        async_add_listener=Mock(),
    )
    monkeypatch.setattr(integration, "EconetFastCoordinator", Mock(return_value=coordinator))
    monkeypatch.setattr(integration, "EconetSlowCoordinator", Mock(return_value=coordinator))
    monkeypatch.setattr(integration, "EconetDatabase", Mock(return_value=Mock(spec=integration.EconetDatabase)))
    tasks = []
    hass.async_create_task = lambda coro: tasks.append(asyncio.create_task(coro))
    await integration.async_setup_entry(hass, entry)
    manager.start.assert_called_once()
    manager.observe.assert_called_once_with(edit_params, [])
    manager.observe.reset_mock()
    changed = deepcopy(edit_params)
    changed["data"]["100"]["value"] = 24
    coordinator.data = {"editParams": changed}
    coordinator.async_add_listener.call_args.args[0]()
    await asyncio.gather(*tasks)
    changes = manager.observe.call_args.args[1]
    assert changes[0]["source"] == "external"
    api.set_param.assert_not_awaited()
    entry.async_on_unload.assert_any_call(manager.close)


@pytest.mark.parametrize("editable", [False, 0, None, "false"])
async def test_readonly_parameter_cannot_be_reverted(actions, hass, api, edit_params, editable):
    manager, _, tasks, _ = actions
    current = await offer(manager, tasks, edit_params)
    current["data"]["100"]["edit"] = editable
    api.fetch_edit_params.return_value = current
    await manager._handle_action(SimpleNamespace(data={"action": action(hass)}))
    api.set_param.assert_not_awaited()


async def test_changed_controller_bounds_block_revert(actions, hass, api, edit_params):
    manager, db, tasks, _ = actions
    current = await offer(manager, tasks, edit_params)
    current["data"]["100"]["minv"] = 22
    api.fetch_edit_params.return_value = current
    await manager._handle_action(SimpleNamespace(data={"action": action(hass)}))
    api.set_param.assert_not_awaited()
    db.async_log_change.assert_not_awaited()


@pytest.mark.enable_socket
@pytest.mark.allow_hosts(["127.0.0.1"])
class TestRealHAManualRevert:
    """Real event bus, entry lifecycle, coordinator, HTTP client and SQLite audit."""

    @pytest.fixture
    def hass(self, real_hass):
        return real_hass

    @pytest.fixture(autouse=True)
    def notifications(self):
        """Use real persistent notifications rather than conftest boundary mocks."""

    @pytest.fixture
    def hass_config_dir(self, tmp_path):
        return str(tmp_path)

    @pytest.fixture
    async def loaded(self, real_hass, enable_custom_integrations, aiohttp_server, monkeypatch):
        from homeassistant.setup import async_setup_component
        from pytest_homeassistant_custom_component.common import MockConfigEntry
        from custom_components.econet_grant.const import DOMAIN
        from emulator import EconetEmulator

        pump = EconetEmulator()
        server = await aiohttp_server(pump.app, host="127.0.0.1")
        monkeypatch.setattr("custom_components.econet_grant.api.MIN_REQUEST_GAP", 0)
        assert await async_setup_component(real_hass, "persistent_notification", {})
        messages = []

        async def notify(call):
            messages.append(call.data)

        real_hass.services.async_register("notify", "mobile_app_test", notify)
        real_hass.services.async_register("notify", "notify", notify)
        entry = MockConfigEntry(
            domain=DOMAIN, title="Synthetic heat pump", unique_id="synthetic-revert",
            data={"host": str(server.make_url("")), "username": "test", "password": "test-only"},
            options={"safe_mode": False, "push_notifications": True,
                     "revert_notify_service": "mobile_app_test"},
        )
        entry.add_to_hass(real_hass)
        assert await real_hass.config_entries.async_setup(entry.entry_id)
        await real_hass.async_block_till_done()
        from custom_components.econet_grant.const import SERVICE_API
        client = real_hass.data[DOMAIN][entry.entry_id][SERVICE_API]._client
        monkeypatch.setattr(client, "_session", pump.session(client._session))
        return real_hass, entry, pump, messages

    async def guest_offer(self, loaded):
        from custom_components.econet_grant.const import DOMAIN, SERVICE_SLOW_COORDINATOR
        hass, entry, pump, messages = loaded
        pump.guest_change("Circuit1ComfortTemp", 24)
        await hass.data[DOMAIN][entry.entry_id][SERVICE_SLOW_COORDINATOR].async_refresh()
        await hass.async_block_till_done()
        assert pump.writes == []
        assert "econet_grant_external_changes" in hass.data["persistent_notification"]
        return next(m["data"]["actions"][0]["action"] for m in messages if "data" in m)

    async def tap(self, hass, token):
        hass.bus.async_fire("mobile_app_notification_action", {
            "action": token, "param_name": "untrusted", "old_value": 99,
        })
        await hass.async_block_till_done()

    async def audit(self, hass):
        import sqlite3
        from pathlib import Path

        def read():
            with sqlite3.connect(Path(hass.config.config_dir) / "econet_grant.db") as conn:
                return conn.execute(
                    "SELECT param_name, old_value, new_value, source FROM change_log"
                ).fetchall()

        return await hass.async_add_executor_job(read)

    async def test_manual_write_audit_replay_and_later_guest_notification(self, loaded):
        from custom_components.econet_grant.const import DOMAIN, SERVICE_SLOW_COORDINATOR
        hass, entry, pump, messages = loaded
        token = await self.guest_offer(loaded)
        assert "Circuit1ComfortTemp" not in token
        await self.tap(hass, token)
        assert pump.writes == [("Circuit1ComfortTemp", 20)]
        assert pump.edit["data"]["238"]["value"] == 20
        assert ("Circuit1ComfortTemp", "24", "20", "revert") in await self.audit(hass)
        await self.tap(hass, token)
        assert len(pump.writes) == 1
        slow = hass.data[DOMAIN][entry.entry_id][SERVICE_SLOW_COORDINATOR]
        await slow.async_refresh()
        await hass.async_block_till_done()
        messages.clear()
        pump.guest_change("Circuit1ComfortTemp", 23)
        await slow.async_refresh()
        await hass.async_block_till_done()
        assert any("23" in m["message"] and "data" in m for m in messages)
        assert len(pump.writes) == 1

    @pytest.mark.parametrize("mode", ["non_ok", "name_mismatch", "value_mismatch",
                                      "http_error", "malformed_json", "timeout"])
    async def test_api_failures_never_audit_success(self, loaded, mode):
        from custom_components.econet_grant.const import DOMAIN
        hass, entry, pump, _ = loaded
        token = await self.guest_offer(loaded)
        pump.mode = mode
        await self.tap(hass, token)
        assert pump.writes == [("Circuit1ComfortTemp", 20)] * (5 if mode == "timeout" else 1)
        assert pump.edit["data"]["238"]["value"] == 24
        assert not any(row[3] == "revert" for row in await self.audit(hass))
        notice = hass.data["persistent_notification"][f"econet_grant_revert_{entry.entry_id}"]
        assert "accepted" not in notice["message"].lower()
        writes = len(pump.writes)
        await self.tap(hass, token)
        assert len(pump.writes) == writes

    @pytest.fixture
    def timed_transport(self, loaded, monkeypatch):
        """Exercise the production gap with a client-local clock, not wall waits.

        HTTP and timeouts remain real. Each completed request costs 0.25 virtual
        seconds so a start-based throttle cannot pass as a completion-based one.
        Neither asyncio nor time is patched globally (HA/aiohttp stay untouched).
        """
        from contextlib import asynccontextmanager
        from custom_components.econet_grant import api as api_module
        from custom_components.econet_grant.const import DOMAIN, SERVICE_API, MIN_REQUEST_GAP

        hass, entry, _, _ = loaded
        client = hass.data[DOMAIN][entry.entry_id][SERVICE_API]._client
        session = client._session
        clock = SimpleNamespace(now=100.0, active=0, starts=[], ends=[], sleeps=[])
        assert MIN_REQUEST_GAP == 1.0
        monkeypatch.setattr(api_module, "MIN_REQUEST_GAP", MIN_REQUEST_GAP)
        client._last_request_at = clock.now

        async def sleep(delay):
            clock.sleeps.append(delay)
            clock.now += delay
            await asyncio.sleep(0)

        @asynccontextmanager
        async def get(*args, **kwargs):
            assert clock.active == 0, "HTTP requests must be serialized"
            assert clock.now - (clock.ends[-1] if clock.ends else 100.0) >= 1.0
            clock.active += 1
            clock.starts.append(clock.now)
            try:
                async with session.get(*args, **kwargs) as response:
                    yield response
            finally:
                clock.now += 0.25
                clock.ends.append(clock.now)
                clock.active -= 1

        monkeypatch.setattr(client, "_session", SimpleNamespace(get=get))
        monkeypatch.setattr(api_module, "time", SimpleNamespace(monotonic=lambda: clock.now))
        monkeypatch.setattr(api_module, "asyncio", SimpleNamespace(
            sleep=sleep, TimeoutError=asyncio.TimeoutError, Lock=asyncio.Lock,
        ))
        return clock

    @pytest.mark.parametrize("recovers", [False, True])
    async def test_one_tap_bounded_timeout_retries(self, loaded, timed_transport, recovers):
        from custom_components.econet_grant.const import DOMAIN, SERVICE_API, API_MAX_RETRIES
        hass, entry, pump, _ = loaded
        token = await self.guest_offer(loaded)
        assert API_MAX_RETRIES == 5  # total attempts, not five additional retries
        if recovers:
            pump.write_modes = ["timeout", "ok"]
        else:
            pump.mode = "timeout"
        # Timeout the real body read only after the emulator has received it.
        hass.bus.async_fire("mobile_app_notification_action", {"action": token})
        # A simultaneous duplicate tap must not start a second operation either.
        await self.tap(hass, token)
        expected = 2 if recovers else 5
        assert pump.writes == [("Circuit1ComfortTemp", 20)] * expected
        attempts = [params for _, params in pump.client_attempts if params]
        assert attempts == [{"newParamName": "Circuit1ComfortTemp", "newParamValue": "20"}] * expected
        assert len(pump.client_attempts) == len(pump.client_completions)
        rows = [row for row in await self.audit(hass) if row[3] == "revert"]
        assert rows == ([("Circuit1ComfortTemp", "24", "20", "revert")] if recovers else [])
        assert pump.edit["data"]["238"]["value"] == (20 if recovers else 24)
        notice = hass.data["persistent_notification"][f"econet_grant_revert_{entry.entry_id}"]
        assert ("accepted" in notice["message"].lower()) is recovers
        if not recovers:
            assert "not confirmed" in notice["message"]
            assert "Check the controller state" in notice["message"]
        requests = list(pump.requests)
        await self.tap(hass, token)
        assert pump.requests == requests  # replay cannot even begin a new preflight
        assert [row for row in await self.audit(hass) if row[3] == "revert"] == rows
        assert len(timed_transport.starts) == len(timed_transport.ends)
        assert timed_transport.sleeps == [1.0] * len(timed_transport.starts)
        # Contending reads still share the same production lock and gap.
        client = hass.data[DOMAIN][entry.entry_id][SERVICE_API]._client
        await asyncio.gather(client.get("sysParams"), client.get("sysParams"))
        assert len(pump.writes) == expected

    @pytest.mark.parametrize("recovers", [False, True])
    async def test_applied_write_lost_response_classification(self, loaded, timed_transport, recovers):
        from homeassistant.components.persistent_notification import async_dismiss
        from custom_components.econet_grant.const import DOMAIN, SERVICE_SLOW_COORDINATOR, EVENT_SETTING_CHANGED

        hass, entry, pump, messages = loaded
        token = await self.guest_offer(loaded)
        events = []
        hass.bus.async_listen(EVENT_SETTING_CHANGED, lambda event: events.append(event.data))
        pump.mode = "applied_timeout"
        if recovers:
            pump.write_modes = ["applied_timeout", "ok"]
        await self.tap(hass, token)
        expected = 2 if recovers else 5
        assert pump.writes == [("Circuit1ComfortTemp", 20)] * expected
        assert pump.edit["data"]["238"]["value"] == 20
        assert len(pump.timeout_releases) == (1 if recovers else 5)
        notice = hass.data["persistent_notification"][f"econet_grant_revert_{entry.entry_id}"]["message"]
        if recovers:
            assert "accepted by the API" in notice
        else:
            assert "not confirmed" in notice
            assert "Check the controller state" in notice
        rows = [row for row in await self.audit(hass) if row[3] == "revert"]
        assert rows == ([("Circuit1ComfortTemp", "24", "20", "revert")] if recovers else [])
        requests = list(pump.requests)
        await self.tap(hass, token)
        assert pump.requests == requests

        # Remove the original guest alert so a false replacement cannot hide.
        async_dismiss(hass, "econet_grant_external_changes")
        messages.clear()
        slow = hass.data[DOMAIN][entry.entry_id][SERVICE_SLOW_COORDINATOR]
        await slow.async_refresh()
        await hass.async_block_till_done()
        assert events == []
        assert messages == []
        assert "econet_grant_external_changes" not in hass.data["persistent_notification"]
        assert ("Circuit1ComfortTemp", "24", "20.0", "user") in await self.audit(hass)
        assert ("Circuit1ComfortTemp", "24", "20.0", "external") not in await self.audit(hass)

        pump.guest_change("Circuit1ComfortTemp", 23)
        await slow.async_refresh()
        await hass.async_block_till_done()
        assert len(events) == 1
        assert events[0]["old_value"] == 20 and events[0]["new_value"] == 23
        assert any("23" in m["message"] and "data" in m for m in messages)
        assert "econet_grant_external_changes" in hass.data["persistent_notification"]
        assert ("Circuit1ComfortTemp", "20.0", "23", "external") in await self.audit(hass)
        assert len(pump.writes) == expected

    @pytest.mark.parametrize("applied", [False, True])
    async def test_unconfirmed_revert_does_not_hide_unmatched_guest_change(self, loaded, applied):
        from custom_components.econet_grant.const import DOMAIN, SERVICE_SLOW_COORDINATOR, EVENT_SETTING_CHANGED

        hass, entry, pump, messages = loaded
        token = await self.guest_offer(loaded)
        pump.mode = "applied_timeout" if applied else "timeout"
        await self.tap(hass, token)
        assert pump.edit["data"]["238"]["value"] == (20 if applied else 24)
        slow = hass.data[DOMAIN][entry.entry_id][SERVICE_SLOW_COORDINATOR]
        if not applied:
            # An unchanged first poll retires a failed write expectation.
            await slow.async_refresh()
            await hass.async_block_till_done()
        events = []
        hass.bus.async_listen(EVENT_SETTING_CHANGED, lambda event: events.append(event.data))
        messages.clear()
        # Before the first poll (applied case), a different guest value is external.
        # After an unchanged poll, even the old requested target is external.
        guest_value = 23 if applied else 20
        pump.guest_change("Circuit1ComfortTemp", guest_value)
        await slow.async_refresh()
        await hass.async_block_till_done()
        assert len(events) == 1 and events[0]["new_value"] == guest_value
        assert any("data" in m for m in messages)
        assert len(pump.writes) == 5

    async def test_safe_mode_and_unload_remove_action_listener(self, loaded):
        hass, entry, pump, _ = loaded
        hass.config_entries.async_update_entry(entry, options={**entry.options, "safe_mode": True})
        await hass.async_block_till_done()
        token = await self.guest_offer(loaded)
        await self.tap(hass, token)
        assert pump.writes == []
        assert not any(row[3] == "revert" for row in await self.audit(hass))
        assert hass.bus.async_listeners()["mobile_app_notification_action"] == 1
        assert await hass.config_entries.async_unload(entry.entry_id)
        await hass.async_block_till_done()
        assert "mobile_app_notification_action" not in hass.bus.async_listeners()
        await self.tap(hass, token)
        assert pump.writes == []

    @pytest.mark.parametrize("case", ["blank", "missing", "delivery_failure"])
    async def test_persistent_fallback(self, loaded, case):
        from custom_components.econet_grant.const import DOMAIN, SERVICE_SLOW_COORDINATOR
        hass, entry, pump, messages = loaded
        if case == "blank":
            hass.config_entries.async_update_entry(entry, options={**entry.options, "revert_notify_service": ""})
            await hass.async_block_till_done()
        elif case == "missing":
            hass.services.async_remove("notify", "mobile_app_test")
        else:
            async def fail(call):
                raise RuntimeError("synthetic delivery failure")
            hass.services.async_register("notify", "mobile_app_test", fail)
        pump.guest_change("Circuit1ComfortTemp", 24)
        await hass.data[DOMAIN][entry.entry_id][SERVICE_SLOW_COORDINATOR].async_refresh()
        await hass.async_block_till_done()
        assert "24" in hass.data["persistent_notification"]["econet_grant_external_changes"]["message"]
        assert not any("data" in m for m in messages)
        assert pump.writes == []
