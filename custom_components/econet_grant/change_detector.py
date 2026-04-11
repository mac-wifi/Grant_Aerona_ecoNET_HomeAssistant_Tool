"""Change detection for ecoNET parameters.

Compares editParams snapshots between polls, fires HA events when external
changes are detected, and maintains a write log for audit purposes.
"""

from __future__ import annotations

import logging
from copy import deepcopy
from typing import Any

from homeassistant.core import HomeAssistant

from .const import (
    CRITICAL_SYS_PARAMS,
    DOMAIN,
    EVENT_SETTING_CHANGED,
    EVENT_SYS_PARAM_CHANGED,
    EVENT_URGENT_CHANGE,
    URGENT_PARAMETERS,
    VOLATILE_PARAMETERS,
    VOLATILE_SYS_PARAMS,
)

_LOGGER = logging.getLogger(__name__)


class ChangeDetector:
    """Detects external parameter changes between slow coordinator polls."""

    def __init__(self, hass: HomeAssistant) -> None:
        self._hass = hass
        self._previous_snapshot: dict[str, Any] | None = None
        self._previous_sys_params: dict[str, Any] | None = None
        self._self_writes: set[str] = set()

    def mark_self_write(self, param_name: str) -> None:
        """Mark a parameter as being written by this integration."""
        self._self_writes.add(param_name)

    def clear_self_write(self, param_name: str) -> None:
        """Clear a self-write marker after the next poll confirms it."""
        self._self_writes.discard(param_name)

    def process_edit_params(self, edit_params: dict[str, Any]) -> list[dict[str, Any]]:
        """Compare current editParams.data to previous snapshot, fire events for changes.

        Returns a list of detected changes for logging/audit.
        """
        data = edit_params.get("data", {})
        if not data:
            return []

        current_snapshot = _extract_values(data)

        if self._previous_snapshot is None:
            self._previous_snapshot = current_snapshot
            _LOGGER.info("Change detector: initial snapshot captured (%d parameters)", len(current_snapshot))
            return []

        raw_changes = _diff_values(self._previous_snapshot, current_snapshot)
        self._previous_snapshot = current_snapshot

        changes = [c for c in raw_changes if c["name"] not in VOLATILE_PARAMETERS]
        if not changes:
            return []

        all_changes: list[dict[str, Any]] = []
        for change in changes:
            param_name = change["name"]

            if param_name in self._self_writes:
                _LOGGER.debug("Self-write confirmed for %s", param_name)
                self._self_writes.discard(param_name)
                change["source"] = "user"
                all_changes.append(change)
                continue

            change["source"] = "external"
            all_changes.append(change)
            _LOGGER.info(
                "External change detected: %s changed from %s to %s",
                param_name, change["old_value"], change["new_value"],
            )

            event_data = {
                "param_name": param_name,
                "param_index": change["index"],
                "old_value": change["old_value"],
                "new_value": change["new_value"],
            }

            self._hass.bus.async_fire(EVENT_SETTING_CHANGED, event_data)

            if param_name in URGENT_PARAMETERS:
                self._hass.bus.async_fire(EVENT_URGENT_CHANGE, event_data)
                _LOGGER.warning("URGENT change: %s", param_name)

        external_changes = [c for c in all_changes if c.get("source") == "external"]
        if external_changes:
            lines = []
            for change in external_changes:
                lines.append(
                    f"- **{change['name']}**: {change['old_value']} → {change['new_value']}"
                )
            message = "Settings changed externally:\n\n" + "\n".join(lines)
            self._hass.components.persistent_notification.async_create(
                message=message,
                title="EcoNet Grant - Settings Changed",
                notification_id=f"{DOMAIN}_external_changes",
            )

        return all_changes


    def process_sys_params(self, sys_params: dict[str, Any]) -> list[dict[str, Any]]:
        """Compare current sysParams to previous snapshot, fire events for changes.

        Returns a list of detected changes for logging/audit.
        """
        if not sys_params:
            return []

        if self._previous_sys_params is None:
            self._previous_sys_params = deepcopy(sys_params)
            _LOGGER.info("Change detector: initial sysParams snapshot captured")
            return []

        changes: list[dict[str, Any]] = []
        for key, new_value in sys_params.items():
            if key in VOLATILE_SYS_PARAMS:
                continue
            old_value = self._previous_sys_params.get(key)
            if old_value == new_value:
                continue

            change = {
                "name": key,
                "index": None,
                "old_value": old_value,
                "new_value": new_value,
                "source": "external",
            }
            changes.append(change)

            severity = "critical" if key in CRITICAL_SYS_PARAMS else "info"
            _LOGGER.log(
                logging.CRITICAL if severity == "critical" else logging.WARNING,
                "sysParams change: %s: %s -> %s",
                key, old_value, new_value,
            )

            self._hass.bus.async_fire(EVENT_SYS_PARAM_CHANGED, {
                "param_name": key,
                "old_value": old_value,
                "new_value": new_value,
                "severity": severity,
            })

            if key == "remoteMenu" and str(new_value).lower() == "true":
                self._hass.components.persistent_notification.async_create(
                    message=(
                        "**CRITICAL:** `remoteMenu` has changed to `true`. "
                        "RM API endpoints may now be available. Investigate immediately."
                    ),
                    title="EcoNet Grant - Remote Menu ENABLED",
                    notification_id=f"{DOMAIN}_remote_menu_alert",
                )

            if key == "alarms":
                self._hass.components.persistent_notification.async_create(
                    message=f"Alarm state changed: {new_value}",
                    title="EcoNet Grant - Alarm Change",
                    notification_id=f"{DOMAIN}_alarm_change",
                )

            if key in CRITICAL_SYS_PARAMS:
                self._hass.components.persistent_notification.async_create(
                    message=(
                        f"**CRITICAL:** `{key}` changed from `{old_value}` to `{new_value}`. "
                        "This should never happen -- investigate immediately."
                    ),
                    title="EcoNet Grant - Critical System Change",
                    notification_id=f"{DOMAIN}_critical_{key}",
                )

        self._previous_sys_params = deepcopy(sys_params)
        return changes


def _extract_values(data: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Extract param_index -> {name, value} from editParams.data."""
    snapshot: dict[str, dict[str, Any]] = {}
    for index, param in data.items():
        if isinstance(param, dict) and "name" in param:
            snapshot[index] = {
                "name": param["name"],
                "value": param.get("value"),
            }
    return snapshot


def _diff_values(
    old: dict[str, dict[str, Any]],
    new: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    """Return list of changed parameters between two snapshots."""
    changes: list[dict[str, Any]] = []
    for index, new_param in new.items():
        old_param = old.get(index)
        if old_param is None:
            continue
        if old_param["value"] != new_param["value"]:
            changes.append({
                "index": index,
                "name": new_param["name"],
                "old_value": old_param["value"],
                "new_value": new_param["value"],
            })
    return changes
