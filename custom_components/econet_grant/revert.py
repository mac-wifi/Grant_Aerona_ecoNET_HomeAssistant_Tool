"""Entry-local, single-use mobile actions. Never write on change detection."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import logging
from math import isfinite
import re
from time import monotonic
from uuid import uuid4

from homeassistant.components.persistent_notification import async_create as pn_async_create

from .const import (
    CONF_PUSH_NOTIFICATIONS, CONF_SAFE_MODE, DEFAULT_PUSH_NOTIFICATIONS,
    DEFAULT_SAFE_MODE, DOMAIN, NUMBER_DEFINITIONS, SELECT_DEFINITIONS,
    VOLATILE_PARAMETERS,
)

_LOGGER = logging.getLogger(__name__)
CONF_REVERT_NOTIFY_SERVICE = "revert_notify_service"
MAX_PENDING = 32
ACTION_TTL = 900  # seconds; no persisted actions survive reload/restart


def valid_notify_service(value: str) -> bool:
    """Only a specifically selected Companion App service may receive actions."""
    return isinstance(value, str) and re.fullmatch(r"mobile_app_[a-z0-9_]+", value) is not None


def _valid_value(name, value):
    if type(value) not in (int, float) or not isfinite(value):
        return False
    if name in NUMBER_DEFINITIONS:
        definition = NUMBER_DEFINITIONS[name]
        return definition["min_value"] <= value <= definition["max_value"]
    return name in SELECT_DEFINITIONS and value in SELECT_DEFINITIONS[name]["options"]


@dataclass(frozen=True)
class PendingRevert:
    index: str
    name: str
    old_value: int | float
    new_value: int | float
    expires: float


class RevertActions:
    """Trust only snapshots from our coordinator, not setting-change events."""

    def __init__(self, hass, entry, api, db, change_detector):
        self._hass, self._entry, self._api, self._db = hass, entry, api, db
        self._change_detector = change_detector
        self._previous = {}
        self._pending: dict[str, PendingRevert] = {}
        self._active = False
        self._unsubscribe = None
        self._generation = 0

    def start(self):
        self._active = True
        self._unsubscribe = self._hass.bus.async_listen(
            "mobile_app_notification_action", self._handle_action
        )

    def close(self):
        self._active = False
        self._pending.clear()
        self._previous.clear()
        if self._unsubscribe:
            self._unsubscribe()
            self._unsubscribe = None

    def _enabled(self):
        return self._entry.options.get(CONF_PUSH_NOTIFICATIONS, DEFAULT_PUSH_NOTIFICATIONS)

    def observe(self, edit_params, changes):
        """Invalidate superseded actions on every poll, then offer external changes."""
        self._generation += 1
        current = deepcopy(edit_params.get("data", {}))
        now = monotonic()
        for token, pending in list(self._pending.items()):
            if pending.expires <= now or not self._matches(current, pending):
                self._pending.pop(token, None)
        previous, self._previous = self._previous, current
        service = self._entry.options.get(CONF_REVERT_NOTIFY_SERVICE, "")
        if not self._active or not self._enabled() or not valid_notify_service(service):
            return
        for change in changes:
            name, index = change["name"], change["index"]
            old, new = change["old_value"], change["new_value"]
            if (change.get("source") != "external" or name in VOLATILE_PARAMETERS
                    or not _valid_value(name, old) or not _valid_value(name, new)):
                continue
            pending = PendingRevert(index, name, old, new, now + ACTION_TTL)
            # Index reuse/rename and duplicate names must not turn one setting's
            # previous value into a write to another setting.
            before = previous.get(index, {})
            if (before.get("name") != name or before.get("value") != old
                    or not self._matches(current, pending)
                    or sum(isinstance(p, dict) and p.get("name") == name
                           for p in previous.values()) != 1):
                continue
            for token, existing in list(self._pending.items()):
                if existing.name == name:
                    self._pending.pop(token, None)
            if len(self._pending) >= MAX_PENDING:
                self._pending.pop(next(iter(self._pending)))
            token = f"{DOMAIN}_revert_{uuid4().hex}"
            self._pending[token] = pending
            self._hass.async_create_task(self._send(service, token, pending))

    @staticmethod
    def _matches(data, pending):
        if not isinstance(data, dict):
            return False
        param = data.get(pending.index)
        return (isinstance(param, dict) and param.get("name") == pending.name
                and param.get("edit") is True
                and all(type(param.get(key)) in (int, float)
                        and isfinite(param[key]) for key in ("minv", "maxv"))
                and param["minv"] <= pending.old_value <= param["maxv"]
                and type(param.get("value")) in (int, float)
                and param["value"] == pending.new_value
                and sum(isinstance(p, dict) and p.get("name") == pending.name
                        for p in data.values()) == 1)

    async def _send(self, service, token, pending):
        if not self._active or token not in self._pending:
            return
        try:
            await self._hass.services.async_call("notify", service, {
                "title": "EcoNet: Revert setting?",
                "message": f"{pending.name}: {pending.old_value} → {pending.new_value}",
                "data": {"actions": [{"action": token, "title": "Revert"}]},
            }, blocking=True)
        except Exception:
            self._pending.pop(token, None)
            _LOGGER.exception("Could not deliver EcoNet revert action; persistent alert retained")

    def _notice(self, message):
        pn_async_create(self._hass, title="EcoNet: Manual revert", message=message,
                        notification_id=f"{DOMAIN}_revert_{self._entry.entry_id}")

    async def _handle_action(self, event):
        token = event.data.get("action")
        if not self._active or not isinstance(token, str):
            return
        # Consume before any await: duplicate taps cannot start another operation.
        # The API's bounded timeout retries may resend this same name/value.
        pending = self._pending.pop(token, None)
        if pending is None:
            return
        if (pending.expires <= monotonic() or not self._enabled()
                or self._entry.options.get(CONF_SAFE_MODE, DEFAULT_SAFE_MODE)):
            self._notice("Revert blocked: Safe Mode, disabled notifications or expired action. Check the dashboard.")
            return
        try:
            generation = self._generation
            fresh = await self._api.fetch_edit_params()
            if (not self._active or pending.expires <= monotonic()
                    or generation != self._generation
                    or self._entry.options.get(CONF_SAFE_MODE, DEFAULT_SAFE_MODE)
                    or not self._enabled()):
                return
            if not fresh or not self._matches(fresh.get("data", {}), pending):
                self._notice("Revert cancelled: setting changed or could not be verified. Check the dashboard.")
                return
            write = self._change_detector.begin_revert(
                pending.index, pending.name, pending.new_value, pending.old_value,
            )
            try:
                success = await self._api.set_param(pending.name, pending.old_value)
            finally:
                self._change_detector.finish_revert(write)
            if not success:
                self._notice("Revert not confirmed. Check the controller state before trying again.")
                return
            await self._db.async_log_change(self._hass, {
                "name": pending.name, "index": pending.index,
                "old_value": pending.new_value, "new_value": pending.old_value,
            }, source="revert")
            self._notice("Revert accepted by the API. The next settings poll will show the observed state.")
        except Exception:
            _LOGGER.exception("Manual EcoNet revert failed")
            self._notice("Revert failed or could not be confirmed. Check the controller state before trying again.")
