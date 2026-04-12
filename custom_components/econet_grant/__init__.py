"""EcoNet Grant Aerona integration for Home Assistant."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import AuthError, make_api
from .backup import async_backup_settings, async_restore_settings, _snapshot_path
from .change_detector import ChangeDetector
from .const import (
    CONF_HOST,
    CONF_PASSWORD,
    CONF_RETENTION_DAYS,
    CONF_SAFE_MODE,
    CONF_USERNAME,
    DATA_RETENTION_DAYS,
    DATABASE_FILENAME,
    DEFAULT_SAFE_MODE,
    DOMAIN,
    SERVICE_API,
    SERVICE_COORDINATOR,
    SERVICE_DATABASE,
    SERVICE_SLOW_COORDINATOR,
)
from .coordinator import EconetFastCoordinator, EconetSlowCoordinator
from .database import EconetDatabase

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [
    Platform.SENSOR,
    Platform.NUMBER,
    Platform.SELECT,
    Platform.BUTTON,
]

SERVICE_CHANGE_DETECTOR = "change_detector"


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up EcoNet Grant Aerona from a config entry."""
    hass.data.setdefault(DOMAIN, {})

    session = async_get_clientsession(hass)
    host = entry.data[CONF_HOST]
    username = entry.data[CONF_USERNAME]
    password = entry.data[CONF_PASSWORD]

    try:
        api = await make_api(session, host, username, password)
    except AuthError as err:
        raise ConfigEntryAuthFailed("Invalid credentials") from err
    except Exception as err:
        raise ConfigEntryNotReady(f"Cannot connect to {host}") from err

    fast_coordinator = EconetFastCoordinator(hass, api, entry)
    slow_coordinator = EconetSlowCoordinator(hass, api, entry)

    await fast_coordinator.async_config_entry_first_refresh()
    await slow_coordinator.async_config_entry_first_refresh()

    db = EconetDatabase(Path(hass.config.config_dir) / DATABASE_FILENAME)
    await db.async_setup(hass)

    retention_days = entry.options.get(CONF_RETENTION_DAYS, DATA_RETENTION_DAYS)
    await db.async_purge_old_data(hass, retention_days)

    change_detector = ChangeDetector(hass, entry)

    # Process the initial slow data for change detection baseline
    if slow_coordinator.data:
        edit_params = slow_coordinator.data.get("editParams", {})
        sys_params = slow_coordinator.data.get("sysParams", {})
        change_detector.process_edit_params(edit_params)
        change_detector.process_sys_params(sys_params)

    # Record the initial data from both coordinators
    if fast_coordinator.data:
        await db.async_record_readings(hass, fast_coordinator.data)
    if slow_coordinator.data:
        edit_params = slow_coordinator.data.get("editParams", {})
        sys_params = slow_coordinator.data.get("sysParams", {})
        if edit_params:
            await db.async_record_settings(hass, edit_params)
        if sys_params:
            await db.async_record_sys_params(hass, sys_params)

    _state: dict[str, Any] = {
        "last_settings_ver": None,
        "last_editable_params_ver": None,
        "last_schedules_ver": None,
    }

    if fast_coordinator.data:
        _state["last_settings_ver"] = fast_coordinator.data.get("settingsVer")
        _state["last_editable_params_ver"] = fast_coordinator.data.get("editableParamsVer")
        _state["last_schedules_ver"] = fast_coordinator.data.get("schedulesVer")

    @callback
    def _on_fast_update() -> None:
        """Record regParams readings and watch version counters for changes."""
        if fast_coordinator.data is None:
            return
        hass.async_create_task(
            db.async_record_readings(hass, fast_coordinator.data)
        )

        new_settings_ver = fast_coordinator.data.get("settingsVer")
        new_edit_ver = fast_coordinator.data.get("editableParamsVer")
        new_sched_ver = fast_coordinator.data.get("schedulesVer")

        trigger_refresh = False
        if new_settings_ver is not None and new_settings_ver != _state["last_settings_ver"]:
            _LOGGER.info(
                "settingsVer changed: %s -> %s, triggering settings refresh",
                _state["last_settings_ver"], new_settings_ver,
            )
            _state["last_settings_ver"] = new_settings_ver
            trigger_refresh = True

        if new_edit_ver is not None and new_edit_ver != _state["last_editable_params_ver"]:
            _LOGGER.info(
                "editableParamsVer changed: %s -> %s",
                _state["last_editable_params_ver"], new_edit_ver,
            )
            _state["last_editable_params_ver"] = new_edit_ver
            trigger_refresh = True

        if new_sched_ver is not None and new_sched_ver != _state["last_schedules_ver"]:
            _LOGGER.info(
                "schedulesVer changed: %s -> %s",
                _state["last_schedules_ver"], new_sched_ver,
            )
            _state["last_schedules_ver"] = new_sched_ver
            trigger_refresh = True

        if trigger_refresh:
            hass.async_create_task(slow_coordinator.async_request_refresh())

    fast_coordinator.async_add_listener(_on_fast_update)

    @callback
    def _on_slow_update() -> None:
        """Run change detection and database recording on slow polls."""
        if slow_coordinator.data is None:
            _LOGGER.debug("Slow coordinator update: data is None, skipping")
            return

        edit_params = slow_coordinator.data.get("editParams", {})
        sys_params = slow_coordinator.data.get("sysParams", {})

        try:
            changes = change_detector.process_edit_params(edit_params)
            for change in changes:
                source = change.pop("source", "external")
                hass.async_create_task(db.async_log_change(hass, change, source))
        except Exception:
            _LOGGER.exception("Error in editParams change detection")

        try:
            sys_changes = change_detector.process_sys_params(sys_params)
            for change in sys_changes:
                source = change.pop("source", "external")
                hass.async_create_task(db.async_log_change(hass, change, source))
        except Exception:
            _LOGGER.exception("Error in sysParams change detection")

        hass.async_create_task(db.async_record_settings(hass, edit_params))
        if sys_params:
            hass.async_create_task(db.async_record_sys_params(hass, sys_params))

    slow_coordinator.async_add_listener(_on_slow_update)

    hass.data[DOMAIN][entry.entry_id] = {
        SERVICE_API: api,
        SERVICE_COORDINATOR: fast_coordinator,
        SERVICE_SLOW_COORDINATOR: slow_coordinator,
        SERVICE_DATABASE: db,
        SERVICE_CHANGE_DETECTOR: change_detector,
    }

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    _register_services(hass, entry)

    return True


