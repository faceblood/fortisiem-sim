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




def _table_has_rows(conn: sqlite3.Connection, table: str) -> bool:
    try:
        row = conn.execute(f"SELECT 1 FROM {table} LIMIT 1").fetchone()
        return row is not None
    except sqlite3.OperationalError:
        return False


def _load_from_lab_assets(conn: sqlite3.Connection) -> dict[str, Any] | None:
    if not _table_has_rows(conn, "lab_assets"):
        return None
    firewalls = []
    windows_hosts = []
    linux_hosts = []
    vmware_assets = []
    for r in conn.execute("SELECT * FROM lab_assets ORDER BY sort_order, id"):
        st = (r["source_type"] or "").lower()
        ip = r["ip"]
        rep = r["reporting_ip"] or ip
        if st == "fortigate":
            firewalls.append({
                "name": r["fortigate_devname"] or r["hostname"],
                "devname": r["fortigate_devname"] or r["hostname"],
                "serial": r["fortigate_serial"] or r["serial_number"] or "",
                "src_ip": ip,
                "reporting_ip": rep,
            })
        elif st == "linux":
            linux_hosts.append({
                "hostname": r["hostname"],
                "user": "lab.user",
                "src_ip": ip,
                "reporting_ip": rep,
            })
        elif st == "vmware":
            vmware_assets.append(dict(r))
        elif st == "windows":
            windows_hosts.append({
                "hostname": r["hostname"],
                "user": "lab.user",
                "src_ip": ip,
                "reporting_ip": rep,
            })
    cols = {c[1] for c in conn.execute("PRAGMA table_info(ad_users)")}
    if "email" in cols:
        users = [
            {"username": r["username"], "email": r["email"] or f"{r['username']}@age.local"}
            for r in conn.execute("SELECT username, email FROM ad_users ORDER BY id")
        ]
    else:
        users = [{"username": u, "email": f"{u}@age.local"} for u in [
            r["username"] for r in conn.execute("SELECT username FROM ad_users ORDER BY id")
        ]]
    c2_ips = []
    c2_domains = []
    try:
        c2_ips = [r["ip"] for r in conn.execute("SELECT ip FROM c2_ips ORDER BY id")]
    except sqlite3.OperationalError:
        pass
    try:
        c2_domains = [r["domain"] for r in conn.execute("SELECT domain FROM c2_domains ORDER BY id")]
    except sqlite3.OperationalError:
        pass
    vmware_users = []
    try:
        vmware_users = [
            {
                "username": r["username"],
                "realm": r["realm"],
                "email": r["email"],
                "role": r["role"],
            }
            for r in conn.execute("SELECT username, realm, email, role FROM vmware_users ORDER BY id")
        ]
    except sqlite3.OperationalError:
        pass
    stats = {}
    try:
        stats = {
            "malware_samples": conn.execute("SELECT COUNT(*) n FROM malware_samples").fetchone()["n"],
            "event_templates": conn.execute("SELECT COUNT(*) n FROM event_templates").fetchone()["n"],
            "vpn_templates": conn.execute(
                "SELECT COUNT(*) n FROM event_templates WHERE source_system='fortigate' AND category='vpn'"
            ).fetchone()["n"],
        }
    except sqlite3.OperationalError:
        stats = {}
    ad_row = conn.execute("SELECT primary_domain FROM ad_settings WHERE id = 1").fetchone()
    primary = ad_row["primary_domain"] if ad_row else "age.local"
    domains = [r["domain"] for r in conn.execute("SELECT domain FROM ad_domains ORDER BY id")]
    pools: dict[str, list[str]] = {"src_ips": [], "reporting_ips": []}
    for row in conn.execute("SELECT pool_name, value FROM ip_pool ORDER BY id"):
        pools.setdefault(row["pool_name"], []).append(row["value"])
    c2_row = conn.execute("SELECT default_ip, default_uri FROM c2_settings WHERE id = 1").fetchone()
    c2 = {
        "default_ip": (c2_row["default_ip"] if c2_row else None) or (c2_ips[0] if c2_ips else "203.0.113.50"),
        "default_uri": (c2_row["default_uri"] if c2_row else None) or "https://lab-c2.example/beacon",
        "ips": c2_ips,
        "domains": c2_domains,
        "uris": c2_domains,
    }
    data = {
        "ad": {
            "primary_domain": primary,
            "domains": domains or [primary],
            "users": users,
        },
        "firewalls": firewalls,
        "windows_hosts": windows_hosts,
        "linux_hosts": linux_hosts,
        "vmware_assets": vmware_assets,
        "vmware_users": vmware_users,
        "pools": pools,
        "c2": c2,
        "stats": stats,
        "storage": "sql",
    }
    return _normalize_assets(data)


