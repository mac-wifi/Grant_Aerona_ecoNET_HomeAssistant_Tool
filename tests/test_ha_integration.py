"""Real HA config-entry/platform lifecycle against a loopback heat pump."""
import asyncio
import base64
from datetime import timedelta

import pytest
import voluptuous as vol
from aiohttp import web
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.components.repairs import repairs_flow_manager
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import issue_registry as ir
from homeassistant.setup import async_setup_component
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.econet_grant import config_flow, repairs
from custom_components.econet_grant.const import DOMAIN
from emulator import EconetEmulator

pytestmark = pytest.mark.usefixtures("loopback_sockets")


@pytest.fixture(autouse=True)
def notifications():
    """Do not apply the legacy boundary notification mock to real HA tests."""


@pytest.fixture
def hass(real_hass):
    """Plugin fixtures must share the real instance, not the boundary namespace."""
    return real_hass


@pytest.fixture
def hass_config_dir(tmp_path):
    return str(tmp_path)


@pytest.fixture
async def loaded(real_hass, enable_custom_integrations, aiohttp_server, monkeypatch):
    pump = EconetEmulator()
    server = await aiohttp_server(pump.app, host="127.0.0.1")
    monkeypatch.setattr("custom_components.econet_grant.api.MIN_REQUEST_GAP", 0)
    assert await async_setup_component(real_hass, "persistent_notification", {})
    entry = MockConfigEntry(
        domain=DOMAIN, title="Synthetic heat pump", unique_id="synthetic-entry",
        data={"host": str(server.make_url("")), "username": "test", "password": "test-only"},
        options={"safe_mode": True, "push_notifications": False},
    )
    entry.add_to_hass(real_hass)
    assert await real_hass.config_entries.async_setup(entry.entry_id)
    await real_hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED
    return real_hass, entry, pump


async def test_setup_platform_entities_and_unload(loaded):
    hass, entry, pump = loaded
    assert isinstance(hass, HomeAssistant)
    entities = er.async_entries_for_config_entry(er.async_get(hass), entry.entry_id)
    assert {entity.domain for entity in entities} == {"sensor", "number", "select", "button"}
    for domain in ("sensor", "number", "select", "button"):
        assert any(hass.states.get(entity.entity_id) is not None
                   for entity in entities if entity.domain == domain)
    assert {"regParams", "editParams", "sysParams"} <= set(pump.requests)
    assert pump.auth_headers == {"Basic dGVzdDp0ZXN0LW9ubHk="}  # test:test-only
    assert pump.writes == []
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.NOT_LOADED
    assert not hasattr(entry, "runtime_data")
    # HA retains registry entries as restored/unavailable after platform unload.
    for entity in entities:
        state = hass.states.get(entity.entity_id)
        assert state.state == "unavailable"
        assert state.attributes["restored"] is True


async def test_options_flow_reloads_poll_interval(loaded):
    hass, entry, pump = loaded
    old = entry.runtime_data.slow_coordinator
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] == "form"
    result = await hass.config_entries.options.async_configure(result["flow_id"], {
        "safe_mode": True, "push_notifications": False, "slow_poll_interval": 30,
    })
    assert result["type"] == "create_entry"
    await hass.async_block_till_done()
    assert entry.options["slow_poll_interval"] == 30
    current = entry.runtime_data.slow_coordinator
    assert current is not old
    assert current.update_interval == timedelta(minutes=30)
    assert entry.state is ConfigEntryState.LOADED
    assert pump.writes == []


async def test_guest_version_change_creates_notification(loaded):
    hass, entry, pump = loaded
    assert "econet_grant_external_changes" not in hass.data.get("persistent_notification", {})
    before = pump.requests.count("editParams")
    pump.guest_change("Circuit1ComfortTemp", 22)
    await entry.runtime_data.fast_coordinator.async_refresh()
    await hass.async_block_till_done()
    assert pump.requests.count("editParams") == before + 1
    notification = hass.data["persistent_notification"]["econet_grant_external_changes"]
    assert "22" in notification["message"]
    assert "20" in notification["message"]
    assert pump.writes == []


@pytest.mark.parametrize("old,new", [(3, 1), (1, 2), (2, 0), (0, 3)])
async def test_guest_mode_notification_matches_dashboard(loaded, old, new):
    import sqlite3
    from pathlib import Path
    from custom_components.econet_grant.const import EVENT_SETTING_CHANGED, SELECT_DEFINITIONS

    hass, entry, pump = loaded
    pump.edit["data"]["236"] = {"name": "Circuit1WorkState", "value": old,
                                "minv": 0, "maxv": 3, "edit": True}
    messages = []

    async def notify(call):
        messages.append((call.service, call.data))

    hass.services.async_register("notify", "notify", notify)
    hass.services.async_register("notify", "mobile_app_test", notify)
    hass.config_entries.async_update_entry(entry, options={
        **entry.options, "safe_mode": False, "push_notifications": True,
        "revert_notify_service": "mobile_app_test",
    })
    await hass.async_block_till_done()
    entities = er.async_entries_for_config_entry(er.async_get(hass), entry.entry_id)
    entity_id = next(e.entity_id for e in entities if e.entity_id.endswith("_ch_operation_mode"))
    old_label = hass.states.get(entity_id).state
    assert old_label == SELECT_DEFINITIONS["Circuit1WorkState"]["options"][old]
    events = []
    hass.bus.async_listen(EVENT_SETTING_CHANGED, lambda event: events.append(event.data))
    pump.guest_change("Circuit1WorkState", new)
    await entry.runtime_data.fast_coordinator.async_refresh()
    await hass.async_block_till_done()
    new_label = hass.states.get(entity_id).state
    assert new_label == SELECT_DEFINITIONS["Circuit1WorkState"]["options"][new]
    transition = f"{old_label} → {new_label}"
    persistent = hass.data["persistent_notification"]["econet_grant_external_changes"]["message"]
    assert f"**CH Operation Mode**: {transition}" in persistent
    push = next(data for service, data in messages if service == "notify")
    actionable = next(data for service, data in messages if service == "mobile_app_test")
    assert push["message"] == f"Settings changed:\nCH Operation Mode: {transition}"
    assert actionable["message"] == f"CH Operation Mode: {transition}"
    assert events == [{"param_name": "Circuit1WorkState", "param_index": "236",
                       "old_value": old, "new_value": new}]
    assert pump.writes == []

    def audit():
        with sqlite3.connect(Path(hass.config.config_dir) / "econet_grant.db") as conn:
            return conn.execute(
                "SELECT old_value, new_value, source FROM change_log WHERE param_name = ?",
                ("Circuit1WorkState",),
            ).fetchall()

    assert await hass.async_add_executor_job(audit) == [(str(old), str(new), "external")]
    token = actionable["data"]["actions"][0]["action"]
    hass.bus.async_fire("mobile_app_notification_action", {"action": token})
    await hass.async_block_till_done()
    assert pump.writes == [("Circuit1WorkState", old)]
    assert (str(new), str(old), "revert") in await hass.async_add_executor_job(audit)
    hass.bus.async_fire("mobile_app_notification_action", {"action": token})
    await hass.async_block_till_done()
    assert pump.writes == [("Circuit1WorkState", old)]


