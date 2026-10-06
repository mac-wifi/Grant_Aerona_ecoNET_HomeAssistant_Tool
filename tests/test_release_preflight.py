"""Exercise the release CLI in disposable repositories, never tag or publish."""

import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/release_preflight.py"
MANIFEST = "custom_components/econet_grant/manifest.json"


def git(repo, *args):
    return subprocess.check_output(["git", "-C", str(repo), *args], text=True).strip()


@pytest.fixture
def release_repo(tmp_path):
    repo = tmp_path / "release"
    repo.mkdir()
    git(repo, "init", "-q")
    git(repo, "config", "user.email", "test@example.invalid")
    git(repo, "config", "user.name", "Synthetic test")
    (repo / MANIFEST).parent.mkdir(parents=True)
    (repo / MANIFEST).write_text('{"version": "0.6.0"}\n')
    (repo / ".gitignore").write_text("__pycache__/\n.pytest_cache/\n")
    (repo / "test_sample.py").write_text("def test_sample():\n    assert True\n")
    (repo / "scripts").mkdir()
    assert SCRIPT.exists(), "release preflight is not implemented"
    shutil.copyfile(SCRIPT, repo / "scripts/release_preflight.py")
    git(repo, "add", ".")
    git(repo, "commit", "-qm", "Synthetic release fixture")
    return repo


def run_preflight(repo, *args):
    env = os.environ.copy()
    # Only the disposable child suite: no HA/plugin boot or parent pytest flags.
    env["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
    env.pop("PYTEST_ADDOPTS", None)
    return subprocess.run(
        [sys.executable, str(repo / "scripts/release_preflight.py"),
         "--commit", git(repo, "rev-parse", "HEAD"),
         "--tag", "v0.6.0", "--release-version", "0.6.0", *args],
        cwd=repo, env=env, capture_output=True, text=True, check=False,
    )


def test_clean_commit_runs_real_suite_and_reports_identity(release_repo):
    result = run_preflight(release_repo)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "1 passed" in result.stdout
    assert git(release_repo, "rev-parse", "HEAD") in result.stdout
    assert "v0.6.0" in result.stdout
    digest = hashlib.sha256((release_repo / MANIFEST).read_bytes()).hexdigest()
    assert f"manifest_sha256={digest}" in result.stdout
    assert "PASS" in result.stdout
    assert git(release_repo, "tag", "--list") == ""
    assert git(release_repo, "status", "--porcelain") == ""


@pytest.mark.parametrize("args", [
    ["--tag", "v0.5.0"],
    ["--release-version", "0.5.0"],
    ["--tag", "0.6.0"],
    ["--release-version", "00.6.0", "--tag", "v00.6.0"],
    ["--commit", "0" * 40],
    ["--commit", "HEAD"],
])
def test_mismatched_or_ambiguous_identity_stops_before_tests(release_repo, args):
    result = run_preflight(release_repo, *args)
    assert result.returncode != 0
    assert "FAIL" in result.stderr
    assert "1 passed" not in result.stdout
    assert "PASS" not in result.stdout


@pytest.mark.parametrize("change", ["tracked", "staged", "untracked", "hidden"])
def test_dirty_tree_stops_before_tests_even_with_hidden_manifest_change(release_repo, change):
    path = release_repo / MANIFEST
    if change == "untracked":
        (release_repo / "unexpected.py").write_text("# unexpected\n")
    else:
        path.write_text('{"version": "0.5.0"}\n')
        if change == "staged":
            git(release_repo, "add", MANIFEST)
        if change == "hidden":
            git(release_repo, "update-index", "--assume-unchanged", MANIFEST)
            assert git(release_repo, "status", "--porcelain") == ""
    result = run_preflight(release_repo)
    assert result.returncode != 0
    assert "FAIL" in result.stderr
    assert "1 passed" not in result.stdout


@pytest.mark.parametrize("body, message", [
    ("def test_sample():\n    assert False\n", "Offline suite failed"),
    ("from pathlib import Path\ndef test_sample():\n    Path('test_sample.py').write_text('# changed')\n", "dirty"),
])
def test_failure_or_mutation_during_suite_never_reports_success(release_repo, body, message):
    (release_repo / "test_sample.py").write_text(body)
    git(release_repo, "add", "test_sample.py")
    git(release_repo, "commit", "-qm", "Synthetic failing or mutating suite")
    result = run_preflight(release_repo)
    assert result.returncode != 0
    assert "PASS" not in result.stdout
    assert message in result.stderr


@pytest.mark.parametrize("raw", ['{"version":"0.5.0"}', '{}', '[]', '{broken'])
def test_invalid_committed_manifest_stops_before_suite(release_repo, raw):
    (release_repo / MANIFEST).write_text(raw)
    git(release_repo, "add", MANIFEST)
    git(release_repo, "commit", "-qm", "Synthetic bad manifest")
    result = run_preflight(release_repo)
    assert result.returncode != 0
    assert "FAIL" in result.stderr
    assert "1 passed" not in result.stdout


def test_manifest_must_be_in_intended_commit_not_just_ignored_on_disk(release_repo):
    git(release_repo, "rm", "--cached", MANIFEST)
    with (release_repo / ".gitignore").open("a") as handle:
        handle.write(MANIFEST + "\n")
    git(release_repo, "add", ".gitignore")
    git(release_repo, "commit", "-qm", "Synthetic ignored manifest")
    assert git(release_repo, "status", "--porcelain") == ""
    result = run_preflight(release_repo)
    assert result.returncode != 0
    assert "PASS" not in result.stdout
    assert "1 passed" not in result.stdout
