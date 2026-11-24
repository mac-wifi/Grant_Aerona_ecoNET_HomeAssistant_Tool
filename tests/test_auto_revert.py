"""Auto-revert, against a real Home Assistant and the loopback emulator.

Writes are asserted as real HTTP requests (``pump.writes``). The three-setting
emulator fixture stays unchanged; each test adds the site's settings in-test.
Test names follow the plan's specification.
"""

import asyncio
import json
import sqlite3
from pathlib import Path

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.econet_grant import auto_revert as auto_revert_module
from custom_components.econet_grant.const import DOMAIN
from emulator import EconetEmulator
from test_ha_integration import hass, hass_config_dir, notifications  # noqa: F401

pytestmark = pytest.mark.usefixtures("loopback_sockets")

WORK_MODE = "select.grant_aerona_heat_pump_work_mode"
SUMMER = "number.grant_aerona_heat_pump_summer_threshold"
WINTER = "number.grant_aerona_heat_pump_winter_threshold"
HW_SET_POINT = "number.grant_aerona_heat_pump_hw_set_point"
HW_PRIORITY = "select.grant_aerona_heat_pump_hw_specify_priority"


def add_site_settings(pump):
    """This site: Winter, both thresholds 20, as the live controller reports them."""
    pump.edit["data"].update({
        "162": {"name": "workState2", "value": 2, "minv": 0, "maxv": 0, "edit": True},
        "702": {"name": "SummerOn", "value": 20, "minv": 20, "maxv": 30, "edit": True},
        "703": {"name": "SummerOff", "value": 20, "minv": 0, "maxv": 20, "edit": True},
        "115": {"name": "DHWBoost", "value": 0, "minv": 0, "maxv": 0, "edit": True},
        "1521": {"name": "Circuit1boosttimeleft", "value": 0, "minv": 0, "maxv": 180,
                 "edit": True},
    })


@pytest.fixture
def setup(real_hass, enable_custom_integrations, aiohttp_server, monkeypatch, hass_storage):
    """Load the integration; returns (hass, entry, pump, pushes)."""
    monkeypatch.setattr("custom_components.econet_grant.api.MIN_REQUEST_GAP", 0)
    state = {}

    async def _setup(*, safe_mode=False, auto_revert=True, grace=0, snapshot=True,
                     push=False, prepare=None):
        monkeypatch.setattr(auto_revert_module, "GRACE_SECONDS", grace)
        pump = EconetEmulator()
        add_site_settings(pump)
        if prepare:
            prepare(pump)
        server = await aiohttp_server(pump.app, host="127.0.0.1")
        assert await async_setup_component(real_hass, "persistent_notification", {})
        pushes = []

        async def notify(call):
            pushes.append(call.data)

        real_hass.services.async_register("notify", "notify", notify)
        entry = MockConfigEntry(
            domain=DOMAIN, title="Synthetic heat pump", unique_id="synthetic-auto-revert",
            data={"host": str(server.make_url("")), "username": "test", "password": "test-only"},
            options={"safe_mode": safe_mode, "push_notifications": push,
                     "auto_revert": auto_revert},
        )
        entry.add_to_hass(real_hass)
        assert await real_hass.config_entries.async_setup(entry.entry_id)
        await real_hass.async_block_till_done()
        assert entry.state is ConfigEntryState.LOADED
        if snapshot:
            await take_snapshot(real_hass)
        state["entry"] = entry
        return real_hass, entry, pump, pushes

    return _setup


async def take_snapshot(hass):
    await hass.services.async_call(DOMAIN, "backup_settings", {"snapshot_name": "Default"},
                                   blocking=True)
    await hass.async_block_till_done()


async def poll(hass, entry):
    await entry.runtime_data.slow_coordinator.async_refresh()
    await hass.async_block_till_done()


async def reload(hass, entry):
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED


async def set_options(hass, entry, **options):
    hass.config_entries.async_update_entry(entry, options={**entry.options, **options})
    await hass.async_block_till_done()


def notices(hass):
    return hass.data.get("persistent_notification", {})


def notice(hass, key):
    return notices(hass).get(f"econet_grant_auto_revert_{key}")


def ar(entry):
    return entry.runtime_data.auto_revert


def snapshot_file(hass):
    return Path(hass.config.config_dir) / "econet_grant_snapshots" / "Default.json"


async def audit(hass):
    def read():
        with sqlite3.connect(Path(hass.config.config_dir) / "econet_grant.db") as conn:
            return conn.execute(
                "SELECT param_name, old_value, new_value, source FROM change_log"
            ).fetchall()

    return await hass.async_add_executor_job(read)


# --- Packet 4: baseline, eligibility, overrides store ---


async def test_baseline_is_default_snapshot_and_survives_reload_and_restart(setup):
    hass, entry, pump, _ = await setup(auto_revert=False)
    targets = ar(entry).targets
    assert targets["workState2"] == 2
    assert targets["SummerOn"] == 20 and targets["SummerOff"] == 20
    assert targets["HDWTSetPoint"] == 50
    assert targets["HDWSETTINGS"] == 5 & (16 | 1 | 4096)
    assert "Circuit1ComfortTemp" not in targets and "DHWBoost" not in targets
    assert "Circuit1boosttimeleft" not in targets
    pump.guest_change("workState2", 1)
    await poll(hass, entry)
    await reload(hass, entry)  # a reload (and a restart) reads the same file again
    assert ar(entry).targets == targets
    assert pump.writes == []


async def test_summer_and_winter_thresholds_at_20_are_protected_and_in_range(setup):
    hass, entry, pump, _ = await setup()
    assert ar(entry).targets["SummerOn"] == 20
    assert ar(entry).targets["SummerOff"] == 20
    assert "SummerOn" not in ar(entry).unprotected
    assert "SummerOff" not in ar(entry).unprotected


