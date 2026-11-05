"""Config flow for EcoNet Grant Aerona integration."""

from __future__ import annotations

from collections.abc import Mapping
import logging
from typing import Any

import aiohttp
import voluptuous as vol

from homeassistant.components import persistent_notification
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigEntryState,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)
from homeassistant.helpers.service_info.dhcp import DhcpServiceInfo

from . import discovery
from .api import AuthError, EconetApi, EconetClient
from .const import (
    CONF_HOST,
    CONF_PASSWORD,
    CONF_PUSH_NOTIFICATIONS,
    CONF_REVERT_NOTIFY_SERVICE,
    CONF_RETENTION_DAYS,
    CONF_SAFE_MODE,
    CONF_SLOW_POLL_INTERVAL,
    CONF_USERNAME,
    DATA_RETENTION_DAYS,
    DEFAULT_PUSH_NOTIFICATIONS,
    DEFAULT_SAFE_MODE,
    DEFAULT_SLOW_POLL_MINUTES,
    DEFAULT_USERNAME,
    DOMAIN,
    MIN_SLOW_POLL_MINUTES,
    MAX_SLOW_POLL_MINUTES,
)

_LOGGER = logging.getLogger(__name__)

USER_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_HOST): str,
        vol.Required(CONF_USERNAME, default=DEFAULT_USERNAME): str,
        vol.Required(CONF_PASSWORD): str,
    }
)


def _normalise_host(host: str) -> str:
    host = host.strip().rstrip("/").lower()
    for prefix in ("http://", "https://"):
        if host.startswith(prefix):
            return host[len(prefix):]
    return host


def _known_uids(hass: HomeAssistant, entry: ConfigEntry) -> set[str]:
    """Controller ids on the entry's devices, ignoring host-string fallbacks."""
    host = _normalise_host(entry.data[CONF_HOST])
    return {
        value
        for device in dr.async_entries_for_config_entry(
            dr.async_get(hass), entry.entry_id
        )
        for domain, value in device.identifiers
        if domain == DOMAIN and _normalise_host(value) != host
    }


_PASSWORD_SELECTOR = TextSelector(TextSelectorConfig(type=TextSelectorType.PASSWORD))


def connection_schema(username: str) -> vol.Schema:
    """Address and login form; a blank or missing password keeps the saved one."""
    return vol.Schema(
        {
            vol.Required(CONF_HOST): str,
            vol.Required(CONF_USERNAME, default=username): str,
            vol.Optional(CONF_PASSWORD): _PASSWORD_SELECTOR,
        }
    )


async def async_check_connection(
    hass: HomeAssistant,
    entry: ConfigEntry,
    host: str,
    username: str,
    password: str,
    require_same_device: bool = False,
) -> str | None:
    """Return an error key, or None if this login works at this address.

    require_same_device makes the controller ID check strict: the address must
    answer with an ID this entry already knows (used for unattended moves).
    """
    wanted = _normalise_host(host)
    if any(
        wanted in (
            _normalise_host(other.unique_id or ""),
            _normalise_host(other.data.get(CONF_HOST) or ""),
        )
        for other in hass.config_entries.async_entries(DOMAIN, include_ignore=False)
        if other.entry_id != entry.entry_id
    ):
        return "already_configured"

    client = EconetClient(host, username, password, async_get_clientsession(hass))
    try:
        sys_params = await EconetApi(client).fetch_sys_params()
    except AuthError:
        return "invalid_auth"
    except (aiohttp.ClientError, OSError):
        return "cannot_connect"
    except Exception:
        _LOGGER.exception("Unexpected error checking the ecoNET connection")
        return "unknown"
    if sys_params is None:
        return "cannot_connect"

    known = _known_uids(hass, entry)
    new_uid = sys_params.get("uid")
    if require_same_device:
        if not known or not new_uid or new_uid not in known:
            return "wrong_device"
    elif known and new_uid and new_uid not in known:
        return "wrong_device"
    return None