async def test_safe_mode_blocks_number_and_select_services(loaded):
    hass, entry, pump = loaded
    entities = er.async_entries_for_config_entry(er.async_get(hass), entry.entry_id)
    number = next(e.entity_id for e in entities if e.entity_id.endswith("_ch_day_temp"))
    select = next(e.entity_id for e in entities if e.entity_id.endswith("_hw_boost"))
    await hass.services.async_call("number", "set_value", {
        "entity_id": number, "value": 22,
    }, blocking=True)
    options = hass.states.get(select).attributes["options"]
    await hass.services.async_call("select", "select_option", {
        "entity_id": select, "option": options[0],
    }, blocking=True)
    await hass.async_block_till_done()
    assert pump.writes == []
    assert pump.edit["data"]["238"]["value"] == 20
    assert pump.reg["settingsVer"] == 1
    notifications = hass.data["persistent_notification"]
    assert len([key for key in notifications if key.startswith("econet_grant_write_")]) == 2


async def test_own_bitmask_write_is_not_reported_as_guest_change(loaded):
    """The self-write marker must use the API name the detector sees (HDWSETTINGS)."""
    import sqlite3
    from pathlib import Path

    hass, entry, pump = loaded
    hass.config_entries.async_update_entry(entry, options={**entry.options, "safe_mode": False})
    await hass.async_block_till_done()
    select = "select.grant_aerona_heat_pump_hw_specify_priority"
    assert hass.states.get(select).state == "No"
    await hass.services.async_call("select", "select_option", {
        "entity_id": select, "option": "Yes",
    }, blocking=True)
    assert pump.writes == [("HDWSETTINGS", 21.0)]
    await entry.runtime_data.fast_coordinator.async_refresh()
    await hass.async_block_till_done()
    assert "econet_grant_external_changes" not in hass.data.get("persistent_notification", {})

    def sources():
        with sqlite3.connect(Path(hass.config.config_dir) / "econet_grant.db") as conn:
            return conn.execute("SELECT param_name, source FROM change_log").fetchall()

    assert ("HDWSETTINGS", "external") not in await hass.async_add_executor_job(sources)


async def test_restore_button_previews_default_snapshot_in_safe_mode(loaded):
    """The dashboard button must call the service with a schema-valid payload."""
    hass, entry, pump = loaded
    await hass.services.async_call("econet_grant", "backup_settings",
                                   {"snapshot_name": "Default"}, blocking=True)
    pump.guest_change("Circuit1ComfortTemp", 23)
    await hass.services.async_call("button", "press", {
        "entity_id": "button.grant_aerona_heat_pump_restore_default_settings",
    }, blocking=True)
    await hass.async_block_till_done()
    preview = hass.data["persistent_notification"]["econet_grant_restore_preview"]
    assert "Circuit1ComfortTemp" in preview["message"]
    assert "23 -> 20" in preview["message"]
    assert pump.writes == []


async def test_setting_entities_update_on_the_settings_poll(loaded):
    """A detected guest change must show on the dashboard in the same poll cycle."""
    hass, entry, pump = loaded
    number = "number.grant_aerona_heat_pump_ch_day_temp"
    bitmask = "select.grant_aerona_heat_pump_hw_specify_priority"
    assert hass.states.get(number).state == "20"
    assert hass.states.get(bitmask).state == "No"
    pump.guest_change("Circuit1ComfortTemp", 23)
    pump.guest_change("HDWSETTINGS", 21)
    await entry.runtime_data.fast_coordinator.async_refresh()  # sees settingsVer, refreshes settings
    await hass.async_block_till_done()
    assert "econet_grant_external_changes" in hass.data["persistent_notification"]
    assert hass.states.get(number).state == "23"
    assert hass.states.get(bitmask).state == "Yes"
    assert pump.writes == []


@pytest.mark.parametrize("case", ["missing", "unchanged"])
async def test_restore_always_reports_outcome(loaded, case):
    """The dashboard's Restore must never finish silently."""
    hass, entry, pump = loaded
    if case == "unchanged":
        await hass.services.async_call("econet_grant", "backup_settings",
                                       {"snapshot_name": "Default"}, blocking=True)
    await hass.services.async_call("econet_grant", "restore_settings",
                                   {"snapshot_name": "Default"}, blocking=True)
    await hass.async_block_till_done()
    result = hass.data["persistent_notification"]["econet_grant_restore_result"]
    expected = "No 'Default' snapshot" if case == "missing" else "already match"
    assert expected in result["message"]
    assert pump.writes == []


async def test_restore_reports_written_changes(loaded):
    hass, entry, pump = loaded
    await hass.services.async_call("econet_grant", "backup_settings",
                                   {"snapshot_name": "Default"}, blocking=True)
    pump.guest_change("Circuit1ComfortTemp", 23)
    await hass.services.async_call("econet_grant", "restore_settings",
                                   {"snapshot_name": "Default"}, blocking=True)
    assert "econet_grant_restore_preview" in hass.data["persistent_notification"]
    hass.config_entries.async_update_entry(entry, options={**entry.options, "safe_mode": False})
    await hass.async_block_till_done()
    await hass.services.async_call("econet_grant", "restore_settings",
                                   {"snapshot_name": "Default"}, blocking=True)
    await hass.async_block_till_done()
    assert pump.writes == [("Circuit1ComfortTemp", 20.0)]
    assert "econet_grant_restore_preview" not in hass.data["persistent_notification"]
    result = hass.data["persistent_notification"]["econet_grant_restore_result"]
    assert "Restored 1 parameter" in result["message"]
    assert "Circuit1ComfortTemp" in result["message"]


async def test_integration_version_sensor_matches_manifest(loaded):
    import json
    from pathlib import Path

    hass, entry, pump = loaded
    manifest = Path(__file__).parents[1] / "custom_components/econet_grant/manifest.json"
    version = json.loads(manifest.read_text())["version"]
    state = hass.states.get("sensor.grant_aerona_heat_pump_integration_version")
    assert state is not None and state.state == version


