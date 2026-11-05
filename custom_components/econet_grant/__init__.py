"""EcoNet Grant Aerona integration for Home Assistant.

Notify-only by design: the integration reports setting changes and never
reverts them automatically. Manual Revert needs an explicit owner tap.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from . import discovery
from .api import AuthError, EconetApi, make_api
from .change_detector import ChangeDetector
from .const import (
    CONF_HOST,
    CONF_PASSWORD,
    CONF_RETENTION_DAYS,
    CONF_USERNAME,
    DATA_RETENTION_DAYS,
    DATABASE_FILENAME,
    DOMAIN,
)
from .coordinator import EconetFastCoordinator, EconetSlowCoordinator
from .database import EconetDatabase
from .entity import EconetConfigEntry, EconetRuntimeData
from .repairs import async_report_failure, async_report_success, issue_id
from .revert import RevertActions
from .services import async_register_services

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [
    Platform.SENSOR,
    Platform.NUMBER,
    Platform.SELECT,
    Platform.BUTTON,
]

# regParams counters that change when the controller's settings change.
VERSION_KEYS = ("settingsVer", "editableParamsVer", "schedulesVer")


async def async_setup_entry(hass: HomeAssistant, entry: EconetConfigEntry) -> bool:
    """Set up EcoNet Grant Aerona from a config entry."""
    api = await _async_connect(hass, entry)

    fast = EconetFastCoordinator(hass, api, entry)
    slow = EconetSlowCoordinator(hass, api, entry)
    await fast.async_config_entry_first_refresh()
    await slow.async_config_entry_first_refresh()

    db = EconetDatabase(Path(hass.config.config_dir) / DATABASE_FILENAME)
    await db.async_setup(hass)
    await db.async_purge_old_data(
        hass, entry.options.get(CONF_RETENTION_DAYS, DATA_RETENTION_DAYS)
    )

    change_detector = ChangeDetector(hass, entry)
    revert_actions = RevertActions(hass, entry, api, db, change_detector)
    data = EconetRuntimeData(api, fast, slow, db, change_detector, revert_actions)

    await _async_record_baseline(hass, data)
    entry.async_on_unload(fast.async_add_listener(_fast_update_listener(hass, data)))
    entry.async_on_unload(slow.async_add_listener(_slow_update_listener(hass, data)))
    entry.runtime_data = data

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_create_background_task(
        hass,
        discovery.async_register_controller_mac(hass, entry, api),
        "econet_grant_register_mac",
    )
    revert_actions.start()
    entry.async_on_unload(revert_actions.close)
    async_register_services(hass)
    entry.async_on_unload(entry.add_update_listener(_async_options_updated))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: EconetConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_remove_entry(hass: HomeAssistant, entry: EconetConfigEntry) -> None:
    """Drop the unreachable-controller issue along with the entry."""
    hass.data.get(f"{DOMAIN}_connection_failures", {}).pop(entry.entry_id, None)
    ir.async_delete_issue(hass, DOMAIN, issue_id(entry))


async def _async_options_updated(hass: HomeAssistant, entry: EconetConfigEntry) -> None:
    """Reload so changed polling/notification options take effect immediately."""
    await hass.config_entries.async_reload(entry.entry_id)


async def _async_connect(hass: HomeAssistant, entry: EconetConfigEntry) -> EconetApi:
    host = entry.data[CONF_HOST]
    try:
        api = await make_api(
            async_get_clientsession(hass), host,
            entry.data[CONF_USERNAME], entry.data[CONF_PASSWORD],
        )
    except AuthError as err:
        # The controller answered, so it is reachable: clear any stale outage.
        async_report_success(hass, entry)
        raise ConfigEntryAuthFailed("Invalid credentials") from err
    except Exception as err:
        async_report_failure(hass, entry)
        raise ConfigEntryNotReady(f"Cannot connect to {host}") from err
    async_report_success(hass, entry)
    return api


async def _async_record_baseline(hass: HomeAssistant, data: EconetRuntimeData) -> None:
    """Seed change detection and record the first poll of each endpoint."""
    fast_data, slow_data = data.fast_coordinator.data, data.slow_coordinator.data
    if slow_data:
        edit_params = slow_data.get("editParams", {})
        data.change_detector.process_edit_params(edit_params)
        data.change_detector.process_sys_params(slow_data.get("sysParams", {}))
        data.revert_actions.observe(edit_params, [])
    if fast_data:
        await data.database.async_record_readings(hass, fast_data)
    if slow_data:
        if edit_params := slow_data.get("editParams", {}):
            await data.database.async_record_settings(hass, edit_params)
        if sys_params := slow_data.get("sysParams", {}):
            await data.database.async_record_sys_params(hass, sys_params)


def _fast_update_listener(hass: HomeAssistant, data: EconetRuntimeData):
    """Record readings; refresh settings early when a version counter moves.

    This is what makes guest changes visible within one fast poll (~5 min)
    rather than waiting for the slow settings poll.
    """
    fast, slow = data.fast_coordinator, data.slow_coordinator
    last: dict[str, Any] = {key: (fast.data or {}).get(key) for key in VERSION_KEYS}

    @callback
    def _on_fast_update() -> None:
        if fast.data is None:
            return
        hass.async_create_task(data.database.async_record_readings(hass, fast.data))
        changed = False
        for key in VERSION_KEYS:
            new = fast.data.get(key)
            if new is not None and new != last[key]:
                _LOGGER.info("%s changed: %s -> %s, refreshing settings", key, last[key], new)
                last[key] = new
                changed = True
        if changed:
            hass.async_create_task(slow.async_request_refresh())

    return _on_fast_update


def _slow_update_listener(hass: HomeAssistant, data: EconetRuntimeData):
    """Run change detection, offer manual Revert actions and record settings."""
    slow, db, detector = data.slow_coordinator, data.database, data.change_detector

    @callback
    def _on_slow_update() -> None:
        if slow.data is None:
            _LOGGER.debug("Slow coordinator update: data is None, skipping")
            return
        edit_params = slow.data.get("editParams", {})
        sys_params = slow.data.get("sysParams", {})

        try:
            changes = detector.process_edit_params(edit_params)
            data.revert_actions.observe(edit_params, changes)
            for change in changes:
                source = change.get("source", "external")
                hass.async_create_task(db.async_log_change(hass, change, source))
        except Exception:
            _LOGGER.exception("Error in editParams change detection")

        try:
            for change in detector.process_sys_params(sys_params):
                source = change.pop("source", "external")
                hass.async_create_task(db.async_log_change(hass, change, source))
        except Exception:
            _LOGGER.exception("Error in sysParams change detection")

        hass.async_create_task(db.async_record_settings(hass, edit_params))
        if sys_params:
            hass.async_create_task(db.async_record_sys_params(hass, sys_params))

    return _on_slow_update
