from __future__ import annotations

import csv
import json
import sqlite3
from pathlib import Path

from .catalog_repo import upsert_catalog_event
from .events_repo import _upsert_mitre
from ..mitre import mitre_from_ttp_slug
from .connection import get_connection, init_schema
from .lab_repo import upsert_ad_user, upsert_lab_asset


def _read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _default_csv_root() -> Path:
    here = Path(__file__).resolve().parents[3]
    sibling = here.parent / "fortisiem-synthetic-senders"
    if sibling.exists():
        return sibling
    alt = here.parent / "fortisiem-simple-log-campaign"
    if alt.exists():
        return alt
    return here


def import_config(conn: sqlite3.Connection, base: Path) -> dict[str, int]:
    counts: dict[str, int] = {}

    for i, row in enumerate(_read_csv(base / "config" / "assets.csv")):
        upsert_lab_asset(conn, row, sort_order=i)
    counts["lab_assets"] = conn.execute("SELECT COUNT(*) AS n FROM lab_assets").fetchone()["n"]

    for row in _read_csv(base / "config" / "users_ad.csv"):
        upsert_ad_user(conn, row["samaccountname"].strip(), row.get("email", "").strip())
    counts["ad_users"] = conn.execute("SELECT COUNT(*) AS n FROM ad_users").fetchone()["n"]

    conn.execute("DELETE FROM vmware_users")
    for row in _read_csv(base / "config" / "vmware_users.csv"):
        conn.execute(
            "INSERT OR REPLACE INTO vmware_users (username, realm, email, role) VALUES (?, ?, ?, ?)",
            (row["username"], row.get("realm", "vsphere.local"), row.get("email", ""), row.get("role", "")),
        )
    counts["vmware_users"] = conn.execute("SELECT COUNT(*) AS n FROM vmware_users").fetchone()["n"]

    conn.execute("DELETE FROM c2_ips")
    for i, row in enumerate(_read_csv(base / "config" / "c2_ips.csv")):
        conn.execute(
            "INSERT INTO c2_ips (ip, asn, country, threat_family, confidence, is_default) VALUES (?, ?, ?, ?, ?, ?)",
            (
                row["ip"],
                row.get("asn", ""),
                row.get("country", ""),
                row.get("threat_family", ""),
                row.get("confidence", "medium"),
                1 if i == 0 else 0,
            ),
        )
    counts["c2_ips"] = conn.execute("SELECT COUNT(*) AS n FROM c2_ips").fetchone()["n"]

    conn.execute("DELETE FROM c2_domains")
    for row in _read_csv(base / "config" / "c2_domains.csv"):
        conn.execute(
            "INSERT INTO c2_domains (domain, threat_family, category, confidence) VALUES (?, ?, ?, ?)",
            (row["domain"], row.get("threat_family", ""), row.get("category", ""), row.get("confidence", "medium")),
        )
    counts["c2_domains"] = conn.execute("SELECT COUNT(*) AS n FROM c2_domains").fetchone()["n"]

    conn.execute("DELETE FROM malware_samples")
    for row in _read_csv(base / "config" / "malware_samples.csv"):
        conn.execute(
            "INSERT INTO malware_samples (family, name, type, severity, sha256, filename, extension) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                row.get("family", ""),
                row.get("name", ""),
                row.get("type", ""),
                row.get("severity", "high"),
                row.get("sha256", ""),
                row.get("filename", ""),
                row.get("extension", ""),
            ),
        )
    counts["malware_samples"] = conn.execute("SELECT COUNT(*) AS n FROM malware_samples").fetchone()["n"]

    from .command_repo import upsert_command

    for row in _read_csv(base / "config" / "powershell_encoded_commands.csv"):
        val = row.get("encoded_command", "").strip()
        if val:
            upsert_command(
                conn,
                pool_name="powershell_encoded",
                value=val,
                legitimacy="illegitimate",
                category="powershell",
                description="Encoded PowerShell (Windows)",
            )

    conn.execute("DELETE FROM command_pool WHERE pool_name='linux_shell'")
    linux_rows = _read_csv(base / "config" / "linux_commands.csv")
    for row in linux_rows:
        cmd = row.get("command", "").strip()
        if not cmd:
            continue
        upsert_command(
            conn,
            pool_name="linux_shell",
            value=cmd,
            legitimacy=row.get("legitimacy", "").strip().lower(),
            category=row.get("category", "").strip(),
            description=row.get("description", "").strip(),
        )
    counts["command_pool"] = conn.execute("SELECT COUNT(*) AS n FROM command_pool").fetchone()["n"]
    counts["linux_commands"] = conn.execute(
        "SELECT COUNT(*) AS n FROM command_pool WHERE pool_name='linux_shell'"
    ).fetchone()["n"]
    return counts


