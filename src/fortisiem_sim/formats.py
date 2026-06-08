from __future__ import annotations

from .models import EventTemplate


SUPPORTED_FORMATS: dict[str, str] = {
    "syslog_generic": "RFC3164 genérico con PRI + hostname",
    "cef": "Common Event Format",
    "fortiedr_cef": "CEF estilo FortiEDR (simulado)",
    "fortigate": "FortiGate key=value (VPN/traffic/event)",
    "linux_auth": "Linux sshd/sudo/auth",
    "windows_security": "Windows Security Event Log (simulado)",
    "esxi_vcenter": "VMware ESXi / vCenter",
    "docker": "Docker / container runtime",
    "nginx_apache": "HTTP access log Nginx/Apache",
    "ot_scada": "OT/SCADA alarmas textuales",
    "crisis_comms": "Comunicación crisis / tabletop IR",
}


def format_rfc3164(pri: int, hostname: str, message: str, syslog_ts: str) -> str:
    host = hostname.strip() or "lab-host"
    return f"<{pri}>{syslog_ts} {host} {message}"


def build_wire_message(template: EventTemplate, body: str, ctx: dict[str, str]) -> str:
    fmt = template.format
    hostname = template.syslog_hostname.replace("{{hostname}}", ctx.get("hostname", "lab-host"))
    if "{{hostname}}" in hostname:
        hostname = ctx.get("hostname", "lab-host")
    pri = template.pri
    ts = ctx.get("syslog_ts", ctx.get("timestamp", ""))

    passthrough = {"nginx_apache", "docker", "ot_scada", "crisis_comms"}
    if fmt in passthrough:
        return body

    if fmt == "cef" and not body.startswith("CEF:"):
        return f"CEF:0|LabVendor|LabSim|2.0|9000|SimulatedEvent|5|{body}"
    if fmt == "fortiedr_cef" and not body.startswith("CEF:"):
        sev = ctx.get("severity", "Medium")
        return (
            f"CEF:0|Fortinet|FortiEDR|7.0|SimulatedDetection|{sev}|"
            f"msg=Simulated EDR src={ctx.get('src_ip')} suser={ctx.get('user')} "
            f"shost={ctx.get('hostname')} cs1Label=simulated cs1=true"
        )
    return format_rfc3164(pri, hostname, body, ts)
