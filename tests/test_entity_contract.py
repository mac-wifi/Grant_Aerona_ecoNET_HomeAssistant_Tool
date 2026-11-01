"""Entity contract: IDs, names and metadata that production dashboards rely on.

Entity IDs are derived from display names, so an innocent-looking rename can
break the owner's dashboards, Grafana queries and history. This test pins the
complete registry/state surface against ``fixtures/entity_contract.json``.

Regenerate deliberately (and review the diff) with:
    ECONET_UPDATE_CONTRACT=1 python -m pytest tests/test_entity_contract.py
"""
import json
import os
from pathlib import Path

import pytest
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er

from test_ha_integration import hass, hass_config_dir, loaded, notifications  # noqa: F401

pytestmark = pytest.mark.usefixtures("loopback_sockets")

CONTRACT = Path(__file__).parent / "fixtures" / "entity_contract.json"
# States derived from wall-clock time, the local file system or the release version.
UNPINNED_STATES = ("_last_reading", "_last_settings_check", "_database_size",
                   "_last_default_snapshot", "_integration_version")


def _describe(hass, entry):
    registry = er.async_get(hass)
    entities = {}
    for item in sorted(er.async_entries_for_config_entry(registry, entry.entry_id),
                       key=lambda e: e.entity_id):
        state = hass.states.get(item.entity_id)
        attributes = {key: value for key, value in state.attributes.items()
                      if key not in ("friendly_name",)}
        record = {
            "unique_id": item.unique_id,
            "original_name": item.original_name,
            "entity_category": item.entity_category,
            "original_icon": item.original_icon,
            "unit": item.unit_of_measurement,
            "original_device_class": item.original_device_class,
            "friendly_name": state.attributes.get("friendly_name"),
            "attributes": json.loads(json.dumps(attributes, default=str)),
        }
        if not item.unique_id.endswith(UNPINNED_STATES):
            record["state"] = state.state
        entities[item.entity_id] = record
    devices = [
        {"identifiers": sorted(list(i) for i in device.identifiers), "name": device.name,
         "manufacturer": device.manufacturer, "model": device.model,
         "sw_version": device.sw_version}
        for device in dr.async_entries_for_config_entry(dr.async_get(hass), entry.entry_id)
    ]
    return {"devices": devices, "entities": entities,
            "services": sorted(hass.services.async_services().get("econet_grant", {}))}


async def test_entity_contract_is_unchanged(loaded):  # noqa: F811
    hass, entry, pump = loaded
    actual = json.loads(json.dumps(_describe(hass, entry), default=str))
    if os.environ.get("ECONET_UPDATE_CONTRACT"):
        CONTRACT.write_text(json.dumps(actual, indent=2, sort_keys=True) + "\n")
    expected = json.loads(CONTRACT.read_text())
    assert actual == expected
    assert pump.writes == []
