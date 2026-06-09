from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from .models import LabProfile


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
    return sorted(p for p in base.glob("*.y*ml")) + sorted(base.glob("*.json"))


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


def merge_lab_into_options(options: Any, lab: LabProfile) -> None:
    if options.target == "10.255.9.3":
        options.target = lab.target
    if options.port == 514:
        options.port = lab.port
    if options.org_id == 1:
        options.org_id = lab.org_id
    if not options.simulation_marker:
        options.simulation_marker = lab.marker
