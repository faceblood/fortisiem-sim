from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml

from .models import (
    ActorPools,
    ActorProfile,
    EventTemplate,
    Scenario,
    ScenarioActors,
    ScenarioEvent,
    ScenarioPhase,
)


def _load_raw(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    if path.suffix.lower() in {".yaml", ".yml"}:
        data = yaml.safe_load(text)
    elif path.suffix.lower() == ".json":
        data = json.loads(text)
    else:
        raise ValueError(f"Formato no soportado: {path.suffix}")
    if not isinstance(data, dict):
        raise ValueError(f"Raíz debe ser objeto: {path}")
    return data


def load_templates(path: Path) -> dict[str, EventTemplate]:
    data = _load_raw(path)
    events_raw = data.get("events", {})
    if not isinstance(events_raw, dict):
        raise ValueError("templates: 'events' debe ser mapa id -> evento")
    out: dict[str, EventTemplate] = {}
    for event_id, raw in events_raw.items():
        if not isinstance(raw, dict):
            raise ValueError(f"Evento {event_id!r} inválido")
        out[event_id] = EventTemplate(
            id=event_id,
            name=str(raw.get("name", event_id)),
            format=str(raw.get("format", "syslog_generic")),
            severity=str(raw.get("severity", "info")),
            category=str(raw.get("category", "generic")),
            body=str(raw.get("body", "")).rstrip("\n"),
            syslog_hostname=str(raw.get("syslog_hostname", "lab-host")),
            pri=int(raw.get("pri", 134)),
            fields=[str(x) for x in raw.get("fields", [])],
            mitre=[str(x) for x in (raw.get("mitre") or [])],
            fortisiem_hints={str(k): str(v) for k, v in (raw.get("fortisiem_hints") or {}).items()},
            defaults={str(k): str(v) for k, v in (raw.get("defaults") or {}).items()},
            tags=[str(x) for x in (raw.get("tags") or [])],
        )
    return out


def _parse_pools(raw: dict[str, Any] | None) -> ActorPools:
    raw = raw or {}
    defaults = ActorPools()
    return ActorPools(
        users=[str(x) for x in raw.get("users", defaults.users)],
        hostnames=[str(x) for x in raw.get("hostnames", defaults.hostnames)],
        src_ips=[str(x) for x in raw.get("src_ips", defaults.src_ips)],
        reporting_ips=[str(x) for x in raw.get("reporting_ips", defaults.reporting_ips)],
        domains=[str(x) for x in raw.get("domains", defaults.domains)],
    )


def _parse_profiles(raw: dict[str, Any] | None) -> dict[str, ActorProfile]:
    raw = raw or {}
    profiles: dict[str, ActorProfile] = {}
    for name, item in raw.items():
        if not isinstance(item, dict):
            continue
        profiles[name] = ActorProfile(
            name=str(name),
            user=str(item.get("user", "lab.user")),
            domain=str(item.get("domain", "lab.local")),
            src_ip=str(item.get("src_ip", "10.10.10.50")),
            reporting_ip=str(item.get("reporting_ip", item.get("src_ip", "10.255.9.21"))),
            hostname=str(item.get("hostname", "ws-lab-01")),
            extra={str(k): str(v) for k, v in (item.get("extra") or {}).items()},
        )
    if "default" not in profiles:
        profiles["default"] = ActorProfile(name="default")
    return profiles


def _parse_actors(raw: dict[str, Any] | None) -> ScenarioActors:
    raw = raw or {}
    pools = _parse_pools(raw.get("pools") or raw)
    profiles = _parse_profiles(raw.get("profiles"))
    if raw.get("users") or raw.get("src_ips"):
        pools = _parse_pools(raw)
    return ScenarioActors(
        profiles=profiles,
        pools=pools,
        default_profile=str(raw.get("default_profile", "default")),
    )


def _parse_event(raw: dict[str, Any]) -> ScenarioEvent:
    return ScenarioEvent(
        id=str(raw["id"]),
        count=int(raw.get("count", 1)),
        delay=float(raw["delay"]) if raw.get("delay") is not None else None,
        jitter=float(raw["jitter"]) if raw.get("jitter") is not None else None,
        actor=str(raw.get("actor", "")),
        overrides={str(k): str(v) for k, v in (raw.get("overrides") or {}).items()},
    )


def _parse_phase(name: str, raw: dict[str, Any]) -> ScenarioPhase:
    events = [_parse_event(item) for item in raw.get("events", []) if isinstance(item, dict)]
    return ScenarioPhase(
        name=name,
        description=str(raw.get("description", "")),
        delay_before=float(raw.get("delay_before", 0.0)),
        events=events,
    )


def load_scenario(path: Path) -> Scenario:
    data = _load_raw(path)
    phases_raw = data.get("phases", {})
    phases: list[ScenarioPhase] = []
    if isinstance(phases_raw, dict):
        for phase_name, phase_data in phases_raw.items():
            if isinstance(phase_data, dict):
                phases.append(_parse_phase(str(phase_name), phase_data))
    elif isinstance(phases_raw, list):
        for item in phases_raw:
            if isinstance(item, dict) and "name" in item:
                phases.append(_parse_phase(str(item["name"]), item))
    return Scenario(
        name=str(data.get("name", path.stem)),
        description=str(data.get("description", "")),
        org_id=int(data.get("org_id", 1)),
        actors=_parse_actors(data.get("actors")),
        phases=phases,
        metadata={str(k): v for k, v in (data.get("metadata") or {}).items()},
        timeline_minutes=int(data.get("timeline_minutes", 0)),
    )
