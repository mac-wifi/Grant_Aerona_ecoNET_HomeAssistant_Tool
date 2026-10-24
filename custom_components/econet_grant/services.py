"""backup_settings / restore_settings services."""

from __future__ import annotations

import json
import logging

import voluptuous as vol

from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import config_validation as cv

from .backup import async_backup_settings, async_restore_settings, snapshot_path
from .const import DOMAIN, SERVICE_BACKUP_SETTINGS, SERVICE_RESTORE_SETTINGS
from .entity import EconetConfigEntry, EconetRuntimeData, is_safe_mode

_LOGGER = logging.getLogger(__name__)

BACKUP_SCHEMA = vol.Schema({vol.Required("snapshot_name", default="Default"): cv.string})
RESTORE_SCHEMA = vol.Schema({vol.Optional("snapshot_name", default="Default"): cv.string})


def _loaded_entry(hass: HomeAssistant) -> EconetConfigEntry:
    """The integration supports one heat pump; use its loaded entry."""
    for entry in hass.config_entries.async_loaded_entries(DOMAIN):
        return entry
    raise HomeAssistantError("EcoNet Grant is not loaded")


async def async_handle_backup(hass: HomeAssistant, call: ServiceCall) -> None:
    entry = _loaded_entry(hass)
    name = call.data.get("snapshot_name", "Default")
    await async_backup_settings(hass, entry.runtime_data.api, snapshot_name=name)


async def async_handle_restore(hass: HomeAssistant, call: ServiceCall) -> None:
    entry = _loaded_entry(hass)
    data: EconetRuntimeData = entry.runtime_data
    name = call.data.get("snapshot_name", "Default")
    safe_mode = is_safe_mode(entry)
    if not safe_mode:
        await _async_mark_restore_writes(hass, data, name)
    result = await async_restore_settings(
        hass, data.api, snapshot_name=name, safe_mode=safe_mode,
    )
    _LOGGER.info("Restore result: %s", result)


async def _async_mark_restore_writes(
    hass: HomeAssistant, data: EconetRuntimeData, name: str,
) -> None:
    """Pre-mark and audit every snapshot parameter as a restore write.

    Known, deliberately deferred defect (#11): this marks parameters that the
    restore will not actually write, which can suppress a later guest alert.
    """
    path = snapshot_path(hass, name)
    if not path.exists():
        return
    snapshot = json.loads(path.read_text())
    for idx, param in snapshot.get("parameters", {}).items():
        if isinstance(param, dict) and "name" in param:
            data.change_detector.mark_self_write(param["name"])
            await data.database.async_log_change(
                hass,
                {"name": param["name"], "index": idx,
                 "old_value": "", "new_value": param.get("value", "")},
                source="restore",
            )


def async_register_services(hass: HomeAssistant) -> None:
    """Register the integration services once."""
    if not hass.services.has_service(DOMAIN, SERVICE_BACKUP_SETTINGS):
        async def handle_backup(call: ServiceCall) -> None:
            await async_handle_backup(hass, call)

        hass.services.async_register(
            DOMAIN, SERVICE_BACKUP_SETTINGS, handle_backup, schema=BACKUP_SCHEMA,
        )
    if not hass.services.has_service(DOMAIN, SERVICE_RESTORE_SETTINGS):
        async def handle_restore(call: ServiceCall) -> None:
            await async_handle_restore(hass, call)

        hass.services.async_register(
            DOMAIN, SERVICE_RESTORE_SETTINGS, handle_restore, schema=RESTORE_SCHEMA,
        )
