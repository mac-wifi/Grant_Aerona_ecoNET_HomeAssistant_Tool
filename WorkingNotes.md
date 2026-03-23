Testing Round 1
Work Mode - X:Winter Y:Auto
Circuit 1 Hystereis - X:0.5c Y:to 0.6
Circuit 1 Operation Mode - X:Day Y:Schedule
DHW preset temp - X:55 Y:49
DHW Work Mode - X:On Y:Schedule

Testing Round 2
Work Mode → Summer (to confirm value 4)
Circuit 1 Operation Mode → Night (to confirm value 2)
DHW Work Mode → Off (to confirm value 0)
DHW Priority: Yes to No
DHW Hysteresis: 5 to 8
DHW Boost:  No to Yes
DHW Extension of work: 0 min to 3 min

Testing Round 3
**System Demand: No to Heat
**Fan speed: 0rpm to 650 or 660
**Main circulation pump: 0rpm to 4000
Circuit 1 Heating Curve: 1.4 to 2.1
Circuiti 1 Heating Curve Shift: 0 to 3

Testing Round 4
Heat Pump Word Mode: On > Schedule (only other possible value is Off)
Circuit 1 Boost Time: 0 > 19 min (could be 18 min, it was counting down) (max 180) 
DHW Specify Priority: Yes > No (only values)
Panel Correction Temp: 0.0 > 0.3c (min -5c, max +5c)

Testing Round 5
DHW Specify Priority: No > Yes
Summer Mode Activation Temp: 19c > 21c
Winter Mode Activation Temp: 17c > 18c
DHW Correction Temp: 5c > 8c
Circuit Temp Correction: 2c > 4c

Testing Round 6
External Temperature Sensor Support: Yes > No → editParams data["69"] TempSettings bit 0 (mask 1): 1=Yes, 0=No
Temp Sensor Source: ecoMulti > Heat Pump → editParams data["69"] TempSettings bit 1 (mask 2): 0=ecoMulti, 1=Heat Pump
Cooling Support: Yes > No → editParams data["485"] HeatingCooling: 1=Yes, 0=No
Heat Pump Lock: No > Yes → editParams data["462"] HeatSourceAllowWorkSett: 0=No, 1=Yes
DHW Support: Yes > No → editParams data["101"] HDWSETTINGS bit 0 (mask 1): 1=Yes, 0=No

Testing Round 7
Hydraulic scheme: Direct > Buffer (3rd option = Low Loss Header) → editParams data["19"] currentSchemat: 0=Direct, 1=Buffer, 2=Low Loss Header
Setpoint temp. correction - cooling: 2c > 5c → editParams data["1054"] decreaseSetTemp: value (min 1, max 10, unit °C)
Off Circuits during charging: Yes > No → editParams data["101"] HDWSETTINGS bit 12 (mask 4096): 1=Yes, 0=No
DHW Recirculation support: Yes > No → editParams data["431"] CirculationSettings bit 0 (mask 1): 1=Yes, 0=No
DHW Start from temp: Yes > No → editParams data["431"] CirculationSettings bit 1 (mask 2): 1=Yes, 0=No
  (Also: data["433"] CirculationTempStart appears/disappears based on this setting; min 20, max 60, unit °C)

Testing Round 8
Circuit crit. temp ignore after DHW: 3 min > 1 min (do not revert) → editParams data["1533"] circuitCritHeatTempIgnoreTime: value (min 0, max 10, unit min)
DHW Recirculation operation time: 20 sec > 29 sec → editParams data["434"] CirculationTimework: value (min 1, max 120, unit sec)
DHW Recirculation pause time: 10 min > 17 min → editParams data["435"] CirculationTimestop: value (min 1, max 100, unit min)
DHW Pump Start Temp: 30c > 39c → editParams data["433"] CirculationTempStart: value (min 20, max 60, unit °C)
Circuit 1 Thermostat pump blockade: Yes > No → editParams data["231"] Circuit1Settings bit 10 (mask 1024): 1=Yes, 0=No

Testing Round 9
Backup Heater operation in defrost: yes > no → editParams data["143"] heatersSett bit 4 (mask 16): 1=Yes, 0=No
Backup heater delay: 30min > 37min → editParams data["147"] heaterBuffDel: value (min 0, max 240, unit min)
DHW heater delay: 15min > 19 min → editParams data["146"] heaterDhwDel: value (min 0, max 240, unit min)
Outside temp start heater: 10c > 12c → editParams data["144"] heatersPermTemp: value (min -20, max 20, unit °C)
Outside temp force heater: -10 > -8c → editParams data["145"] heatersForceTemp: value (min -20, max 20, unit °C)

Testing Round 10
Circuit 1 Circuit Type: Radiators > Fan Coil → editParams data["269"] Circuit1TypeSettings: 1=Radiators, 3=Fan Coil
  (Also: data["231"] Circuit1Settings bit 17 toggles; data["600"] Circuit1Picture tracks same value)
  (Dynamic: data["273"] Circuit1CurveRadiator disappears for Fan Coil; data["586"] MixCirc1HeatCurveFanCoil appears; data["739"] Circuit1MixerCoolBaseTemp appears)
Circuit 1 Regulation Method: Weather > Fixed → editParams data["231"] Circuit1Settings bit 11 (mask 2048): 1=Weather, 0=Fixed
  (Dynamic: data["275"] Circuit1Curveshift and data["586"] MixCirc1HeatCurveFanCoil disappear in Fixed mode)
Circuit 1 Thermostat Pump Blockade: Yes > No → editParams data["231"] Circuit1Settings bit 10 (mask 1024): 1=Yes, 0=No
  (Note: same parameter and bit as Circuit 1 Thermostat Pump Blockade from Round 8 — likely a single setting, not truly separate circuits)
Backup Heater: Yes > No → editParams data["143"] heatersSett bit 0 (mask 1): 1=Yes, 0=No
  (Dynamic: data["144"] heatersPermTemp, ["145"] heatersForceTemp, ["146"] heaterDhwDel, ["147"] heaterBuffDel disappear when No)
DHW Heater: No > Yes → editParams data["143"] heatersSett bit 1 (mask 2): 1=Yes, 0=No
  (Dynamic: data["144"] heatersPermTemp, ["145"] heatersForceTemp reappear; data["1530"] immersionBoosttimeLeft and ["1531"] immersionBoostsettings appear)