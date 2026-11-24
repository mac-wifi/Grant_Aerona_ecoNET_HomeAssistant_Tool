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

from .api import WriteCancelled
from .backup import snapshot_path
from .change_detector import format_setting_change
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
CAP_PER_HOUR = 3  # automatic reverts per setting per rolling hour
THRESHOLDS = frozenset({"SummerOn", "SummerOff"})  # each limits the other
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
    """Token for one own-write operation, bound to the state it counted in."""

    name: str
    value: int | float
    state: _OwnWrites | None = None


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
        self._reloading = 0  # a new Default snapshot is being loaded: old targets unusable
        self._loaded_at = 0.0
        self._grace_checked = False
        self._busy = False
        self._episodes: dict[str, int | float] = {}  # name -> wrong value already handled
        self._unconfirmed: dict[str, tuple] = {}  # name -> (sent, wrong value, done at)
        self._sends: dict[str, list[float]] = {}
        self._cap_notified: set[str] = set()

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
        stored = await self._store.async_load()
        overrides = stored.get("overrides") if isinstance(stored, dict) else None
        self._overrides = {name: value for name, value in (
            overrides.items() if isinstance(overrides, dict) else ())
            if name in AUTO_REVERT_CANDIDATES and target_valid(name, value)}
        await self._async_load_snapshot()
        self._unsubscribe = async_dispatcher_connect(
            self._hass, SIGNAL_SNAPSHOT_SAVED, self._on_snapshot_saved)
        self._loaded_at = monotonic()
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
        self._reloading += 1  # nothing is judged against the old reference from now on
        self._overrides.clear()
        self._entry.async_create_task(self._hass, self._async_snapshot_saved(),
                                      "econet_grant_auto_revert_snapshot")

    async def _async_snapshot_saved(self) -> None:
        try:
            await self._async_save_overrides()
            await self._async_load_snapshot()
        finally:
            self._reloading -= 1
            self.revision += 1

    async def _async_load_snapshot(self) -> None:
        """Load the reference. Never raises: a bad snapshot only disables protection."""
        try:
            await self._async_read_snapshot()
        except Exception:  # noqa: BLE001 - monitoring and control must keep working
            _LOGGER.exception("Auto-revert: could not use the Default snapshot")
            self._snapshot_targets, self.snapshot_usable, self.snapshot_date = {}, False, None
            self._warn_no_snapshot()

    def _warn_no_snapshot(self) -> None:
        if self.enabled:
            self._notify("no_snapshot", "Auto-revert: no usable Default snapshot",
                         "Auto-revert is on, but there is no usable Default snapshot, "
                         "so nothing is protected. Take a Default snapshot "
                         "(Snapshot & Backup on the dashboard).")

    async def _async_read_snapshot(self) -> None:
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
        self.snapshot_usable, self.snapshot_date = False, None
        if isinstance(params, dict):
            for name, candidate in AUTO_REVERT_CANDIDATES.items():
                problem = eligibility_problem(params, name, snapshot=True)
                value = None
                if problem is None:  # only now is the entry known to be a dict
                    value = params[candidate["param_index"]].get("value")
                    if not target_valid(name, value):
                        problem = f"snapshot value {value!r} is not a valid setting"
                if problem:
                    self.unprotected[name] = problem
                    continue
                if candidate["kind"] == "mask":
                    value = int(value) & candidate["labelled_bits"]
                self._snapshot_targets[name] = value
        if not self._snapshot_targets:  # missing, unreadable or nothing usable in it
            self._warn_no_snapshot()
            return
        self.snapshot_usable = True
        created = snapshot.get("created_at")
        self.snapshot_date = created if isinstance(created, str) else None
        pn_async_dismiss(self._hass, f"{DOMAIN}_{NOTICE_PREFIX}_no_snapshot")
        for name, reason in self.unprotected.items():
            _LOGGER.info("Auto-revert: %s not protected (%s)", name, reason)

    # --- overrides (Home Assistant changes stick) ---

    def _apply_override(self, name: str, raw_value: int | float) -> bool:
        """Synchronous part: update the in-memory override. True if it may have changed."""
        candidate = AUTO_REVERT_CANDIDATES.get(name)
        if candidate is None or not target_valid(name, raw_value):
            return False
        value = int(raw_value) & candidate["labelled_bits"] if candidate["kind"] == "mask" \
            else raw_value
        if name in self._snapshot_targets and self._same(name, value,
                                                         self._snapshot_targets[name]):
            self._overrides.pop(name, None)
        else:
            self._overrides[name] = value
        return True

    async def async_record_override(self, name: str, raw_value: int | float) -> None:
        """Remember a value this integration wrote; drop it if it equals the snapshot."""
        if self._apply_override(name, raw_value):
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
        if name not in AUTO_REVERT_CANDIDATES:  # others are never judged
            return OwnWrite(name, value)
        state = self._own.setdefault(name, _OwnWrites())
        state.count += 1
        return OwnWrite(name, value, state)

    async def async_finish_own_write(self, write: OwnWrite, ok: bool) -> None:
        """In a ``finally``: the last acknowledged completion wins.

        Everything that matters happens before the first await, on the token's own
        state. The hold is released only by a poll that started after the last
        overlapping write ended (``_async_settle_own_writes``), never here, so a
        slow save cannot release a newer write's hold.
        """
        state = write.state
        if state is None:
            return
        state.count -= 1
        state.settled_after = monotonic()
        state.values.append(write.value)
        state.failed = state.failed or not ok
        if ok and self._apply_override(write.name, write.value):
            await self._async_save_overrides()

    def held(self, name: str) -> bool:
        """An own write is in flight, or its outcome is not yet judged."""
        return name in self._own

    async def _async_settle_own_writes(self, data: dict[str, Any], started_at: float) -> None:
        """Release holds on the first poll that started after the last write ended.

        After a failed or timed-out write, adopt what that poll shows.
        """
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
        if (not self.enabled or not self.snapshot_usable or self._reloading
                or self._busy or not self.judgeable(started_at)):
            return
        self._busy = True  # one evaluation at a time; a skipped poll consumes nothing
        try:
            await self._async_judge(data, started_at)
        finally:
            self._busy = False

    async def _async_judge(self, data: dict[str, Any], started_at: float) -> None:
        # One revision for the whole batch: anything that invalidates the poll
        # (own write, Restore, snapshot, options) cancels every remaining item.
        revision = self.revision
        found = {d.name: d for d in self.divergences(data)}
        # An episode ends when the setting returns to its target or moves on.
        for name, wrong in list(self._episodes.items()):
            if name not in found or found[name].observed != wrong:
                self._episodes.pop(name)
        for name, (sent, wrong, done_at) in list(self._unconfirmed.items()):
            if started_at <= done_at:
                continue
            self._unconfirmed.pop(name)
            if name in found and found[name].observed == wrong:
                self._notify(name, "Auto-revert not confirmed",
                             f"{format_setting_change(name, wrong, sent)}\n\n"
                             "The controller accepted the change but still reports the old "
                             "value. It will not be tried again for this change; check the "
                             "controller.")
        safe = is_safe_mode(self._entry)
        if not safe and monotonic() - self._loaded_at < GRACE_SECONDS:
            if not self._grace_checked:
                listed = [format_setting_change(d.name, d.observed, d.target)
                          for d in found.values() if d.known and not self.held(d.name)]
                if listed:
                    self._notify("grace", "Auto-revert will put settings back",
                                 "These protected settings differ from the Default snapshot "
                                 "and will be put back in about 5 minutes, unless you take a "
                                 "new Default snapshot or switch Auto-revert off:\n\n- "
                                 + "\n- ".join(listed))
            self._grace_checked = True
            return
        self._grace_checked = True
        for d in found.values():
            if self.held(d.name) or d.name in self._episodes:
                continue
            if not d.known:
                self._episodes[d.name] = d.observed
                self._notify(d.name, "Auto-revert: unrecognised value left alone",
                             f"{label(d.name)} is at a value this integration does not "
                             f"recognise ({d.observed!r}). It was not changed.")
                continue
            if safe:
                self._episodes[d.name] = d.observed
                self._notify(d.name, "Auto-revert report (Safe Mode on)",
                             f"{format_setting_change(d.name, d.observed, d.target)}\n\n"
                             "Auto-revert would have put this back to the Default snapshot "
                             "value (after the arrow). Safe Mode is on, so nothing was changed.")
                continue
            if self._capped(d.name):
                if d.name not in self._cap_notified:
                    self._cap_notified.add(d.name)
                    self._notify(d.name, "Auto-revert stopped for this setting",
                                 f"{label(d.name)} has been put back {CAP_PER_HOUR} times "
                                 "in the last hour. Something keeps changing it, so "
                                 "auto-revert has stopped for it for now.")
                continue
            await self._async_revert(d, revision, started_at)

    def _capped(self, name: str) -> bool:
        now = monotonic()
        recent = [t for t in self._sends.get(name, []) if now - t < 3600]
        self._sends[name] = recent
        if len(recent) < CAP_PER_HOUR:
            self._cap_notified.discard(name)
            return False
        return True

    async def _async_revert(self, d: Divergence, revision: int, started_at: float) -> None:
        """Fresh read, re-check, then one guarded write by name."""
        name = d.name
        candidate = AUTO_REVERT_CANDIDATES[name]

        def armed() -> bool:
            return (self.enabled and not is_safe_mode(self._entry) and not self._reloading
                    and self.revision == revision and self.judgeable(started_at)
                    and not self.held(name))

        try:
            fresh = await self._api.fetch_edit_params(authorise=armed)
        except WriteCancelled:
            return
        except Exception:
            _LOGGER.exception("Auto-revert: could not re-read %s; will try on a later poll", name)
            return
        data = (fresh or {}).get("data")
        if not isinstance(data, dict) or not armed() or self.targets.get(name) != d.target:
            return
        if eligibility_problem(data, name):
            self._episodes[name] = d.observed
            self._notify(name, "Auto-revert cancelled",
                         f"{label(name)} could not be verified "
                         f"({eligibility_problem(data, name)}). Nothing was changed.")
            return
        param = data[d.index]
        current = param.get("value")
        if not _number(current) or not self._same_raw(name, current, d.observed):
            return  # it moved again: the next poll starts a new episode
        if candidate["kind"] == "number":
            low, high = param.get("minv"), param.get("maxv")
            if not (_number(low) and _number(high) and low <= d.target <= high):
                self._episodes[name] = d.observed
                reason = ("while the other season threshold blocks it" if name in THRESHOLDS
                          else "because it is outside the controller's current limits")
                self._notify(name, "Auto-revert not possible",
                             f"{format_setting_change(name, d.observed, d.target)}\n\n"
                             f"{label(name)} cannot be put back {reason} "
                             f"(allowed now: {low} to {high}). Nothing was sent.")
                return
            value = d.target
        elif candidate["kind"] == "select":
            value = int(d.target)
        else:
            bits = candidate["labelled_bits"]
            value = (int(current) & ~bits) | (int(d.target) & bits)

        sent = False

        def authorise() -> bool:
            nonlocal sent
            if armed():
                sent = True
                return True
            return False

        write = self._detector.begin_revert(d.index, name, current, value)
        ok = False
        try:
            ok = await self._api.set_param(name, value, authorise=authorise)
        except WriteCancelled:
            pass
        except Exception:
            _LOGGER.exception("Auto-revert of %s failed", name)
        finally:
            self._detector.finish_revert(write)
        if not sent:
            return  # cancelled before anything was sent: the attempt is not used up
        self._episodes[name] = d.observed
        self._sends.setdefault(name, []).append(monotonic())
        change = format_setting_change(name, current, value)
        if not ok:
            self._notify(name, "Auto-revert failed",
                         f"{change}\n\nThe request was sent but not accepted, or no reply "
                         "came. It will not be retried for this change; check the controller.")
            return
        self._unconfirmed[name] = (value, d.observed, monotonic())
        await self._db.async_log_change(self._hass, {
            "name": name, "index": d.index, "old_value": current, "new_value": value,
        }, source="auto_revert")
        self._notify(name, "Setting put back",
                     f"{change}\n\nChanged outside Home Assistant, so it was put back to the "
                     "Default snapshot value. The controller accepted the change.")

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
