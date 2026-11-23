"""Season thresholds: ranges match what the live controller accepts at this site.

The site runs Winter with both thresholds at 20 °C. The controller pins
Summer's minimum to the Winter value and Winter's maximum to the Summer value,
so 20/20 must be settable (and, later, protectable) from Home Assistant.
"""
import pytest
from homeassistant.exceptions import ServiceValidationError

from custom_components.econet_grant.const import NUMBER_DEFINITIONS
from test_ha_integration import hass, hass_config_dir, loaded, notifications  # noqa: F401

pytestmark = pytest.mark.usefixtures("loopback_sockets")

SUMMER = "number.grant_aerona_heat_pump_summer_threshold"
WINTER = "number.grant_aerona_heat_pump_winter_threshold"


def test_threshold_definition_ranges():
    assert (NUMBER_DEFINITIONS["SummerOn"]["min_value"],
            NUMBER_DEFINITIONS["SummerOn"]["max_value"]) == (20, 30)
    assert (NUMBER_DEFINITIONS["SummerOff"]["min_value"],
            NUMBER_DEFINITIONS["SummerOff"]["max_value"]) == (0, 20)


async def test_thresholds_at_20_are_settable_and_summer_19_is_refused(loaded):  # noqa: F811
    hass, entry, pump = loaded
    pump.edit["data"]["702"] = {"name": "SummerOn", "value": 20, "minv": 20, "maxv": 30,
                                "edit": True}
    pump.edit["data"]["703"] = {"name": "SummerOff", "value": 19, "minv": 0, "maxv": 20,
                                "edit": True}
    hass.config_entries.async_update_entry(entry, options={**entry.options, "safe_mode": False})
    await hass.async_block_till_done()
    assert hass.states.get(WINTER).attributes["max"] == 20
    assert hass.states.get(SUMMER).attributes["min"] == 20
    await hass.services.async_call("number", "set_value", {"entity_id": WINTER, "value": 20},
                                   blocking=True)
    assert pump.writes == [("SummerOff", 20.0)]
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call("number", "set_value",
                                       {"entity_id": SUMMER, "value": 19}, blocking=True)
    assert pump.writes == [("SummerOff", 20.0)]