def _save_lab_assets(conn: sqlite3.Connection, normalized: dict[str, Any]) -> None:
    conn.execute("DELETE FROM lab_assets")
    sort_order = 0
    for fw in normalized.get("firewalls", []):
        conn.execute(
            """
            INSERT INTO lab_assets (
                ip, hostname, os, source_type, reporting_ip, serial_number,
                fortigate_devname, fortigate_serial, sort_order
            ) VALUES (?, ?, 'FortiGate', 'fortigate', ?, ?, ?, ?, ?)
            """,
            (
                fw["src_ip"],
                fw.get("devname") or fw.get("name") or "FGT-LAB",
                fw.get("reporting_ip") or fw["src_ip"],
                fw.get("serial", ""),
                fw.get("devname") or fw.get("name") or "FGT-LAB",
                fw.get("serial", ""),
                sort_order,
            ),
        )
        sort_order += 1
    for host in normalized.get("windows_hosts", []):
        conn.execute(
            """
            INSERT INTO lab_assets (ip, hostname, os, source_type, reporting_ip, sort_order)
            VALUES (?, ?, 'Windows', 'windows', ?, ?)
            """,
            (host["src_ip"], host["hostname"], host.get("reporting_ip") or host["src_ip"], sort_order),
        )
        sort_order += 1
    for host in normalized.get("linux_hosts", []):
        conn.execute(
            """
            INSERT INTO lab_assets (ip, hostname, os, source_type, reporting_ip, sort_order)
            VALUES (?, ?, 'Linux', 'linux', ?, ?)
            """,
            (host["src_ip"], host["hostname"], host.get("reporting_ip") or host["src_ip"], sort_order),
        )
        sort_order += 1
    c2 = normalized.get("c2", {})
    try:
        conn.execute("DELETE FROM c2_ips")
        for i, ip in enumerate(c2.get("ips", [])):
            conn.execute(
                "INSERT INTO c2_ips (ip, is_default) VALUES (?, ?)",
                (ip, 1 if i == 0 else 0),
            )
    except sqlite3.OperationalError:
        pass
    try:
        conn.execute("DELETE FROM c2_domains")
        for domain in c2.get("domains", c2.get("uris", [])):
            conn.execute("INSERT INTO c2_domains (domain) VALUES (?)", (domain,))
    except sqlite3.OperationalError:
        pass
    ad = normalized.get("ad", {})
    cols = {c[1] for c in conn.execute("PRAGMA table_info(ad_users)")}
    conn.execute("DELETE FROM ad_users")
    for u in ad.get("users", []):
        if isinstance(u, dict):
            username = u.get("username", u.get("samaccountname", ""))
            email = u.get("email", f"{username}@age.local")
            domain = u.get("domain", ad.get("primary_domain", "age.local"))
        else:
            username = str(u)
            email = f"{username}@age.local"
            domain = ad.get("primary_domain", "age.local")
        if not username:
            continue
        if "email" in cols:
            conn.execute(
                "INSERT INTO ad_users (username, email, domain) VALUES (?, ?, ?)",
                (username, email, domain),
            )
        else:
            conn.execute("INSERT INTO ad_users (username) VALUES (?)", (username,))


def load_assets_dict(conn: sqlite3.Connection | None = None) -> dict[str, Any]:
    own = conn is None
    if own:
        conn = get_connection()
    try:
        lab = _load_from_lab_assets(conn)
        if lab is not None:
            return lab
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
        cols = {c[1] for c in conn.execute("PRAGMA table_info(ad_users)")}
        user_rows = []
        for u in ad.get("users", []):
            if isinstance(u, dict):
                username = u.get("username", "")
                email = u.get("email", f"{username}@age.local")
                domain = u.get("domain", ad.get("primary_domain", "age.local"))
            else:
                username = str(u)
                email = f"{username}@age.local"
                domain = ad.get("primary_domain", "age.local")
            if not username:
                continue
            if "email" in cols:
                user_rows.append((username, email, domain))
            else:
                user_rows.append((username,))
        if "email" in cols:
            _replace_table_rows(conn, "ad_users", ["username", "email", "domain"], user_rows)
        else:
            _replace_table_rows(conn, "ad_users", ["username"], user_rows)
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
        _save_lab_assets(conn, normalized)
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
