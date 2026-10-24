"""Constants for the EcoNet Grant Aerona integration."""

from homeassistant.components.sensor import SensorDeviceClass, SensorStateClass
from homeassistant.const import UnitOfTemperature

DOMAIN = "econet_grant"

CONF_HOST = "host"
CONF_USERNAME = "username"
CONF_PASSWORD = "password"
CONF_SAFE_MODE = "safe_mode"
CONF_RETENTION_DAYS = "retention_days"
CONF_PUSH_NOTIFICATIONS = "push_notifications"
CONF_SLOW_POLL_INTERVAL = "slow_poll_interval"

DEFAULT_USERNAME = "admin"
DEFAULT_SAFE_MODE = True
DEFAULT_PUSH_NOTIFICATIONS = True
DATA_RETENTION_DAYS = 3650  # 10 years default

# Companion App service that receives single-use manual Revert actions.
CONF_REVERT_NOTIFY_SERVICE = "revert_notify_service"

SERVICE_BACKUP_SETTINGS = "backup_settings"
SERVICE_RESTORE_SETTINGS = "restore_settings"

DATABASE_FILENAME = "econet_grant.db"
SNAPSHOT_DIR_NAME = "econet_grant_snapshots"

DEVICE_NAME = "Grant Aerona Heat Pump"
DEVICE_MANUFACTURER = "Grant"
DEVICE_MODEL = "Aerona (ecoMAX360i)"

# API endpoint paths (appended to http://<host>/econet/).
# Writes always use newParam by name: this controller reports remoteMenu=false,
# so the index-based rm* endpoints do not work and must not be used.
API_BASE_PATH = "/econet"
API_REG_PARAMS = "regParams"
API_EDIT_PARAMS = "editParams"
API_SYS_PARAMS = "sysParams"
API_NEW_PARAM = "newParam"

# Polling intervals (seconds)
FAST_POLL_INTERVAL = 300  # 5 minutes for temperatures and performance
SLOW_POLL_INTERVAL = 300  # 5 minutes for settings change detection
DEFAULT_SLOW_POLL_MINUTES = SLOW_POLL_INTERVAL // 60
MIN_SLOW_POLL_MINUTES = 5
MAX_SLOW_POLL_MINUTES = 1440

# API retry configuration. Deliberate transport redundancy (also used by manual
# Revert): five total attempts on timeout, requests serialised, and at least
# MIN_REQUEST_GAP seconds after the previous request completes.
API_MAX_RETRIES = 5
API_TIMEOUT = 15  # seconds per attempt
MIN_REQUEST_GAP = 1.0  # minimum seconds between consecutive requests to the controller
COORDINATOR_TIMEOUT = 30  # seconds for one complete poll

# --- Sensor definitions from regParams.curr ---


def _temperature(name: str) -> dict:
    return {
        "name": name,
        "device_class": SensorDeviceClass.TEMPERATURE,
        "unit": UnitOfTemperature.CELSIUS,
        "state_class": SensorStateClass.MEASUREMENT,
    }


def _measurement(name: str, unit: str) -> dict:
    return {
        "name": name,
        "device_class": None,
        "unit": unit,
        "state_class": SensorStateClass.MEASUREMENT,
    }