async def test_last_snapshot_sensor_updates_right_after_backup(loaded):
    """The Admin tab must show the new snapshot without waiting for the next poll."""
    hass, entry, pump = loaded
    sensor = "sensor.grant_aerona_heat_pump_last_default_snapshot"
    assert hass.states.get(sensor).state == "unknown"
    await hass.services.async_call("econet_grant", "backup_settings",
                                   {"snapshot_name": "Default"}, blocking=True)
    await hass.async_block_till_done()
    state = hass.states.get(sensor)
    assert state.state not in ("unknown", "unavailable")
    assert state.attributes["param_count"] > 0


@pytest.mark.parametrize("safe_mode", [True, False])
async def test_restore_service_ignores_self_changing_values(loaded, safe_mode):
    """Owner report: an unchanged system previewed 'GrantReg03Float 39.0 -> 38.0'."""
    hass, entry, pump = loaded
    pump.edit["data"]["1148"] = {"name": "GrantReg03Float", "value": 39.0,
                                 "minv": 0, "maxv": 100, "edit": True}
    await hass.services.async_call("econet_grant", "backup_settings",
                                   {"snapshot_name": "Default"}, blocking=True)
    pump.edit["data"]["1148"]["value"] = 38.0  # the controller changes it by itself
    hass.config_entries.async_update_entry(entry, options={**entry.options,
                                                           "safe_mode": safe_mode})
    await hass.async_block_till_done()
    await hass.services.async_call("econet_grant", "restore_settings",
                                   {"snapshot_name": "Default"}, blocking=True)
    await hass.async_block_till_done()
    notices = hass.data["persistent_notification"]
    assert "econet_grant_restore_preview" not in notices
    assert "already match" in notices["econet_grant_restore_result"]["message"]
    assert pump.writes == []


async def _second_pump(aiohttp_server):
    pump = EconetEmulator()
    server = await aiohttp_server(pump.app, host="127.0.0.1")
    return pump, str(server.make_url(""))


async def _reconfigure(hass, entry, host):
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": "reconfigure", "entry_id": entry.entry_id})
    if host is None:
        return result
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"host": host})
    await hass.async_block_till_done()
    return result


def _registry_snapshot(hass, entry):
    entities = er.async_entries_for_config_entry(er.async_get(hass), entry.entry_id)
    devices = dr.async_entries_for_config_entry(dr.async_get(hass), entry.entry_id)
    return ({(e.entity_id, e.unique_id) for e in entities}, {d.id for d in devices})


async def test_reconfigure_form_prefills_current_host(loaded):
    hass, entry, _pump = loaded
    result = await _reconfigure(hass, entry, None)
    assert result["type"] == "form"
    assert result["step_id"] == "reconfigure"
    key = next(k for k in result["data_schema"].schema if k == "host")
    assert key.description["suggested_value"] == entry.data["host"]


async def test_reconfigure_moves_to_new_host_and_keeps_entities(loaded, aiohttp_server):
    hass, entry, pump_a = loaded
    pump_b, new = await _second_pump(aiohttp_server)
    before = _registry_snapshot(hass, entry)
    options = dict(entry.options)
    result = await _reconfigure(hass, entry, new)
    assert result["type"] == "abort"
    assert result["reason"] == "reconfigure_successful"
    assert entry.data["host"] == new
    assert entry.data["username"] == "test" and entry.data["password"] == "test-only"
    assert entry.unique_id == new
    assert dict(entry.options) == options
    assert entry.state is ConfigEntryState.LOADED
    assert _registry_snapshot(hass, entry) == before
    assert {"regParams", "editParams", "sysParams"} <= set(pump_b.requests)
    assert pump_a.writes == [] and pump_b.writes == []


async def test_reconfigure_rejects_different_controller(loaded, aiohttp_server):
    hass, entry, _pump = loaded
    pump_b, new = await _second_pump(aiohttp_server)
    pump_b.sys = {**pump_b.sys, "uid": "some-other-device"}
    old_host = entry.data["host"]
    result = await _reconfigure(hass, entry, new)
    assert result["type"] == "form"
    assert result["errors"] == {"base": "wrong_device"}
    assert entry.data["host"] == old_host
    assert entry.unique_id == "synthetic-entry"


async def test_reconfigure_unreachable_host_keeps_old_host(loaded, monkeypatch):
    hass, entry, _pump = loaded
    monkeypatch.setattr("custom_components.econet_grant.api.API_MAX_RETRIES", 1)
    old_host = entry.data["host"]
    result = await _reconfigure(hass, entry, "http://127.0.0.1:9")
    assert result["type"] == "form"
    assert result["errors"] == {"base": "cannot_connect"}
    assert entry.data["host"] == old_host
    assert entry.unique_id == "synthetic-entry"


async def test_reconfigure_bad_credentials(loaded, aiohttp_server):
    hass, entry, _pump = loaded
    pump_b, new = await _second_pump(aiohttp_server)
    pump_b.auth_fail = True
    old_host = entry.data["host"]
    result = await _reconfigure(hass, entry, new)
    assert result["type"] == "form"
    assert result["errors"] == {"base": "invalid_auth"}
    assert entry.data["host"] == old_host


@pytest.mark.parametrize("renamed", [True, False])
async def test_reconfigure_title_handling(loaded, aiohttp_server, renamed):
    hass, entry, _pump = loaded
    _pump_b, new = await _second_pump(aiohttp_server)
    title = "Heat pump" if renamed else f"EcoNet Grant ({entry.data['host']})"
    hass.config_entries.async_update_entry(entry, title=title)
    result = await _reconfigure(hass, entry, new)
    assert result["reason"] == "reconfigure_successful"
    assert entry.title == ("Heat pump" if renamed else f"EcoNet Grant ({new})")


async def test_reconfigure_rejects_host_used_by_another_entry(loaded):
    hass, entry, _pump = loaded
    other = "http://192.0.2.10"
    MockConfigEntry(
        domain=DOMAIN, unique_id=other,
        data={"host": other, "username": "test", "password": "test-only"},
    ).add_to_hass(hass)
    old_host = entry.data["host"]
    result = await _reconfigure(hass, entry, other)
    assert result["type"] == "form"
    assert result["errors"] == {"base": "already_configured"}
    assert entry.data["host"] == old_host
    assert entry.unique_id == "synthetic-entry"


