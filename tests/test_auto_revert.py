"""Auto-revert, against a real Home Assistant and the loopback emulator.

Writes are asserted as real HTTP requests (``pump.writes``). The three-setting
emulator fixture stays unchanged; each test adds the site's settings in-test.
Test names follow the plan's specification.
"""
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
    assert not any(ar(entry).held(n) for n in ("HDWTSetPoint", "workState2", "HDWSETTINGS"))


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
    assert not ar(entry).held("HDWSETTINGS")
    assert ar(entry).targets["HDWSETTINGS"] == 21 & (16 | 1 | 4096)  # last completed wins


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
