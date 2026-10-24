"""Shared runtime data and entity base classes for EcoNet Grant Aerona."""

from __future__ import annotations

from dataclasses import dataclass
import logging
from typing import TYPE_CHECKING, Any

from homeassistant.components.persistent_notification import async_create as pn_async_create
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    API_BASE_PATH,
    API_NEW_PARAM,
    CONF_SAFE_MODE,
    DEFAULT_SAFE_MODE,
    DEVICE_MANUFACTURER,
    DEVICE_MODEL,
    DEVICE_NAME,
    DOMAIN,
)

if TYPE_CHECKING:
    from .api import EconetApi
    from .change_detector import ChangeDetector
    from .coordinator import EconetFastCoordinator, EconetSlowCoordinator
    from .database import EconetDatabase
    from .revert import RevertActions

_LOGGER = logging.getLogger(__name__)


@dataclass
class EconetRuntimeData:
    """Everything one loaded config entry owns, stored in ``entry.runtime_data``."""

    api: EconetApi
    fast_coordinator: EconetFastCoordinator
    slow_coordinator: EconetSlowCoordinator
    database: EconetDatabase
    change_detector: ChangeDetector
    revert_actions: RevertActions


type EconetConfigEntry = ConfigEntry[EconetRuntimeData]


def device_info(api: EconetApi) -> DeviceInfo:
    """The single heat-pump device every entity belongs to."""
    return DeviceInfo(
        identifiers={(DOMAIN, api.uid or api.host)},
        name=DEVICE_NAME,
        manufacturer=DEVICE_MANUFACTURER,
        model=DEVICE_MODEL,
        sw_version=api.sw_version,
    )


def is_safe_mode(entry: ConfigEntry) -> bool:
    """Safe Mode is on unless the owner has explicitly disabled it."""
    return entry.options.get(CONF_SAFE_MODE, DEFAULT_SAFE_MODE)


def edit_param_value(slow_coordinator: Any, index: str) -> Any:
    """Return editParams.data[index].value from the latest slow poll, or None."""
    data = slow_coordinator.data or {}
    param = data.get("editParams", {}).get("data", {}).get(index)
    return param.get("value") if param else None


def _api_value_text(value: float | int) -> int | float:
    return int(value) if value == int(value) else value


def notify_safe_mode_write(
    hass: HomeAssistant,
    api: EconetApi,
    key: str,
    api_param_name: str,
    api_value: float | int,
    details: str,
) -> None:
    """Preview, instead of performing, a write while Safe Mode is on."""
    notification_id = f"{DOMAIN}_write_{key}_{api_value}"
    api_url = (
        f"`{api.host}{API_BASE_PATH}/{API_NEW_PARAM}"
        f"?newParamName={api_param_name}&newParamValue={_api_value_text(api_value)}`"
    )
    message = (
        f"**EcoNet Grant**: Pending write request\n\n"
        f"Parameter: **{key}**\n"
        f"{details}\n\n"
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
        "Safe mode: blocked write of %s = %s (%s). Created persistent notification %s",
        key, api_value, api_param_name, notification_id,
    )


class EconetEntity(CoordinatorEntity):
    """Base for every coordinator-backed entity on the heat-pump device."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: Any, api: EconetApi, key: str) -> None:
        super().__init__(coordinator)
        self._api = api
        self._attr_unique_id = f"{DOMAIN}_{api.uid}_{key}"

    @property
    def device_info(self) -> DeviceInfo:
        return device_info(self._api)


class EconetSettingEntity(EconetEntity):
    """Base for writable entities backed by an editParams setting.

    Availability follows the fast coordinator; values come from the slow
    coordinator's latest editParams snapshot.
    """

    def __init__(
        self, data: EconetRuntimeData, entry: ConfigEntry, key: str,
    ) -> None:
        super().__init__(data.fast_coordinator, data.api, key)
        self._slow_coordinator = data.slow_coordinator
        self._change_detector = data.change_detector
        self._database = data.database
        self._entry = entry
        self._key = key

    @property
    def _safe_mode(self) -> bool:
        return is_safe_mode(self._entry)

    def _edit_value(self, index: str) -> Any:
        return edit_param_value(self._slow_coordinator, index)

    def _set_local_state(self, value: Any) -> None:
        """Reflect an API-acknowledged write in this entity's state."""
        raise NotImplementedError

    async def _async_write(
        self,
        api_param_name: str,
        api_value: float | int,
        *,
        index: str,
        old: Any,
        new: Any,
    ) -> bool:
        """Write one setting by name, then audit it as a user change.

        The self-write marker is keyed by the API parameter name, which is the
        name the change detector will see on the next settings poll.
        """
        self._change_detector.mark_self_write(api_param_name)
        if not await self._api.set_param(api_param_name, api_value):
            _LOGGER.error("Failed to set %s to %s (API value %s)", self._key, new, api_value)
            self._change_detector.clear_self_write(api_param_name)
            return False
        self._set_local_state(new)
        self.async_write_ha_state()
        _LOGGER.info("Set %s to %s (API %s = %s)", self._key, new, api_param_name, api_value)
        await self._database.async_log_change(
            self.hass,
            {"name": self._key, "index": index, "old_value": old, "new_value": new},
            source="user",
        )
        return True
