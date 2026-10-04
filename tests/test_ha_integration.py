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
