# Local release preparation and owner-controlled updates

This procedure prepares a local candidate. It does **not** commit, publish, create a tag,
merge, push, install into HA or change heating settings. Those actions require
separate owner approval. A local `PASS` is not a release or a production sign-off.

## Proposed version and reconciliation

The proposed manifest/release version is **0.6.5**, with proposed tag **v0.6.5**.
This combined candidate supersedes the unreleased 0.6.4-only scope and its graph
exclusions. The owner authorised a local commit after independent review, but
this preparation/reviewer must not stage or commit automatically. Execution of
that conditional commit remains owner-controlled; push, tag, release and deployment
are not authorised.
This is a dashboard/documentation PATCH after published 0.6.3, not a runtime
change. The owner confirmed the corrected live dashboard was good and requested
canonical promotion. That is owner-reported validation of the input, not new
agent testing of HA, phones or Grafana rendering.

The candidate preserves six tabs and the owner's existing registry IDs (including
`heating_*` and `dhw_*`), corrects entity references and leaves Guest as an
explanatory note without checkout helpers or actions. Other installations must
reconcile their own entity IDs. README dashboard guidance follows this layout;
the preserved About `v0.4.0` label is not the installed integration version.

The approved card-content divergence from the current owner-deployment YAML is the System
Grafana card and its prerequisite comment: canonical retains the published
authenticated-access **Markdown** guidance instead of the input's placeholder
HTTP iframe. The existing Grafana safety test is unchanged. Canonical deployment
comments now also contain the approved HACS installation guidance. Both YAMLs
contain matching reviewed dual-axis graphs: Favourites has Outdoor/CH Actual on
the left and HW Tank on the right; Circuit 1 has CH Actual/Outdoor on the left
and Flow/Return on the right. Each axis scales automatically, with both labels
and side-labelled legends, no fixed bounds, and unchanged colours/history/sampling.
The Hot Water graph is unchanged. Static checks do not establish live rendering.
All auto-revert design or implementation is **excluded from 0.6.5**.
Notify-only behavior, manual Revert,
transport retries and the deferred #11 strict expected failure remain unchanged.

Exact intended commit scope from published 0.6.3 (new tests are currently untracked):
- `README.md`: dashboard compatibility plus HACS packaging/copy instructions,
  config-relative lowercase `/dashboards/`, safe Lovelace mapping merge,
  configuration check/restart and manual copied-dashboard update guidance.
- `tests/test_dashboard_graphs.py`: canonical/owner graph contracts.
- `tests/test_dashboard_installation.py`: static packaging/path/YAML-snippet checks.
- `custom_components/econet_grant/extras/econet_grant_dashboard.yaml`: approved
  layout/entity corrections, Grafana exception, both dual-axis graphs and matching
  HACS installation comments, plus lowercase `/dashboards/` destination.
- `custom_components/econet_grant/manifest.json`: one 0.6.4 → 0.6.5 working-file
  bump; net published-baseline change is 0.6.3 → 0.6.5.
- `RELEASE.md`: this release reconciliation and owner-controlled gates.

Local handoff/checkpoints are ignored development evidence, not shipped files.
The dashboard promotion and both graphs have independent review; combined release
preparation and the HACS instructions/tests require independent review together.
No staging or automatic commits on root `main` are authorised.
Exact-final-commit preflight cannot PASS for uncommitted 0.6.5 files:
run it unchanged, retain its dirty-tree refusal and rerun after a separately
authorised commit. A passing offline suite is not an exact-commit release PASS.

Historical version reconciliation:

