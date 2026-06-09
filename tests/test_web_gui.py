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
                "events": [{"id": "login_failed", "count": 3, "actor": "firewall"}],
            }
        ],
    }
    text = scenario_to_yaml(doc, assets)
    assert "login_failed" in text
    assert "actors:" in text


@pytest.fixture
def client(tmp_path, monkeypatch):
    db = tmp_path / "test.db"
    monkeypatch.setenv("FORTISIEM_SIM_DB", str(db))
    monkeypatch.setenv("FORTISIEM_SIM_STORAGE", "sql")
    app = create_app(ROOT / "templates" / "events.yaml")
    app.config["TESTING"] = True
    return app.test_client()


def test_api_config_get(client):
    r = client.get("/api/config")
    assert r.status_code == 200
    data = r.get_json()
    assert "ad" in data
    assert "c2" in data
    assert "smtp" in data
    assert "actor_keys" in data


def test_api_emails(client):
    r = client.get("/api/emails")
    assert r.status_code == 200
    data = r.get_json()
    assert data["count"] >= 3
    assert "catalog" in data
    r2 = client.get("/api/emails/ir_alert_tabletop")
    assert r2.status_code == 200
    assert "html_body" in r2.get_json()


def test_api_mitre_tactics(client):
    r = client.get("/api/mitre/tactics")
    assert r.status_code == 200
    data = r.get_json()
    assert len(data["tactics"]) >= 14
    assert data["tactics"][0]["id"].startswith("TA")


def test_api_events(client):
    r = client.get("/api/events")
    assert r.status_code == 200
    data = r.get_json()
    assert data["count"] >= 23
    assert "login_success" in data["ids"]
    assert "catalog" in data
    assert len(data["catalog"]) == data["count"]
    assert "by_tactic" in data
    assert "login_failed" in data["by_tactic"]["TA0001"]
    assert "system" in data["catalog"][0]


def test_api_events_import(client, tmp_path, monkeypatch):
    yaml_body = """
events:
  gui_test_evt:
    name: GUI import test
    format: syslog_generic
    body: event=gui_test simulated=true
    mitre:
      tactics: [TA0001]
      techniques: [T1078]
"""
    before = client.get("/api/events").get_json()["count"]
    r = client.post("/api/events/import", data=yaml_body, content_type="text/yaml")
    assert r.status_code == 200
    data = r.get_json()
    assert data["ok"] is True
    assert "gui_test_evt" in data["added"]
    assert data["count"] == before + 1
    after = client.get("/api/events").get_json()
    assert "gui_test_evt" in after["ids"]


def test_api_scenarios_list_has_items(client):
    r = client.get("/api/scenarios")
    assert r.status_code == 200
    data = r.get_json()
    assert "items" in data
    assert len(data["items"]) >= 1
    assert "phases" in data["items"][0]


def test_index_serves_html(client):
    r = client.get("/")
    assert r.status_code == 200
    assert b"FortiSIEM Sim" in r.data
    assert b"panel-config" in r.data
