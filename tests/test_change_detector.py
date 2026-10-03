"""Classification is tested through public poll/marker methods and HA events."""
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
