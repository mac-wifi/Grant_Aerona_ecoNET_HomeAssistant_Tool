# 4-Hour Pre-Deployment Development Plan

## Todos

- [ ] **database-hardening**: Harden database.py: add try/except to all write methods, add 10-year data retention with configurable option in the options flow, add write-source auditing to change_log
- [ ] **change-monitoring**: Enhance change detection across all 3 endpoints: settingsVer early-warning in fast coordinator, sysParams monitoring (remoteMenu, alarms, firmware), VOLATILE_PARAMETERS ignore list, persistent notifications for all external changes
- [ ] **hacs-and-admin-dashboard**: HACS packaging (fix hacs.json, manifest, dead imports, README with InfluxDB prereq) + add diagnostic sensors and Admin tab to dashboard for integration management
- [ ] **write-audit-and-quality**: Write path audit trail: tag change_log entries with source (user/guardian/restore/external), verify write flow end-to-end in code, final code quality pass, tag v0.2.0

**Execute sequentially in order (shared file dependencies between todos 1 and 2).**

---

## Current State

The integration is functionally complete for read operations (sensors, settings display) and has write infrastructure (number, select, bitmask select, backup/restore, guardian) gated behind safe mode. Three files have uncommitted changes adding SQLite database support (`database.py`, `__init__.py`, `const.py`). Ten rounds of manual before/after testing have been completed against the live controller.

## Database Strategy (agreed)

**Two-layer approach -- no future data migration needed:**

- **SQLite** (bundled in integration, zero external dependencies): stores settings audit trail (`change_log`), settings snapshots (`settings_history`, `sys_params_history`), and time-series readings (`readings`) as a local indefinite archive. Already 90% implemented in `custom_components/econet_grant/database.py`.

- **HA's InfluxDB integration** (configured separately at the HA level, not part of our HACS package): captures all sensor entity state changes for Grafana dashboards. All sensors already have `state_class: SensorStateClass.MEASUREMENT` set in `custom_components/econet_grant/const.py` lines 47-143, so HA's recorder and InfluxDB integration will pick them up automatically. The Grafana dashboard configs already exist in `grafana/`.

## Integration UI

Our integration is a **custom_components integration** (not an add-on), so it does not get the add-on management UI (Start/Stop/Watchdog/CPU/tabs). Instead, we build an equivalent experience from two parts:

1. **HA's built-in integration UI** -- config flow, options flow, device page, services, logs (automatic for any config-flow integration)
2. **A dedicated "Admin" tab in the Lovelace dashboard** -- a management console built from diagnostic sensors, service buttons, and information cards that gives a friendly, single-pane-of-glass view for managing the integration without touching YAML or Python files

## What We Are NOT Doing (deferred)

- Grafana dashboard wiring / InfluxDB addon setup (deployment-time task, not code)
- Alexa voice control / guest checkout automations
- Automated test suite
- The missing `compare_exports.py` tool
- `binary_sensor` or `switch` platforms
- Custom sidebar panel (JavaScript/Lit frontend)

---

## Hour 1: Database Hardening (~60 min)

### 1a. Error resilience in `custom_components/econet_grant/database.py`

Every `_record_*` and `_log_change` method currently lets exceptions propagate. Since these are called via `hass.async_create_task()` in `custom_components/econet_grant/__init__.py` lines 100-121, an unhandled SQLite error (disk full, locked DB, permissions) would produce noisy tracebacks and could affect the event loop.

**Fix:** Wrap each method body in try/except, log the error, and return gracefully. The integration must keep running even if the database is temporarily unavailable.

```python
def _record_readings(self, data: dict[str, Any]) -> None:
    try:
        # ... existing logic ...
    except sqlite3.Error:
        _LOGGER.error("Failed to record readings", exc_info=True)
```

Apply the same pattern to `_record_settings`, `_record_sys_params`, and `_log_change`.

### 1b. Data retention management (default 10 years, user-configurable)

The `readings` table writes ~20 rows per 5-minute poll (~5,760 rows/day, ~2.1M rows/year). Add a retention method that purges rows older than a configurable age, called once on startup after `async_setup`:

```python
async def async_purge_old_readings(self, hass: HomeAssistant, days: int = 3650) -> None:
```

Add `DATA_RETENTION_DAYS = 3650` to `custom_components/econet_grant/const.py` as the default (10 years).

**Make it configurable in the options flow.** Expand `custom_components/econet_grant/config_flow.py` `EconetGrantOptionsFlow.async_step_init` to include a retention days field alongside safe_mode:

