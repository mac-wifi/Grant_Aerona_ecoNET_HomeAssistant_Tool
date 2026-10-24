"""Select platform for EcoNet Grant Aerona (modes and bitmask toggles)."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.select import SelectEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import BITMASK_SELECT_DEFINITIONS, SELECT_DEFINITIONS
from .entity import (
    EconetConfigEntry,
    EconetRuntimeData,
    EconetSettingEntity,
    notify_safe_mode_write,
)

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: EconetConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up select entities from a config entry."""
    data = entry.runtime_data
    entities: list[SelectEntity] = [
        EconetSelect(data, entry, key, defn) for key, defn in SELECT_DEFINITIONS.items()
    ]
    entities += [
        EconetBitmaskSelect(data, entry, key, defn)
        for key, defn in BITMASK_SELECT_DEFINITIONS.items()
    ]
    async_add_entities(entities)


class EconetSelect(EconetSettingEntity, SelectEntity):
    """A mode selector mapping API integers to labels (written by name)."""

    def __init__(
        self,
        data: EconetRuntimeData,
        entry: EconetConfigEntry,
        key: str,
        defn: dict[str, Any],
    ) -> None:
        super().__init__(data, entry, key)
        self._param_index = defn["param_index"]
        self._value_to_label: dict[int, str] = defn["options"]
        self._label_to_value: dict[str, int] = {v: k for k, v in defn["options"].items()}
        self._attr_name = defn["name"]
        self._attr_options = list(self._value_to_label.values())
        self._attr_current_option: str | None = self._read_current()

    def _read_current(self) -> str | None:
        raw = self._edit_value(self._param_index)
        if raw is None:
            return None
        value = int(raw)
        return self._value_to_label.get(value, f"Unknown ({value})")

    @callback
    def _handle_coordinator_update(self) -> None:
        current = self._read_current()
        if current is not None:
            self._attr_current_option = current
        self.async_write_ha_state()

    def _set_local_state(self, value: Any) -> None:
        self._attr_current_option = value

    async def async_select_option(self, option: str) -> None:
        """Write a new mode to the controller, or preview it in Safe Mode."""
        api_value = self._label_to_value.get(option)
        if api_value is None:
            _LOGGER.error("Unknown option '%s' for %s", option, self._key)
            return
        if self._safe_mode:
            notify_safe_mode_write(
                self.hass, self._api, self._key, self._key, api_value,
                f"New mode: **{option}** (API value: {api_value})\n"
                f"API param name: {self._key}",
            )
            return
        await self._async_write(
            self._key, api_value, index=self._param_index,
            old=self._attr_current_option, new=option,
        )


class EconetBitmaskSelect(EconetSettingEntity, SelectEntity):
    """A two-option toggle for one bit of a settings bitmask.

    Writes send the whole bitmask parameter by name with only this bit changed.
    """

    def __init__(
        self,
        data: EconetRuntimeData,
        entry: EconetConfigEntry,
        key: str,
        defn: dict[str, Any],
    ) -> None:
        super().__init__(data, entry, key)
        self._settings_param = defn["settings_param"]
        self._settings_param_name = defn["settings_param_name"]
        self._bit_mask = defn["bit_mask"]
        self._on_label = defn["on_label"]
        self._off_label = defn["off_label"]
        self._on_clears_bit = defn.get("on_clears_bit", False)
        self._attr_name = defn["name"]
        self._attr_options = [self._on_label, self._off_label]
        self._attr_current_option = self._read_current()

    def _read_current(self) -> str | None:
        raw = self._edit_value(self._settings_param)
        if raw is None:
            return None
        is_on = bool(int(raw) & self._bit_mask) != self._on_clears_bit
        return self._on_label if is_on else self._off_label

    @callback
    def _handle_coordinator_update(self) -> None:
        self._attr_current_option = self._read_current()
        self.async_write_ha_state()

    def _set_local_state(self, value: Any) -> None:
        self._attr_current_option = value

    def _bitmask_for(self, current: int, want_on: bool) -> int:
        set_bit = want_on != self._on_clears_bit
        return current | self._bit_mask if set_bit else current & ~self._bit_mask

    async def async_select_option(self, option: str) -> None:
        """Toggle this bit, preserving all other bits of the current bitmask."""
        current_raw = self._edit_value(self._settings_param)
        if current_raw is None:
            _LOGGER.error("Cannot read current %s for bitmask toggle", self._settings_param)
            return
        new_value = self._bitmask_for(int(current_raw), option == self._on_label)
        if self._safe_mode:
            notify_safe_mode_write(
                self.hass, self._api, self._key, self._settings_param_name, new_value,
                f"New mode: **{option}** (API value: {new_value})\n"
                f"API param name: {self._settings_param_name}",
            )
            return
        await self._async_write(
            self._settings_param_name, new_value, index=self._settings_param,
            old=self._attr_current_option, new=option,
        )