async def test_reconfigure_reloads_exactly_once(loaded, aiohttp_server, caplog):
    """The entry's update listener reloads; a second reload doubles controller traffic."""
    hass, entry, _pump = loaded
    pump_b, new = await _second_pump(aiohttp_server)
    await _reconfigure(hass, entry, new)
    # 1 validation fetch + one setup (make_api + slow coordinator first refresh).
    assert pump_b.requests.count("sysParams") == 3
    assert pump_b.requests.count("regParams") == 1
    assert "should use it for scheduling a reload" not in caplog.text


async def test_reconfigure_ignores_host_fallback_identifier(loaded, aiohttp_server):
    """A device keyed by the host (controller never gave a uid) is not a different pump."""
    hass, entry, _pump = loaded
    registry = dr.async_get(hass)
    for device in dr.async_entries_for_config_entry(registry, entry.entry_id):
        registry.async_update_device(
            device.id, new_identifiers={(DOMAIN, entry.data["host"].rstrip("/"))})
    _pump_b, new = await _second_pump(aiohttp_server)
    result = await _reconfigure(hass, entry, new)
    assert result["reason"] == "reconfigure_successful"
    assert entry.data["host"] == new


async def test_reconfigure_duplicate_check_normalises_host(loaded):
    hass, entry, _pump = loaded
    MockConfigEntry(
        domain=DOMAIN, unique_id="192.0.2.10",
        data={"host": "192.0.2.10", "username": "test", "password": "test-only"},
    ).add_to_hass(hass)
    old_host = entry.data["host"]
    result = await _reconfigure(hass, entry, "http://192.0.2.10/")
    assert result["errors"] == {"base": "already_configured"}
    assert entry.data["host"] == old_host


async def test_reconfigure_timeout_keeps_old_host(loaded, aiohttp_server, monkeypatch):
    hass, entry, _pump = loaded
    release = asyncio.Event()

    async def hang(request):
        await release.wait()
        raise web.HTTPServiceUnavailable()

    app = web.Application()
    app.router.add_get("/{endpoint}", hang)
    server = await aiohttp_server(app, host="127.0.0.1")
    monkeypatch.setattr("custom_components.econet_grant.api.API_TIMEOUT", 0.1)
    monkeypatch.setattr("custom_components.econet_grant.api.API_MAX_RETRIES", 2)
    old_host = entry.data["host"]
    try:
        result = await _reconfigure(hass, entry, str(server.make_url("")))
    finally:
        release.set()
    assert result["type"] == "form"
    assert result["errors"] == {"base": "cannot_connect"}
    assert entry.data["host"] == old_host
    assert entry.unique_id == "synthetic-entry"


async def test_reconfigure_recovers_entry_stuck_in_setup_retry(
        real_hass, enable_custom_integrations, aiohttp_server, monkeypatch):
    """Wrong host at setup leaves no update listener; reconfigure must still reload."""
    hass = real_hass
    monkeypatch.setattr("custom_components.econet_grant.api.MIN_REQUEST_GAP", 0)
    assert await async_setup_component(hass, "persistent_notification", {})
    entry = MockConfigEntry(
        domain=DOMAIN, title="Synthetic heat pump", unique_id="synthetic-entry",
        data={"host": "http://127.0.0.1:9", "username": "test", "password": "test-only"},
        options={"safe_mode": True, "push_notifications": False},
    )
    entry.add_to_hass(hass)
    assert not await hass.config_entries.async_setup(entry.entry_id)
    assert entry.state is ConfigEntryState.SETUP_RETRY
    pump, new = await _second_pump(aiohttp_server)
    # No time advance: it must load now, not at HA's next back-off retry.
    result = await _reconfigure(hass, entry, new)
    assert result["reason"] == "reconfigure_successful"
    assert entry.state is ConfigEntryState.LOADED
    assert entry.data["host"] == new
    assert "regParams" in pump.requests


# --- Part A: credentials in Reconfigure, Re-authenticate -------------------

async def _reconfigure_with(hass, entry, user_input):
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": "reconfigure", "entry_id": entry.entry_id})
    result = await hass.config_entries.flow.async_configure(result["flow_id"], user_input)
    await hass.async_block_till_done()
    return result


async def test_reconfigure_changes_username_and_password(loaded, aiohttp_server, caplog):
    hass, entry, pump_a = loaded
    old_host = entry.data["host"]
    # Same host: pump A itself now demands the new login.
    pump_a.credentials = ("new-user", "new-pass")
    before = _registry_snapshot(hass, entry)
    result = await _reconfigure_with(
        hass, entry, {"host": old_host, "username": "new-user", "password": "new-pass"})
    assert result["type"] == "abort"
    assert result["reason"] == "reconfigure_successful"
    assert entry.data["username"] == "new-user"
    assert entry.data["password"] == "new-pass"
    assert entry.state is ConfigEntryState.LOADED
    assert _registry_snapshot(hass, entry) == before
    expected = "Basic " + base64.b64encode(b"new-user:new-pass").decode()
    assert expected in pump_a.auth_headers
    assert "new-pass" not in caplog.text


async def test_reconfigure_new_host_and_login(loaded, aiohttp_server):
    hass, entry, _pump = loaded
    pump_b, new = await _second_pump(aiohttp_server)
    pump_b.credentials = ("new-user", "new-pass")
    result = await _reconfigure_with(
        hass, entry, {"host": new, "username": "new-user", "password": "new-pass"})
    assert result["reason"] == "reconfigure_successful"
    expected = "Basic " + base64.b64encode(b"new-user:new-pass").decode()
    assert expected in pump_b.auth_headers
    assert entry.data["host"] == new and entry.state is ConfigEntryState.LOADED


async def test_reconfigure_blank_password_keeps_stored(loaded, aiohttp_server):
    hass, entry, _pump = loaded
    _pump_b, new = await _second_pump(aiohttp_server)
    result = await _reconfigure_with(hass, entry, {"host": new, "username": "test"})
    assert result["reason"] == "reconfigure_successful"
    assert entry.data["password"] == "test-only"
    _pump_c, other = await _second_pump(aiohttp_server)
    result = await _reconfigure_with(
        hass, entry, {"host": other, "username": "test", "password": ""})
    assert result["reason"] == "reconfigure_successful"
    assert entry.data["password"] == "test-only"


async def test_reconfigure_wrong_password_rejected(loaded, aiohttp_server):
    hass, entry, _pump = loaded
    pump_b, new = await _second_pump(aiohttp_server)
    pump_b.credentials = ("new-user", "new-pass")
    before = dict(entry.data)
    result = await _reconfigure_with(
        hass, entry, {"host": new, "username": "new-user", "password": "wrong"})
    assert result["type"] == "form"
    assert result["errors"] == {"base": "invalid_auth"}
    assert dict(entry.data) == before


