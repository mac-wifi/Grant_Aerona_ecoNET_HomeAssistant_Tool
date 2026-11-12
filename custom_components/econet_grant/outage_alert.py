"""Phone alerts while the controller is unreachable.

A single Home Assistant notice is easy to miss (production went four days
unnoticed). Once an outage reaches the Repairs threshold, the owner's phone
(the Revert notification phone) gets a time-sensitive alert, repeated about
every hour while it lasts, plus a Live Activity on the lock screen counting
the outage time. When contact returns, the Live Activity ends and the last
alert is replaced by an all-clear. Time-sensitive alerts get through Focus
modes but stay silent when the phone is muted.

Timing follows the polls that report the failures (every 5 minutes, or the
setup retry back-off of up to 10 minutes), so a reminder can be a few minutes
late. Nothing is sent if Home Assistant itself is down.
"""

from __future__ import annotations

from datetime import datetime, timedelta
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.util import dt as dt_util

from .const import CONF_HOST, CONF_REVERT_NOTIFY_SERVICE, DOMAIN
from .revert import valid_notify_service

_LOGGER = logging.getLogger(__name__)

OUTAGE_ALERTS = f"{DOMAIN}_outage_alerts"
REMINDER_EVERY = timedelta(hours=1)
# Polls land a little before the hour; don't push the reminder to the next one.
_REMINDER_SLACK = timedelta(minutes=2)
_INTEGRATION_PAGE = f"/config/integrations/integration/{DOMAIN}"


def _tag(entry: ConfigEntry) -> str:
    return f"econet_grant_outage_{entry.entry_id}"


def _live_tag(entry: ConfigEntry) -> str:
    return f"econet_grant_outage_live_{entry.entry_id}"


def _phone(entry: ConfigEntry) -> str | None:
    service = entry.options.get(CONF_REVERT_NOTIFY_SERVICE, "")
    return service if valid_notify_service(service) else None


def _host(entry: ConfigEntry) -> str:
    host = str(entry.data[CONF_HOST]).strip()
    for prefix in ("http://", "https://"):
        host = host.removeprefix(prefix)
    return host.rstrip("/")


def _clock(when: datetime) -> str:
    local, today = dt_util.as_local(when), dt_util.as_local(dt_util.utcnow())
    return local.strftime("%H:%M" if local.date() == today.date() else "%a %d %b %H:%M")


def _duration(span: timedelta) -> str:
    minutes = max(int(span.total_seconds() // 60), 0)
    hours, minutes = divmod(minutes, 60)
    if hours and minutes:
        return f"{hours} h {minutes} min"
    return f"{hours} h" if hours else f"{minutes} min"


@callback
def async_outage_ongoing(
    hass: HomeAssistant, entry: ConfigEntry, since: datetime, now: datetime
) -> None:
    """Called on each failed contact once the outage passed the threshold."""
    phone = _phone(entry)
    if phone is None:
        return
    state: dict[str, Any] = hass.data.setdefault(OUTAGE_ALERTS, {}).setdefault(
        entry.entry_id, {"last": None}
    )
    last = state["last"]
    if last is not None and now - last < REMINDER_EVERY - _REMINDER_SLACK:
        return
    first = last is None
    # Keep the first start: a new address restarts the Repairs clock, not the outage.
    since = state.setdefault("since", since)
    state["last"], state["phone"] = now, phone
    down_for = _duration(now - since)
    messages = [{
        "title": "EcoNet heat pump offline",
        "message": (
            f"Home Assistant can't reach the ecoNET module at {_host(entry)}. "
            f"Down since {_clock(since)} ({down_for}). No readings are being recorded."
        ),
        "data": {
            "tag": _tag(entry),
            "url": _INTEGRATION_PAGE,
            "push": {"interruption-level": "time-sensitive"},
        },
    }]
    if first:
        messages.append({
            "title": "EcoNet heat pump offline",
            "message": f"Not reachable at {_host(entry)}",
            "data": {
                "tag": _live_tag(entry),
                "live_update": True,
                "chronometer": True,
                "when": since.timestamp(),
                "when_relative": False,
                "notification_icon": "mdi:heat-pump-outline",
                "notification_icon_color": "#F44336",
                "relevance_score": 1.0,
                "url": _INTEGRATION_PAGE,
            },
        })
    _send(hass, entry, phone, messages)


@callback
def async_outage_over(hass: HomeAssistant, entry: ConfigEntry, now: datetime) -> None:
    """Contact is back: end the Live Activity and send an all-clear."""
    state = hass.data.get(OUTAGE_ALERTS, {}).pop(entry.entry_id, None)
    if not state or state.get("last") is None:
        return
    _send(hass, entry, state["phone"], [
        {"message": "clear_notification", "data": {"tag": _live_tag(entry)}},
        {
            "title": "EcoNet heat pump back online",
            "message": (
                "Back online: the ecoNET module answers again after "
                f"{_duration(now - state['since'])}."
            ),
            "data": {"tag": _tag(entry), "url": _INTEGRATION_PAGE},
        },
    ])


@callback
def async_forget(hass: HomeAssistant, entry: ConfigEntry) -> None:
    hass.data.get(OUTAGE_ALERTS, {}).pop(entry.entry_id, None)


def _send(
    hass: HomeAssistant, entry: ConfigEntry, phone: str, messages: list[dict]
) -> None:
    async def deliver() -> None:
        for message in messages:
            try:
                await hass.services.async_call("notify", phone, message, blocking=True)
            except Exception:  # noqa: BLE001 - an alert must never break polling
                _LOGGER.warning(
                    "Could not send the EcoNet outage alert to notify.%s", phone,
                    exc_info=True,
                )
                return

    hass.async_create_background_task(deliver(), f"{DOMAIN}_outage_alert_{entry.entry_id}")
