"""Sensor platform for EcoNet Grant Aerona."""

from __future__ import annotations

from datetime import datetime, timezone
import logging
from typing import Any

from homeassistant.components.sensor import (
    SensorEntity,
    SensorEntityDescription,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .api import EconetApi
from .backup import get_snapshot_info
from .const import (
    CONF_SAFE_MODE,
    DEFAULT_SAFE_MODE,
    DEVICE_MANUFACTURER,
    DEVICE_MODEL,
    DOMAIN,
    SENSOR_DEFINITIONS,
    SERVICE_API,
    SERVICE_COORDINATOR,
    SERVICE_DATABASE,
    SERVICE_SLOW_COORDINATOR,
    TILES_SENSOR_DEFINITIONS,
)
from .coordinator import EconetFastCoordinator, EconetSlowCoordinator
from .database import EconetDatabase

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up sensor entities from a config entry."""
    data = hass.data[DOMAIN][entry.entry_id]
    coordinator: EconetFastCoordinator = data[SERVICE_COORDINATOR]
    slow_coordinator: EconetSlowCoordinator = data[SERVICE_SLOW_COORDINATOR]
    api: EconetApi = data[SERVICE_API]
    db: EconetDatabase = data[SERVICE_DATABASE]

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

    entities.extend([
        EconetDiagnosticSensor(
            coordinator, api, "last_reading",
            "Last Sensor Poll", "mdi:clock-check",
        ),
        EconetDiagnosticSensor(
            slow_coordinator, api, "last_settings_check",
            "Last Settings Check", "mdi:clock-alert",
        ),
        EconetSettingsVersionSensor(coordinator, api),
        EconetDatabaseSizeSensor(coordinator, api, db),
        EconetSafeModeSensor(coordinator, api, entry),
        EconetRemoteMenuSensor(slow_coordinator, api),
        EconetRecentChangesSensor(slow_coordinator, api, db),
        EconetLastSnapshotSensor(coordinator, api, hass),
    ])

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


# ------------------------------------------------------------------
# Diagnostic sensors for the Admin dashboard tab
# ------------------------------------------------------------------


class EconetDiagnosticSensor(CoordinatorEntity, SensorEntity):
    """Diagnostic sensor showing the timestamp of the last successful poll."""

    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(
        self,
        coordinator,
        api: EconetApi,
        key: str,
        name: str,
        icon: str,
    ) -> None:
        super().__init__(coordinator)
        self._api = api
        self._attr_unique_id = f"{DOMAIN}_{api.uid}_{key}"
        self._attr_name = name
        self._attr_icon = icon
        self._last_update: str | None = None

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, self._api.uid or self._api.host)},
            name="Grant Aerona Heat Pump",
            manufacturer=DEVICE_MANUFACTURER,
            model=DEVICE_MODEL,
        )

    @callback
    def _handle_coordinator_update(self) -> None:
        if self.coordinator.data is not None:
            self._last_update = datetime.now(timezone.utc).isoformat(timespec="seconds")
        self.async_write_ha_state()

    @property
    def native_value(self) -> str | None:
        return self._last_update


class EconetSettingsVersionSensor(CoordinatorEntity[EconetFastCoordinator], SensorEntity):
    """Shows the current settingsVer from regParams."""

    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_name = "Settings Version"
    _attr_icon = "mdi:counter"

    def __init__(self, coordinator: EconetFastCoordinator, api: EconetApi) -> None:
        super().__init__(coordinator)
        self._api = api
        self._attr_unique_id = f"{DOMAIN}_{api.uid}_settings_version"

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, self._api.uid or self._api.host)},
            name="Grant Aerona Heat Pump",
            manufacturer=DEVICE_MANUFACTURER,
            model=DEVICE_MODEL,
        )

    @property
    def native_value(self) -> Any:
        if self.coordinator.data is None:
            return None
        return self.coordinator.data.get("settingsVer")


class EconetDatabaseSizeSensor(CoordinatorEntity[EconetFastCoordinator], SensorEntity):
    """Shows the SQLite database file size in MB."""

    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_name = "Database Size"
    _attr_icon = "mdi:database"
    _attr_native_unit_of_measurement = "MB"

    def __init__(
        self, coordinator: EconetFastCoordinator, api: EconetApi, db: EconetDatabase
    ) -> None:
        super().__init__(coordinator)
        self._api = api
        self._db = db
        self._attr_unique_id = f"{DOMAIN}_{api.uid}_database_size"

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, self._api.uid or self._api.host)},
            name="Grant Aerona Heat Pump",
            manufacturer=DEVICE_MANUFACTURER,
            model=DEVICE_MODEL,
        )

    @property
    def native_value(self) -> float:
        return round(self._db.get_db_size_mb(), 2)


class EconetSafeModeSensor(CoordinatorEntity[EconetFastCoordinator], SensorEntity):
    """Shows whether safe mode is enabled."""

    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_name = "Safe Mode"
    _attr_icon = "mdi:shield-lock"

    def __init__(
        self, coordinator: EconetFastCoordinator, api: EconetApi, entry: ConfigEntry
    ) -> None:
        super().__init__(coordinator)
        self._api = api
        self._entry = entry
        self._attr_unique_id = f"{DOMAIN}_{api.uid}_safe_mode"

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, self._api.uid or self._api.host)},
            name="Grant Aerona Heat Pump",
            manufacturer=DEVICE_MANUFACTURER,
            model=DEVICE_MODEL,
        )

    @property
    def native_value(self) -> str:
        safe = self._entry.options.get(CONF_SAFE_MODE, DEFAULT_SAFE_MODE)
        return "On" if safe else "Off"


class EconetRemoteMenuSensor(CoordinatorEntity[EconetSlowCoordinator], SensorEntity):
    """Shows the remoteMenu sysParam value."""

    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_name = "Remote Menu"
    _attr_icon = "mdi:remote"

    def __init__(self, coordinator: EconetSlowCoordinator, api: EconetApi) -> None:
        super().__init__(coordinator)
        self._api = api
        self._attr_unique_id = f"{DOMAIN}_{api.uid}_remote_menu"

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, self._api.uid or self._api.host)},
            name="Grant Aerona Heat Pump",
            manufacturer=DEVICE_MANUFACTURER,
            model=DEVICE_MODEL,
        )

    @property
    def native_value(self) -> str:
        if self.coordinator.data is None:
            return "unknown"
        sys_params = self.coordinator.data.get("sysParams", {})
        return str(sys_params.get("remoteMenu", "unknown")).lower()


class EconetRecentChangesSensor(CoordinatorEntity[EconetSlowCoordinator], SensorEntity):
    """Shows count of parameter changes detected in the last 24 hours."""

    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_name = "Recent Changes (24h)"
    _attr_icon = "mdi:delta"

    def __init__(
        self, coordinator: EconetSlowCoordinator, api: EconetApi, db: EconetDatabase
    ) -> None:
        super().__init__(coordinator)
        self._api = api
        self._db = db
        self._attr_unique_id = f"{DOMAIN}_{api.uid}_recent_changes"
        self._count: int = 0

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, self._api.uid or self._api.host)},
            name="Grant Aerona Heat Pump",
            manufacturer=DEVICE_MANUFACTURER,
            model=DEVICE_MODEL,
        )

    @callback
    def _handle_coordinator_update(self) -> None:
        self._count = self._db.get_recent_change_count()
        self.async_write_ha_state()

    @property
    def native_value(self) -> int:
        return self._count


class EconetLastSnapshotSensor(CoordinatorEntity[EconetFastCoordinator], SensorEntity):
    """Shows the date/time the 'Default' snapshot was last taken."""

    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_name = "Last Default Snapshot"
    _attr_icon = "mdi:content-save-check"

    def __init__(
        self,
        coordinator: EconetFastCoordinator,
        api: EconetApi,
        hass: HomeAssistant,
    ) -> None:
        super().__init__(coordinator)
        self._api = api
        self._hass_ref = hass
        self._attr_unique_id = f"{DOMAIN}_{api.uid}_last_default_snapshot"
        self._info: dict[str, Any] | None = get_snapshot_info(hass, "Default")

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, self._api.uid or self._api.host)},
            name="Grant Aerona Heat Pump",
            manufacturer=DEVICE_MANUFACTURER,
            model=DEVICE_MODEL,
        )

    @callback
    def _handle_coordinator_update(self) -> None:
        self._info = get_snapshot_info(self._hass_ref, "Default")
        self.async_write_ha_state()

    @property
    def native_value(self) -> str | None:
        if self._info and self._info.get("created_at"):
            return self._info["created_at"]
        return None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        if self._info:
            return {"param_count": self._info.get("param_count", 0)}
        return {}
