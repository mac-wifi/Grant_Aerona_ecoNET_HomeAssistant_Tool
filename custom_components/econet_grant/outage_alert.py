"""Phone alerts while the controller is unreachable.

A single Home Assistant notice is easy to miss (production went four days
unnoticed). Once an outage reaches the Repairs threshold, the owner's phone
(the Revert notification phone) gets a time-sensitive alert, repeated about
every hour while it lasts, plus a Live Activity on the lock screen counting
the outage time. When contact returns, the Live Activity ends and the last
alert is replaced by an all-clear. Time-sensitive alerts get through Focus
modes but stay silent when the phone is muted.

The outage state is saved to disk, so a Home Assistant restart mid-outage
still ends with an all-clear and keeps the real start time. Timing follows
the polls that report failures (every 5 minutes, or the setup retry back-off
of up to 10 minutes), so a reminder can be a few minutes late. Nothing is
sent if Home Assistant itself is down. No function here ever raises.
"""

from __future__ import annotations

from datetime import datetime, timedelta
import logging
from typing import Any
from urllib.parse import urlsplit

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .const import CONF_HOST, CONF_REVERT_NOTIFY_SERVICE, DOMAIN
from .revert import valid_notify_service

_LOGGER = logging.getLogger(__name__)

OUTAGE_ALERTS = f"{DOMAIN}_outage_alerts"
_STORE = f"{DOMAIN}_outage_store"
REMINDER_EVERY = timedelta(hours=1)
# Polls land a little before the hour; don't push the reminder to the next one.
_REMINDER_SLACK = timedelta(minutes=2)
_INTEGRATION_PAGE = f"/config/integrations/integration/{DOMAIN}"


def _tag(entry_id: str) -> str:
    return f"econet_grant_outage_{entry_id}"


def _live_tag(entry_id: str) -> str:
    return f"econet_grant_outage_live_{entry_id}"


def _phone(entry: ConfigEntry) -> str | None:
    service = entry.options.get(CONF_REVERT_NOTIFY_SERVICE, "")
    return service if valid_notify_service(service) else None


def _host(entry: ConfigEntry) -> str:
    """Address only: any user:password@ in the saved host is dropped."""
    host = str(entry.data[CONF_HOST]).strip()
    parts = urlsplit(host if "://" in host else f"http://{host}")
    name = parts.hostname or host
    if ":" in name:
        name = f"[{name}]"
    return f"{name}:{parts.port}" if parts.port else name


def _clock(when: datetime) -> str:
    local, today = dt_util.as_local(when), dt_util.as_local(dt_util.utcnow())
    return local.strftime("%H:%M" if local.date() == today.date() else "%a %d %b %H:%M")


