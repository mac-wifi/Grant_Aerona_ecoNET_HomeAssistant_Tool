# Offline development tests

This is the initial, proportionate test foundation for issues #6 and #12, not
exhaustive integration certification. The removed guardian is deliberately not
recreated. Release preparation (#10 / release portion of #12) is separate.

## Setup and one test command

Use Python 3.13 in an isolated environment from the repository root:

```sh
python3.13 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements-test.txt
python -m pytest
```

The single suite command is `python -m pytest`. `pytest.ini` discovers all
`tests/test_*.py` files without a manually maintained list. Dependencies pin the
test baseline to Home Assistant 2025.3.4 and Python 3.13, not the production
installation. The advertised HACS minimum (HA 2024.1) and newer HA versions have
not been verified by this baseline; it does not change the supported minimum.
No test dependency is added to the shipped integration manifest.

On filesystems that cannot run a virtual environment (for example a cloud drive
without executable files/symlinks), create the isolated environment on an
executable local filesystem instead, activate it, and run the same suite command
from the repository root. Do not use `PYTHONPATH` workarounds or install into HA,
system Python or an agent's runtime. Dependency installation needs package-index
access; test execution does not.

## Boundaries and coverage

- Hand-authored reduced JSON fixtures contain synthetic indices/values, not
  controller exports, credentials, device IDs or property/network information.
- Tests import real integration and Home Assistant modules. HA orchestration,
  notifications, sessions and device calls are mocked at the boundary; they do
  not replace the production functions being tested with fake implementations.
- Tests cover external/self-write classification and volatile filtering, Safe
  Mode for number/select/bitmask and restore paths, backup filtering, restore
  no-op/fetch/write failure, basic flow/options/schema decisions and setup/unload
  orchestration, by-name API routing, bitmask read-modify-write (including
  inverted bits), and SQLite persistence in a temporary database.
- `pytest-socket` blocks network sockets during tests. Unix-domain sockets are
  allowed for asyncio's event loop, not device/network access. API calls are
  mocked regardless. No production HA configuration or device is required.
- One narrowly scoped strict xfail documents deferred issue #11 through the
  actual restore service handler: a no-op restore can suppress the next guest
  alert. Only the specific classification/event symptom raises its dedicated
  expected exception. Setup/no-write failures remain failures. An unexpected
  pass fails the suite and requires review; do not remove the marker without
  reviewing #11. This task does not fix restore-marker ownership or expiry.
- No full HA instance is started. Platform lifecycle/listener cleanup, live
  HTTP retry/firmware behavior, all option/auth paths, audit retention/migrations,
  push delivery, every parameter mapping, and concurrent writes remain outside
  this initial suite. It does not prove hardware behavior or complete issue #6.

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