| Version | Evidence and meaning |
| --- | --- |
| 0.4.1 | Owner-reported deployed version; not revalidated on production here. |
| 0.4.2 | Committed baseline `524a45a`: documentation and canonical dashboard packaging. |
| 0.4.3 | Earlier local write-validation work incremented the working manifest for matching returned parameter name/value. Not a published release. |
| 0.5.0 | Earlier local polling-options work incremented the working manifest for configurable slow polling. Not a published release. |
| 0.6.0 | Found in the working manifest during manual-Revert development; consolidated by release preparation `3eefa14`, including tests, exports and Grafana guidance. Historical local candidate, not a claimed published release. |
| 0.6.1 | Owner-authorised single post-preparation PATCH bump in card t_47c836cd for reviewed readable setting-change notifications (`b9d80ce`). Includes the subsequent retry/observation remediation and local acceptance described below. No new controller functionality in the display correction. |
| 0.6.2 | Owner-authorised direct correction of the README's manual-Revert attribution explanation and TESTING's TCP-enabled module count. PATCH bump required by the direct-change workflow; no runtime-code or test changes. |
| 0.6.3 | Owner-authorised PATCH preparation after reviewed test-only socket-policy correction `a579ec6`. Function-scoped numeric-loopback permissions replace plugin-order-dependent markers; regression tests cover both plugin orders and teardown isolation. No integration runtime changes. |
| 0.6.4 | Reviewed but unreleased dashboard/documentation preparation for canonical promotion and the Grafana exception. Superseded by combined 0.6.5; not a separate publication target. |
| 0.6.5 | Combined canonical promotion/Grafana exception, both reviewed dual-axis graphs, HACS installation guidance and static regression tests. No runtime changes. Local candidate pending combined review. |

The intermediate versions through 0.6.1 were local working-file changes, **not** a sequence of
published releases. The original preparation consolidated committed 0.4.2 to 0.6.0;
the notification refresh incremented it to 0.6.1, and this documentation correction
incremented it to 0.6.2. The subsequent CI correction incremented it to 0.6.3;
prior preparation wrote 0.6.4; this preparation adds exactly one bump to 0.6.5,
not per-file or per-test bumps.
Inspect the actual manifest bytes: the working
filesystem previously omitted same-size edits from `git status`/`git diff`.

Changes since that preparation: `6f73843` made retry evidence deterministic and
classified exact observed manual-Revert transitions without false guest alerts;
`37391af` recorded independent local acceptance with no product-tree change;
`b9d80ce` added shared human-readable select and changed-bit labels for persistent,
generic push and actionable notifications, retaining raw events/audit/write values.
Numeric settings stay numeric; unknown or invalid mapped values remain explicit
raw fallbacks. No auto-revert, retry-policy change or deferred #11 fix is included.