async def test_reconfigure_form_never_prefills_password(loaded):
    hass, entry, _pump = loaded
    result = await _reconfigure(hass, entry, None)
    keys = {str(k): k for k in result["data_schema"].schema}
    assert keys["username"].description["suggested_value"] == "test"
    password = keys["password"]
    assert "suggested_value" not in (password.description or {})
    assert password.default is vol.UNDEFINED


async def _failed_setup_entry(hass, aiohttp_server, monkeypatch):
    monkeypatch.setattr("custom_components.econet_grant.api.MIN_REQUEST_GAP", 0)
    assert await async_setup_component(hass, "persistent_notification", {})
    pump, url = await _second_pump(aiohttp_server)
    pump.credentials = ("test", "new-pass")
    entry = MockConfigEntry(
        domain=DOMAIN, title="Synthetic heat pump", unique_id="synthetic-entry",
        data={"host": url, "username": "test", "password": "test-only"},
        options={"safe_mode": True, "push_notifications": False},
    )
    entry.add_to_hass(hass)
    assert not await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.SETUP_ERROR
    return entry, pump


def _reauth_flow(hass):
    flows = [f for f in hass.config_entries.flow.async_progress()
             if f["context"]["source"] == "reauth"]
    assert len(flows) == 1
    return flows[0]


async def test_reauth_reloads_failed_entry_when_nothing_changed(
        real_hass, enable_custom_integrations, aiohttp_server, monkeypatch):
    hass = real_hass
    monkeypatch.setattr("custom_components.econet_grant.api.MIN_REQUEST_GAP", 0)
    assert await async_setup_component(hass, "persistent_notification", {})
    pump, url = await _second_pump(aiohttp_server)
    pump.credentials = ("test", "other")
    # unique_id == host like a real entry, so re-applying the same login changes nothing.
    entry = MockConfigEntry(
        domain=DOMAIN, title="Synthetic heat pump", unique_id=url,
        data={"host": url, "username": "test", "password": "test-only"},
        options={"safe_mode": True, "push_notifications": False},
    )
    entry.add_to_hass(hass)
    assert not await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.SETUP_ERROR
    flow = _reauth_flow(hass)
    # The owner fixes the password on the controller side.
    pump.credentials = ("test", "test-only")
    result = await hass.config_entries.flow.async_configure(
        flow["flow_id"], {"username": "test", "password": "test-only"})
    await hass.async_block_till_done()
    assert result["reason"] == "reauth_successful"
    assert entry.state is ConfigEntryState.LOADED


async def test_reauth_from_failed_setup(
        real_hass, enable_custom_integrations, aiohttp_server, monkeypatch, caplog):
    hass = real_hass
    entry, _pump = await _failed_setup_entry(hass, aiohttp_server, monkeypatch)
    flow = _reauth_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        flow["flow_id"], {"username": "test", "password": "new-pass"})
    await hass.async_block_till_done()
    assert result["type"] == "abort"
    assert result["reason"] == "reauth_successful"
    assert entry.state is ConfigEntryState.LOADED
    assert entry.data["password"] == "new-pass"
    assert "new-pass" not in caplog.text


async def test_reauth_wrong_password_keeps_entry(
        real_hass, enable_custom_integrations, aiohttp_server, monkeypatch):
    hass = real_hass
    entry, _pump = await _failed_setup_entry(hass, aiohttp_server, monkeypatch)
    flow = _reauth_flow(hass)
    form = await hass.config_entries.flow.async_configure(flow["flow_id"], None)
    assert form["step_id"] == "reauth_confirm"
    assert form["description_placeholders"]["host"] == entry.data["host"]
    result = await hass.config_entries.flow.async_configure(
        flow["flow_id"], {"username": "test", "password": "wrong"})
    assert result["type"] == "form"
    assert result["errors"] == {"base": "invalid_auth"}
    assert entry.data["password"] == "test-only"
    assert entry.state is ConfigEntryState.SETUP_ERROR


# --- Part B: Repairs fix, Controller Address sensor -------------------------

ADDRESS_ENTITY = "sensor.grant_aerona_heat_pump_controller_address"


def _issues(hass):
    return {k: v for k, v in ir.async_get(hass).issues.items() if k[0] == DOMAIN}


async def _closed_port_entry(hass, monkeypatch):
    monkeypatch.setattr("custom_components.econet_grant.api.MIN_REQUEST_GAP", 0)
    assert await async_setup_component(hass, "persistent_notification", {})
    assert await async_setup_component(hass, "repairs", {})
    entry = MockConfigEntry(
        domain=DOMAIN, title="Synthetic heat pump", unique_id="synthetic-entry",
        data={"host": "http://127.0.0.1:9", "username": "test", "password": "test-only"},
        options={"safe_mode": True, "push_notifications": False},
    )
    entry.add_to_hass(hass)
    assert not await hass.config_entries.async_setup(entry.entry_id)
    assert entry.state is ConfigEntryState.SETUP_RETRY
    return entry


async def test_no_repair_issue_on_short_outage(
        real_hass, enable_custom_integrations, monkeypatch):
    await _closed_port_entry(real_hass, monkeypatch)
    assert _issues(real_hass) == {}


async def test_repair_issue_after_threshold(
        real_hass, enable_custom_integrations, monkeypatch):
    monkeypatch.setattr(repairs, "CONNECTION_ISSUE_AFTER", timedelta(0))
    entry = await _closed_port_entry(real_hass, monkeypatch)
    issue = ir.async_get(real_hass).async_get_issue(DOMAIN, f"cannot_connect_{entry.entry_id}")
    assert issue is not None and issue.is_fixable
    assert issue.translation_placeholders == {"host": "http://127.0.0.1:9"}
    assert "test-only" not in repr(issue.translation_placeholders) + repr(issue.data)
    assert issue.data == {"entry_id": entry.entry_id}


async def test_repair_fix_flow_repairs_connection(
        real_hass, enable_custom_integrations, aiohttp_server, monkeypatch):
    hass = real_hass
    monkeypatch.setattr(repairs, "CONNECTION_ISSUE_AFTER", timedelta(0))
    entry = await _closed_port_entry(hass, monkeypatch)
    iid = f"cannot_connect_{entry.entry_id}"
    _pump, url = await _second_pump(aiohttp_server)
    mgr = repairs_flow_manager(hass)
    form = await mgr.async_init(DOMAIN, data={"issue_id": iid})
    assert form["type"] == "form"
    keys = {str(k): k for k in form["data_schema"].schema}
    assert "suggested_value" not in (keys["password"].description or {})
    assert keys["password"].default is vol.UNDEFINED
    assert form["description_placeholders"]["host"] == "http://127.0.0.1:9"
    result = await mgr.async_configure(
        form["flow_id"], {"host": url, "username": "test", "password": ""})
    assert result["type"] == "create_entry"
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED
    assert entry.data["host"] == url
    assert entry.data["password"] == "test-only"
    assert _issues(hass) == {}


