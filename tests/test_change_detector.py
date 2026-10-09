"""Classification is tested through public poll/marker methods and HA events."""
import pytest

from custom_components.econet_grant.change_detector import ChangeDetector
from custom_components.econet_grant.const import EVENT_SETTING_CHANGED, VOLATILE_PARAMETERS


def test_external_change_emits_event(hass, entry, edit_params, notifications):
    detector = ChangeDetector(hass, entry)
    assert detector.process_edit_params(edit_params) == []
    assert detector.process_edit_params(edit_params) == []
    hass.bus.async_fire.assert_not_called()
    edit_params["data"]["100"]["value"] = 24
    changes = detector.process_edit_params(edit_params)
    assert changes == [{"index": "100", "name": "Circuit1ComfortTemp",
                        "old_value": 20, "new_value": 24, "source": "external"}]
    hass.bus.async_fire.assert_any_call(EVENT_SETTING_CHANGED, {
        "param_name": "Circuit1ComfortTemp", "param_index": "100",
        "old_value": 20, "new_value": 24,
    })
    notifications.assert_called_once()


def test_self_write_consumed_then_later_external_change_alerts(hass, entry, edit_params):
    detector = ChangeDetector(hass, entry)
    detector.process_edit_params(edit_params)
    detector.mark_self_write("Circuit1ComfortTemp")
    edit_params["data"]["100"]["value"] = 21
    assert detector.process_edit_params(edit_params)[0]["source"] == "user"
    hass.bus.async_fire.assert_not_called()
    edit_params["data"]["100"]["value"] = 24
    assert detector.process_edit_params(edit_params)[0]["source"] == "external"
    assert hass.bus.async_fire.call_args_list[0].args[0] == EVENT_SETTING_CHANGED


def test_volatile_changes_ignored_in_both_endpoints(hass, entry):
    detector = ChangeDetector(hass, entry)
    name = sorted(VOLATILE_PARAMETERS)[0]
    detector.process_edit_params({"data": {"1": {"name": name, "value": 1}}})
    detector.process_sys_params({name: 1})
    assert detector.process_edit_params({"data": {"1": {"name": name, "value": 2}}}) == []
    assert detector.process_sys_params({name: 2}) == []
    hass.bus.async_fire.assert_not_called()


@pytest.mark.parametrize("case", ["unchanged", "different", "renamed", "duplicate"])
def test_revert_expectation_does_not_hide_later_guest_change(
    hass, entry, edit_params, case,
):
    detector = ChangeDetector(hass, entry)
    detector.process_edit_params(edit_params)
    write = detector.begin_revert("100", "Circuit1ComfortTemp", 20, 24)
    detector.finish_revert(write)
    param = edit_params["data"]["100"]
    if case == "different":
        param["value"] = 22
    elif case == "renamed":
        param.update(name="HDWTSetPoint", value=24)
    elif case == "duplicate":
        edit_params["data"]["999"] = dict(param)
        param["value"] = 24

    changes = detector.process_edit_params(edit_params)
    assert all(c["source"] == "external" for c in changes)
    assert bool(changes) is (case != "unchanged")
    # In particular an unchanged poll must not leave a stale wildcard marker.
    param["value"] = 24 if case in ("unchanged", "different") else 25
    assert detector.process_edit_params(edit_params)[0]["source"] == "external"


def test_revert_inflight_poll_and_completion_consume_only_once(hass, entry, edit_params):
    detector = ChangeDetector(hass, entry)
    detector.process_edit_params(edit_params)
    write = detector.begin_revert("100", "Circuit1ComfortTemp", 20, 24)
    assert detector.process_edit_params(edit_params) == []  # before application
    edit_params["data"]["100"]["value"] = 24
    assert detector.process_edit_params(edit_params)[0]["source"] == "user"
    detector.finish_revert(write)
    edit_params["data"]["100"]["value"] = 25
    assert detector.process_edit_params(edit_params)[0]["source"] == "external"


def test_revert_empty_poll_retains_exact_expectation(hass, entry, edit_params):
    detector = ChangeDetector(hass, entry)
    detector.process_edit_params(edit_params)
    write = detector.begin_revert("100", "Circuit1ComfortTemp", 20, 24)
    detector.finish_revert(write)
    assert detector.process_edit_params({}) == []
    edit_params["data"]["100"]["value"] = 24
    assert detector.process_edit_params(edit_params)[0]["source"] == "user"
