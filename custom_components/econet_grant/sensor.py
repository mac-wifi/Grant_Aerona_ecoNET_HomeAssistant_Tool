"""Sensor platform for EcoNet Grant Aerona."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from homeassistant.components.sensor import SensorEntity, SensorEntityDescription
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.loader import async_get_integration

from .api import EconetApi
from .backup import get_snapshot_info
from .const import (
    CONF_HOST,
    DOMAIN,
    SENSOR_DEFINITIONS,
    SIGNAL_SNAPSHOT_SAVED,
    TILES_SENSOR_DEFINITIONS,
)
from .database import EconetDatabase
from .entity import EconetConfigEntry, EconetEntity, is_safe_mode


async def async_setup_entry(
    hass: HomeAssistant,
    entry: EconetConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up sensor entities from a config entry."""
    data = entry.runtime_data
    fast, slow, api, db = data.fast_coordinator, data.slow_coordinator, data.api, data.database
    version = (await async_get_integration(hass, DOMAIN)).version

    entities: list[SensorEntity] = [
        EconetSensor(fast, api, _description(key, defn), defn.get("value_map"))
        for key, defn in SENSOR_DEFINITIONS.items()
    ]
    entities += [
        EconetTilesSensor(fast, api, _description(key, defn), defn)
        for key, defn in TILES_SENSOR_DEFINITIONS.items()
    ]
    entities += [
        EconetPollTimeSensor(fast, api, "last_reading", "Last Sensor Poll", "mdi:clock-check"),
        EconetPollTimeSensor(
            slow, api, "last_settings_check", "Last Settings Check", "mdi:clock-alert",
        ),
        EconetSettingsVersionSensor(fast, api),
        EconetDatabaseSizeSensor(fast, api, db),
        EconetSafeModeSensor(fast, api, entry),
        EconetRemoteMenuSensor(slow, api),
        EconetRecentChangesSensor(slow, api, db),
        EconetLastSnapshotSensor(fast, api),
        EconetIntegrationVersionSensor(fast, api, str(version)),
        EconetControllerAddressSensor(fast, api, entry),
    ]
    async_add_entities(entities)


def _description(key: str, defn: dict[str, Any]) -> SensorEntityDescription:
    kwargs: dict[str, Any] = {
        "key": key,
        "name": defn["name"],
        "device_class": defn["device_class"],
        "native_unit_of_measurement": defn["unit"],
        "state_class": defn["state_class"],
    }
    if defn["state_class"] is not None:
        kwargs["suggested_display_precision"] = 1
    return SensorEntityDescription(**kwargs)


class EconetSensor(EconetEntity, SensorEntity):
    """A live reading from regParams.curr."""

    def __init__(
        self,
        coordinator: Any,
        api: EconetApi,
        description: SensorEntityDescription,
        value_map: dict[int, str] | None = None,
    ) -> None:
        super().__init__(coordinator, api, description.key)
        self.entity_description = description
        self._value_map = value_map

    @property
    def native_value(self) -> Any:
        curr = (self.coordinator.data or {}).get("curr", {})
        value = curr.get(self.entity_description.key)
        if value is None:
            return None
        if self._value_map:
            return self._value_map.get(int(value), f"Unknown ({value})")
        return value


class EconetTilesSensor(EconetEntity, SensorEntity):
    """A reading from regParams.tilesParams[i][0][0][0] or schemaParams[key][0][0][0]."""

    def __init__(
        self,
        coordinator: Any,
        api: EconetApi,
        description: SensorEntityDescription,
        defn: dict[str, Any],
    ) -> None:
        super().__init__(coordinator, api, description.key)
        self.entity_description = description
        self._source = defn["source"]
        self._tile_index = defn.get("tile_index")
        self._schema_key = defn.get("schema_key")
        self._value_map = defn.get("value_map")

    @property
    def native_value(self) -> Any:
        data = self.coordinator.data
        if not data:
            return None
        if self._source == "tilesParams" and self._tile_index is not None:
            container, key = data.get("tilesParams", []), self._tile_index
        elif self._source == "schemaParams" and self._schema_key:
            container, key = data.get("schemaParams", {}), self._schema_key
        else:
            return None
        try:
            value = container[key][0][0][0]
        except (IndexError, TypeError, KeyError):
            return None
        if self._value_map:
            lookup = str(value) if self._source == "tilesParams" else value
            return self._value_map.get(lookup, str(value))
        return value


# ------------------------------------------------------------------
# Diagnostic sensors for the Admin dashboard tab
# ------------------------------------------------------------------


class EconetDiagnosticEntity(EconetEntity, SensorEntity):
    """Base for diagnostic sensors with fixed name/icon."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC


class EconetPollTimeSensor(EconetDiagnosticEntity):
    """Timestamp of the coordinator's last successful poll."""

    def __init__(
        self, coordinator: Any, api: EconetApi, key: str, name: str, icon: str,
    ) -> None:
        super().__init__(coordinator, api, key)
        self._attr_name = name
        self._attr_icon = icon
        self._last_update: str | None = None

    @callback
    def _handle_coordinator_update(self) -> None:
        if self.coordinator.data is not None:
            self._last_update = datetime.now(timezone.utc).isoformat(timespec="seconds")
        self.async_write_ha_state()

    @property
    def native_value(self) -> str | None:
        return self._last_update


