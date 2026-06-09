from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

import yaml

from ..assets import assets_to_actors, scenario_to_yaml
from ..loaders import _parse_actors, _parse_event, _parse_phase, load_scenario, scenarios_dir
from ..mitre import guess_tactic_from_phase, tactic_by_id
from ..models import Scenario, ScenarioPhase
from .connection import get_connection


def _slugify(name: str) -> str:
    return str(name).strip().replace(" ", "-").lower()


def list_scenario_ids(conn: sqlite3.Connection | None = None) -> list[str]:
    own = conn is None
    if own:
        conn = get_connection()
    try:
        return [
            r["id"]
            for r in conn.execute("SELECT id FROM scenarios ORDER BY name")
        ]
    finally:
        if own:
            conn.close()


def resolve_scenario_id(value: str, conn: sqlite3.Connection | None = None) -> str:
    candidate = value.strip()
    if not candidate:
        raise ValueError("Escenario vacío")
    own = conn is None
    if own:
        conn = get_connection()
    try:
        ids = list_scenario_ids(conn)
        stem = candidate.lower().removesuffix(".yml").removesuffix(".yaml").removesuffix(".json")
        if stem in ids:
            return stem
        exact = [i for i in ids if i.lower() == stem]
        if exact:
            return exact[0]
        partial = [i for i in ids if stem in i.lower()]
        if len(partial) == 1:
            return partial[0]
        if len(partial) > 1:
            raise ValueError(f"'{value}' es ambiguo. Coincidencias: {', '.join(partial)}")
        names = ", ".join(ids) or "(ninguno)"
        raise ValueError(f"Escenario '{value}' no encontrado. Disponibles: {names}")
    finally:
        if own:
            conn.close()


def load_scenario_model(scenario_id: str, assets: dict[str, Any] | None = None) -> Scenario:
    conn = get_connection()
    try:
        row = conn.execute("SELECT * FROM scenarios WHERE id = ?", (scenario_id,)).fetchone()
        if not row:
            raise ValueError(f"Escenario no encontrado: {scenario_id}")
        phases: list[ScenarioPhase] = []
        for ph_row in conn.execute(
            """
            SELECT * FROM scenario_phases
            WHERE scenario_id = ?
            ORDER BY sort_order, id
            """,
            (scenario_id,),
        ):
            events = [
                _parse_event(
                    {
                        "id": ev["event_id"],
                        "count": ev["count"],
                        "actor": ev["actor"],
                        "overrides": json.loads(ev["overrides_json"] or "{}"),
                    }
                )
                for ev in conn.execute(
                    """
                    SELECT * FROM scenario_phase_events
                    WHERE phase_id = ?
                    ORDER BY sort_order, id
                    """,
                    (ph_row["id"],),
                )
            ]
            phases.append(
                ScenarioPhase(
                    name=ph_row["slug"],
                    description=ph_row["description"],
                    events=events,
                )
            )
        if row["use_config_actors"]:
            if assets is None:
                from .assets_repo import load_assets_dict

                assets = load_assets_dict(conn)
            actors = _parse_actors(assets_to_actors(assets))
        else:
            actors = _parse_actors(json.loads(row["actors_json"] or "{}"))
        metadata = json.loads(row["metadata_json"] or "{}")
        return Scenario(
            name=row["name"],
            description=row["description"],
            org_id=int(row["org_id"]),
            actors=actors,
            phases=phases,
            metadata=metadata,
            timeline_minutes=int(row["timeline_minutes"]),
        )
    finally:
        conn.close()


def builder_payload(scenario_id: str, assets: dict[str, Any] | None = None) -> dict[str, Any]:
    sc = load_scenario_model(scenario_id, assets=assets)
    conn = get_connection()
    try:
        row = conn.execute("SELECT * FROM scenarios WHERE id = ?", (scenario_id,)).fetchone()
        phases_out = []
        for ph_row in conn.execute(
            """
            SELECT * FROM scenario_phases
            WHERE scenario_id = ?
            ORDER BY sort_order, id
            """,
            (scenario_id,),
        ):
            mitre_tactic = ph_row["mitre_tactic"] or ""
            mitre_techniques = json.loads(ph_row["mitre_techniques_json"] or "[]")
            if not mitre_tactic:
                mitre_tactic = guess_tactic_from_phase(ph_row["slug"], ph_row["description"])
            tactic = tactic_by_id(mitre_tactic) if mitre_tactic else None
            phase_name = tactic["slug"] if tactic else ph_row["slug"]
            events = [
                {
                    "id": ev["event_id"],
                    "count": ev["count"],
                    "actor": ev["actor"] or "",
                }
                for ev in conn.execute(
                    """
                    SELECT * FROM scenario_phase_events
                    WHERE phase_id = ?
                    ORDER BY sort_order, id
                    """,
                    (ph_row["id"],),
                )
            ]
            phases_out.append({
                "name": phase_name,
                "description": ph_row["description"],
                "mitre_tactic": mitre_tactic,
                "mitre_techniques": mitre_techniques,
                "events": events,
            })
        actor_keys = list(sc.actors.profiles.keys()) if sc.actors.profiles else []
        return {
            "id": scenario_id,
            "name": sc.name,
            "description": sc.description,
            "org_id": sc.org_id,
            "timeline_minutes": sc.timeline_minutes,
            "use_config_actors": bool(row["use_config_actors"]),
            "actor_keys": actor_keys,
            "phases": phases_out,
        }
    finally:
        conn.close()


