from __future__ import annotations

from typing import Any

# Formato de plantilla → sistema origen mostrado en GUI / catálogo
FORMAT_SYSTEM: dict[str, str] = {
    "syslog_generic": "Genérico",
    "fortigate": "FortiGate",
    "linux_auth": "Linux",
    "cef": "File audit (CEF)",
    "fortiedr_cef": "FortiEDR",
    "windows_security": "Windows",
    "nginx_apache": "Web (Nginx/Apache)",
    "esxi_vcenter": "VMware ESXi",
    "docker": "Docker",
    "ot_scada": "SCADA / OT",
}


def event_system_label(tmpl: Any) -> str:
    """Etiqueta legible del sistema que genera el log (EDR, Windows, OT, …)."""
    explicit = str(getattr(tmpl, "source_system", "") or "").strip()
    if explicit:
        return explicit
    fmt = str(getattr(tmpl, "format", "") or "").strip()
    return FORMAT_SYSTEM.get(fmt, fmt.replace("_", " ").title() if fmt else "—")

# Tácticas MITRE ATT&CK Enterprise (orden kill-chain habitual en tabletop)
MITRE_TACTICS: list[dict[str, Any]] = [
    {
        "id": "TA0043",
        "name": "Reconnaissance",
        "slug": "reconnaissance",
        "techniques": ["T1595", "T1592", "T1589"],
        "description": "TA0043 Reconnaissance — reconocimiento previo simulado",
        "suggested_events": [
            {"id": "outbound_connection", "count": 5, "delay": 0.5, "jitter": 0.2},
            {"id": "web_login", "count": 2, "delay": 1.0},
        ],
    },
    {
        "id": "TA0001",
        "name": "Initial Access",
        "slug": "initial_access",
        "techniques": ["T1078", "T1133", "T1566"],
        "description": "TA0001 Initial Access — T1078 Valid Accounts, T1133 External Remote Services",
        "suggested_events": [
            {"id": "login_failed", "count": 10, "delay": 0.4, "jitter": 0.2},
            {"id": "login_success", "count": 1, "delay": 1.0},
            {"id": "vpn_login_foreign_country", "count": 2, "delay": 2.0},
        ],
    },
    {
        "id": "TA0002",
        "name": "Execution",
        "slug": "execution",
        "techniques": ["T1059", "T1203", "T1047"],
        "description": "TA0002 Execution — T1059 Command and Scripting Interpreter",
        "suggested_events": [
            {"id": "ssh_login", "count": 2, "delay": 1.0},
            {"id": "suspicious_powershell_simulated", "count": 3, "delay": 1.5, "jitter": 0.5},
            {"id": "process_execution", "count": 3, "delay": 0.8},
            {"id": "container_exec", "count": 1, "delay": 1.0},
        ],
    },
    {
        "id": "TA0003",
        "name": "Persistence",
        "slug": "persistence",
        "techniques": ["T1098", "T1136", "T1543"],
        "description": "TA0003 Persistence — T1098 Account Manipulation, T1136 Create Account",
        "suggested_events": [
            {"id": "new_user_created", "count": 1, "delay": 1.0},
            {"id": "privilege_change", "count": 1, "delay": 1.0},
        ],
    },
    {
        "id": "TA0004",
        "name": "Privilege Escalation",
        "slug": "privilege_escalation",
        "techniques": ["T1068", "T1078", "T1548"],
        "description": "TA0004 Privilege Escalation — escalada de privilegios simulada",
        "suggested_events": [
            {"id": "sudo_command", "count": 2, "delay": 1.0},
            {"id": "privilege_change", "count": 1, "delay": 1.0},
        ],
    },
    {
        "id": "TA0005",
        "name": "Defense Evasion",
        "slug": "defense_evasion",
        "techniques": ["T1070", "T1562", "T1036"],
        "description": "TA0005 Defense Evasion — evasión / supresión de alarmas simulada",
        "suggested_events": [
            {"id": "shadow_access_simulated", "count": 2, "delay": 1.5},
            {"id": "alarm_suppressed", "count": 1, "delay": 1.0},
        ],
    },
    {
        "id": "TA0006",
        "name": "Credential Access",
        "slug": "credential_access",
        "techniques": ["T1003", "T1110", "T1558"],
        "description": "TA0006 Credential Access — T1003 OS Credential Dumping (simulado)",
        "suggested_events": [
            {"id": "credential_access_simulated", "count": 3, "delay": 1.5},
            {"id": "login_failed", "count": 5, "delay": 0.3, "jitter": 0.2},
        ],
    },
    {
        "id": "TA0007",
        "name": "Discovery",
        "slug": "discovery",
        "techniques": ["T1083", "T1046", "T1018"],
        "description": "TA0007 Discovery — enumeración de recursos simulada",
        "suggested_events": [
            {"id": "file_access_sensitive", "count": 3, "delay": 0.8},
            {"id": "ssh_login", "count": 1, "delay": 1.0},
        ],
    },
    {
        "id": "TA0008",
        "name": "Lateral Movement",
        "slug": "lateral_movement",
        "techniques": ["T1021", "T1570", "T1080"],
        "description": "TA0008 Lateral Movement — T1021 Remote Services",
        "suggested_events": [
            {"id": "lateral_movement_simulated", "count": 3, "delay": 2.0},
            {"id": "ssh_login", "count": 2, "delay": 1.0},
            {"id": "hypervisor_login", "count": 1, "delay": 1.5},
        ],
    },
    {
        "id": "TA0009",
        "name": "Collection",
        "slug": "collection",
        "techniques": ["T1560", "T1074", "T1114"],
        "description": "TA0009 Collection — staging y archivado simulado",
        "suggested_events": [
            {"id": "file_access_sensitive", "count": 5, "delay": 1.0},
            {"id": "archive_creation", "count": 2, "delay": 2.0},
            {"id": "backup_access", "count": 2, "delay": 1.5},
        ],
    },
    {
        "id": "TA0011",
        "name": "Command and Control",
        "slug": "command_and_control",
        "techniques": ["T1071", "T1095", "T1571"],
        "description": "TA0011 Command and Control — beaconing / C2 simulado",
        "suggested_events": [
            {"id": "outbound_connection", "count": 20, "delay": 0.2, "jitter": 0.1},
        ],
    },
    {
        "id": "TA0010",
        "name": "Exfiltration",
        "slug": "exfiltration",
        "techniques": ["T1048", "T1567", "T1020"],
        "description": "TA0010 Exfiltration — T1048 Exfiltration Over Alternative Protocol",
        "suggested_events": [
            {"id": "web_upload", "count": 4, "delay": 1.0},
            {"id": "outbound_connection", "count": 10, "delay": 0.3, "jitter": 0.1},
        ],
    },
    {
        "id": "TA0040",
        "name": "Impact",
        "slug": "impact",
        "techniques": ["T1486", "T1491", "T1485"],
        "description": "TA0040 Impact — T1486 Data Encrypted for Impact, T1491 Defacement",
        "suggested_events": [
            {"id": "defacement_simulated", "count": 1, "delay": 1.0},
            {"id": "degraded_mode", "count": 2, "delay": 2.0},
            {"id": "telemetry_delay", "count": 5, "delay": 1.0},
        ],
    },
    {
        "id": "TA0042",
        "name": "Resource Development",
        "slug": "resource_development",
        "techniques": ["T1583", "T1584", "T1587"],
        "description": "TA0042 Resource Development — infraestructura adversaria simulada",
        "suggested_events": [
            {"id": "outbound_connection", "count": 3, "delay": 1.0},
        ],
    },
]