```python
vol.Required(CONF_SAFE_MODE, default=current_safe_mode): bool,
vol.Optional(CONF_RETENTION_DAYS, default=current_retention): vol.All(
    vol.Coerce(int), vol.Range(min=30, max=7300)
),
```

Add `CONF_RETENTION_DAYS = "retention_days"` to const.py. In `async_setup_entry`, read the option and pass it to the purge method. Update `strings.json` and `translations/en.json` with the new field label and description.

### 1c. Write-source auditing

Currently, `custom_components/econet_grant/change_detector.py` logs external changes to `change_log` with `source="external"`. But writes made by the integration (user via UI, guardian revert, restore) are only tracked as `_self_writes` markers and silently discarded.

**Fix:** When a self-write is confirmed (line 68-69 of change_detector.py), also return it in the changes list but tagged with `source="user"`. In `__init__.py`, pass the source when calling `db.async_log_change`. This gives a complete audit trail:

- `source="external"` -- someone changed a setting via the panel/app
- `source="user"` -- changed via this integration's UI
- `source="guardian"` -- reverted by the heating guardian
- `source="restore"` -- bulk restore from snapshot

The guardian and restore code paths in `custom_components/econet_grant/guardian.py` and `custom_components/econet_grant/__init__.py` (handle_restore) should also log to the database with their respective source tags.

---

## Hour 2: Enhanced Change Monitoring Across All Endpoints (~60 min)

The current change detector only monitors `editParams` (polled every 24 hours). This leaves two gaps:

1. **Detection latency**: A guest changes a setting at the panel. We don't notice for up to 24 hours.
2. **sysParams blind spot**: Changes to alarms, `remoteMenu`, firmware, or network config are never detected.

### 2a. settingsVer early-warning trigger (5-minute detection instead of 24-hour)

`regParams` includes a `settingsVer` counter (currently `20842`) that increments whenever any setting is modified on the controller. This is already in the fast coordinator's data (`custom_components/econet_grant/coordinator.py` line 53).

**Enhancement in `custom_components/econet_grant/__init__.py` `_on_fast_update`:** Track the previous `settingsVer`. When it changes, log a warning and trigger an immediate slow coordinator refresh:

```python
@callback
def _on_fast_update() -> None:
    if fast_coordinator.data is None:
        return
    hass.async_create_task(db.async_record_readings(hass, fast_coordinator.data))
    
    new_ver = fast_coordinator.data.get("settingsVer")
    if new_ver is not None and new_ver != _state["last_settings_ver"]:
        _LOGGER.warning("settingsVer changed: %s -> %s, triggering settings refresh",
                        _state["last_settings_ver"], new_ver)
        _state["last_settings_ver"] = new_ver
        hass.async_create_task(slow_coordinator.async_request_refresh())
```

This means when a guest changes a setting on the panel, the integration detects within **5 minutes** (next fast poll), immediately fetches the new editParams, and fires the change notification. Same approach for `editableParamsVer` and `schedulesVer`.

### 2b. sysParams change detection

Add a new detector (or extend `ChangeDetector`) for sysParams. On each slow poll, compare the current sysParams to the previous snapshot, ignoring volatile fields.

**Volatile sysParams fields to ignore** (change on their own):

```python
VOLATILE_SYS_PARAMS: set[str] = {
    "signal",       # WiFi signal strength, fluctuates constantly
    "quality",      # WiFi quality metric, fluctuates constantly
}
```

**Fields to actively monitor and alert on:**

- `remoteMenu` -- fire an urgent alert if this changes to `true` (per the original brief: red banner on dashboard). Create a persistent notification with high visibility.
- `alarms` -- detect new alarm entries (compare list length or most recent entry). Fire a notification with the alarm code and timestamp.
- `softVer`, `panelVer`, `moduleASoftVer`, `ecosrvSoftVer` -- firmware version changes (likely after maintenance/update).
- `wlan0`, `ssid`, `wifi`, `lan` -- network config changes.
- `controllerID`, `uid` -- should never change; alert as critical if they do.

**Implementation:** Add a `process_sys_params` method to `ChangeDetector` (or a new `SysParamsMonitor` class). Store previous sysParams snapshot, diff on each slow poll, filter out volatile fields, fire events and notifications for changes.

### 2c. Add VOLATILE_PARAMETERS for editParams to `custom_components/econet_grant/const.py`

```python
VOLATILE_PARAMETERS: set[str] = {
    "Circuit1boosttimeleft",
    "Circuit2boosttimeleft",
    "Circuit3boosttimeleft",
    "Circuit4boosttimeleft",
    "Circuit5boosttimeleft",
    "Circuit6boosttimeleft",
    "Circuit7boosttimeleft",
}
```

