from __future__ import annotations

import random
import sqlite3
from dataclasses import dataclass

from .connection import get_connection


@dataclass
class LabAsset:
    ip: str
    hostname: str
    os: str
    source_type: str
    reporting_ip: str = ""
    serial_number: str = ""
    fortigate_devname: str = ""
    fortigate_serial: str = ""
    edr_tenant: str = ""
    edr_site: str = ""
    edr_mssp_mode: str = "false"
    vmware_role: str = ""
    vmware_datacenter: str = ""
    vmware_cluster: str = ""


@dataclass
class AdUser:
    username: str
    email: str
    domain: str
    sid: str = ""


@dataclass
class VmwareUserRow:
    username: str
    realm: str
    email: str
    role: str


def _row_to_asset(row: sqlite3.Row) -> LabAsset:
    return LabAsset(
        ip=row["ip"],
        hostname=row["hostname"],
        os=row["os"],
        source_type=row["source_type"],
        reporting_ip=row["reporting_ip"] or row["ip"],
        serial_number=row["serial_number"] or "",
        fortigate_devname=row["fortigate_devname"] or row["hostname"],
        fortigate_serial=row["fortigate_serial"] or row["serial_number"] or "",
        edr_tenant=row["edr_tenant"] or "",
        edr_site=row["edr_site"] or "",
        edr_mssp_mode=row["edr_mssp_mode"] or "false",
        vmware_role=row["vmware_role"] or "",
        vmware_datacenter=row["vmware_datacenter"] or "",
        vmware_cluster=row["vmware_cluster"] or "",
    )


def load_all_assets(conn: sqlite3.Connection | None = None) -> list[LabAsset]:
    own = conn is None
    if own:
        conn = get_connection()
    try:
        rows = conn.execute("SELECT * FROM lab_assets ORDER BY sort_order, id").fetchall()
        return [_row_to_asset(r) for r in rows]
    finally:
        if own:
            conn.close()


def pick_asset(
    assets: list[LabAsset],
    source_type: str,
    fallback: LabAsset | None = None,
) -> LabAsset:
    matches = [a for a in assets if a.source_type.lower() == source_type.lower()]
    if matches:
        return random.choice(matches)
    if fallback:
        return fallback
    if assets:
        return random.choice(assets)
    return LabAsset(ip="10.10.10.21", hostname="WIN-IT-001", os="Windows", source_type="windows")


def find_asset_by_ip(assets: list[LabAsset], ip: str) -> LabAsset | None:
    ip = ip.strip()
    for a in assets:
        if a.ip == ip:
            return a
    return None


def load_ad_users(conn: sqlite3.Connection | None = None) -> list[AdUser]:
    own = conn is None
    if own:
        conn = get_connection()
    try:
        cols = {r[1] for r in conn.execute("PRAGMA table_info(ad_users)")}
        if "email" in cols:
            rows = conn.execute(
                "SELECT username, email, domain, sid FROM ad_users ORDER BY id"
            ).fetchall()
            return [
                AdUser(
                    username=r["username"],
                    email=r["email"] or f"{r['username']}@age.local",
                    domain=r["domain"] or "age.local",
                    sid=r["sid"] or "",
                )
                for r in rows
            ]
        rows = conn.execute("SELECT username FROM ad_users ORDER BY id").fetchall()
        return [
            AdUser(username=r["username"], email=f"{r['username']}@age.local", domain="age.local")
            for r in rows
        ]
    finally:
        if own:
            conn.close()


def load_vmware_users(conn: sqlite3.Connection | None = None) -> list[VmwareUserRow]:
    own = conn is None
    if own:
        conn = get_connection()
    try:
        try:
            rows = conn.execute(
                "SELECT username, realm, email, role FROM vmware_users ORDER BY id"
            ).fetchall()
        except sqlite3.OperationalError:
            return []
        return [VmwareUserRow(r["username"], r["realm"], r["email"], r["role"]) for r in rows]
    finally:
        if own:
            conn.close()


def upsert_lab_asset(conn: sqlite3.Connection, row: dict, sort_order: int = 0) -> None:
    conn.execute(
        """
        INSERT INTO lab_assets (
            ip, hostname, os, source_type, reporting_ip, serial_number,
            fortigate_devname, fortigate_serial, edr_tenant, edr_site, edr_mssp_mode,
            vmware_role, vmware_datacenter, vmware_cluster, sort_order
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(ip) DO UPDATE SET
            hostname=excluded.hostname, os=excluded.os, source_type=excluded.source_type,
            reporting_ip=excluded.reporting_ip, serial_number=excluded.serial_number,
            fortigate_devname=excluded.fortigate_devname, fortigate_serial=excluded.fortigate_serial,
            edr_tenant=excluded.edr_tenant, edr_site=excluded.edr_site,
            edr_mssp_mode=excluded.edr_mssp_mode, vmware_role=excluded.vmware_role,
            vmware_datacenter=excluded.vmware_datacenter, vmware_cluster=excluded.vmware_cluster,
            sort_order=excluded.sort_order
        """,
        (
            row["ip"],
            row["hostname"],
            row["os"],
            row["source_type"],
            (row.get("reporting_ip") or row["ip"] or ""),
            (row.get("serial_number") or ""),
            (row.get("fortigate_devname") or ""),
            (row.get("fortigate_serial") or ""),
            (row.get("edr_tenant") or ""),
            (row.get("edr_site") or ""),
            (row.get("edr_mssp_mode") or "false"),
            (row.get("vmware_role") or ""),
            (row.get("vmware_datacenter") or ""),
            (row.get("vmware_cluster") or ""),
            sort_order,
        ),
    )


def upsert_ad_user(conn: sqlite3.Connection, username: str, email: str, domain: str = "age.local") -> None:
    sid = f"S-1-5-21-{random.randint(1000000000, 1999999999)}-{random.randint(1000, 9999)}"
    cols = {r[1] for r in conn.execute("PRAGMA table_info(ad_users)")}
    if "email" in cols:
        conn.execute(
            """
            INSERT INTO ad_users (username, email, domain, sid) VALUES (?, ?, ?, ?)
            ON CONFLICT(username) DO UPDATE SET email=excluded.email, domain=excluded.domain
            """,
            (username, email, domain, sid),
        )
    else:
        conn.execute(
            "INSERT OR IGNORE INTO ad_users (username) VALUES (?)",
            (username,),
        )
