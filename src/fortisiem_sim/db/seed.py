from __future__ import annotations

import sqlite3

from ..loaders import (
    custom_events_path,
    default_lab_path,
    default_templates_path,
    load_lab_profile,
    load_templates,
)
from .assets_repo import seed_assets_from_yaml
from .connection import get_connection, init_schema
from .email_repo import seed_email_templates
from .events_repo import upsert_event_raw, upsert_template
from .import_activity_chains import import_activity_chains
from .scenarios_repo import seed_scenarios_from_yaml


def seed_database(conn: sqlite3.Connection | None = None) -> None:
    own = conn is None
    if own:
        conn = get_connection()
        init_schema(conn)
    try:
        base = default_templates_path()
        if base.exists():
            for eid, tmpl in load_templates(base).items():
                upsert_template(conn, tmpl, is_builtin=True)
        custom = custom_events_path()
        if custom.exists():
            for eid, tmpl in load_templates(custom).items():
                upsert_template(conn, tmpl, is_builtin=False)
        lab = load_lab_profile(default_lab_path())
        conn.execute(
            """
            INSERT INTO lab_settings (
                id, target, port, org_id, version, edition,
                default_delay, default_jitter, marker
            ) VALUES (1, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                target = excluded.target,
                port = excluded.port,
                org_id = excluded.org_id,
                version = excluded.version,
                edition = excluded.edition,
                default_delay = excluded.default_delay,
                default_jitter = excluded.default_jitter,
                marker = excluded.marker
            """,
            (
                lab.target,
                lab.port,
                lab.org_id,
                lab.version,
                lab.edition,
                lab.default_delay,
                lab.default_jitter,
                lab.marker,
            ),
        )
        seed_assets_from_yaml(conn)
        seed_email_templates(conn)
        seed_scenarios_from_yaml(conn)
        conn.commit()
    finally:
        if own:
            conn.close()
    import_activity_chains()