These are boost heating countdown timers that decrement automatically. All other editParams are genuine settings that should trigger alerts when changed.

### 2d. Update `custom_components/econet_grant/change_detector.py` to skip volatile params

In `process_edit_params`, filter out volatile parameters before processing:

```python
from .const import VOLATILE_PARAMETERS

changes = [c for c in _diff_values(...) if c["name"] not in VOLATILE_PARAMETERS]
```

### 2e. Persistent notifications for ALL external changes

Currently the change detector only fires HA events (`econet_grant_setting_changed`). Add persistent notification creation so changes are visible without automations:

```python
if external_changes:
    lines = []
    for change in external_changes:
        lines.append(f"- **{change['name']}**: {change['old_value']} -> {change['new_value']}")
    message = "Settings changed externally:\n\n" + "\n".join(lines)
    self._hass.components.persistent_notification.async_create(
        message=message,
        title="EcoNet Grant - Settings Changed",
        notification_id=f"{DOMAIN}_external_changes",
    )
```

This covers ALL editParams changes -- both mapped parameters (like `Circuit1ComfortTemp`) and unmapped ones (like `Circuit2ComfortTemp`, `BuforsetPoint`, etc.). No before/after snapshot mapping is required; the parameter name from the API is used directly.

### 2f. Verify existing events still fire

Keep the existing `EVENT_SETTING_CHANGED` and `EVENT_URGENT_CHANGE` event firing alongside the new notifications. This preserves the hook for HA automations (SMS/WhatsApp alerts via `URGENT_PARAMETERS`).

---

## Hour 3: HACS Packaging + Admin Dashboard (~60 min)

### HACS Packaging (first ~30 min)

### 3a. Fix `hacs.json`

Current file lists platforms that don't exist (`binary_sensor`, `switch`). Fix to match actual platforms:

```json
{
  "name": "EcoNet Grant Aerona",
  "homeassistant": "2024.1.0",
  "render_readme": true,
  "iot_class": "local_polling",
  "domains": ["sensor", "number", "select", "button"]
}
```

### 3b. Verify `custom_components/econet_grant/manifest.json`

Current manifest looks correct. Verify:
- `requirements: ["aiohttp>=3.8.0"]` -- aiohttp ships with HA, but listing it is fine for HACS validation
- `version: "0.1.0"` -- present and correct
- `config_flow: true` -- present
- No additional pip dependencies needed (SQLite is stdlib)

### 3c. Remove dead import in `custom_components/econet_grant/coordinator.py`

Line 15: `ApiError` is imported but never used. Change to:

```python
from .api import AuthError, EconetApi
```

### 3d. Verify HACS repo structure

HACS requires this structure (already mostly correct):

```
custom_components/
  econet_grant/
    __init__.py
    manifest.json
    config_flow.py
    strings.json
    translations/
      en.json
    (all other .py files)
    services.yaml
hacs.json
README.md
```

Verify `translations/en.json` exists and matches `strings.json`. Ensure no stray files break HACS validation.

### 3e. Update `README.md` for HACS users

Add installation instructions with InfluxDB as a documented prerequisite:

```markdown
## Installation

### Prerequisites (recommended)

If you want Grafana dashboards with historical temperature and performance graphs:

1. Install the **InfluxDB** addon from the Home Assistant Add-on Store
2. Configure the **InfluxDB integration** in HA (Settings > Devices & Services > Add Integration > InfluxDB)
3. This captures all sensor data from the moment the EcoNet integration starts -- no data migration needed later

If you skip this step, the integration still works fully. Sensor data is stored in HA's built-in
recorder and in the integration's own SQLite database. You can add InfluxDB later, but you will
only have data from that point forward.

### Install via HACS (recommended)

1. Open HACS in your Home Assistant instance
2. Click the three dots menu > Custom repositories
3. Add this repository URL with category "Integration"
4. Click "Download" on the EcoNet Grant Aerona card
5. Restart Home Assistant
6. Go to Settings > Devices & Services > Add Integration > "EcoNet Grant Aerona"
7. Enter your ecoNET device's local IP address, username, and password

### Manual Installation

1. Copy the `custom_components/econet_grant/` folder into your HA `custom_components/` directory
2. Restart Home Assistant
3. Add the integration via Settings > Devices & Services
```

### 3f. Remove stale references

- README references `tools/compare_exports.py` which doesn't exist. Remove the reference.
- README mentions `dashboards/econet.yaml` as the dashboard, but the project rule says the primary dashboard is `dashboards/econet_grant_dashboard.yaml`. Align the reference.

