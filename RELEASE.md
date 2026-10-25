# Releasing, updating and rolling back

Only the owner publishes, from a credentialed local clone. Changes reach
`main` only after the full test suite passes and an independent code review
(done by a separate reviewing agent for this project) approves them. The
owner doesn't need to review code.

## 1. Prepare the release commit

1. Work on a branch from `main`. Run `python -m pytest` (see
   [TESTING.md](TESTING.md)); it must pass with only the strict #11 expected
   failure.
2. Bump `custom_components/econet_grant/manifest.json` once per release:
   PATCH for fixes and small changes, MINOR for new or changed functionality.
3. Move the `Unreleased` entry in [CHANGELOG.md](CHANGELOG.md) under the new
   version and date.
4. Have the change independently reviewed, fix the findings, then merge it
   into `main` with a clean working tree.

## 2. Preflight the exact commit

From the repository root, in the test environment:

```sh
python scripts/release_preflight.py \
  --commit "$(git rev-parse HEAD)" --tag vX.Y.Z --release-version X.Y.Z
```

The preflight refuses a dirty tree, untracked files or tracked bytes that
differ from `HEAD`. It also refuses if the manifest version, tag and release
version don't match exactly. It runs the full suite and repeats the checks
afterwards, and prints `PASS` only if everything held. It checks local state
only: it does not create tags or inspect the remote.

## 3. Publish

1. `git push origin main`, then wait for the **Offline tests** GitHub Actions
   run on that exact commit to succeed.
2. Tag that commit, `git tag vX.Y.Z <commit>`, then run `git push origin vX.Y.Z`.
   Never move or reuse a published tag.
3. Create a GitHub **Release** for the tag, using the changelog entry as the
   notes. HACS offers versions from releases, not bare tags.

## Updating an installation

1. Take a Home Assistant backup. HACS replaces
   `custom_components/econet_grant/`, so local edits there are lost.
2. In HACS, open EcoNet Grant Aerona, use **Update information** if needed,
   then **Download/Redownload** the chosen release.
3. Restart Home Assistant when convenient. Check that the integration loads,
   that Safe Mode is still on, and the entity states and logs. Downloading code
   is not permission to write to the controller.
4. HACS does not update a dashboard you copied into `dashboards/`. Compare it
   with `custom_components/econet_grant/extras/econet_grant_dashboard.yaml`
   and reconcile it deliberately.

## Rolling back

Use HACS **Need a different version?** to install an earlier release, or
replace the whole `custom_components/econet_grant/` directory with a
known-good version (never overlay versions). Then restart.

**Code rollback is not device or data rollback.** It does not undo heat-pump
writes, SQLite contents or retention purges, snapshots, entity configuration
or InfluxDB data. Do not use Restore Default to roll back code. Restore's
marker defect (#11) is still open.

## Support baseline

`hacs.json` requires Home Assistant Core **2026.9.4**, which is the version the
suite tests (`pytest-homeassistant-custom-component==0.13.367`, Python 3.14).
Later Core versions are expected to work but are not verified until the test
pin moves.
