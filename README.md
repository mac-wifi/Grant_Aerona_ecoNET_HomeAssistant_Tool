# EcoNet Grant Aerona - Home Assistant Integration

> [!CAUTION]
> **Work in progress -- use at your own risk.** This is an active development project built with AI-assisted coding (Cursor IDE). It is provided as-is with no warranty. This integration writes to a live heat pump controller -- incorrect use could affect your heating system.

A custom Home Assistant integration for monitoring and controlling a **Grant Aerona** heat pump via the **ecoNET** local REST API (ecoMAX360i controller).

This project was created to remotely manage a holiday home heat pump, allowing the owner to monitor what guests are doing with the heating and revert unwanted changes.

## Current Status

**Version:** 0.4.2 (active development)

Version 0.4.1 is deployed and running in production on a Home Assistant OS instance, alongside a separate test HA instance used for development. Version 0.4.2 updates documentation and consolidates the dashboard packaging; it does not change integration runtime logic. Parameter mappings were confirmed through manual before/after testing against the live ecoNET controller using the vendor's iOS app. An automated test suite has not yet been added.

## What Works

The integration currently creates **21 sensors**, **24 number entities**, **21 select entities**, and **1 button entity**.

### Operational Sensors (13, polled every 5 minutes from `regParams`)

| Entity | Source | Description |
|---|---|---|
| Outdoor Temperature | `curr.GrantOutdoorTemp` | Outdoor air temperature from the heat pump |
| Flow Temperature | `curr.GrantOutgoingTemp` | Water flow temperature |
| Return Temperature | `curr.GrantReturnTemp` | Water return temperature |
| HW Temperature | `curr.TempCWU` | Hot-water tank temperature |
| CH Thermostat | `curr.Circuit1thermostat` | Central-heating room thermostat reading |
| Weather Temperature | `curr.TempWthr` | Weather-compensation sensor |
| Buffer Temp (Lower) | `curr.TempBuforDown` | Lower buffer-tank temperature |
| Heat Exchanger Temp | `curr.TempClutch` | Heat-exchanger/clutch temperature |
| Heat Source Preset Temp | `curr.HeatSourceCalcPresetTemp` | Calculated target flow temperature |
| Compressor Frequency | `curr.GrantCompressorFreq` | Compressor operating frequency (Hz) |
| Pump Speed | `curr.GrantPumpSpeed` | Main circulation-pump speed (rpm) |
| Fan Speed | `tilesParams[3]` | Outdoor-unit fan speed (rpm) |
| System Demand | `schemaParams.reakcja_termostat1` | Heating / No Demand status |

Eight additional diagnostic sensors report the last sensor poll, last settings check, settings version, SQLite database size, safe-mode state, Remote Menu state, changes detected in the last 24 hours, and the last Default snapshot.

### Writable Number Entities (24, from `editParams`)

| Entity | Param Index | Range |
|---|---:|---:|
| CH Day Temp | 238 | 10-35 °C |
| CH Night Temp | 239 | 10-35 °C |
| CH Base Temp | 261 | 25-60 °C |
| CH Hysteresis | 240 | 0-5 °C |
| CH Curve | 273 | 0-4 |
| CH Curve Shift | 275 | -20 to 20 °C |
| CH Boost Time | 1521 | 0-180 min |
| HW Set Point | 103 | 20-55 °C |
| HW Hysteresis | 104 | 0-10 °C |
| HW Extend Work | 113 | 0-30 min |
| HW Correction Temp | 481 | 0-20 °C |
| Panel Temp Correction | 10413 | -5 to 5 °C |
| Summer Threshold | 702 | 17-30 °C |
| Winter Threshold | 703 | 0-19 °C |
| Heating Temp Correction | 1402 | 0-20 °C |
| Cooling Setpoint Adj | 1054 | 1-10 °C |
| HW Pump Start Temp | 433 | 20-60 °C |
| Crit Temp Ignore | 1533 | 0-10 min |
| HW Recirc Run Time | 434 | 1-120 s |
| HW Recirc Pause | 435 | 1-100 min |
| Outside Temp Start Heater | 144 | -20 to 20 °C |
| Outside Temp Force Heater | 145 | -20 to 20 °C |
| HW Heater Delay | 146 | 0-240 min |
| Backup Heater Delay | 147 | 0-240 min |

### Writable Select Entities (7, from `editParams`)

| Entity | Param Index | Options |
|---|---:|---|
| Work Mode | 162 | Summer, Winter, Auto |
| CH Operation Mode | 236 | Off, Day, Night, Schedule |
| HW Work Mode | 119 | Off, On, Schedule |
| HW Boost | 115 | Off, On |
| Heat Pump Mode | 1133 | Off, On, Schedule |
| Hydraulic Scheme | 19 | Direct, Buffer, Low Loss Header |
| CH Circuit Type | 269 | Radiators, Fan Coil |

### Bitmask Select Entities (14, from `editParams`)

These read and modify one bit within a larger settings value. The integration writes the complete resulting bitmask by API parameter name.

| Entity | Settings Param | Bit Mask | Options |
|---|---|---:|---|
| HW Specify Priority | 101 (`HDWSETTINGS`) | 16 | Yes / No |
| Ext Temp Sensor | 69 (`TempSettings`) | 1 | Yes / No |
| Temp Sensor Source | 69 (`TempSettings`) | 2 | Heat Pump / ecoMulti |
| Cooling Support | 485 (`HeatingCooling`) | 1 | Yes / No |
| Heat Pump Lock | 462 (`HeatSourceAllowWorkSett`) | 1 | Yes / No |
| HW Support | 101 (`HDWSETTINGS`) | 1 | Yes / No |
| Off Circuits on HW | 101 (`HDWSETTINGS`) | 4096 | Yes / No |
| HW Recirc Support | 431 (`CirculationSettings`) | 1 | Yes / No |
| HW Start From Temp | 431 (`CirculationSettings`) | 2 | Yes / No |
| CH Pump Blockade | 231 (`Circuit1Settings`) | 1024 | Yes / No |
| Backup Htr in Defrost | 143 (`heatersSett`) | 16 | Yes / No |
| CH Regulation Method | 231 (`Circuit1Settings`) | 2048 | Weather / Fixed |
| Backup Heater | 143 (`heatersSett`) | 1 | Yes / No |
| HW Heater | 143 (`heatersSett`) | 2 | Yes / No |

