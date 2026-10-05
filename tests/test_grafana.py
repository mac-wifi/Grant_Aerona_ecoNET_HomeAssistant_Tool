"""Offline contracts for examples, not execution of InfluxQL or Grafana imports."""

import json
import fnmatch
import re
from pathlib import Path

import pytest
import yaml
from homeassistant.util import slugify

from custom_components.econet_grant.const import (
    NUMBER_DEFINITIONS,
    SELECT_DEFINITIONS,
    SENSOR_DEFINITIONS,
)

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("name", ["performance", "system", "temperature"])
def test_dashboards_bind_influxql_datasource(name):
    source = yaml.safe_load((ROOT / "grafana/datasources/influxdb.yaml").read_text())["datasources"][0]
    assert source["jsonData"]["version"] == "InfluxQL"
    assert source["jsonData"]["dbName"] == "econet_grant"
    assert source["uid"] == "econet-influxdb"
    dashboard = json.loads((ROOT / f"grafana/dashboards/{name}.json").read_text())
    # Dashboard model, not the HTTP API's {dashboard, overwrite} envelope.
    assert dashboard["uid"] == f"econet-{name}"
    for panel in dashboard["panels"]:
        if panel.get("targets"):
            # Grafana resolves the panel datasource before non-mixed targets.
            assert panel.get("datasource") == {"type": "influxdb", "uid": source["uid"]}
        for target in panel.get("targets", []):
            assert target["datasource"] == {"type": "influxdb", "uid": source["uid"]}
            assert target["rawQuery"] is True
            assert target["query"].startswith("SELECT ")
            assert "$timeFilter" in target["query"]


def test_fixture_matches_integration_entities_and_ha_filter():
    fixture = json.loads((ROOT / "tests/fixtures/influx_schema.json").read_text())
    config = yaml.safe_load((ROOT / "ha_config/configuration.yaml").read_text())["influxdb"]
    assert config["default_measurement"] == "state"
    assert config["measurement_attr"] == "unit_of_measurement"
    assert "override_measurement" not in config
    definitions = {"sensor": SENSOR_DEFINITIONS, "number": NUMBER_DEFINITIONS, "select": SELECT_DEFINITIONS}
    for series in fixture["series"]:
        domain = series["tags"]["domain"]
        definition = definitions[domain][series["key"]]
        object_id = slugify(f"Grant Aerona Heat Pump {definition['name']}")
        assert series["tags"]["entity_id"] == object_id
        assert series["measurement"] == (definition.get("unit") or "state")
        if domain == "select":
            assert series["fields"]["state"] in definition["options"].values()
            assert "value" not in series["fields"]
        else:
            assert isinstance(series["fields"]["value"], float)
        assert any(fnmatch.fnmatchcase(f"{domain}.{object_id}", glob)
                   for glob in config["include"]["entity_globs"])


@pytest.mark.parametrize("name", ["performance", "system", "temperature"])
def test_all_query_fields_measurements_and_tag_pairs_exist_in_fixture(name):
    """Validate the deliberately small example-query grammar, not an SQL engine."""
    fixture = json.loads((ROOT / "tests/fixtures/influx_schema.json").read_text())
    dashboard = json.loads((ROOT / f"grafana/dashboards/{name}.json").read_text())
    series_by_tags = {(s["tags"]["domain"], s["tags"]["entity_id"]): s for s in fixture["series"]}
    pair_pattern = r'''\("domain" = '([^']+)' AND "entity_id" = '([^']+)'\)'''
    for panel in dashboard["panels"]:
        for target in panel.get("targets", []):
            query = target["query"]
            match = re.fullmatch(
                r'SELECT (mean\("value"\)|last\("value"\)|"state") '
                r'FROM "([^"]+)" WHERE \$timeFilter AND (.+)', query,
            )
            assert match, query
            selection, measurement, predicate = match.groups()
            pairs = re.findall(pair_pattern, predicate)
            assert pairs
            # Reject unscoped OR branches, unknown syntax and missing group tags.
            remainder = re.sub(pair_pattern, "PAIR", predicate)
            group = (' GROUP BY time($__interval), "domain", "entity_id" fill(null)'
                     if selection.startswith("mean") else
                     ' GROUP BY "domain", "entity_id"' if selection.startswith("last") else "")
            expected = "PAIR" if len(pairs) == 1 else "(" + " OR ".join(["PAIR"] * len(pairs)) + ")"
            assert remainder == expected + group
            field = "state" if selection == '"state"' else "value"
            for pair in pairs:
                series = series_by_tags[pair]
                assert series["measurement"] == measurement
                assert field in series["fields"]
                assert series["fields"][field] not in fixture["skipped_states"]
            if field == "state":
                assert target["resultFormat"] == "table"
                assert panel["type"] == "state-timeline"
            else:
                assert target["resultFormat"] == "time_series"
                assert target["alias"] == "$tag_entity_id"


def test_yaml_credentials_and_lovelace_access_are_safe_placeholders():
    source = yaml.safe_load((ROOT / "grafana/datasources/influxdb.yaml").read_text())["datasources"][0]
    assert source["access"] == "proxy"
    assert source["url"] == "${INFLUXDB_URL}"
    assert source["user"] == "${INFLUXDB_READ_USER}"
    assert source["secureJsonData"] == {"password": "$INFLUXDB_READ_PASSWORD"}
    assert source["isDefault"] is False
    assert not {"token", "organization", "defaultBucket"} & source["jsonData"].keys()
    dashboard = yaml.safe_load((ROOT / "custom_components/econet_grant/extras/econet_grant_dashboard.yaml").read_text())
    system = next(view for view in dashboard["views"] if view["path"] == "system")
    grafana = next(card for card in system["cards"] if "Grafana" in card.get("title", ""))
    assert grafana["type"] == "markdown"
    assert "Open Web UI" in grafana["content"]
    assert "url" not in grafana
