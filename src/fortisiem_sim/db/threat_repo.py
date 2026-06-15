from __future__ import annotations

import random
import sqlite3

from .connection import get_connection


def load_c2_ips(conn: sqlite3.Connection | None = None) -> list[str]:
    own = conn is None
    if own:
        conn = get_connection()
    try:
        try:
            rows = conn.execute("SELECT ip FROM c2_ips ORDER BY id").fetchall()
            if rows:
                return [r["ip"] for r in rows]
        except sqlite3.OperationalError:
            pass
        rows = conn.execute(
            "SELECT value FROM c2_iocs WHERE kind='ip' ORDER BY id"
        ).fetchall()
        return [r["value"] for r in rows] or ["45.9.148.10"]
    finally:
        if own:
            conn.close()


def load_c2_domains(conn: sqlite3.Connection | None = None) -> list[str]:
    own = conn is None
    if own:
        conn = get_connection()
    try:
        try:
            rows = conn.execute("SELECT domain FROM c2_domains ORDER BY id").fetchall()
            if rows:
                return [r["domain"] for r in rows]
        except sqlite3.OperationalError:
            pass
        return ["cdn-update-security.example"]
    finally:
        if own:
            conn.close()


def load_malware_samples(conn: sqlite3.Connection | None = None) -> list[dict[str, str]]:
    own = conn is None
    if own:
        conn = get_connection()
    try:
        try:
            rows = conn.execute(
                "SELECT family, name, type, severity, sha256, filename, extension FROM malware_samples"
            ).fetchall()
            if rows:
                return [dict(r) for r in rows]
        except sqlite3.OperationalError:
            pass
        return [{"name": "Suspicious/EncodedPowerShell", "family": "PowerShell"}]
    finally:
        if own:
            conn.close()


def load_command_pool(pool_name: str, conn: sqlite3.Connection | None = None) -> list[str]:
    from .command_repo import load_commands

    rows = load_commands(pool_name, conn=conn)
    if rows:
        return [r["value"] for r in rows]
    if pool_name == "powershell_encoded":
        return [
            "SQBFAFgAIAAoAE4AZQB3AC0ATwBiAGoAZQBjAHQAIABOAGUAdAAuAFcAZQBiAEMAbABpAGUAbgB0ACkA"
        ]
    return []


def pick_c2_ip(conn: sqlite3.Connection | None = None) -> str:
    ips = load_c2_ips(conn)
    return random.choice(ips)


def pick_c2_domain(conn: sqlite3.Connection | None = None) -> str:
    domains = load_c2_domains(conn)
    return random.choice(domains)


def pick_malware(conn: sqlite3.Connection | None = None) -> dict[str, str]:
    samples = load_malware_samples(conn)
    return random.choice(samples)
