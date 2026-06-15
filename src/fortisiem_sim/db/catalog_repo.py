from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from .connection import get_connection


@dataclass
class CatalogTemplate:
    id: str
    source: str
    category: str
    event_name: str
    severity: str
    action: str
    weight: int
    template: str


def load_sender_templates(
    conn: sqlite3.Connection | None = None,
    *,
    source: str = "",
    category: str = "",
) -> list[CatalogTemplate]:
    own = conn is None
    if own:
        conn = get_connection()
    try:
        sql = (
            "SELECT id, source_system, category, name, severity, "
            "COALESCE(action, '') AS action, COALESCE(weight, 5) AS weight, body "
            "FROM event_templates WHERE 1=1"
        )
        params: list[str] = []
        if source:
            sql += " AND source_system=?"
            params.append(source)
        if category:
            sql += " AND category=?"
            params.append(category)
        sql += " ORDER BY id"
        rows = conn.execute(sql, params).fetchall()
        out: list[CatalogTemplate] = []
        for r in rows:
            if not r["source_system"]:
                continue
            out.append(
                CatalogTemplate(
                    id=r["id"],
                    source=r["source_system"],
                    category=r["category"],
                    event_name=r["name"],
                    severity=r["severity"],
                    action=r["action"] or "detect",
                    weight=int(r["weight"]),
                    template=r["body"],
                )
            )
        return out
    finally:
        if own:
            conn.close()


def upsert_catalog_event(conn: sqlite3.Connection, row: dict) -> None:
    tags = row.get("tags", "")
    tags_json = "[]"
    if tags:
        import json
        tags_json = json.dumps([t.strip() for t in tags.split(",") if t.strip()])
    conn.execute(
        """
        INSERT INTO event_templates (
            id, name, format, severity, category, source_system, body,
            syslog_hostname, pri, fields_json, defaults_json,
            fortisiem_hints_json, tags_json, action, weight, event_group, ttp,
            is_builtin, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, '[]', '{}', '{}', ?, ?, ?, ?, ?, 1, datetime('now'))
        ON CONFLICT(id) DO UPDATE SET
            name=excluded.name, format=excluded.format, severity=excluded.severity,
            category=excluded.category, source_system=excluded.source_system, body=excluded.body,
            tags_json=excluded.tags_json, action=excluded.action, weight=excluded.weight,
            event_group=excluded.event_group, ttp=excluded.ttp, updated_at=datetime('now')
        """,
        (
            row["id"],
            row["event_name"],
            row.get("format", "fortigate" if row.get("source") == "fortigate" else "syslog_generic"),
            row.get("severity", "medium"),
            row.get("category", "generic"),
            row.get("source", ""),
            row["template"],
            row.get("syslog_hostname", "{{devname}}" if row.get("source") == "fortigate" else "{{hostname}}"),
            int(row.get("pri", 189 if row.get("source") == "fortigate" else 134)),
            tags_json,
            row.get("action", ""),
            int(row.get("weight", 5)),
            row.get("event_group", ""),
            row.get("ttp", ""),
        ),
    )
