from __future__ import annotations

import sqlite3

MIGRATION_V2 = """
CREATE TABLE IF NOT EXISTS lab_assets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ip TEXT NOT NULL UNIQUE,
    hostname TEXT NOT NULL,
    os TEXT NOT NULL,
    source_type TEXT NOT NULL,
    reporting_ip TEXT NOT NULL DEFAULT '',
    serial_number TEXT NOT NULL DEFAULT '',
    fortigate_devname TEXT NOT NULL DEFAULT '',
    fortigate_serial TEXT NOT NULL DEFAULT '',
    edr_tenant TEXT NOT NULL DEFAULT '',
    edr_site TEXT NOT NULL DEFAULT '',
    edr_mssp_mode TEXT NOT NULL DEFAULT 'false',
    vmware_role TEXT NOT NULL DEFAULT '',
    vmware_datacenter TEXT NOT NULL DEFAULT '',
    vmware_cluster TEXT NOT NULL DEFAULT '',
    sort_order INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS vmware_users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL,
    realm TEXT NOT NULL DEFAULT 'vsphere.local',
    email TEXT NOT NULL DEFAULT '',
    role TEXT NOT NULL DEFAULT '',
    UNIQUE(username, realm)
);

CREATE TABLE IF NOT EXISTS c2_ips (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ip TEXT NOT NULL UNIQUE,
    asn TEXT NOT NULL DEFAULT '',
    country TEXT NOT NULL DEFAULT '',
    threat_family TEXT NOT NULL DEFAULT '',
    confidence TEXT NOT NULL DEFAULT 'medium',
    is_default INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS c2_domains (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    domain TEXT NOT NULL UNIQUE,
    threat_family TEXT NOT NULL DEFAULT '',
    category TEXT NOT NULL DEFAULT '',
    confidence TEXT NOT NULL DEFAULT 'medium'
);

CREATE TABLE IF NOT EXISTS malware_samples (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    family TEXT NOT NULL,
    name TEXT NOT NULL,
    type TEXT NOT NULL DEFAULT '',
    severity TEXT NOT NULL DEFAULT 'high',
    sha256 TEXT NOT NULL DEFAULT '',
    filename TEXT NOT NULL DEFAULT '',
    extension TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS command_pool (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    pool_name TEXT NOT NULL,
    value TEXT NOT NULL,
    UNIQUE(pool_name, value)
);

CREATE TABLE IF NOT EXISTS scenario_steps (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    scenario_id TEXT NOT NULL REFERENCES scenarios(id) ON DELETE CASCADE,
    step_num INTEGER NOT NULL,
    phase TEXT NOT NULL DEFAULT '',
    source_system TEXT NOT NULL,
    category TEXT NOT NULL,
    event_hint TEXT NOT NULL,
    event_id TEXT,
    src_role TEXT NOT NULL DEFAULT '',
    dst_role TEXT NOT NULL DEFAULT '',
    asset_role TEXT NOT NULL DEFAULT '',
    user_role TEXT NOT NULL DEFAULT '',
    repeat_count INTEGER NOT NULL DEFAULT 1,
    min_delay_ms INTEGER NOT NULL DEFAULT 0,
    max_delay_ms INTEGER NOT NULL DEFAULT 0,
    sort_order INTEGER NOT NULL DEFAULT 0,
    UNIQUE(scenario_id, step_num)
);
"""


def _column_exists(conn: sqlite3.Connection, table: str, column: str) -> bool:
    cols = {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}
    return column in cols


def _add_column(conn: sqlite3.Connection, table: str, ddl: str) -> None:
    conn.execute(f"ALTER TABLE {table} ADD COLUMN {ddl}")


