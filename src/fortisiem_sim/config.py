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
