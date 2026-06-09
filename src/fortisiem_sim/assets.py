from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from .loaders import package_root


def default_assets_path() -> Path:
    return package_root() / "config" / "assets.yaml"


def load_assets(path: Path | None = None) -> dict[str, Any]:
    assets_file = path or default_assets_path()
    if not assets_file.exists():
        return _empty_assets()
    data = yaml.safe_load(assets_file.read_text(encoding="utf-8")) or {}
    return _normalize_assets(data)


def save_assets(data: dict[str, Any], path: Path | None = None) -> Path:
    assets_file = path or default_assets_path()
    assets_file.parent.mkdir(parents=True, exist_ok=True)
    normalized = _normalize_assets(data)
    assets_file.write_text(
        yaml.dump(normalized, allow_unicode=True, sort_keys=False, default_flow_style=False),
        encoding="utf-8",
    )
    return assets_file


def _empty_assets() -> dict[str, Any]:
    return {
        "ad": {"primary_domain": "lab.local", "domains": ["lab.local"], "users": []},
        "firewalls": [],
        "windows_hosts": [],
        "linux_hosts": [],
        "pools": {"src_ips": [], "reporting_ips": []},
    }


def _normalize_assets(data: dict[str, Any]) -> dict[str, Any]:
    ad = data.get("ad") or {}
    pools = data.get("pools") or {}
    return {
        "ad": {
            "primary_domain": str(ad.get("primary_domain", "lab.local")),
            "domains": [str(x) for x in ad.get("domains", ["lab.local"])],
            "users": [str(x) for x in ad.get("users", [])],
        },
        "firewalls": [_norm_fw(x) for x in data.get("firewalls", []) if isinstance(x, dict)],
        "windows_hosts": [_norm_host(x) for x in data.get("windows_hosts", []) if isinstance(x, dict)],
        "linux_hosts": [_norm_host(x) for x in data.get("linux_hosts", []) if isinstance(x, dict)],
        "pools": {
            "src_ips": [str(x) for x in pools.get("src_ips", [])],
            "reporting_ips": [str(x) for x in pools.get("reporting_ips", [])],
        },
    }


def _norm_fw(raw: dict[str, Any]) -> dict[str, str]:
    name = str(raw.get("name", raw.get("devname", "FGT-LAB-01")))
    return {
        "name": name,
        "devname": str(raw.get("devname", name)),
        "serial": str(raw.get("serial", "FGT60FTK23000001")),
        "src_ip": str(raw.get("src_ip", "10.255.9.21")),
        "reporting_ip": str(raw.get("reporting_ip", raw.get("src_ip", "10.255.9.21"))),
    }


def _norm_host(raw: dict[str, Any]) -> dict[str, str]:
    return {
        "hostname": str(raw.get("hostname", "ws-lab-01")),
        "user": str(raw.get("user", "lab.user")),
        "src_ip": str(raw.get("src_ip", "10.10.10.50")),
        "reporting_ip": str(raw.get("reporting_ip", raw.get("src_ip", "10.255.9.21"))),
    }


