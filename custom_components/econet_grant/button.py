"""Button platform for EcoNet Grant Aerona (restore settings)."""

from __future__ import annotations

import logging

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .api import EconetApi
from .const import (
    DEVICE_MANUFACTURER,
    DEVICE_MODEL,
    DOMAIN,
    SERVICE_API,
)

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up button entities from a config entry."""
    data = hass.data[DOMAIN][entry.entry_id]
    api: EconetApi = data[SERVICE_API]
    async_add_entities([RestoreSettingsButton(api, entry)])


class RestoreSettingsButton(ButtonEntity):
    """Button that triggers the restore_settings service."""

    _attr_has_entity_name = True
    _attr_name = "Restore Default Settings"
    _attr_icon = "mdi:backup-restore"

    def __init__(self, api: EconetApi, entry: ConfigEntry) -> None:
        self._api = api
        self._entry = entry
        self._attr_unique_id = f"{DOMAIN}_{api.uid}_restore_settings"

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, self._api.uid or self._api.host)},
            name="Grant Aerona Heat Pump",
            manufacturer=DEVICE_MANUFACTURER,
            model=DEVICE_MODEL,
            sw_version=self._api.sw_version,
        )

    async def async_press(self) -> None:
        """Trigger the settings restore service."""
        await self.hass.services.async_call(
            DOMAIN,
            "restore_settings",
            {"entry_id": self._entry.entry_id},
        )