def _register_services(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Register backup_settings and restore_settings services."""

    async def handle_backup(call: ServiceCall) -> None:
        name = call.data.get("snapshot_name", "Default")
        api = hass.data[DOMAIN][entry.entry_id][SERVICE_API]
        await async_backup_settings(hass, api, snapshot_name=name)

    async def handle_restore(call: ServiceCall) -> None:
        name = call.data.get("snapshot_name", "Default")
        api = hass.data[DOMAIN][entry.entry_id][SERVICE_API]
        safe_mode = entry.options.get(CONF_SAFE_MODE, DEFAULT_SAFE_MODE)
        change_detector_inst = hass.data[DOMAIN][entry.entry_id][SERVICE_CHANGE_DETECTOR]
        db_inst = hass.data[DOMAIN][entry.entry_id][SERVICE_DATABASE]

        if not safe_mode:
            path = _snapshot_path(hass, name)
            if path.exists():
                snapshot = json.loads(path.read_text())
                for idx, param in snapshot.get("parameters", {}).items():
                    if isinstance(param, dict) and "name" in param:
                        change_detector_inst.mark_self_write(param["name"])
                        await db_inst.async_log_change(
                            hass,
                            {
                                "name": param["name"],
                                "index": idx,
                                "old_value": "",
                                "new_value": param.get("value", ""),
                            },
                            source="restore",
                        )

        result = await async_restore_settings(hass, api, snapshot_name=name, safe_mode=safe_mode)
        _LOGGER.info("Restore result: %s", result)

    if not hass.services.has_service(DOMAIN, "backup_settings"):
        hass.services.async_register(
            DOMAIN,
            "backup_settings",
            handle_backup,
            schema=vol.Schema({
                vol.Required("snapshot_name", default="Default"): cv.string,
            }),
        )

    if not hass.services.has_service(DOMAIN, "restore_settings"):
        hass.services.async_register(
            DOMAIN,
            "restore_settings",
            handle_restore,
            schema=vol.Schema({
                vol.Optional("snapshot_name", default="Default"): cv.string,
            }),
        )


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    if unload_ok := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        hass.data[DOMAIN].pop(entry.entry_id, None)
    return unload_ok
