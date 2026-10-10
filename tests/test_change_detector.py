"""Classification is tested through public poll/marker methods and HA events."""
import pytest

from custom_components.econet_grant.change_detector import ChangeDetector
from custom_components.econet_grant.const import (
    BITMASK_SELECT_DEFINITIONS, EVENT_SETTING_CHANGED, SELECT_DEFINITIONS,
    VOLATILE_PARAMETERS,
)


@pytest.mark.parametrize("name,old,new", [
    (name, old, new)
    for name, definition in SELECT_DEFINITIONS.items()
    for old in definition["options"] for new in definition["options"] if old != new
])
def test_notification_select_labels(hass, entry, notifications, name, old, new):
    detector = ChangeDetector(hass, entry)
    definition = SELECT_DEFINITIONS[name]
    index = definition["param_index"]
    detector.process_edit_params({"data": {index: {"name": name, "value": old}}})
    changes = detector.process_edit_params({"data": {index: {"name": name, "value": new}}})
    expected = f"**{definition['name']}**: {definition['options'][old]} → {definition['options'][new]}"
    assert expected in notifications.call_args.kwargs["message"]
    assert changes == [{"index": index, "name": name, "old_value": old,
                        "new_value": new, "source": "external"}]


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


@pytest.mark.parametrize("definition", list(BITMASK_SELECT_DEFINITIONS.values()))
@pytest.mark.parametrize("reverse", [False, True])
def test_notification_bitmask_labels(hass, entry, notifications, definition, reverse):
    detector = ChangeDetector(hass, entry)
    name = definition["settings_param_name"]
    old, new = (definition["bit_mask"], 0) if reverse else (0, definition["bit_mask"])
    detector.process_edit_params({"data": {"1": {"name": name, "value": old}}})
    changes = detector.process_edit_params({"data": {"1": {"name": name, "value": new}}})
    on, off = definition["on_label"], definition["off_label"]
    labels = (on, off) if reverse != definition.get("on_clears_bit", False) else (off, on)
    assert notifications.call_args.kwargs["message"] == (
        f"Settings changed externally:\n\n- **{definition['name']}**: {labels[0]} → {labels[1]}"
    )
    assert changes[0]["old_value"] == old and changes[0]["new_value"] == new


@pytest.mark.parametrize("old,new,expected", [
    (0, 1, "Yes → No"),
    (1, 0, "No → Yes"),
])
async def test_notification_bitmask_inverted_labels(
    hass, entry, notifications, monkeypatch, old, new, expected,
):
    import asyncio

    definition = dict(BITMASK_SELECT_DEFINITIONS["ExternalTempSensorSupport"])
    definition["on_clears_bit"] = True
    monkeypatch.setitem(BITMASK_SELECT_DEFINITIONS, "ExternalTempSensorSupport", definition)
    entry.options["push_notifications"] = True
    tasks = []
    hass.async_create_task = lambda coro: tasks.append(asyncio.create_task(coro))
    detector = ChangeDetector(hass, entry)
    detector.process_edit_params({"data": {"69": {"name": "TempSettings", "value": old}}})
    changes = detector.process_edit_params(
        {"data": {"69": {"name": "TempSettings", "value": new}}}
    )
    await asyncio.gather(*tasks)

    assert notifications.call_args.kwargs["message"] == (
        f"Settings changed externally:\n\n- **Ext Temp Sensor**: {expected}"
    )
    assert hass.services.async_call.call_args.args[2]["message"] == (
        f"Settings changed:\nExt Temp Sensor: {expected}"
    )
    assert changes == [{"index": "69", "name": "TempSettings", "old_value": old,
                        "new_value": new, "source": "external"}]
    hass.bus.async_fire.assert_any_call(EVENT_SETTING_CHANGED, {
        "param_name": "TempSettings", "param_index": "69",
        "old_value": old, "new_value": new,
    })


def test_notification_bitmask_multiple_and_unknown_bits(hass, entry, notifications):
    detector = ChangeDetector(hass, entry)
    detector.process_edit_params({"data": {"69": {"name": "TempSettings", "value": 8}}})
    detector.process_edit_params({"data": {"69": {"name": "TempSettings", "value": 19}}})
    message = notifications.call_args.kwargs["message"]
    assert "**Ext Temp Sensor**: No → Yes" in message
    assert "**Temp Sensor Source**: ecoMulti → Heat Pump" in message
    assert "**TempSettings unknown bits (0x18)**: 0x8 → 0x10" in message


@pytest.mark.parametrize("name,value", [
    (name, value)
    for name in ("Circuit1WorkState", "TempSettings")
    for value in (-1, 1.5, True, None, "bad", "1.5", [], {}, float("inf"), float("nan"))
] + [("Circuit1WorkState", 6)])
@pytest.mark.parametrize("reverse", [False, True])
def test_notification_unknown_numeric_values(hass, entry, notifications, name, value, reverse):
    detector = ChangeDetector(hass, entry)
    old, new = (0, value) if reverse else (value, 0)
    detector.process_edit_params({"data": {"1": {"name": name, "value": old}}})
    detector.process_edit_params({"data": {"1": {"name": name, "value": new}}})
    assert f"Unknown ({value!r})" in notifications.call_args.kwargs["message"]


@pytest.mark.parametrize("name,old,new,expected", [
    ("Circuit1WorkState", "3", 1.0, "CH Operation Mode: Schedule → Day"),
    ("TempSettings", "0", 1.0, "Ext Temp Sensor: No → Yes"),
    ("TempSettings", 0, 8, "TempSettings unknown bits (0x8): 0x0 → 0x8"),
    ("TempSettings", 0, "0", "TempSettings: Raw (0) → Raw ('0')"),
    ("Circuit1WorkState", 1, 6, "CH Operation Mode: Day → Unknown (6)"),
    ("Circuit1ComfortTemp", 20.5, 22, "CH Day Temp: 20.5 → 22"),
    ("UnmappedParameter", 4, 8, "UnmappedParameter: 4 → 8"),
])
async def test_notification_push_matches_persistent(
    hass, entry, notifications, name, old, new, expected,
):
    import asyncio

    entry.options["push_notifications"] = True
    tasks = []
    hass.async_create_task = lambda coro: tasks.append(asyncio.create_task(coro))
    detector = ChangeDetector(hass, entry)
    detector.process_edit_params({"data": {"1": {"name": name, "value": old}}})
    detector.process_edit_params({"data": {"1": {"name": name, "value": new}}})
    await asyncio.gather(*tasks)
    assert notifications.call_args.kwargs["message"].replace("**", "") == (
        f"Settings changed externally:\n\n- {expected}"
    )
    assert hass.services.async_call.call_args.args[2]["message"] == f"Settings changed:\n{expected}"


@pytest.mark.parametrize("old,new", [(20, 24), (20.5, 22.0)])
def test_notification_numeric_settings_unchanged(hass, entry, notifications, old, new):
    detector = ChangeDetector(hass, entry)
    detector.process_edit_params({"data": {"1": {"name": "Circuit1ComfortTemp", "value": old}}})
    detector.process_edit_params({"data": {"1": {"name": "Circuit1ComfortTemp", "value": new}}})
    assert f"**CH Day Temp**: {old} → {new}" in notifications.call_args.kwargs["message"]


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
