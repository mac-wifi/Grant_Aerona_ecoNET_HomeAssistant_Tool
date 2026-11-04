# Changelog

Versions follow `MAJOR.MINOR.PATCH`: PATCH for fixes and small changes, MINOR
for new or changed functionality. Only versions with a GitHub Release were
published; the others were local development candidates.

## 0.8.0 — 2026-11-04

- **Change the controller address without reinstalling.** If the ecoNET
  module gets a new IP address, use **Settings > Devices & services > EcoNet
  Grant Aerona > ⋮ > Reconfigure**. Entities, entity IDs, history, options and
  snapshots are kept. Once the integration has connected at least once, the new
  address must answer as the same controller, or it is refused ("different ecoNET controller"); it also cannot duplicate
  another entry. Spaces around the address are now trimmed when setting up.
  Works even when the entry is stuck retrying because the old address is
  wrong: it reloads straight away instead of waiting for the next retry.

## 0.7.1 — 2026-11-02

- **Restore skips values the controller changes by itself.** With nothing
  changed, the preview listed e.g. `GrantReg03Float: 39.0 -> 38.0`. Restore
  now ignores the same `VOLATILE_PARAMETERS` list that change detection
  ignores (this value and the boost-time-left counters). With Safe Mode off
  it would previously have written them back to the controller.

- **Last Default Snapshot** now updates as soon as a backup completes.
  Previously it kept showing *Unknown* (or the old time) until the next
  5-minute poll. Its snapshot file is now also read off Home Assistant's main
  event loop.

## 0.7.0 — 2026-11-01

- **Restore always reports its outcome.** Previously it finished silently when
  no snapshot existed, when settings already matched the snapshot, when the
  current settings couldn't be read, and after a real (Safe Mode off) restore.
  Each case now produces an "EcoNet Grant - Restore ..." notification. This
  includes connection errors and an unreadable snapshot file. A result clears
  any earlier Safe Mode preview, whose content is otherwise unchanged.
- **New diagnostic sensor *Integration Version*.** It shows the version Home
  Assistant is actually running, so a pending restart after a HACS download is
  visible. The dashboard's Admin › About card now reads it instead of a
  hard-coded (stale "v0.4.0") label. Recopy the dashboard once to pick this up.

## 0.6.6 — 2026-11-01

Bug fixes (each has a regression test that fails on 0.6.5):

- **Restore Default Settings button** never worked: it called
  `restore_settings` with a field the service schema rejects. It now restores
  the `Default` snapshot (a preview only while Safe Mode is on).
- **Bitmask selects** (for example *HW Specify Priority*): the integration's
  own writes were reported as external "Settings changed" alerts and pushes.
- **Writable entities** now update as soon as a settings poll detects a
  change, instead of up to one fast poll (5 minutes) later.

Internal:

- Refactor with no intended behaviour change: shared entity base classes,
  config-entry `runtime_data`, one write path for all writable entities,
  a separate services module and simpler coordinators, database and change
  detector. Integration code shrank by about 20%.
- Removed the unused `rmNewParam`/`rmCurrNewParam` write helpers; writes only
  ever use `newParam` by name.
- Basic authentication no longer uses the `aiohttp.BasicAuth` helper, which is
  deprecated for aiohttp 4.
- New entity-contract test pins every entity ID, unique ID, name, icon, unit
  and device attribute, so a refactor can't silently rename entities.

## 0.6.5 — 2026-10-24

Canonical dashboard promoted from the owner-tested layout; dual-axis
Favourites and Circuit 1 history graphs; HACS dashboard installation
instructions; static dashboard tests. No runtime changes.

## 0.6.3 — 2026-10-17

Deterministic loopback-socket test fixture (fixes the hosted CI failure seen
on 0.6.2). No runtime changes.

## 0.6.2 — 2026-10-12

Documentation corrections (manual Revert attribution, test notes). No runtime
changes. Tagged; hosted CI failed, see 0.6.3.

## 0.6.1 and earlier development candidates

- 0.6.1: human-readable labels in setting-change notifications.
- 0.6.0: opt-in single-use manual **Revert** action notifications, read-only
  export/compare tools, Grafana examples, offline test suite and release
  preflight; HACS minimum Core 2026.9.4.
- 0.5.0: configurable settings (slow) polling interval.
- 0.4.3: write responses validated against the requested name and value.
- 0.4.2: documentation and dashboard packaging.
- 0.4.1: earlier production baseline.
