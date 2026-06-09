from __future__ import annotations

from pathlib import Path

from fortisiem_sim.mitre import (
    EVENT_MITRE,
    build_event_catalog,
    events_for_tactic,
    guess_tactic_from_phase,
    index_events_by_tactic,
    list_tactics,
    tactic_by_id,
)


def test_list_tactics_has_enterprise_kill_chain():
    tactics = list_tactics()
    ids = {t["id"] for t in tactics}
    assert "TA0001" in ids
    assert "TA0002" in ids
    assert "TA0040" in ids
    assert len(tactics) >= 14


def test_tactic_by_id_and_slug():
    t = tactic_by_id("TA0001")
    assert t and t["slug"] == "initial_access"
    assert tactic_by_id("initial_access")["id"] == "TA0001"


def test_guess_tactic_from_ransomware_phase():
    assert guess_tactic_from_phase("recon_and_access", "") == "TA0001"
    assert guess_tactic_from_phase("lateral_movement", "") == "TA0008"


def test_all_templates_mapped_to_mitre():
    from fortisiem_sim.loaders import load_templates

    templates = load_templates(Path(__file__).resolve().parent.parent / "templates" / "events.yaml")
    missing = [eid for eid in templates if eid not in EVENT_MITRE]
    assert missing == [], f"Eventos sin mapeo MITRE: {missing}"


def test_events_for_tactic_initial_access():
    ids = events_for_tactic("TA0001")
    assert "login_success" in ids
    assert "vpn_login_foreign_country" in ids
    assert "suspicious_powershell_simulated" not in ids


def test_build_event_catalog_and_index():
    from fortisiem_sim.loaders import load_templates

    templates = load_templates(Path(__file__).resolve().parent.parent / "templates" / "events.yaml")
    catalog = build_event_catalog(templates)
    by_tactic = index_events_by_tactic(catalog)
    assert len(catalog) == len(templates)
    assert "login_failed" in by_tactic["TA0001"]
    assert "login_failed" in by_tactic["TA0006"]


def test_suggested_events_exist_in_templates():
    from fortisiem_sim.loaders import load_templates

    templates = load_templates(Path(__file__).resolve().parent.parent / "templates" / "events.yaml")
    for tactic in list_tactics():
        for ev in tactic.get("suggested_events", []):
            assert ev["id"] in templates, f"{tactic['id']}: missing event {ev['id']}"