async def test_repair_fix_flow_errors_keep_issue(
        real_hass, enable_custom_integrations, monkeypatch):
    hass = real_hass
    monkeypatch.setattr(repairs, "CONNECTION_ISSUE_AFTER", timedelta(0))
    entry = await _closed_port_entry(hass, monkeypatch)
    iid = f"cannot_connect_{entry.entry_id}"
    mgr = repairs_flow_manager(hass)
    form = await mgr.async_init(DOMAIN, data={"issue_id": iid})
    result = await mgr.async_configure(
        form["flow_id"], {"host": "http://127.0.0.1:9", "username": "test"})
    assert result["type"] == "form"
    assert result["errors"] == {"base": "cannot_connect"}
    assert (DOMAIN, iid) in ir.async_get(hass).issues


async def test_repair_fix_flow_entry_removed(
        real_hass, enable_custom_integrations, monkeypatch):
    hass = real_hass
    monkeypatch.setattr(repairs, "CONNECTION_ISSUE_AFTER", timedelta(0))
    entry = await _closed_port_entry(hass, monkeypatch)
    iid = f"cannot_connect_{entry.entry_id}"
    mgr = repairs_flow_manager(hass)
    form = await mgr.async_init(DOMAIN, data={"issue_id": iid})
    await hass.config_entries.async_remove(entry.entry_id)
    await hass.async_block_till_done()
    result = await mgr.async_configure(
        form["flow_id"], {"host": "http://127.0.0.1:9", "username": "test"})
    assert result["type"] == "abort"
    assert result["reason"] == "entry_removed"


async def test_loaded_entry_losing_controller_raises_then_clears_issue(
        loaded, monkeypatch):
    hass, entry, pump = loaded
    assert await async_setup_component(hass, "repairs", {})
    monkeypatch.setattr(repairs, "CONNECTION_ISSUE_AFTER", timedelta(0))
    good = pump.reg["curr"]
    pump.reg["curr"] = {}  # regParams now unusable -> UpdateFailed
    await entry.runtime_data.fast_coordinator.async_refresh()
    assert (DOMAIN, f"cannot_connect_{entry.entry_id}") in ir.async_get(hass).issues
    pump.reg["curr"] = good
    await entry.runtime_data.fast_coordinator.async_refresh()
    assert _issues(hass) == {}


async def test_controller_address_sensor(loaded, aiohttp_server):
    hass, entry, _pump = loaded
    host = entry.data["host"].removeprefix("http://").rstrip("/")
    state = hass.states.get(ADDRESS_ENTITY)
    assert state.state == host
    assert "test-only" not in repr(state.attributes)
    _pump_b, new = await _second_pump(aiohttp_server)
    result = await _reconfigure_with(hass, entry, {"host": new, "username": "test"})
    assert result["reason"] == "reconfigure_successful"
    assert hass.states.get(ADDRESS_ENTITY).state == new.removeprefix("http://").rstrip("/")


async def test_removing_entry_removes_issue(
        real_hass, enable_custom_integrations, monkeypatch):
    hass = real_hass
    monkeypatch.setattr(repairs, "CONNECTION_ISSUE_AFTER", timedelta(0))
    entry = await _closed_port_entry(hass, monkeypatch)
    assert _issues(hass)
    await hass.config_entries.async_remove(entry.entry_id)
    await hass.async_block_till_done()
    assert _issues(hass) == {}


async def test_login_rejection_clears_stale_unreachable_issue(
        real_hass, enable_custom_integrations, aiohttp_server, monkeypatch):
    hass = real_hass
    monkeypatch.setattr(repairs, "CONNECTION_ISSUE_AFTER", timedelta(0))
    entry = await _closed_port_entry(hass, monkeypatch)
    assert (DOMAIN, f"cannot_connect_{entry.entry_id}") in ir.async_get(hass).issues
    pump, url = await _second_pump(aiohttp_server)
    pump.credentials = ("test", "different-pass")
    hass.config_entries.async_update_entry(entry, data={**entry.data, "host": url})
    await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert _issues(hass) == {}
    assert any(
        f["context"]["source"] == "reauth" for f in hass.config_entries.flow.async_progress()
    )


async def test_applying_connection_resets_outage_clock(loaded, aiohttp_server):
    hass, entry, _pump = loaded
    failures = hass.data.setdefault(f"{DOMAIN}_connection_failures", {})
    failures[entry.entry_id] = dt_util.utcnow() - timedelta(hours=3)
    _pump_b, new = await _second_pump(aiohttp_server)
    # Synchronous check: a later successful reload would clear it anyway.
    config_flow.async_apply_connection(hass, entry, new, "test", "test")
    assert entry.entry_id not in hass.data.get(f"{DOMAIN}_connection_failures", {})
    await hass.async_block_till_done()


async def test_issue_raised_only_at_threshold(real_hass, monkeypatch):
    hass = real_hass
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={"host": "http://127.0.0.1:9", "username": "t", "password": "p"},
    )
    entry.add_to_hass(hass)
    start = dt_util.utcnow()
    now = [start]
    monkeypatch.setattr(repairs.dt_util, "utcnow", lambda: now[0])
    assert repairs.CONNECTION_ISSUE_AFTER == timedelta(minutes=10)
    key = (DOMAIN, f"cannot_connect_{entry.entry_id}")
    repairs.async_report_failure(hass, entry)
    now[0] = start + timedelta(minutes=9)
    repairs.async_report_failure(hass, entry)
    assert key not in ir.async_get(hass).issues
    now[0] = start + timedelta(minutes=10)
    repairs.async_report_failure(hass, entry)
    assert key in ir.async_get(hass).issues


async def _setup_with_lookup(real_hass, aiohttp_server, monkeypatch, lookup):
    pump = EconetEmulator()
    server = await aiohttp_server(pump.app, host="127.0.0.1")
    monkeypatch.setattr("custom_components.econet_grant.api.MIN_REQUEST_GAP", 0)
    monkeypatch.setattr("custom_components.econet_grant.discovery.async_lookup_mac", lookup)
    assert await async_setup_component(real_hass, "persistent_notification", {})
    entry = MockConfigEntry(
        domain=DOMAIN, title="Synthetic heat pump", unique_id="synthetic-entry",
        data={"host": str(server.make_url("")), "username": "test", "password": "test-only"},
        options={"safe_mode": True, "push_notifications": False},
    )
    entry.add_to_hass(real_hass)
    assert await real_hass.config_entries.async_setup(entry.entry_id)
    await real_hass.async_block_till_done()
    return entry, pump