def apply_migrations(conn: sqlite3.Connection) -> list[int]:
    conn.executescript(
        "CREATE TABLE IF NOT EXISTS schema_migrations ("
        "version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL DEFAULT (datetime('now')));"
    )
    applied: list[int] = []
    row = conn.execute("SELECT MAX(version) AS v FROM schema_migrations").fetchone()
    current = int(row["v"] or 0)

    if current < 2:
        conn.executescript(MIGRATION_V2)
        if _column_exists(conn, "ad_users", "username") and not _column_exists(conn, "ad_users", "email"):
            _add_column(conn, "ad_users", "email TEXT NOT NULL DEFAULT ''")
            _add_column(conn, "ad_users", "domain TEXT NOT NULL DEFAULT 'age.local'")
            _add_column(conn, "ad_users", "sid TEXT NOT NULL DEFAULT ''")
        if _column_exists(conn, "event_templates", "id"):
            for col, typedef in (
                ("action", "TEXT NOT NULL DEFAULT ''"),
                ("weight", "INTEGER NOT NULL DEFAULT 5"),
                ("event_group", "TEXT NOT NULL DEFAULT ''"),
                ("ttp", "TEXT NOT NULL DEFAULT ''"),
            ):
                if not _column_exists(conn, "event_templates", col):
                    _add_column(conn, "event_templates", f"{col} {typedef}")
        conn.execute("INSERT INTO schema_migrations (version) VALUES (2)")
        applied.append(2)
        conn.commit()

    if current < 3:
        if _column_exists(conn, "command_pool", "pool_name"):
            for col, typedef in (
                ("legitimacy", "TEXT NOT NULL DEFAULT ''"),
                ("category", "TEXT NOT NULL DEFAULT ''"),
                ("description", "TEXT NOT NULL DEFAULT ''"),
            ):
                if not _column_exists(conn, "command_pool", col):
                    _add_column(conn, "command_pool", f"{col} {typedef}")
        conn.execute("INSERT INTO schema_migrations (version) VALUES (3)")
        applied.append(3)
        conn.commit()

    if current < 4:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS command_refs (
                id TEXT PRIMARY KEY,
                command_line TEXT NOT NULL,
                legitimacy TEXT NOT NULL DEFAULT '',
                category TEXT NOT NULL DEFAULT '',
                description TEXT NOT NULL DEFAULT ''
            );

            CREATE TABLE IF NOT EXISTS activity_chains (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                legitimacy TEXT NOT NULL DEFAULT 'legitimate',
                category TEXT NOT NULL DEFAULT '',
                severity TEXT NOT NULL DEFAULT 'info',
                description TEXT NOT NULL DEFAULT '',
                objective TEXT NOT NULL DEFAULT '',
                source_system TEXT NOT NULL DEFAULT 'linux',
                mitre_json TEXT NOT NULL DEFAULT '[]',
                updated_at TEXT NOT NULL DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS activity_chain_steps (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chain_id TEXT NOT NULL REFERENCES activity_chains(id) ON DELETE CASCADE,
                sort_order INTEGER NOT NULL DEFAULT 0,
                step_kind TEXT NOT NULL DEFAULT 'event',
                event_id TEXT NOT NULL DEFAULT '',
                command_ref TEXT NOT NULL DEFAULT '',
                command_line TEXT NOT NULL DEFAULT '',
                min_delay_ms INTEGER NOT NULL DEFAULT 0,
                max_delay_ms INTEGER NOT NULL DEFAULT 0,
                optional INTEGER NOT NULL DEFAULT 0,
                UNIQUE(chain_id, sort_order)
            );
            """
        )
        if _column_exists(conn, "scenario_phase_events", "event_id"):
            if not _column_exists(conn, "scenario_phase_events", "chain_id"):
                _add_column(conn, "scenario_phase_events", "chain_id TEXT NOT NULL DEFAULT ''")
        conn.execute("INSERT INTO schema_migrations (version) VALUES (4)")
        applied.append(4)
        conn.commit()

    if current < 5:
        if _column_exists(conn, "activity_chain_steps", "chain_id"):
            if not _column_exists(conn, "activity_chain_steps", "legitimacy"):
                _add_column(conn, "activity_chain_steps", "legitimacy TEXT NOT NULL DEFAULT ''")
            conn.execute(
                """
                UPDATE activity_chain_steps
                SET legitimacy = (
                    SELECT legitimacy FROM activity_chains
                    WHERE activity_chains.id = activity_chain_steps.chain_id
                )
                WHERE legitimacy = '' OR legitimacy IS NULL
                """
            )
        conn.execute("INSERT INTO schema_migrations (version) VALUES (5)")
        applied.append(5)
        conn.commit()
    return applied
