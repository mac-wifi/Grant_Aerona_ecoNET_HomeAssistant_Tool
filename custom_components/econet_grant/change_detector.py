"""Change detection for ecoNET parameters.

Compares editParams snapshots between polls, fires HA events when external
changes are detected, and maintains a write log for audit purposes.
"""

from __future__ import annotations

import logging
from copy import deepcopy
from dataclasses import dataclass
from typing import Any

from homeassistant.components.persistent_notification import async_create as pn_async_create
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import (
    BITMASK_SELECT_DEFINITIONS,
    CONF_PUSH_NOTIFICATIONS,
    CRITICAL_SYS_PARAMS,
    DEFAULT_PUSH_NOTIFICATIONS,
    DOMAIN,
    EVENT_SETTING_CHANGED,
    EVENT_SYS_PARAM_CHANGED,
    EVENT_URGENT_CHANGE,
    NUMBER_DEFINITIONS,
    SELECT_DEFINITIONS,
    URGENT_PARAMETERS,
    VOLATILE_PARAMETERS,
)

_LOGGER = logging.getLogger(__name__)


def _build_display_name_map() -> dict[str, str]:
    """Build API-param-name -> friendly display name from all entity definitions."""
    mapping: dict[str, str] = {}
    for api_key, defn in NUMBER_DEFINITIONS.items():
        mapping[api_key] = defn["name"]
    for api_key, defn in SELECT_DEFINITIONS.items():
        mapping[api_key] = defn["name"]
    for api_key, defn in BITMASK_SELECT_DEFINITIONS.items():
        mapping[api_key] = defn["name"]
    return mapping


_DISPLAY_NAMES = _build_display_name_map()


def _friendly(param_name: str) -> str:
    """Return the friendly display name for a parameter, falling back to the API name."""
    return _DISPLAY_NAMES.get(param_name, param_name)


def format_setting_change(name: str, old: Any, new: Any, *, bold: bool = False) -> str:
    """Format notification text only; never alter the raw change or write values."""
    def line(display: str, before: str, after: str) -> str:
        if bold:
            display = f"**{display}**"
        return f"{display}: {before} → {after}"

    def value_label(value: Any) -> str:
        if name in SELECT_DEFINITIONS:
            return SELECT_DEFINITIONS[name]["options"].get(
                _notification_integer(value), f"Unknown ({value!r})",
            )
        return str(value)

    definitions = [definition for definition in BITMASK_SELECT_DEFINITIONS.values()
                   if definition["settings_param_name"] == name]
    if definitions:
        before, after = _notification_integer(old), _notification_integer(new)
        if before is None or after is None or before < 0 or after < 0:
            # An invalid whole mask cannot safely be interpreted as bit states.
            return line(_friendly(name), f"Unknown ({old!r})", f"Unknown ({new!r})")
        changed = before ^ after
        known = 0
        lines = []
        for definition in definitions:
            mask = definition["bit_mask"]
            known |= mask
            if not changed & mask:
                continue

            def bit_label(value: int) -> str:
                on = bool(value & mask) != definition.get("on_clears_bit", False)
                return definition["on_label"] if on else definition["off_label"]

            lines.append(line(definition["name"], bit_label(before), bit_label(after)))
        unknown = changed & ~known
        if unknown:
            lines.append(line(
                f"{name} unknown bits ({unknown:#x})",
                f"{before & unknown:#x}", f"{after & unknown:#x}",
            ))
        if lines:
            return "; ".join(lines)
        # A representation-only change still needs a visible raw explanation.
        return line(_friendly(name), f"Raw ({old!r})", f"Raw ({new!r})")
    return line(_friendly(name), value_label(old), value_label(new))


def _notification_integer(value: Any) -> int | None:
    """Accept integral API values without truncating fractions or treating bools as modes."""
    if type(value) not in (int, float, str):
        return None
    try:
        integer = int(value)
    except (ValueError, OverflowError):
        return None
    if isinstance(value, float) and value != integer:
        return None
    return integer


@dataclass
class _RevertWrite:
    """One explicit Revert attempt, separate from legacy Restore markers."""

    index: str
    name: str
    before: int | float
    target: int | float
    active: bool = True


