"""Data update coordinators for EcoNet Grant Aerona."""

from __future__ import annotations

import asyncio
from datetime import timedelta
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import AuthError, EconetApi
from .const import DOMAIN, FAST_POLL_INTERVAL, SLOW_POLL_INTERVAL

_LOGGER = logging.getLogger(__name__)


class EconetFastCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Polls regParams every 5 minutes for live temperature/performance data."""

    def __init__(self, hass: HomeAssistant, api: EconetApi, entry: ConfigEntry) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}_fast",
            update_interval=timedelta(seconds=FAST_POLL_INTERVAL),
        )
        self.api = api
        self._entry = entry

    async def _async_update_data(self) -> dict[str, Any]:
        try:
            async with asyncio.timeout(30):
                reg_params = await self.api.fetch_reg_params()
        except AuthError as err:
            raise ConfigEntryAuthFailed from err
        except (asyncio.TimeoutError, Exception) as err:
            raise UpdateFailed(f"Error fetching regParams: {err}") from err

        if reg_params is None:
            raise UpdateFailed("regParams returned None")

        curr = reg_params.get("curr", {})
        if not curr:
            raise UpdateFailed("regParams.curr is empty")

        return {
            "curr": curr,
            "currUnits": reg_params.get("currUnits", {}),
            "settingsVer": reg_params.get("settingsVer"),
            "editableParamsVer": reg_params.get("editableParamsVer"),
            "schedulesVer": reg_params.get("schedulesVer"),
            "tilesParams": reg_params.get("tilesParams", []),
            "schemaParams": reg_params.get("schemaParams", {}),
        }


class EconetSlowCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Polls editParams and sysParams every 5 minutes for change detection."""

    def __init__(self, hass: HomeAssistant, api: EconetApi, entry: ConfigEntry) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}_slow",
            update_interval=timedelta(seconds=SLOW_POLL_INTERVAL),
        )
        self.api = api
        self._entry = entry

    async def _async_update_data(self) -> dict[str, Any]:
        try:
            async with asyncio.timeout(30):
                edit_params, sys_params = await asyncio.gather(
                    self.api.fetch_edit_params(),
                    self.api.fetch_sys_params(),
                )
        except AuthError as err:
            raise ConfigEntryAuthFailed from err
        except (asyncio.TimeoutError, Exception) as err:
            raise UpdateFailed(f"Error fetching slow data: {err}") from err

        if edit_params is None:
            raise UpdateFailed("editParams returned None")
        if sys_params is None:
            raise UpdateFailed("sysParams returned None")

        return {
            "editParams": edit_params,
            "sysParams": sys_params,
        }
