# EcoNet Grant Aerona - Home Assistant Integration

> [!CAUTION]
> **Work in progress -- use at your own risk.** This is an active development project built with AI-assisted coding (Cursor IDE). It is provided as-is with no warranty. This integration writes to a live heat pump controller -- incorrect use could affect your heating system.

A custom Home Assistant integration for monitoring and controlling a **Grant Aerona** heat pump via the **ecoNET** local REST API (ecoMAX360i controller).

This project was created to remotely manage a holiday home heat pump, allowing the owner to monitor what guests are doing with the heating and revert unwanted changes.

## Current Status

**Version:** 0.3.0 (active development)

The integration is functional but has not been deployed to a production Home Assistant instance yet. All parameter mappings have been confirmed through manual before/after testing against the live ecoNET controller using the vendor's iOS app.

## What Works

### Read-Only Sensors (polled every 5 minutes from `regParams`)

| Entity | Source | Description |
|---|---|---|
| Outdoor Temperature | `curr.GrantOutdoorTemp` | Outdoor air temp from heat pump |
| Flow Temperature | `curr.GrantOutgoingTemp` | Water flow temperature |
| Return Temperature | `curr.GrantReturnTemp` | Water return temperature |
| DHW Temperature | `curr.TempCWU` | Domestic hot water tank temp |
| Heating Thermostat | `curr.Circuit1thermostat` | Circuit 1 room thermostat reading |
| Weather Temperature | `curr.TempWthr` | Weather compensation sensor |
| Buffer Temperature (Lower) | `curr.TempBuforDown` | Buffer tank lower temp |
| Heat Exchanger Temperature | `curr.TempClutch` | Heat exchanger / clutch temp |
| Heat Source Preset Temp | `curr.HeatSourceCalcPresetTemp` | Calculated target flow temp |
| Compressor Frequency | `curr.GrantCompressorFreq` | Compressor operating frequency (Hz) |
| Pump Speed | `curr.GrantPumpSpeed` | Main circulation pump speed (rpm) |
| Work State | `curr.GrantWorkState` | System on/off state |
| Fan Speed | `tilesParams[3]` | Outdoor unit fan speed (rpm) |
| System Demand | `schemaParams.reakcja_termostat1` | Heat demand status (Heat / No Demand) |

### Writable Number Entities (from `editParams`)

| Entity | Param Index | Range | Description |
|---|---|---|---|
| Heating Day Temperature | 238 | 10-35 °C | Circuit 1 comfort (day) setpoint |
| Heating Night Temperature | 239 | 10-35 °C | Circuit 1 eco (night) setpoint |
| Heating Base Temperature | 261 | 25-60 °C | Circuit 1 base temperature |
| Heating Hysteresis | 240 | 0-5 °C | Circuit 1 switching hysteresis |
| Heating Curve | 273 | 0-4 | Weather compensation curve gradient |
| Heating Curve Shift | 275 | -20 to 20 °C | Curve parallel shift offset |
| Circuit 1 Boost Time | 1521 | 0-180 min | Boost heating timer |
| DHW Set Point | 103 | 20-55 °C | Hot water target temperature |
| DHW Hysteresis | 104 | 0-10 °C | Hot water switching hysteresis |
| DHW Extension of Work | 113 | 0-30 min | Extra DHW heating time |
| DHW Correction Temperature | 481 | 0-20 °C | DHW temperature correction offset |
| Panel Temperature Correction | 10413 | -5 to 5 °C | Panel sensor correction |
| Summer Mode Activation Temp | 702 | 17-30 °C | Outdoor temp to enter summer mode |
| Winter Mode Activation Temp | 703 | 0-19 °C | Outdoor temp to enter winter mode |
| Heating Temperature Correction | 1402 | 0-20 °C | Circuit temperature correction offset |

### Writable Select Entities (from `editParams`)

| Entity | Param Index | Options | Description |
|---|---|---|---|
| Work Mode | 162 | Summer, Winter, Auto | System operating mode |
| Heating Operation Mode | 236 | Off, Day, Night, Schedule | Circuit 1 operating mode |
| DHW Work Mode | 119 | Off, On, Schedule | Hot water operating mode |
| DHW Boost | 115 | Off, On | Temporary DHW boost |
| Heat Pump Mode | 1133 | Off, On, Schedule | Heat pump operating mode |

### Bitmask Toggle Selects (from `editParams`)

These operate on individual bits within bitmask settings parameters.

