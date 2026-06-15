from __future__ import annotations

import json
import re
from pathlib import Path

import yaml

from .catalog_repo import upsert_catalog_event
from .connection import get_connection, init_schema
from .events_repo import _upsert_mitre

_PLACEHOLDER = re.compile(r"\{\{(\w+)\}\}")
_SYSLOG_PREFIX = re.compile(
    r"^(?:\{\{timestamp(?:_iso|_nginx|_nginx_error)?\}\}\s+)?(?:\{\{host\}\}\s+)?"
)

_VAR_MAP = {
    "user": "username",
    "command": "command_line",
    "host": "hostname",
}

_CATEGORY_MAP = {
    "autenticacion": "auth",
    "privilegios": "sudo",
    "servicios": "systemd",
    "desactivacion_defensas": "defense",
    "sistema": "system",
    "tareas_programadas": "cron",
    "paquetes": "packages",
    "red": "network",
    "firewall": "firewall",
    "auditd": "audit",
    "almacenamiento": "storage",
    "web": "web",
    "contenedores": "docker",
    "hardware": "hardware",
    "integridad_archivos": "fim",
    "persistencia": "persistence",
    "ejecucion": "execution",
    "ofuscacion_ejecucion": "obfuscation",
    "shell_remota": "reverse-shell",
    "tunneling": "tunneling",
    "borrado_logs": "log-tampering",
    "borrado_historial": "history",
    "cuentas": "accounts",
    "permisos": "permissions",
    "captura_red": "sniffing",
    "elevacion_privilegios": "privilege-escalation",
    "persistencia_evasion": "persistence",
    "persistencia_acceso": "persistence",
    "preparacion_exfiltracion": "collection",
    "exfiltracion": "exfiltration",
    "ejecucion_web": "web-exec",
    "credenciales": "credentials",
}

_SEVERITY_MAP = {
    "info": "low",
    "notice": "low",
    "warning": "medium",
    "medium": "medium",
    "high": "high",
    "critical": "critical",
}

_WEIGHT_BY_SEVERITY = {
    "low": 5,
    "medium": 7,
    "high": 8,
    "critical": 10,
}

_TTP_BY_CATEGORY = {
    "auth": "initial-access",
    "ssh": "initial-access",
    "sudo": "privilege-escalation",
    "systemd": "persistence",
    "cron": "persistence",
    "persistence": "persistence",
    "defense": "defense-evasion",
    "execution": "execution",
    "obfuscation": "execution",
    "reverse-shell": "execution",
    "tunneling": "command-and-control",
    "log-tampering": "defense-evasion",
    "history": "defense-evasion",
    "accounts": "persistence",
    "permissions": "defense-evasion",
    "privilege-escalation": "privilege-escalation",
    "collection": "impact",
    "exfiltration": "impact",
    "web-exec": "execution",
    "credentials": "credential-access",
    "audit": "credential-access",
    "web": "initial-access",
    "network": "discovery",
    "firewall": "discovery",
    "docker": "execution",
    "fim": "defense-evasion",
    "packages": "execution",
}


def _normalize_body(plantilla: str) -> str:
    body = str(plantilla or "").strip()
    body = _SYSLOG_PREFIX.sub("", body)

    def _repl(match: re.Match[str]) -> str:
        name = match.group(1)
        return "{" + _VAR_MAP.get(name, name) + "}"

    return _PLACEHOLDER.sub(_repl, body)


def _map_category(raw: str) -> str:
    key = (raw or "").strip().lower()
    return _CATEGORY_MAP.get(key, key.replace("_", "-") or "generic")


def _map_severity(raw: str, legitimidad: str) -> str:
    sev = _SEVERITY_MAP.get((raw or "medium").strip().lower(), "medium")
    if legitimidad == "non-legit" and sev == "low":
        return "medium"
    return sev


def _infer_action(ev: dict, category: str, legitimidad: str) -> str:
    eid = str(ev.get("id", "")).lower()
    if "failed" in eid or "failure" in eid or "invalid" in eid or "block" in eid:
        return "failure"
    if legitimidad == "non-legit":
        if category in {"persistence", "log-tampering", "history", "collection"}:
            return "create"
        if category in {"execution", "obfuscation", "reverse-shell", "web-exec"}:
            return "execute"
        if category in {"defense", "fim", "permissions"}:
            return "modify"
        return "detect"
    if "login" in eid or "success" in eid or "opened" in eid:
        return "success"
    if "stopped" in eid or "closed" in eid:
        return "stop"
    if "started" in eid or "start" in eid:
        return "start"
    if category == "sudo":
        return "execute"
    if category == "cron":
        return "execute"
    return "success"


def _weight_for(severity: str, legitimidad: str) -> int:
    base = _WEIGHT_BY_SEVERITY.get(severity, 6)
    return min(10, base + (1 if legitimidad == "non-legit" else 0))


def _techniques_from_event(ev: dict) -> list[str]:
    mitre = ev.get("mitre") or {}
    raw = mitre.get("tecnicas") or mitre.get("techniques") or []
    return [str(t).strip() for t in raw if str(t).strip()]


