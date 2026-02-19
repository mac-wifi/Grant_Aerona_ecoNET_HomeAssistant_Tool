"""EcoNet Grant Aerona integration for Home Assistant."""

from __future__ import annotations

import json
import logging
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
    CONF_SAFE_MODE,
    CONF_USERNAME,
    DEFAULT_SAFE_MODE,
    DOMAIN,
    SERVICE_API,
    SERVICE_COORDINATOR,
    SERVICE_SLOW_COORDINATOR,
)
from .coordinator import EconetFastCoordinator, EconetSlowCoordinator
from .guardian import Circuit1Guardian

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [
    Platform.SENSOR,
    Platform.NUMBER,
    Platform.BUTTON,
]

SERVICE_CHANGE_DETECTOR = "change_detector"
SERVICE_GUARDIAN = "guardian"


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

    change_detector = ChangeDetector(hass)
    guardian = Circuit1Guardian(hass, api, change_detector)

    # Process the initial slow data for change detection baseline
    if slow_coordinator.data:
        edit_params = slow_coordinator.data.get("editParams", {})
        change_detector.process_edit_params(edit_params)

    @callback
    def _on_slow_update() -> None:
        """Run change detection and guardian on slow coordinator updates."""
        if slow_coordinator.data is None:
            return
        edit_params = slow_coordinator.data.get("editParams", {})
        change_detector.process_edit_params(edit_params)
        hass.async_create_task(guardian.check_and_revert(edit_params))

    slow_coordinator.async_add_listener(_on_slow_update)

    hass.data[DOMAIN][entry.entry_id] = {
        SERVICE_API: api,
        SERVICE_COORDINATOR: fast_coordinator,
        SERVICE_SLOW_COORDINATOR: slow_coordinator,
        SERVICE_CHANGE_DETECTOR: change_detector,
        SERVICE_GUARDIAN: guardian,
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
        change_detector = hass.data[DOMAIN][entry.entry_id][SERVICE_CHANGE_DETECTOR]

        if not safe_mode:
            path = _snapshot_path(hass, name)
            if path.exists():
                snapshot = json.loads(path.read_text())
                for param in snapshot.get("parameters", {}).values():
                    if isinstance(param, dict) and "name" in param:
                        change_detector.mark_self_write(param["name"])

        result = await async_restore_settings(hass, api, snapshot_name=name, safe_mode=safe_mode)
        _LOGGER.info("Restore result: %s", result)

    async def handle_set_guardian(call: ServiceCall) -> None:
        temp = call.data.get("temperature")
        guardian = hass.data[DOMAIN][entry.entry_id][SERVICE_GUARDIAN]
        if temp is not None:
            guardian.set_desired_temp(float(temp))
        else:
            guardian.disable()

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

    if not hass.services.has_service(DOMAIN, "set_guardian_temp"):
        hass.services.async_register(
            DOMAIN,
            "set_guardian_temp",
            handle_set_guardian,
            schema=vol.Schema({
                vol.Optional("temperature"): vol.Coerce(float),
            }),
        )


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    if unload_ok := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        hass.data[DOMAIN].pop(entry.entry_id, None)
    return unload_ok
