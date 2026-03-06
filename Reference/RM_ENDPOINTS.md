# ecoNET Remote Menu (RM) API Endpoints

## Summary

The ecoNET controller exposes two generations of API:

1. **Legacy API** -- `regParams`, `editParams`, `sysParams`. Supported by all known ecoNET firmware versions. This is what our integration currently uses.
2. **Remote Menu (RM) API** -- A newer, richer set of endpoints that provide structured parameter metadata, descriptions, enum mappings, units, and hierarchical menu structures. When available, these expose 165+ parameters with full type information.

Our Grant Aerona controller (ecoMAX360i, firmware 3.2.3881) does **not** support the RM API. The `sysParams` response includes `"remoteMenu": false`, which is the definitive indicator.

## Our Controller Details

| Field | Value |
|---|---|
| Controller | ecoMAX360i |
| Protocol | gm3_pomp |
| ecoNET Module Firmware (`softVer`) | 3.2.3881 |
| Panel (`modulePanelSoftVer`) | S004.24_1.22 |
| Module A (`moduleASoftVer`) | S004.29 |
| Router | mr3020-v3 |
| `remoteMenu` flag | **False** |

## Which Devices Support RM?

Based on the [jontofront/ecoNET-300-Home-Assistant-Integration](https://github.com/jontofront/ecoNET-300-Home-Assistant-Integration) project:

- **RM supported**: ecoMAX810P-L TOUCH, ecoMAX850R2-X, ecoMAX860P2-N, ecoMAX860P3-V, and likely other pellet/biomass boiler controllers using the ecoNET-300 module. These are typically Plum Sp. z o.o. heating systems.
- **RM NOT supported**: ecoMAX360 / ecoMAX360i (our controller type), ecoMAX360-cf8, and possibly other heat-pump-specific controllers. Issue [#210](https://github.com/jontofront/ecoNET-300-Home-Assistant-Integration/issues/210) confirmed that ecoMAX860D3-HB on firmware 3.2.3879 also lacks RM support.

The determining factor appears to be the **controller model** rather than firmware version alone. The ecoMAX360i is a heat-pump controller that uses the simpler `gm3_pomp` protocol, while RM-capable controllers use protocols suited to pellet/biomass boilers with more complex parameter trees.

The jontofront project added automatic RM detection (probe with 2-second timeout) in v1.2.1 (Feb 2026) after v1.2.0's RM-dependent code broke installations on legacy-only modules.

## RM Endpoint Catalogue

All endpoints are under `http://<econet_ip>/econet/`. They require the same basic auth as legacy endpoints.

### Read Endpoints

| Endpoint | Purpose |
|---|---|
| `rmCurrentDataParams` | Current live parameter values (similar to `regParams` but structured by the RM menu tree) |
| `rmCurrentDataParamsEdits` | Current values of editable parameters only (similar to `editParams`) |
| `rmParamsData` | Full parameter definitions -- index, value, min, max, type |
| `rmParamsNames` | Human-readable parameter names keyed by index |
| `rmParamsDescs` | Detailed parameter descriptions (supports `?lang=en` query param) |
| `rmParamsEnums` | Enum value mappings for select-type parameters (e.g. mode 0="Off", 1="On") |
| `rmParamsUnitsNames` | Unit labels for parameters (°C, %, rpm, etc.) |
| `rmStructure` | Hierarchical menu structure -- categories, groups, and parameter references |
| `rmLangs` | Language file for the currently selected language |
| `rmExistingLangs` | List of available language codes |
| `rmLocksNames` | Names/descriptions of parameter lock states |
| `rmAlarmsNames` | Alarm code descriptions |
| `regParamsData` | Extended version of `regParams` with additional metadata |

### Write Endpoints

| Endpoint | Purpose |
|---|---|
| `rmNewParam` | Set a parameter by index: `?uid=<uid>&newParamIndex=<idx>&newParamValue=<val>` |
| `rmCurrNewParam` | Set a "current" parameter by key: `?uid=<uid>&newParamKey=<key>&newParamValue=<val>` |
| `rmAccess` | Authenticate with the service password to unlock protected parameters |

## How the jontofront Integration Uses RM

When RM is available, the jontofront integration:

1. Probes `rmParamsData` with a 2-second timeout on first poll
2. If RM is detected, fetches `rmCurrentDataParams`, `rmParamsNames`, `rmParamsData`, and `rmLangs` as core data
3. Builds a `mergedData` structure that combines parameter values, names, limits, and enums
4. Dynamically creates HA entities (Number, Switch, Select, Sensor) from the merged data
5. Uses `rmNewParam` for writes (same as our `set_param_by_index` approach)

When RM is NOT detected, it falls back to `regParams` + `editParams` + `sysParams` only -- which is essentially what our integration does.

## How to Check if RM Becomes Available

If a future firmware update enables RM on the ecoMAX360i:

1. Check `sysParams` -- look for `"remoteMenu": true`
2. Or manually try: `curl -u admin:PASSWORD http://192.168.1.6/econet/rmParamsData`
   - If it returns JSON with a `"data"` key: RM is supported
   - If it errors (e.g. `'CommThread' object has no attribute 'getRemoteMenuParams'`): still legacy-only

The `tools/pull_exports.sh` script already attempts all RM endpoints and reports SKIP for those that fail, so running an export after any firmware update will immediately show whether RM has become available.

## Why This Matters

If RM were available, we would get:
- Full parameter metadata (names, units, min/max, enums) directly from the controller
- No need for manual before/after testing to discover parameter indices
- Automatic entity creation for all exposed parameters
- Proper enum mappings for select entities instead of hardcoded option lists

Until then, our integration correctly uses the legacy `editParams` endpoint for both reading settings and writing them via `set_param_by_index`, which hits the same underlying parameter store.

## Source

- jontofront integration repo: https://github.com/jontofront/ecoNET-300-Home-Assistant-Integration
- Relevant issue (legacy detection): https://github.com/jontofront/ecoNET-300-Home-Assistant-Integration/issues/210
- RM endpoint constants defined in: `custom_components/econet300/const.py` of that repo
- RM probe logic in: `custom_components/econet300/api.py` (`probe_rm_support()`)
- Coordinator fallback in: `custom_components/econet300/common.py` (`_async_update_data()`)
