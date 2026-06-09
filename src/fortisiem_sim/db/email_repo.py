from __future__ import annotations

import json
import sqlite3
from typing import Any

from ..mail import normalize_smtp
from ..models import EmailTemplate
from .connection import get_connection

DEFAULT_EMAIL_TEMPLATES: list[dict[str, Any]] = [
    {
        "id": "ir_alert_tabletop",
        "name": "Alerta IR — ejercicio tabletop",
        "description": "Notificación simulada al equipo IR",
        "subject": "[SIM-TABLETOP] Actividad sospechosa detectada — {{hostname}}",
        "html_body": """<!DOCTYPE html>
<html><body style="font-family:Segoe UI,Arial,sans-serif;color:#222">
<h2 style="color:#c0392b">Alerta de seguridad (simulación)</h2>
<p>Se ha detectado actividad correlacionada en <strong>{{hostname}}</strong> (usuario <code>{{user}}@{{domain}}</code>).</p>
<ul>
  <li>Origen: {{src_ip}}</li>
  <li>Reporting IP: {{reporting_ip}}</li>
  <li>Org ID: {{org_id}}</li>
</ul>
<p style="color:#666;font-size:12px">Mensaje generado por FortiSIEM Sim — solo lab / tabletop.</p>
</body></html>""",
    },
    {
        "id": "phishing_simulated",
        "name": "Phishing simulado (HTML)",
        "description": "Correo de phishing para concienciación",
        "subject": "Acción requerida: verificación de cuenta — {{domain}}",
        "html_body": """<!DOCTYPE html>
<html><body style="font-family:Arial,sans-serif">
<p>Hola {{user}},</p>
<p>Detectamos un inicio de sesión inusual. <a href="https://lab-phish.example/verify">Verificar cuenta</a></p>
<p style="font-size:11px;color:#888">Simulación tabletop — no es un enlace real.</p>
</body></html>""",
    },
    {
        "id": "ransom_note_tabletop",
        "name": "Nota ransomware (tabletop)",
        "description": "Mensaje de impacto simulado",
        "subject": "[TABLETOP] Notificación de incidente — {{hostname}}",
        "html_body": """<!DOCTYPE html>
<html><body style="background:#1a1a1a;color:#eee;font-family:monospace;padding:24px">
<h1 style="color:#e74c3c">INCIDENTE SIMULADO</h1>
<p>Host afectado: {{hostname}} / {{user}}@{{domain}}</p>
<p>Este mensaje forma parte de un ejercicio CSIRT. No hay cifrado real.</p>
</body></html>""",
    },
]


def load_smtp_settings(conn: sqlite3.Connection | None = None) -> dict[str, Any]:
    own = conn is None
    if own:
        conn = get_connection()
    try:
        row = conn.execute("SELECT * FROM smtp_settings WHERE id = 1").fetchone()
        if not row:
            return normalize_smtp({})
        return normalize_smtp({
            "enabled": bool(row["enabled"]),
            "host": row["host"],
            "port": row["port"],
            "username": row["username"],
            "password": row["password"],
            "from_address": row["from_address"],
            "from_name": row["from_name"],
            "use_tls": bool(row["use_tls"]),
            "use_ssl": bool(row["use_ssl"]),
        })
    finally:
        if own:
            conn.close()


def save_smtp_settings(data: dict[str, Any], conn: sqlite3.Connection | None = None) -> None:
    cfg = normalize_smtp(data)
    own = conn is None
    if own:
        conn = get_connection()
    try:
        conn.execute(
            """
            INSERT INTO smtp_settings (
                id, enabled, host, port, username, password,
                from_address, from_name, use_tls, use_ssl
            ) VALUES (1, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                enabled=excluded.enabled, host=excluded.host, port=excluded.port,
                username=excluded.username, password=excluded.password,
                from_address=excluded.from_address, from_name=excluded.from_name,
                use_tls=excluded.use_tls, use_ssl=excluded.use_ssl
            """,
            (
                1 if cfg["enabled"] else 0,
                cfg["host"],
                cfg["port"],
                cfg["username"],
                cfg["password"],
                cfg["from_address"],
                cfg["from_name"],
                1 if cfg["use_tls"] else 0,
                1 if cfg["use_ssl"] else 0,
            ),
        )
        conn.commit()
    finally:
        if own:
            conn.close()


def load_all_email_templates(conn: sqlite3.Connection | None = None) -> dict[str, EmailTemplate]:
    own = conn is None
    if own:
        conn = get_connection()
    try:
        out: dict[str, EmailTemplate] = {}
        for row in conn.execute("SELECT * FROM email_templates ORDER BY id"):
            out[row["id"]] = EmailTemplate(
                id=row["id"],
                name=row["name"],
                subject=row["subject"],
                html_body=row["html_body"],
                description=row["description"],
            )
        return out
    finally:
        if own:
            conn.close()


def list_email_catalog(conn: sqlite3.Connection | None = None) -> list[dict[str, Any]]:
    own = conn is None
    if own:
        conn = get_connection()
    try:
        return [
            {
                "id": row["id"],
                "name": row["name"],
                "subject": row["subject"],
                "description": row["description"],
                "is_builtin": bool(row["is_builtin"]),
            }
            for row in conn.execute("SELECT * FROM email_templates ORDER BY id")
        ]
    finally:
        if own:
            conn.close()


def upsert_email_template(tmpl: dict[str, Any], *, is_builtin: bool = False, conn: sqlite3.Connection | None = None) -> None:
    own = conn is None
    if own:
        conn = get_connection()
    try:
        eid = str(tmpl["id"]).strip()
        conn.execute(
            """
            INSERT INTO email_templates (id, name, subject, html_body, description, is_builtin, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, datetime('now'))
            ON CONFLICT(id) DO UPDATE SET
                name=excluded.name, subject=excluded.subject, html_body=excluded.html_body,
                description=excluded.description,
                is_builtin=CASE WHEN email_templates.is_builtin=1 THEN 1 ELSE excluded.is_builtin END,
                updated_at=datetime('now')
            """,
            (
                eid,
                str(tmpl.get("name", eid)),
                str(tmpl.get("subject", "")),
                str(tmpl.get("html_body", "")),
                str(tmpl.get("description", "")),
                1 if is_builtin else 0,
            ),
        )
        conn.commit()
    finally:
        if own:
            conn.close()


def delete_email_template(template_id: str, conn: sqlite3.Connection | None = None) -> bool:
    own = conn is None
    if own:
        conn = get_connection()
    try:
        row = conn.execute(
            "SELECT is_builtin FROM email_templates WHERE id = ?", (template_id,)
        ).fetchone()
        if not row:
            return False
        if row["is_builtin"]:
            raise ValueError(f"No se puede borrar plantilla builtin: {template_id}")
        conn.execute("DELETE FROM email_templates WHERE id = ?", (template_id,))
        conn.commit()
        return True
    finally:
        if own:
            conn.close()


def seed_email_templates(conn: sqlite3.Connection) -> None:
    count = conn.execute("SELECT COUNT(*) AS n FROM email_templates").fetchone()["n"]
    if int(count) > 0:
        return
    for tmpl in DEFAULT_EMAIL_TEMPLATES:
        upsert_email_template(tmpl, is_builtin=True, conn=conn)
    save_smtp_settings({"enabled": False}, conn=conn)
