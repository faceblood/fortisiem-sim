from __future__ import annotations

from pathlib import Path

import pytest

from fortisiem_sim.assets import assets_to_actors, load_assets, save_assets, scenario_to_yaml
from fortisiem_sim.web import create_app


ROOT = Path(__file__).resolve().parent.parent


def test_load_assets_has_lab_users():
    assets = load_assets(ROOT / "config" / "assets.yaml")
    usernames = {
        u["username"] if isinstance(u, dict) else str(u)
        for u in assets["ad"]["users"]
    }
    assert "jgarcia" in usernames
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
    from fortisiem_sim.db.connection import ensure_database, get_connection, init_schema
    from fortisiem_sim.db.import_csv import _default_csv_root, import_config

    db = tmp_path / "test.db"
    monkeypatch.setenv("FORTISIEM_SIM_DB", str(db))
    monkeypatch.setenv("FORTISIEM_SIM_STORAGE", "sql")
    ensure_database(seed_from_yaml=True, path=db)
    conn = get_connection(db)
    import_config(conn, _default_csv_root())
    conn.commit()
    conn.close()
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


def test_api_commands_linux(client):
    r = client.get("/api/commands")
    assert r.status_code == 200
    data = r.get_json()
    assert data["count"] >= 50
    legit = [c for c in data["commands"] if c["legitimacy"] == "legitimate"]
    illeg = [c for c in data["commands"] if c["legitimacy"] == "illegitimate"]
    assert len(legit) >= 20
    assert len(illeg) >= 20
    sample = data["commands"][0]
    r2 = client.put(
        f"/api/commands/{sample['id']}",
        json={**sample, "description": "test update"},
        content_type="application/json",
    )
    assert r2.status_code == 200


def test_api_event_detail_and_update(client):
    r = client.get("/api/events/login_failed")
    assert r.status_code == 200
    detail = r.get_json()
    assert detail["id"] == "login_failed"
    assert "tactics" in detail
    assert "techniques" in detail
    assert "body" in detail
    assert "tactic_labels" in detail

    detail["name"] = detail["name"] + " (test)"
    r2 = client.put(
        "/api/events/login_failed",
        json=detail,
        content_type="application/json",
    )
    assert r2.status_code == 200
    assert r2.get_json()["ok"] is True

    r3 = client.get("/api/events/login_failed")
    assert "(test)" in r3.get_json()["name"]


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
    assert b"btn-continue" in r.data


def test_api_scenario_phases_use_mitre_technique_labels(client):
    r = client.get("/api/scenarios")
    data = None
    scenario = None
    for sid in r.get_json()["scenarios"]:
        payload = client.get(f"/api/scenarios/{sid}").get_json()
        if payload.get("phases"):
            scenario = sid
            data = payload
            break
    assert scenario, "Ningún escenario con fases en la BD de test"
    assert data["phases"]
    ph = data["phases"][0]
    assert "label" in ph
    assert "display_label" in ph
    assert "tactic_name" in ph
    assert "mitre_techniques" in ph
    assert ph["display_label"]
    assert "recon_and_access" not in ph["display_label"]
    assert ph["tactic_name"]


def test_api_chains_seeded_on_init(client):
    r = client.get("/api/chains")
    assert r.status_code == 200
    data = r.get_json()
    assert data["count"] >= 1
    assert data["chains"][0]["step_count"] >= 1


def test_api_scenario_chain_phase_roundtrip(client):
    chains = client.get("/api/chains").get_json()["chains"]
    assert chains
    chain_id = chains[0]["id"]
    step_count = chains[0].get("step_count", 1)
    payload = {
        "name": "test-chain-phase",
        "description": "fase dedicada cadena",
        "org_id": 1,
        "timeline_minutes": 0,
        "use_config_actors": True,
        "phases": [
            {
                "phase_type": "chain",
                "name": "cadena_lateral",
                "description": "actividad linux agrupada",
                "chains": [{"chain_id": chain_id, "actor": "", "sort_order": 0}],
            }
        ],
    }
    save = client.post("/api/scenarios/builder", json=payload)
    assert save.status_code == 200
    sid = save.get_json()["name"]
    loaded = client.get(f"/api/scenarios/{sid}/builder").get_json()
    assert loaded["phases"][0]["phase_type"] == "chain"
    assert loaded["phases"][0]["chains"][0]["chain_id"] == chain_id
    detail = client.get(f"/api/scenarios/{sid}").get_json()
    assert detail["phases"][0]["display_label"] == "Cadena Linux"
    assert detail["phases"][0]["total"] >= step_count


def test_api_scenario_with_chain_roundtrip(client):
    chains = client.get("/api/chains").get_json()["chains"]
    assert chains
    chain_id = chains[0]["id"]
    step_count = chains[0].get("step_count", 1)
    payload = {
        "name": "test-chain-scenario",
        "description": "escenario con cadena",
        "org_id": 1,
        "timeline_minutes": 0,
        "use_config_actors": True,
        "phases": [
            {
                "phase_type": "mitre",
                "name": "initial_access",
                "description": "cadena linux",
                "mitre_tactic": "TA0001",
                "mitre_techniques": ["T1078"],
                "events": [{"chain_id": chain_id, "count": 1, "actor": "", "sort_order": 0}],
                "emails": [],
            }
        ],
    }
    save = client.post("/api/scenarios/builder", json=payload)
    assert save.status_code == 200
    sid = save.get_json()["name"]
    loaded = client.get(f"/api/scenarios/{sid}/builder").get_json()
    assert loaded["phases"][0]["events"][0]["chain_id"] == chain_id
    detail = client.get(f"/api/scenarios/{sid}").get_json()
    assert detail["phases"][0]["events"][0]["chain_id"] == chain_id
    assert detail["phases"][0]["total"] >= step_count
