# EcoNet Grant Aerona - Home Assistant Integration

A custom Home Assistant integration for monitoring and controlling a **Grant Aerona** heat pump system via the **ecoNET** REST API (ecoMAX360i controller).

## Features

- **Temperature Monitoring**: Circuit 1, DHW, outdoor, flow, and return temperatures polled every 5 minutes
- **Performance Monitoring**: Compressor frequency, pump speed
- **System Settings**: Daily polling of all 208+ configurable parameters
- **Temperature Control**: Set Circuit 1 and DHW temperatures directly from Home Assistant
- **Change Detection**: Notifications when settings are changed externally (e.g. by guests)
- **Urgent Alerts**: SMS/WhatsApp for critical setting changes
- **Settings Backup & Restore**: One-button restore to saved defaults
- **Circuit 1 Guardian**: Automatically reverts Circuit 1 temperature if changed by guests
- **Guest Checkout**: Alexa integration to schedule automatic settings reset at checkout
- **Safe Mode**: Write approval queue for safe testing against live systems
- **Long-term Storage**: InfluxDB integration for indefinite data retention
- **Grafana Dashboards**: Temperature, performance, and system dashboards

## Installation

### HACS (Recommended)

1. Install [HACS](https://hacs.xyz/) if not already installed
2. Add this repository as a custom repository in HACS
3. Search for "EcoNet Grant Aerona" and install
4. Restart Home Assistant
5. Go to Settings > Devices & Services > Add Integration > "EcoNet Grant Aerona"

### Manual

1. Copy `custom_components/econet_grant/` to your HA `custom_components/` directory
2. Restart Home Assistant
3. Go to Settings > Devices & Services > Add Integration > "EcoNet Grant Aerona"

## Configuration

During setup you will be prompted for:

- **Host**: IP address of your ecoNET device (e.g. `192.168.x.x`)
- **Username**: Local device username (not econet24.com credentials)
- **Password**: Local device password

## InfluxDB & Grafana

For long-term data storage and graphing, install the InfluxDB and Grafana add-ons in Home Assistant. See `ha_config/configuration.yaml` for the InfluxDB integration snippet and `grafana/` for importable dashboard JSON files.

## Architecture

```
HA Server (192.168.x.x)
  ├── econet_grant integration  ←→  ecoNET device (192.168.x.x)
  ├── InfluxDB 2.x (indefinite storage)
  ├── Grafana (graphs & dashboards)
  ├── Automations (notifications, guest checkout, Circuit 1 guardian)
  └── Lovelace Dashboard (controls + embedded Grafana)
```

## Development

### Parameter Mapping

Use `tools/param_mapper.py` to identify unknown API parameters by comparing before/after JSON snapshots:

```bash
python tools/param_mapper.py Reference/before.json Reference/after.json
```

### Safe Mode

During development, enable `safe_mode` in the integration options. All write operations will be queued and require manual approval via HA persistent notifications before being sent to the live system.

## License

MIT
