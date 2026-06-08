from __future__ import annotations

import ipaddress
import re
from pathlib import Path

from .formats import SUPPORTED_FORMATS
from .loaders import load_scenario, load_templates
from .models import EventTemplate, Scenario


def validate_templates(templates: dict[str, EventTemplate]) -> list[str]:
    errors: list[str] = []
    for event_id, tmpl in templates.items():
        if tmpl.id != event_id:
            errors.append(f"ID inconsistente: clave {event_id!r} vs id {tmpl.id!r}")
        if not tmpl.body.strip():
            errors.append(f"Evento {event_id}: body vacío")
        if tmpl.format not in SUPPORTED_FORMATS:
            errors.append(f"Evento {event_id}: formato desconocido {tmpl.format!r}")
        if tmpl.pri < 0 or tmpl.pri > 199:
            errors.append(f"Evento {event_id}: PRI fuera de rango ({tmpl.pri})")
    return errors


def validate_scenario(scenario: Scenario, templates: dict[str, EventTemplate]) -> list[str]:
    errors: list[str] = []
    if not scenario.phases:
        errors.append("Escenario sin fases")
    seen_phases: set[str] = set()
    for phase in scenario.phases:
        if phase.name in seen_phases:
            errors.append(f"Fase duplicada: {phase.name!r}")
        seen_phases.add(phase.name)
        if not phase.events:
            errors.append(f"Fase {phase.name!r} sin eventos")
        for event in phase.events:
            if event.id not in templates:
                errors.append(f"Fase {phase.name}: evento desconocido {event.id!r}")
            if event.count < 1:
                errors.append(f"Fase {phase.name}: count inválido en {event.id}")
            if event.actor and event.actor not in scenario.actors.profiles:
                errors.append(
                    f"Fase {phase.name}: actor {event.actor!r} no definido en actors.profiles"
                )
    for name, profile in scenario.actors.profiles.items():
        for label, value in (("src_ip", profile.src_ip), ("reporting_ip", profile.reporting_ip)):
            try:
                ipaddress.IPv4Address(value)
            except ValueError:
                errors.append(f"Actor {name}: {label} no es IPv4 válida ({value})")
    return errors


def validate_all(scenario_path: Path, templates_path: Path) -> list[str]:
    templates = load_templates(templates_path)
    scenario = load_scenario(scenario_path)
    errors = validate_templates(templates)
    errors.extend(validate_scenario(scenario, templates))
    return errors
