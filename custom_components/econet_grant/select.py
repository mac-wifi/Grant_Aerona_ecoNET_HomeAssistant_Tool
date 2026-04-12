"""Select platform for EcoNet Grant Aerona (mode selectors)."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.persistent_notification import async_create as pn_async_create
from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .api import EconetApi
from .const import (
    BITMASK_SELECT_DEFINITIONS,
    CONF_SAFE_MODE,
    DEFAULT_SAFE_MODE,
    DEVICE_MANUFACTURER,
    DEVICE_MODEL,
    DOMAIN,
    SELECT_DEFINITIONS,
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
    """Set up select entities from a config entry."""
    data = hass.data[DOMAIN][entry.entry_id]
    fast_coordinator: EconetFastCoordinator = data[SERVICE_COORDINATOR]
    slow_coordinator: EconetSlowCoordinator = data[SERVICE_SLOW_COORDINATOR]
    api: EconetApi = data[SERVICE_API]

    entities: list[SelectEntity] = []
    for key, defn in SELECT_DEFINITIONS.items():
        entities.append(
            EconetSelect(fast_coordinator, slow_coordinator, api, entry, key, defn)
        )
    for key, defn in BITMASK_SELECT_DEFINITIONS.items():
        entities.append(
            EconetBitmaskSelect(fast_coordinator, slow_coordinator, api, entry, key, defn)
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

    def _get_database(self):
        """Get the database from hass.data."""
        entry_data = self.hass.data.get(DOMAIN, {}).get(self._entry.entry_id, {})
        return entry_data.get(SERVICE_DATABASE)

    async def async_select_option(self, option: str) -> None:
        """Write a new mode to the ecoNET device."""
        api_value = self._label_to_value.get(option)
        if api_value is None:
            _LOGGER.error("Unknown option '%s' for %s", option, self._key)
            return

        if self._safe_mode:
            await _safe_mode_notify(self.hass, self._api, self._key, self._key, option, api_value)
            return

        old_option = self._attr_current_option
        change_detector = self._get_change_detector()
        if change_detector:
            change_detector.mark_self_write(self._key)

        success = await self._api.set_param(self._key, api_value)
        if success:
            self._attr_current_option = option
            self.async_write_ha_state()
            _LOGGER.info("Set %s to %s (value=%d)", self._key, option, api_value)
            db = self._get_database()
            if db:
                await db.async_log_change(
                    self.hass,
                    {
                        "name": self._key,
                        "index": self._param_index,
                        "old_value": old_option,
                        "new_value": option,
                    },
                    source="user",
                )
        else:
            _LOGGER.error("Failed to set %s to %s (value=%d)", self._key, option, api_value)
            if change_detector:
                change_detector.clear_self_write(self._key)


class EconetBitmaskSelect(CoordinatorEntity[EconetFastCoordinator], SelectEntity):
    """A select entity that toggles a single bit within a settings bitmask."""

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
        self._settings_param = defn["settings_param"]
        self._settings_param_name = defn["settings_param_name"]
        self._bit_mask = defn["bit_mask"]
        self._on_label = defn["on_label"]
        self._off_label = defn["off_label"]
        self._on_clears_bit = defn.get("on_clears_bit", False)

        self._attr_unique_id = f"{DOMAIN}_{api.uid}_{key}"
        self._attr_name = defn["name"]
        self._attr_options = [self._on_label, self._off_label]

        self._attr_current_option = self._read_current()

    def _read_current(self) -> str | None:
        edit_params = (
            self._slow_coordinator.data.get("editParams", {})
            if self._slow_coordinator.data
            else {}
        )
        param_data = edit_params.get("data", {}).get(self._settings_param, {})
        raw_value = param_data.get("value") if param_data else None
        if raw_value is None:
            return None
        bit_is_set = bool(int(raw_value) & self._bit_mask)
        if self._on_clears_bit:
            return self._off_label if bit_is_set else self._on_label
        return self._on_label if bit_is_set else self._off_label

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
        self._attr_current_option = self._read_current()
        self.async_write_ha_state()

    def _get_change_detector(self):
        entry_data = self.hass.data.get(DOMAIN, {}).get(self._entry.entry_id, {})
        return entry_data.get(SERVICE_CHANGE_DETECTOR)

    def _get_database(self):
        entry_data = self.hass.data.get(DOMAIN, {}).get(self._entry.entry_id, {})
        return entry_data.get(SERVICE_DATABASE)

    async def async_select_option(self, option: str) -> None:
        """Toggle the bitmask bit to match the selected option."""
        edit_params = (
            self._slow_coordinator.data.get("editParams", {})
            if self._slow_coordinator.data
            else {}
        )
        param_data = edit_params.get("data", {}).get(self._settings_param, {})
        current_raw = param_data.get("value") if param_data else None
        if current_raw is None:
            _LOGGER.error("Cannot read current %s for bitmask toggle", self._settings_param)
            return

        current_int = int(current_raw)
        want_on = option == self._on_label

        if self._on_clears_bit:
            new_value = current_int & ~self._bit_mask if want_on else current_int | self._bit_mask
        else:
            new_value = current_int | self._bit_mask if want_on else current_int & ~self._bit_mask

        if self._safe_mode:
            await _safe_mode_notify(
                self.hass, self._api, self._key, self._settings_param_name, option, new_value,
            )
            return

        old_option = self._attr_current_option
        change_detector = self._get_change_detector()
        if change_detector:
            change_detector.mark_self_write(self._key)

        success = await self._api.set_param(self._settings_param_name, new_value)
        if success:
            self._attr_current_option = option
            self.async_write_ha_state()
            _LOGGER.info("Set %s to %s (bitmask %s → %d)", self._key, option, self._settings_param, new_value)
            db = self._get_database()
            if db:
                await db.async_log_change(
                    self.hass,
                    {
                        "name": self._key,
                        "index": self._settings_param,
                        "old_value": old_option,
                        "new_value": option,
                    },
                    source="user",
                )
        else:
            _LOGGER.error("Failed to set %s to %s", self._key, option)
            if change_detector:
                change_detector.clear_self_write(self._key)


async def _safe_mode_notify(
    hass: HomeAssistant,
    api: EconetApi,
    key: str,
    param_name: str,
    option: str,
    api_value: int,
) -> None:
    """Show a persistent notification instead of writing in safe mode."""
    notification_id = f"{DOMAIN}_write_{key}_{api_value}"
    formatted = int(api_value) if api_value == int(api_value) else api_value
    api_url = (
        f"`{api.host}/econet/newParam"
        f"?newParamName={param_name}&newParamValue={formatted}`"
    )
    message = (
        f"**EcoNet Grant**: Pending write request\n\n"
        f"Parameter: **{key}**\n"
        f"New mode: **{option}** (API value: {api_value})\n"
        f"API param name: {param_name}\n\n"
        f"API call that would run:\n{api_url}\n\n"
        f"Safe mode is ON. To execute this write, disable safe mode in "
        f"the integration options and set the value again."
    )
    pn_async_create(
        hass,
        message=message,
        title="EcoNet Grant - Write Pending",
        notification_id=notification_id,
    )
    _LOGGER.warning(
        "Safe mode: blocked write of %s = %s (param %s, value %d). "
        "Created persistent notification %s",
        key, option, param_name, api_value, notification_id,
    )
