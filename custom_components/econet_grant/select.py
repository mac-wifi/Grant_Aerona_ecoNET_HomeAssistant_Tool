"""Select platform for EcoNet Grant Aerona (mode selectors)."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.select import SelectEntity
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
    SELECT_DEFINITIONS,
    SERVICE_API,
    SERVICE_COORDINATOR,
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
    """Set up select entities from a config entry."""
    data = hass.data[DOMAIN][entry.entry_id]
    fast_coordinator: EconetFastCoordinator = data[SERVICE_COORDINATOR]
    slow_coordinator: EconetSlowCoordinator = data[SERVICE_SLOW_COORDINATOR]
    api: EconetApi = data[SERVICE_API]

    entities: list[EconetSelect] = []
    for key, defn in SELECT_DEFINITIONS.items():
        entities.append(
            EconetSelect(fast_coordinator, slow_coordinator, api, entry, key, defn)
        )

    async_add_entities(entities)
    _LOGGER.info("Created %d select entities", len(entities))


class EconetSelect(CoordinatorEntity[EconetFastCoordinator], SelectEntity):
    """A select entity for an ecoNET mode parameter."""

    _attr_has_entity_name = True

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

        self._value_to_label: dict[int, str] = defn["options"]
        self._label_to_value: dict[str, int] = {v: k for k, v in defn["options"].items()}

        self._attr_unique_id = f"{DOMAIN}_{api.uid}_{key}"
        self._attr_name = defn["name"]
        self._attr_options = list(self._value_to_label.values())

        edit_params = (
            slow_coordinator.data.get("editParams", {})
            if slow_coordinator.data
            else {}
        )
        param_data = edit_params.get("data", {}).get(self._param_index, {})
        raw_value = param_data.get("value") if param_data else None
        if raw_value is not None:
            int_value = int(raw_value)
            self._attr_current_option = self._value_to_label.get(
                int_value, f"Unknown ({int_value})"
            )
        else:
            self._attr_current_option: str | None = None

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
            raw_value = param_data.get("value")
            if raw_value is not None:
                int_value = int(raw_value)
                self._attr_current_option = self._value_to_label.get(
                    int_value, f"Unknown ({int_value})"
                )
        self.async_write_ha_state()

    def _get_change_detector(self):
        """Get the change detector from hass.data."""
        entry_data = self.hass.data.get(DOMAIN, {}).get(self._entry.entry_id, {})
        return entry_data.get(SERVICE_CHANGE_DETECTOR)

    async def async_select_option(self, option: str) -> None:
        """Write a new mode to the ecoNET device."""
        api_value = self._label_to_value.get(option)
        if api_value is None:
            _LOGGER.error("Unknown option '%s' for %s", option, self._key)
            return

        if self._safe_mode:
            await _safe_mode_notify(self.hass, self._key, self._param_index, option, api_value)
            return

        change_detector = self._get_change_detector()
        if change_detector:
            change_detector.mark_self_write(self._key)

        success = await self._api.set_param_by_index(self._param_index, api_value)
        if success:
            self._attr_current_option = option
            self.async_write_ha_state()
            _LOGGER.info("Set %s to %s (value=%d)", self._key, option, api_value)
        else:
            _LOGGER.error("Failed to set %s to %s (value=%d)", self._key, option, api_value)
            if change_detector:
                change_detector.clear_self_write(self._key)


async def _safe_mode_notify(
    hass: HomeAssistant,
    key: str,
    param_index: str,
    option: str,
    api_value: int,
) -> None:
    """Show a persistent notification instead of writing in safe mode."""
    notification_id = f"{DOMAIN}_write_{key}_{api_value}"
    message = (
        f"**EcoNet Grant**: Pending write request\n\n"
        f"Parameter: **{key}**\n"
        f"New mode: **{option}** (API value: {api_value})\n"
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
        "Safe mode: blocked write of %s = %s (index %s, value %d). "
        "Created persistent notification %s",
        key, option, param_index, api_value, notification_id,
    )