The renewed cumulative lead safety/privacy audit accepted `6ae2364` (0.6.1) for
the owner's release decision. The owner accepted its remaining findings and limits
and authorised the 0.6.2 documentation corrections. Subsequently the owner
authorised and performed a Mac push: the 2026-10-17 diagnosis records remote main
and peeled **v0.6.2** at `a381e7dd6e54c955745600583bfeaad5ea6865af`.
That published tag is immutable; do not move or reuse it for this correction.
GitHub Actions [run 39026863699](https://github.com/mac-wifi/Grant_Aerona_ecoNET_HomeAssistant_Tool/actions/runs/39026863699)
**failed: 9 failed, 302 passed, 1 xfailed, 59 errors**. Its failure signature was
reproduced locally by changing plugin order; the hosted hook order itself was
not logged. The reviewed correction passed locally in both explicit plugin
orders. GitHub release creation was initially paused, then owner-authorised
0.6.3 publication completed as recorded below.
The 0.6.3 delta is test setup/regressions, documentation and version metadata,
not runtime behavior. Before publication, review that delta and retain privacy evidence and
preflight bound to the final intended commit; the earlier commit's preflight is
not evidence for a changed tree. Local tests do not establish phone delivery,
physical controller behavior, hosted CI or HACS installation.

The subsequent **2026-10-17 publication record** confirms main and peeled v0.6.3
at `036210461ed1497c8b809c8064e38e2918a15ff6`, successful hosted runs
39032095759 and 39032095770, and the public non-draft/non-prerelease
[v0.6.3 release](https://github.com/mac-wifi/Grant_Aerona_ecoNET_HomeAssistant_Tool/releases/tag/v0.6.3).
This supersedes the earlier empty-release-list observation; it is retained
publication evidence, not a fresh remote query or a 0.6.5 hosted result.
Published v0.6.2 and v0.6.3 are immutable. Before any 0.6.5 publication the owner
must recheck remote state and ensure that version is unused. No commit, tag,
release or production installation is authorised by this preparation.

## Combined candidate evidence and manual visual checklist

Local working-file verification for 0.6.5: full guarded suite **347 passed,
1 xfailed, 327 warnings**; the exact required `python -m pytest -q` also exited 0.
The strict deferred #11 no-op Restore suppression defect remains, not fixed.
Dashboard audits found six views, 89 reference occurrences / 66 unique IDs and
zero unresolved references against the owner's supplied export, for both YAMLs.
All parsed cards/graphs match except the approved Grafana card. Integration
runtime bytes, the #11 test and release preflight are unchanged from published
0.6.3. Dashboard address/credential-pattern and canonical public-URL checks passed;
this is not a full-history or unknown-secret certification.

The unchanged preflight was invoked with current HEAD and proposed v0.6.5 / 0.6.5:
**exit 1, `FAIL: Working tree/index is dirty (including untracked files)`**.
It refused before tests; there is no final 0.6.5 commit or exact-commit PASS.
`README.md` and `tests/test_dashboard_installation.py` are included and use lowercase configuration-relative `/dashboards/`. The canonical dashboard remains `custom_components/econet_grant/extras/econet_grant_dashboard.yaml`, already containing both independently reviewed graphs; the ignored owner-specific `_live.yaml` was not added to HACS and no duplicate dashboard file was created. No commit, push, release or deployment has happened.

After separately authorised installation, the owner must verify (not performed here):

1. Back up the copied dashboard, configuration and data; follow README Step 7's
   case-sensitive config-relative `dashboards/` copy and merge instructions.
   Check configuration and deliberately restart for registration/integration changes.
2. Confirm required custom cards, all six tabs and actual registry IDs on both
   mobile and desktop; Guest remains explanatory and About's v0.4.0 is historical.
3. On Favourites confirm CH/Outdoor left and HW right; on Circuit 1 confirm
   CH/Outdoor left and Flow/Return right. Inspect both axis labels/legends,
   independent automatic scales with narrow and wide ranges, unclipped outliers,
   missing-series and all-empty history. Confirm Hot Water history is unchanged.
4. Verify authenticated Grafana access without an HTTP iframe workaround; static
   checks do not validate HAOS/Ingress/browser/phone behavior.
5. Confirm clean integration loading, Safe Mode ON and no unexpected writes.
   Do not run Restore or enable checkout/auto-revert. HACS download, update and
   rollback remain live owner checks, not outcomes of this offline preparation.

## Home Assistant support evidence

`hacs.json` sets the minimum to **Core 2026.9.4**, not an HAOS version.
The owner approved this support baseline on **2026-10-05**, replacing the
historical, unverified Core 2024.1.0 minimum. The recorded owner decision cites
[Home Assistant's stable-version metadata](https://version.home-assistant.io/stable.json)
as reporting Core 2026.9.4 / HAOS 18.3 at that time; this moving endpoint is not
a permanent version pin. This is an explicit support-policy decision, not proof
of the earliest version on which the integration could work. Older Core versions
are outside the advertised support baseline; no legacy test programme is planned.
The owner intends to deploy on this baseline or newer, but later Core versions
still need validation: compatibility with every future version is not implied.

The tested baseline is **HA Core 2026.9.4**, pinned by
`pytest-homeassistant-custom-component==0.13.367` in `requirements-test.txt`, on
Python 3.14 (HA requires >=3.14.2). The owner reports production Core 2026.9.4 /
HAOS 18.3; offline tests run Core in a test process, not HAOS or production. See
[TESTING.md](TESTING.md) for real-HA/emulator coverage and its limits. Brand assets
for newer HA frontends are not evidence of a minimum runtime requirement.

HACS metadata now uses documented keys: normal integration-directory packaging,
no custom ZIP asset, default-branch selection retained. `iot_class` remains in
the integration manifest, and platforms remain defined by integration code;
obsolete `hacs.json` fields are removed. The manifest includes the issue tracker
required by the current HACS integration documentation. This is a static metadata
review, not hosted HACS validation or acceptance into its default store.

## Executable local preflight

Use the isolated test environment described in TESTING.md, from the repository
root. Install the pinned dependencies first; the preflight itself installs
nothing and needs no network. Complete independent review, then obtain separate
owner authorisation for an explicit-path local commit first. Reviewers must not
stage or commit automatically. Do not run tests concurrently with
edits, commits or other release preparation.

Record the **full intended commit ID** from `git rev-parse HEAD` after review.
Pass that exact ID, not `HEAD`, a branch, an abbreviated hash or an automatically
moving reference. For example, replace the placeholder before running:

```sh
env -u PYTHONPATH -u PYTHONHOME python scripts/release_preflight.py \
  --commit <full-reviewed-commit-id> \
  --tag v0.6.5 \
  --release-version 0.6.5
```

Use the same Python interpreter as the test environment. The script:

1. Requires execution at the Git root and the explicit commit to equal current
   HEAD. Rejects staged, unstaged and non-ignored untracked files.
2. Independently hashes **every tracked file's actual bytes** against HEAD's Git
   blobs, rather than trusting cached filesystem status. This includes the
   manifest and catches hidden/stale-status edits. Symlinks and submodules are
   rejected rather than incompletely checked. Use an unchanged LF checkout;
   automatic line-ending conversion also fails this exact-byte check.
3. Requires an exact three-component release version, the same manifest version
   and the proposed `v`-prefixed tag. It does not resolve/create that proposed tag.
4. Runs the standard whole suite as `sys.executable -m pytest -q`, streaming its
   output. Any nonzero result (including no tests, strict-xfail XPASS, collection
   failure or missing dependencies) stops the preflight with a nonzero exit.
5. Repeats the commit, tree-byte and version checks after the suite. Only then
   prints `PASS` with the full commit, tag, release version and manifest SHA-256.
   Save the complete output and exit status with the owner's release record.

Do not override pytest discovery/options via environment variables or use an
untrusted test environment. Ignored files (including virtualenvs and local notes),
installed dependencies and the OS are outside the Git-byte check. This is a small
repeatable local check, not a hermetic build, a concurrent filesystem lock or a
security boundary against malicious code. It does not inspect remote tag targets,
protect branches or prevent someone bypassing it to publish an untested commit.
The strict expected failure for deferred **#11** remains part of the standard
suite; a green suite does not mean that defect has been fixed.

Tests in `tests/test_release_preflight.py` run real pytest subprocesses in
isolated synthetic Git repositories: clean success, dirty/staged/untracked and
hidden-byte changes, wrong commit/version/tag, invalid manifest, a failing suite
and mutations during testing. Fixture commits are disposable; no product commit,
tag, release or push is performed by those tests.

## Procedural publication gate (owner only)

These are **instructions, not executable enforcement**:

1. Complete independent review and the final local acceptance handoff. Review
   release notes, safety limitations and backup/rollback options. Confirm the
   target Core version against the approved support baseline and test evidence.
   Retain the completed cumulative notification safety/privacy audit and review
   the test/documentation/version delta described above for the final candidate.
2. After an owner-authorised root-main commit, rerun preflight against the **final intended
   publication commit**, not a formerly tested branch tip. Any changed commit or
   files require a new run. Retain the full output, commit ID and manifest hash.
   Do not merge from the retired worker branch. Include both reviewed graphs in
   this candidate: if the shared tree advances, stop and reconcile the exact
   reviewed release scope before committing. Preserve unrelated artwork; use an
   owner-authorised clean checkout for final preflight rather than deleting it.
3. Only with separate approval, publish from the owner's credentialed local
   clone. Tag **that exact tested commit**, not whichever commit happens to be
   current later. The proposed release version 0.6.5 and tag v0.6.5 must match
   its manifest. Do not move an existing tag to conceal different contents.
4. Require a successful actual hosted test run for the exact intended commit
   before creating the GitHub release. The failed v0.6.2 run is not cleared by
   local tests. Publish a GitHub **release associated with the new tag**, not only a tag or a
   manifest bump. No custom ZIP packaging is needed. Check the tag's resolved
   commit, source archive's manifest/integration/extras and the release notes.
5. Check the actual hosted test run for that exact commit. Local workflow parsing
   is not proof that GitHub Actions ran. Then verify HACS metadata refresh,
   version display, download and pending-restart behaviour on an owner-approved
   test installation before deciding on production. HACS discovery may lag;
   **Update information** refreshes metadata but does not install code.

Hosted CI for v0.6.2 failed; 0.6.3 hosted success and release visibility are
recorded above. Hosted CI and publication for **0.6.5** remain unverified, as do
live HACS update detection, archive installation and earlier-version rollback.
No custom update entity or auto-update is added:
HACS already provides update entities for tracked repositories.

## Owner-controlled installation and rollback

Before an update, take a Home Assistant backup and preserve any locally edited
files outside the integration directory. HACS downloads replace that directory;
local edits in `custom_components/econet_grant/` can be lost. Keep a known-good
code archive and appropriate backups of configuration, SQLite history and named
snapshots. Verify the chosen version is compatible with your HA version.

For a repository with releases, the documented HACS route is:

1. Open HACS and find EcoNet Grant Aerona. Use the repository three-dot menu >
   **Update information** if needed, then **Redownload**.
2. Under **Need a different version?**, choose the intended available release
   (including an earlier known-good one for code rollback), inspect it and confirm.
   HACS documents the latest five releases plus the default branch for integrations.
   Without versioned releases the selector may not appear. The recorded 0.6.3
   release does not prove that every earlier version is selectable in HACS.
3. Restart Home Assistant **when the owner chooses** to activate the downloaded
   integration. Check integration loading, Safe Mode, entities and logs afterward.
   Redownloading code is not permission to write to the controller.

If the required version is unavailable in HACS, manual installation remains
supported: obtain its known-good source archive or exact previously saved commit,
replace only `custom_components/econet_grant/` with that complete version, then
restart HA. Do not overlay versions and leave removed Python files behind. Do not
delete HA configuration or the database as part of code replacement.

The canonical dashboard remains
`custom_components/econet_grant/extras/econet_grant_dashboard.yaml`. HACS delivers
that packaged source; it does not update your separately copied/customised
Lovelace dashboard. Back up and deliberately reconcile that copy. Top-level
`scripts/`, `grafana/` and `ha_config/` are repository extras, not installed HA
integration files. Use matching examples from the chosen source version.

**Code rollback is not device or database rollback.** It does not undo heat-pump
writes, revert SQLite contents/schema or retention purges, restore snapshots,
restore entity IDs/configuration, or rewind InfluxDB. Database compatibility with
older code needs separate consideration and backup restoration must be deliberate.
Do not invoke Restore Default or automate heating changes to accomplish a code
rollback. The no-op restore suppression defect #11 is still deferred; checkout
restoration and unsupported Remote Menu work (#2/#7) are not enabled by this release.

## Authoritative references consulted

Read on 2026-10-05 UTC (live website retrieval, not live HACS UI testing):

- [HACS integration requirements](https://www.hacs.xyz/docs/publish/integration/):
  one integration directory, manifest fields, optional releases and five-release
  selection versus default-branch fallback.
- [HACS general publishing/metadata](https://www.hacs.xyz/docs/publish/start/):
  supported `hacs.json` fields and GitHub releases, not tags alone, for versions.
- [HACS dashboard/download/version selection](https://www.hacs.xyz/docs/use/repositories/dashboard/):
  metadata refresh, Redownload, earlier-version selector and pending restart.
- [HACS download behaviour](https://www.hacs.xyz/docs/faq/download/):
  target directory replacement.
- [HACS update entities](https://www.hacs.xyz/docs/use/entities/update/):
  HACS already provides them; advanced version-action overrides are unnecessary here.
- [Public release history](https://api.github.com/repos/mac-wifi/Grant_Aerona_ecoNET_HomeAssistant_Tool/releases?per_page=100):
  empty public list at the historical inspection; superseded by the recorded
  0.6.3 publication above. Recheck before owner publication.
