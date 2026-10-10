"""Real HA config-entry/platform lifecycle against a loopback heat pump."""
from datetime import timedelta

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.econet_grant.const import DOMAIN, SERVICE_COORDINATOR, SERVICE_SLOW_COORDINATOR
from emulator import EconetEmulator

pytestmark = [pytest.mark.enable_socket, pytest.mark.allow_hosts(["127.0.0.1"])]


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
    assert pump.writes == []
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.NOT_LOADED
    assert entry.entry_id not in hass.data[DOMAIN]
    # HA retains registry entries as restored/unavailable after platform unload.
    for entity in entities:
        state = hass.states.get(entity.entity_id)
        assert state.state == "unavailable"
        assert state.attributes["restored"] is True


async def test_options_flow_reloads_poll_interval(loaded):
    hass, entry, pump = loaded
    old = hass.data[DOMAIN][entry.entry_id][SERVICE_SLOW_COORDINATOR]
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] == "form"
    result = await hass.config_entries.options.async_configure(result["flow_id"], {
        "safe_mode": True, "push_notifications": False, "slow_poll_interval": 30,
    })
    assert result["type"] == "create_entry"
    await hass.async_block_till_done()
    assert entry.options["slow_poll_interval"] == 30
    current = hass.data[DOMAIN][entry.entry_id][SERVICE_SLOW_COORDINATOR]
    assert current is not old
    assert current.update_interval == timedelta(minutes=30)
    assert entry.state is ConfigEntryState.LOADED
    assert pump.writes == []


async def test_guest_version_change_creates_notification(loaded):
    hass, entry, pump = loaded
    assert "econet_grant_external_changes" not in hass.data.get("persistent_notification", {})
    before = pump.requests.count("editParams")
    pump.guest_change("Circuit1ComfortTemp", 22)
    await hass.data[DOMAIN][entry.entry_id][SERVICE_COORDINATOR].async_refresh()
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
    await hass.data[DOMAIN][entry.entry_id][SERVICE_COORDINATOR].async_refresh()
    await hass.async_block_till_done()
    # Selects subscribe to the fast coordinator and read the slow snapshot.
    await hass.data[DOMAIN][entry.entry_id][SERVICE_COORDINATOR].async_refresh()
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