def import_log_templates(conn: sqlite3.Connection, base: Path) -> int:
    repo = base / "log_repository"
    n = 0
    for path in sorted(repo.rglob("*.csv")):
        if path.parent.name == "campaigns":
            continue
        for row in _read_csv(path):
            if "template" not in row or "id" not in row:
                continue
            upsert_catalog_event(conn, row)
            ttp = row.get("ttp", "")
            meta = mitre_from_ttp_slug(ttp)
            if meta.get("tactics") or meta.get("techniques"):
                _upsert_mitre(conn, row["id"], meta.get("tactics", []), meta.get("techniques", []))
            n += 1
    # Geo VPN event from former YAML
    upsert_catalog_event(
        conn,
        {
            "id": "vpn_login_foreign_country",
            "source": "fortigate",
            "category": "vpn",
            "event_name": "VPN login from foreign country",
            "severity": "notice",
            "action": "login",
            "weight": 8,
            "template": (
                'date={date} time={time} devname="{fortigate_hostname}" devid="{fortigate_serial}" '
                'logid="0101039944" type="event" subtype="vpn" level="notice" vd="root" '
                'eventtype="sslvpn" user="{username}" remip={vpn_remote_ip} tunneltype="ssl-web" '
                'action="login" status="success" country={country} reportingIp={reporting_ip} '
                'msg="SSL VPN login from foreign country (simulated)"'
            ),
            "tags": "fortigate,vpn,sslvpn,geo",
            "ttp": "initial-access",
            "format": "fortigate",
        },
    )
    n += 1
    return n


def import_campaigns(conn: sqlite3.Connection, base: Path) -> int:
    campaigns_dir = base / "log_repository" / "campaigns"
    n = 0
    for path in sorted(campaigns_dir.glob("*.csv")):
        scenario_id = path.stem
        rows = _read_csv(path)
        if not rows:
            continue
        conn.execute(
            """
            INSERT INTO scenarios (id, name, description) VALUES (?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET name=excluded.name
            """,
            (scenario_id, scenario_id.replace("_", " ").title(), f"Imported from {path.name}"),
        )
        conn.execute("DELETE FROM scenario_steps WHERE scenario_id=?", (scenario_id,))
        for row in rows:
            step = int(row.get("step", "0"))
            conn.execute(
                """
                INSERT INTO scenario_steps (
                    scenario_id, step_num, phase, source_system, category, event_hint,
                    src_role, dst_role, asset_role, user_role, repeat_count,
                    min_delay_ms, max_delay_ms, sort_order
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    scenario_id,
                    step,
                    row.get("phase", ""),
                    row.get("source", ""),
                    row.get("category", ""),
                    row.get("event_hint", ""),
                    row.get("src_role", ""),
                    row.get("dst_role", ""),
                    row.get("asset_role", ""),
                    row.get("user_role", ""),
                    int(row.get("repeat", "1") or "1"),
                    int(row.get("min_delay_ms", "0") or "0"),
                    int(row.get("max_delay_ms", "0") or "0"),
                    step,
                ),
            )
            n += 1
    return n


def import_all_csv(base: Path | None = None, db_path: Path | None = None) -> dict[str, int | dict]:
    base = base or _default_csv_root()
    conn = get_connection(db_path)
    init_schema(conn)
    try:
        config_counts = import_config(conn, base)
        templates = import_log_templates(conn, base)
        campaigns = import_campaigns(conn, base)
        conn.commit()
        return {
            "csv_root": str(base),
            "config": config_counts,
            "event_templates": templates,
            "scenario_steps": campaigns,
        }
    finally:
        conn.close()


def main(argv: list[str] | None = None) -> int:
    import argparse

    p = argparse.ArgumentParser(description="Import CSV lab data into fortisiem.db")
    p.add_argument("--csv-root", type=Path, default=None)
    p.add_argument("--db", type=Path, default=None)
    args = p.parse_args(argv)
    result = import_all_csv(args.csv_root, args.db)
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
