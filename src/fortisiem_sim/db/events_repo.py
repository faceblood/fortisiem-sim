from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

import yaml

from ..loaders import (
    _parse_mitre_fields,
    custom_events_path,
    default_templates_path,
    load_scenario,
    load_templates,
    package_root,
    scenarios_dir,
)
from ..mitre import EVENT_MITRE
from ..models import EventTemplate
import re
from .connection import db_path, get_connection


def _body_for_sim(body: str) -> str:
    if "{{" in body:
        return body
    return re.sub(r"\{(\w+)\}", r"{{\1}}", body)



def _json_loads(raw: str, default: Any) -> Any:
    try:
        return json.loads(raw) if raw else default
    except json.JSONDecodeError:
        return default


def _template_from_row(row: sqlite3.Row, mitre: dict[str, list[str]] | None = None) -> EventTemplate:
    meta = mitre or {}
    tactics = meta.get("tactics", [])
    techniques = meta.get("techniques", [])
    flat = tactics + techniques
    return EventTemplate(
        id=row["id"],
        name=row["name"],
        format=row["format"],
        severity=row["severity"],
        category=row["category"],
        source_system=row["source_system"],
        body=_body_for_sim(row["body"]),
        syslog_hostname=row["syslog_hostname"],
        pri=int(row["pri"]),
        fields=_json_loads(row["fields_json"], []),
        defaults=_json_loads(row["defaults_json"], {}),
        fortisiem_hints=_json_loads(row["fortisiem_hints_json"], {}),
        tags=_json_loads(row["tags_json"], []),
        action=str(row["action"] if "action" in row.keys() else ""),
        ttp=str(row["ttp"] if "ttp" in row.keys() else ""),
        weight=int(row["weight"] if "weight" in row.keys() else 5),
        event_group=str(row["event_group"] if "event_group" in row.keys() else ""),
        mitre=flat,
        mitre_tactics=tactics,
        mitre_techniques=techniques,
    )


def _load_mitre_map(conn: sqlite3.Connection) -> dict[str, dict[str, list[str]]]:
    out: dict[str, dict[str, list[str]]] = {}
    for row in conn.execute(
        "SELECT event_id, kind, value FROM event_mitre ORDER BY event_id, kind, value"
    ):
        bucket = out.setdefault(row["event_id"], {"tactics": [], "techniques": []})
        if row["kind"] == "tactic":
            bucket["tactics"].append(row["value"])
        else:
            bucket["techniques"].append(row["value"])
    return out


def load_all_templates(conn: sqlite3.Connection | None = None) -> dict[str, EventTemplate]:
    own = conn is None
    if own:
        conn = get_connection()
    try:
        mitre_map = _load_mitre_map(conn)
        out: dict[str, EventTemplate] = {}
        for row in conn.execute("SELECT * FROM event_templates ORDER BY id"):
            meta = mitre_map.get(row["id"], {"tactics": [], "techniques": []})
            if not meta["tactics"] and not meta["techniques"]:
                meta = EVENT_MITRE.get(row["id"], meta)
            out[row["id"]] = _template_from_row(row, meta)
        return out
    finally:
        if own:
            conn.close()


def _upsert_mitre(conn: sqlite3.Connection, event_id: str, tactics: list[str], techniques: list[str]) -> None:
    conn.execute("DELETE FROM event_mitre WHERE event_id = ?", (event_id,))
    for value in tactics:
        conn.execute(
            "INSERT INTO event_mitre (event_id, kind, value) VALUES (?, 'tactic', ?)",
            (event_id, value),
        )
    for value in techniques:
        conn.execute(
            "INSERT INTO event_mitre (event_id, kind, value) VALUES (?, 'technique', ?)",
            (event_id, value),
        )


