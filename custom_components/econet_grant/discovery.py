"""Learn the controller's MAC so HA's DHCP discovery can follow it to a new IP."""
from __future__ import annotations

import ipaddress
import logging
from urllib.parse import urlsplit

from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr

from .const import CONF_HOST, DOMAIN

_LOGGER = logging.getLogger(__name__)

ARP_TABLE_PATH = "/proc/net/arp"


def parse_arp_table(text: str, ip: str) -> str | None:
    """Return the formatted MAC for ip from /proc/net/arp text, or None."""
    for line in text.splitlines()[1:]:
        parts = line.split()
        if len(parts) < 4 or parts[0] != ip:
            continue
        flags, mac = parts[2], parts[3]
        if flags == "0x0" or mac == "00:00:00:00:00:00":
            continue
        return dr.format_mac(mac)
    return None


def _split(host: str):
    host = host.strip()
    if "://" not in host:
        host = f"http://{host}"
    return urlsplit(host)


def host_ip(host: str) -> str | None:
    """IP literal from a stored host, else None (DNS names are not followed)."""
    try:
        hostname = _split(host).hostname
        return str(ipaddress.ip_address(hostname)) if hostname else None
    except ValueError:
        return None


def replace_host_ip(old_host: str, new_ip: str) -> str:
    """Keep the old scheme and port and swap in new_ip."""
    parts = _split(old_host)
    had_scheme = "://" in old_host
    new_host = f"[{new_ip}]" if ":" in new_ip else new_ip
    netloc = f"{new_host}:{parts.port}" if parts.port else new_host
    return f"{parts.scheme}://{netloc}" if had_scheme else netloc


async def async_lookup_mac(hass: HomeAssistant, ip: str) -> str | None:
    """Find the MAC for ip from HA's dhcp data, falling back to the ARP table."""
    try:
        from homeassistant.components.dhcp import async_discovered_service_info

        for info in async_discovered_service_info(hass):
            if info.ip == ip:
                return dr.format_mac(info.macaddress)
    except (ImportError, KeyError):
        pass

    def _read() -> str:
        with open(ARP_TABLE_PATH, encoding="utf-8") as arp:
            return arp.read()

    try:
        text = await hass.async_add_executor_job(_read)
    except OSError:
        return None
    return parse_arp_table(text, ip)


def parse_arp_table_ips(text: str, mac: str) -> list[str]:
    """Return the IPs /proc/net/arp lists for the formatted mac."""
    found = []
    for line in text.splitlines()[1:]:
        parts = line.split()
        if len(parts) < 4 or parts[2] == "0x0":
            continue
        try:
            if dr.format_mac(parts[3]) == mac:
                found.append(parts[0])
        except ValueError:
            continue
    return found


def entry_macs(hass: HomeAssistant, entry) -> list[str]:
    """MAC addresses registered on this entry's devices."""
    return sorted(
        mac
        for device in dr.async_entries_for_config_entry(dr.async_get(hass), entry.entry_id)
        for kind, mac in device.connections
        if kind == dr.CONNECTION_NETWORK_MAC
    )


async def async_lookup_ips(hass: HomeAssistant, mac: str) -> list[str]:
    """Where the network last saw mac: HA's DHCP data first, then the ARP table."""
    found: list[str] = []
    try:
        from homeassistant.components.dhcp import async_discovered_service_info

        found += [
            info.ip
            for info in async_discovered_service_info(hass)
            if dr.format_mac(info.macaddress) == mac
        ]
    except (ImportError, KeyError):
        pass

    def _read() -> str:
        with open(ARP_TABLE_PATH, encoding="utf-8") as arp:
            return arp.read()

    try:
        found += parse_arp_table_ips(await hass.async_add_executor_job(_read), mac)
    except OSError:
        pass
    return list(dict.fromkeys(found))


async def async_register_controller_mac(hass: HomeAssistant, entry, api) -> None:
    """Add the controller's MAC to its device. Never raises."""
    try:
        if not api.uid:
            _LOGGER.debug("MAC not registered: controller ID unknown")
            return
        ip = host_ip(entry.data[CONF_HOST])
        if not ip:
            _LOGGER.debug("MAC not registered: host is not an IP address")
            return
        mac = await async_lookup_mac(hass, ip)
        if not mac:
            _LOGGER.debug("MAC not registered: no MAC known for %s", ip)
            return
        registry = dr.async_get(hass)
        device = registry.async_get_device_by_identifier((DOMAIN, api.uid), entry.entry_id)
        if device is None:
            _LOGGER.debug("MAC not registered: device not found")
            return
        registry.async_update_device(
            device.id, new_connections=device.connections | {(dr.CONNECTION_NETWORK_MAC, mac)}
        )
    except Exception:  # noqa: BLE001 - best effort, must never affect setup
        _LOGGER.debug("Could not register the controller MAC", exc_info=True)