def _pump_device(hass, entry):
    devices = dr.async_entries_for_config_entry(dr.async_get(hass), entry.entry_id)
    assert devices
    return devices[0]


def _mac_connections(device):
    return {c for c in device.connections if c[0] == dr.CONNECTION_NETWORK_MAC}


async def test_mac_registered_after_setup(
        real_hass, enable_custom_integrations, aiohttp_server, monkeypatch, caplog):
    async def lookup(hass, ip):
        return "aa:bb:cc:dd:ee:ff"

    entry, pump = await _setup_with_lookup(real_hass, aiohttp_server, monkeypatch, lookup)
    assert entry.state is ConfigEntryState.LOADED
    assert (dr.CONNECTION_NETWORK_MAC, "aa:bb:cc:dd:ee:ff") in _pump_device(
        real_hass, entry).connections
    assert "merge_connections" not in caplog.text  # deprecated; breaks in HA 2027.9
    assert pump.writes == []


async def test_no_mac_found_leaves_device_unchanged(
        real_hass, enable_custom_integrations, aiohttp_server, monkeypatch):
    async def lookup(hass, ip):
        return None

    entry, _ = await _setup_with_lookup(real_hass, aiohttp_server, monkeypatch, lookup)
    assert entry.state is ConfigEntryState.LOADED
    assert not _mac_connections(_pump_device(real_hass, entry))


async def test_lookup_failure_does_not_break_setup(
        real_hass, enable_custom_integrations, aiohttp_server, monkeypatch):
    async def lookup(hass, ip):
        raise RuntimeError("boom")

    entry, _ = await _setup_with_lookup(real_hass, aiohttp_server, monkeypatch, lookup)
    assert entry.state is ConfigEntryState.LOADED
    assert not _mac_connections(_pump_device(real_hass, entry))


async def test_manifest_declares_registered_devices_dhcp(real_hass, enable_custom_integrations):
    import json
    from pathlib import Path
    from homeassistant import loader

    manifest = json.loads(Path("custom_components/econet_grant/manifest.json").read_text())
    assert {"registered_devices": True} in manifest["dhcp"]
    assert manifest["version"] == "0.9.0"
    assert {"domain": "econet_grant", "registered_devices": True} in \
        await loader.async_get_dhcp(real_hass)


# --- DHCP flow: follow the controller to a new IP ---------------------------

MAC = "aa:bb:cc:dd:ee:ff"


async def _dhcp_setup(hass, aiohttp_server, monkeypatch, *, pump_a_up=True):
    """Pump A on 127.0.0.1:P, pump B on 127.0.0.2:P, entry pointing at A."""
    monkeypatch.setattr("custom_components.econet_grant.api.MIN_REQUEST_GAP", 0)

    async def no_lookup(hass, ip):
        return None

    monkeypatch.setattr("custom_components.econet_grant.discovery.async_lookup_mac", no_lookup)
    assert await async_setup_component(hass, "persistent_notification", {})
    pump_a, pump_b = EconetEmulator(), EconetEmulator()
    server_a = await aiohttp_server(pump_a.app, host="127.0.0.1")
    port = server_a.port
    await aiohttp_server(pump_b.app, host="127.0.0.2", port=port)
    if not pump_a_up:
        await server_a.close()
    entry = MockConfigEntry(
        domain=DOMAIN, title="Synthetic heat pump", unique_id="synthetic-entry",
        data={"host": f"http://127.0.0.1:{port}", "username": "test", "password": "test-only"},
        options={"safe_mode": True, "push_notifications": False},
    )
    entry.add_to_hass(hass)
    registry = dr.async_get(hass)
    if pump_a_up:
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        assert entry.state is ConfigEntryState.LOADED
        device = dr.async_entries_for_config_entry(registry, entry.entry_id)[0]
    else:
        assert not await hass.config_entries.async_setup(entry.entry_id)
        assert entry.state is ConfigEntryState.SETUP_RETRY
        # Setup never got far enough to create the device; add the one it would have.
        device = registry.async_get_or_create(
            config_entry_id=entry.entry_id, identifiers={(DOMAIN, pump_b.sys["uid"])})
    registry.async_update_device(
        device.id, new_connections=device.connections | {(dr.CONNECTION_NETWORK_MAC, MAC)})
    return entry, pump_a, pump_b, port


async def _dhcp(hass, ip, mac="aabbccddeeff"):
    from homeassistant import config_entries
    from homeassistant.helpers.service_info.dhcp import DhcpServiceInfo

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_DHCP},
        data=DhcpServiceInfo(ip=ip, hostname="", macaddress=mac))
    await hass.async_block_till_done()
    return result


@pytest.fixture
def dhcp_env(real_hass, enable_custom_integrations, aiohttp_server, monkeypatch,
             two_loopback_sockets):
    async def build(**kwargs):
        return (real_hass, *await _dhcp_setup(real_hass, aiohttp_server, monkeypatch, **kwargs))
    return build


async def test_dhcp_moves_entry_to_new_ip(dhcp_env):
    hass, entry, pump_a, pump_b, port = await dhcp_env()
    pump_a.unavailable = True  # the old address has stopped answering
    before = _registry_snapshot(hass, entry)
    result = await _dhcp(hass, "127.0.0.2")
    assert result["type"] == "abort"
    assert result["reason"] == "address_updated"
    assert entry.data["host"] == f"http://127.0.0.2:{port}"
    assert entry.data["username"] == "test"
    assert entry.data["password"] == "test-only"
    assert entry.unique_id == entry.data["host"]
    assert entry.state is ConfigEntryState.LOADED
    assert "regParams" in pump_b.requests
    assert _registry_snapshot(hass, entry) == before
    notice = hass.data["persistent_notification"][f"econet_grant_address_changed_{entry.entry_id}"]
    assert "127.0.0.1" in notice["message"] and "127.0.0.2" in notice["message"]
    assert "test-only" not in notice["message"]
    assert pump_a.writes == [] and pump_b.writes == []


async def test_dhcp_refuses_different_controller(dhcp_env):
    hass, entry, pump_a, pump_b, port = await dhcp_env()
    pump_a.unavailable = True
    pump_b.sys = {**pump_b.sys, "uid": "some-other-device"}
    result = await _dhcp(hass, "127.0.0.2")
    assert result["reason"] == "wrong_device"
    assert entry.data["host"] == f"http://127.0.0.1:{port}"


