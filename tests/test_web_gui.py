from __future__ import annotations

from pathlib import Path

import pytest

from fortisiem_sim.assets import assets_to_actors, load_assets, save_assets, scenario_to_yaml
from fortisiem_sim.web import create_app


ROOT = Path(__file__).resolve().parent.parent


def test_load_assets_has_lab_users():
    assets = load_assets(ROOT / "config" / "assets.yaml")
    assert "jgarcia" in assets["ad"]["users"]
    assert len(assets["firewalls"]) >= 2
    assert any(h["hostname"] == "ws-finance-01" for h in assets["windows_hosts"])


def test_assets_to_actors_profiles():
    assets = load_assets(ROOT / "config" / "assets.yaml")
    actors = assets_to_actors(assets)
    assert "firewall" in actors["profiles"]
    assert "ws_finance_01" in actors["profiles"]
    assert "jgarcia" in actors["pools"]["users"]


def test_scenario_to_yaml_with_config_actors():
    assets = load_assets(ROOT / "config" / "assets.yaml")
    doc = {
        "name": "test-gui",
        "description": "unit test",
        "org_id": 1,
        "use_config_actors": True,
        "phases": [
            {
                "name": "phase1",
                "description": "test",
                "delay_before": 0,
                "events": [{"id": "login_failed", "count": 3, "actor": "firewall"}],
            }
        ],
    }
    text = scenario_to_yaml(doc, assets)
    assert "login_failed" in text
    assert "actors:" in text


@pytest.fixture
def client():
    app = create_app(ROOT / "templates" / "events.yaml")
    app.config["TESTING"] = True
    return app.test_client()


def test_api_config_get(client):
    r = client.get("/api/config")
    assert r.status_code == 200
    data = r.get_json()
    assert "ad" in data
    assert "actor_keys" in data


def test_api_events(client):
    r = client.get("/api/events")
    assert r.status_code == 200
    data = r.get_json()
    assert data["count"] >= 27
    assert "login_success" in data["ids"]


def test_index_serves_html(client):
    r = client.get("/")
    assert r.status_code == 200
    assert b"FortiSIEM Sim" in r.data
    assert b"panel-config" in r.data