# Alias usados en escenarios existentes del repo
_SLUG_ALIASES: dict[str, str] = {
    "recon_and_access": "initial_access",
    "staging_and_exfil": "collection",
    "impact_identity": "impact",
    "ot_and_crisis": "impact",
}


# Mapeo evento → tácticas MITRE + técnicas (TTP)
EVENT_MITRE: dict[str, dict[str, list[str]]] = {
    "login_success": {"tactics": ["TA0001"], "techniques": ["T1078"]},
    "login_failed": {"tactics": ["TA0001", "TA0006"], "techniques": ["T1078", "T1110"]},
    "vpn_login_foreign_country": {"tactics": ["TA0001"], "techniques": ["T1078", "T1133"]},
    "web_login": {"tactics": ["TA0001", "TA0043"], "techniques": ["T1078", "T1595"]},
    "ssh_login": {"tactics": ["TA0001", "TA0002", "TA0007", "TA0008"], "techniques": ["T1078", "T1021"]},
    "suspicious_powershell_simulated": {"tactics": ["TA0002"], "techniques": ["T1059", "T1059.001"]},
    "process_execution": {"tactics": ["TA0002"], "techniques": ["T1059", "T1204"]},
    "container_exec": {"tactics": ["TA0002"], "techniques": ["T1059", "T1609"]},
    "new_user_created": {"tactics": ["TA0003"], "techniques": ["T1136", "T1098"]},
    "privilege_change": {"tactics": ["TA0003", "TA0004"], "techniques": ["T1098", "T1078"]},
    "sudo_command": {"tactics": ["TA0004"], "techniques": ["T1548", "T1068"]},
    "shadow_access_simulated": {"tactics": ["TA0005", "TA0006"], "techniques": ["T1003", "T1070"]},
    "alarm_suppressed": {"tactics": ["TA0005", "TA0040"], "techniques": ["T1562", "T1499"]},
    "credential_access_simulated": {"tactics": ["TA0006"], "techniques": ["T1003", "T1558"]},
    "file_access_sensitive": {"tactics": ["TA0007", "TA0009"], "techniques": ["T1083", "T1005"]},
    "lateral_movement_simulated": {"tactics": ["TA0008"], "techniques": ["T1021", "T1570"]},
    "hypervisor_login": {"tactics": ["TA0008"], "techniques": ["T1021", "T1078"]},
    "archive_creation": {"tactics": ["TA0009"], "techniques": ["T1560", "T1074"]},
    "backup_access": {"tactics": ["TA0009"], "techniques": ["T1074", "T1114"]},
    "web_upload": {"tactics": ["TA0010"], "techniques": ["T1048", "T1567"]},
    "outbound_connection": {"tactics": ["TA0011", "TA0010", "TA0043", "TA0042"], "techniques": ["T1071", "T1048"]},
    "defacement_simulated": {"tactics": ["TA0040"], "techniques": ["T1491", "T1486"]},
    "telemetry_delay": {"tactics": ["TA0040"], "techniques": ["T1499", "T1489"]},
    "degraded_mode": {"tactics": ["TA0040"], "techniques": ["T1499", "T1489"]},
}


