"""Repairs: a "Fix" button when the controller has been unreachable a while."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import voluptuous as vol

from homeassistant.components.repairs import RepairsFlow
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers import issue_registry as ir
from homeassistant.util import dt as dt_util

from .config_flow import (
    async_apply_connection,
    async_check_connection,
    connection_schema,
)
from .const import CONF_HOST, CONF_PASSWORD, CONF_USERNAME, DOMAIN

CONNECTION_ISSUE_AFTER = timedelta(minutes=10)
_FAILURES_KEY = f"{DOMAIN}_connection_failures"


def issue_id(entry: ConfigEntry) -> str:
    return f"cannot_connect_{entry.entry_id}"


@callback
def async_report_failure(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Note a failed contact; raise the issue once it has lasted long enough."""
    failures: dict[str, Any] = hass.data.setdefault(_FAILURES_KEY, {})
    now = dt_util.utcnow()
    first = failures.setdefault(entry.entry_id, now)
    if now - first >= CONNECTION_ISSUE_AFTER:
        ir.async_create_issue(
            hass,
            DOMAIN,
            issue_id(entry),
            is_fixable=True,
            severity=ir.IssueSeverity.ERROR,
            translation_key="cannot_connect",
            translation_placeholders={"host": entry.data[CONF_HOST]},
            data={"entry_id": entry.entry_id},
        )


@callback
def async_report_success(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Contact works again: forget the outage and clear the issue."""
    hass.data.get(_FAILURES_KEY, {}).pop(entry.entry_id, None)
    # A new outage should log its first address-follow refusal again.
    hass.data.get(f"{DOMAIN}_follow_logged", {}).pop(entry.entry_id, None)
    ir.async_delete_issue(hass, DOMAIN, issue_id(entry))


async def async_create_fix_flow(
    hass: HomeAssistant, issue_id: str, data: dict[str, Any] | None
) -> RepairsFlow:
    return ConnectionFixFlow((data or {}).get("entry_id", ""))


class ConnectionFixFlow(RepairsFlow):
    """Enter a new address or login for the unreachable controller."""

    def __init__(self, entry_id: str) -> None:
        self._entry_id = entry_id

    async def async_step_init(
        self, user_input: dict[str, str] | None = None
    ) -> FlowResult:
        entry = self.hass.config_entries.async_get_entry(self._entry_id)
        if entry is None:
            return self.async_abort(reason="entry_removed")
        errors: dict[str, str] = {}
        suggested = {
            CONF_HOST: entry.data[CONF_HOST],
            CONF_USERNAME: entry.data[CONF_USERNAME],
        }

        # HA starts a repairs flow by passing {"issue_id": ...} to the init
        # step; only a submitted form carries the host.
        if user_input is not None and CONF_HOST in user_input:
            host = user_input[CONF_HOST].strip()
            username = user_input[CONF_USERNAME].strip()
            password = user_input.get(CONF_PASSWORD) or entry.data[CONF_PASSWORD]
            error = await async_check_connection(
                self.hass, entry, host, username, password
            )
            if error is None:
                async_apply_connection(self.hass, entry, host, username, password)
                ir.async_delete_issue(self.hass, DOMAIN, issue_id(entry))
                return self.async_create_entry(data={})
            errors["base"] = error
            suggested = {CONF_HOST: host, CONF_USERNAME: username}

        schema: vol.Schema = connection_schema(entry.data[CONF_USERNAME])
        return self.async_show_form(
            step_id="init",
            data_schema=self.add_suggested_values_to_schema(schema, suggested),
            description_placeholders={"host": entry.data[CONF_HOST]},
            errors=errors,
        )
