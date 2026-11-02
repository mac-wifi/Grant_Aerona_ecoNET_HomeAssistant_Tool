"""Restore behavior with real snapshot files, no device or production HA."""
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from unittest.mock import Mock

from custom_components.econet_grant import backup, services
from custom_components.econet_grant.change_detector import ChangeDetector
from custom_components.econet_grant.const import EVENT_SETTING_CHANGED


def restore_handler(hass, entry, api, db, detector):
    """Register the real services against one loaded synthetic entry."""
    entry.runtime_data = SimpleNamespace(api=api, database=db, change_detector=detector)
    hass.config_entries.async_loaded_entries = Mock(return_value=[entry])
    services.async_register_services(hass)
    return next(call.args[2] for call in hass.services.async_register.call_args_list
                if call.args[1] == "restore_settings")


@pytest.fixture
def snapshot(hass, edit_params):
    path = backup.snapshot_path(hass, "Default")
    path.write_text(json.dumps({"parameters": {"100": edit_params["data"]["100"]}}))
    return path


async def test_backup_keeps_only_editable_parameters(hass, api):
    assert await backup.async_backup_settings(hass, api)
    saved = json.loads(backup.snapshot_path(hass, "Default").read_text())
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


def restore_notice(notifications):
    calls = [c.kwargs for c in notifications.call_args_list
             if c.kwargs.get("notification_id") == "econet_grant_restore_result"]
    assert len(calls) == 1
    return calls[0]


async def test_restore_write_failure_reported(hass, api, snapshot, edit_params, notifications):
    edit_params["data"]["100"]["value"] = 24
    api.set_param.return_value = False
    result = await backup.async_restore_settings(hass, api, safe_mode=False)
    assert result["success"] is False
    assert result["changes"] == 0
    assert result["failures"] == 1
    api.set_param.assert_awaited_once_with("Circuit1ComfortTemp", 20)
    notice = restore_notice(notifications)
    assert notice["title"] == "EcoNet Grant - Restore Failed"
    assert "**1 failed**" in notice["message"]
    assert "- Circuit1ComfortTemp: 24 -> 20 (**failed**)" in notice["message"]


async def test_restore_write_exception_still_reports(hass, api, snapshot, edit_params,
                                                     notifications):
    edit_params["data"]["100"]["value"] = 24
    api.set_param.side_effect = OSError("synthetic connection reset")
    result = await backup.async_restore_settings(hass, api, safe_mode=False)
    assert result["success"] is False and result["failures"] == 1
    assert restore_notice(notifications)["title"] == "EcoNet Grant - Restore Failed"


async def test_restore_unreadable_snapshot_reports(hass, api, snapshot, notifications):
    snapshot.write_text("{corrupt")
    result = await backup.async_restore_settings(hass, api, safe_mode=False)
    assert result["success"] is False
    assert restore_notice(notifications)["title"] == "EcoNet Grant - Restore Not Possible"
    api.set_param.assert_not_awaited()


@pytest.mark.parametrize("failure", ["none", "exception"])
async def test_restore_fetch_failure_does_not_write(hass, api, snapshot, notifications, failure):
    if failure == "none":
        api.fetch_edit_params.return_value = None
    else:
        api.fetch_edit_params.side_effect = OSError("synthetic connection refused")
    assert await backup.async_restore_settings(hass, api, safe_mode=False) == {
        "success": False, "error": "Cannot fetch current editParams",
    }
    api.set_param.assert_not_awaited()
    notice = restore_notice(notifications)
    assert notice["title"] == "EcoNet Grant - Restore Failed"
    assert "Nothing was changed" in notice["message"]


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
    handler = restore_handler(hass, entry, api, db, detector)
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
    handler = restore_handler(
        hass, entry, api, SimpleNamespace(async_log_change=AsyncMock()), detector,
    )
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


@pytest.mark.parametrize("safe_mode", [True, False])
async def test_restore_ignores_volatile_parameters(hass, api, edit_params, notifications,
                                                   safe_mode):
    """Self-changing values (VOLATILE_PARAMETERS) must never be previewed or written."""
    edit_params["data"]["1148"] = {"name": "GrantReg03Float", "value": 39.0,
                                   "minv": 0, "maxv": 100, "edit": True}
    assert await backup.async_backup_settings(hass, api)
    edit_params["data"]["1148"]["value"] = 38.0
    result = await backup.async_restore_settings(hass, api, safe_mode=safe_mode)
    assert result["changes"] == 0
    api.set_param.assert_not_awaited()
    assert restore_notice(notifications)["title"] == "EcoNet Grant - Nothing to Restore"