### 3g. Update `strings.json` and `translations/en.json`

Add entries for the new `retention_days` option in the options flow. Ensure all existing strings are correct.

---

### Admin Dashboard Tab (remaining ~30 min)

The existing dashboard (`dashboards/econet_grant_dashboard.yaml`) has 4 tabs: Temperature, Performance, Settings(?), Guest. We add a 5th **Admin** tab that serves as a management console, giving a user-friendly experience similar to the add-on UI.

### 3h. Add diagnostic sensors

Create a new `diagnostics.py` platform file (or add to `sensor.py`) that exposes integration health as HA entities. These give the Admin tab live data to display:

- **`sensor.grant_aerona_heat_pump_last_reading`** -- timestamp of the last successful fast poll (`entity_category: diagnostic`)
- **`sensor.grant_aerona_heat_pump_last_settings_check`** -- timestamp of the last successful slow poll
- **`sensor.grant_aerona_heat_pump_settings_version`** -- current `settingsVer` value (tracks when settings change)
- **`sensor.grant_aerona_heat_pump_database_size`** -- SQLite file size in MB (updated on each write)
- **`sensor.grant_aerona_heat_pump_guardian_status`** -- "Active (21.0C)" or "Disabled"
- **`sensor.grant_aerona_heat_pump_safe_mode`** -- "On" or "Off" (mirrors the option for dashboard visibility)
- **`sensor.grant_aerona_heat_pump_remote_menu`** -- "false" (with conditional card styling to go red if "true")
- **`sensor.grant_aerona_heat_pump_recent_changes`** -- count of changes detected in the last 24 hours

All diagnostic sensors use `entity_category: EntityCategory.DIAGNOSTIC` so they don't clutter the main entity lists but are available for dashboards.

Add `Platform.SENSOR` (already present) to handle both the existing sensors and the new diagnostic ones. The diagnostic sensors read from the coordinators' data and the hass.data store.

### 3i. Build the Admin tab in `dashboards/econet_grant_dashboard.yaml`

Add a new view to the dashboard YAML:

```yaml
  - title: Admin
    path: admin
    icon: mdi:cog
    cards:
      # --- Status Overview (like add-on Info tab) ---
      - type: entities
        title: Integration Status
        show_header_toggle: false
        entities:
          - entity: sensor.grant_aerona_heat_pump_safe_mode
            name: Safe Mode
            icon: mdi:shield-lock
          - entity: sensor.grant_aerona_heat_pump_guardian_status
            name: Heating Guardian
            icon: mdi:shield-home
          - entity: sensor.grant_aerona_heat_pump_last_reading
            name: Last Sensor Poll
            icon: mdi:clock-check
          - entity: sensor.grant_aerona_heat_pump_last_settings_check
            name: Last Settings Check
            icon: mdi:clock-alert
          - entity: sensor.grant_aerona_heat_pump_settings_version
            name: Settings Version
            icon: mdi:counter
          - entity: sensor.grant_aerona_heat_pump_database_size
            name: Database Size
            icon: mdi:database
          - entity: sensor.grant_aerona_heat_pump_recent_changes
            name: Changes (24h)
            icon: mdi:delta

      # --- Remote Menu Warning Banner ---
      - type: conditional
        conditions:
          - entity: sensor.grant_aerona_heat_pump_remote_menu
            state: "true"
        card:
          type: markdown
          content: >
            ## WARNING: Remote Menu is ENABLED

            The ecoNET controller has `remoteMenu: true`. This was previously
            `false`. RM API endpoints may now be available. Investigate immediately
            -- this could indicate a firmware update or configuration change.
          style: |
            ha-card { background-color: #d32f2f; color: white; }

      # --- Configuration Links ---
      - type: markdown
        title: Configuration
        content: >
          **To change integration settings** (safe mode, data retention):

          Settings > Devices & Services > EcoNet Grant Aerona > Configure


          **To view detailed logs:**

          Settings > System > Logs > filter by `econet_grant`

      # --- Quick Actions (like add-on Start/Stop/Restart) ---
      - type: horizontal-stack
        cards:
          - type: button
            name: Backup Settings
            icon: mdi:content-save-all
            tap_action:
              action: call-service
              service: econet_grant.backup_settings
              service_data:
                snapshot_name: "Default"
            confirmation:
              text: "Save current settings as 'Default' snapshot?"

          - type: button
            name: Restore Default
            icon: mdi:backup-restore
            tap_action:
              action: call-service
              service: econet_grant.restore_settings
              service_data:
                snapshot_name: "Default"
            confirmation:
              text: "Restore all settings from the 'Default' snapshot?"

      - type: horizontal-stack
        cards:
          - type: button
            name: Enable Guardian (21C)
            icon: mdi:shield-check
            tap_action:
              action: call-service
              service: econet_grant.set_guardian_temp
              service_data:
                temperature: 21
            confirmation:
              text: "Enable Heating Guardian at 21C?"

          - type: button
            name: Disable Guardian
            icon: mdi:shield-off
            tap_action:
              action: call-service
              service: econet_grant.set_guardian_temp
              service_data: {}
            confirmation:
              text: "Disable Heating Guardian?"

      # --- About ---
      - type: markdown
        title: About
        content: >
          **EcoNet Grant Aerona** v0.2.0

          Monitors and controls a Grant Aerona heat pump via the ecoNET local API.

          [Documentation](https://github.com/mac-wifi/Grant_Aerona_ecoNET_HomeAssistant_Tool)
```