async def test_selects_and_masks_with_zero_bounds_are_protected(setup):
    hass, entry, pump, _ = await setup()
    assert pump.edit["data"]["162"]["maxv"] == 0 and pump.edit["data"]["101"]["maxv"] == 0
    assert "workState2" in ar(entry).targets and "HDWSETTINGS" in ar(entry).targets


@pytest.mark.parametrize("case", ["missing", "unreadable", "empty"])
async def test_missing_or_unreadable_snapshot_warns_and_protects_nothing(setup, case):
    hass, entry, pump, _ = await setup(snapshot=case != "missing")
    if case != "missing":
        await hass.async_add_executor_job(
            snapshot_file(hass).write_text, "{not json" if case == "unreadable" else "{}")
        await reload(hass, entry)
    assert ar(entry).targets == {}
    assert ar(entry).effect == "no usable snapshot"
    assert "no usable Default snapshot" in notice(hass, "no_snapshot")["message"]
    pump.guest_change("workState2", 1)
    await poll(hass, entry)
    assert pump.writes == []


async def test_no_warning_when_auto_revert_is_off(setup):
    hass, entry, pump, _ = await setup(auto_revert=False, snapshot=False)
    assert notice(hass, "no_snapshot") is None
    assert ar(entry).effect == "off"


async def test_warning_dismissed_when_snapshot_saved(setup):
    hass, entry, pump, _ = await setup(snapshot=False)
    assert notice(hass, "no_snapshot") is not None
    await take_snapshot(hass)
    assert notice(hass, "no_snapshot") is None
    assert ar(entry).targets["workState2"] == 2


async def test_renamed_duplicate_or_readonly_parameter_not_protected_at_baseline(setup):
    def prepare(pump):
        pump.edit["data"]["103"]["name"] = "HDWTSetPointRenamed"
        pump.edit["data"]["9702"] = dict(pump.edit["data"]["702"])  # duplicate name

    hass, entry, pump, _ = await setup(prepare=prepare)
    unprotected = ar(entry).unprotected
    assert "HDWTSetPointRenamed" in unprotected["HDWTSetPoint"]
    assert "more than once" in unprotected["SummerOn"]
    assert "HDWTSetPoint" not in ar(entry).targets and "SummerOn" not in ar(entry).targets
    assert "SummerOff" in ar(entry).targets


async def test_snapshot_value_outside_the_definition_is_not_a_target(setup):
    def prepare(pump):
        pump.edit["data"]["162"]["value"] = 4  # never seen: not a known Work Mode option

    hass, entry, pump, _ = await setup(prepare=prepare)
    assert "workState2" not in ar(entry).targets
    assert "4" in ar(entry).unprotected["workState2"]


async def test_overrides_persist_drop_when_equal_and_clear_on_new_snapshot(setup):
    hass, entry, pump, _ = await setup()
    await ar(entry).async_record_override("HDWTSetPoint", 45)
    await ar(entry).async_record_override("HDWSETTINGS", 5 | 256)  # unlabelled bit ignored
    await ar(entry).async_record_override("Circuit1ComfortTemp", 23)  # excluded: ignored
    assert ar(entry).targets["HDWTSetPoint"] == 45
    assert ar(entry).targets["HDWSETTINGS"] == 5 & (16 | 1 | 4096)
    assert "Circuit1ComfortTemp" not in ar(entry).targets
    await reload(hass, entry)
    assert ar(entry).targets["HDWTSetPoint"] == 45
    await ar(entry).async_record_override("HDWTSetPoint", 50)  # equals the snapshot
    await reload(hass, entry)
    assert ar(entry)._overrides == {}
    await ar(entry).async_record_override("HDWTSetPoint", 45)
    revision = ar(entry).revision
    pump.guest_change("HDWTSetPoint", 47)
    await take_snapshot(hass)
    assert ar(entry).revision > revision
    assert ar(entry)._overrides == {}
    assert ar(entry).targets["HDWTSetPoint"] == 47
    await reload(hass, entry)
    assert ar(entry)._overrides == {}


async def test_divergences_judge_numbers_selects_and_masks(setup):
    hass, entry, pump, _ = await setup()
    data = pump.edit["data"]
    assert ar(entry).divergences(data) == []
    data["702"]["value"] = 19  # outside the definition range: still judged
    data["103"]["value"] = 50.04  # within tolerance
    data["162"]["value"] = 1
    data["101"]["value"] = 5 | 256  # unlabelled bit only: not a divergence
    found = {d.name: d for d in ar(entry).divergences(data)}
    assert set(found) == {"SummerOn", "workState2"}
    assert found["SummerOn"].observed == 19 and found["SummerOn"].target == 20
    assert found["workState2"].known is True
    data["162"]["value"] = 3  # not a known Work Mode option
    data["101"]["value"] = 4.5  # fractional mask
    found = {d.name: d for d in ar(entry).divergences(data)}
    assert found["workState2"].known is False
    assert found["HDWSETTINGS"].known is False
    data["1521"]["value"] = 99  # volatile, never judged
    data["238"]["value"] = 25  # CH Day Temp, never judged
    assert not {"Circuit1boosttimeleft", "Circuit1ComfortTemp"} & set(
        d.name for d in ar(entry).divergences(data))


# --- Packet 5: hooks (own writes, manual Revert, Restore pause, fetch-start stamp) ---


async def ha_set(hass, entity_id, value):
    if entity_id.startswith("number."):
        await hass.services.async_call("number", "set_value",
                                       {"entity_id": entity_id, "value": value}, blocking=True)
    else:
        await hass.services.async_call("select", "select_option",
                                       {"entity_id": entity_id, "option": value}, blocking=True)
    await hass.async_block_till_done()


