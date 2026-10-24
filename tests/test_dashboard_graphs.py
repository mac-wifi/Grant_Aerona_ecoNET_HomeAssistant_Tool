"""Offline Mini Graph Card contracts; these do not verify browser rendering."""

from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
CANONICAL = ROOT / "custom_components/econet_grant/extras/econet_grant_dashboard.yaml"
OWNER = ROOT / "tools/owner-deployment/econet_grant_dashboard_live.yaml"


def favourites_graph(path):
    dashboard = yaml.safe_load(path.read_text())
    view = next(view for view in dashboard["views"] if view["title"] == "Favourites")
    graphs = [card for card in view["cards"] if card.get("name") == "Temperature History (24h)"]
    assert len(graphs) == 1
    return graphs[0]


@pytest.mark.parametrize("path", [CANONICAL, OWNER], ids=["canonical", "owner"])
def test_favourites_temperature_axes(path):
    if path == OWNER and not path.exists():
        pytest.skip("Owner deployment artifact is local/ignored, not distributed")
    graph = favourites_graph(path)
    assert graph["type"] == "custom:mini-graph-card"
    assert graph["entities"] == [
        {
            "entity": "sensor.grant_aerona_heat_pump_outdoor_temperature",
            "name": "Outdoor (left)",
            "color": "#4FC3F7",
        },
        {
            "entity": "sensor.grant_aerona_heat_pump_heating_thermostat",
            "name": "CH Actual (left)",
            "color": "#FF7043",
        },
        {
            "entity": "sensor.grant_aerona_heat_pump_dhw_temperature",
            "name": "HW Tank (right)",
            "color": "#66BB6A",
            "y_axis": "secondary",
        },
    ]
    assert graph["show"] == {"labels": True, "labels_secondary": True, "legend": True}
    assert graph["hours_to_show"] == 24
    assert graph["points_per_hour"] == 2
    assert graph["line_width"] == 2
    # No fixed/soft bounds or minimum-range constraints on either automatic axis.
    assert not any("bound" in key for key in graph)
    assert set(graph) == {
        "type", "name", "entities", "hours_to_show", "points_per_hour", "line_width", "show"
    }
    if path == OWNER:
        assert graph == favourites_graph(CANONICAL)


def circuit1_graph(path):
    dashboard = yaml.safe_load(path.read_text())
    view = next(view for view in dashboard["views"] if view["title"] == "Circuit 1")
    graphs = [card for card in view["cards"] if card.get("name") == "CH Temperature History (24h)"]
    assert len(graphs) == 1
    return graphs[0]


@pytest.mark.parametrize("path", [CANONICAL, OWNER], ids=["canonical", "owner"])
def test_circuit1_temperature_axes(path):
    if path == OWNER and not path.exists():
        pytest.skip("Owner deployment artifact is local/ignored, not distributed")
    graph = circuit1_graph(path)
    assert graph["type"] == "custom:mini-graph-card"
    assert graph["entities"] == [
        {
            "entity": "sensor.grant_aerona_heat_pump_heating_thermostat",
            "name": "CH Actual (left)",
            "color": "#FF7043",
        },
        {
            "entity": "sensor.grant_aerona_heat_pump_flow_temperature",
            "name": "Flow (right)",
            "color": "#EF5350",
            "y_axis": "secondary",
        },
        {
            "entity": "sensor.grant_aerona_heat_pump_return_temperature",
            "name": "Return (right)",
            "color": "#42A5F5",
            "y_axis": "secondary",
        },
        {
            "entity": "sensor.grant_aerona_heat_pump_outdoor_temperature",
            "name": "Outdoor (left)",
            "color": "#4FC3F7",
        },
    ]
    assert graph["show"] == {"labels": True, "labels_secondary": True, "legend": True}
    assert graph["hours_to_show"] == 24
    assert graph["points_per_hour"] == 2
    assert graph["line_width"] == 2
    assert not any("bound" in key for key in graph)
    assert set(graph) == {
        "type", "name", "entities", "hours_to_show", "points_per_hour", "line_width", "show"
    }
    if path == OWNER:
        assert graph == circuit1_graph(CANONICAL)
