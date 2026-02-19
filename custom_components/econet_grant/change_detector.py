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
    DOMAIN,
    EVENT_SETTING_CHANGED,
    EVENT_URGENT_CHANGE,
    URGENT_PARAMETERS,
)

_LOGGER = logging.getLogger(__name__)


class ChangeDetector:
    """Detects external parameter changes between slow coordinator polls."""

    def __init__(self, hass: HomeAssistant) -> None:
        self._hass = hass
        self._previous_snapshot: dict[str, Any] | None = None
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

        changes = _diff_values(self._previous_snapshot, current_snapshot)
        self._previous_snapshot = current_snapshot

        if not changes:
            return []

        external_changes: list[dict[str, Any]] = []
        for change in changes:
            param_name = change["name"]

            if param_name in self._self_writes:
                _LOGGER.debug("Ignoring self-write for %s", param_name)
                self._self_writes.discard(param_name)
                continue

            external_changes.append(change)
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

        return external_changes


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
