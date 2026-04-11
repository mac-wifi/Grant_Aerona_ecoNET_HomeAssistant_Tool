"""Constants for the EcoNet Grant Aerona integration."""

from homeassistant.components.sensor import SensorDeviceClass, SensorStateClass
from homeassistant.const import UnitOfTemperature

DOMAIN = "econet_grant"

CONF_HOST = "host"
CONF_USERNAME = "username"
CONF_PASSWORD = "password"
CONF_SAFE_MODE = "safe_mode"
CONF_RETENTION_DAYS = "retention_days"

DEFAULT_USERNAME = "admin"
DEFAULT_SAFE_MODE = True
DATA_RETENTION_DAYS = 3650  # 10 years default

SERVICE_COORDINATOR = "coordinator"
SERVICE_SLOW_COORDINATOR = "slow_coordinator"
SERVICE_API = "api"
SERVICE_DATABASE = "database"

DATABASE_FILENAME = "econet_grant.db"

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
        "value_map": {
            "Grzej": "Heating",
            "Nie grzej": "No Demand",
            "Heating": "Heating",
            "No Demand": "No Demand",
        },
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
    "Circuit1boosttimeleft": {
        "param_index": "1521",
        "name": "Circuit 1 Boost Time",
        "min_value": 0,
        "max_value": 180,
        "step": 1,
        "unit": "min",
    },
    "Korekta_temperatury": {
        "param_index": "10413",
        "name": "Panel Temperature Correction",
        "min_value": -5,
        "max_value": 5,
        "step": 0.1,
        "unit": UnitOfTemperature.CELSIUS,
    },
    "SummerOn": {
        "param_index": "702",
        "name": "Summer Mode Activation Temperature",
        "min_value": 17,
        "max_value": 30,
        "step": 1,
        "unit": UnitOfTemperature.CELSIUS,
    },
    "SummerOff": {
        "param_index": "703",
        "name": "Winter Mode Activation Temperature",
        "min_value": 0,
        "max_value": 19,
        "step": 1,
        "unit": UnitOfTemperature.CELSIUS,
    },
    "HeatSourceTempInc": {
        "param_index": "481",
        "name": "DHW Correction Temperature",
        "min_value": 0,
        "max_value": 20,
        "step": 1,
        "unit": UnitOfTemperature.CELSIUS,
    },
    "hSMPTSIncreaseCirc": {
        "param_index": "1402",
        "name": "Heating Temperature Correction",
        "min_value": 0,
        "max_value": 20,
        "step": 1,
        "unit": UnitOfTemperature.CELSIUS,
    },
    "decreaseSetTemp": {
        "param_index": "1054",
        "name": "Setpoint Temperature Correction - Cooling",
        "min_value": 1,
        "max_value": 10,
        "step": 1,
        "unit": UnitOfTemperature.CELSIUS,
    },
    "CirculationTempStart": {
        "param_index": "433",
        "name": "DHW Pump Start Temp",
        "min_value": 20,
        "max_value": 60,
        "step": 1,
        "unit": UnitOfTemperature.CELSIUS,
    },
    "circuitCritHeatTempIgnoreTime": {
        "param_index": "1533",
        "name": "Heating Crit Temp Ignore After DHW",
        "min_value": 0,
        "max_value": 10,
        "step": 1,
        "unit": "min",
    },
    "CirculationTimework": {
        "param_index": "434",
        "name": "DHW Recirculation Operation Time",
        "min_value": 1,
        "max_value": 120,
        "step": 1,
        "unit": "s",
    },
    "CirculationTimestop": {
        "param_index": "435",
        "name": "DHW Recirculation Pause Time",
        "min_value": 1,
        "max_value": 100,
        "step": 1,
        "unit": "min",
    },
    "heatersPermTemp": {
        "param_index": "144",
        "name": "Outside Temp Start Heater",
        "min_value": -20,
        "max_value": 20,
        "step": 1,
        "unit": UnitOfTemperature.CELSIUS,
    },
    "heatersForceTemp": {
        "param_index": "145",
        "name": "Outside Temp Force Heater",
        "min_value": -20,
        "max_value": 20,
        "step": 1,
        "unit": UnitOfTemperature.CELSIUS,
    },
    "heaterDhwDel": {
        "param_index": "146",
        "name": "DHW Heater Delay",
        "min_value": 0,
        "max_value": 240,
        "step": 1,
        "unit": "min",
    },
    "heaterBuffDel": {
        "param_index": "147",
        "name": "Backup Heater Delay",
        "min_value": 0,
        "max_value": 240,
        "step": 1,
        "unit": "min",
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
    "GrantWorkState": {
        "param_index": "1133",
        "name": "Heat Pump Mode",
        "options": {
            0: "Off",
            1: "On",
            2: "Schedule",
        },
    },
    "currentSchemat": {
        "param_index": "19",
        "name": "Hydraulic Scheme",
        "options": {
            0: "Direct",
            1: "Buffer",
            2: "Low Loss Header",
        },
    },
    "Circuit1TypeSettings": {
        "param_index": "269",
        "name": "Heating Circuit Type",
        "options": {
            1: "Radiators",
            3: "Fan Coil",
        },
    },
}

