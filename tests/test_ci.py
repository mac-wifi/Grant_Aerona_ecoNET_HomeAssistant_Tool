"""Local CI contract validation; this is not a hosted Actions execution."""
from pathlib import Path

import yaml


def test_workflow_runs_same_discovered_suite():
    # BaseLoader keeps YAML 1.2's 'on' spelling instead of YAML 1.1's boolean coercion.
    workflow = yaml.load(Path(".github/workflows/tests.yml").read_text(), Loader=yaml.BaseLoader)
    assert set(workflow["on"]) == {"push", "pull_request"}
    assert workflow["permissions"] == {"contents": "read"}
    job = workflow["jobs"]["tests"]
    steps = job["steps"]
    # Keep CI on the real-HA harness's Python baseline.
    assert any(step.get("with", {}).get("python-version") == "3.14" for step in steps)
    assert [step["run"] for step in steps if "run" in step] == [
        "python -m pip install -r requirements-test.txt", "python -m pytest",
    ]
