from __future__ import annotations

import json
import sqlite3
from typing import Any

from ..assets import _empty_assets, _normalize_assets, default_assets_path
from ..loaders import _load_raw
from .connection import get_connection


def _replace_table_rows(
    conn: sqlite3.Connection,
    table: str,
    columns: list[str],
    rows: list[tuple[Any, ...]],
) -> None:
    conn.execute(f"DELETE FROM {table}")
    if not rows:
        return
    placeholders = ", ".join("?" for _ in columns)
    col_list = ", ".join(columns)
    conn.executemany(
        f"INSERT INTO {table} ({col_list}) VALUES ({placeholders})",
        rows,
    )


def load_assets_dict(conn: sqlite3.Connection | None = None) -> dict[str, Any]:
    own = conn is None
    if own:
        conn = get_connection()
    try:
        ad_row = conn.execute("SELECT primary_domain FROM ad_settings WHERE id = 1").fetchone()
        if not ad_row:
            return _empty_assets()
        domains = [
            r["domain"]
            for r in conn.execute("SELECT domain FROM ad_domains ORDER BY id")
        ]
        users = [
            r["username"]
            for r in conn.execute("SELECT username FROM ad_users ORDER BY id")
        ]
        firewalls = [
            {
                "name": r["name"],
                "devname": r["devname"],
                "serial": r["serial"],
                "src_ip": r["src_ip"],
                "reporting_ip": r["reporting_ip"],
            }
            for r in conn.execute(
                "SELECT * FROM firewalls ORDER BY sort_order, id"
            )
        ]
        windows_hosts = [
            {
                "hostname": r["hostname"],
                "user": r["user"],
                "src_ip": r["src_ip"],
                "reporting_ip": r["reporting_ip"],
            }
            for r in conn.execute(
                "SELECT * FROM hosts WHERE os_type = 'windows' ORDER BY sort_order, id"
            )
        ]
        linux_hosts = [
            {
                "hostname": r["hostname"],
                "user": r["user"],
                "src_ip": r["src_ip"],
                "reporting_ip": r["reporting_ip"],
            }
            for r in conn.execute(
                "SELECT * FROM hosts WHERE os_type = 'linux' ORDER BY sort_order, id"
            )
        ]
        pools: dict[str, list[str]] = {"src_ips": [], "reporting_ips": []}
        for row in conn.execute("SELECT pool_name, value FROM ip_pool ORDER BY id"):
            pools.setdefault(row["pool_name"], []).append(row["value"])
        c2_row = conn.execute("SELECT default_ip, default_uri FROM c2_settings WHERE id = 1").fetchone()
        c2_ips = [
            r["value"]
            for r in conn.execute("SELECT value FROM c2_iocs WHERE kind = 'ip' ORDER BY id")
        ]
        c2_uris = [
            r["value"]
            for r in conn.execute("SELECT value FROM c2_iocs WHERE kind = 'uri' ORDER BY id")
        ]
        c2 = {
            "default_ip": c2_row["default_ip"] if c2_row else "203.0.113.50",
            "default_uri": c2_row["default_uri"] if c2_row else "https://lab-c2.example/beacon",
            "ips": c2_ips,
            "uris": c2_uris,
        }
        data = {
            "ad": {
                "primary_domain": ad_row["primary_domain"],
                "domains": domains or [ad_row["primary_domain"]],
                "users": users,
            },
            "firewalls": firewalls,
            "windows_hosts": windows_hosts,
            "linux_hosts": linux_hosts,
            "pools": pools,
            "c2": c2,
        }
        return _normalize_assets(data)
    finally:
        if own:
            conn.close()


def load_assets_dict_with_smtp(conn: sqlite3.Connection | None = None) -> dict[str, Any]:
    from .email_repo import load_smtp_settings

    data = load_assets_dict(conn)
    data["smtp"] = load_smtp_settings(conn)
    return data


def save_assets_dict(data: dict[str, Any], conn: sqlite3.Connection | None = None) -> None:
    from .email_repo import save_smtp_settings

    smtp = data.get("smtp")
    normalized = _normalize_assets(data)
    own = conn is None
    if own:
        conn = get_connection()
    try:
        ad = normalized["ad"]
        conn.execute(
            """
            INSERT INTO ad_settings (id, primary_domain) VALUES (1, ?)
            ON CONFLICT(id) DO UPDATE SET primary_domain = excluded.primary_domain
            """,
            (ad["primary_domain"],),
        )
        _replace_table_rows(
            conn,
            "ad_domains",
            ["domain"],
            [(d,) for d in ad.get("domains", [])],
        )
        _replace_table_rows(
            conn,
            "ad_users",
            ["username"],
            [(u,) for u in ad.get("users", [])],
        )
        _replace_table_rows(
            conn,
            "firewalls",
            ["sort_order", "name", "devname", "serial", "src_ip", "reporting_ip"],
            [
                (
                    i,
                    fw["name"],
                    fw["devname"],
                    fw["serial"],
                    fw["src_ip"],
                    fw["reporting_ip"],
                )
                for i, fw in enumerate(normalized.get("firewalls", []))
            ],
        )
        host_rows: list[tuple[Any, ...]] = []
        for i, host in enumerate(normalized.get("windows_hosts", [])):
            host_rows.append(
                (i, "windows", host["hostname"], host["user"], host["src_ip"], host["reporting_ip"])
            )
        offset = len(host_rows)
        for i, host in enumerate(normalized.get("linux_hosts", [])):
            host_rows.append(
                (offset + i, "linux", host["hostname"], host["user"], host["src_ip"], host["reporting_ip"])
            )
        _replace_table_rows(
            conn,
            "hosts",
            ["sort_order", "os_type", "hostname", "user", "src_ip", "reporting_ip"],
            host_rows,
        )
        pool_rows: list[tuple[str, str]] = []
        for pool_name, values in normalized.get("pools", {}).items():
            if pool_name.startswith("c2_"):
                continue
            for value in values:
                pool_rows.append((pool_name, value))
        _replace_table_rows(conn, "ip_pool", ["pool_name", "value"], pool_rows)
        c2 = normalized["c2"]
        conn.execute(
            """
            INSERT INTO c2_settings (id, default_ip, default_uri) VALUES (1, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                default_ip = excluded.default_ip,
                default_uri = excluded.default_uri
            """,
            (c2["default_ip"], c2["default_uri"]),
        )
        c2_rows = [("ip", ip) for ip in c2.get("ips", [])] + [("uri", uri) for uri in c2.get("uris", [])]
        _replace_table_rows(conn, "c2_iocs", ["kind", "value"], c2_rows)
        if smtp is not None:
            save_smtp_settings(smtp, conn=conn)
        conn.commit()
    finally:
        if own:
            conn.close()


def seed_assets_from_yaml(conn: sqlite3.Connection) -> None:
    path = default_assets_path()
    if not path.exists():
        save_assets_dict(_empty_assets(), conn=conn)
        return
    data = _load_raw(path)
    save_assets_dict(data, conn=conn)
