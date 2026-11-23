"""Opt-in auto-revert of protected settings changed outside Home Assistant.

Reference: the Default snapshot, plus overrides for settings this integration
wrote itself (Home Assistant changes stick). Off by default. Settings without
an entity definition, CH Day Temp, HW Boost and volatile values are never
candidates (``const.AUTO_REVERT_CANDIDATES``).
"""

from __future__ import annotations

from dataclasses import dataclass, field
import json
import logging
from math import isfinite
from time import monotonic
from typing import Any

from homeassistant.components.persistent_notification import async_dismiss as pn_async_dismiss
from homeassistant.core import callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.storage import Store

from .backup import snapshot_path
from .const import (
    AUTO_REVERT_CANDIDATES,
    AUTO_REVERT_SNAPSHOT,
    CONF_AUTO_REVERT,
    DEFAULT_AUTO_REVERT,
    DOMAIN,
    NUMBER_DEFINITIONS,
    SELECT_DEFINITIONS,
    SIGNAL_SNAPSHOT_SAVED,
)
from .entity import is_safe_mode

_LOGGER = logging.getLogger(__name__)

GRACE_SECONDS = 300  # no automatic write until 5 minutes after load (owner decision D4)
TOLERANCE = 0.05  # number settings step by 0.1
STORE_VERSION = 1
NOTICE_PREFIX = "auto_revert"  # the detector's alert adds the "econet_grant_" prefix


def _number(value: Any) -> bool:
    return type(value) in (int, float) and isfinite(value)


def _integral(value: Any) -> bool:
    return _number(value) and value == int(value)


def target_valid(name: str, value: Any) -> bool:
    """Check C, type part: may this value ever be sent for this setting?"""
    candidate = AUTO_REVERT_CANDIDATES[name]
    if candidate["kind"] == "number":
        return _number(value) and candidate["min_value"] <= value <= candidate["max_value"]
    if candidate["kind"] == "select":
        return _integral(value) and int(value) in candidate["options"]
    return _integral(value) and value >= 0


def eligibility_problem(
    data: dict[str, Any], name: str, *, snapshot: bool = False,
) -> str | None:
    """Check A: the parameter is where, and what, the definition expects.

    Snapshot files hold only editable settings and no ``edit`` flag.
    """
    index = AUTO_REVERT_CANDIDATES[name]["param_index"]
    param = data.get(index)
    if not isinstance(param, dict):
        return f"index {index} missing"
    if param.get("name") != name:
        return f"index {index} is now named {param.get('name')!r}"
    if sum(isinstance(p, dict) and p.get("name") == name for p in data.values()) != 1:
        return "name appears more than once"
    if not snapshot and param.get("edit") is not True:
        return "not editable"
    return None


@dataclass(frozen=True)
class Divergence:
    """A protected setting that differs from its target on one poll."""

    name: str
    index: str
    observed: int | float
    target: int | float
    known: bool  # False: unrecognised select value or invalid mask, never overwritten


@dataclass
class _OwnWrites:
    """Overlapping Home Assistant writes to one parameter (per-operation count)."""

    count: int = 0
    settled_after: float = 0.0  # judge only polls that started after this
    values: list = field(default_factory=list)  # completed values, oldest first
    failed: bool = False


@dataclass
class OwnWrite:
    """Token for one own-write operation."""

    name: str
    value: int | float