### Other Features

- **Safe Mode**: All write operations are blocked by default and previewed in persistent notifications. Disable Safe Mode in integration options only when ready to write to the controller.
- **Change Detection**: Monitors both `editParams` and `sysParams`, filters volatile values, and uses version counters from `regParams` to trigger an immediate settings refresh. It fires `econet_grant_setting_changed`, `econet_grant_urgent_change`, and `econet_grant_sys_param_changed` events. Persistent and optional push notifications are enabled by default.
- **History and Audit**: A bundled SQLite database records live readings, settings history, system snapshots, and a source-tagged change log. Retention for the first three defaults to 10 years, is configurable from 30 days to 20 years, and is enforced when the integration is set up or reloaded. Change-log audit entries and named JSON backup snapshots are currently retained indefinitely.
- **Backup & Restore**: Services create named JSON snapshots and restore changed editable parameters. Safe Mode previews a restore without writing. Home Assistant also exposes a Restore Default Settings button; dashboard cards call both services.
- **Dashboard YAML**: The Lovelace dashboard uses Mushroom Cards and Mini Graph Card. Its single canonical copy is `custom_components/econet_grant/extras/econet_grant_dashboard.yaml`, where HACS can package it and manual installers can also access it.
- **Optional Grafana support**: Example InfluxDB and Grafana configuration is included for users who want Grafana dashboards. It is not required for the integration, change detection, SQLite audit history, or Home Assistant history.

## Architecture

```
Home Assistant Server
  └── custom_components/econet_grant/
        ├── Fast coordinator (5 min)  ──GET──>  http://<econet_ip>/econet/regParams
        │     └── Operational sensors, version counters, SQLite readings
        ├── Slow coordinator (default 5 min, configurable) ──GET──> http://<econet_ip>/econet/editParams + sysParams
        │     └── Settings data for number/select entities, change detection, SQLite history/audit
        └── Write operations          ──GET──>  http://<econet_ip>/econet/newParam?newParamName=...&newParamValue=...
              └── Sets parameters by name; `rm*` endpoints are not supported by this controller
```

The ecoNET device exposes a local REST API with Basic Authentication. A bare host/IP defaults to local HTTP; an explicitly supplied `https://` URL is also accepted. Requests are serialised with a minimum one-second gap to avoid overwhelming the controller.

The SQLite database and optional InfluxDB database serve different consumers. SQLite is the integration's internal raw-history and audit store at `<HA config>/econet_grant.db`; named backup snapshots are stored separately under `<HA config>/econet_grant_snapshots/`. Currently only database size and recent-change count are exposed in Home Assistant. InfluxDB receives Home Assistant entity states and exists to support Grafana and flexible time-series queries. If Grafana is not required, do not install InfluxDB: Home Assistant's recorder plus the integration's SQLite database are sufficient.

---

## Installation Guide

Step-by-step instructions for installing the integration on a clean Home Assistant OS (HAOS) instance. Tested against HAOS on a virtual machine; the same steps apply to any HAOS installation (Raspberry Pi, NUC, VM, etc.).

**Estimated time:** 25--35 minutes end-to-end.

> **UI terminology:** From HA Core 2026.x, "Add-ons" has been renamed to "Apps" in the Settings menu. This guide uses the current path **Settings > Apps > Install app**. If you're on an older HA version (pre-2026), the equivalent path is **Settings > Add-ons > Add-on Store**.

### Contents

