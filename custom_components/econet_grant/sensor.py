"""Sensor platform for EcoNet Grant Aerona."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.sensor import (
    SensorEntity,
    SensorEntityDescription,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .api import EconetApi
from .const import (
    DEVICE_MANUFACTURER,
    DEVICE_MODEL,
    DOMAIN,
    SENSOR_DEFINITIONS,
    SERVICE_API,
    SERVICE_COORDINATOR,
)
from .coordinator import EconetFastCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up sensor entities from a config entry."""
    data = hass.data[DOMAIN][entry.entry_id]
    coordinator: EconetFastCoordinator = data[SERVICE_COORDINATOR]
    api: EconetApi = data[SERVICE_API]

    entities: list[EconetSensor] = []
    curr = coordinator.data.get("curr", {}) if coordinator.data else {}

    for key, defn in SENSOR_DEFINITIONS.items():
        if key in curr and curr[key] is not None:
            description = SensorEntityDescription(
                key=key,
                name=defn["name"],
                device_class=defn["device_class"],
                native_unit_of_measurement=defn["unit"],
                state_class=defn["state_class"],
                suggested_display_precision=1,
            )
            entities.append(EconetSensor(coordinator, api, description))
        else:
            _LOGGER.debug("Skipping sensor %s: not present or null in regParams.curr", key)

    async_add_entities(entities)
    _LOGGER.info("Created %d sensor entities", len(entities))


class EconetSensor(CoordinatorEntity[EconetFastCoordinator], SensorEntity):
    """A sensor entity backed by the fast coordinator (regParams.curr)."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: EconetFastCoordinator,
        api: EconetApi,
        description: SensorEntityDescription,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._api = api
        self._attr_unique_id = f"{DOMAIN}_{api.uid}_{description.key}"

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, self._api.uid or self._api.host)},
            name="Grant Aerona Heat Pump",
            manufacturer=DEVICE_MANUFACTURER,
            model=DEVICE_MODEL,
            sw_version=self._api.sw_version,
        )

    @callback
    def _handle_coordinator_update(self) -> None:
        curr = self.coordinator.data.get("curr", {}) if self.coordinator.data else {}
        value = curr.get(self.entity_description.key)
        if value is not None:
            self._attr_native_value = value
        self.async_write_ha_state()
