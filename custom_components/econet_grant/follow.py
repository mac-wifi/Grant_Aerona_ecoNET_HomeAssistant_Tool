"""Keep following the controller to a new IP while it is unreachable.

HA's DHCP watcher reports a device once per address. If the controller is
still starting up when that report arrives, the first move is refused and HA
never reports that address again. So after every failed poll (the saved
address has just been retried and failed), look up where the network last
saw the controller's MAC and try the move again.
"""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback

from . import discovery
from .config_flow import async_follow_to_ip
from .const import CONF_HOST, DOMAIN

_LOGGER = logging.getLogger(__name__)

# Per entry: (ip, reason) refusals already logged at WARNING in this outage.
FOLLOW_LOGGED = f"{DOMAIN}_follow_logged"


@callback
def async_schedule_follow_retry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Start a retry in the background; a failed setup must not cancel it."""
    hass.async_create_background_task(
        async_retry_follow(hass, entry), f"{DOMAIN}_follow_retry_{entry.entry_id}"
    )


async def async_retry_follow(hass: HomeAssistant, entry: ConfigEntry) -> str:
    """Try the move to wherever the controller was last seen. Never raises."""
    try:
        if hass.config_entries.async_get_entry(entry.entry_id) is not entry:
            return "entry_removed"
        saved = discovery.host_ip(entry.data[CONF_HOST])
        if saved is None:
            return "not_ip_host"
        macs = discovery.entry_macs(hass, entry)
        if not macs:
            _LOGGER.debug("ecoNET MAC unknown, cannot look for a new address")
            return "no_mac"
        seen = [
            ip for mac in macs for ip in await discovery.async_lookup_ips(hass, mac)
        ]
        candidates = [ip for ip in dict.fromkeys(seen) if ip != saved]
        if hass.config_entries.async_get_entry(entry.entry_id) is not entry:
            return "entry_removed"
        if not candidates:
            _LOGGER.debug(
                "ecoNET controller not answering at %s and not seen at another "
                "address yet", saved,
            )
            return "not_seen_elsewhere"
        logged = hass.data.setdefault(FOLLOW_LOGGED, {}).setdefault(entry.entry_id, set())
        result = "not_seen_elsewhere"
        for ip in candidates:
            result = await async_follow_to_ip(hass, entry, ip)
            if result in ("address_updated", "already_configured", "in_progress"):
                return result
            # Retried every failed poll: say it once, not every 5 minutes.
            log = _LOGGER.debug if (ip, result) in logged else _LOGGER.warning
            logged.add((ip, result))
            log(
                "ecoNET controller not answering at %s; seen at %s but not "
                "switching yet (%s). Will try again after the next failed poll.",
                saved, ip, result,
            )
        return result
    except Exception:  # noqa: BLE001 - must never break polling or setup
        _LOGGER.exception("Unexpected error looking for the ecoNET controller")
        return "unknown"