def _sync_suggested_events_from_catalog() -> None:
    """Alinea suggested_events de cada táctica con EVENT_MITRE."""
    for tactic in MITRE_TACTICS:
        tid = tactic["id"]
        ids = events_for_tactic(tid)
        existing = {e["id"]: e for e in tactic.get("suggested_events", [])}
        tactic["suggested_events"] = [
            existing.get(eid) or {"id": eid, "count": 3, "delay": 1.0}
            for eid in ids
            if eid in existing or eid in EVENT_MITRE
        ][:6]


def event_mitre_meta(event_id: str, tmpl: Any) -> dict[str, list[str]]:
    if event_id in EVENT_MITRE:
        return EVENT_MITRE[event_id]
    tactics = list(getattr(tmpl, "mitre_tactics", []) or [])
    techniques = list(getattr(tmpl, "mitre_techniques", []) or [])
    if not tactics and not techniques:
        for item in getattr(tmpl, "mitre", []) or []:
            s = str(item).strip()
            if s.upper().startswith("TA"):
                tactics.append(s.upper())
            elif s.upper().startswith("T"):
                techniques.append(s)
    return {"tactics": tactics, "techniques": techniques}


def events_for_tactic(tactic_id: str, templates: dict[str, Any] | None = None) -> list[str]:
    tid = tactic_id.strip().upper()
    found = {
        eid
        for eid, meta in EVENT_MITRE.items()
        if tid in meta.get("tactics", [])
    }
    if templates:
        for eid, tmpl in templates.items():
            if tid in (getattr(tmpl, "mitre_tactics", []) or []):
                found.add(eid)
    return sorted(found)


def build_event_catalog(templates: dict[str, Any]) -> list[dict[str, Any]]:
    catalog: list[dict[str, Any]] = []
    for event_id in sorted(templates.keys()):
        tmpl = templates[event_id]
        meta = event_mitre_meta(event_id, tmpl)
        catalog.append({
            "id": event_id,
            "name": getattr(tmpl, "name", event_id),
            "format": getattr(tmpl, "format", ""),
            "system": event_system_label(tmpl),
            "severity": getattr(tmpl, "severity", ""),
            "tactics": meta.get("tactics", []),
            "techniques": meta.get("techniques", []),
        })
    return catalog


def index_events_by_tactic(catalog: list[dict[str, Any]]) -> dict[str, list[str]]:
    by_tactic: dict[str, list[str]] = {t["id"]: [] for t in MITRE_TACTICS}
    for item in catalog:
        for tid in item.get("tactics", []):
            if tid in by_tactic:
                by_tactic[tid].append(item["id"])
    for tid in by_tactic:
        by_tactic[tid] = sorted(by_tactic[tid])
    return by_tactic


def list_tactics() -> list[dict[str, Any]]:
    return MITRE_TACTICS


def tactic_by_id(tactic_id: str) -> dict[str, Any] | None:
    tid = tactic_id.strip().upper()
    for t in MITRE_TACTICS:
        if t["id"].upper() == tid or t["slug"] == tactic_id.strip().lower():
            return t
    alias = _SLUG_ALIASES.get(tactic_id.strip().lower())
    if alias:
        return tactic_by_id(alias)
    return None


def guess_tactic_from_phase(phase_name: str, description: str = "") -> str:
    """Devuelve tactic id (TAxxxx) si se reconoce la fase."""
    key = phase_name.strip().lower()
    if key in _SLUG_ALIASES:
        t = tactic_by_id(_SLUG_ALIASES[key])
        return t["id"] if t else ""
    for t in MITRE_TACTICS:
        if t["slug"] == key:
            return t["id"]
    text = f"{phase_name} {description}".upper()
    for t in MITRE_TACTICS:
        if t["id"] in text:
            return t["id"]
    return ""


_sync_suggested_events_from_catalog()