class ChangeDetector:
    """Detects external parameter changes between slow coordinator polls."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self._hass = hass
        self._entry = entry
        self._previous_snapshot: dict[str, Any] | None = None
        self._previous_sys_params: dict[str, Any] | None = None
        self._self_writes: set[str] = set()
        self._revert_writes: dict[str, _RevertWrite] = {}

    @property
    def _push_enabled(self) -> bool:
        return self._entry.options.get(
            CONF_PUSH_NOTIFICATIONS, DEFAULT_PUSH_NOTIFICATIONS
        )

    async def _async_send_push(self, title: str, message: str) -> None:
        """Send a push notification via notify.notify."""
        try:
            await self._hass.services.async_call(
                "notify", "notify",
                {"title": title, "message": message},
            )
        except Exception:
            _LOGGER.exception("Failed to send push notification")

    def mark_self_write(self, param_name: str) -> None:
        """Mark a parameter as being written by this integration."""
        self._self_writes.add(param_name)

    def clear_self_write(self, param_name: str) -> None:
        """Clear a self-write marker after the next poll confirms it."""
        self._self_writes.discard(param_name)

    def begin_revert(
        self, index: str, name: str, before: int | float, target: int | float,
    ) -> _RevertWrite:
        """Track an authorised attempt, not an acknowledgement of success."""
        write = _RevertWrite(index, name, before, target)
        self._revert_writes[name] = write
        return write

    def finish_revert(self, write: _RevertWrite) -> None:
        """After completion even an unchanged poll must retire the expectation."""
        write.active = False

    def _observed_reverts(self, current: dict[str, Any]) -> set[tuple[str, str]]:
        """Attribute only the exact transition; never swallow a different value.

        No-change polls during the HTTP operation may precede application. Once
        it finishes, the next populated poll consumes the expectation even if
        nothing changed. Restore's legacy markers intentionally remain separate.
        """
        matched = set()
        for name, write in list(self._revert_writes.items()):
            previous = (self._previous_snapshot or {}).get(write.index)
            observed = current.get(write.index)
            before = {"name": name, "value": write.before}
            target = {"name": name, "value": write.target}
            if (previous == before and observed == target
                    and sum(p["name"] == name for p in current.values()) == 1):
                matched.add((write.index, name))
            if not write.active or observed != before:
                self._revert_writes.pop(name, None)
        return matched

    def process_edit_params(self, edit_params: dict[str, Any]) -> list[dict[str, Any]]:
        """Compare current editParams.data to previous snapshot, fire events for changes.

        Returns a list of detected changes for logging/audit.
        """
        data = edit_params.get("data", {})
        if not data:
            _LOGGER.warning("Change detector: editParams has no 'data' key")
            return []

        current_snapshot = _extract_values(data)
        observed_reverts = self._observed_reverts(current_snapshot)

        if self._previous_snapshot is None:
            self._previous_snapshot = current_snapshot
            _LOGGER.info(
                "Change detector: initial snapshot captured (%d parameters)",
                len(current_snapshot),
            )
            return []

        _LOGGER.debug(
            "Change detector: comparing %d params (previous) vs %d params (current)",
            len(self._previous_snapshot), len(current_snapshot),
        )
        raw_changes = _diff_values(self._previous_snapshot, current_snapshot)
        self._previous_snapshot = current_snapshot

        _LOGGER.debug(
            "Change detector: %d raw change(s) found, %d after volatile filter",
            len(raw_changes),
            len([c for c in raw_changes if c["name"] not in VOLATILE_PARAMETERS]),
        )

        changes = [c for c in raw_changes if c["name"] not in VOLATILE_PARAMETERS]
        if not changes:
            return []

        all_changes: list[dict[str, Any]] = []
        for change in changes:
            param_name = change["name"]

            if (change["index"], param_name) in observed_reverts:
                change["source"] = "user"
                all_changes.append(change)
                continue

            if param_name in self._self_writes:
                _LOGGER.debug("Self-write confirmed for %s", param_name)
                self._self_writes.discard(param_name)
                change["source"] = "user"
                all_changes.append(change)
                continue

            change["source"] = "external"
            all_changes.append(change)
            _LOGGER.warning(
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
                    "- " + format_setting_change(
                        change["name"], change["old_value"], change["new_value"], bold=True,
                    )
                )
            message = "Settings changed externally:\n\n" + "\n".join(lines)
            try:
                pn_async_create(
                    self._hass,
                    message=message,
                    title="EcoNet Grant - Settings Changed",
                    notification_id=f"{DOMAIN}_external_changes",
                )
            except Exception:
                _LOGGER.exception("Failed to create persistent notification")

            if self._push_enabled:
                plain_lines = [
                    format_setting_change(c["name"], c["old_value"], c["new_value"])
                    for c in external_changes
                ]
                push_message = "Settings changed:\n" + "\n".join(plain_lines)
                self._hass.async_create_task(
                    self._async_send_push(
                        "EcoNet: Settings Changed", push_message
                    )
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
            if key in VOLATILE_PARAMETERS:
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
                logging.CRITICAL if severity == "critical" else logging.INFO,
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
                msg = (
                    "CRITICAL: remoteMenu has changed to true. "
                    "RM API endpoints may now be available. Investigate immediately."
                )
                pn_async_create(
                    self._hass,
                    message=f"**{msg}**",
                    title="EcoNet Grant - Remote Menu ENABLED",
                    notification_id=f"{DOMAIN}_remote_menu_alert",
                )
                if self._push_enabled:
                    self._hass.async_create_task(
                        self._async_send_push("URGENT: EcoNet Remote Menu", msg)
                    )

            if key == "alarms":
                msg = f"Alarm state changed: {new_value}"
                pn_async_create(
                    self._hass,
                    message=msg,
                    title="EcoNet Grant - Alarm Change",
                    notification_id=f"{DOMAIN}_alarm_change",
                )
                if self._push_enabled:
                    self._hass.async_create_task(
                        self._async_send_push("EcoNet: Alarm Change", msg)
                    )

            if key in CRITICAL_SYS_PARAMS:
                msg = (
                    f"CRITICAL: {key} changed from {old_value} to {new_value}. "
                    "This should never happen -- investigate immediately."
                )
                pn_async_create(
                    self._hass,
                    message=f"**{msg}**",
                    title="EcoNet Grant - Critical System Change",
                    notification_id=f"{DOMAIN}_critical_{key}",
                )
                if self._push_enabled:
                    self._hass.async_create_task(
                        self._async_send_push("URGENT: EcoNet Critical Change", msg)
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