async def test_ha_number_select_and_bitmask_writes_record_overrides(setup):
    hass, entry, pump, _ = await setup()
    await ha_set(hass, HW_SET_POINT, 45)
    await ha_set(hass, WORK_MODE, "Summer")
    await ha_set(hass, HW_PRIORITY, "Yes")
    assert pump.writes == [("HDWTSetPoint", 45.0), ("workState2", 1.0), ("HDWSETTINGS", 21.0)]
    targets = ar(entry).targets
    assert (targets["HDWTSetPoint"], targets["workState2"], targets["HDWSETTINGS"]) == (45, 1, 17)
    names = ("HDWTSetPoint", "workState2", "HDWSETTINGS")
    assert all(ar(entry).held(n) for n in names)  # until a poll started after completion
    await poll(hass, entry)
    assert not any(ar(entry).held(n) for n in names)


async def test_ha_write_sticks_across_reload_and_restart(setup):
    hass, entry, pump, _ = await setup()
    await ha_set(hass, SUMMER, 22)
    await reload(hass, entry)
    assert ar(entry).targets["SummerOn"] == 22


async def test_ha_write_equal_to_snapshot_drops_override(setup):
    hass, entry, pump, _ = await setup()
    await ha_set(hass, HW_SET_POINT, 45)
    await ha_set(hass, HW_SET_POINT, 50)
    assert ar(entry)._overrides == {}


async def test_safe_mode_ha_write_is_a_preview_and_records_nothing(setup):
    hass, entry, pump, _ = await setup(safe_mode=True)
    await ha_set(hass, HW_SET_POINT, 45)
    assert pump.writes == [] and ar(entry)._overrides == {}


async def test_manual_revert_counts_as_own_write(setup, monkeypatch):
    hass, entry, pump, pushes = await setup(push=True)
    await set_options(hass, entry, revert_notify_service="mobile_app_test")
    hass.services.async_register("notify", "mobile_app_test", lambda call: pushes.append(call.data))
    pump.guest_change("HDWTSetPoint", 45)
    await poll(hass, entry)
    token = next(p["data"]["actions"][0]["action"] for p in pushes if "data" in p)
    await take_snapshot(hass)  # the reference is now 45
    hass.bus.async_fire("mobile_app_notification_action", {"action": token})
    await hass.async_block_till_done()
    assert pump.writes == [("HDWTSetPoint", 50.0)]
    assert ar(entry).targets["HDWTSetPoint"] == 50  # the owner's tap sticks


async def test_failed_or_timed_out_ha_write_judged_only_from_post_completion_poll(setup):
    hass, entry, pump, _ = await setup()
    pump.write_modes = ["http_error"]
    await ha_set(hass, HW_SET_POINT, 45)  # refused: the entity logs, it does not raise
    assert ar(entry).held("HDWTSetPoint")
    pump.guest_change("HDWTSetPoint", 45)  # it was applied despite the error
    await poll(hass, entry)
    assert not ar(entry).held("HDWTSetPoint")
    assert ar(entry).targets["HDWTSetPoint"] == 45
    pump.write_modes = ["http_error"]
    await ha_set(hass, HW_SET_POINT, 47)  # not applied this time
    await poll(hass, entry)
    assert not ar(entry).held("HDWTSetPoint")
    assert ar(entry).targets["HDWTSetPoint"] == 45  # existing override kept


async def test_late_pre_completion_poll_does_not_decide(setup):
    hass, entry, pump, _ = await setup()
    started_before = entry.runtime_data.slow_coordinator.data_started_at
    pump.write_modes = ["http_error"]
    await ha_set(hass, HW_SET_POINT, 45)
    pump.guest_change("HDWTSetPoint", 45)
    await ar(entry).async_observe(pump.edit, started_before)
    assert ar(entry).held("HDWTSetPoint")
    assert "HDWTSetPoint" not in ar(entry)._overrides


async def test_two_overlapping_same_name_writes_hold_two_counts(setup):
    hass, entry, pump, _ = await setup()
    first = ar(entry).begin_own_write("HDWSETTINGS", 21)
    second = ar(entry).begin_own_write("HDWSETTINGS", 4117)
    await ar(entry).async_finish_own_write(second, True)
    assert ar(entry).held("HDWSETTINGS")
    await poll(hass, entry)
    assert ar(entry).held("HDWSETTINGS")
    await ar(entry).async_finish_own_write(first, True)
    assert ar(entry).held("HDWSETTINGS")  # until a poll started after both ended
    assert ar(entry).targets["HDWSETTINGS"] == 21 & (16 | 1 | 4096)  # last completed wins
    await poll(hass, entry)
    assert not ar(entry).held("HDWSETTINGS")


async def restore(hass, name="Default"):
    await hass.services.async_call(DOMAIN, "restore_settings", {"snapshot_name": name},
                                   blocking=True)
    await hass.async_block_till_done()


@pytest.mark.parametrize("case", ["safe_mode", "missing", "unreadable", "preflight"])
async def test_restore_preview_and_prewrite_failures_keep_overrides(setup, case):
    hass, entry, pump, _ = await setup()
    await ha_set(hass, HW_SET_POINT, 45)
    name = "Default"
    if case == "safe_mode":
        await set_options(hass, entry, safe_mode=True)
    elif case == "missing":
        name = "Missing"
    elif case == "unreadable":
        await hass.async_add_executor_job(snapshot_file(hass).write_text, "{not json")
    else:
        pump.unavailable = True
    writes = len(pump.writes)
    if case == "unreadable":
        # Existing behaviour, unchanged here: with Safe Mode off the service
        # raises on an unreadable snapshot before anything is written.
        with pytest.raises(ValueError):
            await restore(hass, name)
    else:
        await restore(hass, name)
    pump.unavailable = False
    assert len(pump.writes) == writes
    assert not ar(entry).paused
    await reload(hass, entry)
    assert ar(entry)._overrides == {"HDWTSetPoint": 45}


