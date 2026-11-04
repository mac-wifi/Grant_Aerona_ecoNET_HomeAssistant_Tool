"""Real HA config-entry/platform lifecycle against a loopback heat pump."""
import asyncio
from datetime import timedelta

import pytest
from aiohttp import web
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import MockConfigEntry

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
