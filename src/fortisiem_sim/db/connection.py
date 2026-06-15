from __future__ import annotations

import os
import sqlite3
from pathlib import Path

from ..loaders import package_root

SCHEMA = """
CREATE TABLE IF NOT EXISTS lab_settings (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    target TEXT NOT NULL DEFAULT '10.255.9.3',
    port INTEGER NOT NULL DEFAULT 514,
    org_id INTEGER NOT NULL DEFAULT 1,
    version TEXT NOT NULL DEFAULT '7.5',
    edition TEXT NOT NULL DEFAULT 'enterprise',
    default_delay REAL NOT NULL DEFAULT 0.5,
    default_jitter REAL NOT NULL DEFAULT 0.2,
    marker TEXT NOT NULL DEFAULT 'simulated=true'
);

CREATE TABLE IF NOT EXISTS event_templates (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    format TEXT NOT NULL,
    severity TEXT NOT NULL,
    category TEXT NOT NULL DEFAULT 'generic',
    source_system TEXT NOT NULL DEFAULT '',
    body TEXT NOT NULL,
    syslog_hostname TEXT NOT NULL DEFAULT 'lab-host',
    pri INTEGER NOT NULL DEFAULT 134,
    fields_json TEXT NOT NULL DEFAULT '[]',
    defaults_json TEXT NOT NULL DEFAULT '{}',
    fortisiem_hints_json TEXT NOT NULL DEFAULT '{}',
    tags_json TEXT NOT NULL DEFAULT '[]',
    is_builtin INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS event_mitre (
    event_id TEXT NOT NULL REFERENCES event_templates(id) ON DELETE CASCADE,
    kind TEXT NOT NULL CHECK (kind IN ('tactic', 'technique')),
    value TEXT NOT NULL,
    PRIMARY KEY (event_id, kind, value)
);

CREATE TABLE IF NOT EXISTS ad_settings (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    primary_domain TEXT NOT NULL DEFAULT 'lab.local'
);

CREATE TABLE IF NOT EXISTS ad_domains (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    domain TEXT NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS ad_users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS firewalls (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sort_order INTEGER NOT NULL DEFAULT 0,
    name TEXT NOT NULL,
    devname TEXT NOT NULL,
    serial TEXT NOT NULL,
    src_ip TEXT NOT NULL,
    reporting_ip TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS hosts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sort_order INTEGER NOT NULL DEFAULT 0,
    os_type TEXT NOT NULL CHECK (os_type IN ('windows', 'linux')),
    hostname TEXT NOT NULL,
    user TEXT NOT NULL,
    src_ip TEXT NOT NULL,
    reporting_ip TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS ip_pool (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    pool_name TEXT NOT NULL,
    value TEXT NOT NULL,
    UNIQUE(pool_name, value)
);

CREATE TABLE IF NOT EXISTS c2_settings (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    default_ip TEXT NOT NULL DEFAULT '203.0.113.50',
    default_uri TEXT NOT NULL DEFAULT 'https://lab-c2.example/beacon'
);

CREATE TABLE IF NOT EXISTS c2_iocs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    kind TEXT NOT NULL CHECK (kind IN ('ip', 'uri')),
    value TEXT NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS scenarios (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    org_id INTEGER NOT NULL DEFAULT 1,
    timeline_minutes INTEGER NOT NULL DEFAULT 0,
    use_config_actors INTEGER NOT NULL DEFAULT 1,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    actors_json TEXT,
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS scenario_phases (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    scenario_id TEXT NOT NULL REFERENCES scenarios(id) ON DELETE CASCADE,
    slug TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    phase_type TEXT NOT NULL DEFAULT 'mitre',
    mitre_tactic TEXT NOT NULL DEFAULT '',
    mitre_techniques_json TEXT NOT NULL DEFAULT '[]',
    sort_order INTEGER NOT NULL DEFAULT 0,
    UNIQUE(scenario_id, slug)
);

CREATE TABLE IF NOT EXISTS scenario_phase_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    phase_id INTEGER NOT NULL REFERENCES scenario_phases(id) ON DELETE CASCADE,
    event_id TEXT NOT NULL,
    count INTEGER NOT NULL DEFAULT 1,
    actor TEXT NOT NULL DEFAULT '',
    overrides_json TEXT NOT NULL DEFAULT '{}',
    sort_order INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS scenario_phase_emails (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    phase_id INTEGER NOT NULL REFERENCES scenario_phases(id) ON DELETE CASCADE,
    template_id TEXT NOT NULL,
    to_address TEXT NOT NULL DEFAULT '',
    cc TEXT NOT NULL DEFAULT '',
    actor TEXT NOT NULL DEFAULT '',
    overrides_json TEXT NOT NULL DEFAULT '{}',
    sort_order INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS smtp_settings (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    enabled INTEGER NOT NULL DEFAULT 0,
    host TEXT NOT NULL DEFAULT '',
    port INTEGER NOT NULL DEFAULT 587,
    username TEXT NOT NULL DEFAULT '',
    password TEXT NOT NULL DEFAULT '',
    from_address TEXT NOT NULL DEFAULT '',
    from_name TEXT NOT NULL DEFAULT 'FortiSIEM Sim Lab',
    use_tls INTEGER NOT NULL DEFAULT 1,
    use_ssl INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS email_templates (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    subject TEXT NOT NULL,
    html_body TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    is_builtin INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);
"""


def db_path(override: Path | None = None) -> Path:
    if override is not None:
        return override
    env = os.environ.get("FORTISIEM_SIM_DB", "").strip()
    if env:
        return Path(env)
    return package_root() / "config" / "fortisiem.db"


def get_connection(path: Path | None = None) -> sqlite3.Connection:
    target = db_path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(target))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    from .migrations import apply_migrations
    apply_migrations(conn)
    cols = {r[1] for r in conn.execute("PRAGMA table_info(scenario_phases)")}
    if "phase_type" not in cols:
        conn.execute("ALTER TABLE scenario_phases ADD COLUMN phase_type TEXT NOT NULL DEFAULT 'mitre'")
    conn.commit()


def database_is_empty(conn: sqlite3.Connection) -> bool:
    row = conn.execute("SELECT COUNT(*) AS n FROM event_templates").fetchone()
    return int(row["n"]) == 0


def ensure_database(seed_from_yaml: bool = False, path: Path | None = None) -> Path:
    """Crea schema y opcionalmente importa YAML si la BD está vacía."""
    from .email_repo import seed_email_templates
    from .seed import seed_database

    target = db_path(path)
    conn = get_connection(target)
    try:
        init_schema(conn)
        seed_email_templates(conn)
        if seed_from_yaml and database_is_empty(conn):
            seed_database(conn)
    finally:
        conn.close()
    return target
