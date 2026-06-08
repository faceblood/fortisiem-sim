from __future__ import annotations

import random
import re
from datetime import datetime, timedelta

from .models import ActorProfile, EventTemplate, RenderContext, Scenario, SendOptions

_PLACEHOLDER = re.compile(r"\{\{(\w+)\}\}")


def _pick(pool: list[str], fallback: str) -> str:
    return random.choice(pool) if pool else fallback


def resolve_actor(scenario: Scenario, actor_name: str) -> ActorProfile:
    profiles = scenario.actors.profiles
    key = actor_name or scenario.actors.default_profile
    if key in profiles:
        return profiles[key]
    if "default" in profiles:
        return profiles["default"]
    return ActorProfile(name="default")


def build_context(
    scenario: Scenario,
    template: EventTemplate,
    options: SendOptions,
    *,
    actor_name: str = "",
    overrides: dict[str, str] | None = None,
    sequence_index: int = 0,
    timeline_total: int = 0,
) -> RenderContext:
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

    defaults = dict(template.defaults)
    defaults.update(profile.extra)
    defaults.update(overrides)

    syslog_ts = now.strftime("%b %d %H:%M:%S")
    return RenderContext(
        timestamp=now.isoformat(timespec="seconds"),
        date=now.strftime("%Y-%m-%d"),
        time=now.strftime("%H:%M:%S"),
        epoch=str(int(now.timestamp())),
        syslog_ts=syslog_ts,
        src_ip=src_ip,
        reporting_ip=reporting_ip,
        dst_ip=defaults.get("dst_ip", "10.255.9.3"),
        hostname=hostname,
        user=user,
        domain=domain,
        org_id=str(scenario.org_id),
        country=defaults.get("country", "ES"),
        action=defaults.get("action", "simulated"),
        severity=template.severity,
        process=defaults.get("process", "simulated-process"),
        command=defaults.get("command", "echo simulated-lab-only"),
        file_path=defaults.get("file_path", "/var/log/simulated.log"),
        device_id=defaults.get("device_id", "LAB-DEVICE-001"),
        serial=defaults.get("serial", "SIM0000001"),
        simulation_marker=options.simulation_marker,
        extra={k: v for k, v in defaults.items()},
    )


def render_body(template: EventTemplate, ctx: RenderContext) -> str:
    mapping = ctx.as_dict()

    def repl(match: re.Match[str]) -> str:
        return mapping.get(match.group(1), match.group(0))

    body = _PLACEHOLDER.sub(repl, template.body)
    if ctx.simulation_marker and ctx.simulation_marker not in body:
        body = f"{body} {ctx.simulation_marker}"
    return body


def render_wire(template: EventTemplate, ctx: RenderContext) -> str:
    from .formats import build_wire_message

    body = render_body(template, ctx)
    return build_wire_message(template, body, ctx.as_dict())
