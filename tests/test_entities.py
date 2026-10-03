"""Entity writes stay mocked; exercise production Safe Mode and bit operations."""
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from custom_components.econet_grant.const import (
    BITMASK_SELECT_DEFINITIONS, NUMBER_DEFINITIONS, SELECT_DEFINITIONS,
)
from custom_components.econet_grant.number import EconetNumber
from custom_components.econet_grant.select import EconetBitmaskSelect, EconetSelect


def make_entity(cls, key, definition, hass, entry, api, data):
    fast = SimpleNamespace(data={}, last_update_success=True)
    slow = SimpleNamespace(data={"editParams": {"data": data}})
    entity = cls(fast, slow, api, entry, key, definition)
    entity.hass = hass
    entity.async_write_ha_state = Mock()
    return entity


@pytest.mark.parametrize("kind", ["number", "select", "bitmask"])
async def test_safe_mode_blocks_all_entity_write_types(kind, hass, entry, api, notifications):
    detector = Mock()
    hass.data = {"econet_grant": {entry.entry_id: {"change_detector": detector}}}
    if kind == "number":
        key, definition = next(iter(NUMBER_DEFINITIONS.items()))
        entity = make_entity(EconetNumber, key, definition, hass, entry, api, {})
        await entity.async_set_native_value(21)
    elif kind == "select":
        key, definition = next(iter(SELECT_DEFINITIONS.items()))
        entity = make_entity(EconetSelect, key, definition, hass, entry, api, {})
        await entity.async_select_option(next(iter(definition["options"].values())))
    else:
        key = "HDWSpecifyPriority"
        definition = BITMASK_SELECT_DEFINITIONS[key]
        entity = make_entity(EconetBitmaskSelect, key, definition, hass, entry, api,
                             {definition["settings_param"]: {"value": 5}})
        await entity.async_select_option(definition["on_label"])
    api.set_param.assert_not_awaited()
    detector.mark_self_write.assert_not_called()
    entity.async_write_ha_state.assert_not_called()
    notifications.assert_called_once()
    assert "Safe mode is ON" in notifications.call_args.kwargs["message"]


@pytest.mark.parametrize("inverted, option, initial, expected", [
    (False, "Yes", 5, 21), (False, "No", 21, 5),
    (True, "Yes", 21, 5), (True, "No", 5, 21),
])
async def test_bitmask_preserves_unrelated_bits(
    inverted, option, initial, expected, hass, entry, api,
):
    entry.options["safe_mode"] = False
    definition = {**BITMASK_SELECT_DEFINITIONS["HDWSpecifyPriority"], "on_clears_bit": inverted}
    entity = make_entity(EconetBitmaskSelect, "HDWSpecifyPriority", definition,
                         hass, entry, api, {"101": {"value": initial}})
    assert entity.current_option == ("No" if option == "Yes" else "Yes")
    await entity.async_select_option(option)
    api.set_param.assert_awaited_once_with("HDWSETTINGS", expected)
    assert entity.current_option == option
    entity.async_write_ha_state.assert_called_once()


async def test_bitmask_missing_read_does_not_write(hass, entry, api):
    entry.options["safe_mode"] = False
    definition = BITMASK_SELECT_DEFINITIONS["HDWSpecifyPriority"]
    entity = make_entity(EconetBitmaskSelect, "HDWSpecifyPriority", definition,
                         hass, entry, api, {})
    assert entity.current_option is None
    await entity.async_select_option("Yes")
    api.set_param.assert_not_awaited()
