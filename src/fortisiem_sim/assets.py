from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from .loaders import package_root
from .c2 import DEFAULT_C2_IP, DEFAULT_C2_URI, merge_c2_import, normalize_c2, parse_c2_text
from .mail import normalize_smtp
from .mitre import tactic_by_id
from .models import Scenario


def default_assets_path() -> Path:
    return package_root() / "config" / "assets.yaml"


def load_assets(path: Path | None = None) -> dict[str, Any]:
    from .storage import load_assets_data, use_sql_storage

    if use_sql_storage() and path is None:
        return load_assets_data()
    assets_file = path or default_assets_path()
    if not assets_file.exists():
        return _empty_assets()
    data = yaml.safe_load(assets_file.read_text(encoding="utf-8")) or {}
    return _normalize_assets(data)


def save_assets(data: dict[str, Any], path: Path | None = None) -> Path:
    from .storage import save_assets_data, use_sql_storage

    if use_sql_storage() and path is None:
        result = save_assets_data(data)
        return result or default_assets_path()
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
        "c2": normalize_c2(None),
        "smtp": normalize_smtp(None),
    }



def _norm_user(raw: Any) -> dict[str, str]:
    if isinstance(raw, dict):
        username = str(raw.get("username") or raw.get("samaccountname") or "").strip()
        email = str(raw.get("email") or f"{username}@age.local").strip()
        return {"username": username, "email": email}
    name = str(raw).strip()
    return {"username": name, "email": f"{name}@age.local"}


def _normalize_assets(data: dict[str, Any]) -> dict[str, Any]:
    ad = data.get("ad") or {}
    pools = data.get("pools") or {}
    c2 = normalize_c2(data.get("c2"))
    smtp = normalize_smtp(data.get("smtp"))
    return {
        "ad": {
            "primary_domain": str(ad.get("primary_domain", "lab.local")),
            "domains": [str(x) for x in ad.get("domains", ["lab.local"])],
            "users": [_norm_user(x) for x in ad.get("users", [])],
        },
        "firewalls": [_norm_fw(x) for x in data.get("firewalls", []) if isinstance(x, dict)],
        "windows_hosts": [_norm_host(x) for x in data.get("windows_hosts", []) if isinstance(x, dict)],
        "linux_hosts": [_norm_host(x) for x in data.get("linux_hosts", []) if isinstance(x, dict)],
        "pools": {
            "src_ips": [str(x) for x in pools.get("src_ips", [])],
            "reporting_ips": [str(x) for x in pools.get("reporting_ips", [])],
            "c2_ips": c2["ips"],
            "c2_uris": c2["uris"],
            "c2_default_ip": c2["default_ip"],
            "c2_default_uri": c2["default_uri"],
        },
        "c2": c2,
        "smtp": smtp,
        "stats": data.get("stats") or {},
        "storage": data.get("storage") or "",
        "vmware_users": data.get("vmware_users") or [],
        "vmware_assets": data.get("vmware_assets") or [],
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


def _username_from_user_entry(entry: Any) -> str:
    if isinstance(entry, dict):
        return str(entry.get("username") or entry.get("samaccountname") or "").strip()
    return str(entry).strip()


def _usernames_from_ad(ad: dict[str, Any]) -> list[str]:
    return [_username_from_user_entry(u) for u in ad.get("users", []) if _username_from_user_entry(u)]


def assets_to_actors(assets: dict[str, Any]) -> dict[str, Any]:
    """Genera bloque actors YAML a partir del inventario Config."""
    ad = assets.get("ad", {})
    domain = ad.get("primary_domain", "lab.local")
    profiles: dict[str, Any] = {}
    user_names = _usernames_from_ad(ad)
    default_user = user_names[0] if user_names else "vpn.user"

    for i, fw in enumerate(assets.get("firewalls", [])):
        key = f"firewall_{i + 1}" if i else "firewall"
        profiles[key] = {
            "user": default_user,
            "domain": domain,
            "src_ip": fw["src_ip"],
            "reporting_ip": fw["reporting_ip"],
            "hostname": fw["devname"],
            "extra": {
                "devname": fw["devname"],
                "serial": fw.get("serial", "FGT00000000"),
                "vpn_gateway_ip": fw["src_ip"],
            },
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
    all_users = user_names or ["lab.user"]
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
            "c2_ips": assets.get("c2", {}).get("ips", [DEFAULT_C2_IP]),
            "c2_uris": assets.get("c2", {}).get("uris", [DEFAULT_C2_URI]),
            "c2_default_ip": assets.get("c2", {}).get("default_ip", DEFAULT_C2_IP),
            "c2_default_uri": assets.get("c2", {}).get("default_uri", DEFAULT_C2_URI),
        },
    }


def apply_config_c2_to_scenario(scenario: Scenario) -> None:
    """Inyecta IOC C2 desde config/assets.yaml en los pools del escenario."""
    c2 = normalize_c2(load_assets().get("c2"))
    pools = scenario.actors.pools
    pools.c2_ips = list(c2["ips"])
    pools.c2_uris = list(c2["uris"])
    pools.c2_default_ip = c2["default_ip"]
    pools.c2_default_uri = c2["default_uri"]


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
        tactic = tactic_by_id(str(ph.get("mitre_tactic", ""))) if ph.get("mitre_tactic") else None
        name = tactic["slug"] if tactic else str(ph.get("name", "phase")).strip().replace(" ", "_")
        events = []
        for ev in ph.get("events", []):
            item: dict[str, Any] = {
                "id": ev["id"],
                "count": int(ev.get("count", 1)),
            }
            if ev.get("actor"):
                item["actor"] = ev["actor"]
            if ev.get("overrides"):
                item["overrides"] = ev["overrides"]
            events.append(item)
        phase_doc: dict[str, Any] = {
            "description": ph.get("description", ""),
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
    from .storage import save_scenario_data

    ref = save_scenario_data(scenario, assets)
    return package_root() / "scenarios" / f"{ref}.yml"