def upsert_event_raw(
    conn: sqlite3.Connection,
    event_id: str,
    raw: dict[str, Any],
    *,
    is_builtin: bool = False,
) -> None:
    from ..mitre import mitre_from_ttp_slug

    tactics, techniques, _ = _parse_mitre_fields(raw)
    ttp = str(raw.get("ttp", "") or "").strip()
    if ttp and not tactics and not techniques:
        mapped = mitre_from_ttp_slug(ttp)
        tactics = mapped.get("tactics", [])
        techniques = mapped.get("techniques", [])
    if not tactics and not techniques:
        meta = EVENT_MITRE.get(event_id, {})
        tactics = meta.get("tactics", [])
        techniques = meta.get("techniques", [])
    conn.execute(
        """
        INSERT INTO event_templates (
            id, name, format, severity, category, source_system, body,
            syslog_hostname, pri, fields_json, defaults_json,
            fortisiem_hints_json, tags_json, action, weight, event_group, ttp,
            is_builtin, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
        ON CONFLICT(id) DO UPDATE SET
            name=excluded.name, format=excluded.format, severity=excluded.severity,
            category=excluded.category, source_system=excluded.source_system, body=excluded.body,
            syslog_hostname=excluded.syslog_hostname, pri=excluded.pri,
            fields_json=excluded.fields_json, defaults_json=excluded.defaults_json,
            fortisiem_hints_json=excluded.fortisiem_hints_json, tags_json=excluded.tags_json,
            action=excluded.action, weight=excluded.weight,
            event_group=excluded.event_group, ttp=excluded.ttp,
            is_builtin=CASE WHEN event_templates.is_builtin = 1 THEN 1 ELSE excluded.is_builtin END,
            updated_at=datetime('now')
        """,
        (
            event_id,
            str(raw.get("name", event_id)),
            str(raw.get("format", "syslog_generic")),
            str(raw.get("severity", "info")),
            str(raw.get("category", "generic")),
            str(raw.get("source_system", "")),
            str(raw.get("body", "")).rstrip("\n"),
            str(raw.get("syslog_hostname", "lab-host")),
            int(raw.get("pri", 134)),
            json.dumps([str(x) for x in raw.get("fields", [])]),
            json.dumps({str(k): str(v) for k, v in (raw.get("defaults") or {}).items()}),
            json.dumps({str(k): str(v) for k, v in (raw.get("fortisiem_hints") or {}).items()}),
            json.dumps([str(x) for x in (raw.get("tags") or [])]),
            str(raw.get("action", "")),
            int(raw.get("weight", 5)),
            str(raw.get("event_group", "")),
            ttp,
            1 if is_builtin else 0,
        ),
    )
    _upsert_mitre(conn, event_id, tactics, techniques)


def _tactic_labels(tactics: list[str]) -> list[dict[str, str]]:
    from ..mitre import tactic_by_id

    out: list[dict[str, str]] = []
    for tid in tactics:
        t = tactic_by_id(tid)
        out.append({
            "id": tid,
            "name": t["name"] if t else tid,
            "slug": t["slug"] if t else "",
        })
    return out


def event_to_detail(tmpl: EventTemplate, *, is_builtin: bool = False, updated_at: str = "") -> dict[str, Any]:
    from ..mitre import event_mitre_meta, event_system_label

    meta = event_mitre_meta(tmpl.id, tmpl)
    tactics = meta.get("tactics", [])
    techniques = meta.get("techniques", [])
    return {
        "id": tmpl.id,
        "name": tmpl.name,
        "format": tmpl.format,
        "system": event_system_label(tmpl),
        "source_system": tmpl.source_system,
        "category": tmpl.category,
        "action": tmpl.action,
        "severity": tmpl.severity,
        "weight": tmpl.weight,
        "event_group": tmpl.event_group,
        "ttp": tmpl.ttp,
        "body": tmpl.body,
        "syslog_hostname": tmpl.syslog_hostname,
        "pri": tmpl.pri,
        "fields": tmpl.fields,
        "defaults": tmpl.defaults,
        "fortisiem_hints": tmpl.fortisiem_hints,
        "tags": tmpl.tags,
        "tactics": tactics,
        "techniques": techniques,
        "tactic_labels": _tactic_labels(tactics),
        "is_builtin": bool(is_builtin),
        "updated_at": updated_at,
    }


