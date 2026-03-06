"""Sensor platform for EcoNet Grant Aerona."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.sensor import (
    SensorEntity,
    SensorEntityDescription,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
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
    TILES_SENSOR_DEFINITIONS,
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

    entities: list[SensorEntity] = []

    for key, defn in SENSOR_DEFINITIONS.items():
        desc_kwargs: dict[str, Any] = {
            "key": key,
            "name": defn["name"],
            "device_class": defn["device_class"],
            "native_unit_of_measurement": defn["unit"],
            "state_class": defn["state_class"],
        }
        if defn["state_class"] is not None:
            desc_kwargs["suggested_display_precision"] = 1
        description = SensorEntityDescription(**desc_kwargs)
        value_map = defn.get("value_map")
        entities.append(EconetSensor(coordinator, api, description, value_map))

    for key, defn in TILES_SENSOR_DEFINITIONS.items():
        desc_kwargs = {
            "key": key,
            "name": defn["name"],
            "device_class": defn["device_class"],
            "native_unit_of_measurement": defn["unit"],
            "state_class": defn["state_class"],
        }
        if defn["state_class"] is not None:
            desc_kwargs["suggested_display_precision"] = 1
        description = SensorEntityDescription(**desc_kwargs)
        entities.append(
            EconetTilesSensor(coordinator, api, description, defn)
        )

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
        value_map: dict[int, str] | None = None,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._api = api
        self._value_map = value_map
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

    @property
    def native_value(self) -> Any:
        curr = self.coordinator.data.get("curr", {}) if self.coordinator.data else {}
        value = curr.get(self.entity_description.key)
        if value is None:
            return None
        if self._value_map:
            return self._value_map.get(int(value), f"Unknown ({value})")
        return value


class EconetTilesSensor(CoordinatorEntity[EconetFastCoordinator], SensorEntity):
    """A sensor backed by regParams.tilesParams or regParams.schemaParams."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: EconetFastCoordinator,
        api: EconetApi,
        description: SensorEntityDescription,
        defn: dict[str, Any],
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._api = api
        self._source = defn["source"]
        self._tile_index = defn.get("tile_index")
        self._schema_key = defn.get("schema_key")
        self._value_map = defn.get("value_map")
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

    @property
    def native_value(self) -> Any:
        if not self.coordinator.data:
            return None

        if self._source == "tilesParams" and self._tile_index is not None:
            return self._read_tile()
        if self._source == "schemaParams" and self._schema_key:
            return self._read_schema()
        return None

    def _read_tile(self) -> Any:
        """Extract value from tilesParams[index][0][0][0]."""
        tiles = self.coordinator.data.get("tilesParams", [])
        try:
            value = tiles[self._tile_index][0][0][0]
        except (IndexError, TypeError, KeyError):
            return None
        if self._value_map:
            return self._value_map.get(str(value), str(value))
        return value

    def _read_schema(self) -> Any:
        """Extract value from schemaParams[key][0][0][0]."""
        schema = self.coordinator.data.get("schemaParams", {})
        try:
            value = schema[self._schema_key][0][0][0]
        except (IndexError, TypeError, KeyError):
            return None
        if self._value_map:
            return self._value_map.get(value, str(value))
        return value
