# Tests

## Run

Use Python 3.14 (3.14.2 or later) in an isolated environment on a normal local
disk. A cloud-synced folder that can't hold executables won't work.

```sh
python3.14 -m venv .venv && . .venv/bin/activate
python -m pip install -r requirements-test.txt
python -m pytest
```

`requirements-test.txt` pins Home Assistant Core 2026.9.4 through
`pytest-homeassistant-custom-component`. GitHub Actions
(`.github/workflows/tests.yml`) runs the same command on every push and pull
request.

Expected result: everything passes except one **strict expected failure** for
deferred issue #11, where a no-op Restore can suppress the next guest alert.
If that test unexpectedly passes, the suite fails, so #11 gets reviewed
rather than silently "fixed".

## What the suite covers

- **Real Home Assistant + emulator** (`test_ha_integration.py`,
  `test_revert.py`, `test_entity_contract.py`): a real HA test instance loads
  the config entry and all platforms. It talks over loopback HTTP to
  `tests/emulator.py`, a small stateful ecoNET emulator (regParams,
  editParams, sysParams and by-name `newParam`). These tests cover setup and
  unload, options reload, guest-change detection and notifications, Safe Mode,
  own-write classification, manual Revert, the Restore button and entity
  freshness.
- **Entity contract** (`fixtures/entity_contract.json`): every entity ID,
  unique ID, name, icon, unit, category and device attribute. Entity IDs feed
  dashboards, Grafana and history, so an accidental rename fails the suite.
  Regenerate it only for an intended change, then review the diff:
  `ECONET_UPDATE_CONTRACT=1 python -m pytest tests/test_entity_contract.py`.
- **Focused unit tests**: API retries and write-response validation, change
  classification and volatile filtering, bitmask read-modify-write, backup and
  restore, config and options flows, coordinators, SQLite storage, export
  tools, Grafana examples, dashboards and the release preflight.

The emulator fixtures are reduced, sanitised samples. They keep real
parameter names, indices and response shapes; values and identities are
synthetic. The suite does not prove firmware behaviour, phone push delivery,
frontend rendering or HAOS specifics.

## Network policy

`pytest-socket` blocks network access by default. Emulator tests opt in with
the function-scoped `loopback_sockets` fixture, which allows TCP to numeric
`127.0.0.1` only and blocks it again afterwards. Don't replace it with
`enable_socket` or `allow_hosts` markers: their interaction with the HA plugin
depends on plugin load order, and that broke hosted CI for 0.6.2.
`test_socket_policy.py` checks both plugin orders.

## Conventions

- Fix a bug by first adding a test that fails, then making it pass.
- Behaviour that touches controller writes, change detection,
  `VOLATILE_PARAMETERS`, notifications, Safe Mode, Restore or Revert needs a
  real-HA/emulator test, not just a mock.
- Never point tests at a real controller, VM or production HA.
