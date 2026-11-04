"""Exercise flow decisions and real voluptuous schemas at mocked HA boundaries."""
from unittest.mock import AsyncMock, Mock

import pytest
import voluptuous as vol

from custom_components.econet_grant import config_flow


async def test_config_flow_success_defaults_to_safe_mode(hass, entry, api, monkeypatch):
    monkeypatch.setattr(config_flow, "async_get_clientsession", Mock())
    monkeypatch.setattr(config_flow, "EconetApi", Mock(return_value=api))
    api.test_connection.return_value = True
    flow = config_flow.EconetGrantConfigFlow()
    flow.hass = hass
    flow.async_set_unique_id = AsyncMock()
    flow._abort_if_unique_id_configured = Mock()
    flow.async_create_entry = Mock(return_value={"type": "create_entry"})
    assert await flow.async_step_user(entry.data) == {"type": "create_entry"}
    flow.async_set_unique_id.assert_awaited_once_with("econet.invalid")
    flow._abort_if_unique_id_configured.assert_called_once()
    assert flow.async_create_entry.call_args.kwargs["data"] == entry.data
    assert flow.async_create_entry.call_args.kwargs["options"]["safe_mode"] is True


async def test_config_flow_connection_failure(hass, entry, api, monkeypatch):
    monkeypatch.setattr(config_flow, "async_get_clientsession", Mock())
    monkeypatch.setattr(config_flow, "EconetApi", Mock(return_value=api))
    api.test_connection.return_value = False
    flow = config_flow.EconetGrantConfigFlow()
    flow.hass = hass
    result = await flow.async_step_user(entry.data)
    assert result["type"] == "form"
    assert result["errors"] == {"base": "cannot_connect"}


async def test_options_schema_and_submission(entry):
    flow = config_flow.EconetGrantOptionsFlow(entry)
    form = await flow.async_step_init()
    assert form["step_id"] == "init"
    schema = form["data_schema"]
    assert schema({})["safe_mode"] is True
    with pytest.raises(vol.Invalid):
        schema({"retention_days": 29})
    with pytest.raises(vol.Invalid):
        schema({"retention_days": 7301})
    options = schema({"safe_mode": False, "push_notifications": False, "retention_days": 30})
    result = await flow.async_step_init(options)
    assert result["type"] == "create_entry"
    assert result["data"] == options


async def test_slow_poll_option_default_boundaries_and_saved_value(entry):
    flow = config_flow.EconetGrantOptionsFlow(entry)
    schema = (await flow.async_step_init())["data_schema"]
    assert schema({})["slow_poll_interval"] == 5
    for minutes in (5, 60, 1440):
        options = schema({"slow_poll_interval": minutes})
        assert (await flow.async_step_init(options))["data"]["slow_poll_interval"] == minutes
    for invalid in (0, -1, 4, 1441, 5.5, "hourly", None, True):
        with pytest.raises(vol.Invalid):
            schema({"slow_poll_interval": invalid})
    entry.options["slow_poll_interval"] = 60
    schema = (await flow.async_step_init())["data_schema"]
    assert schema({})["slow_poll_interval"] == 60


async def test_revert_service_is_optional_and_mobile_only(entry):
    flow = config_flow.EconetGrantOptionsFlow(entry)
    schema = (await flow.async_step_init())["data_schema"]
    assert schema({})["revert_notify_service"] == ""
    assert schema({"revert_notify_service": "mobile_app_test"})["revert_notify_service"] == "mobile_app_test"
    for invalid in ("notify", "notify.mobile_app_test", "mobile_app_", "other_service", True):
        with pytest.raises(vol.Invalid):
            schema({"revert_notify_service": invalid})
    entry.options["revert_notify_service"] = "mobile_app_test"
    assert (await flow.async_step_init())["data_schema"]({})["revert_notify_service"] == "mobile_app_test"


async def test_user_step_strips_host_whitespace(hass, entry, api, monkeypatch):
    monkeypatch.setattr(config_flow, "async_get_clientsession", Mock())
    monkeypatch.setattr(config_flow, "EconetApi", Mock(return_value=api))
    api.test_connection.return_value = True
    flow = config_flow.EconetGrantConfigFlow()
    flow.hass = hass
    flow.async_set_unique_id = AsyncMock()
    flow._abort_if_unique_id_configured = Mock()
    flow.async_create_entry = Mock(return_value={"type": "create_entry"})
    await flow.async_step_user({**entry.data, "host": "  econet.invalid "})
    flow.async_set_unique_id.assert_awaited_once_with("econet.invalid")
    assert flow.async_create_entry.call_args.kwargs["data"]["host"] == "econet.invalid"


def test_translations_match_strings_and_cover_reconfigure():
    import json
    from pathlib import Path

    base = Path(config_flow.__file__).parent
    strings = json.loads((base / "strings.json").read_text())
    english = json.loads((base / "translations" / "en.json").read_text())
    assert strings == english
    config = strings["config"]
    assert "reconfigure" in config["step"]
    assert "wrong_device" in config["error"]
    assert "already_configured" in config["error"]
    assert "reconfigure_successful" in config["abort"]


def test_reconfigure_abort_text_covers_login_too():
    import json
    from pathlib import Path
    base = Path(__file__).parent.parent / "custom_components" / "econet_grant"
    for name in ("strings.json", "translations/en.json"):
        text = json.loads((base / name).read_text())["config"]["abort"]["reconfigure_successful"]
        assert text == "Connection updated. The integration has been reloaded."