1. [Before You Start](#1-before-you-start)
2. [Install HACS](#2-install-hacs)
3. [Optional: Install & Configure InfluxDB](#3-optional-install--configure-influxdb)
4. [Install the Integration via HACS](#4-install-the-integration-via-hacs)
5. [Alternative: Manual Installation](#4-alt-manual-installation)
6. [Configure the Integration](#5-configure-the-integration)
7. [Understand Safe Mode](#6-understand-safe-mode)
8. [Dashboard Setup](#7-dashboard-setup)
9. [Take a Baseline Backup](#8-take-a-baseline-backup)
10. [Create Helpers](#9-create-helpers)
11. [Install Automations](#10-install-automations)
12. [Optional: Grafana](#11-optional-grafana)
13. [Verification Checklist](#12-verification-checklist)
14. [Troubleshooting](#13-troubleshooting)

---

### 1. Before You Start

#### What you need

| Item | Details |
|------|---------|
| **Home Assistant OS** | Version 2024.1.0 or later (tested on Core 2026.2.3) |
| **ecoNET device** | ecoNET300 module on the same LAN as your HA instance |
| **ecoNET local credentials** | The username and password for the device's local REST API (not your econet24.com cloud account) |
| **ecoNET IP address** | The local IP of the ecoNET300 module (check your router's DHCP table or the vendor app) |

#### Network requirements

The integration communicates over HTTP on the local network. Make sure your HA instance can reach the ecoNET device's IP on port 80:

```
HA  ──HTTP:80──>  ecoNET300  ──>  ecoMAX360i controller  ──>  Grant Aerona heat pump
```

If your HA VM is on a different VLAN or subnet, ensure there is a route and no firewall blocking port 80 between them.

> **Tip:** Test connectivity from HA before installing. Go to **Settings > Apps > Install app** and install **Terminal & SSH** (if not already installed), then open a terminal and run:
> ```bash
> curl -u username:password http://<econet_ip>/econet/regParams
> ```
> You should get a JSON response with temperature readings. If this fails, fix the network before proceeding.

---

### 2. Install HACS

If HACS is already installed, skip to [Step 3](#3-optional-install--configure-influxdb).

1. In Home Assistant, go to **Settings > Apps > Install app**
2. Search for and install the **Terminal & SSH** app (if not already installed) and start it
3. Open the terminal and run:
   ```bash
   wget -O - https://get.hacs.xyz | bash -
   ```
4. Restart Home Assistant: **Settings > System > Restart**
5. After restart, go to **Settings > Devices & Services > Add Integration**
6. Search for **HACS** and complete the setup (you'll need a GitHub account to authorise)
7. HACS will appear in the sidebar once configured

> **Reference:** [HACS installation docs](https://hacs.xyz/docs/use/)

---

### 3. Optional: Install & Configure InfluxDB

InfluxDB is needed only for the supplied Grafana dashboards or other InfluxQL time-series queries. It is **not** required for the integration, notifications, backup/restore, Home Assistant history, or the integration's SQLite history and audit log. If you do not intend to use Grafana, skip directly to [Step 4](#4-install-the-integration-via-hacs).

Installing InfluxDB before the integration captures entity-state history from the first poll. Installing it later is also supported, but InfluxDB cannot reconstruct entity states from before it was configured.

#### 3a. Install the InfluxDB app

1. Go to **Settings > Apps > Install app**
2. Search for **InfluxDB** and install it
3. Start the app and open the web UI (Chronograf)

These examples target **InfluxDB 1.x** with Chronograf as the web interface. Check the installed app's version; the examples are not Flux/InfluxDB 2.x configuration. A default `_internal` database and pre-created users (`chronograf`, `kapacitor`) are normal for this setup.

#### 3b. Create the database and user

You need to create a dedicated database and a user for Home Assistant. In the Chronograf web UI:

1. Click **InfluxDB Admin** in the left sidebar
2. On the **Databases** tab, click **Create Database**
3. Enter `econet_grant` as the name and press Enter
4. Choose a retention policy appropriate to your disk space and history needs. The example queries use the database's default retention policy.
5. Switch to the **Users** tab and click **Create User**
6. Enter username `homeassistant` and a password of your choice, then click **Create**
7. Grant **WRITE** and **READ** on `econet_grant` only, not global admin. Enable InfluxDB authentication if not already enabled; database grants do not protect a server with authentication disabled. Create a separate Grafana user with **READ only** on `econet_grant` (Step 11).

You're now finished with the InfluxDB / Chronograf UI. The remaining steps are done in the Home Assistant config files.

#### 3c. Add the InfluxDB integration via the UI

Use the current Home Assistant InfluxDB UI for connection settings; keep only filtering and schema options in YAML as below. See the [Home Assistant InfluxDB documentation](https://www.home-assistant.io/integrations/influxdb/) for version-specific setup.

1. Go to **Settings > Devices & Services**
2. Click **Add Integration** (bottom right)
3. Search for **InfluxDB** and select it
4. Choose **InfluxDB 1.x** (this matches the HA InfluxDB app)
5. Enter the connection details:

| Field | Value |
|-------|-------|
| **Host** | `<INFLUXDB_HOST>` reachable from HA; use the hostname shown by your installed app |
| **Port** | `<INFLUXDB_PORT>` (normally `8086` for InfluxDB 1.x) |
| **Database** | `econet_grant` |
| **Username** | `homeassistant` |
| **Password** | the password you chose in Step 3b |

6. Click **Submit**

#### 3d. Add entity filtering to configuration.yaml

The UI handles the connection, but entity filtering is still configured in YAML. Add the following to `/homeassistant/configuration.yaml`:

```yaml
influxdb:
  max_retries: 3
  measurement_attr: unit_of_measurement
  default_measurement: state
  include:
    entity_globs:
      - sensor.grant_aerona_heat_pump_*
      - number.grant_aerona_heat_pump_*
      - select.grant_aerona_heat_pump_*
```

Do not duplicate UI-managed connection credentials in this snippet. Merge into any existing `influxdb:` section, rather than creating a second one. Adjust the globs if your device or entity IDs were renamed; they filter full HA IDs. Do not add a measurement override unless you also change the Grafana queries.

Before restarting, verify your YAML is valid: go to **Developer Tools > YAML** (tab) and click **Check Configuration**. If it reports "Configuration will not prevent Home Assistant from starting", you're good to proceed. If it shows errors, fix them in `configuration.yaml` before continuing.

#### 3e. Restart Home Assistant

**Settings > System > Restart**

With a working connection and matching filters, subsequent HA entity-state events are exported. Confirm data arrives using Step 11; unchanged states need not produce a point on every poll. This does not query or backfill the integration's SQLite database.

---

### 4. Install the Integration via HACS

1. Open **HACS** from the sidebar (this takes you straight to the Home Assistant Community Store page)
2. Click the **three-dot menu** (top right) > **Custom repositories**
3. In the dialog:
   - **Repository:** `https://github.com/mac-wifi/Grant_Aerona_ecoNET_HomeAssistant_Tool`
   - **Category:** Integration
   - Click **Add**
4. Close the dialog. The **EcoNet Grant Aerona** card should now appear
5. Click the card > **Download** > **Download** (HACS will show a commit hash rather than a version number -- this is normal for custom repositories)
6. **Restart Home Assistant:** Settings > System > Restart

After the restart, the integration files will be in place at `custom_components/econet_grant/`.

---

### 4-ALT. Manual Installation

Use this method if you prefer not to use HACS, or for quick testing.

1. Download or clone the repository:
   ```bash
   git clone https://github.com/mac-wifi/Grant_Aerona_ecoNET_HomeAssistant_Tool.git
   ```
2. Copy the `custom_components/econet_grant/` folder into your HA config directory:
   ```
   /homeassistant/custom_components/econet_grant/
   ```
   You can use the **Samba** or **SSH** apps to transfer files, or the **File Editor** app to create the directory structure.
3. **Restart Home Assistant:** Settings > System > Restart

---

### 5. Configure the Integration

1. Go to **Settings > Devices & Services**
2. Click **Add Integration** (bottom right)
3. Search for **EcoNet Grant Aerona**
4. Enter the connection details:
   - **Host:** the ecoNET device's local IP address (e.g. `192.168.1.50`)
   - **Username:** local device username
   - **Password:** local device password
5. Click **Submit**

If the connection succeeds, you'll see a new device called **Grant Aerona Heat Pump** with all the sensor, number, select, and button entities.

> **Note:** These are the local device credentials, not your econet24.com cloud account.

If you set up InfluxDB in Step 3, data will start flowing into the `econet_grant` database within seconds of the first sensor poll.

#### Settings polling interval

Under **Settings > Devices & Services > EcoNet Grant Aerona > Configure**, set
**Settings polling interval (minutes)** to a whole number from **5 to 1440**.
The default remains **5 minutes**, including for existing installations with no
saved interval. Use **60** for hourly polling or **1440** for daily polling of
`editParams` and `sysParams`. Shorter intervals catch changes that do not increment
version counters sooner, but increase device load; polling faster than five
minutes is not supported.

`regParams` still polls every five minutes. Changes in `settingsVer`,
`editableParamsVer`, or `schedulesVer` still request an early settings refresh,
regardless of the chosen interval. Saving options reloads the integration to apply
the interval without restarting Home Assistant; this also resets the in-memory
change-detection baseline. It does not write settings to the heat pump.

#### Optional: individual manual Revert notifications

In integration **Configure** options, leave **Revert notification service** blank
to keep the existing notify-only behaviour. To opt in, enable **Push notifications
for setting changes** and enter one Companion App service name such as
`mobile_app_your_phone`, without the `notify.` prefix. Find the actual service
under **Developer Tools > Actions**. Saving options reloads the integration and
invalidates any outstanding Revert buttons.

Eligible external changes receive an additional mobile notification showing the
API parameter name and old/new values, with an individual **Revert** button. The
existing persistent change alert remains available even if the target is missing
or mobile delivery fails; ordinary push alerts may also appear. Detection alone
never writes. Safe Mode still blocks Revert, even after a deliberate tap.

Each button is single-use, expires after 15 minutes, and belongs to that loaded
integration entry. At most 32 actions are retained in memory; older actions can
be evicted. Changed settings, reloads, unloads and restarts invalidate actions.
Unknown, read-only, volatile and bitmask parameters are not offered. Before a
write, the integration fetches fresh settings and checks identity, value and
editable bounds; a concurrent settings poll can conservatively cancel the action.
The controller has no atomic compare-and-set: a change after that check cannot
be ruled out.

One authorised tap starts one bounded operation, not necessarily one HTTP
request. Existing transport handling may resend the **same parameter/value**
after a timeout, up to **five total attempts** (initial plus at most four retries).
Requests remain serialised with at least one second after the preceding request
completes, including timeouts. A response stops timeout retries; explicit errors
and response mismatches are not retried. Duplicate taps cannot start another
operation. There is no scheduled retry, automatic revert, or Revert All.

Only an API-acknowledged success is logged with `source=revert`; this is not
physical-state confirmation. After an unconfirmed/failed operation, check the
controller before trying again: a timed-out request might have been applied.
The next settings poll shows the observed state and may also notify about the
revert itself. Revert deliberately does not add self-write suppression markers,
so later guest changes remain visible; the separate deferred restore issue #11
is unchanged. Local HA/emulator tests cover this path, not real phone delivery or
heat-pump behaviour.

#### What gets created

After successful configuration, you'll have entities with the prefix `grant_aerona_heat_pump_`:

- **21 sensors** -- 13 operational readings and 8 diagnostic/status sensors
- **24 number entities** -- writable setpoints, thresholds, timers and correction values
- **21 select entities** -- 7 mode/type selectors and 14 bitmask controls
- **1 button entity** -- Restore Default Settings
- **2 services** -- named settings backup and restore

Go to **Settings > Devices & Services > EcoNet Grant Aerona** to see the full list.

---

### 6. Understand Safe Mode

The integration starts in **Safe Mode** by default. This means:

- All write operations (changing setpoints, modes, etc.) are **blocked**
- When you attempt a write, a persistent notification appears showing what *would* have been sent
- No data is actually written to the controller

This lets you verify the integration is reading correctly before you allow it to write.

**To disable Safe Mode** (when you're ready to write):
1. Go to **Settings > Devices & Services**
2. Click **Configure** on the EcoNet Grant Aerona entry
3. Uncheck **Safe mode (require approval for writes)**
4. Click **Submit**

> **Recommendation:** Leave Safe Mode enabled for initial testing. Check that all sensor values match what you see in the ecoNET vendor app. Only disable it when you're confident the readings are correct.

---

### 7. Dashboard Setup

The integration includes a Lovelace dashboard for **fresh installations** with 6 tabs: Favourites, Circuit 1, Hot Water, System, Guest, and Admin. It uses two custom frontend cards. Deploy it now if you want the supplied UI and its snapshot controls.

> **Upgraded installations:** Home Assistant normally preserves existing entity IDs when friendly names change. This dashboard uses the IDs generated by a fresh installation of the current version. If your integration was installed before the CH/HW naming update, compare the actual IDs under **Settings > Devices & Services > EcoNet Grant Aerona > Device** and replace any differing dashboard IDs before deployment.

#### 7a. Install required HACS frontend cards

The dashboard uses two custom card libraries. Install both from HACS:

1. Open **HACS** from the sidebar
2. Go to **Frontend** (tab at top)
3. Click **Explore & Download Repositories** (bottom right)
4. Search for **Mushroom** and install it
5. Search for **Mini Graph Card** and install it
6. When prompted, **reload the browser** (or clear cache / hard refresh with Ctrl+Shift+R)

#### 7b. Copy the dashboard file

If you installed via HACS, the dashboard file is already on your system at:

```
/homeassistant/custom_components/econet_grant/extras/econet_grant_dashboard.yaml
```

You need to copy it to a location where HA can use it as a YAML dashboard. Open the **Terminal & SSH** app and run:

```bash
mkdir -p /homeassistant/dashboards
cp /homeassistant/custom_components/econet_grant/extras/econet_grant_dashboard.yaml \
   /homeassistant/dashboards/econet_grant_dashboard.yaml
```

> **Alternative:** If you prefer, use the **File Editor** app or **Samba** share to copy the file manually. The source and destination paths are shown above.

> **Manual installation?** If you cloned the repo instead of using HACS, use `custom_components/econet_grant/extras/econet_grant_dashboard.yaml` from the clone and copy it to `/homeassistant/dashboards/`.

#### 7c. Register the dashboard

Add the following to your `/homeassistant/configuration.yaml`:

```yaml
lovelace:
  mode: storage
  dashboards:
    econet-grant:
      mode: yaml
      title: Grant Aerona Heat Pump
      icon: mdi:heat-pump-outline
      filename: dashboards/econet_grant_dashboard.yaml
```

> If you already have a `lovelace:` section, just add the `econet-grant:` block under the existing `dashboards:` key.

#### 7d. Check configuration

Before restarting, verify your YAML is valid:

1. Go to **Developer Tools** (in the sidebar) > **YAML** tab
2. Click **Check Configuration**
3. If you see *"Configuration will not prevent Home Assistant from starting"*, you're good to proceed
4. If errors are reported, fix the `configuration.yaml` edits from step 7c before continuing

#### 7e. Restart and verify

1. **Restart Home Assistant:** Settings > System > Restart
2. The **Grant Aerona Heat Pump** dashboard will appear in the sidebar
3. Open it and verify the Favourites tab shows Mushroom cards with live readings and a temperature history graph

> **Note:** Some dashboard cards depend on helpers that haven't been created yet. The Guest tab will show errors until you complete [Step 9](#9-create-helpers).

#### 7f. Updating the dashboard after a HACS update

When you update the integration via HACS, a new version of the dashboard file arrives at `custom_components/econet_grant/extras/`. To apply it, re-run the copy command from Step 7b:

```bash
cp /homeassistant/custom_components/econet_grant/extras/econet_grant_dashboard.yaml \
   /homeassistant/dashboards/econet_grant_dashboard.yaml
```

Then hard-refresh the browser (Ctrl+Shift+R). No HA restart is needed -- YAML dashboards are re-read on page load.

---

### 8. Take a Baseline Backup

Before changing any settings, save a snapshot of the current configuration using the dashboard you just deployed:

1. Open the **Grant Aerona Heat Pump** dashboard from the sidebar
2. Go to the **Admin** tab
3. Click the **Take Default Snapshot** button (you'll be asked to confirm)
4. A persistent notification will confirm the snapshot was saved

The **Last Default Snapshot** field on the Admin tab shows when the snapshot was taken. Open the entity's more-info dialog to see its `param_count` attribute. You can restore to this state using the **Restore Default** button next to it.

> **Why now?** The backup captures the controller's current state. Taking it before you or the integration change anything gives you a known-good baseline to roll back to.

---

### 9. Create Helpers

The dashboard and automations use two HA helpers. Create them via the UI:

Go to **Settings > Devices & Services > Helpers** (tab at top) > **Create Helper**.

#### Helper 1: Guest Checkout Date

| Field | Value |
|-------|-------|
| Type | Date |
| Name | Guest Checkout Date |
| Entity ID | `input_datetime.guest_checkout_date` |

#### Helper 2: Guest Checkout Active

| Field | Value |
|-------|-------|
| Type | Toggle |
| Name | Guest Checkout Active |
| Entity ID | `input_boolean.guest_checkout_active` |

After creating both helpers, the dashboard's Guest tab should work without errors.

---

### 10. Install Automations

The repository includes a guest checkout automation YAML file under `ha_config/automations/`. This is optional but recommended if you use the guest checkout feature.

> **Note:** Push notifications for setting changes are built into the integration (enabled by default). No automation is needed for those -- toggle the option in **Settings > Devices & Services > EcoNet Grant Aerona > Configure**.

#### Option A: Import via the UI (recommended)

Open the file below, copy the contents, and paste it into **Settings > Automations & Scenes > Create Automation > Edit as YAML**.

| File | Purpose |
|------|---------|
| `ha_config/automations/guest_checkout.yaml` | Restores default settings at 10 AM on the guest checkout date |

> **Note:** When pasting, remove the leading `- ` list marker if the HA editor expects a single automation per entry. The YAML file contains a list item (starting with `- id:`).

#### Option B: Include via configuration.yaml

If you prefer file-based automations, copy the YAML file into `/homeassistant/automations/` and include it:

```yaml
automation: !include_dir_merge_list automations/
```

Then restart Home Assistant.

---

### 11. Optional: Grafana

The three examples use **InfluxDB 1.x / InfluxQL**, with HA exporting entity states as in Step 3. They do not query `econet_grant.db`, reconstruct earlier history, or require a new entity or provider. Download `grafana/` and `ha_config/` from the repository; these top-level examples are not installed by HACS with the integration.

#### Datasource and import

1. Install and start the Grafana app, then use **Open Web UI** (or its HA sidebar entry). Standalone Grafana also works with an authenticated URL you manage.
2. In Grafana, add an **InfluxDB** datasource under **Connections > Data sources**, selecting **InfluxQL**, not Flux. Use a server URL reachable **from Grafana**, e.g. `https://<INFLUXDB_HOST>:<INFLUXDB_PORT>`, with the scheme/port actually configured by your server. Keep TLS verification enabled for HTTPS; private app-network HTTP is a different connection from browser embedding. Do not expose InfluxDB publicly.
3. Set database `econet_grant`, the dedicated **READ-only** database username and password from Step 3, and HTTP method **GET**. These are database credentials, not your HA/Grafana login; do not enable an extra HTTP Basic Auth layer unless your proxy requires one. Choose **Save & test**, then verify an actual read in Explore. A successful connection test alone does not prove entity data exists. Database selection is not access control: enforce read-only grants server-side.
4. The supplied dashboards bind every query to datasource UID **`econet-influxdb`** (not the display name). Either provision `grafana/datasources/influxdb.yaml` using your Grafana installation's supported provisioning mechanism, or configure via the UI and replace every `econet-influxdb` UID in the three JSON files with your datasource's actual UID before import. The provisioning example uses `jsonData.dbName` and environment placeholders `INFLUXDB_URL`, `INFLUXDB_READ_USER`, `INFLUXDB_READ_PASSWORD`; these must be set in the **Grafana process**, not HA's YAML or your browser. If your HAOS app does not expose provisioning/environment configuration, use the UI route. Never put secrets in dashboard JSON or commit filled-in provisioning files.
5. Use **Dashboards > New > Import**, upload each of `temperature.json`, `performance.json`, and `system.json` from `grafana/dashboards/`, choose a folder and import. These are dashboard models, not HTTP API `{dashboard, overwrite}` envelopes. Their stable dashboard UIDs are `econet-temperature`, `econet-performance`, `econet-system`; check before replacing an existing dashboard with the same UID.
6. Start with **Last 24 hours** (System defaults to **Last 7 days**), then widen the range to include known exported events. Use the panel's Query inspector to check the resolved datasource, request and returned fields. The stat panel shows the latest setpoints **within the selected range**, not guaranteed current controller values.

#### Schema and entity mapping

With `measurement_attr: unit_of_measurement` and `default_measurement: state`, numeric temperatures use measurement **`°C`**, frequency **`Hz`**, pump speed **`rpm`**, with numeric field **`value`**. Unitless text modes use measurement **`state`**, string field **`state`**, not `value`. Each point has separate **`domain`** and **`entity_id`** tags; the latter is the object ID **without** `sensor.`, `number.` or `select.`. HA `unknown`/`unavailable` states are not plotted as zero. Custom units (e.g. °F), measurement overrides, or renamed entities require matching query changes.

Fresh default entity IDs used by these examples:

| API definition | HA entity ID | Measurement / field |
|---|---|---|
| `Circuit1thermostat` | `sensor.grant_aerona_heat_pump_ch_thermostat` | `°C` / `value` |
| `Circuit1ComfortTemp` | `number.grant_aerona_heat_pump_ch_day_temp` | `°C` / `value` |
| `TempCWU` | `sensor.grant_aerona_heat_pump_hw_temperature` | `°C` / `value` |
| `HDWTSetPoint` | `number.grant_aerona_heat_pump_hw_set_point` | `°C` / `value` |
| `GrantOutdoorTemp` | `sensor.grant_aerona_heat_pump_outdoor_temperature` | `°C` / `value` |
| `GrantOutgoingTemp` | `sensor.grant_aerona_heat_pump_flow_temperature` | `°C` / `value` |
| `GrantReturnTemp` | `sensor.grant_aerona_heat_pump_return_temperature` | `°C` / `value` |
| `GrantCompressorFreq` | `sensor.grant_aerona_heat_pump_compressor_frequency` | `Hz` / `value` |
| `GrantPumpSpeed` | `sensor.grant_aerona_heat_pump_pump_speed` | `rpm` / `value` |
| `HeatSourceCalcPresetTemp` | `sensor.grant_aerona_heat_pump_heat_source_preset_temp` | `°C` / `value` |
| `TempBuforDown` | `sensor.grant_aerona_heat_pump_buffer_temp_lower` | `°C` / `value` |
| `workState2` | `select.grant_aerona_heat_pump_work_mode` | `state` / `state` |

Verify IDs in **Developer Tools > States** or the entity registry. Existing installations can retain legacy Circuit 1/DHW labels and IDs; custom device names and collision suffixes also change IDs. Changing a display label does not migrate stored InfluxDB tags. Adjust the HA include filters and each query's domain/object-ID pair to your actual IDs; do not rename live entities just to fit an example. Old `sensor.econet_grant_*` examples are not authoritative registry IDs.

The CH Day setting is not always the active target (Night/Schedule modes differ). Work Mode is the configured Summer/Winter/Auto select, not a nonexistent work-state sensor or compressor-running indication. Buffer and other readings may be absent on a controller: hide those panels or accept no data, rather than inventing a sensor. Performance shows existing temperatures, frequency and speed only; it does not infer COP. The former Flux differential join is omitted, and the System overview is scoped to flow/return rather than every temperature in your HA database.

#### No-data diagnosis (read only)

In Grafana Explore, select the same datasource and switch to the raw InfluxQL editor. Check the schema with `SHOW MEASUREMENTS`, `SHOW FIELD KEYS FROM "°C"`, and `SHOW TAG VALUES FROM "°C" WITH KEY = "entity_id"`. For example:

```sql
SELECT "value" FROM "°C"
WHERE "domain" = 'sensor'
  AND "entity_id" = 'grant_aerona_heat_pump_ch_thermostat'
  AND time > now() - 7d
ORDER BY time DESC LIMIT 10
```

If empty, check in order: datasource UID and InfluxQL selection; database and default retention policy; Grafana-to-InfluxDB connectivity and read grants; HA InfluxDB connection/logs and include filters; exact measurement/unit, field and domain/object-ID tags; then time range/timezone and whether any state events occurred since export started. Text queries must select `"state"` from `"state"`; `mean("value")` cannot graph Winter/Auto. Missing sensors, unchanged values, unavailable periods and expired retention can all mean no points. Widen the range for infrequently changed setpoints/modes; the text timeline has no inferred state before its first returned event. Do not change heating settings merely to populate a graph. There is no automatic SQLite backfill.

#### Access from the HA dashboard

The canonical Lovelace System tab now has instructions rather than a failing default iframe. Prefer **Open Web UI** / the app's sidebar entry: [Home Assistant Ingress](https://developers.home-assistant.io/docs/apps/presentation/#ingress) authenticates access through HA. That developer API does not promise a permanent copy-and-paste Lovelace iframe URL. Do not hard-code a session/Ingress path, disable authentication, enable anonymous access, or weaken framing/cookie protections to make embedding work. For standalone Grafana, open its authenticated HTTPS URL in a separate tab; an HTTP iframe in HTTPS HA is mixed content and should not be assumed to work.

**Validation status:** repository tests parse all example JSON/YAML and statically check query grammar, datasource binding and measurement/field/tag pairs against a synthetic, sanitised HA schema fixture and integration definitions. They do **not** execute InfluxQL, render Grafana, or test login/Ingress. **UNVERIFIED owner validation:** clean HAOS/Grafana install, authenticated datasource read, all three dashboard imports, real entity mapping, text timeline rendering, time range/no-data behaviour and remote/Companion access. Record installed versions and results before treating this as an end-to-end verified setup.

References: [HA InfluxDB schema/configuration](https://www.home-assistant.io/integrations/influxdb/), [HA state-to-point implementation](https://github.com/home-assistant/core/blob/2026.2.3/homeassistant/components/influxdb/__init__.py), [Grafana InfluxDB datasource configuration/provisioning](https://grafana.com/docs/grafana/latest/datasources/influxdb/configure-influxdb-data-source/).

---

### 12. Verification Checklist

Use this checklist to confirm everything is working. Tick off each item as you go.

#### Core Integration

- [ ] Integration appears in **Settings > Devices & Services**
- [ ] Device **Grant Aerona Heat Pump** is listed with all entities
- [ ] Sensor values (outdoor temp, flow temp, DHW temp, etc.) match the ecoNET vendor app
- [ ] Compressor frequency and pump speed show plausible values
- [ ] System Demand is populated
- [ ] Fan Speed shows a reading (or 0 if the outdoor unit is idle)

#### InfluxDB (if installed)

- [ ] InfluxDB app is running
- [ ] Database `econet_grant` exists (check **InfluxDB Admin > Databases** in Chronograf)
- [ ] InfluxDB integration appears in **Settings > Devices & Services** (configured via UI, not YAML)
- [ ] `configuration.yaml` InfluxDB section contains only filtering (`include`), **not** connection keys
- [ ] In Chronograf, go to **Explore** and query `econet_grant` to confirm readings are being recorded

#### Safe Mode

- [ ] With Safe Mode ON: attempt to change a number entity (e.g. HW Set Point). A persistent notification appears instead of writing
- [ ] No value was actually changed on the controller (verify in vendor app)

#### Dashboard

- [ ] **Grant Aerona Heat Pump** appears in the sidebar
- [ ] Favourites tab: Mushroom cards show live readings; temperature history graph displays
- [ ] Circuit 1 tab: CH temperature history graph and all heating controls display
- [ ] Hot Water tab: HW temperature history graph and all hot water controls display
- [ ] System tab: operating modes, system readings, and backup heater settings display
- [ ] Guest tab: checkout date helper and toggle are functional
- [ ] Admin tab: safe mode status and backup/restore buttons work

#### Helpers & Automations

- [ ] Both helpers exist in **Settings > Helpers**
- [ ] Push notifications: toggle is enabled in integration options (Settings > Devices & Services > EcoNet Grant Aerona > Configure)

#### Write Operations (when ready)

- [ ] Disable Safe Mode in integration options
- [ ] Change a non-critical setting (e.g. HW Hysteresis from its current value to current+1, then back)
- [ ] Verify the change appears in the ecoNET vendor app
- [ ] Verify the change detector fires an event (check **Developer Tools > Events** > listen for `econet_grant_setting_changed`)

---

### 13. Troubleshooting

#### Integration won't connect

- Verify the ecoNET IP is reachable: `curl http://<ip>/econet/regParams` from the HA terminal
- Check credentials are for the local device, not the cloud account
- Ensure nothing else is holding a connection to the device (the ecoNET app, another HA instance)

#### Entities show "Unavailable"

- The first data pull happens within 30 seconds of integration load. Wait a minute after restart
- Check **Settings > System > Logs** for errors containing `econet_grant`
- If using a firewall or VLAN, confirm HA can still reach the device

#### Dashboard shows errors

- Ensure both helpers from [Step 9](#9-create-helpers) exist with the exact entity IDs listed
- The System-tab Grafana card is informational. If you skipped Step 11, no Grafana setup is required; see that step for optional import and no-data diagnosis.

#### Entity IDs don't match expected format

All entities use the prefix `grant_aerona_heat_pump_` (from the device name "Grant Aerona Heat Pump"). If your entity IDs are different, check **Settings > Devices & Services > EcoNet Grant Aerona > Device** for the actual entity IDs and update the dashboard YAML to match.

#### Safe Mode notifications keep appearing

This is working as intended. Every write attempt in Safe Mode generates a notification. Disable Safe Mode in integration options when ready to allow writes.

#### InfluxDB shows no data

- Confirm the InfluxDB integration is set up via **Settings > Devices & Services** (not just the YAML)
- Confirm the entity globs in `configuration.yaml` use `grant_aerona_heat_pump_*` (not `econet_grant_*`)
- Check the InfluxDB app logs for connection errors
- Verify the password you entered in the UI integration matches the one you set for the `homeassistant` user in InfluxDB
- Remember that data flows to InfluxDB only from the point at which InfluxDB is configured; earlier Home Assistant or SQLite history is not backfilled
- If you see a deprecation warning about YAML connection keys (`host`, `port`, `database`, `username`, `password`), remove those keys from `configuration.yaml` and restart -- the connection is now managed via the UI

---

## Quick Reference

| What | Where |
|------|-------|
| Integration domain | `econet_grant` |
| Entity ID prefix | `grant_aerona_heat_pump_*` |
| Service calls | `econet_grant.backup_settings`, `econet_grant.restore_settings` |
| Dashboard file | `custom_components/econet_grant/extras/econet_grant_dashboard.yaml` (copy to `/homeassistant/dashboards/`) |
| HA config additions | None for the integration itself. Optional: Lovelace dashboard block and InfluxDB filtering block |
| Automations | `ha_config/automations/` -- guest checkout (push notifications are built-in) |
| Helpers needed | `input_datetime.guest_checkout_date`, `input_boolean.guest_checkout_active` |
| Logs | Settings > System > Logs (filter for `econet_grant`) |
| GitHub | [mac-wifi/Grant_Aerona_ecoNET_HomeAssistant_Tool](https://github.com/mac-wifi/Grant_Aerona_ecoNET_HomeAssistant_Tool) |

## Hardware

- **Heat Pump**: Grant Aerona (air source)
- **Controller**: ecoMAX360i
- **Network Module**: ecoNET300

## Known Limitations

- Parameter mappings were reverse-engineered from a single Grant Aerona installation. Other ecoNET-based systems (different manufacturers or controller models) will likely have different parameter indices and tile layouts.
- Fan Speed and System Demand are read from `tilesParams` and `schemaParams` respectively, which are positional/key-based. These positions could theoretically differ on other firmware versions.
- The ecoNET local API is undocumented. Endpoint behaviour was determined through experimentation.
- Not all ecoNET parameters have been mapped -- only those tested via before/after comparison.
- The ecoNET Remote Menu (RM) API, which provides full parameter metadata and dynamic entity creation, is not supported by the ecoMAX360i controller (`remoteMenu: false` in `sysParams`). If a future firmware update enables it, the integration could be significantly enhanced.
- Write success currently requires only `result: "OK"`; the returned `paramName` and `paramValue` are not yet validated and there is no post-write read-back check.
- The bundled SQLite history is currently an internal audit/raw-data store rather than a general Home Assistant or Grafana data source. Only database size and recent-change count are exposed as entities.
- An initial offline test suite covers selected safety and lifecycle behavior; it is not full Home Assistant or hardware verification. See [TESTING.md](TESTING.md) for setup, coverage limits and the single `python -m pytest` command. Hosted CI execution remains unverified.

## Read-only before/after export and comparison

The standalone utilities in `scripts/` use Python 3.10+ and the standard library;
they do not require Home Assistant or third-party packages. Run them from a local
repository checkout, keeping `export_econet.py` and `compare_econet.py` together.
They are not integration services or restore files, and are not installed into
Home Assistant by the HACS integration package. Their presence in this checkout
does not imply a published release.

**Privacy:** sanitisation is best-effort, not a guarantee of anonymity. It redacts
recognised credential, UID/controller identity, serial, host/IP/MAC and network
fields, known sensitive strings echoed elsewhere, and address-like text. Unknown
firmware fields or free text can still contain private data. Redaction can also
hide useful differences or over-redact innocent strings. Review **both snapshots
and the comparison** before sharing. Never commit real captures or comparisons,
even if they appear sanitised; only synthetic fixtures belong in Git. Keep output
in a private directory (the existing `exports/` path is ignored) and avoid shared
or cloud-synchronised folders. Ignore rules are not an access-control mechanism.

### Owner-operated workflow

Only do this when you deliberately choose to investigate a setting on your own
device. The utilities never make a setting change themselves.

1. Capture the **before** state. Replace the placeholders with your explicit
   local device origin and local username; there are no private connection defaults:

   ```sh
   python3 scripts/export_econet.py --origin 'http://<econet-host>' \
     --username '<local-username>' --output-dir exports/before
   ```

   Enter the local API password at the hidden terminal prompt. There is no password
   argument or credential file lookup; an unavailable hidden prompt fails rather
   than echoing the password. Host and username arguments may be visible in shell
   history/process listings. Never put credentials in the URL. Basic Auth over
   HTTP is unencrypted: use only a trusted LAN, or an explicit `https://` origin
   if your device supports it (normal certificate verification remains enabled).
2. In the vendor app, make **one owner-chosen change**, noting the setting and
   old/new values. Wait for the vendor app to show the saved value.
3. Capture the **after** state with the same command but `--output-dir exports/after`.
   Each successful run prints the path of a separate `econet-<UTC timestamp>.json`.
4. Compare the two exact printed paths, substituting them below:

   ```sh
   python3 scripts/compare_econet.py exports/before/econet-<timestamp>.json \
     exports/after/econet-<timestamp>.json > exports/comparison.json
   ```

Each snapshot contains `schema_version: 1`, a timezone-aware `captured_at`, and
an `endpoints` object containing only `regParams`, `editParams`, and `sysParams`.
Capture performs three sequential GETs with a one-second gap and 15-second request
timeouts, not an atomic controller transaction. It never accesses write or Remote
Menu endpoints, follows redirects, uses environment proxies, or retries. All three
responses must pass structural validation before a final snapshot is published;
failed/partial/invalid downloads do not become valid snapshots. Files are created
privately (0600 on POSIX) and existing captures are not overwritten. Atomic final
publication requires a local filesystem supporting hard links. Unsupported payload
shapes fail closed rather than being silently treated as empty data.

Comparison is entirely offline. Its JSON array contains `endpoint`, `name`,
`index`, `change` (`changed`, `added`, `removed`), `old`, and `new`. Editable values
use the API name and string index; other fields, including editable metadata, use
escaped JSON Pointer paths (for example `/curr/GrantOutgoingTemp` or
`/data/238/maxv`) with `index: null`. Arrays are compared as whole values. The change
kind distinguishes a missing value from JSON `null`; renamed/reindexed parameters
appear as removal/addition. Unchanged values and capture timestamps are omitted;
no differences produces `[]`. Volatile readings/version counters are intentionally
included, so not every difference is caused by your vendor-app change. Redacted
values cannot reveal whether the underlying secret changed.

Both tools return 0 on success, 1 on capture/input failure, and 2 on invalid CLI
arguments. Comparison differences still return 0. On failure, no comparison JSON
is printed; a shell-redirected output file may exist but will be empty, not `[]`.
Missing, malformed, incomplete or unsupported-version snapshots are rejected.
These utilities were exercised only with synthetic snapshots and mocked HTTP;
no real controller capture or real-data sanitisation validation is claimed.

## Related Projects

- [ecoNET-300 Home Assistant Integration](https://github.com/jontofront/ecoNET-300-Home-Assistant-Integration) -- A similar project for different ecoNET hardware (pellet boilers). Some API knowledge was referenced from this project.

## License

MIT
