from __future__ import annotations

import sqlite3

from .connection import get_connection


def list_step_scenario_ids(conn: sqlite3.Connection | None = None) -> list[str]:
    own = conn is None
    if own:
        conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT DISTINCT scenario_id FROM scenario_steps ORDER BY scenario_id"
        ).fetchall()
        return [r["scenario_id"] for r in rows]
    finally:
        if own:
            conn.close()


def load_steps_builder_payload(scenario_id: str, conn: sqlite3.Connection | None = None) -> dict:
    own = conn is None
    if own:
        conn = get_connection()
    try:
        row = conn.execute("SELECT * FROM scenarios WHERE id=?", (scenario_id,)).fetchone()
        steps = conn.execute(
            "SELECT * FROM scenario_steps WHERE scenario_id=? ORDER BY step_num",
            (scenario_id,),
        ).fetchall()
        if not steps:
            raise ValueError(f"scenario_steps vacío: {scenario_id}")
        phases: dict[str, dict] = {}
        for s in steps:
            phase_key = s["phase"] or "campaign"
            if phase_key not in phases:
                phases[phase_key] = {
                    "name": phase_key.replace("-", "_"),
                    "description": f"SQL campaign {scenario_id} · {phase_key}",
                    "mitre_tactic": "",
                    "mitre_techniques": [],
                    "events": [],
                }
            event_id = s["event_id"] or _resolve_event_id(conn, s["source_system"], s["category"], s["event_hint"])
            phases[phase_key]["events"].append({
                "id": event_id,
                "count": int(s["repeat_count"] or 1),
                "actor": s["user_role"] or s["src_role"] or "",
            })
        return {
            "id": scenario_id,
            "name": row["name"] if row else scenario_id,
            "description": row["description"] if row else "",
            "org_id": int(row["org_id"]) if row else 1,
            "timeline_minutes": 0,
            "use_config_actors": True,
            "actor_keys": [],
            "phases": list(phases.values()),
            "source": "scenario_steps",
        }
    finally:
        if own:
            conn.close()


def _resolve_event_id(conn: sqlite3.Connection, source: str, category: str, hint: str) -> str:
    if not hint:
        return ""
    row = conn.execute(
        "SELECT id FROM event_templates WHERE source_system=? AND category=? AND name=? LIMIT 1",
        (source, category, hint),
    ).fetchone()
    if row:
        return row["id"]
    row = conn.execute(
        "SELECT id FROM event_templates WHERE name=? LIMIT 1",
        (hint,),
    ).fetchone()
    return row["id"] if row else hint.replace(" ", "_").lower()
