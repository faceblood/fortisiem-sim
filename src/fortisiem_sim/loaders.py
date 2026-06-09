from __future__ import annotations

import ipaddress
import json
from pathlib import Path
from typing import Any

import yaml

from .models import (
    ActorPools,
    ActorProfile,
    EventTemplate,
    LabProfile,
    Scenario,
    ScenarioActors,
    ScenarioEvent,
    ScenarioPhase,
    SendOptions,
)

# --------------------------------------------------------------------------- #
# Rutas del proyecto
# --------------------------------------------------------------------------- #

def package_root() -> Path:
    return Path(__file__).resolve().parent.parent.parent


def default_lab_path() -> Path:
    return package_root() / "lab.yaml"


def default_templates_path() -> Path:
    return package_root() / "templates" / "events.yaml"


def scenarios_dir() -> Path:
    return package_root() / "scenarios"


def list_scenarios() -> list[Path]:
    base = scenarios_dir()
    if not base.exists():
        return []
    return sorted(base.glob("*.y*ml")) + sorted(base.glob("*.json"))


def resolve_scenario(value: str) -> Path:
    """Acepta ruta completa o nombre corto (p.ej. 'ransomware' -> ransomware-tabletop.yml)."""
    candidate = Path(value)
    if candidate.exists():
        return candidate
    available = list_scenarios()
    stem = value.lower().removesuffix(".yml").removesuffix(".yaml").removesuffix(".json")
    exact = [p for p in available if p.stem.lower() == stem]
    if exact:
        return exact[0]
    partial = [p for p in available if stem in p.stem.lower()]
    if len(partial) == 1:
        return partial[0]
    if len(partial) > 1:
        names = ", ".join(p.stem for p in partial)
        raise ValueError(f"'{value}' es ambiguo. Coincidencias: {names}")
    names = ", ".join(p.stem for p in available) or "(ninguno)"
    raise ValueError(f"Escenario '{value}' no encontrado. Disponibles: {names}")


def resolve_templates_path(options: SendOptions) -> Path:
    return Path(options.templates_path) if options.templates_path else default_templates_path()


# --------------------------------------------------------------------------- #
# Perfil de laboratorio (lab.yaml)
# --------------------------------------------------------------------------- #

def load_lab_profile(path: Path | None = None) -> LabProfile:
    lab_file = path or default_lab_path()
    if not lab_file.exists():
        return LabProfile()
    data = yaml.safe_load(lab_file.read_text(encoding="utf-8")) or {}
    fs = data.get("fortisiem") or {}
    sim = data.get("simulation") or {}
    return LabProfile(
        target=str(fs.get("target", "10.255.9.3")),
        port=int(fs.get("port", 514)),
        org_id=int(fs.get("org_id", 1)),
        version=str(fs.get("version", "7.5")),
        edition=str(fs.get("edition", "enterprise")),
        marker=str(sim.get("marker", "simulated=true")),
        default_delay=float(sim.get("default_delay", 0.5)),
        default_jitter=float(sim.get("default_jitter", 0.2)),
    )


def merge_lab_into_options(options: SendOptions, lab: LabProfile) -> None:
    """Rellena con valores de lab.yaml solo si el usuario no los cambió por CLI."""
    if options.target == "10.255.9.3":
        options.target = lab.target
    if options.port == 514:
        options.port = lab.port
    if options.org_id == 1:
        options.org_id = lab.org_id
    if not options.simulation_marker:
        options.simulation_marker = lab.marker


# --------------------------------------------------------------------------- #
# Carga de plantillas y escenarios
# --------------------------------------------------------------------------- #

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


def _parse_pools(raw: dict[str, Any]) -> ActorPools:
    d = ActorPools()
    return ActorPools(
        users=[str(x) for x in raw.get("users", d.users)],
        hostnames=[str(x) for x in raw.get("hostnames", d.hostnames)],
        src_ips=[str(x) for x in raw.get("src_ips", d.src_ips)],
        reporting_ips=[str(x) for x in raw.get("reporting_ips", d.reporting_ips)],
        domains=[str(x) for x in raw.get("domains", d.domains)],
    )


def _parse_profiles(raw: dict[str, Any] | None) -> dict[str, ActorProfile]:
    profiles: dict[str, ActorProfile] = {}
    for name, item in (raw or {}).items():
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
    profiles.setdefault("default", ActorProfile(name="default"))
    return profiles


def _parse_actors(raw: dict[str, Any] | None) -> ScenarioActors:
    raw = raw or {}
    pools_src = raw if (raw.get("users") or raw.get("src_ips")) else (raw.get("pools") or {})
    return ScenarioActors(
        profiles=_parse_profiles(raw.get("profiles")),
        pools=_parse_pools(pools_src),
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
    return ScenarioPhase(
        name=name,
        description=str(raw.get("description", "")),
        delay_before=float(raw.get("delay_before", 0.0)),
        events=[_parse_event(i) for i in raw.get("events", []) if isinstance(i, dict)],
    )


def load_scenario(path: Path) -> Scenario:
    data = _load_raw(path)
    phases_raw = data.get("phases", {})
    phases: list[ScenarioPhase] = []
    if isinstance(phases_raw, dict):
        phases = [_parse_phase(str(n), p) for n, p in phases_raw.items() if isinstance(p, dict)]
    elif isinstance(phases_raw, list):
        phases = [_parse_phase(str(i["name"]), i) for i in phases_raw if isinstance(i, dict) and "name" in i]
    return Scenario(
        name=str(data.get("name", path.stem)),
        description=str(data.get("description", "")),
        org_id=int(data.get("org_id", 1)),
        actors=_parse_actors(data.get("actors")),
        phases=phases,
        metadata={str(k): v for k, v in (data.get("metadata") or {}).items()},
        timeline_minutes=int(data.get("timeline_minutes", 0)),
    )


# --------------------------------------------------------------------------- #
# Validación
# --------------------------------------------------------------------------- #

def validate_all(scenario_path: Path, templates_path: Path) -> list[str]:
    from .render import SUPPORTED_FORMATS

    templates = load_templates(templates_path)
    scenario = load_scenario(scenario_path)
    errors: list[str] = []

    for event_id, tmpl in templates.items():
        if not tmpl.body.strip():
            errors.append(f"Evento {event_id}: body vacío")
        if tmpl.format not in SUPPORTED_FORMATS:
            errors.append(f"Evento {event_id}: formato desconocido {tmpl.format!r}")
        if not 0 <= tmpl.pri <= 199:
            errors.append(f"Evento {event_id}: PRI fuera de rango ({tmpl.pri})")

    if not scenario.phases:
        errors.append("Escenario sin fases")
    seen: set[str] = set()
    for phase in scenario.phases:
        if phase.name in seen:
            errors.append(f"Fase duplicada: {phase.name!r}")
        seen.add(phase.name)
        if not phase.events:
            errors.append(f"Fase {phase.name!r} sin eventos")
        for event in phase.events:
            if event.id not in templates:
                errors.append(f"Fase {phase.name}: evento desconocido {event.id!r}")
            if event.actor and event.actor not in scenario.actors.profiles:
                errors.append(f"Fase {phase.name}: actor {event.actor!r} no definido")

    for name, profile in scenario.actors.profiles.items():
        for label, value in (("src_ip", profile.src_ip), ("reporting_ip", profile.reporting_ip)):
            try:
                ipaddress.IPv4Address(value)
            except ValueError:
                errors.append(f"Actor {name}: {label} no es IPv4 válida ({value})")
    return errors