async def test_dhcp_refuses_unknown_device_id(dhcp_env):
    hass, entry, pump_a, _b, port = await dhcp_env()
    pump_a.unavailable = True
    registry = dr.async_get(hass)
    for device in dr.async_entries_for_config_entry(registry, entry.entry_id):
        registry.async_update_device(
            device.id, new_identifiers={(DOMAIN, entry.data["host"].rstrip("/"))})
    result = await _dhcp(hass, "127.0.0.2")
    assert result["reason"] == "wrong_device"
    assert entry.data["host"] == f"http://127.0.0.1:{port}"


async def test_dhcp_wrong_login_at_new_ip(dhcp_env):
    hass, entry, pump_a, pump_b, port = await dhcp_env()
    pump_a.unavailable = True
    pump_b.credentials = ("test", "something-else")
    result = await _dhcp(hass, "127.0.0.2")
    assert result["reason"] == "invalid_auth"
    assert entry.data["host"] == f"http://127.0.0.1:{port}"
    assert f"econet_grant_address_changed_{entry.entry_id}" not in \
        hass.data.get("persistent_notification", {})


async def test_dhcp_same_address_does_not_reload(dhcp_env):
    hass, entry, pump_a, pump_b, _port = await dhcp_env()
    count = len(pump_a.requests)
    result = await _dhcp(hass, "127.0.0.1")
    assert result["reason"] == "already_configured"
    assert len(pump_a.requests) == count
    assert pump_b.requests == []


async def test_dhcp_ignored_while_old_address_still_answers(dhcp_env):
    hass, entry, _a, pump_b, port = await dhcp_env()
    result = await _dhcp(hass, "127.0.0.2")
    assert result["reason"] == "already_configured"
    assert entry.data["host"] == f"http://127.0.0.1:{port}"
    assert f"econet_grant_address_changed_{entry.entry_id}" not in \
        hass.data.get("persistent_notification", {})
    assert pump_b.requests == []  # the login was never sent to the new address


async def test_dhcp_ignored_while_old_address_rejects_login(dhcp_env):
    """A controller that still answers (even with 401) has not moved."""
    hass, entry, pump_a, pump_b, port = await dhcp_env()
    pump_a.auth_fail = True
    result = await _dhcp(hass, "127.0.0.2")
    assert result["reason"] == "already_configured"
    assert entry.data["host"] == f"http://127.0.0.1:{port}"
    assert pump_b.requests == []  # the login was never sent to the new address


async def test_dhcp_does_not_overwrite_dns_host(dhcp_env):
    hass, entry, *_ = await dhcp_env()
    hass.config_entries.async_update_entry(
        entry, data={**entry.data, "host": "http://econet.invalid"})
    result = await _dhcp(hass, "127.0.0.2")
    assert result["reason"] == "not_ip_host"
    assert entry.data["host"] == "http://econet.invalid"


async def test_lookup_mac_uses_dhcp_data_before_arp(real_hass, monkeypatch):
    from homeassistant.helpers.service_info.dhcp import DhcpServiceInfo

    from custom_components.econet_grant import discovery

    dhcp = _import_dhcp_component(monkeypatch)
    monkeypatch.setattr(dhcp, "async_discovered_service_info", lambda hass: [
        DhcpServiceInfo(ip="192.0.2.7", hostname="", macaddress="aabbccddeeff")])
    monkeypatch.setattr(discovery, "ARP_TABLE_PATH", "/nonexistent/arp")
    assert await discovery.async_lookup_mac(real_hass, "192.0.2.7") == "aa:bb:cc:dd:ee:ff"


async def test_dhcp_unknown_mac(dhcp_env):
    hass, *_ = await dhcp_env()
    result = await _dhcp(hass, "127.0.0.2", mac="112233445566")
    assert result["reason"] == "not_econet_device"


async def test_dhcp_recovers_failed_entry(dhcp_env):
    hass, entry, _a, pump_b, port = await dhcp_env(pump_a_up=False)
    result = await _dhcp(hass, "127.0.0.2")
    assert result["reason"] == "address_updated"
    assert entry.state is ConfigEntryState.LOADED
    assert entry.data["host"] == f"http://127.0.0.2:{port}"
    assert "regParams" in pump_b.requests


async def test_dhcp_duplicate_reports_are_harmless(dhcp_env):
    hass, entry, pump_a, pump_b, _port = await dhcp_env()
    pump_a.unavailable = True
    first = await _dhcp(hass, "127.0.0.2")
    count = len(pump_b.requests)
    second = await _dhcp(hass, "127.0.0.2")
    assert first["reason"] == "address_updated"
    assert second["reason"] == "already_configured"
    assert len(pump_b.requests) == count
    assert entry.state is ConfigEntryState.LOADED


def _import_dhcp_component(monkeypatch):
    """Import HA's dhcp component, stubbing raw-socket helpers the test venv lacks."""
    import sys
    from unittest.mock import MagicMock

    # The watcher is never started here, so stubs are enough.
    for name in ("aiodhcpwatcher", "aiodiscover", "aiodiscover.discovery"):
        try:
            __import__(name)
        except ImportError:  # the stub must also cover the submodule
            monkeypatch.setitem(sys.modules, name, MagicMock())
    try:
        __import__("cached_ipaddress")
    except ImportError:
        import ipaddress
        import types

        def cached_ip_addresses(address):
            try:
                return ipaddress.ip_address(address)
            except ValueError:
                return None

        monkeypatch.setitem(sys.modules, "cached_ipaddress", types.SimpleNamespace(
            cached_ip_addresses=cached_ip_addresses))
    from homeassistant.components import dhcp

    return dhcp


async def test_real_dhcp_watcher_starts_our_flow(dhcp_env, monkeypatch):
    from homeassistant import config_entries, loader

    dhcp = _import_dhcp_component(monkeypatch)
    from homeassistant.components.dhcp.models import DHCPData

    hass, entry, *_ = await dhcp_env()
    matchers = dhcp.async_index_integration_matchers(await loader.async_get_dhcp(hass))
    watcher = dhcp.WatcherBase(hass, DHCPData(integration_matchers=matchers))
    calls = []
    monkeypatch.setattr(
        "homeassistant.components.dhcp.discovery_flow.async_create_flow",
        lambda hass, domain, context, data, **kw: calls.append((domain, context, data)))
    watcher.async_process_client("192.0.2.50", "", "aabbccddeeff")
    assert len(calls) == 1
    domain, context, data = calls[0]
    assert domain == DOMAIN
    assert context["source"] == config_entries.SOURCE_DHCP
    assert data.ip == "192.0.2.50"
