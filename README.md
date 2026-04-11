# EcoNet Grant Aerona - Home Assistant Integration

> **Warning: This is a work-in-progress project built with AI-assisted coding (Cursor IDE). It is provided as-is with no warranty. Use entirely at your own risk. This integration writes to a live heat pump controller -- incorrect use could affect your heating system.**

A custom Home Assistant integration for monitoring and controlling a **Grant Aerona** heat pump via the **ecoNET** local REST API (ecoMAX360i controller).

This project was created to remotely manage a holiday home heat pump, allowing the owner to monitor what guests are doing with the heating and revert unwanted changes.

## Current Status

**Version:** 0.2.0 (active development)

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
- **Change Detection**: Monitors `editParams` for external changes (e.g. someone adjusting settings via the ecoNET app or panel). Fires `econet_grant_setting_changed` events and `econet_grant_urgent_change` for critical parameters.
- **Circuit 1 Guardian**: Can lock the heating day temperature to a desired value and automatically revert if changed externally.
- **Backup & Restore**: Services to snapshot all editable parameters and restore them later (e.g. after guest checkout).
- **Dashboard YAML**: A ready-made Lovelace dashboard in `dashboards/econet_grant_dashboard.yaml`.

## Installation

### Prerequisites (recommended)

If you want Grafana dashboards with historical temperature and performance graphs:

1. Install the **InfluxDB** addon from the Home Assistant Add-on Store
2. Configure the **InfluxDB integration** in HA (Settings > Devices & Services > Add Integration > InfluxDB)
3. This captures all sensor data from the moment the EcoNet integration starts -- no data migration needed later

If you skip this step, the integration still works fully. Sensor data is stored in HA's built-in recorder and in the integration's own SQLite database. You can add InfluxDB later, but you will only have data from that point forward.

### Install via HACS (recommended)

1. Open HACS in your Home Assistant instance
2. Click the three dots menu > Custom repositories
3. Add this repository URL with category "Integration"
4. Click "Download" on the EcoNet Grant Aerona card
5. Restart Home Assistant
6. Go to Settings > Devices & Services > Add Integration > "EcoNet Grant Aerona"
7. Enter your ecoNET device's local IP address, username, and password

### Manual Installation

1. Copy the `custom_components/econet_grant/` folder into your Home Assistant `custom_components/` directory
2. Restart Home Assistant
3. Go to **Settings > Devices & Services > Add Integration** and search for "EcoNet Grant Aerona"
4. Enter your ecoNET device's local IP address, username, and password (these are the local device credentials, not your econet24.com cloud account)

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

## Export & Comparison Tools

The `tools/` directory contains scripts for reverse-engineering the ecoNET API by comparing parameter snapshots before and after making changes in the vendor iOS app.

### Pulling exports

```bash
# Set your ecoNET password (or you'll be prompted)
export ECONET_PASS="your_password"

# Pull a "before" snapshot
./tools/pull_exports.sh before

# Make a change in the iOS app...

# Pull an "after" snapshot
./tools/pull_exports.sh after
```

This saves `regParams.json`, `editParams.json`, and `sysParams.json` to timestamped directories under `exports/`.

Exports can be compared manually using standard JSON diff tools (`diff`, `jq`, etc.) to discover parameter index mappings. This is how all the parameter mappings in this integration were identified.

Note: `exports/` is gitignored because the files contain device identifiers and password hashes.

## Hardware

- **Heat Pump**: Grant Aerona (air source)
- **Controller**: ecoMAX360i
- **Network Module**: ecoNET300 (mr3020-v3 router, firmware 3.2.3881)
- **Panel**: S003.20_1.10
- **Module A**: S003.14

## Known Limitations

- Parameter mappings were reverse-engineered from a single Grant Aerona installation. Other ecoNET-based systems (different manufacturers or controller models) will likely have different parameter indices and tile layouts.
- Fan Speed and System Demand are read from `tilesParams` and `schemaParams` respectively, which are positional/key-based. These positions could theoretically differ on other firmware versions.
- The ecoNET local API is undocumented. Endpoint behaviour was determined through experimentation.
- Not all ecoNET parameters have been mapped -- only those tested via before/after comparison.
- The ecoNET Remote Menu (RM) API, which provides full parameter metadata and dynamic entity creation, is not supported by the ecoMAX360i controller (`remoteMenu: false` in `sysParams`). See [Reference/RM_ENDPOINTS.md](Reference/RM_ENDPOINTS.md) for details and how to detect if a future firmware update enables it.
- InfluxDB, Grafana, and Alexa/guest-checkout integration are planned but not yet implemented.

## Related Projects

- [ecoNET-300 Home Assistant Integration](https://github.com/jontofront/ecoNET-300-Home-Assistant-Integration) -- A similar project for different ecoNET hardware (pellet boilers). Some API knowledge was referenced from this project.

## License

MIT
