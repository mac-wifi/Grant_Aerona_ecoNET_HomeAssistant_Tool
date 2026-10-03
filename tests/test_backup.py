"""Restore behavior with real snapshot files, no device or production HA."""
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

import custom_components.econet_grant as integration
from custom_components.econet_grant import backup
from custom_components.econet_grant.change_detector import ChangeDetector
from custom_components.econet_grant.const import (
    DOMAIN, EVENT_SETTING_CHANGED, SERVICE_API, SERVICE_DATABASE,
)


@pytest.fixture
def snapshot(hass, edit_params):
    path = backup._snapshot_path(hass, "Default")
    path.write_text(json.dumps({"parameters": {"100": edit_params["data"]["100"]}}))
    return path


async def test_backup_keeps_only_editable_parameters(hass, api):
    assert await backup.async_backup_settings(hass, api)
    saved = json.loads(backup._snapshot_path(hass, "Default").read_text())
    assert set(saved["parameters"]) == {"100", "101"}
    assert saved["parameters"]["100"]["value"] == 20
    api.set_param.assert_not_awaited()


async def test_noop_restore_does_not_write(hass, api, snapshot):
    assert await backup.async_restore_settings(hass, api, safe_mode=False) == {
        "success": True, "changes": 0, "details": [],
    }
    api.set_param.assert_not_awaited()


async def test_default_safe_mode_previews_without_write(hass, api, snapshot, edit_params):
    edit_params["data"]["100"]["value"] = 24
    result = await backup.async_restore_settings(hass, api)
    assert result["safe_mode"] is True
    assert result["changes"] == 1
    assert result["details"][0]["restore_value"] == 20
    api.set_param.assert_not_awaited()


async def test_restore_write_failure_reported(hass, api, snapshot, edit_params):
    edit_params["data"]["100"]["value"] = 24
    api.set_param.return_value = False
    result = await backup.async_restore_settings(hass, api, safe_mode=False)
    assert result["success"] is False
    assert result["changes"] == 0
    assert result["failures"] == 1
    api.set_param.assert_awaited_once_with("Circuit1ComfortTemp", 20)


async def test_restore_fetch_failure_does_not_write(hass, api, snapshot):
    api.fetch_edit_params.return_value = None
    assert await backup.async_restore_settings(hass, api, safe_mode=False) == {
        "success": False, "error": "Cannot fetch current editParams",
    }
    api.set_param.assert_not_awaited()


async def test_restore_missing_snapshot_does_not_fetch_or_write(hass, api):
    result = await backup.async_restore_settings(hass, api, safe_mode=False)
    assert result["success"] is False
    assert "not found" in result["error"]
    api.fetch_edit_params.assert_not_awaited()
    api.set_param.assert_not_awaited()


async def test_service_safe_mode_leaves_no_marker(hass, entry, api, snapshot, edit_params):
    detector = ChangeDetector(hass, entry)
    detector.process_edit_params(edit_params)
    db = SimpleNamespace(async_log_change=AsyncMock())
    hass.data[DOMAIN] = {entry.entry_id: {
        SERVICE_API: api, SERVICE_DATABASE: db, "change_detector": detector,
    }}
    integration._register_services(hass, entry)
    handler = next(call.args[2] for call in hass.services.async_register.call_args_list
                   if call.args[1] == "restore_settings")
    await handler(SimpleNamespace(data={}))
    api.set_param.assert_not_awaited()
    db.async_log_change.assert_not_awaited()
    edit_params["data"]["100"]["value"] = 24
    assert detector.process_edit_params(edit_params)[0]["source"] == "external"


class RestoreMarkerDefect(AssertionError):
    """Only the documented #11 symptom qualifies as an expected failure."""


@pytest.mark.xfail(strict=True, raises=RestoreMarkerDefect, reason="Deferred #11")
async def test_deferred_noop_restore_does_not_suppress_guest_alert(
    hass, entry, api, snapshot, edit_params,
):
    """#11: xfail only the known classification defect, not setup or no-write checks."""
    entry.options["safe_mode"] = False
    detector = ChangeDetector(hass, entry)
    detector.process_edit_params(edit_params)
    hass.data[DOMAIN] = {entry.entry_id: {
        SERVICE_API: api,
        SERVICE_DATABASE: SimpleNamespace(async_log_change=AsyncMock()),
        "change_detector": detector,
    }}
    integration._register_services(hass, entry)
    handler = next(call.args[2] for call in hass.services.async_register.call_args_list
                   if call.args[1] == "restore_settings")
    await handler(SimpleNamespace(data={}))
    api.set_param.assert_not_awaited()
    edit_params["data"]["100"]["value"] = 24
    changes = detector.process_edit_params(edit_params)
    # Failures outside this exact known symptom must not become expected failures.
    assert len(changes) == 1
    if changes[0]["source"] == "user" and not hass.bus.async_fire.called:
        raise RestoreMarkerDefect("No-op restore suppressed the next guest alert")
    assert changes[0]["source"] == "external"
    hass.bus.async_fire.assert_any_call(EVENT_SETTING_CHANGED, {
        "param_name": "Circuit1ComfortTemp", "param_index": "100",
        "old_value": 20, "new_value": 24,
    })