def _tactics_for_techniques(techniques: list[str]) -> list[str]:
    from ..mitre import MITRE_TACTICS

    tactics: list[str] = []
    for tech in techniques:
        base = tech.split(".")[0]
        for tactic in MITRE_TACTICS:
            if any(t == tech or t == base or t.startswith(base) for t in tactic.get("techniques", [])):
                tid = tactic["id"]
                if tid not in tactics:
                    tactics.append(tid)
    return tactics


def _ttp_slug(category: str, legitimidad: str, techniques: list[str]) -> str:
    if legitimidad == "non-legit" and category in {"auth", "audit"}:
        return "credential-access"
    if techniques:
        t0 = techniques[0]
        if t0.startswith("T1110"):
            return "credential-access"
        if t0.startswith("T1021"):
            return "initial-access"
        if t0.startswith("T1548"):
            return "privilege-escalation"
        if t0.startswith("T1053"):
            return "persistence"
        if t0.startswith("T1562"):
            return "defense-evasion"
        if t0.startswith("T1059"):
            return "execution"
        if t0.startswith("T1190"):
            return "initial-access"
    return _TTP_BY_CATEGORY.get(category, "execution" if legitimidad == "non-legit" else "initial-access")


def _catalog_event_to_row(ev: dict) -> dict:
    legitimidad = str(ev.get("legitimidad", "legit")).strip().lower()
    category = _map_category(str(ev.get("categoria", "")))
    severity = _map_severity(str(ev.get("severidad_sugerida", "medium")), legitimidad)
    programa = str(ev.get("programa", "")).strip()
    yaml_id = str(ev.get("id", "")).strip()
    event_id = yaml_id if yaml_id.startswith("linux_") else f"linux_{yaml_id}"
    tags = ",".join(
        t
        for t in (
            "linux",
            category,
            programa.lower() if programa else "",
            legitimidad.replace("-", ""),
        )
        if t
    )
    return {
        "id": event_id,
        "source": "linux",
        "category": category,
        "event_group": category,
        "event_name": str(ev.get("nombre", yaml_id)),
        "severity": severity,
        "action": _infer_action(ev, category, legitimidad),
        "weight": _weight_for(severity, legitimidad),
        "template": _normalize_body(str(ev.get("plantilla", ""))),
        "tags": tags,
        "ttp": _ttp_slug(category, legitimidad, _techniques_from_event(ev)),
        "format": "syslog_generic",
    }


def parse_linux_catalog_yaml(text: str) -> list[dict]:
    data = yaml.safe_load(text)
    if not isinstance(data, dict):
        raise ValueError("YAML inválido: la raíz debe ser un objeto")
    root = data.get("catalogo_eventos_linux")
    if not isinstance(root, dict):
        raise ValueError("Falta sección 'catalogo_eventos_linux'")
    eventos = root.get("eventos")
    if not isinstance(eventos, list) or not eventos:
        raise ValueError("Falta lista 'eventos' en catalogo_eventos_linux")
    return [ev for ev in eventos if isinstance(ev, dict) and ev.get("id")]


def import_linux_catalog_yaml(
    path: Path,
    *,
    db_path: Path | None = None,
) -> dict[str, int | list[str]]:
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(path)
    eventos = parse_linux_catalog_yaml(path.read_text(encoding="utf-8"))
    conn = get_connection(db_path)
    init_schema(conn)
    imported: list[str] = []
    try:
        for ev in eventos:
            row = _catalog_event_to_row(ev)
            if not row["template"]:
                continue
            upsert_catalog_event(conn, row)
            techniques = _techniques_from_event(ev)
            tactics = _tactics_for_techniques(techniques)
            _upsert_mitre(conn, row["id"], tactics, techniques)
            imported.append(row["id"])
        conn.commit()
        total_linux = conn.execute(
            "SELECT COUNT(*) AS n FROM event_templates WHERE source_system='linux'"
        ).fetchone()["n"]
    finally:
        conn.close()
    return {"imported": len(imported), "linux_total": total_linux, "ids": imported}


def default_catalog_path() -> Path:
    here = Path(__file__).resolve().parents[3]
    preferred = here / "config" / "catalogo_eventos_linux.yaml"
    if preferred.exists():
        return preferred
    alt = Path.home() / "fortisiem-sim" / "catalogo_eventos_linux.yaml"
    return alt if alt.exists() else preferred


def main(argv: list[str] | None = None) -> int:
    import argparse

    p = argparse.ArgumentParser(description="Import Linux event catalog YAML into fortisiem.db")
    p.add_argument("yaml", type=Path, nargs="?", default=None, help="catalogo_eventos_linux.yaml")
    p.add_argument("--db", type=Path, default=None)
    args = p.parse_args(argv)
    path = args.yaml or default_catalog_path()
    result = import_linux_catalog_yaml(path, db_path=args.db)
    print(json.dumps({k: v for k, v in result.items() if k != "ids"}, indent=2))
    print(f"ids: {len(result['ids'])} eventos")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
