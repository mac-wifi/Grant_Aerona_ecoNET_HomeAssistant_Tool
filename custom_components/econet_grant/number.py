"""Number platform for EcoNet Grant Aerona (writable setpoints)."""

from __future__ import annotations

from typing import Any

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import NUMBER_DEFINITIONS
from .entity import (
    EconetConfigEntry,
    EconetRuntimeData,
    EconetSettingEntity,
    notify_safe_mode_write,
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: EconetConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up number entities from a config entry."""
    async_add_entities(
        EconetNumber(entry.runtime_data, entry, key, defn)
        for key, defn in NUMBER_DEFINITIONS.items()
    )


class EconetNumber(EconetSettingEntity, NumberEntity):
    """A writable number entity for one editParams setpoint (written by name)."""

    _attr_mode = NumberMode.BOX

    def __init__(
        self,
        data: EconetRuntimeData,
        entry: EconetConfigEntry,
        key: str,
        defn: dict[str, Any],
    ) -> None:
        super().__init__(data, entry, key)
        self._param_index = defn["param_index"]
        self._attr_name = defn["name"]
        self._attr_native_min_value = defn["min_value"]
        self._attr_native_max_value = defn["max_value"]
        self._attr_native_step = defn["step"]
        self._attr_native_unit_of_measurement = defn["unit"]
        value = self._edit_value(self._param_index)
        if value is not None:
            self._attr_native_value = value

    @callback
    def _handle_coordinator_update(self) -> None:
        value = self._edit_value(self._param_index)
        if value is not None:
            self._attr_native_value = value
        self.async_write_ha_state()

    def _set_local_state(self, value: Any) -> None:
        self._attr_native_value = value

    async def async_set_native_value(self, value: float) -> None:
        """Write a new value to the controller, or preview it in Safe Mode."""
        if self._safe_mode:
            notify_safe_mode_write(
                self.hass, self._api, self._key, self._key, value,
                f"New value: **{value}**\nParam index: {self._param_index}",
            )
            return
        await self._async_write(
            self._key, value, index=self._param_index,
            old=self._attr_native_value, new=value,
        )
