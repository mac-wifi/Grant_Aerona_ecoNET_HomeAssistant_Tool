"""Setup orchestration tests, not a running HA instance or platform integration test."""
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady

import custom_components.econet_grant as integration
from custom_components.econet_grant.api import AuthError
from custom_components.econet_grant.const import DOMAIN, SERVICE_API


@pytest.fixture
def setup_boundaries(monkeypatch, api, edit_params):
    factory = AsyncMock(return_value=api)
    monkeypatch.setattr(integration, "make_api", factory)
    monkeypatch.setattr(integration, "async_get_clientsession", Mock())
    fast = SimpleNamespace(
        data={"curr": {"temp": 20}, "settingsVer": 1},
        async_config_entry_first_refresh=AsyncMock(), async_add_listener=Mock(),
    )
    slow = SimpleNamespace(
        data={"editParams": edit_params, "sysParams": {"remoteMenu": False}},
        async_config_entry_first_refresh=AsyncMock(), async_add_listener=Mock(),
    )
    monkeypatch.setattr(integration, "EconetFastCoordinator", Mock(return_value=fast))
    monkeypatch.setattr(integration, "EconetSlowCoordinator", Mock(return_value=slow))
    db = Mock(spec=integration.EconetDatabase)
    monkeypatch.setattr(integration, "EconetDatabase", Mock(return_value=db))
    return factory, fast, slow, db


async def test_setup_and_unload(hass, entry, api, setup_boundaries):
    factory, fast, slow, db = setup_boundaries
    assert await integration.async_setup_entry(hass, entry) is True
    factory.assert_awaited_once()
    fast.async_config_entry_first_refresh.assert_awaited_once()
    slow.async_config_entry_first_refresh.assert_awaited_once()
    db.async_setup.assert_awaited_once_with(hass)
    db.async_record_settings.assert_awaited_once()
    assert hass.data[DOMAIN][entry.entry_id][SERVICE_API] is api
    assert {call.args[1] for call in hass.services.async_register.call_args_list} == {
        "backup_settings", "restore_settings",
    }
    hass.config_entries.async_forward_entry_setups.assert_awaited_once_with(
        entry, integration.PLATFORMS,
    )
    assert await integration.async_unload_entry(hass, entry) is True
    assert entry.entry_id not in hass.data[DOMAIN]
    hass.config_entries.async_unload_platforms.assert_awaited_once_with(entry, integration.PLATFORMS)


async def test_failed_unload_preserves_entry(hass, entry):
    hass.data[DOMAIN] = {entry.entry_id: {"sentinel": True}}
    hass.config_entries.async_unload_platforms.return_value = False
    assert await integration.async_unload_entry(hass, entry) is False
    assert hass.data[DOMAIN][entry.entry_id] == {"sentinel": True}


@pytest.mark.parametrize("error, expected", [
    (AuthError("synthetic"), ConfigEntryAuthFailed),
    (OSError("synthetic"), ConfigEntryNotReady),
])
async def test_setup_maps_connection_errors(hass, entry, setup_boundaries, error, expected):
    factory, fast, slow, db = setup_boundaries
    factory.side_effect = error
    with pytest.raises(expected):
        await integration.async_setup_entry(hass, entry)
    hass.config_entries.async_forward_entry_setups.assert_not_awaited()
    db.async_setup.assert_not_awaited()
    assert entry.entry_id not in hass.data[DOMAIN]


async def test_options_update_requests_reload_and_registers_cleanup(hass, entry, setup_boundaries):
    _, fast, slow, _ = setup_boundaries
    await integration.async_setup_entry(hass, entry)
    entry.add_update_listener.assert_called_once()
    update = entry.add_update_listener.call_args.args[0]
    entry.async_on_unload.assert_any_call(entry.add_update_listener.return_value)
    entry.async_on_unload.assert_any_call(fast.async_add_listener.return_value)
    entry.async_on_unload.assert_any_call(slow.async_add_listener.return_value)
    entry.options["slow_poll_interval"] = 60
    await update(hass, entry)
    hass.config_entries.async_reload.assert_awaited_once_with(entry.entry_id)

    # HA invokes registered unload callbacks after successful platform unload.
    assert await integration.async_unload_entry(hass, entry)
    for call in entry.async_on_unload.call_args_list:
        call.args[0]()
    fast.async_add_listener.return_value.assert_called_once_with()
    slow.async_add_listener.return_value.assert_called_once_with()
    entry.add_update_listener.return_value.assert_called_once_with()

    # A fresh setup constructs a real slow coordinator from the updated options.
    from custom_components.econet_grant.coordinator import EconetSlowCoordinator
    from datetime import timedelta

    assert EconetSlowCoordinator(hass, setup_boundaries[0].return_value, entry).update_interval == timedelta(hours=1)


async def test_settings_version_still_requests_early_slow_refresh(hass, entry, setup_boundaries):
    import asyncio

    _, fast, slow, _ = setup_boundaries
    entry.options["slow_poll_interval"] = 1440
    slow.async_request_refresh = AsyncMock()
    tasks = []

    def create_task(coro):
        task = asyncio.create_task(coro)
        tasks.append(task)
        return task

    hass.async_create_task = create_task
    await integration.async_setup_entry(hass, entry)
    listener = fast.async_add_listener.call_args.args[0]
    listener()
    await asyncio.gather(*tasks)
    slow.async_request_refresh.assert_not_awaited()
    fast.data["settingsVer"] = 2
    listener()
    await asyncio.gather(*tasks)
    slow.async_request_refresh.assert_awaited_once()
    listener()
    await asyncio.gather(*tasks)
    slow.async_request_refresh.assert_awaited_once()
