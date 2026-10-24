"""Button platform for EcoNet Grant Aerona (restore settings)."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .api import EconetApi
from .const import DOMAIN, SERVICE_RESTORE_SETTINGS
from .entity import EconetConfigEntry, device_info


async def async_setup_entry(
    hass: HomeAssistant,
    entry: EconetConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up button entities from a config entry."""
    async_add_entities([RestoreSettingsButton(entry.runtime_data.api)])


class RestoreSettingsButton(ButtonEntity):
    """Restore the 'Default' snapshot (a preview only while Safe Mode is on)."""

    _attr_has_entity_name = True
    _attr_name = "Restore Default Settings"
    _attr_icon = "mdi:backup-restore"

    def __init__(self, api: EconetApi) -> None:
        self._api = api
        self._attr_unique_id = f"{DOMAIN}_{api.uid}_restore_settings"

    @property
    def device_info(self) -> DeviceInfo:
        return device_info(self._api)

    async def async_press(self) -> None:
        await self.hass.services.async_call(
            DOMAIN, SERVICE_RESTORE_SETTINGS, {"snapshot_name": "Default"}, blocking=True,
        )