SENSOR_DEFINITIONS: dict[str, dict] = {
    "GrantOutdoorTemp": _temperature("Outdoor Temperature"),
    "GrantOutgoingTemp": _temperature("Flow Temperature"),
    "GrantReturnTemp": _temperature("Return Temperature"),
    "TempCWU": _temperature("HW Temperature"),
    "Circuit1thermostat": _temperature("CH Thermostat"),
    "TempWthr": _temperature("Weather Temperature"),
    "TempBuforDown": _temperature("Buffer Temp (Lower)"),
    "TempClutch": _temperature("Heat Exchanger Temp"),
    "HeatSourceCalcPresetTemp": _temperature("Heat Source Preset Temp"),
    "GrantCompressorFreq": _measurement("Compressor Frequency", "Hz"),
    "GrantPumpSpeed": _measurement("Pump Speed", "rpm"),
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
# key: API parameter name; param_index: key in editParams.data.

_C = UnitOfTemperature.CELSIUS
_MIN = "min"
_SEC = "s"


def _number(index: str, name: str, min_value, max_value, step, unit) -> dict:
    return {
        "param_index": index,
        "name": name,
        "min_value": min_value,
        "max_value": max_value,
        "step": step,
        "unit": unit,
    }


NUMBER_DEFINITIONS: dict[str, dict] = {
    "Circuit1ComfortTemp": _number("238", "CH Day Temp", 10, 35, 0.1, _C),
    "Circuit1EcoTemp": _number("239", "CH Night Temp", 10, 35, 0.1, _C),
    "Circuit1BaseTemp": _number("261", "CH Base Temp", 25, 60, 1, _C),
    "HDWTSetPoint": _number("103", "HW Set Point", 20, 55, 1, _C),
    "Circuit1DownHist": _number("240", "CH Hysteresis", 0, 5, 0.1, _C),
    "DHWHysteresis": _number("104", "HW Hysteresis", 0, 10, 1, _C),
    "DHWExtensionOfWork": _number("113", "HW Extend Work", 0, 30, 1, _MIN),
    "Circuit1CurveRadiator": _number("273", "CH Curve", 0, 4, 0.1, None),
    "Circuit1Curveshift": _number("275", "CH Curve Shift", -20, 20, 1, _C),
    "Circuit1boosttimeleft": _number("1521", "CH Boost Time", 0, 180, 1, _MIN),
    "Korekta_temperatury": _number("10413", "Panel Temp Correction", -5, 5, 0.1, _C),
    "SummerOn": _number("702", "Summer Threshold", 17, 30, 1, _C),
    "SummerOff": _number("703", "Winter Threshold", 0, 19, 1, _C),
    "HeatSourceTempInc": _number("481", "HW Correction Temp", 0, 20, 1, _C),
    "hSMPTSIncreaseCirc": _number("1402", "Heating Temp Correction", 0, 20, 1, _C),
    "decreaseSetTemp": _number("1054", "Cooling Setpoint Adj", 1, 10, 1, _C),
    "CirculationTempStart": _number("433", "HW Pump Start Temp", 20, 60, 1, _C),
    "circuitCritHeatTempIgnoreTime": _number("1533", "Crit Temp Ignore", 0, 10, 1, _MIN),
    "CirculationTimework": _number("434", "HW Recirc Run Time", 1, 120, 1, _SEC),
    "CirculationTimestop": _number("435", "HW Recirc Pause", 1, 100, 1, _MIN),
    "heatersPermTemp": _number("144", "Outside Temp Start Heater", -20, 20, 1, _C),
    "heatersForceTemp": _number("145", "Outside Temp Force Heater", -20, 20, 1, _C),
    "heaterDhwDel": _number("146", "HW Heater Delay", 0, 240, 1, _MIN),
    "heaterBuffDel": _number("147", "Backup Heater Delay", 0, 240, 1, _MIN),
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
        "name": "CH Operation Mode",
        "options": {
            0: "Off",
            1: "Day",
            2: "Night",
            3: "Schedule",
        },
    },
    "HDWusermode": {
        "param_index": "119",
        "name": "HW Work Mode",
        "options": {
            0: "Off",
            1: "On",
            2: "Schedule",
        },
    },
    "DHWBoost": {
        "param_index": "115",
        "name": "HW Boost",
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
        "name": "CH Circuit Type",
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

def _bit(
    settings_param: str,
    settings_param_name: str,
    bit_mask: int,
    name: str,
    on_label: str = "Yes",
    off_label: str = "No",
) -> dict:
    return {
        "settings_param": settings_param,
        "settings_param_name": settings_param_name,
        "bit_mask": bit_mask,
        "name": name,
        "on_label": on_label,
        "off_label": off_label,
        "on_clears_bit": False,
    }


BITMASK_SELECT_DEFINITIONS: dict[str, dict] = {
    "HDWSpecifyPriority": _bit("101", "HDWSETTINGS", 16, "HW Specify Priority"),
    "ExternalTempSensorSupport": _bit("69", "TempSettings", 1, "Ext Temp Sensor"),
    "TempSensorSource": _bit("69", "TempSettings", 2, "Temp Sensor Source", on_label="Heat Pump", off_label="ecoMulti"),
    "CoolingSupport": _bit("485", "HeatingCooling", 1, "Cooling Support"),
    "HeatPumpLock": _bit("462", "HeatSourceAllowWorkSett", 1, "Heat Pump Lock"),
    "DHWSupport": _bit("101", "HDWSETTINGS", 1, "HW Support"),
    "OffCircuitsDuringCharging": _bit("101", "HDWSETTINGS", 4096, "Off Circuits on HW"),
    "DHWRecirculationSupport": _bit("431", "CirculationSettings", 1, "HW Recirc Support"),
    "DHWStartFromTemp": _bit("431", "CirculationSettings", 2, "HW Start From Temp"),
    "Circuit1ThermostatPumpBlockade": _bit("231", "Circuit1Settings", 1024, "CH Pump Blockade"),
    "BackupHeaterInDefrost": _bit("143", "heatersSett", 16, "Backup Htr in Defrost"),
    "Circuit1RegulationMethod": _bit("231", "Circuit1Settings", 2048, "CH Regulation Method", on_label="Weather", off_label="Fixed"),
    "BackupHeater": _bit("143", "heatersSett", 1, "Backup Heater"),
    "DHWHeater": _bit("143", "heatersSett", 2, "HW Heater"),
}

# Parameters considered "urgent" -- external changes also fire EVENT_URGENT_CHANGE
URGENT_PARAMETERS: set[str] = {
    "Circuit1ComfortTemp",
    "Circuit1EcoTemp",
    "HDWTSetPoint",
}

# Volatile parameters that fluctuate automatically and should be excluded from
# change detection across ALL API endpoints (editParams, sysParams, etc.).
# This is a single master list — do not create per-endpoint volatile lists.
VOLATILE_PARAMETERS: set[str] = {
    "Circuit1boosttimeleft",
    "Circuit2boosttimeleft",
    "Circuit3boosttimeleft",
    "Circuit4boosttimeleft",
    "Circuit5boosttimeleft",
    "Circuit6boosttimeleft",
    "Circuit7boosttimeleft",
    "GrantReg03Float",
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
