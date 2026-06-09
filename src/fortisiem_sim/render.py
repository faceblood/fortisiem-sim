from __future__ import annotations

import random
import re
from datetime import datetime, timedelta

from .models import ActorProfile, EventTemplate, Scenario, SendOptions

_PLACEHOLDER = re.compile(r"\{\{(\w+)\}\}")

SUPPORTED_FORMATS: dict[str, str] = {
    "syslog_generic": "RFC3164 genérico con PRI + hostname",
    "cef": "Common Event Format",
    "fortiedr_cef": "CEF estilo FortiEDR (simulado)",
    "fortigate": "FortiGate key=value (VPN/traffic/event)",
    "linux_auth": "Linux sshd/sudo/auth",
    "windows_security": "Windows Security Event Log (simulado)",
    "esxi_vcenter": "VMware ESXi / vCenter",
    "docker": "Docker / container runtime",
    "nginx_apache": "HTTP access log Nginx/Apache",
    "ot_scada": "OT/SCADA alarmas textuales",
    "crisis_comms": "Comunicación crisis / tabletop IR",
}

_PASSTHROUGH = {"nginx_apache", "docker", "ot_scada", "crisis_comms"}


def _pick(pool: list[str], fallback: str) -> str:
    return random.choice(pool) if pool else fallback


def resolve_actor(scenario: Scenario, actor_name: str) -> ActorProfile:
    profiles = scenario.actors.profiles
    return profiles.get(actor_name or scenario.actors.default_profile) or profiles.get(
        "default", ActorProfile(name="default")
    )


def build_context(
    scenario: Scenario,
    template: EventTemplate,
    options: SendOptions,
    *,
    actor_name: str = "",
    overrides: dict[str, str] | None = None,
    sequence_index: int = 0,
    timeline_total: int = 0,
) -> dict[str, str]:
    """Construye el contexto de render como dict plano de placeholders."""
    pools = scenario.actors.pools
    profile = resolve_actor(scenario, actor_name)
    overrides = dict(overrides or {})

    now = datetime.now()
    if scenario.timeline_minutes > 0 and timeline_total > 0:
        spread = scenario.timeline_minutes * 60
        offset = int((sequence_index / max(1, timeline_total - 1)) * spread)
        now = now - timedelta(seconds=spread - offset)
    elif options.randomize_timestamps:
        now = now + timedelta(seconds=random.randint(-3600, 3600))

    user = overrides.pop("user", profile.user)
    hostname = overrides.pop("hostname", profile.hostname)
    domain = overrides.pop("domain", profile.domain)
    src_ip = overrides.pop("src_ip", profile.src_ip)
    reporting_ip = overrides.pop("reporting_ip", profile.reporting_ip)

    if options.randomize_user:
        user = _pick(pools.users, user)
    if options.randomize_src:
        src_ip = _pick(pools.src_ips, src_ip)
    if options.randomize_reporting_ip:
        reporting_ip = _pick(pools.reporting_ips, reporting_ip)

    ctx: dict[str, str] = {
        "timestamp": now.isoformat(timespec="seconds"),
        "date": now.strftime("%Y-%m-%d"),
        "time": now.strftime("%H:%M:%S"),
        "epoch": str(int(now.timestamp())),
        "syslog_ts": now.strftime("%b %d %H:%M:%S"),
        "src_ip": src_ip,
        "reporting_ip": reporting_ip,
        "dst_ip": "10.255.9.3",
        "hostname": hostname,
        "user": user,
        "domain": domain,
        "org_id": str(scenario.org_id),
        "country": "ES",
        "action": "simulated",
        "severity": template.severity,
        "process": "simulated-process",
        "command": "echo simulated-lab-only",
        "file_path": "/var/log/simulated.log",
        "device_id": "LAB-DEVICE-001",
        "serial": "SIM0000001",
        "simulation_marker": options.simulation_marker,
    }
    # defaults de plantilla + extra de actor + overrides del evento (en este orden de prioridad)
    ctx.update(template.defaults)
    ctx.update(profile.extra)
    ctx.update(overrides)
    return ctx


def render_body(template: EventTemplate, ctx: dict[str, str]) -> str:
    body = _PLACEHOLDER.sub(lambda m: ctx.get(m.group(1), m.group(0)), template.body)
    marker = ctx.get("simulation_marker", "")
    if marker and marker not in body:
        body = f"{body} {marker}"
    return body


def build_wire(template: EventTemplate, body: str, ctx: dict[str, str]) -> str:
    """Aplica el envoltorio según el formato del evento."""
    fmt = template.format
    if fmt in _PASSTHROUGH:
        return body
    if fmt == "cef" and not body.startswith("CEF:"):
        return f"CEF:0|LabVendor|LabSim|2.0|9000|SimulatedEvent|5|{body}"
    if fmt == "fortiedr_cef" and not body.startswith("CEF:"):
        return (
            f"CEF:0|Fortinet|FortiEDR|7.0|SimulatedDetection|{ctx.get('severity', 'Medium')}|"
            f"msg=Simulated EDR src={ctx.get('src_ip')} suser={ctx.get('user')} "
            f"shost={ctx.get('hostname')} cs1Label=simulated cs1=true"
        )
    # RFC3164: <PRI>timestamp hostname mensaje
    hostname = template.syslog_hostname
    if "{{hostname}}" in hostname or not hostname.strip():
        hostname = ctx.get("hostname", "lab-host")
    return f"<{template.pri}>{ctx.get('syslog_ts', '')} {hostname} {body}"


def render_wire(template: EventTemplate, ctx: dict[str, str]) -> str:
    return build_wire(template, render_body(template, ctx), ctx)
