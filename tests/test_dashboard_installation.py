"""Static HACS dashboard packaging and copy/registration documentation contract."""

import json
from pathlib import Path
import re

import yaml

ROOT = Path(__file__).resolve().parents[1]
PACKAGE_PATH = "custom_components/econet_grant/extras/econet_grant_dashboard.yaml"
DESTINATION = "dashboards/econet_grant_dashboard.yaml"


def test_dashboard_is_in_hacs_integration_tree():
    hacs = json.loads((ROOT / "hacs.json").read_text())
    assert hacs["content_in_root"] is False
    assert hacs["zip_release"] is False
    assert (ROOT / PACKAGE_PATH).is_file()
    dashboard = yaml.safe_load((ROOT / PACKAGE_PATH).read_text())
    assert len(dashboard["views"]) == 6
    assert (ROOT / "custom_components/econet_grant/manifest.json").is_file()


def test_readme_copy_and_registration_paths_match():
    readme = (ROOT / "README.md").read_text()
    section = readme.split("### 7. Dashboard Setup", 1)[1].split("### 8.", 1)[0]
    assert "mkdir -p /homeassistant/dashboards" in section
    assert section.count(f"/homeassistant/{PACKAGE_PATH}") >= 2
    assert section.count(f"/homeassistant/{DESTINATION}") >= 2
    match = re.search(r"```yaml\n(.*?)```", section, re.S)
    assert match is not None
    config = yaml.safe_load(match[1])
    assert config == {
        "lovelace": {"dashboards": {"econet-grant": {
            "mode": "yaml",
            "title": "Grant Aerona Heat Pump",
            "icon": "mdi:heat-pump-outline",
            "show_in_sidebar": True,
            "filename": DESTINATION,
        }}}
    }
    assert "do not replace" in section.lower()
    assert "does not automatically update" in section
    assert "Restart Home Assistant" in section


def test_deployment_header_matches_readme_registration():
    text = (ROOT / PACKAGE_PATH).read_text()
    header = text.split("\ntitle:", 1)[0]
    assert f"/homeassistant/{PACKAGE_PATH}" in header
    assert f"/homeassistant/{DESTINATION}" in header
    assert "do not replace" in header.lower()
    assert "does not automatically update" in header
    assert "Restart Home Assistant" in header
    uncommented = "\n".join(line[2:] for line in header.splitlines() if line.startswith("# "))
    match = re.search(r"(?m)^       lovelace:\n(?:       .*\n)+", uncommented)
    assert match is not None
    config = yaml.safe_load(match[0])
    readme = (ROOT / "README.md").read_text().split("#### 7c.", 1)[1]
    match = re.search(r"```yaml\n(.*?)```", readme, re.S)
    assert match is not None
    expected = yaml.safe_load(match[1])
    assert config == expected
