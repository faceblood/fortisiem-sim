from __future__ import annotations

import json
import sqlite3
from typing import Any

from ..activity_chain import ActivityChain, ChainLog, derive_chain_legitimacy
from .connection import get_connection


def _legitimacy_label(raw: str) -> str:
    val = (raw or "").strip().lower()
    if val in {"legit", "legitimate"}:
        return "legitimate"
    if val in {"non-legit", "illegitimate", "non_legit"}:
        return "illegitimate"
    if val == "mixed":
        return "mixed"
    return val or "legitimate"


def _row_to_chain(row: sqlite3.Row, logs: list[ChainLog]) -> ActivityChain:
    return ActivityChain(
        id=row["id"],
        name=row["name"],
        legitimacy=row["legitimacy"],
        logs=logs,
        category=row["category"] or "",
        severity=row["severity"] or "info",
        description=row["description"] or "",
        objective=row["objective"] or "",
        source_system=row["source_system"] or "linux",
        mitre=json.loads(row["mitre_json"] or "[]"),
    )


def step_counts_by_id(conn: sqlite3.Connection | None = None) -> dict[str, int]:
    """Número de logs por cadena (para estimar volumen en escenarios)."""
    own = conn is None
    if own:
        conn = get_connection()
    try:
        rows = conn.execute(
            """
            SELECT chain_id, COUNT(*) AS n
            FROM activity_chain_steps
            GROUP BY chain_id
            """
        ).fetchall()
        return {str(r["chain_id"]): int(r["n"]) for r in rows}
    finally:
        if own:
            conn.close()


def load_chain(chain_id: str, conn: sqlite3.Connection | None = None) -> ActivityChain | None:
    own = conn is None
    if own:
        conn = get_connection()
    try:
        row = conn.execute("SELECT * FROM activity_chains WHERE id = ?", (chain_id,)).fetchone()
        if not row:
            return None
        logs = [
            ChainLog.from_row(s)
            for s in conn.execute(
                """
                SELECT * FROM activity_chain_steps
                WHERE chain_id = ?
                ORDER BY sort_order, id
                """,
                (chain_id,),
            )
        ]
        return _row_to_chain(row, logs)
    finally:
        if own:
            conn.close()


def list_chains(
    conn: sqlite3.Connection | None = None,
    *,
    legitimacy: str = "",
    source_system: str = "",
) -> list[dict[str, Any]]:
    own = conn is None
    if own:
        conn = get_connection()
    try:
        sql = (
            "SELECT c.*, "
            "(SELECT COUNT(*) FROM activity_chain_steps s WHERE s.chain_id = c.id) AS step_count, "
            "(SELECT COUNT(*) FROM activity_chain_steps s WHERE s.chain_id = c.id "
            " AND s.legitimacy IN ('legitimate','legit')) AS legit_log_count, "
            "(SELECT COUNT(*) FROM activity_chain_steps s WHERE s.chain_id = c.id "
            " AND s.legitimacy IN ('illegitimate','non-legit','non_legit')) AS illegit_log_count "
            "FROM activity_chains c WHERE 1=1"
        )
        params: list[str] = []
        if legitimacy:
            if legitimacy == "mixed":
                sql += (
                    " AND (c.legitimacy = 'mixed' OR ("
                    " (SELECT COUNT(*) FROM activity_chain_steps s WHERE s.chain_id = c.id "
                    " AND s.legitimacy IN ('legitimate','legit')) > 0"
                    " AND (SELECT COUNT(*) FROM activity_chain_steps s WHERE s.chain_id = c.id "
                    " AND s.legitimacy IN ('illegitimate','non-legit','non_legit')) > 0))"
                )
            else:
                sql += " AND c.legitimacy = ?"
                params.append(legitimacy)
        if source_system:
            sql += " AND c.source_system = ?"
            params.append(source_system)
        sql += " ORDER BY c.legitimacy, c.name"
        out: list[dict[str, Any]] = []
        for row in conn.execute(sql, params):
            stored = _legitimacy_label(row["legitimacy"])
            legit_n = int(row["legit_log_count"] or 0)
            illeg_n = int(row["illegit_log_count"] or 0)
            if stored == "mixed" or (legit_n > 0 and illeg_n > 0):
                effective = "mixed"
            elif illeg_n > 0 and legit_n == 0:
                effective = "illegitimate"
            else:
                effective = stored if stored != "mixed" else "legitimate"
            out.append({
                "id": row["id"],
                "name": row["name"],
                "legitimacy": row["legitimacy"],
                "effective_legitimacy": effective,
                "category": row["category"],
                "severity": row["severity"],
                "description": row["description"],
                "objective": row["objective"],
                "source_system": row["source_system"],
                "mitre": json.loads(row["mitre_json"] or "[]"),
                "step_count": int(row["step_count"]),
            })
        return out
    finally:
        if own:
            conn.close()


def chain_detail_payload(chain_id: str, conn: sqlite3.Connection | None = None) -> dict[str, Any] | None:
    chain = load_chain(chain_id, conn)
    if not chain:
        return None
    return chain.to_payload()


