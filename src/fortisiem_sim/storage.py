from __future__ import annotations

import os
from pathlib import Path

from .db.connection import db_path, ensure_database
from .db.events_repo import load_all_templates, merge_events_import
from .db.assets_repo import load_assets_dict, save_assets_dict
from .db.scenarios_repo import (
    builder_payload,
    list_scenario_ids,
    load_scenario_model,
    resolve_scenario_id,
    save_from_builder,
)
from .assets import scenario_to_yaml
from .loaders import (
    custom_events_path,
    list_scenarios as list_scenario_files,
    load_scenario as load_scenario_file,
    load_templates_merged as load_templates_merged_files,
    merge_custom_events_import as merge_custom_events_files,
    package_root,
    resolve_scenario as resolve_scenario_file,
)
from .assets import (
    default_assets_path,
    load_assets as load_assets_file,
    save_assets as save_assets_file,
)


def use_sql_storage() -> bool:
    mode = os.environ.get("FORTISIEM_SIM_STORAGE", "").strip().lower()
    if mode == "yaml":
        return False
    if mode == "sql":
        return True
    return db_path().exists()


def enable_sql_storage(seed_from_yaml: bool = False, path: Path | None = None) -> Path:
    return ensure_database(seed_from_yaml=seed_from_yaml, path=path)


def load_all_event_templates(base: Path | None = None) -> dict:
    if use_sql_storage():
        return load_all_templates()
    return load_templates_merged_files(base)


def import_event_templates(new_events: dict, path: Path | None = None) -> tuple[list[str], list[str]]:
    if use_sql_storage():
        return merge_events_import(new_events, path=db_path() if path is None else path)
    return merge_custom_events_files(new_events, path=path or custom_events_path())


def load_assets_data(path: Path | None = None) -> dict:
    if use_sql_storage():
        from .db.assets_repo import load_assets_dict_with_smtp
        return load_assets_dict_with_smtp()
    return load_assets_file(path)


def save_assets_data(data: dict, path: Path | None = None) -> Path | None:
    if use_sql_storage():
        save_assets_dict(data)
        return db_path()
    return save_assets_file(data, path)


def list_scenario_refs() -> list[str]:
    if use_sql_storage():
        return list_scenario_ids()
    return [p.stem for p in list_scenario_files()]


def resolve_scenario_ref(value: str) -> str:
    if use_sql_storage():
        return resolve_scenario_id(value)
    return resolve_scenario_file(value).stem


def load_scenario_data(value: str):
    if use_sql_storage():
        scenario_id = resolve_scenario_id(value)
        assets = load_assets_dict()
        return load_scenario_model(scenario_id, assets=assets)
    return load_scenario_file(resolve_scenario_file(value))


def scenario_builder_data(value: str) -> dict:
    if use_sql_storage():
        scenario_id = resolve_scenario_id(value)
        return builder_payload(scenario_id, assets=load_assets_dict())
    from .web import _scenario_builder_payload  # circular — inline instead

    path = resolve_scenario_file(value)
    return _scenario_builder_payload_from_path(path)


def _scenario_builder_payload_from_path(path: Path) -> dict:
    import yaml

    from .loaders import load_scenario
    from .mitre import guess_tactic_from_phase, tactic_by_id

    sc = load_scenario(path)
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    phases_raw = raw.get("phases", {}) if isinstance(raw.get("phases"), dict) else {}
    actor_keys = list(sc.actors.profiles.keys()) if sc.actors.profiles else []
    phases_out = []
    for ph in sc.phases:
        raw_ph = phases_raw.get(ph.name, {}) if isinstance(phases_raw, dict) else {}
        mitre_raw = raw_ph.get("mitre", {}) if isinstance(raw_ph, dict) else {}
        mitre_tactic = str(mitre_raw.get("tactic", "")) if mitre_raw else ""
        if not mitre_tactic:
            mitre_tactic = guess_tactic_from_phase(ph.name, ph.description)
        mitre_techniques = mitre_raw.get("techniques", []) if mitre_raw else []
        tactic = tactic_by_id(mitre_tactic) if mitre_tactic else None
        phase_name = tactic["slug"] if tactic else ph.name
        phases_out.append({
            "name": phase_name,
            "description": ph.description,
            "mitre_tactic": mitre_tactic,
            "mitre_techniques": mitre_techniques,
            "events": [
                {"id": e.id, "count": e.count, "actor": e.actor or ""}
                for e in ph.events
            ],
        })
    return {
        "id": path.stem,
        "name": sc.name,
        "description": sc.description,
        "org_id": sc.org_id,
        "timeline_minutes": sc.timeline_minutes,
        "use_config_actors": False,
        "actor_keys": actor_keys,
        "phases": phases_out,
    }


def save_scenario_data(scenario: dict, assets: dict | None = None) -> str:
    if use_sql_storage():
        return save_from_builder(scenario, assets)
    name = str(scenario.get("name", "custom")).strip().replace(" ", "-").lower()
    if not name:
        raise ValueError("El escenario necesita un nombre")
    path = package_root() / "scenarios" / f"{name}.yml"
    path.write_text(scenario_to_yaml(scenario, assets), encoding="utf-8")
    return path.stem


def storage_label() -> str:
    return "SQLite" if use_sql_storage() else "YAML"