# --- Bitmask toggle selects (Yes/No toggles within a settings bitmask) ---
# These operate on a single bit within a larger settings parameter.
# The select reads the bit state and writes the full param with the bit toggled.
# key: friendly key, settings_param: data key holding the bitmask,
# bit_mask: the bit to toggle, on_label/off_label: display labels,
# on_clears_bit: True if "On/Yes" means the bit should be CLEAR (inverted logic).

BITMASK_SELECT_DEFINITIONS: dict[str, dict] = {
    "HDWSpecifyPriority": {
        "settings_param": "101",
        "bit_mask": 16,
        "name": "DHW Specify Priority",
        "on_label": "Yes",
        "off_label": "No",
        "on_clears_bit": False,
    },
    "ExternalTempSensorSupport": {
        "settings_param": "69",
        "bit_mask": 1,
        "name": "External Temperature Sensor Support",
        "on_label": "Yes",
        "off_label": "No",
        "on_clears_bit": False,
    },
    "TempSensorSource": {
        "settings_param": "69",
        "bit_mask": 2,
        "name": "Temperature Sensor Source",
        "on_label": "Heat Pump",
        "off_label": "ecoMulti",
        "on_clears_bit": False,
    },
    "CoolingSupport": {
        "settings_param": "485",
        "bit_mask": 1,
        "name": "Cooling Support",
        "on_label": "Yes",
        "off_label": "No",
        "on_clears_bit": False,
    },
    "HeatPumpLock": {
        "settings_param": "462",
        "bit_mask": 1,
        "name": "Heat Pump Lock",
        "on_label": "Yes",
        "off_label": "No",
        "on_clears_bit": False,
    },
    "DHWSupport": {
        "settings_param": "101",
        "bit_mask": 1,
        "name": "DHW Support",
        "on_label": "Yes",
        "off_label": "No",
        "on_clears_bit": False,
    },
    "OffCircuitsDuringCharging": {
        "settings_param": "101",
        "bit_mask": 4096,
        "name": "Off Circuits During Charging",
        "on_label": "Yes",
        "off_label": "No",
        "on_clears_bit": False,
    },
    "DHWRecirculationSupport": {
        "settings_param": "431",
        "bit_mask": 1,
        "name": "DHW Recirculation Support",
        "on_label": "Yes",
        "off_label": "No",
        "on_clears_bit": False,
    },
    "DHWStartFromTemp": {
        "settings_param": "431",
        "bit_mask": 2,
        "name": "DHW Start From Temp",
        "on_label": "Yes",
        "off_label": "No",
        "on_clears_bit": False,
    },
    "Circuit1ThermostatPumpBlockade": {
        "settings_param": "231",
        "bit_mask": 1024,
        "name": "Heating Thermostat Pump Blockade",
        "on_label": "Yes",
        "off_label": "No",
        "on_clears_bit": False,
    },
    "BackupHeaterInDefrost": {
        "settings_param": "143",
        "bit_mask": 16,
        "name": "Backup Heater Operation in Defrost",
        "on_label": "Yes",
        "off_label": "No",
        "on_clears_bit": False,
    },
    "Circuit1RegulationMethod": {
        "settings_param": "231",
        "bit_mask": 2048,
        "name": "Heating Regulation Method",
        "on_label": "Weather",
        "off_label": "Fixed",
        "on_clears_bit": False,
    },
    "BackupHeater": {
        "settings_param": "143",
        "bit_mask": 1,
        "name": "Backup Heater",
        "on_label": "Yes",
        "off_label": "No",
        "on_clears_bit": False,
    },
    "DHWHeater": {
        "settings_param": "143",
        "bit_mask": 2,
        "name": "DHW Heater",
        "on_label": "Yes",
        "off_label": "No",
        "on_clears_bit": False,
    },
}

# Parameters considered "urgent" -- external changes trigger SMS/WhatsApp alerts
URGENT_PARAMETERS: set[str] = {
    "Circuit1ComfortTemp",
    "Circuit1EcoTemp",
    "HDWTSetPoint",
}

# Volatile editParams that change automatically (boost timers count down)
VOLATILE_PARAMETERS: set[str] = {
    "Circuit1boosttimeleft",
    "Circuit2boosttimeleft",
    "Circuit3boosttimeleft",
    "Circuit4boosttimeleft",
    "Circuit5boosttimeleft",
    "Circuit6boosttimeleft",
    "Circuit7boosttimeleft",
}

# Volatile sysParams fields that fluctuate constantly (ignore for change detection)
VOLATILE_SYS_PARAMS: set[str] = {
    "signal",
    "quality",
}

# sysParams fields that should never change -- alert as critical if they do
CRITICAL_SYS_PARAMS: set[str] = {
    "controllerID",
    "uid",
}

# Events fired by the integration
EVENT_SETTING_CHANGED = f"{DOMAIN}_setting_changed"
EVENT_URGENT_CHANGE = f"{DOMAIN}_urgent_change"
EVENT_SYS_PARAM_CHANGED = f"{DOMAIN}_sys_param_changed"