async def test_authorised_restore_clears_overrides_at_first_write(setup):
    hass, entry, pump, _ = await setup()
    await ha_set(hass, HW_SET_POINT, 45)
    resume_before = ar(entry)._resume_after
    await restore(hass)
    assert pump.writes[-1] == ("HDWTSetPoint", 50.0)
    assert ar(entry)._overrides == {}
    assert not ar(entry).paused and ar(entry)._resume_after > resume_before
    assert not ar(entry).judgeable(resume_before)


async def test_restore_exception_releases_the_pause(setup, monkeypatch):
    hass, entry, pump, _ = await setup()

    async def broken(*args, **kwargs):
        raise RuntimeError("synthetic")

    monkeypatch.setattr("custom_components.econet_grant.services.async_restore_settings", broken)
    with pytest.raises(RuntimeError):
        await restore(hass)
    assert not ar(entry).paused


async def test_unload_closes_auto_revert(setup):
    hass, entry, pump, _ = await setup()
    instance = ar(entry)
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert instance._active is False and instance._unsubscribe is None


async def test_failed_write_to_an_unprotected_setting_is_not_tracked(setup):
    hass, entry, pump, _ = await setup()
    pump.write_modes = ["http_error"]
    await ha_set(hass, "number.grant_aerona_heat_pump_ch_day_temp", 22)
    assert ar(entry)._own == {}
    await poll(hass, entry)  # must not raise in the background


# --- Packet 6: execution ---


def auto_writes(pump, before):
    return pump.writes[before:]


async def guest(hass, entry, pump, name, value):
    pump.guest_change(name, value)
    await poll(hass, entry)


async def test_default_off_writes_nothing(setup):
    hass, entry, pump, _ = await setup(auto_revert=False)
    await guest(hass, entry, pump, "workState2", 1)
    await poll(hass, entry)
    assert pump.writes == []
    assert not [k for k in notices(hass) if "auto_revert" in k]


async def test_safe_mode_on_reports_would_revert_and_writes_nothing(setup):
    hass, entry, pump, _ = await setup(safe_mode=True)
    await guest(hass, entry, pump, "workState2", 1)
    assert pump.writes == []
    message = notice(hass, "workState2")["message"]
    assert "Winter" in message and "Summer" in message and "nothing was changed" in message
    assert ar(entry).effect == "reporting only (Safe Mode on)"


async def test_safe_mode_report_once_per_episode(setup):
    hass, entry, pump, _ = await setup(safe_mode=True)
    await guest(hass, entry, pump, "workState2", 1)
    pn = hass.data["persistent_notification"]
    pn.pop("econet_grant_auto_revert_workState2")
    await poll(hass, entry)
    assert notice(hass, "workState2") is None  # same wrong value: no repeat
    await guest(hass, entry, pump, "workState2", 2)
    await guest(hass, entry, pump, "workState2", 1)
    assert notice(hass, "workState2") is not None  # a new episode


async def test_armed_reverts_number_select_and_bitmask(setup):
    hass, entry, pump, _ = await setup()
    pump.guest_change("workState2", 1)
    pump.guest_change("SummerOff", 18)
    pump.guest_change("HDWSETTINGS", 4)  # HW Support (bit 1) switched off
    await poll(hass, entry)
    assert sorted(pump.writes) == [("HDWSETTINGS", 5.0), ("SummerOff", 20.0), ("workState2", 2.0)]
    assert "put back" in notice(hass, "workState2")["message"]
    rows = [r for r in await audit(hass) if r[3] == "auto_revert"]
    assert {r[0] for r in rows} == {"workState2", "SummerOff", "HDWSETTINGS"}
    await poll(hass, entry)  # the corrections are not reported as guest changes
    assert len(pump.writes) == 3
    assert notice(hass, "workState2")["title"] == "EcoNet Grant - Setting put back"


async def test_bitmask_restores_only_labelled_bits_even_if_unlabelled_bits_change(setup):
    hass, entry, pump, _ = await setup()
    # Snapshot 5 = bits 1 and 4; labelled bits are 1, 16 and 4096 (4 and 256 are not).
    await guest(hass, entry, pump, "HDWSETTINGS", 4 | 16 | 256)  # bit 1 off, 16 on, 256 on
    assert pump.writes == [("HDWSETTINGS", float(1 | 4 | 256))]  # unlabelled bits kept


async def test_grace_after_load_lists_differences_and_does_not_write_for_5_minutes(setup, monkeypatch):
    hass, entry, pump, _ = await setup(grace=300)
    await guest(hass, entry, pump, "workState2", 1)
    assert pump.writes == []
    assert "will be put back" in notice(hass, "grace")["message"]
    clock = [auto_revert_module.monotonic() + 301]
    monkeypatch.setattr(auto_revert_module, "monotonic", lambda: clock[0])
    entry.runtime_data.slow_coordinator.data_started_at = clock[0]
    monkeypatch.setattr("custom_components.econet_grant.coordinator.monotonic",
                        lambda: clock[0])
    await poll(hass, entry)
    assert pump.writes == [("workState2", 2.0)]


async def test_same_wrong_value_one_attempt_but_new_episode_qualifies_again(setup):
    hass, entry, pump, _ = await setup()
    pump.mode = "non_ok"  # the controller refuses
    await guest(hass, entry, pump, "workState2", 1)
    await poll(hass, entry)
    assert pump.writes == [("workState2", 2.0)]
    assert "Auto-revert failed" in notice(hass, "workState2")["title"]
    pump.mode = "ok"
    await guest(hass, entry, pump, "workState2", 6)
    assert pump.writes[-1] == ("workState2", 2.0) and len(pump.writes) == 2


