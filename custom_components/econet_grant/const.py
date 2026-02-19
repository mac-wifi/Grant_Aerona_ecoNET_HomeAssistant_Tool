"""Constants for the EcoNet Grant Aerona integration."""

from homeassistant.components.sensor import SensorDeviceClass, SensorStateClass
from homeassistant.const import UnitOfTemperature

DOMAIN = "econet_grant"

CONF_HOST = "host"
CONF_USERNAME = "username"
CONF_PASSWORD = "password"
CONF_SAFE_MODE = "safe_mode"

DEFAULT_USERNAME = "admin"
DEFAULT_SAFE_MODE = True

SERVICE_COORDINATOR = "coordinator"
SERVICE_SLOW_COORDINATOR = "slow_coordinator"
SERVICE_API = "api"

DEVICE_MANUFACTURER = "Grant"
DEVICE_MODEL = "Aerona (ecoMAX360i)"

# API endpoint paths (appended to http://<host>/econet/)
API_BASE_PATH = "/econet"
API_REG_PARAMS = "regParams"
API_EDIT_PARAMS = "editParams"
API_SYS_PARAMS = "sysParams"
API_NEW_PARAM = "newParam"
API_RM_NEW_PARAM = "rmNewParam"
API_RM_CURR_NEW_PARAM = "rmCurrNewParam"

# Polling intervals (seconds)
FAST_POLL_INTERVAL = 300  # 5 minutes for temperatures and performance
SLOW_POLL_INTERVAL = 86400  # 24 hours for system settings

# API retry configuration
API_MAX_RETRIES = 5
API_RETRY_DELAY = 1  # seconds
API_TIMEOUT = 15  # seconds

# --- Sensor definitions from regParams.curr ---
# Each entry: (key_in_api, friendly_name, device_class, unit, state_class)

SENSOR_DEFINITIONS: dict[str, dict] = {
    "GrantOutdoorTemp": {
        "name": "Outdoor Temperature",
        "device_class": SensorDeviceClass.TEMPERATURE,
        "unit": UnitOfTemperature.CELSIUS,
        "state_class": SensorStateClass.MEASUREMENT,
    },
    "GrantOutgoingTemp": {
        "name": "Flow Temperature",
        "device_class": SensorDeviceClass.TEMPERATURE,
        "unit": UnitOfTemperature.CELSIUS,
        "state_class": SensorStateClass.MEASUREMENT,
    },
    "GrantReturnTemp": {
        "name": "Return Temperature",
        "device_class": SensorDeviceClass.TEMPERATURE,
        "unit": UnitOfTemperature.CELSIUS,
        "state_class": SensorStateClass.MEASUREMENT,
    },
    "TempCWU": {
        "name": "DHW Temperature",
        "device_class": SensorDeviceClass.TEMPERATURE,
        "unit": UnitOfTemperature.CELSIUS,
        "state_class": SensorStateClass.MEASUREMENT,
    },
    "Circuit1thermostat": {
        "name": "Circuit 1 Thermostat",
        "device_class": SensorDeviceClass.TEMPERATURE,
        "unit": UnitOfTemperature.CELSIUS,
        "state_class": SensorStateClass.MEASUREMENT,
    },
    "TempWthr": {
        "name": "Weather Temperature",
        "device_class": SensorDeviceClass.TEMPERATURE,
        "unit": UnitOfTemperature.CELSIUS,
        "state_class": SensorStateClass.MEASUREMENT,
    },
    "TempBuforDown": {
        "name": "Buffer Temperature (Lower)",
        "device_class": SensorDeviceClass.TEMPERATURE,
        "unit": UnitOfTemperature.CELSIUS,
        "state_class": SensorStateClass.MEASUREMENT,
    },
    "TempClutch": {
        "name": "Heat Exchanger Temperature",
        "device_class": SensorDeviceClass.TEMPERATURE,
        "unit": UnitOfTemperature.CELSIUS,
        "state_class": SensorStateClass.MEASUREMENT,
    },
    "HeatSourceCalcPresetTemp": {
        "name": "Heat Source Preset Temperature",
        "device_class": SensorDeviceClass.TEMPERATURE,
        "unit": UnitOfTemperature.CELSIUS,
        "state_class": SensorStateClass.MEASUREMENT,
    },
    "GrantCompressorFreq": {
        "name": "Compressor Frequency",
        "device_class": None,
        "unit": "Hz",
        "state_class": SensorStateClass.MEASUREMENT,
    },
    "GrantPumpSpeed": {
        "name": "Pump Speed",
        "device_class": None,
        "unit": None,
        "state_class": SensorStateClass.MEASUREMENT,
    },
    "GrantWorkState": {
        "name": "Work State",
        "device_class": None,
        "unit": None,
        "state_class": None,
    },
}

# --- Writable number entities (from editParams.data) ---
# key: param index in editParams, name in editParams, friendly name, min, max, unit
# These are the parameters the user explicitly wants to control.

NUMBER_DEFINITIONS: dict[str, dict] = {
    "Circuit1ComfortTemp": {
        "param_index": "238",
        "name": "Circuit 1 Comfort Temperature",
        "min_value": 10,
        "max_value": 35,
        "step": 0.1,
        "unit": UnitOfTemperature.CELSIUS,
    },
    "Circuit1EcoTemp": {
        "param_index": "239",
        "name": "Circuit 1 Eco Temperature",
        "min_value": 10,
        "max_value": 35,
        "step": 0.1,
        "unit": UnitOfTemperature.CELSIUS,
    },
    "Circuit1BaseTemp": {
        "param_index": "261",
        "name": "Circuit 1 Base Temperature",
        "min_value": 25,
        "max_value": 60,
        "step": 1,
        "unit": UnitOfTemperature.CELSIUS,
    },
    "HDWTSetPoint": {
        "param_index": "103",
        "name": "DHW Set Point",
        "min_value": 20,
        "max_value": 55,
        "step": 1,
        "unit": UnitOfTemperature.CELSIUS,
    },
}

# Parameters considered "urgent" -- external changes trigger SMS/WhatsApp alerts
URGENT_PARAMETERS: set[str] = {
    "Circuit1ComfortTemp",
    "Circuit1EcoTemp",
    "HDWTSetPoint",
}

# Events fired by the integration
EVENT_SETTING_CHANGED = f"{DOMAIN}_setting_changed"
EVENT_URGENT_CHANGE = f"{DOMAIN}_urgent_change"