| Entity | Settings Param | Bit Mask | Options | Description |
|---|---|---|---|---|
| DHW Specify Priority | 101 (`HDWSETTINGS`) | 16 | Yes / No | DHW priority over heating |
| External Temp Sensor Support | 69 (`TempSettings`) | 1 | Yes / No | External temperature sensor enabled |
| Temperature Sensor Source | 69 (`TempSettings`) | 2 | Heat Pump / ecoMulti | Source of temperature readings |
| Cooling Support | 485 (`HeatingCooling`) | 1 | Yes / No | Cooling mode enabled |
| Heat Pump Lock | 462 (`HeatSourceAllowWorkSett`) | 1 | Yes / No | Lock heat pump operation |
| DHW Support | 101 (`HDWSETTINGS`) | 1 | Yes / No | Domestic hot water enabled |

### Other Features

- **Safe Mode**: All write operations are blocked by default and shown as persistent notifications, allowing manual review before anything is sent to the controller. Disable in integration options when ready to write.
- **Change Detection**: Monitors `editParams` for external changes (e.g. someone adjusting settings via the ecoNET app or panel). Fires `econet_grant_setting_changed` events and `econet_grant_urgent_change` for critical parameters. Creates persistent notifications (bell icon) and sends push notifications to all connected devices (enabled by default, toggle in integration options).
- **Backup & Restore**: Services to snapshot all editable parameters and restore them later (e.g. after guest checkout).
- **Dashboard YAML**: A ready-made Lovelace dashboard in `dashboards/econet_grant_dashboard.yaml`.

## Architecture

```
Home Assistant Server
  └── custom_components/econet_grant/
        ├── Fast coordinator (5 min)  ──GET──>  http://<econet_ip>/econet/regParams
        │     └── Sensors, Fan Speed, System Demand
        ├── Slow coordinator (24 hr)  ──GET──>  http://<econet_ip>/econet/editParams
        │     └── Number entities, Select entities, Change detection
        └── Write operations          ──GET──>  http://<econet_ip>/econet/rmNewParam?...
              └── Sets parameters by index with value
```

The ecoNET device exposes a local REST API with basic auth. All communication is HTTP on the local network. The integration serialises requests with a minimum 1-second gap to avoid overwhelming the controller.

---

## Installation Guide

Step-by-step instructions for installing the integration on a clean Home Assistant OS (HAOS) instance. Tested against HAOS on a virtual machine; the same steps apply to any HAOS installation (Raspberry Pi, NUC, VM, etc.).

**Estimated time:** 25--35 minutes end-to-end.

> **UI terminology:** From HA Core 2026.x, "Add-ons" has been renamed to "Apps" in the Settings menu. This guide uses the current path **Settings > Apps > Install app**. If you're on an older HA version (pre-2026), the equivalent path is **Settings > Add-ons > Add-on Store**.

### Contents

