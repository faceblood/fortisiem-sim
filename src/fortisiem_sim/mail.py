from __future__ import annotations

import re
import smtplib
import ssl
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Any

from .models import EventTemplate, SendOptions
from .render import build_context

_PLACEHOLDER = re.compile(r"\{\{(\w+)\}\}")


def substitute_text(template: str, ctx: dict[str, str]) -> str:
    return _PLACEHOLDER.sub(lambda m: ctx.get(m.group(1), m.group(0)), template)


def normalize_smtp(raw: dict[str, Any] | None) -> dict[str, Any]:
    data = raw or {}
    return {
        "enabled": bool(data.get("enabled", False)),
        "host": str(data.get("host", "")).strip(),
        "port": int(data.get("port", 587)),
        "username": str(data.get("username", "")).strip(),
        "password": str(data.get("password", "")),
        "from_address": str(data.get("from_address", "")).strip(),
        "from_name": str(data.get("from_name", "FortiSIEM Sim Lab")).strip(),
        "use_tls": bool(data.get("use_tls", True)),
        "use_ssl": bool(data.get("use_ssl", False)),
    }


def render_email(
    template: dict[str, Any],
    scenario,
    actor_name: str,
    overrides: dict[str, str] | None = None,
    options: SendOptions | None = None,
) -> tuple[str, str]:
    opts = options or SendOptions()
    dummy = EventTemplate(id="_email", name="", format="email", severity="info", body="")
    ctx = build_context(
        scenario, dummy, opts,
        actor_name=actor_name, overrides=overrides,
    )
    subject = substitute_text(str(template.get("subject", "")), ctx)
    html = substitute_text(str(template.get("html_body", "")), ctx)
    return subject, html


def send_html_email(
    smtp_cfg: dict[str, Any],
    *,
    to_address: str,
    cc: str = "",
    subject: str,
    html_body: str,
    dry_run: bool = True,
) -> dict[str, Any]:
    cfg = normalize_smtp(smtp_cfg)
    to_list = [a.strip() for a in to_address.split(",") if a.strip()]
    cc_list = [a.strip() for a in cc.split(",") if a.strip()] if cc else []
    if not to_list:
        raise ValueError("Destinatario (to) vacío")

    result = {
        "to": ", ".join(to_list),
        "cc": ", ".join(cc_list),
        "subject": subject,
        "sent": False,
        "dry_run": dry_run,
        "error": "",
    }

    if dry_run:
        return result

    if not cfg["enabled"]:
        raise ValueError("SMTP deshabilitado en Config")
    if not cfg["host"]:
        raise ValueError("SMTP host no configurado")

    msg = MIMEMultipart("alternative")
    from_hdr = cfg["from_address"] or cfg["username"] or "noreply@lab.local"
    if cfg["from_name"]:
        msg["From"] = f"{cfg['from_name']} <{from_hdr}>"
    else:
        msg["From"] = from_hdr
    msg["To"] = ", ".join(to_list)
    if cc_list:
        msg["Cc"] = ", ".join(cc_list)
    msg["Subject"] = subject
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    recipients = to_list + cc_list
    try:
        if cfg["use_ssl"]:
            server = smtplib.SMTP_SSL(cfg["host"], cfg["port"], timeout=30)
        else:
            server = smtplib.SMTP(cfg["host"], cfg["port"], timeout=30)
        with server:
            if cfg["use_tls"] and not cfg["use_ssl"]:
                server.starttls(context=ssl.create_default_context())
            if cfg["username"]:
                server.login(cfg["username"], cfg["password"])
            server.sendmail(from_hdr, recipients, msg.as_string())
        result["sent"] = True
    except (OSError, smtplib.SMTPException) as exc:
        result["error"] = str(exc)
        raise RuntimeError(f"Error SMTP: {exc}") from exc
    return result