def _duration(span: timedelta) -> str:
    minutes = max(int(span.total_seconds() // 60), 0)
    hours, minutes = divmod(minutes, 60)
    if hours and minutes:
        return f"{hours} h {minutes} min"
    return f"{hours} h" if hours else f"{minutes} min"


# --- saved state ------------------------------------------------------------

def _store(hass: HomeAssistant) -> Store:
    if _STORE not in hass.data:
        hass.data[_STORE] = Store(hass, 1, f"{DOMAIN}.outage_alerts")
    return hass.data[_STORE]


def _states(hass: HomeAssistant) -> dict[str, dict[str, Any]]:
    return hass.data.setdefault(OUTAGE_ALERTS, {})


async def async_load(hass: HomeAssistant) -> None:
    """Restore outages that were in progress when Home Assistant stopped."""
    if OUTAGE_ALERTS in hass.data:
        return
    states = _states(hass)
    try:
        saved = await _store(hass).async_load() or {}
        for entry_id, state in saved.items():
            states[entry_id] = {
                "phone": state["phone"],
                "since": dt_util.parse_datetime(state["since"]),
                "last": dt_util.parse_datetime(state["last"]),
                "live": bool(state.get("live")),
            }
    except Exception:  # noqa: BLE001 - a bad file must not stop setup
        _LOGGER.warning("Could not read saved EcoNet outage alerts", exc_info=True)


@callback
def _save(hass: HomeAssistant) -> None:
    def data() -> dict[str, Any]:
        return {
            entry_id: {
                "phone": state["phone"],
                "since": state["since"].isoformat(),
                "last": state["last"].isoformat(),
                "live": state["live"],
            }
            for entry_id, state in _states(hass).items()
            if state.get("last") is not None
        }

    _store(hass).async_delay_save(data, 1)


# --- outage hooks -----------------------------------------------------------

@callback
def async_outage_ongoing(
    hass: HomeAssistant,
    entry: ConfigEntry,
    since: datetime,
    now: datetime,
    threshold_reached: bool,
) -> None:
    """Called on each failed contact. Never raises."""
    try:
        _ongoing(hass, entry, since, now, threshold_reached)
    except Exception:  # noqa: BLE001 - an alert must never break polling or setup
        _LOGGER.exception("Could not prepare the EcoNet outage alert")


def _ongoing(hass, entry, since, now, threshold_reached) -> None:
    state = _states(hass).get(entry.entry_id)
    # Once alerting has started it keeps its own clock, even if the Repairs
    # clock restarts (a new address) or Home Assistant restarted.
    if state is None and not threshold_reached:
        return
    phone = _phone(entry)
    if phone is None:
        return
    if state is None:
        state = _states(hass)[entry.entry_id] = {
            "phone": phone, "since": since, "last": None, "live": False,
        }
    if state["phone"] != phone:
        # The phone setting changed: take the card off the old phone.
        if state["live"]:
            _send(hass, entry, state["phone"], [_clear_live(entry.entry_id)])
        state.update(phone=phone, live=False, last=None)

    messages: list[dict[str, Any]] = []
    last = state["last"]
    if last is None or now - last >= REMINDER_EVERY - _REMINDER_SLACK:
        state["last"] = now
        messages.append({
            "title": "EcoNet heat pump offline",
            "message": (
                f"Home Assistant can't reach the ecoNET module at {_host(entry)}. "
                f"Down since {_clock(state['since'])} "
                f"({_duration(now - state['since'])}). No readings are being recorded."
            ),
            "data": {
                "tag": _tag(entry.entry_id),
                "url": _INTEGRATION_PAGE,
                "push": {"interruption-level": "time-sensitive"},
            },
        })
    if not state["live"]:
        state["live"] = True  # set back to False below if delivery fails
        messages.append({
            "title": "EcoNet heat pump offline",
            "message": f"Not reachable at {_host(entry)}",
            "data": {
                "tag": _live_tag(entry.entry_id),
                "live_update": True,
                "chronometer": True,
                "when": state["since"].timestamp(),
                "when_relative": False,
                "notification_icon": "mdi:heat-pump-outline",
                "notification_icon_color": "#F44336",
                "relevance_score": 1.0,
                "url": _INTEGRATION_PAGE,
            },
        })
    if not messages:
        return
    _save(hass)

    def delivered(message: dict[str, Any], ok: bool) -> None:
        if ok or _states(hass).get(entry.entry_id) is not state:
            return
        if message["data"].get("live_update"):
            state["live"] = False  # the card is tried again on the next poll
        else:
            state["last"] = last  # the alert is tried again on the next poll
        _save(hass)

    _send(hass, entry, phone, messages, delivered)


@callback
def async_outage_over(hass: HomeAssistant, entry: ConfigEntry, now: datetime) -> None:
    """Contact is back: end the Live Activity and send an all-clear. Never raises."""
    try:
        state = _states(hass).pop(entry.entry_id, None)
        if not state or state.get("last") is None:
            return
        _save(hass)
        _send(hass, entry, state["phone"], [
            _clear_live(entry.entry_id),
            {
                "title": "EcoNet heat pump back online",
                "message": (
                    "Back online: the ecoNET module answers again after "
                    f"{_duration(now - state['since'])}."
                ),
                "data": {"tag": _tag(entry.entry_id), "url": _INTEGRATION_PAGE},
            },
        ])
    except Exception:  # noqa: BLE001
        _LOGGER.exception("Could not send the EcoNet all-clear")


@callback
def async_forget(hass: HomeAssistant, entry: ConfigEntry) -> None:
    if _states(hass).pop(entry.entry_id, None) is not None:
        _save(hass)


def _clear_live(entry_id: str) -> dict[str, Any]:
    return {"message": "clear_notification", "data": {"tag": _live_tag(entry_id)}}


def _send(hass, entry, phone, messages, delivered=None) -> None:
    async def deliver() -> None:
        for message in messages:
            try:
                await hass.services.async_call("notify", phone, message, blocking=True)
            except Exception:  # noqa: BLE001 - each message is sent independently
                _LOGGER.warning(
                    "Could not send the EcoNet outage alert to notify.%s", phone,
                    exc_info=True,
                )
                ok = False
            else:
                ok = True
            if delivered:
                delivered(message, ok)

    hass.async_create_background_task(deliver(), f"{DOMAIN}_outage_alert_{entry.entry_id}")
