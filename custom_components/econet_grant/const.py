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
API_TIMEOUT = 15  # seconds
MIN_REQUEST_GAP = 1.0  # minimum seconds between consecutive requests to the controller

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
        "name": "Heating Thermostat",
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
        "unit": "rpm",
        "state_class": SensorStateClass.MEASUREMENT,
    },
    "GrantWorkState": {
        "name": "Work State",
        "device_class": None,
        "unit": None,
        "state_class": None,
        "value_map": {0: "Off", 1: "On"},
    },
}

# --- Sensors from regParams.tilesParams / schemaParams ---
# These read from non-curr sections of the regParams response.
# Each entry specifies a source path within the regParams JSON.

TILES_SENSOR_DEFINITIONS: dict[str, dict] = {
    "FanSpeed": {
        "name": "Fan Speed",
        "device_class": None,
        "unit": "rpm",
        "state_class": SensorStateClass.MEASUREMENT,
        "source": "tilesParams",
        "tile_index": 3,
    },
    "SystemDemand": {
        "name": "System Demand",
        "device_class": None,
        "unit": None,
        "state_class": None,
        "source": "schemaParams",
        "schema_key": "reakcja_termostat1",
        "value_map": {"Grzej": "Heat", "Nie grzej": "No Demand"},
    },
}

# --- Writable number entities (from editParams.data) ---
# key: param index in editParams, name in editParams, friendly name, min, max, unit
# These are the parameters the user explicitly wants to control.

NUMBER_DEFINITIONS: dict[str, dict] = {
    "Circuit1ComfortTemp": {
        "param_index": "238",
        "name": "Heating Day Temperature",
        "min_value": 10,
        "max_value": 35,
        "step": 0.1,
        "unit": UnitOfTemperature.CELSIUS,
    },
    "Circuit1EcoTemp": {
        "param_index": "239",
        "name": "Heating Night Temperature",
        "min_value": 10,
        "max_value": 35,
        "step": 0.1,
        "unit": UnitOfTemperature.CELSIUS,
    },
    "Circuit1BaseTemp": {
        "param_index": "261",
        "name": "Heating Base Temperature",
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
    "Circuit1DownHist": {
        "param_index": "240",
        "name": "Heating Hysteresis",
        "min_value": 0,
        "max_value": 5,
        "step": 0.1,
        "unit": UnitOfTemperature.CELSIUS,
    },
    "DHWHysteresis": {
        "param_index": "104",
        "name": "DHW Hysteresis",
        "min_value": 0,
        "max_value": 10,
        "step": 1,
        "unit": UnitOfTemperature.CELSIUS,
    },
    "DHWExtensionOfWork": {
        "param_index": "113",
        "name": "DHW Extension of Work",
        "min_value": 0,
        "max_value": 30,
        "step": 1,
        "unit": "min",
    },
    "Circuit1CurveRadiator": {
        "param_index": "273",
        "name": "Heating Curve",
        "min_value": 0,
        "max_value": 4,
        "step": 0.1,
        "unit": None,
    },
    "Circuit1Curveshift": {
        "param_index": "275",
        "name": "Heating Curve Shift",
        "min_value": -20,
        "max_value": 20,
        "step": 1,
        "unit": UnitOfTemperature.CELSIUS,
    },
}

# --- Writable select entities (mode selectors from editParams.data) ---
# key: param name, param_index, friendly name, options mapping {api_value: label}
# Values confirmed via before/after iOS app comparison on 2026-02-25 and 2026-02-28.

SELECT_DEFINITIONS: dict[str, dict] = {
    "workState2": {
        "param_index": "162",
        "name": "Work Mode",
        "options": {
            1: "Summer",
            2: "Winter",
            6: "Auto",
        },
    },
    "Circuit1WorkState": {
        "param_index": "236",
        "name": "Heating Operation Mode",
        "options": {
            0: "Off",
            1: "Day",
            2: "Night",
            3: "Schedule",
        },
    },
    "HDWusermode": {
        "param_index": "119",
        "name": "DHW Work Mode",
        "options": {
            0: "Off",
            1: "On",
            2: "Schedule",
        },
    },
    "DHWBoost": {
        "param_index": "115",
        "name": "DHW Boost",
        "options": {
            0: "Off",
            1: "On",
        },
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
