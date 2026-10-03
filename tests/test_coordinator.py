"""Real coordinators with mocked API; no device or running HA required."""
from datetime import timedelta

import pytest

from custom_components.econet_grant.coordinator import (
    EconetFastCoordinator, EconetSlowCoordinator,
)


@pytest.mark.parametrize("minutes", [None, 5, 60, 1440])
async def test_poll_intervals(hass, entry, api, minutes):
    if minutes is not None:
        entry.options["slow_poll_interval"] = minutes
    slow = EconetSlowCoordinator(hass, api, entry)
    fast = EconetFastCoordinator(hass, api, entry)
    assert slow.update_interval == timedelta(minutes=5 if minutes is None else minutes)
    assert fast.update_interval == timedelta(minutes=5)
    api.fetch_sys_params.return_value = {"remoteMenu": False}
    data = await slow._async_update_data()
    assert data["sysParams"] == {"remoteMenu": False}
    api.fetch_edit_params.assert_awaited_once()
    api.fetch_sys_params.assert_awaited_once()
    api.set_param.assert_not_awaited()