async def test_failed_write_not_retried_on_next_poll_and_notified(setup):
    hass, entry, pump, _ = await setup()
    pump.mode = "http_error"
    await guest(hass, entry, pump, "SummerOn", 25)
    await poll(hass, entry)
    await poll(hass, entry)
    assert pump.writes == [("SummerOn", 20.0)]
    assert "not accepted" in notice(hass, "SummerOn")["message"]


async def test_pre_send_cancellation_does_not_consume_the_attempt(setup, monkeypatch):
    hass, entry, pump, _ = await setup()
    real = entry.runtime_data.api.fetch_edit_params

    async def fetch_then_owner_writes(*args, **kwargs):
        result = await real(*args, **kwargs)
        ar(entry).revision += 1  # e.g. the owner started a write meanwhile
        return result

    monkeypatch.setattr(entry.runtime_data.api, "fetch_edit_params", fetch_then_owner_writes)
    await guest(hass, entry, pump, "workState2", 1)
    assert pump.writes == []
    monkeypatch.setattr(entry.runtime_data.api, "fetch_edit_params", real)
    await poll(hass, entry)
    assert pump.writes == [("workState2", 2.0)]


async def test_hourly_cap_stops_a_fight(setup):
    hass, entry, pump, _ = await setup()
    for wrong in (1, 6, 1):
        await guest(hass, entry, pump, "workState2", wrong)
        await poll(hass, entry)
    assert len(pump.writes) == 3
    await guest(hass, entry, pump, "workState2", 6)
    assert len(pump.writes) == 3
    assert "stopped" in notice(hass, "workState2")["message"]


async def test_not_confirmed_is_reported_once(setup):
    hass, entry, pump, _ = await setup()
    pump.mode = "value_mismatch"
    pump.write_modes = ["ok"]

    await guest(hass, entry, pump, "SummerOff", 18)
    pump.guest_change("SummerOff", 18)  # the controller put it straight back
    await poll(hass, entry)
    assert "not confirmed" in notice(hass, "SummerOff")["title"]
    assert pump.writes == [("SummerOff", 20.0)]


async def test_day_temperature_and_hw_boost_never_reverted(setup):
    hass, entry, pump, _ = await setup()
    await guest(hass, entry, pump, "Circuit1ComfortTemp", 25)
    await guest(hass, entry, pump, "DHWBoost", 1)
    assert pump.writes == []


async def test_volatile_and_unlabelled_never_reverted(setup):
    hass, entry, pump, _ = await setup()
    await guest(hass, entry, pump, "Circuit1boosttimeleft", 50)
    await guest(hass, entry, pump, "HDWSETTINGS", 5 | 256)
    assert pump.writes == []


async def test_work_mode_reverts_to_snapshot_value_whatever_the_other_raw_value(setup):
    hass, entry, pump, _ = await setup()
    for wrong in (1, 6):
        await guest(hass, entry, pump, "workState2", wrong)
        await poll(hass, entry)
    assert pump.writes == [("workState2", 2.0), ("workState2", 2.0)]


async def test_any_select_with_an_unknown_value_is_left_alone_and_notified(setup):
    hass, entry, pump, _ = await setup()
    await guest(hass, entry, pump, "workState2", 3)
    await poll(hass, entry)
    assert pump.writes == []
    assert "not recognise" in notice(hass, "workState2")["message"]


async def test_select_value_not_a_known_option_is_left_alone_and_mask_with_fractional_value_is_not_protected(setup):
    hass, entry, pump, _ = await setup()
    await guest(hass, entry, pump, "HDWSETTINGS", 4.5)
    assert pump.writes == []


async def test_observed_summer_19_outside_definition_range_is_still_judged(setup):
    hass, entry, pump, _ = await setup()
    pump.edit["data"]["702"]["minv"] = 0  # suppose the controller allowed it
    await guest(hass, entry, pump, "SummerOn", 19)
    assert pump.writes == [("SummerOn", 20.0)]


async def test_threshold_blocked_by_the_other_threshold_is_notified_once_and_not_sent(setup):
    hass, entry, pump, _ = await setup()
    # A guest lowers Winter to 15 and Summer to 18; the controller then allows Winter
    # only up to 18, so Winter 20 cannot be sent until Summer is back at 20.
    pump.guest_change("SummerOff", 15)
    pump.guest_change("SummerOn", 18)
    pump.edit["data"]["702"]["minv"] = 15
    pump.edit["data"]["703"]["maxv"] = 18
    await poll(hass, entry)
    assert ("SummerOff", 20.0) not in pump.writes
    assert ("SummerOn", 20.0) in pump.writes
    assert "other season threshold" in notice(hass, "SummerOff")["message"]
    count = len(pump.writes)
    await poll(hass, entry)
    assert len(pump.writes) == count


async def test_threshold_revert_rejected_by_controller_is_reported_once_not_retried(setup):
    hass, entry, pump, _ = await setup()
    pump.mode = "non_ok"
    await guest(hass, entry, pump, "SummerOn", 25)
    await poll(hass, entry)
    assert pump.writes == [("SummerOn", 20.0)]


async def test_threshold_target_outside_fresh_live_bounds_is_never_sent(setup):
    hass, entry, pump, _ = await setup()
    pump.edit["data"]["103"]["maxv"] = 45  # HW Set Point limit lowered by the controller
    await guest(hass, entry, pump, "HDWTSetPoint", 40)
    assert pump.writes == []
    assert "current limits" in notice(hass, "HDWTSetPoint")["message"]


async def test_bounds_change_after_baseline_cancels_the_write(setup, monkeypatch):
    hass, entry, pump, _ = await setup()
    real = entry.runtime_data.api.fetch_edit_params

    async def fetch_with_new_bounds(*args, **kwargs):
        pump.edit["data"]["702"]["minv"] = 21
        return await real(*args, **kwargs)

    monkeypatch.setattr(entry.runtime_data.api, "fetch_edit_params", fetch_with_new_bounds)
    await guest(hass, entry, pump, "SummerOn", 25)
    assert pump.writes == []


