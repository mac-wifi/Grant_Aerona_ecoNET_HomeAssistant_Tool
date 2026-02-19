"""Config flow for EcoNet Grant Aerona integration."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, ConfigFlow, OptionsFlow
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import AuthError, EconetClient, EconetApi
from .const import (
    CONF_HOST,
    CONF_PASSWORD,
    CONF_SAFE_MODE,
    CONF_USERNAME,
    DEFAULT_SAFE_MODE,
    DEFAULT_USERNAME,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)

USER_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_HOST): str,
        vol.Required(CONF_USERNAME, default=DEFAULT_USERNAME): str,
        vol.Required(CONF_PASSWORD): str,
    }
)


class EconetGrantConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for EcoNet Grant Aerona."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the initial user configuration step."""
        errors: dict[str, str] = {}

        if user_input is not None:
            host = user_input[CONF_HOST]
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
                        options={CONF_SAFE_MODE: DEFAULT_SAFE_MODE},
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
    ) -> FlowResult:
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        current_safe_mode = self._config_entry.options.get(
            CONF_SAFE_MODE, DEFAULT_SAFE_MODE
        )
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_SAFE_MODE, default=current_safe_mode): bool,
                }
            ),
        )