def load_event_detail(event_id: str, conn: sqlite3.Connection | None = None) -> dict[str, Any] | None:
    own = conn is None
    if own:
        conn = get_connection()
    try:
        row = conn.execute(
            "SELECT * FROM event_templates WHERE id = ?", (event_id,)
        ).fetchone()
        if not row:
            return None
        mitre_map = _load_mitre_map(conn)
        meta = mitre_map.get(event_id, {"tactics": [], "techniques": []})
        if not meta["tactics"] and not meta["techniques"]:
            meta = EVENT_MITRE.get(event_id, meta)
        tmpl = _template_from_row(row, meta)
        return event_to_detail(
            tmpl,
            is_builtin=bool(row["is_builtin"]),
            updated_at=str(row["updated_at"] or ""),
        )
    finally:
        if own:
            conn.close()


def save_event_from_api(event_id: str, data: dict[str, Any]) -> None:
    tactics = [str(x).strip().upper() for x in (data.get("tactics") or []) if str(x).strip()]
    techniques = [str(x).strip() for x in (data.get("techniques") or []) if str(x).strip()]
    raw: dict[str, Any] = {
        "name": data.get("name", event_id),
        "format": data.get("format", "syslog_generic"),
        "severity": data.get("severity", "info"),
        "category": data.get("category", "generic"),
        "source_system": data.get("source_system", data.get("system", "")),
        "body": data.get("body", ""),
        "syslog_hostname": data.get("syslog_hostname", "lab-host"),
        "pri": int(data.get("pri", 134)),
        "fields": data.get("fields") or [],
        "defaults": data.get("defaults") or {},
        "fortisiem_hints": data.get("fortisiem_hints") or {},
        "tags": data.get("tags") or [],
        "action": data.get("action", ""),
        "weight": int(data.get("weight", 5)),
        "event_group": data.get("event_group", ""),
        "ttp": data.get("ttp", ""),
        "mitre": {"tactics": tactics, "techniques": techniques},
    }
    conn = get_connection()
    try:
        upsert_event_raw(conn, event_id, raw, is_builtin=False)
        conn.commit()
    finally:
        conn.close()


def delete_event(event_id: str) -> bool:
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT is_builtin FROM event_templates WHERE id = ?", (event_id,)
        ).fetchone()
        if not row:
            return False
        if int(row["is_builtin"]):
            raise ValueError("No se puede eliminar un evento builtin")
        conn.execute("DELETE FROM event_templates WHERE id = ?", (event_id,))
        conn.commit()
        return True
    finally:
        conn.close()


def upsert_template(conn: sqlite3.Connection, tmpl: EventTemplate, *, is_builtin: bool = False) -> None:
    raw = {
        "name": tmpl.name,
        "format": tmpl.format,
        "severity": tmpl.severity,
        "category": tmpl.category,
        "source_system": tmpl.source_system,
        "body": tmpl.body,
        "syslog_hostname": tmpl.syslog_hostname,
        "pri": tmpl.pri,
        "fields": tmpl.fields,
        "defaults": tmpl.defaults,
        "fortisiem_hints": tmpl.fortisiem_hints,
        "tags": tmpl.tags,
        "mitre": {"tactics": tmpl.mitre_tactics, "techniques": tmpl.mitre_techniques},
    }
    upsert_event_raw(conn, tmpl.id, raw, is_builtin=is_builtin)


def merge_events_import(
    new_events: dict[str, dict[str, Any]],
    path: Path | None = None,
) -> tuple[list[str], list[str]]:
    conn = get_connection(path)
    added: list[str] = []
    updated: list[str] = []
    try:
        for eid in new_events:
            exists = conn.execute(
                "SELECT 1 FROM event_templates WHERE id = ?", (eid,)
            ).fetchone()
            if exists:
                updated.append(eid)
            else:
                added.append(eid)
            upsert_event_raw(conn, eid, new_events[eid], is_builtin=False)
        conn.commit()
    finally:
        conn.close()
    return added, updated