def assets_to_actors(assets: dict[str, Any]) -> dict[str, Any]:
    """Genera bloque actors YAML a partir del inventario Config."""
    ad = assets.get("ad", {})
    domain = ad.get("primary_domain", "lab.local")
    profiles: dict[str, Any] = {}

    for i, fw in enumerate(assets.get("firewalls", [])):
        key = f"firewall_{i + 1}" if i else "firewall"
        profiles[key] = {
            "user": ad.get("users", ["lab.user"])[0] if ad.get("users") else "vpn.user",
            "domain": domain,
            "src_ip": fw["src_ip"],
            "reporting_ip": fw["reporting_ip"],
            "hostname": fw["devname"],
        }

    for i, host in enumerate(assets.get("windows_hosts", [])):
        key = host["hostname"].replace("-", "_")
        profiles[key] = {
            "user": host["user"],
            "domain": domain,
            "src_ip": host["src_ip"],
            "reporting_ip": host["reporting_ip"],
            "hostname": host["hostname"],
        }

    for i, host in enumerate(assets.get("linux_hosts", [])):
        key = f"linux_{host['hostname'].replace('-', '_')}"
        profiles[key] = {
            "user": host["user"],
            "domain": domain,
            "src_ip": host["src_ip"],
            "reporting_ip": host["reporting_ip"],
            "hostname": host["hostname"],
        }

    if not profiles:
        profiles["default"] = {
            "user": "lab.user",
            "domain": domain,
            "src_ip": "10.10.10.50",
            "reporting_ip": "10.255.9.21",
            "hostname": "ws-lab-01",
        }

    pools = assets.get("pools", {})
    all_users = ad.get("users", [])
    all_hostnames = [h["hostname"] for h in assets.get("windows_hosts", [])]
    all_hostnames += [h["hostname"] for h in assets.get("linux_hosts", [])]
    all_src = pools.get("src_ips") or [p["src_ip"] for p in profiles.values()]
    all_rep = pools.get("reporting_ips") or [p["reporting_ip"] for p in profiles.values()]

    return {
        "default_profile": next(iter(profiles)),
        "profiles": profiles,
        "pools": {
            "users": all_users,
            "domains": ad.get("domains", [domain]),
            "hostnames": all_hostnames or ["ws-lab-01"],
            "src_ips": list(dict.fromkeys(all_src)),
            "reporting_ips": list(dict.fromkeys(all_rep)),
        },
    }


def scenario_to_yaml(scenario: dict[str, Any], assets: dict[str, Any] | None = None) -> str:
    """Convierte dict del builder a YAML compatible con load_scenario."""
    doc: dict[str, Any] = {
        "name": scenario.get("name", "custom-scenario"),
        "description": scenario.get("description", ""),
        "org_id": int(scenario.get("org_id", 1)),
        "timeline_minutes": int(scenario.get("timeline_minutes", 0)),
        "metadata": scenario.get("metadata") or {
            "classification": "simulated-only",
            "created_by": "fortisiem-sim-gui",
        },
    }
    if scenario.get("use_config_actors", True) and assets:
        doc["actors"] = assets_to_actors(assets)
    elif scenario.get("actors"):
        doc["actors"] = scenario["actors"]

    phases: dict[str, Any] = {}
    for ph in scenario.get("phases", []):
        name = str(ph.get("name", "phase")).strip().replace(" ", "_")
        events = []
        for ev in ph.get("events", []):
            item: dict[str, Any] = {
                "id": ev["id"],
                "count": int(ev.get("count", 1)),
            }
            if ev.get("actor"):
                item["actor"] = ev["actor"]
            if ev.get("delay") is not None and ev.get("delay") != "":
                item["delay"] = float(ev["delay"])
            if ev.get("jitter") is not None and ev.get("jitter") != "":
                item["jitter"] = float(ev["jitter"])
            if ev.get("overrides"):
                item["overrides"] = ev["overrides"]
            events.append(item)
        phase_doc: dict[str, Any] = {
            "description": ph.get("description", ""),
            "delay_before": float(ph.get("delay_before", 0)),
            "events": events,
        }
        if ph.get("mitre_tactic"):
            phase_doc["mitre"] = {
                "tactic": ph["mitre_tactic"],
                "techniques": ph.get("mitre_techniques") or [],
            }
        phases[name] = phase_doc
    doc["phases"] = phases
    return yaml.dump(doc, allow_unicode=True, sort_keys=False, default_flow_style=False)


def save_scenario_from_builder(scenario: dict[str, Any], assets: dict[str, Any] | None = None) -> Path:
    name = str(scenario.get("name", "custom")).strip().replace(" ", "-").lower()
    if not name:
        raise ValueError("El escenario necesita un nombre")
    path = package_root() / "scenarios" / f"{name}.yml"
    yaml_text = scenario_to_yaml(scenario, assets)
    path.write_text(yaml_text, encoding="utf-8")
    return path