1. [Before You Start](#1-before-you-start)
2. [Install HACS](#2-install-hacs)
3. [Install & Configure InfluxDB (recommended)](#3-install--configure-influxdb-recommended)
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

If HACS is already installed, skip to [Step 3](#3-install--configure-influxdb-recommended).

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

### 3. Install & Configure InfluxDB (recommended)

> **Why now?** InfluxDB must be running *before* the integration is added so that sensor data is captured from the very first poll. If you add InfluxDB later, you will only have data from that point forward -- the initial readings will be lost.
>
> If you want to skip InfluxDB entirely, jump to [Step 4](#4-install-the-integration-via-hacs). The integration works fully without it. Sensor data is still stored in HA's built-in recorder (default 10 days of raw history; long-term hourly statistics are kept indefinitely) and in the integration's own SQLite database (default 10-year retention, configurable in integration options).

#### 3a. Install the InfluxDB app

1. Go to **Settings > Apps > Install app**
2. Search for **InfluxDB** and install it
3. Start the app and open the web UI (Chronograf)

The HA InfluxDB app ships **InfluxDB 1.x** with Chronograf as the web interface. You'll see a default `_internal` database and pre-created users (`chronograf`, `kapacitor`) -- this is normal.

#### 3b. Create the database and user

You need to create a dedicated database and a user for Home Assistant. In the Chronograf web UI:

1. Click **InfluxDB Admin** in the left sidebar
2. On the **Databases** tab, click **Create Database**
3. Enter `econet_grant` as the name and press Enter
4. The database is created with an infinite retention policy by default -- leave this as-is
5. Switch to the **Users** tab and click **Create User**
6. Enter username `homeassistant` and a password of your choice, then click **Create**
7. Click **Grant admin** to give the user admin permissions, or at minimum grant **WRITE** and **READ** on the `econet_grant` database

You're now finished with the InfluxDB / Chronograf UI. The remaining steps are done in the Home Assistant config files.

#### 3c. Add the InfluxDB integration via the UI

> **Note:** As of HA Core 2025.x, InfluxDB connection settings (host, port, database, username, password) **must** be configured via the UI, not in YAML. YAML is only used for filtering options (include/exclude) and other non-connection settings.

1. Go to **Settings > Devices & Services**
2. Click **Add Integration** (bottom right)
3. Search for **InfluxDB** and select it
4. Choose **InfluxDB 1.x** (this matches the HA InfluxDB app)
5. Enter the connection details:

| Field | Value |
|-------|-------|
| **Host** | `a0d7b954-influxdb` |
| **Port** | `8086` |
| **Database** | `econet_grant` |
| **Username** | `homeassistant` |
| **Password** | the password you chose in Step 3b |

6. Click **Submit**

#### 3d. Add entity filtering to configuration.yaml

The UI handles the connection, but entity filtering is still configured in YAML. Add the following to `/homeassistant/configuration.yaml`:

```yaml
influxdb:
  max_retries: 3
  default_measurement: state
  include:
    entity_globs:
      - sensor.grant_aerona_heat_pump_*
      - number.grant_aerona_heat_pump_*
      - select.grant_aerona_heat_pump_*
```

> **Important:** Do NOT add `host`, `port`, `database`, `username`, or `password` keys here. Those are now managed by the UI integration. If you include them, HA will show a deprecation warning and may remove them automatically.

Before restarting, verify your YAML is valid: go to **Developer Tools > YAML** (tab) and click **Check Configuration**. If it reports "Configuration will not prevent Home Assistant from starting", you're good to proceed. If it shows errors, fix them in `configuration.yaml` before continuing.

#### 3e. Restart Home Assistant

**Settings > System > Restart**

InfluxDB is now ready and waiting. As soon as the EcoNet integration starts creating entities (after Step 5), data will flow into InfluxDB automatically.

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

#### What gets created

After successful configuration, you'll have entities with the prefix `grant_aerona_heat_pump_`:

- **14 sensors** -- temperatures, compressor frequency, pump speed, work state, fan speed, system demand
- **14 number entities** -- writable temperature setpoints, hysteresis values, curve settings
- **5 select entities** -- work mode, heating mode, DHW mode, DHW boost, heat pump mode
- **6 bitmask toggle selects** -- DHW priority, external sensor, cooling support, etc.
- **2 button entities** -- backup and restore

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

The integration includes a ready-made Lovelace dashboard with 5 tabs: Temperature, Performance, System, Guest, and Admin. Deploy it now so you can use the built-in snapshot button in the next step.

#### 7a. Copy the dashboard file

Copy `dashboards/econet_grant_dashboard.yaml` from the repository into your HA config directory:

```
/homeassistant/dashboards/econet_grant_dashboard.yaml
```

If the `dashboards/` directory doesn't exist under `/homeassistant/`, create it first.

Using the **Terminal & SSH** app:
```bash
mkdir -p /homeassistant/dashboards
```

Then copy the file using Samba, SSH/SCP, or the File Editor app.

#### 7b. Register the dashboard

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

#### 7c. Check configuration

Before restarting, verify your YAML is valid:

1. Go to **Developer Tools** (in the sidebar) > **YAML** tab
2. Click **Check Configuration**
3. If you see *"Configuration will not prevent Home Assistant from starting"*, you're good to proceed
4. If errors are reported, fix the `configuration.yaml` edits from step 7b before continuing

#### 7d. Restart and verify

1. **Restart Home Assistant:** Settings > System > Restart
2. The **Grant Aerona Heat Pump** dashboard will appear in the sidebar
3. Open it and verify the Temperature tab shows live gauge readings

> **Note:** Some dashboard cards depend on helpers that haven't been created yet. The Guest tab will show errors until you complete [Step 9](#9-create-helpers).

---

### 8. Take a Baseline Backup

Before changing any settings, save a snapshot of the current configuration using the dashboard you just deployed:

1. Open the **Grant Aerona Heat Pump** dashboard from the sidebar
2. Go to the **Admin** tab
3. Click the **Take Default Snapshot** button (you'll be asked to confirm)
4. A persistent notification will confirm the snapshot was saved

The **Last Default Snapshot** field on the Admin tab shows when the snapshot was taken and how many parameters it contains. You can restore to this state at any time using the **Restore Default** button next to it.

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

If you installed InfluxDB in Step 3 and want visual dashboards with historical graphs:

1. Go to **Settings > Apps > Install app**
2. Search for **Grafana** and install it
3. Start the app (runs on port 3000)
4. Open the Grafana web UI and add InfluxDB as a data source (InfluxQL query language, URL `http://a0d7b954-influxdb:8086`, database `econet_grant`, user `homeassistant`)
5. Import the dashboards from `grafana/dashboards/` in the repository (system, temperature, performance JSON files)

> **Note:** The Lovelace dashboard's Performance tab includes Grafana iframe panels that expect Grafana on port 3000. These panels will show errors if Grafana is not installed -- everything else still works.

---

### 12. Verification Checklist

Use this checklist to confirm everything is working. Tick off each item as you go.

#### Core Integration

- [ ] Integration appears in **Settings > Devices & Services**
- [ ] Device **Grant Aerona Heat Pump** is listed with all entities
- [ ] Sensor values (outdoor temp, flow temp, DHW temp, etc.) match the ecoNET vendor app
- [ ] Compressor frequency and pump speed show plausible values
- [ ] Work State and System Demand are populated
- [ ] Fan Speed shows a reading (or 0 if the outdoor unit is idle)

#### InfluxDB (if installed)

- [ ] InfluxDB app is running
- [ ] Database `econet_grant` exists (check **InfluxDB Admin > Databases** in Chronograf)
- [ ] InfluxDB integration appears in **Settings > Devices & Services** (configured via UI, not YAML)
- [ ] `configuration.yaml` InfluxDB section contains only filtering (`include`), **not** connection keys
- [ ] In Chronograf, go to **Explore** and query `econet_grant` to confirm readings are being recorded

#### Safe Mode

- [ ] With Safe Mode ON: attempt to change a number entity (e.g. DHW Set Point). A persistent notification appears instead of writing
- [ ] No value was actually changed on the controller (verify in vendor app)

#### Dashboard

- [ ] **Grant Aerona Heat Pump** appears in the sidebar
- [ ] Temperature tab: gauges show live temperatures
- [ ] Performance tab: compressor/pump/fan cards display data
- [ ] Settings tab: number and select entities are controllable
- [ ] Guest tab: checkout date helper and toggle are functional
- [ ] Admin tab: safe mode status and backup/restore buttons work

#### Helpers & Automations

- [ ] Both helpers exist in **Settings > Helpers**
- [ ] Push notifications: toggle is enabled in integration options (Settings > Devices & Services > EcoNet Grant Aerona > Configure)

#### Write Operations (when ready)

- [ ] Disable Safe Mode in integration options
- [ ] Change a non-critical setting (e.g. DHW Hysteresis from its current value to current+1, then back)
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

- Ensure all four helpers from [Step 9](#9-create-helpers) exist with the exact entity IDs listed
- Grafana panels will show errors if Grafana is not installed -- this is expected if you skipped Step 11

#### Entity IDs don't match expected format

All entities use the prefix `grant_aerona_heat_pump_` (from the device name "Grant Aerona Heat Pump"). If your entity IDs are different, check **Settings > Devices & Services > EcoNet Grant Aerona > Device** for the actual entity IDs and update the dashboard YAML to match.

#### Safe Mode notifications keep appearing

This is working as intended. Every write attempt in Safe Mode generates a notification. Disable Safe Mode in integration options when ready to allow writes.

#### InfluxDB shows no data

- Confirm the InfluxDB integration is set up via **Settings > Devices & Services** (not just the YAML)
- Confirm the entity globs in `configuration.yaml` use `grant_aerona_heat_pump_*` (not `econet_grant_*`)
- Check the InfluxDB app logs for connection errors
- Verify the password you entered in the UI integration matches the one you set for the `homeassistant` user in InfluxDB
- Confirm InfluxDB was installed and configured **before** the integration was added (data only flows from the point InfluxDB is configured)
- If you see a deprecation warning about YAML connection keys (`host`, `port`, `database`, `username`, `password`), remove those keys from `configuration.yaml` and restart -- the connection is now managed via the UI

---

## Quick Reference

| What | Where |
|------|-------|
| Integration domain | `econet_grant` |
| Entity ID prefix | `grant_aerona_heat_pump_*` |
| Service calls | `econet_grant.backup_settings`, `econet_grant.restore_settings` |
| Dashboard file | `dashboards/econet_grant_dashboard.yaml` |
| HA config additions | `configuration.yaml` -- lovelace block, InfluxDB filtering block (connection via UI) |
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

## Related Projects

- [ecoNET-300 Home Assistant Integration](https://github.com/jontofront/ecoNET-300-Home-Assistant-Integration) -- A similar project for different ecoNET hardware (pellet boilers). Some API knowledge was referenced from this project.

## License

MIT