def save_from_builder(
    scenario: dict[str, Any],
    assets: dict[str, Any] | None = None,
) -> str:
    name = str(scenario.get("name", "custom")).strip().replace(" ", "-").lower()
    if not name:
        raise ValueError("El escenario necesita un nombre")
    scenario_id = _slugify(scenario.get("id") or name)
    use_config = bool(scenario.get("use_config_actors", True))
    actors_json = None
    if not use_config and scenario.get("actors"):
        actors_json = json.dumps(scenario["actors"])
    metadata = scenario.get("metadata") or {
        "classification": "simulated-only",
        "created_by": "fortisiem-sim-gui",
    }
    conn = get_connection()
    try:
        conn.execute(
            """
            INSERT INTO scenarios (
                id, name, description, org_id, timeline_minutes,
                use_config_actors, metadata_json, actors_json, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
            ON CONFLICT(id) DO UPDATE SET
                name = excluded.name,
                description = excluded.description,
                org_id = excluded.org_id,
                timeline_minutes = excluded.timeline_minutes,
                use_config_actors = excluded.use_config_actors,
                metadata_json = excluded.metadata_json,
                actors_json = excluded.actors_json,
                updated_at = datetime('now')
            """,
            (
                scenario_id,
                scenario.get("name", name),
                scenario.get("description", ""),
                int(scenario.get("org_id", 1)),
                int(scenario.get("timeline_minutes", 0)),
                1 if use_config else 0,
                json.dumps(metadata),
                actors_json,
            ),
        )
        conn.execute("DELETE FROM scenario_phases WHERE scenario_id = ?", (scenario_id,))
        for pi, ph in enumerate(scenario.get("phases", [])):
            tactic = tactic_by_id(str(ph.get("mitre_tactic", ""))) if ph.get("mitre_tactic") else None
            slug = tactic["slug"] if tactic else str(ph.get("name", f"phase_{pi}")).strip().replace(" ", "_")
            cur = conn.execute(
                """
                INSERT INTO scenario_phases (
                    scenario_id, slug, description, mitre_tactic,
                    mitre_techniques_json, sort_order
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    scenario_id,
                    slug,
                    ph.get("description", ""),
                    ph.get("mitre_tactic", ""),
                    json.dumps(ph.get("mitre_techniques") or []),
                    pi,
                ),
            )
            phase_id = cur.lastrowid
            for ei, ev in enumerate(ph.get("events", [])):
                conn.execute(
                    """
                    INSERT INTO scenario_phase_events (
                        phase_id, event_id, count, actor, overrides_json, sort_order
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        phase_id,
                        ev["id"],
                        int(ev.get("count", 1)),
                        str(ev.get("actor", "")),
                        json.dumps(ev.get("overrides") or {}),
                        ei,
                    ),
                )
        conn.commit()
    finally:
        conn.close()
    return scenario_id


def seed_scenarios_from_yaml(conn: sqlite3.Connection) -> None:
    base = scenarios_dir()
    if not base.exists():
        return
    for path in sorted(base.glob("*.y*ml")):
        sc = load_scenario(path)
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        phases_raw = raw.get("phases", {}) if isinstance(raw.get("phases"), dict) else {}
        builder_phases = []
        for ph in sc.phases:
            raw_ph = phases_raw.get(ph.name, {}) if isinstance(phases_raw, dict) else {}
            mitre_raw = raw_ph.get("mitre", {}) if isinstance(raw_ph, dict) else {}
            builder_phases.append({
                "name": ph.name,
                "description": ph.description,
                "mitre_tactic": str(mitre_raw.get("tactic", "")) if mitre_raw else "",
                "mitre_techniques": mitre_raw.get("techniques", []) if mitre_raw else [],
                "events": [
                    {"id": e.id, "count": e.count, "actor": e.actor or ""}
                    for e in ph.events
                ],
            })
        save_from_builder(
            {
                "id": path.stem,
                "name": sc.name,
                "description": sc.description,
                "org_id": sc.org_id,
                "timeline_minutes": sc.timeline_minutes,
                "use_config_actors": not bool(raw.get("actors")),
                "actors": raw.get("actors"),
                "metadata": sc.metadata,
                "phases": builder_phases,
            },
            assets=None,
        )


def export_scenario_yaml(scenario_id: str, assets: dict[str, Any] | None = None) -> str:
    payload = builder_payload(scenario_id, assets=assets)
    if assets is None:
        from .assets_repo import load_assets_dict

        assets = load_assets_dict()
    doc = {
        "name": payload["name"],
        "description": payload["description"],
        "org_id": payload["org_id"],
        "timeline_minutes": payload["timeline_minutes"],
        "use_config_actors": payload["use_config_actors"],
        "phases": payload["phases"],
    }
    return scenario_to_yaml(doc, assets if payload["use_config_actors"] else None)