async def test_renamed_duplicate_or_readonly_parameter_not_protected_and_cancelled_if_it_changes_later(setup, monkeypatch):
    hass, entry, pump, _ = await setup()
    real = entry.runtime_data.api.fetch_edit_params

    async def fetch_readonly(*args, **kwargs):
        if "authorise" in kwargs:  # only auto-revert's fresh read, not the poll
            pump.edit["data"]["162"]["edit"] = False
        return await real(*args, **kwargs)

    monkeypatch.setattr(entry.runtime_data.api, "fetch_edit_params", fetch_readonly)
    await guest(hass, entry, pump, "workState2", 1)
    assert pump.writes == []
    assert "cancelled" in notice(hass, "workState2")["title"]


async def test_ha_number_select_and_bitmask_writes_stick_with_autorevert_on(setup):
    hass, entry, pump, _ = await setup()
    await ha_set(hass, HW_SET_POINT, 45)
    await ha_set(hass, WORK_MODE, "Summer")
    await ha_set(hass, HW_PRIORITY, "Yes")
    await poll(hass, entry)
    await poll(hass, entry)
    assert len(pump.writes) == 3


async def test_no_automatic_http_send_between_an_own_writes_timeout_retries(setup):
    hass, entry, pump, _ = await setup()
    own = ar(entry).begin_own_write("workState2", 1)
    await guest(hass, entry, pump, "workState2", 6)
    assert pump.writes == []
    await ar(entry).async_finish_own_write(own, False)
    await poll(hass, entry)  # settles: 6 is not what we wrote, override unchanged
    await poll(hass, entry)
    assert pump.writes == [("workState2", 2.0)]


async def test_overlapping_own_write_cancels_queued_revert(setup, monkeypatch):
    hass, entry, pump, _ = await setup()
    real = entry.runtime_data.api.fetch_edit_params

    async def fetch_during_own_write(*args, **kwargs):
        result = await real(*args, **kwargs)
        ar(entry).begin_own_write("workState2", 6)
        return result

    monkeypatch.setattr(entry.runtime_data.api, "fetch_edit_params", fetch_during_own_write)
    await guest(hass, entry, pump, "workState2", 1)
    assert pump.writes == []


async def test_restore_pauses_cancels_queued_and_resumes_after_post_release_poll(setup):
    hass, entry, pump, _ = await setup()
    ar(entry).pause()
    await guest(hass, entry, pump, "workState2", 1)
    assert pump.writes == []
    ar(entry).resume()
    await poll(hass, entry)
    assert pump.writes == [("workState2", 2.0)]


async def test_two_overlapping_restores_cannot_release_each_other(setup):
    hass, entry, pump, _ = await setup()
    ar(entry).pause()
    ar(entry).pause()
    ar(entry).resume()
    await guest(hass, entry, pump, "workState2", 1)
    assert pump.writes == []
    ar(entry).resume()
    await poll(hass, entry)
    assert pump.writes == [("workState2", 2.0)]


async def test_stale_restore_markers_do_not_hide_a_divergence(setup):
    hass, entry, pump, _ = await setup()
    await set_options(hass, entry, safe_mode=False)
    await restore(hass)  # nothing to restore, but #11 leaves name-only markers
    await guest(hass, entry, pump, "workState2", 1)
    assert pump.writes == [("workState2", 2.0)]


async def test_switching_off_stops_and_unload_cancels(setup):
    hass, entry, pump, _ = await setup()
    await set_options(hass, entry, auto_revert=False)
    await guest(hass, entry, pump, "workState2", 1)
    assert pump.writes == []


# --- Packet 7: sensor ---

SENSOR = "sensor.grant_aerona_heat_pump_auto_revert"


async def test_sensor_mirrors_option_and_reports_effect(setup):
    hass, entry, pump, _ = await setup(safe_mode=True)
    await entry.runtime_data.fast_coordinator.async_refresh()
    await hass.async_block_till_done()
    state = hass.states.get(SENSOR)
    assert state.state == "On"
    assert state.attributes["effect"] == "reporting only (Safe Mode on)"
    assert state.attributes["protected_count"] == len(ar(entry).targets) > 0
    assert state.attributes["snapshot_date"]
    await set_options(hass, entry, safe_mode=False)
    assert hass.states.get(SENSOR).attributes["effect"] == "active"
    await set_options(hass, entry, auto_revert=False)
    assert hass.states.get(SENSOR).state == "Off"


async def test_new_snapshot_reloads_baseline_and_clears_overrides(setup):
    hass, entry, pump, _ = await setup()
    await ha_set(hass, HW_SET_POINT, 45)
    await guest(hass, entry, pump, "workState2", 1)  # reverted to the old target, 2
    assert pump.writes[-1] == ("workState2", 2.0)
    pump.guest_change("workState2", 1)
    await take_snapshot(hass)  # 1 is now the reference; the override is gone
    assert ar(entry)._overrides == {}
    assert ar(entry).targets["workState2"] == 1 and ar(entry).targets["HDWTSetPoint"] == 45
    before = len(pump.writes)
    await poll(hass, entry)
    assert pump.writes[before:] == []