@callback
def async_apply_connection(
    hass: HomeAssistant, entry: ConfigEntry, host: str, username: str, password: str
) -> None:
    """Store the new connection and make sure the entry reloads exactly once."""
    # Read before updating: the update listener can start its reload straight away.
    was_loaded = entry.state is ConfigEntryState.LOADED
    # A new address or login starts a fresh outage clock.
    hass.data.get(f"{DOMAIN}_connection_failures", {}).pop(entry.entry_id, None)
    # Follow the address in the title unless the owner renamed it.
    title = entry.title
    if title == f"EcoNet Grant ({entry.data[CONF_HOST]})":
        title = f"EcoNet Grant ({host})"
    changed = hass.config_entries.async_update_entry(
        entry,
        unique_id=host,
        title=title,
        data={
            **entry.data,
            CONF_HOST: host,
            CONF_USERNAME: username,
            CONF_PASSWORD: password,
        },
    )
    if not changed and was_loaded:
        return
    # Loaded entry: its update listener reloads once on a change. Anything else
    # (failed setup, retrying) has no listener yet, so reload explicitly, even
    # when the stored login is unchanged (reauth after fixing the controller).
    if not was_loaded:
        hass.config_entries.async_schedule_reload(entry.entry_id)


class EconetGrantConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for EcoNet Grant Aerona."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the initial user configuration step."""
        errors: dict[str, str] = {}

        if user_input is not None:
            host = user_input[CONF_HOST].strip()
            user_input = {**user_input, CONF_HOST: host}
            username = user_input[CONF_USERNAME]
            password = user_input[CONF_PASSWORD]

            session = async_get_clientsession(self.hass)
            client = EconetClient(host, username, password, session)
            api = EconetApi(client)

            try:
                if await api.test_connection():
                    await self.async_set_unique_id(host)
                    self._abort_if_unique_id_configured()
                    return self.async_create_entry(
                        title=f"EcoNet Grant ({host})",
                        data=user_input,
                        options={
                            CONF_SAFE_MODE: DEFAULT_SAFE_MODE,
                            CONF_PUSH_NOTIFICATIONS: DEFAULT_PUSH_NOTIFICATIONS,
                        },
                    )
                errors["base"] = "cannot_connect"
            except AuthError:
                errors["base"] = "invalid_auth"
            except Exception:
                _LOGGER.exception("Unexpected error during config flow")
                errors["base"] = "unknown"

        return self.async_show_form(
            step_id="user",
            data_schema=USER_SCHEMA,
            errors=errors,
        )

    async def async_step_dhcp(self, discovery_info: DhcpServiceInfo) -> ConfigFlowResult:
        """The controller's MAC appeared at an address; follow it if it is really ours."""
        mac = dr.format_mac(discovery_info.macaddress)
        entry = next(
            (
                found
                for device in dr.async_get(self.hass).async_get_devices(
                    connections={(dr.CONNECTION_NETWORK_MAC, mac)}
                )
                for entry_id in device.config_entries
                if (found := self.hass.config_entries.async_get_entry(entry_id))
                and found.domain == DOMAIN
            ),
            None,
        )
        if entry is None:
            return self.async_abort(reason="not_econet_device")

        old = entry.data[CONF_HOST]
        if discovery.host_ip(old) is None:
            _LOGGER.debug("ecoNET entry uses a host name (%s); not moving it", old)
            return self.async_abort(reason="not_ip_host")
        new_host = discovery.replace_host_ip(old, discovery_info.ip)
        if _normalise_host(new_host) == _normalise_host(old):
            return self.async_abort(reason="already_configured")

        username, password = entry.data[CONF_USERNAME], entry.data[CONF_PASSWORD]
        # Is the controller still answering at its current address (even if it
        # rejects the login)? If so it has not moved, and we must not send the
        # login anywhere else.
        if await async_check_connection(
            self.hass, entry, old, username, password, require_same_device=True
        ) in (None, "invalid_auth"):
            _LOGGER.info(
                "ecoNET MAC reported at %s, but the controller still answers at "
                "its current address; ignoring", discovery_info.ip,
            )
            return self.async_abort(reason="already_configured")
        error = await async_check_connection(
            self.hass, entry, new_host, username, password, require_same_device=True
        )
        if error:
            _LOGGER.warning(
                "ecoNET MAC seen at %s but not switching: %s", discovery_info.ip, error
            )
            return self.async_abort(reason=error)

        async_apply_connection(self.hass, entry, new_host, username, password)
        persistent_notification.async_create(
            self.hass,
            f"The ecoNET controller moved from {old} to {new_host}. The integration "
            "now uses the new address. No heat-pump settings were changed.",
            title="EcoNet Grant - controller address changed",
            notification_id=f"econet_grant_address_changed_{entry.entry_id}",
        )
        _LOGGER.info("ecoNET controller moved from %s to %s", old, new_host)
        return self.async_abort(reason="address_updated")

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Change the controller address and login; entities and history are kept."""
        entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}

        if user_input is not None:
            host = user_input[CONF_HOST].strip()
            username = user_input[CONF_USERNAME].strip()
            password = user_input.get(CONF_PASSWORD) or entry.data[CONF_PASSWORD]
            error = await async_check_connection(
                self.hass, entry, host, username, password
            )
            if error is None:
                async_apply_connection(self.hass, entry, host, username, password)
                return self.async_abort(reason="reconfigure_successful")
            errors["base"] = error

        # The password is never prefilled, and a failed submit doesn't echo it.
        suggested = {
            CONF_HOST: entry.data[CONF_HOST],
            CONF_USERNAME: entry.data[CONF_USERNAME],
        }
        if user_input is not None:
            suggested = {
                CONF_HOST: user_input[CONF_HOST],
                CONF_USERNAME: user_input[CONF_USERNAME],
            }
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=self.add_suggested_values_to_schema(
                connection_schema(entry.data[CONF_USERNAME]), suggested
            ),
            errors=errors,
        )

    async def async_step_reauth(
        self, entry_data: Mapping[str, Any]
    ) -> ConfigFlowResult:
        """The controller rejected the saved login."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        entry = self._get_reauth_entry()
        errors: dict[str, str] = {}

        if user_input is not None:
            host = entry.data[CONF_HOST]
            username = user_input[CONF_USERNAME].strip()
            password = user_input[CONF_PASSWORD]
            error = await async_check_connection(
                self.hass, entry, host, username, password
            )
            if error is None:
                async_apply_connection(self.hass, entry, host, username, password)
                return self.async_abort(reason="reauth_successful")
            errors["base"] = error

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=self.add_suggested_values_to_schema(
                vol.Schema(
                    {
                        vol.Required(CONF_USERNAME): str,
                        vol.Required(CONF_PASSWORD): _PASSWORD_SELECTOR,
                    }
                ),
                {CONF_USERNAME: entry.data[CONF_USERNAME]},
            ),
            description_placeholders={"host": entry.data[CONF_HOST]},
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return EconetGrantOptionsFlow(config_entry)