def upsert_chain(conn: sqlite3.Connection, meta: dict[str, Any], steps: list[dict[str, Any]]) -> None:
    conn.execute(
        """
        INSERT INTO activity_chains (
            id, name, legitimacy, category, severity, description, objective,
            source_system, mitre_json, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
        ON CONFLICT(id) DO UPDATE SET
            name=excluded.name, legitimacy=excluded.legitimacy, category=excluded.category,
            severity=excluded.severity, description=excluded.description, objective=excluded.objective,
            source_system=excluded.source_system, mitre_json=excluded.mitre_json,
            updated_at=datetime('now')
        """,
        (
            meta["id"],
            meta["name"],
            meta.get("legitimacy", "legitimate"),
            meta.get("category", ""),
            meta.get("severity", "info"),
            meta.get("description", ""),
            meta.get("objective", ""),
            meta.get("source_system", "linux"),
            json.dumps(meta.get("mitre", [])),
        ),
    )
    conn.execute("DELETE FROM activity_chain_steps WHERE chain_id = ?", (meta["id"],))
    for step in steps:
        conn.execute(
            """
            INSERT INTO activity_chain_steps (
                chain_id, sort_order, step_kind, event_id, command_ref, command_line,
                min_delay_ms, max_delay_ms, optional, legitimacy
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                meta["id"],
                int(step["sort_order"]),
                step.get("step_kind", "event"),
                step.get("event_id", ""),
                step.get("command_ref", ""),
                step.get("command_line", ""),
                int(step.get("min_delay_ms", 0)),
                int(step.get("max_delay_ms", 0)),
                1 if step.get("optional") else 0,
                _legitimacy_label(step.get("legitimacy", meta.get("legitimacy", "legitimate"))),
            ),
        )


def save_chain_from_api(chain_id: str, data: dict[str, Any]) -> ActivityChain:
    logs_raw = data.get("logs") or data.get("steps") or []
    logs = [
        ChainLog(
            sort_order=int(i + 1 if lg.get("sort_order") is None else lg.get("sort_order")),
            event_id=str(lg.get("event_id", "")).strip(),
            command_line=str(lg.get("command_line", "")).strip(),
            command_ref=str(lg.get("command_ref", "")).strip(),
            step_kind=str(lg.get("step_kind", "event")),
            min_delay_ms=int(lg.get("min_delay_ms", 0) or 0),
            max_delay_ms=int(lg.get("max_delay_ms", 0) or 0),
            optional=bool(lg.get("optional")),
            legitimacy=_legitimacy_label(lg.get("legitimacy", "")),
        )
        for i, lg in enumerate(logs_raw)
        if str(lg.get("event_id", "")).strip()
    ]
    requested = _legitimacy_label(str(data.get("legitimacy", "")))
    if requested == "mixed":
        chain_legit = "mixed"
    else:
        chain_legit = derive_chain_legitimacy(logs, requested or "legitimate")
    meta = {
        "id": chain_id,
        "name": str(data.get("name", chain_id)).strip() or chain_id,
        "legitimacy": chain_legit,
        "category": str(data.get("category", "")).strip(),
        "severity": str(data.get("severity", "info")).strip(),
        "description": str(data.get("description", data.get("objective", ""))).strip(),
        "objective": str(data.get("objective", data.get("description", ""))).strip(),
        "source_system": str(data.get("source_system", "linux")).strip() or "linux",
        "mitre": data.get("mitre") or [],
    }
    steps = []
    for lg in sorted(logs, key=lambda x: x.sort_order):
        d = lg.to_dict()
        if not d["legitimacy"]:
            d["legitimacy"] = chain_legit if chain_legit != "mixed" else "legitimate"
        steps.append(d)
    conn = get_connection()
    try:
        upsert_chain(conn, meta, steps)
        conn.commit()
    finally:
        conn.close()
    result = load_chain(chain_id)
    if not result:
        raise ValueError(f"No se pudo guardar cadena {chain_id}")
    return result


def chain_stats(conn: sqlite3.Connection | None = None) -> dict[str, int]:
    own = conn is None
    if own:
        conn = get_connection()
    try:
        total = conn.execute("SELECT COUNT(*) AS n FROM activity_chains").fetchone()["n"]
        legit = conn.execute(
            "SELECT COUNT(*) AS n FROM activity_chains WHERE legitimacy='legitimate'"
        ).fetchone()["n"]
        illegit = conn.execute(
            "SELECT COUNT(*) AS n FROM activity_chains WHERE legitimacy='illegitimate'"
        ).fetchone()["n"]
        mixed = conn.execute(
            "SELECT COUNT(*) AS n FROM activity_chains WHERE legitimacy='mixed'"
        ).fetchone()["n"]
        steps = conn.execute("SELECT COUNT(*) AS n FROM activity_chain_steps").fetchone()["n"]
        return {
            "chains": int(total),
            "legitimate": int(legit),
            "illegitimate": int(illegit),
            "mixed": int(mixed),
            "steps": int(steps),
        }
    finally:
        if own:
            conn.close()