async def test_two_overlapping_same_name_writes_hold_two_counts_and_no_auto_send_until_both_end(
        setup, monkeypatch):
    hass, entry, pump, _ = await setup()
    api = entry.runtime_data.api
    real = api.set_param
    gate = asyncio.Event()
    entered = []
    automatic = []  # auto-revert always passes a dispatch-time guard

    async def slow_set_param(name, value, **kwargs):
        if "authorise" in kwargs:
            automatic.append(name)
            return await real(name, value, **kwargs)
        entered.append(value)
        if len(entered) == 1:
            await gate.wait()  # the first toggle is still in flight
        return await real(name, value, **kwargs)

    monkeypatch.setattr(api, "set_param", slow_set_param)
    def toggle(entity_id):
        # Not ha_set: its async_block_till_done would wait for the other toggle.
        return hass.async_create_task(hass.services.async_call(
            "select", "select_option", {"entity_id": entity_id, "option": "Yes"},
            blocking=True))

    first = toggle(HW_PRIORITY)
    await asyncio.sleep(0)
    for _ in range(20):
        if entered:
            break
        await asyncio.sleep(0.01)
    second = toggle("select.grant_aerona_heat_pump_off_circuits_on_hw")
    for _ in range(50):
        if len(entered) == 2 or second.done():
            break
        await asyncio.sleep(0.01)
    assert ar(entry).held("HDWSETTINGS")
    pump.guest_change("HDWTSetPoint", 40)  # an unrelated guest change is still handled
    pump.guest_change("HDWSETTINGS", 4)  # and a wrong mask value meanwhile...
    # Not async_block_till_done: the first toggle is deliberately still waiting.
    await entry.runtime_data.slow_coordinator.async_refresh()
    for _ in range(50):
        if ("HDWTSetPoint", 50.0) in pump.writes:
            break
        await asyncio.sleep(0.01)
    assert "HDWSETTINGS" not in automatic  # ...is not auto-sent while one write is open
    assert ar(entry).held("HDWSETTINGS")
    gate.set()
    await asyncio.wait_for(asyncio.gather(first, second), 10)
    await hass.async_block_till_done()
    await poll(hass, entry)
    assert not ar(entry).held("HDWSETTINGS")
    assert len(entered) == 2 and "HDWSETTINGS" not in automatic
    assert [w[0] for w in pump.writes].count("HDWSETTINGS") == 2  # only the two own writes


# --- Review fixes (2026-11-24 code review) ---


def short_timeouts(entry, monkeypatch, seconds=0.3):
    from aiohttp import ClientTimeout
    monkeypatch.setattr(entry.runtime_data.api._client, "_timeout", ClientTimeout(total=seconds))


def gate_store_saves(entry, monkeypatch):
    """Make overrides saves wait until released; returns (entered, release)."""
    store = ar(entry)._store
    real = store.async_save
    entered, release = asyncio.Event(), asyncio.Event()

    async def slow_save(data):
        entered.set()
        await release.wait()
        await real(data)

    monkeypatch.setattr(store, "async_save", slow_save)
    return entered, release


def select_task(hass, entity_id, option):
    return hass.async_create_task(hass.services.async_call(
        "select", "select_option", {"entity_id": entity_id, "option": option}, blocking=True))


async def wait_for(condition, seconds=5):
    for _ in range(int(seconds / 0.01)):
        if condition():
            return
        await asyncio.sleep(0.01)
    raise AssertionError("condition not reached")


async def test_stale_finaliser_cannot_release_a_newer_writes_hold_during_its_timeout_retries(
        setup, monkeypatch):
    hass, entry, pump, _ = await setup()
    short_timeouts(entry, monkeypatch)
    entered, release = gate_store_saves(entry, monkeypatch)
    first = select_task(hass, WORK_MODE, "Summer")  # acknowledged; its save is slow
    await asyncio.wait_for(entered.wait(), 5)
    # A poll that started after the first write ended runs during the slow save.
    await ar(entry).async_observe(pump.edit, auto_revert_module.monotonic())
    pump.write_modes = ["timeout", "timeout", "ok"]
    second = select_task(hass, WORK_MODE, "Auto")  # a newer own write, retrying
    await wait_for(lambda: len(pump.writes) == 2)
    release.set()
    await asyncio.wait_for(first, 5)  # the old finaliser ends during the retries
    pump.guest_change("workState2", 2)  # meanwhile something else changes it
    judged = hass.async_create_task(
        ar(entry).async_observe(pump.edit, auto_revert_module.monotonic()))
    try:
        await asyncio.wait_for(asyncio.gather(second, judged), 10)
    finally:
        for release_timeout in pump.timeout_releases:  # held emulator responses
            release_timeout.set()
    # Only the own write's three attempts: nothing automatic between its retries.
    assert pump.writes == [("workState2", 1.0)] + [("workState2", 6.0)] * 3


async def test_successful_own_write_held_until_a_post_completion_poll(setup):
    hass, entry, pump, _ = await setup()
    before = auto_revert_module.monotonic()
    await ha_set(hass, WORK_MODE, "Summer")
    pump.guest_change("workState2", 2)
    await ar(entry).async_observe(pump.edit, before)  # started before completion
    assert ar(entry).held("workState2") and pump.writes == [("workState2", 1.0)]
    await poll(hass, entry)  # releases the hold, then judges: 2 is not what was written
    assert not ar(entry).held("workState2")
    assert pump.writes == [("workState2", 1.0), ("workState2", 1.0)]


async def test_restore_during_first_items_read_cancels_the_rest_of_that_poll(setup, monkeypatch):
    hass, entry, pump, _ = await setup()
    api = entry.runtime_data.api
    real = api.fetch_edit_params
    restored = []

    async def fetch_with_restore_meanwhile(*args, **kwargs):
        if "authorise" in kwargs and not restored:
            restored.append(True)  # a whole Restore starts and finishes here
            await hass.services.async_call(DOMAIN, "restore_settings",
                                           {"snapshot_name": "Missing"}, blocking=True)
        return await real(*args, **kwargs)

    monkeypatch.setattr(api, "fetch_edit_params", fetch_with_restore_meanwhile)
    pump.guest_change("workState2", 1)
    pump.guest_change("SummerOn", 25)
    await ar(entry).async_observe(pump.edit, auto_revert_module.monotonic())
    assert restored and pump.writes == []  # neither item uses the pre-Restore poll
    await poll(hass, entry)  # a poll that started after the Restore ended
    assert sorted(pump.writes) == [("SummerOn", 20.0), ("workState2", 2.0)]


