from __future__ import annotations

import random
import time

from .db.context_repo import build_send_context
from .db.events_repo import load_all_templates
from .models import EventTemplate, RunSummary, SendOptions
from .render import render_wire
from .syslog import resolve_local_ip, send_syslog_scapy


def _vpn_templates(templates: dict[str, EventTemplate]) -> list[EventTemplate]:
    out = [
        t
        for t in templates.values()
        if t.source_system == "fortigate" and t.category == "vpn"
    ]
    if not out:
        out = [t for t in templates.values() if t.format == "fortigate" and "vpn" in t.id]
    return out


def _pick_weighted(templates: list[EventTemplate]) -> EventTemplate:
    weights = [max(1, int(t.weight)) for t in templates]
    return random.choices(templates, weights=weights, k=1)[0]


def run_vpn_sender(
    options: SendOptions,
    *,
    count: int = 120,
    rate: float = 5.0,
    remote_access_ip: str = "",
    vpn_gateway_ip: str = "",
    vpn_assigned_ip: str = "",
    event_hint: str = "",
    templates: dict[str, EventTemplate] | None = None,
) -> RunSummary:
    """Emit FortiGate VPN templates loaded from SQLite."""
    catalog = templates or load_all_templates()
    vpn_tmpls = _vpn_templates(catalog)
    if event_hint:
        hint = event_hint.lower()
        filtered = [
            t
            for t in vpn_tmpls
            if hint in t.id.lower() or hint in t.name.lower()
        ]
        if filtered:
            vpn_tmpls = filtered
    if not vpn_tmpls:
        raise RuntimeError(
            "No VPN templates in SQLite. Run: fortisiem-sim db import-csv"
        )

    summary = RunSummary()
    rate_sleep = 1.0 / max(1.0, rate)
    overrides: dict[str, str] = {}
    if remote_access_ip.strip():
        overrides["remote_access_ip"] = remote_access_ip.strip()
        overrides["vpn_remote_ip"] = remote_access_ip.strip()
    if vpn_gateway_ip.strip():
        overrides["vpn_gateway_ip"] = vpn_gateway_ip.strip()
    if vpn_assigned_ip.strip():
        overrides["vpn_assigned_ip"] = vpn_assigned_ip.strip()

    for _ in range(max(1, count)):
        template = _pick_weighted(vpn_tmpls)
        ctx = build_send_context(overrides=overrides)
        ctx["simulation_marker"] = options.simulation_marker
        ctx["severity"] = template.severity
        wire = render_wire(template, ctx)
        packet_src = ctx["reporting_ip"] if options.spoof_src else resolve_local_ip()
        sent = not options.dry_run
        if sent:
            send_syslog_scapy(
                options.target,
                options.port,
                wire,
                src_ip=packet_src if options.spoof_src else None,
                iface=options.iface,
                use_spoof=options.spoof_src,
            )
        summary.total += 1
        summary.sent += int(sent)
        summary.dry_run += int(not sent)
        summary.by_format[template.format] = summary.by_format.get(template.format, 0) + 1
        summary.by_event[template.id] = summary.by_event.get(template.id, 0) + 1
        if not options.quiet:
            mode = "SENT" if sent else "DRY"
            print(f"[{mode}] event={template.id} reporting_ip={ctx['reporting_ip']}\n{wire}")
        time.sleep(rate_sleep)
    return summary
