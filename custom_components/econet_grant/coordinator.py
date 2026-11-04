"""Data update coordinators for EcoNet Grant Aerona.

Fast: regParams (live readings and settings version counters), every 5 min.
Slow: editParams + sysParams (settings), at the configured fallback interval,
plus an immediate refresh whenever a version counter changes.
"""

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
from .const import (
    CONF_SLOW_POLL_INTERVAL,
    COORDINATOR_TIMEOUT,
    DEFAULT_SLOW_POLL_MINUTES,
    DOMAIN,
    FAST_POLL_INTERVAL,
)
from .repairs import async_report_failure, async_report_success

_LOGGER = logging.getLogger(__name__)


class _EconetCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Shared timeout and error mapping; subclasses implement ``_async_fetch``."""

    label = ""

    def __init__(
        self,
        hass: HomeAssistant,
        api: EconetApi,
        entry: ConfigEntry,
        name: str,
        update_interval: timedelta,
    ) -> None:
        super().__init__(
            hass, _LOGGER, config_entry=entry,
            name=f"{DOMAIN}_{name}", update_interval=update_interval,
        )
        self.api = api
        self._entry = entry

    async def _async_fetch(self) -> dict[str, Any]:
        raise NotImplementedError

    async def _async_update_data(self) -> dict[str, Any]:
        try:
            async with asyncio.timeout(COORDINATOR_TIMEOUT):
                return await self._async_fetch()
        except AuthError as err:
            raise ConfigEntryAuthFailed from err
        except UpdateFailed:
            raise
        except Exception as err:  # includes TimeoutError
            raise UpdateFailed(f"Error fetching {self.label}: {err}") from err


class EconetFastCoordinator(_EconetCoordinator):
    """Polls regParams every 5 minutes for live temperature/performance data."""

    label = "regParams"

    def __init__(self, hass: HomeAssistant, api: EconetApi, entry: ConfigEntry) -> None:
        super().__init__(
            hass, api, entry, "fast", timedelta(seconds=FAST_POLL_INTERVAL),
        )

    async def _async_update_data(self) -> dict[str, Any]:
        """Track outages for the Repairs issue (auth failures use HA's reauth)."""
        try:
            data = await super()._async_update_data()
        except ConfigEntryAuthFailed:
            # A login rejection still means the controller answered.
            async_report_success(self.hass, self._entry)
            raise
        except UpdateFailed:
            async_report_failure(self.hass, self._entry)
            raise
        async_report_success(self.hass, self._entry)
        return data

    async def _async_fetch(self) -> dict[str, Any]:
        reg_params = await self.api.fetch_reg_params()
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


class EconetSlowCoordinator(_EconetCoordinator):
    """Polls editParams and sysParams at the configured fallback interval."""

    label = "slow data"

    def __init__(self, hass: HomeAssistant, api: EconetApi, entry: ConfigEntry) -> None:
        minutes = entry.options.get(CONF_SLOW_POLL_INTERVAL, DEFAULT_SLOW_POLL_MINUTES)
        super().__init__(hass, api, entry, "slow", timedelta(minutes=minutes))

    async def _async_fetch(self) -> dict[str, Any]:
        edit_params, sys_params = await asyncio.gather(
            self.api.fetch_edit_params(),
            self.api.fetch_sys_params(),
        )
        if edit_params is None:
            raise UpdateFailed("editParams returned None")
        if sys_params is None:
            raise UpdateFailed("sysParams returned None")
        return {"editParams": edit_params, "sysParams": sys_params}