async def test_nothing_judged_against_the_old_reference_while_a_new_snapshot_loads(
        setup, monkeypatch):
    hass, entry, pump, _ = await setup()
    entered, release = gate_store_saves(entry, monkeypatch)
    pump.guest_change("workState2", 1)  # the owner's new intended value
    saved = hass.async_create_task(hass.services.async_call(
        DOMAIN, "backup_settings", {"snapshot_name": "Default"}, blocking=True))
    await asyncio.wait_for(entered.wait(), 5)
    await ar(entry).async_observe(pump.edit, auto_revert_module.monotonic())
    assert pump.writes == []
    release.set()
    await asyncio.wait_for(saved, 5)
    await hass.async_block_till_done()
    assert ar(entry).targets["workState2"] == 1
    await poll(hass, entry)
    assert pump.writes == []


MALFORMED_SNAPSHOTS = {
    "entry_not_a_dict": {"parameters": {"103": "invalid", "162": None}},
    "parameters_a_list": {"parameters": ["invalid"]},
    "parameters_null": {"parameters": None},
    "top_level_list": ["invalid"],
    "bad_values": {"created_at": 5, "parameters": {
        "162": {"name": "workState2", "value": "Winter"},
        "702": {"name": "SummerOn", "value": [20]}}},
}


@pytest.mark.parametrize("enabled", [True, False])
@pytest.mark.parametrize("shape", sorted(MALFORMED_SNAPSHOTS))
async def test_malformed_snapshot_never_stops_the_integration_loading(setup, shape, enabled):
    hass, entry, pump, _ = await setup(auto_revert=enabled)
    await hass.async_add_executor_job(
        snapshot_file(hass).write_text, json.dumps(MALFORMED_SNAPSHOTS[shape]))
    await reload(hass, entry)
    assert entry.state is ConfigEntryState.LOADED
    assert hass.states.get(HW_SET_POINT) is not None  # monitoring and control still work
    assert not ar(entry).snapshot_usable and ar(entry).targets == {}
    assert (notice(hass, "no_snapshot") is not None) is enabled
    pump.guest_change("workState2", 1)
    await poll(hass, entry)
    assert pump.writes == []


async def test_partly_malformed_snapshot_protects_only_the_valid_entries(setup):
    hass, entry, pump, _ = await setup()
    data = json.loads(await hass.async_add_executor_job(snapshot_file(hass).read_text))
    data["parameters"]["702"] = "invalid"
    await hass.async_add_executor_job(snapshot_file(hass).write_text, json.dumps(data))
    await reload(hass, entry)
    assert entry.state is ConfigEntryState.LOADED
    assert "SummerOn" in ar(entry).unprotected and ar(entry).targets["workState2"] == 2


@pytest.mark.parametrize("stored", [{"overrides": "invalid"}, ["invalid"], {"overrides": None}])
async def test_malformed_stored_overrides_are_ignored(setup, hass_storage, stored):
    hass, entry, pump, _ = await setup()
    key = f"{DOMAIN}.auto_revert.{entry.entry_id}"
    hass_storage[key] = {"version": 1, "minor_version": 1, "key": key, "data": stored}
    await reload(hass, entry)
    assert entry.state is ConfigEntryState.LOADED and ar(entry)._overrides == {}



async def test_settling_one_failed_write_cannot_release_a_newer_hold_on_another_setting(
        setup, monkeypatch):
    hass, entry, pump, _ = await setup()
    short_timeouts(entry, monkeypatch)
    # A (HW Set Point) fails but was applied; B (Work Mode) completes normally.
    pump.write_modes = ["http_error"]
    await ha_set(hass, HW_SET_POINT, 45)
    pump.guest_change("HDWTSetPoint", 45)
    await ha_set(hass, WORK_MODE, "Summer")
    entered, release = gate_store_saves(entry, monkeypatch)
    first = hass.async_create_task(  # settles A, then waits in A's save
        ar(entry).async_observe(pump.edit, auto_revert_module.monotonic()))
    await asyncio.wait_for(entered.wait(), 5)
    assert not ar(entry).held("workState2")  # B was settled before the save
    pump.write_modes = ["timeout", "timeout", "ok"]
    newer = select_task(hass, WORK_MODE, "Auto")  # a newer B write, retrying
    await wait_for(lambda: len(pump.writes) == 4)
    release.set()  # the first observer resumes after its save
    await asyncio.wait_for(first, 5)
    assert ar(entry).held("workState2")
    pump.guest_change("workState2", 2)
    judged = hass.async_create_task(
        ar(entry).async_observe(pump.edit, auto_revert_module.monotonic()))
    try:
        await asyncio.wait_for(asyncio.gather(newer, judged), 10)
    finally:
        for release_timeout in pump.timeout_releases:
            release_timeout.set()
    assert pump.writes == [("HDWTSetPoint", 45.0), ("workState2", 1.0)] + [
        ("workState2", 6.0)] * 3


async def test_failed_overrides_save_still_loads_the_new_snapshot(setup, monkeypatch):
    hass, entry, pump, _ = await setup()
    store = ar(entry)._store

    async def broken_save(data):
        raise OSError("synthetic: storage directory not writable")

    monkeypatch.setattr(store, "async_save", broken_save)
    pump.guest_change("workState2", 1)  # the owner's new intended value
    await take_snapshot(hass)
    await hass.async_block_till_done()
    assert ar(entry).targets["workState2"] == 1 and not ar(entry)._reloading
    await poll(hass, entry)
    assert pump.writes == []  # the superseded target (2) is never sent
