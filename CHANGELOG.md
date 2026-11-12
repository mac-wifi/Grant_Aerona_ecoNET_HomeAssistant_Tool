# Changelog

Versions follow `MAJOR.MINOR.PATCH`: PATCH for fixes and small changes, MINOR
for new or changed functionality. Only versions with a GitHub Release were
published; the others were local development candidates.

## 0.11.0 — 2026-11-12

- **Tests now run on Home Assistant 2026.10.4** (was 2026.9.4), the newest
  version the test harness supports; the suite also passes on 2026.9.4 and,
  checked by hand, on 2026.11.1. This exposed two device-registry calls that
  Home Assistant has deprecated (they would stop working in 2027.8 and
  2027.10); both are replaced, with no change in behaviour.
- **Phone alerts while the heat pump can't be reached.** Once the
  controller has been unreachable for 10 minutes, the phone set for Revert
  buttons gets a time-sensitive alert, repeated about every hour until it
  answers again, then a "back online" message. On iPhone, a Live Activity
  on the lock screen also counts the time it has been down (needs the Home
  Assistant app's beta Live Activities). The option is now labelled "Phone
  for Revert buttons and outage alerts"; no setting changes are needed if a
  Revert phone is already set.
- **Fix: automatic address follow now keeps trying.** If the module
  restarted and took a new address before its web server was ready, the
  first attempt to switch failed and was never retried, because Home
  Assistant reports a new address only once. The integration then kept
  polling the old address until the address was changed by hand. Now, after
  every failed poll and every failed setup, it tries the saved address again
  and then the address where Home Assistant last saw the module, with the
  same safety checks, until the switch succeeds. A successful switch is now
  written to the Home Assistant log as a warning so it is visible there.
- **Docs follow Home Assistant 2026.11.** HACS is now the built-in
  **Marketplace** (Settings > Marketplace). The README, release notes and
  dashboard header now give the Marketplace steps (Add from link, Install,
  Settings > Updates, Install another version) and keep a short HACS note for
  Core 2026.9.4 to 2026.10. The entity naming change is noted: entity IDs are
  unchanged, only displayed names differ. No integration behaviour changed.

## 0.10.0 — 2026-11-05

- **Follows the controller to a new IP automatically.** The integration now
  learns the module's MAC address. If the router gives the module a new
  address, Home Assistant's DHCP discovery notices, and the integration
  switches only when the old address has stopped answering, and only after
  logging in at the new address and confirming it is the same controller. It
  never sends the login to a new address while the controller still answers at
  the old one. It then posts a notification and changes no heat-pump
  setting. Addresses saved as DNS names, or on another subnet, still need
  Reconfigure.

## 0.9.0 — 2026-11-05

- **Change the login as well as the address.** **Reconfigure** now also takes
  the username and password; leave the password blank to keep the saved one.
- **Re-authenticate.** If the controller rejects the saved login, Home
  Assistant now offers a Re-authenticate prompt to enter the current one.
- **Repairs "Fix" button.** After the controller has been unreachable for 10
  minutes, Settings > Repairs shows a Fix button to enter a new address or
  login. It clears itself once the controller answers again, including when
  the controller answers by rejecting the login.
- **Controller Address sensor.** A new diagnostic sensor shows the saved
  address (never the login).
- **Dashboard Connection card.** The Admin tab shows the saved address, a
  "not reachable" notice and buttons to Reconfigure and Repairs. Recopy the
  dashboard file to get it (README Step 7b).

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
