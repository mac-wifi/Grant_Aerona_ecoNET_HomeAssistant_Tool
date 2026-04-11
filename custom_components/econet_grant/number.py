"""Number platform for EcoNet Grant Aerona (writable temperature setpoints)."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .api import EconetApi
from .const import (
    CONF_SAFE_MODE,
    DEFAULT_SAFE_MODE,
    DEVICE_MANUFACTURER,
    DEVICE_MODEL,
    DOMAIN,
    NUMBER_DEFINITIONS,
    SERVICE_API,
    SERVICE_COORDINATOR,
    SERVICE_DATABASE,
    SERVICE_SLOW_COORDINATOR,
)
from .coordinator import EconetFastCoordinator, EconetSlowCoordinator

_LOGGER = logging.getLogger(__name__)

SERVICE_CHANGE_DETECTOR = "change_detector"


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up number entities from a config entry."""
    data = hass.data[DOMAIN][entry.entry_id]
    fast_coordinator: EconetFastCoordinator = data[SERVICE_COORDINATOR]
    slow_coordinator: EconetSlowCoordinator = data[SERVICE_SLOW_COORDINATOR]
    api: EconetApi = data[SERVICE_API]

    entities: list[EconetNumber] = []
    for key, defn in NUMBER_DEFINITIONS.items():
        entities.append(
            EconetNumber(fast_coordinator, slow_coordinator, api, entry, key, defn)
        )

    async_add_entities(entities)
    _LOGGER.info("Created %d number entities", len(entities))


class EconetNumber(CoordinatorEntity[EconetFastCoordinator], NumberEntity):
    """A writable number entity for an ecoNET temperature setpoint."""

    _attr_has_entity_name = True
    _attr_mode = NumberMode.BOX

    def __init__(
        self,
        fast_coordinator: EconetFastCoordinator,
        slow_coordinator: EconetSlowCoordinator,
        api: EconetApi,
        entry: ConfigEntry,
        key: str,
        defn: dict[str, Any],
    ) -> None:
        super().__init__(fast_coordinator)
        self._slow_coordinator = slow_coordinator
        self._api = api
        self._entry = entry
        self._key = key
        self._param_index = defn["param_index"]

        self._attr_unique_id = f"{DOMAIN}_{api.uid}_{key}"
        self._attr_name = defn["name"]
        self._attr_native_min_value = defn["min_value"]
        self._attr_native_max_value = defn["max_value"]
        self._attr_native_step = defn["step"]
        self._attr_native_unit_of_measurement = defn["unit"]

        edit_params = (
            slow_coordinator.data.get("editParams", {})
            if slow_coordinator.data
            else {}
        )
        param_data = edit_params.get("data", {}).get(self._param_index, {})
        if param_data:
            self._attr_native_value = param_data.get("value")

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, self._api.uid or self._api.host)},
            name="Grant Aerona Heat Pump",
            manufacturer=DEVICE_MANUFACTURER,
            model=DEVICE_MODEL,
            sw_version=self._api.sw_version,
        )

    @property
    def _safe_mode(self) -> bool:
        return self._entry.options.get(CONF_SAFE_MODE, DEFAULT_SAFE_MODE)

    @callback
    def _handle_coordinator_update(self) -> None:
        """Read current value from the slow coordinator's editParams.data."""
        edit_params = (
            self._slow_coordinator.data.get("editParams", {})
            if self._slow_coordinator.data
            else {}
        )
        param_data = edit_params.get("data", {}).get(self._param_index, {})
        if param_data:
            self._attr_native_value = param_data.get("value")
        self.async_write_ha_state()

    def _get_change_detector(self):
        """Get the change detector from hass.data."""
        entry_data = self.hass.data.get(DOMAIN, {}).get(self._entry.entry_id, {})
        return entry_data.get(SERVICE_CHANGE_DETECTOR)

    def _get_database(self):
        """Get the database from hass.data."""
        entry_data = self.hass.data.get(DOMAIN, {}).get(self._entry.entry_id, {})
        return entry_data.get(SERVICE_DATABASE)

    async def async_set_native_value(self, value: float) -> None:
        """Write a new value to the ecoNET device."""
        if self._safe_mode:
            await _safe_mode_queue(self.hass, self._api, self._key, self._param_index, value)
            return

        old_value = self._attr_native_value
        change_detector = self._get_change_detector()
        if change_detector:
            change_detector.mark_self_write(self._key)

        success = await self._api.set_param_by_index(self._param_index, value)
        if success:
            self._attr_native_value = value
            self.async_write_ha_state()
            _LOGGER.info("Set %s to %s", self._key, value)
            db = self._get_database()
            if db:
                await db.async_log_change(
                    self.hass,
                    {
                        "name": self._key,
                        "index": self._param_index,
                        "old_value": old_value,
                        "new_value": value,
                    },
                    source="user",
                )
        else:
            _LOGGER.error("Failed to set %s to %s", self._key, value)
            if change_detector:
                change_detector.clear_self_write(self._key)


async def _safe_mode_queue(
    hass: HomeAssistant,
    api: EconetApi,
    key: str,
    param_index: str,
    value: float,
) -> None:
    """Queue a write for manual approval via persistent notification."""
    notification_id = f"{DOMAIN}_write_{key}_{value}"
    message = (
        f"**EcoNet Grant**: Pending write request\n\n"
        f"Parameter: **{key}**\n"
        f"New value: **{value}**\n"
        f"Param index: {param_index}\n\n"
        f"Safe mode is ON. To execute this write, disable safe mode in "
        f"the integration options and set the value again."
    )
    hass.components.persistent_notification.async_create(
        message=message,
        title="EcoNet Grant - Write Pending",
        notification_id=notification_id,
    )
    _LOGGER.warning(
        "Safe mode: blocked write of %s = %s (index %s). "
        "Created persistent notification %s",
        key, value, param_index, notification_id,
    )