class EconetSettingsVersionSensor(EconetDiagnosticEntity):
    """The controller's settingsVer counter from regParams."""

    _attr_name = "Settings Version"
    _attr_icon = "mdi:counter"

    def __init__(self, coordinator: Any, api: EconetApi) -> None:
        super().__init__(coordinator, api, "settings_version")

    @property
    def native_value(self) -> Any:
        if self.coordinator.data is None:
            return None
        return self.coordinator.data.get("settingsVer")


class EconetDatabaseSizeSensor(EconetDiagnosticEntity):
    """SQLite database file size in MB."""

    _attr_name = "Database Size"
    _attr_icon = "mdi:database"
    _attr_native_unit_of_measurement = "MB"

    def __init__(self, coordinator: Any, api: EconetApi, db: EconetDatabase) -> None:
        super().__init__(coordinator, api, "database_size")
        self._db = db

    @property
    def native_value(self) -> float:
        return round(self._db.get_db_size_mb(), 2)


class EconetSafeModeSensor(EconetDiagnosticEntity):
    """Whether Safe Mode (writes previewed, never sent) is on."""

    _attr_name = "Safe Mode"
    _attr_icon = "mdi:shield-lock"

    def __init__(self, coordinator: Any, api: EconetApi, entry: EconetConfigEntry) -> None:
        super().__init__(coordinator, api, "safe_mode")
        self._entry = entry

    @property
    def native_value(self) -> str:
        return "On" if is_safe_mode(self._entry) else "Off"


class EconetRemoteMenuSensor(EconetDiagnosticEntity):
    """The sysParams remoteMenu flag (false on this controller)."""

    _attr_name = "Remote Menu"
    _attr_icon = "mdi:remote"

    def __init__(self, coordinator: Any, api: EconetApi) -> None:
        super().__init__(coordinator, api, "remote_menu")

    @property
    def native_value(self) -> str:
        if self.coordinator.data is None:
            return "unknown"
        sys_params = self.coordinator.data.get("sysParams", {})
        return str(sys_params.get("remoteMenu", "unknown")).lower()


class EconetRecentChangesSensor(EconetDiagnosticEntity):
    """Number of audited parameter changes in the last 24 hours."""

    _attr_name = "Recent Changes (24h)"
    _attr_icon = "mdi:delta"

    def __init__(self, coordinator: Any, api: EconetApi, db: EconetDatabase) -> None:
        super().__init__(coordinator, api, "recent_changes")
        self._db = db
        self._count = 0

    @callback
    def _handle_coordinator_update(self) -> None:
        self._count = self._db.get_recent_change_count()
        self.async_write_ha_state()

    @property
    def native_value(self) -> int:
        return self._count


class EconetLastSnapshotSensor(EconetDiagnosticEntity):
    """When the 'Default' settings snapshot was last taken.

    Refreshed at start-up, as soon as a backup completes, and on each poll
    (which also catches files changed outside HA). The file is read in the
    executor, never on the event loop.
    """

    _attr_name = "Last Default Snapshot"
    _attr_icon = "mdi:content-save-check"

    def __init__(self, coordinator: Any, api: EconetApi) -> None:
        super().__init__(coordinator, api, "last_default_snapshot")
        self._info: dict[str, Any] | None = None

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(
            async_dispatcher_connect(self.hass, SIGNAL_SNAPSHOT_SAVED, self._on_snapshot_saved)
        )
        await self._async_refresh()

    @callback
    def _on_snapshot_saved(self, snapshot_name: str) -> None:
        if snapshot_name == "Default":
            self.coordinator.config_entry.async_create_task(self.hass, self._async_refresh())

    @callback
    def _handle_coordinator_update(self) -> None:
        self.coordinator.config_entry.async_create_task(self.hass, self._async_refresh())

    async def _async_refresh(self) -> None:
        self._info = await self.hass.async_add_executor_job(
            get_snapshot_info, self.hass, "Default"
        )
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


class EconetIntegrationVersionSensor(EconetDiagnosticEntity):
    """The integration version Home Assistant is actually running (manifest.json).

    Lets the dashboard show the live version, and reveals a pending restart
    after a Marketplace (HACS) update.
    """

    _attr_name = "Integration Version"
    _attr_icon = "mdi:tag"

    def __init__(self, coordinator: Any, api: EconetApi, version: str) -> None:
        super().__init__(coordinator, api, "integration_version")
        self._attr_native_value = version

    @property
    def available(self) -> bool:
        """Known locally, so still shown while the controller is unreachable."""
        return True


class EconetControllerAddressSensor(EconetDiagnosticEntity):
    """The saved controller address, so a dead connection is easy to diagnose.

    Address only: never the username or password.
    """

    _attr_name = "Controller Address"
    _attr_icon = "mdi:ip-network"

    def __init__(self, coordinator: Any, api: EconetApi, entry: EconetConfigEntry) -> None:
        super().__init__(coordinator, api, "controller_address")
        host = str(entry.data[CONF_HOST]).strip()
        for prefix in ("http://", "https://"):
            host = host.removeprefix(prefix)
        self._attr_native_value = host.rstrip("/")

    @property
    def available(self) -> bool:
        """Known locally, so still shown while the controller is unreachable."""
        return True