class AutoRevert:
    """Baseline, overrides and judgement for one config entry."""

    def __init__(self, hass, entry, api, db, change_detector) -> None:
        self._hass, self._entry, self._api, self._db = hass, entry, api, db
        self._detector = change_detector
        self._store = Store(hass, STORE_VERSION, f"{DOMAIN}.auto_revert.{entry.entry_id}")
        self._snapshot_targets: dict[str, int | float] = {}
        self._overrides: dict[str, int | float] = {}
        self.unprotected: dict[str, str] = {}
        self.snapshot_date: str | None = None
        self.snapshot_usable = False
        self.revision = 0  # bumped whenever a queued decision must be dropped
        self._unsubscribe = None
        self._active = False
        self._own: dict[str, _OwnWrites] = {}
        self._pauses = 0
        self._resume_after = 0.0

    # --- state ---

    @property
    def enabled(self) -> bool:
        return self._entry.options.get(CONF_AUTO_REVERT, DEFAULT_AUTO_REVERT)

    @property
    def effect(self) -> str:
        if not self.enabled:
            return "off"
        if not self.snapshot_usable:
            return "no usable snapshot"
        if is_safe_mode(self._entry):
            return "reporting only (Safe Mode on)"
        return "active"

    @property
    def targets(self) -> dict[str, int | float]:
        """Effective target per protected setting: override, else snapshot value."""
        return {name: self._overrides.get(name, value)
                for name, value in self._snapshot_targets.items()}

    # --- lifecycle ---

    async def async_load(self) -> None:
        stored = await self._store.async_load() or {}
        self._overrides = {name: value for name, value in stored.get("overrides", {}).items()
                           if name in AUTO_REVERT_CANDIDATES and target_valid(name, value)}
        await self._async_load_snapshot()
        self._unsubscribe = async_dispatcher_connect(
            self._hass, SIGNAL_SNAPSHOT_SAVED, self._on_snapshot_saved)
        self._active = True

    def close(self) -> None:
        self._active = False
        self.revision += 1
        if self._unsubscribe:
            self._unsubscribe()
            self._unsubscribe = None

    @callback
    def _on_snapshot_saved(self, name: str) -> None:
        if name != AUTO_REVERT_SNAPSHOT:
            return
        # The new snapshot contains the owner's Home Assistant changes.
        self.revision += 1
        self._overrides.clear()
        self._entry.async_create_task(self._hass, self._async_snapshot_saved(),
                                      "econet_grant_auto_revert_snapshot")

    async def _async_snapshot_saved(self) -> None:
        await self._async_save_overrides()
        await self._async_load_snapshot()

    async def _async_load_snapshot(self) -> None:
        path = snapshot_path(self._hass, AUTO_REVERT_SNAPSHOT)

        def read() -> dict[str, Any] | None:
            try:
                return json.loads(path.read_text())
            except (OSError, ValueError):
                return None

        snapshot = await self._hass.async_add_executor_job(read)
        self.revision += 1
        self._snapshot_targets, self.unprotected = {}, {}
        params = snapshot.get("parameters") if isinstance(snapshot, dict) else None
        self.snapshot_usable = isinstance(params, dict) and bool(params)
        self.snapshot_date = snapshot.get("created_at") if self.snapshot_usable else None
        if not self.snapshot_usable:
            if self.enabled:
                self._notify("no_snapshot", "Auto-revert: no usable Default snapshot",
                             "Auto-revert is on, but there is no usable Default snapshot, "
                             "so nothing is protected. Take a Default snapshot "
                             "(Snapshot & Backup on the dashboard).")
            return
        pn_async_dismiss(self._hass, f"{DOMAIN}_{NOTICE_PREFIX}_no_snapshot")
        for name, candidate in AUTO_REVERT_CANDIDATES.items():
            problem = eligibility_problem(params, name, snapshot=True)
            value = (params.get(candidate["param_index"]) or {}).get("value")
            if problem is None and not target_valid(name, value):
                problem = f"snapshot value {value!r} is not a valid setting"
            if problem:
                self.unprotected[name] = problem
                continue
            if candidate["kind"] == "mask":
                value = int(value) & candidate["labelled_bits"]
            self._snapshot_targets[name] = value
        for name, reason in self.unprotected.items():
            _LOGGER.info("Auto-revert: %s not protected (%s)", name, reason)

    # --- overrides (Home Assistant changes stick) ---

    async def async_record_override(self, name: str, raw_value: int | float) -> None:
        """Remember a value this integration wrote; drop it if it equals the snapshot."""
        candidate = AUTO_REVERT_CANDIDATES.get(name)
        if candidate is None or not target_valid(name, raw_value):
            return
        value = int(raw_value) & candidate["labelled_bits"] if candidate["kind"] == "mask" \
            else raw_value
        if name in self._snapshot_targets and self._same(name, value,
                                                         self._snapshot_targets[name]):
            self._overrides.pop(name, None)
        else:
            self._overrides[name] = value
        await self._async_save_overrides()

    async def async_clear_overrides(self) -> None:
        self._overrides.clear()
        await self._async_save_overrides()

    async def _async_save_overrides(self) -> None:
        await self._store.async_save({"overrides": dict(self._overrides)})

    # --- hooks: own writes, Restore pause ---

    def begin_own_write(self, name: str, value: int | float) -> OwnWrite:
        """Before a Home Assistant write: drop queued decisions, hold this parameter."""
        self.revision += 1
        if name in AUTO_REVERT_CANDIDATES:  # others are never judged
            self._own.setdefault(name, _OwnWrites()).count += 1
        return OwnWrite(name, value)

    async def async_finish_own_write(self, write: OwnWrite, ok: bool) -> None:
        """In a ``finally``: the last acknowledged completion wins."""
        state = self._own.get(write.name)
        if state is None:
            return
        state.count -= 1
        state.settled_after = monotonic()
        state.values.append(write.value)
        state.failed = state.failed or not ok
        if ok:
            await self.async_record_override(write.name, write.value)
        if state.count == 0 and not state.failed:
            self._own.pop(write.name, None)

    def held(self, name: str) -> bool:
        """An own write is in flight, or its outcome is not yet judged."""
        return name in self._own

    async def _async_settle_own_writes(self, data: dict[str, Any], started_at: float) -> None:
        """After a failed or timed-out write, adopt what a later poll shows."""
        for name, state in list(self._own.items()):
            if state.count or started_at <= state.settled_after:
                continue
            self._own.pop(name)
            if not state.failed or eligibility_problem(data, name):
                continue
            observed = data[AUTO_REVERT_CANDIDATES[name]["param_index"]].get("value")
            for value in reversed(state.values):
                if _number(observed) and self._same_raw(name, observed, value):
                    await self.async_record_override(name, value)
                    break

    def pause(self) -> None:
        """Restore starts: nothing is sent and queued decisions are dropped."""
        self._pauses += 1
        self.revision += 1

    def resume(self) -> None:
        self._pauses -= 1
        self.revision += 1
        self._resume_after = monotonic()

    @property
    def paused(self) -> bool:
        return self._pauses > 0

    def _same_raw(self, name: str, observed: int | float, value: int | float) -> bool:
        candidate = AUTO_REVERT_CANDIDATES[name]
        if candidate["kind"] == "mask":
            bits = candidate["labelled_bits"]
            return _integral(observed) and int(observed) & bits == int(value) & bits
        return self._same(name, observed, value)

    # --- per poll ---

    def judgeable(self, started_at: float) -> bool:
        """Only polls that started after the last Restore ended, and not while paused."""
        return self._active and not self.paused and started_at > self._resume_after

    async def async_observe(self, edit_params: dict[str, Any], started_at: float) -> None:
        """Called after change detection on every settings poll."""
        if not self._active:
            return
        data = edit_params.get("data", {})
        if not isinstance(data, dict) or not data:
            return
        await self._async_settle_own_writes(data, started_at)

    # --- judgement ---

    @staticmethod
    def _same(name: str, a: int | float, b: int | float) -> bool:
        if AUTO_REVERT_CANDIDATES[name]["kind"] == "number":
            return abs(a - b) <= TOLERANCE
        return a == b

    def divergences(self, data: dict[str, Any]) -> list[Divergence]:
        """Check B: protected settings whose observed value differs from the target."""
        found = []
        for name, target in self.targets.items():
            candidate = AUTO_REVERT_CANDIDATES[name]
            if eligibility_problem(data, name):
                continue
            index = candidate["param_index"]
            observed = data[index].get("value")
            kind = candidate["kind"]
            if kind == "number":
                if not _number(observed):
                    continue
                if not self._same(name, observed, target):
                    found.append(Divergence(name, index, observed, target, True))
            elif kind == "select":
                known = _integral(observed) and int(observed) in candidate["options"]
                if not known or observed != target:
                    found.append(Divergence(name, index, observed, target, known))
            else:
                known = _integral(observed) and observed >= 0
                if not known or int(observed) & candidate["labelled_bits"] != target:
                    found.append(Divergence(name, index, observed, target, known))
        return found

    # --- notifications ---

    def _notify(self, key: str, title: str, message: str) -> None:
        self._detector._alert(f"{NOTICE_PREFIX}_{key}", f"EcoNet Grant - {title}",
                              message, f"EcoNet: {title}", message)


def label(name: str) -> str:
    """Display name for notifications (CH/HW labels, never the raw API name alone)."""
    if name in NUMBER_DEFINITIONS:
        return NUMBER_DEFINITIONS[name]["name"]
    if name in SELECT_DEFINITIONS:
        return SELECT_DEFINITIONS[name]["name"]
    return name