class EconetGrantOptionsFlow(OptionsFlow):
    """Handle options for EcoNet Grant Aerona."""

    def __init__(self, config_entry: ConfigEntry) -> None:
        self._config_entry = config_entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        options = self._config_entry.options
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_SAFE_MODE,
                        default=options.get(CONF_SAFE_MODE, DEFAULT_SAFE_MODE),
                    ): bool,
                    vol.Required(
                        CONF_PUSH_NOTIFICATIONS,
                        default=options.get(CONF_PUSH_NOTIFICATIONS, DEFAULT_PUSH_NOTIFICATIONS),
                    ): bool,
                    vol.Optional(
                        CONF_REVERT_NOTIFY_SERVICE,
                        default=options.get(CONF_REVERT_NOTIFY_SERVICE, ""),
                    ): vol.All(str, vol.Match(r"^(?:mobile_app_[a-z0-9_]+)?$")),
                    vol.Optional(
                        CONF_SLOW_POLL_INTERVAL,
                        default=options.get(CONF_SLOW_POLL_INTERVAL, DEFAULT_SLOW_POLL_MINUTES),
                    ): vol.All(int, vol.Range(
                        min=MIN_SLOW_POLL_MINUTES, max=MAX_SLOW_POLL_MINUTES
                    )),
                    vol.Optional(
                        CONF_RETENTION_DAYS,
                        default=options.get(CONF_RETENTION_DAYS, DATA_RETENTION_DAYS),
                    ): vol.All(vol.Coerce(int), vol.Range(min=30, max=7300)),
                }
            ),
        )
