# Offline development tests

This is the initial, proportionate test foundation for issues #6 and #12, not
exhaustive integration certification. The removed guardian is deliberately not
recreated. Release preparation (#10 / release portion of #12) is separate.

## Setup and one test command

Use Python 3.14.2 or later in the 3.14 series in an isolated environment from the
repository root (locally verified with Python 3.14.8):

```sh
python3.14 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements-test.txt
python -m pytest
```

The single suite command is `python -m pytest`. `pytest.ini` discovers all
`tests/test_*.py` files without a manually maintained list. Dependencies pin the
test baseline to Home Assistant 2026.9.4 through
`pytest-homeassistant-custom-component==0.13.367`. Its distribution metadata
requires exactly HA 2026.9.4, matching the owner-reported production Core version.
This runs Core in a test process, not HAOS 18.3 or the production installation.
The advertised HACS minimum (HA 2024.1) and other HA versions have not been
verified by this baseline; it does not change the supported minimum.
No test dependency is added to the shipped integration manifest.

On filesystems that cannot run a virtual environment (for example a cloud drive
without executable files/symlinks), create the isolated environment on an
executable local filesystem instead, activate it, and run the same suite command
from the repository root. Do not use `PYTHONPATH` workarounds or install into HA,
system Python or an agent's runtime. Dependency installation needs package-index
access; test execution does not.

## Boundaries and coverage

- The emulator fixtures are reduced from local reference samples
  `regParams_Output.json`, `editParams_Output.json`, `sysParams_Output.json` and
  `newParam_success_sample.json`. Parameter names, numeric indices and response
  shapes are retained; values/version counters and identities are synthetic.
  Network, serial and credential fields are omitted. No original exports ship.
- Existing focused tests import real integration and HA modules with small
  boundary mocks. The official HA fixture also provides their helper lifecycle.
  `test_ha_integration.py` instead starts a real HA test instance, loads the
  config entry and all four platforms, unloads them, submits an options flow
  with reload, and exercises guest settingsVer detection and persistent
  notifications plus Safe Mode through real number/select services. These paths
  do not mock setup, coordinators, notifications or the HTTP client.
- `tests/emulator.py` serves loopback HTTP GET endpoints for regParams,
  editParams, sysParams and by-name newParam. Successful writes mutate editParams
  and increment settingsVer. Tests exercise name/value mismatch, non-OK result,
  malformed JSON, HTTP error and timeout modes. Malformed JSON currently raises
  JSONDecodeError from the client; this documents its behavior, not a claim of
  graceful handling. Timeout duration is shortened for tests; this is not a
  firmware simulator or a complete controller parameter map.
- Tests cover external/self-write classification and volatile filtering, Safe
  Mode for number/select/bitmask and restore paths, backup filtering, restore
  no-op/fetch/write failure, basic flow/options/schema decisions and setup/unload
  orchestration, by-name API routing, bitmask read-modify-write (including
  inverted bits), and SQLite persistence in a temporary database.
- `pytest-socket` blocks network sockets by default. Unix-domain sockets are
  allowed for asyncio. Only the two emulator test modules enable TCP with an
  allowlist containing numeric `127.0.0.1`; a test verifies that non-loopback
  connections remain blocked before network I/O. No device/VM/production
  endpoint or production HA configuration is used.
- One narrowly scoped strict xfail documents deferred issue #11 through the
  actual restore service handler: a no-op restore can suppress the next guest
  alert. Only the specific classification/event symptom raises its dedicated
  expected exception. Setup/no-write failures remain failures. An unexpected
  pass fails the suite and requires review; do not remove the marker without
  reviewing #11. This task does not fix restore-marker ownership or expiry.
- Physical firmware behavior, all option/auth paths, audit retention/migrations,
  actual mobile push delivery, every parameter mapping, frontend behavior and
  concurrent writes remain outside this suite. It does not prove hardware
  behavior or complete every aspect of issue #6. Deferred #11 is unchanged.

## Development convention and CI

Save relevant regression tests in `tests/test_*.py` when changing behavior and
run `python -m pytest` during development and before submission. Tests do not
run automatically after every local edit. Temporary manual checks are not
permanent tests, and discovery cannot guarantee adequate coverage. Prefer a
small behavioral test to a coverage-percentage target.

`.github/workflows/tests.yml` runs the same command on pushes and pull requests,
with read-only repository permissions and no deployment steps. The suite parses
and checks its triggers, dependency setup and test command locally; this is not
a GitHub Actions execution or full Actions schema validation. Hosted execution
is unverified until publication and an actual run are authorised.

The socket guard, test discovery and strict xfail are executable controls.
Running tests before submission/release is an instruction, not an enforced
publication gate: no repository protection settings or release automation are
changed here. Reuse this command against the exact intended release commit in
the separate release procedure. HACS distribution and owner-controlled updates
remain unchanged; no release, production update or heating change is performed
by this workflow.
