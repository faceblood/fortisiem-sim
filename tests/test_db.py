from __future__ import annotations

import pytest

from fortisiem_sim.db.connection import ensure_database
from fortisiem_sim.db.events_repo import load_all_templates, merge_events_import
from fortisiem_sim.db.scenarios_repo import list_scenario_ids, load_scenario_model
from fortisiem_sim.storage import (
    load_assets_data,
    load_scenario_data,
    save_assets_data,
    use_sql_storage,
)


@pytest.fixture
def sql_db(tmp_path, monkeypatch):
    db = tmp_path / "fortisiem.db"
    monkeypatch.setenv("FORTISIEM_SIM_DB", str(db))
    monkeypatch.setenv("FORTISIEM_SIM_STORAGE", "sql")
    ensure_database(seed_from_yaml=True, path=db)
    return db


def test_use_sql_storage_env(monkeypatch, sql_db):
    assert use_sql_storage() is True
    monkeypatch.setenv("FORTISIEM_SIM_STORAGE", "yaml")
    assert use_sql_storage() is False


def test_seed_loads_events_and_scenarios(sql_db):
    templates = load_all_templates()
    assert len(templates) >= 23
    assert "login_failed" in templates
    ids = list_scenario_ids()
    assert len(ids) >= 1
    sc = load_scenario_model(ids[0], assets=load_assets_data())
    assert sc.phases


def test_assets_roundtrip(sql_db):
    assets = load_assets_data()
    assets["ad"]["users"].append("test.user")
    save_assets_data(assets)
    reloaded = load_assets_data()
    assert "test.user" in reloaded["ad"]["users"]


def test_import_event_sql(sql_db):
    added, updated = merge_events_import(
        {
            "sql_only_evt": {
                "name": "SQL event",
                "format": "syslog_generic",
                "body": "event=sql_test simulated=true",
                "mitre": {"tactics": ["TA0001"], "techniques": ["T1078"]},
            }
        },
        path=sql_db,
    )
    assert added == ["sql_only_evt"]
    templates = load_all_templates()
    assert "sql_only_evt" in templates


def test_load_scenario_via_storage(sql_db):
    ids = list_scenario_ids()
    sc = load_scenario_data(ids[0])
    assert sc.name


def test_email_templates_seeded(sql_db):
    from fortisiem_sim.db.email_repo import list_email_catalog, load_smtp_settings

    catalog = list_email_catalog()
    assert len(catalog) >= 3
    assert any(c["id"] == "phishing_simulated" for c in catalog)
    smtp = load_smtp_settings()
    assert smtp["enabled"] is False


def test_mitre_phase_with_inline_email(sql_db):
    from fortisiem_sim.db.scenarios_repo import save_from_builder, builder_payload

    scenario_id = save_from_builder({
        "name": "email-inline-test",
        "description": "test",
        "org_id": 1,
        "use_config_actors": True,
        "phases": [{
            "phase_type": "mitre",
            "name": "initial_access",
            "description": "test",
            "mitre_tactic": "TA0001",
            "events": [{"id": "login_failed", "count": 1, "actor": "", "sort_order": 0}],
            "emails": [{
                "template_id": "ir_alert_tabletop",
                "to_address": "soc@lab.local",
                "cc": "",
                "actor": "",
                "sort_order": 1,
            }],
        }],
    })
    payload = builder_payload(scenario_id)
    ph = payload["phases"][0]
    assert ph["phase_type"] == "mitre"
    assert len(ph["events"]) == 1
    assert len(ph["emails"]) == 1
    assert ph["emails"][0]["sort_order"] == 1


def test_build_manual_blocks_phase_and_email(sql_db):
    from fortisiem_sim.db.scenarios_repo import save_from_builder
    from fortisiem_sim.engine import build_manual_blocks

    scenario_id = save_from_builder({
        "name": "manual-plan-test",
        "description": "test",
        "org_id": 1,
        "use_config_actors": True,
        "phases": [{
            "phase_type": "mitre",
            "name": "initial_access",
            "description": "Acceso inicial",
            "mitre_tactic": "TA0001",
            "events": [{"id": "login_failed", "count": 2, "actor": "", "sort_order": 0}],
            "emails": [{
                "template_id": "ir_alert_tabletop",
                "to_address": "soc@lab.local",
                "cc": "",
                "sort_order": 1,
            }],
        }],
    })
    sc = load_scenario_data(scenario_id)
    blocks = build_manual_blocks(
        sc,
        email_templates={"ir_alert_tabletop": {"name": "Alerta IR", "subject": "[SIM]"}},
    )
    assert len(blocks) == 2
    assert blocks[0]["kind"] == "phase"
    assert blocks[0]["events"][0]["count"] == 2
    assert blocks[1]["kind"] == "email"
