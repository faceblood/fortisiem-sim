"""Unified flat render context built from SQLite lab inventory."""
from __future__ import annotations

import random
import sqlite3
from datetime import datetime

from .connection import get_connection
from .lab_repo import load_ad_users, load_all_assets, pick_asset
from .threat_repo import load_command_pool, pick_c2_domain, pick_c2_ip, pick_malware
from .command_repo import pick_linux_command

_VPN_ASSIGNED_POOL = [f"10.212.134.{i}" for i in range(50, 200)]
_COUNTRIES = ["ES", "US", "DE", "FR", "GB", "NL", "IT", "PL"]


def _random_attacker_ip(conn: sqlite3.Connection) -> str:
    rows = conn.execute(
        "SELECT value FROM ip_pool WHERE pool_name='src_ips' ORDER BY RANDOM() LIMIT 1"
    ).fetchone()
    if rows:
        return rows["value"]
    assets = load_all_assets(conn)
    externals = [a.ip for a in assets if a.source_type.lower() != "fortigate"]
    if externals:
        return random.choice(externals)
    return f"198.51.100.{random.randint(10, 250)}"


def build_send_context(
    conn: sqlite3.Connection | None = None,
    *,
    overrides: dict[str, str] | None = None,
) -> dict[str, str]:
    """Load lab inventory from SQL and return a flat placeholder dict."""
    own = conn is None
    if own:
        conn = get_connection()
    overrides = dict(overrides or {})
    try:
        assets = load_all_assets(conn)
        users = load_ad_users(conn)
        user = random.choice(users) if users else None
        fortigate = pick_asset(assets, "fortigate")
        victim = pick_asset(assets, "windows", fortigate)
        c2 = pick_c2_ip(conn)
        malware = pick_malware(conn)
        encoded = load_command_pool("powershell_encoded", conn)
        linux_cmd = pick_linux_command(conn=conn)
        vmware_users = []
        try:
            vmware_users = [
                r["username"]
                for r in conn.execute("SELECT username FROM vmware_users ORDER BY id").fetchall()
            ]
        except sqlite3.OperationalError:
            pass

        attacker = overrides.get("attacker_ip") or overrides.get("src_ip") or _random_attacker_ip(conn)
        remote = (
            overrides.get("remote_access_ip")
            or overrides.get("vpn_remote_ip")
            or attacker
        )
        gateway = overrides.get("vpn_gateway_ip") or fortigate.ip
        assigned = overrides.get("vpn_assigned_ip") or random.choice(_VPN_ASSIGNED_POOL)
        victim_ip = overrides.get("victim_ip") or victim.ip

        now = datetime.now()
        username = overrides.get("username") or overrides.get("user") or (user.username if user else "jgarcia")
        email = overrides.get("email") or (user.email if user else f"{username}@age.local")
        domain = overrides.get("domain") or (user.domain if user else "age.local")

        ctx: dict[str, str] = {
            "user": username,
            "username": username,
            "email": email,
            "domain": domain,
            "src_ip": attacker,
            "remote_access_ip": remote,
            "vpn_remote_ip": remote,
            "vpn_gateway_ip": gateway,
            "vpn_assigned_ip": assigned,
            "victim_ip": victim_ip,
            "dst_ip": c2,
            "c2_ip": c2,
            "c2_domain": pick_c2_domain(conn),
            "devname": overrides.get("devname") or fortigate.fortigate_devname or fortigate.hostname,
            "devserial": overrides.get("devserial") or fortigate.fortigate_serial or fortigate.serial_number,
            "fortigate_hostname": overrides.get("fortigate_hostname")
            or fortigate.fortigate_devname
            or fortigate.hostname,
            "fortigate_serial": overrides.get("fortigate_serial")
            or fortigate.fortigate_serial
            or fortigate.serial_number,
            "reporting_ip": overrides.get("reporting_ip") or fortigate.reporting_ip or fortigate.ip,
            "hostname": victim.hostname,
            "malware_name": malware.get("name", "Generic.Malware"),
            "malware_family": malware.get("family", "Generic"),
            "command_line": linux_cmd["value"],
            "command_legitimacy": linux_cmd["legitimacy"],
            "command_category": linux_cmd["category"],
            "vmware_user": random.choice(vmware_users) if vmware_users else "administrator",
            "country": overrides.get("country") or random.choice(_COUNTRIES),
            "date": now.strftime("%Y-%m-%d"),
            "time": now.strftime("%H:%M:%S"),
            "tunnel_id": str(random.randint(1000, 9999)),
        }
        ctx.update(overrides)
        return ctx
    finally:
        if own:
            conn.close()


def merge_sql_context(
    base: dict[str, str],
    *,
    overrides: dict[str, str] | None = None,
    conn: sqlite3.Connection | None = None,
) -> dict[str, str]:
    """Enrich an existing render context with SQL-backed lab values."""
    seed = dict(base)
    if overrides:
        seed.update(overrides)
    sql_ctx = build_send_context(conn, overrides=seed)
    merged = dict(base)
    for key, value in sql_ctx.items():
        if value:
            merged[key] = value
    if overrides:
        merged.update(overrides)
    return merged
