"""Config flow for EcoNet Grant Aerona integration."""

from __future__ import annotations

import logging
from typing import Any

import aiohttp
import voluptuous as vol

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.aiohttp_client import async_get_clientsession

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

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Change the controller address; entities and history are kept."""
        entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}

        if user_input is not None:
            host = user_input[CONF_HOST].strip()
            wanted = _normalise_host(host)
            if any(
                wanted in (
                    _normalise_host(other.unique_id or ""),
                    _normalise_host(other.data.get(CONF_HOST) or ""),
                )
                for other in self._async_current_entries(include_ignore=False)
                if other.entry_id != entry.entry_id
            ):
                errors["base"] = "already_configured"
            else:
                client = EconetClient(
                    host,
                    entry.data[CONF_USERNAME],
                    entry.data[CONF_PASSWORD],
                    async_get_clientsession(self.hass),
                )
                try:
                    sys_params = await EconetApi(client).fetch_sys_params()
                except AuthError:
                    errors["base"] = "invalid_auth"
                except (aiohttp.ClientError, OSError):
                    errors["base"] = "cannot_connect"
                except Exception:
                    _LOGGER.exception("Unexpected error during reconfigure")
                    errors["base"] = "unknown"
                else:
                    if sys_params is None:
                        errors["base"] = "cannot_connect"
                    else:
                        known = _known_uids(self.hass, entry)
                        new_uid = sys_params.get("uid")
                        if known and new_uid and new_uid not in known:
                            errors["base"] = "wrong_device"

            if not errors:
                # Follow the address in the title unless the owner renamed it.
                title = entry.title
                if title == f"EcoNet Grant ({entry.data[CONF_HOST]})":
                    title = f"EcoNet Grant ({host})"
                return self.async_update_and_abort(
                    entry,
                    unique_id=host,
                    title=title,
                    data_updates={CONF_HOST: host},
                )

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=self.add_suggested_values_to_schema(
                vol.Schema({vol.Required(CONF_HOST): str}),
                user_input or {CONF_HOST: entry.data[CONF_HOST]},
            ),
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
