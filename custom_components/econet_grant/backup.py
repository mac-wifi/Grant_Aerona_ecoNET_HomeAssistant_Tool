"""Settings backup and restore for EcoNet Grant Aerona.

Snapshots all editable parameters to JSON files in the HA config directory.
Supports multiple named snapshots (e.g. "Default", "Guest Mode").
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from homeassistant.core import HomeAssistant

from .api import EconetApi
from .const import CONF_SAFE_MODE, DEFAULT_SAFE_MODE, DOMAIN

_LOGGER = logging.getLogger(__name__)

SNAPSHOT_DIR_NAME = "econet_grant_snapshots"


def _snapshot_dir(hass: HomeAssistant) -> Path:
    """Return the snapshot directory, creating it if needed."""
    path = Path(hass.config.config_dir) / SNAPSHOT_DIR_NAME
    path.mkdir(exist_ok=True)
    return path


def _snapshot_path(hass: HomeAssistant, name: str) -> Path:
    safe_name = "".join(c if c.isalnum() or c in "._-" else "_" for c in name)
    return _snapshot_dir(hass) / f"{safe_name}.json"


async def async_backup_settings(
    hass: HomeAssistant,
    api: EconetApi,
    snapshot_name: str = "Default",
) -> bool:
    """Save all current editParams values to a named snapshot file."""
    edit_params = await api.fetch_edit_params()
    if edit_params is None:
        _LOGGER.error("Cannot backup: editParams fetch failed")
        return False

    data = edit_params.get("data", {})
    if not data:
        _LOGGER.error("Cannot backup: editParams.data is empty")
        return False

    snapshot = {
        "snapshot_name": snapshot_name,
        "editableParamsVer": edit_params.get("editableParamsVer"),
        "parameters": {},
    }

    for index, param in data.items():
        if isinstance(param, dict) and param.get("edit", False):
            snapshot["parameters"][index] = {
                "name": param.get("name"),
                "value": param.get("value"),
                "minv": param.get("minv"),
                "maxv": param.get("maxv"),
            }

    path = _snapshot_path(hass, snapshot_name)
    path.write_text(json.dumps(snapshot, indent=2))
    _LOGGER.info(
        "Saved snapshot '%s' with %d parameters to %s",
        snapshot_name, len(snapshot["parameters"]), path,
    )
    return True


async def async_restore_settings(
    hass: HomeAssistant,
    api: EconetApi,
    snapshot_name: str = "Default",
    safe_mode: bool = True,
) -> dict[str, Any]:
    """Restore settings from a named snapshot. Returns a summary dict.

    In safe mode, generates a report but does NOT write to the device.
    """
    path = _snapshot_path(hass, snapshot_name)
    if not path.exists():
        msg = f"Snapshot '{snapshot_name}' not found at {path}"
        _LOGGER.error(msg)
        return {"success": False, "error": msg}

    snapshot = json.loads(path.read_text())
    saved_params = snapshot.get("parameters", {})

    current_edit = await api.fetch_edit_params()
    if current_edit is None:
        return {"success": False, "error": "Cannot fetch current editParams"}

    current_data = current_edit.get("data", {})

    to_restore: list[dict[str, Any]] = []
    for index, saved in saved_params.items():
        current = current_data.get(index, {})
        current_val = current.get("value") if isinstance(current, dict) else None
        if current_val != saved["value"]:
            to_restore.append({
                "index": index,
                "name": saved["name"],
                "current_value": current_val,
                "restore_value": saved["value"],
            })

    if not to_restore:
        _LOGGER.info("Restore '%s': all parameters already match snapshot", snapshot_name)
        return {"success": True, "changes": 0, "details": []}

    if safe_mode:
        report_lines = [
            f"SAFE MODE: Would restore {len(to_restore)} parameter(s) from '{snapshot_name}':\n"
        ]
        for item in to_restore:
            report_lines.append(
                f"  {item['name']} (idx {item['index']}): "
                f"{item['current_value']} -> {item['restore_value']}"
            )
        report = "\n".join(report_lines)
        _LOGGER.warning(report)
        hass.components.persistent_notification.async_create(
            message=report,
            title="EcoNet Grant - Restore Preview (Safe Mode)",
            notification_id=f"{DOMAIN}_restore_preview",
        )
        return {"success": True, "safe_mode": True, "changes": len(to_restore), "details": to_restore}

    successes = 0
    failures = 0
    for item in to_restore:
        ok = await api.set_param_by_index(item["index"], item["restore_value"])
        if ok:
            successes += 1
        else:
            failures += 1
            _LOGGER.error("Failed to restore %s (idx %s)", item["name"], item["index"])

    _LOGGER.info(
        "Restore '%s' complete: %d succeeded, %d failed",
        snapshot_name, successes, failures,
    )
    return {
        "success": failures == 0,
        "changes": successes,
        "failures": failures,
        "details": to_restore,
    }


def list_snapshots(hass: HomeAssistant) -> list[str]:
    """Return names of all saved snapshots."""
    path = _snapshot_dir(hass)
    return [f.stem for f in path.glob("*.json")]