This gives the user a single "Admin" tab with:
- **Status overview** -- equivalent to the add-on Info section (live health data, poll times, DB size)
- **Remote Menu warning** -- the red banner, shown conditionally only when `remoteMenu` becomes true
- **Configuration links** -- directs users to the right HA settings pages
- **Quick actions** -- backup, restore, guardian enable/disable (equivalent to Start/Stop buttons)
- **About section** -- version and documentation link (equivalent to the add-on Documentation tab)

---

## Hour 4: Write Path Quality and Final Polish (~60 min)

### 4a. Audit the write flow end-to-end in code

Walk through each write path and verify correctness:

1. **Number entity** (`custom_components/econet_grant/number.py` `async_set_native_value`): safe_mode check -> mark_self_write -> set_param_by_index -> optimistic update or clear_self_write. Looks correct.

2. **Select entity** (`custom_components/econet_grant/select.py`): same pattern for both regular and bitmask selects. Verify the bitmask read-modify-write is correct (reads current int, toggles bit, writes full int back).

3. **Guardian** (`custom_components/econet_grant/guardian.py`): No safe_mode check (intentional -- guardian should always enforce). Add `db.async_log_change` call with `source="guardian"` when a revert happens.

4. **Restore** (`custom_components/econet_grant/__init__.py` `handle_restore`): Pre-marks all self_writes, then calls `async_restore_settings`. Add DB logging with `source="restore"` for each restored parameter.

### 4b. Ensure write operations log to the database

Currently, the `change_log` table only captures changes detected by the change_detector on the next slow poll. For writes, we should also log immediately when the write succeeds. Add a helper in `__init__.py` or `database.py`:

```python
async def async_log_write(self, hass, param_name, param_index, old_value, new_value, source="user"):
```

Call this from `number.py` and `select.py` on successful writes (after `set_param_by_index` returns `True`). This gives immediate audit records rather than waiting up to 24 hours for the slow poll to detect the change.

### 4c. Final code quality pass

- Verify all entity platforms handle `None`/missing data gracefully (coordinator returns None, editParams missing a param index, etc.)
- Check that the `GrantWorkState` select (listed in README as a sensor but defined as a select in const.py) is correctly categorised
- Ensure `services.yaml` descriptions match the actual service behaviour
- Verify `strings.json` and `translations/en.json` are in sync

### 4d. Commit, tag, and push

- Commit all changes with a descriptive message
- Tag as `v0.2.0` (reflects database, change monitoring, admin dashboard, and HACS readiness)
- Push to GitHub (the HACS custom repository URL will point here)

---

## Success Criteria

After 4 hours of development, the code should be:

1. **Database-ready**: SQLite hardened with error handling, 10-year default retention (user-configurable in integration options), and a complete audit trail covering all write sources
2. **Monitoring all endpoints**: `settingsVer` watched every 5 minutes for early change detection; all editParams changes notified (mapped or unmapped, minus volatile timers); sysParams monitored for `remoteMenu`, alarms, firmware, and network changes
3. **HACS-installable**: Clean repo structure, correct `hacs.json`/`manifest.json`, install instructions in README (with InfluxDB prerequisite documented)
4. **Admin dashboard**: An "Admin" tab with integration status, remote menu warning banner, quick-action buttons (backup/restore/guardian), configuration links, and version/documentation info
5. **Write-audited**: Every write (user, guardian, restore) immediately logged to the database with its source
6. **User-configurable**: Options flow includes safe_mode toggle and data retention days setting
7. **Tagged `v0.2.0`** and pushed to GitHub, ready for HACS custom repository addition

**Deployment itself** (copying to HA, installing InfluxDB addon, adding the integration, testing a live write) is a separate step after this work.
