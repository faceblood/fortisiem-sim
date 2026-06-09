from __future__ import annotations

import ipaddress
import re
from typing import Any
from urllib.parse import urlparse

# RFC 5737 TEST-NET — defaults lab-only (sin C2 real)
DEFAULT_C2_IP = "203.0.113.50"
DEFAULT_C2_URI = "https://lab-c2.example/beacon"

_IOC_LINE = re.compile(r"^\s*#")


def classify_ioc(line: str) -> tuple[str, str]:
    """Clasifica una línea IOC en ('ip', addr) o ('uri', url)."""
    raw = line.strip()
    if not raw or _IOC_LINE.match(raw):
        return "", ""
    if raw.startswith("http://") or raw.startswith("https://"):
        return "uri", raw
    host_part = raw.split("/")[0].split(":")[0]
    try:
        ipaddress.ip_address(host_part)
        if "/" in raw or (":" in raw and not raw.startswith("[")):
            uri = raw if "://" in raw else f"http://{raw}"
            return "uri", uri
        return "ip", host_part
    except ValueError:
        pass
    if re.match(r"^[\w.-]+\.[a-zA-Z]{2,}(/.*)?$", raw):
        return "uri", raw if "://" in raw else f"https://{raw}"
    return "uri", raw


def parse_c2_text(text: str) -> dict[str, list[str]]:
    ips: list[str] = []
    uris: list[str] = []
    for line in text.splitlines():
        kind, value = classify_ioc(line)
        if kind == "ip" and value not in ips:
            ips.append(value)
        elif kind == "uri" and value not in uris:
            uris.append(value)
    return {"ips": ips, "uris": uris}


def c2_host_from_uri(uri: str) -> str:
    if not uri:
        return ""
    if "://" not in uri:
        uri = f"https://{uri}"
    try:
        parsed = urlparse(uri)
        return parsed.netloc or uri
    except ValueError:
        return uri


def _default_c2() -> dict[str, Any]:
    return {
        "default_ip": DEFAULT_C2_IP,
        "default_uri": DEFAULT_C2_URI,
        "ips": [DEFAULT_C2_IP, "203.0.113.66"],
        "uris": [
            DEFAULT_C2_URI,
            "https://malware-c2.example.com/gate",
        ],
    }


def normalize_c2(raw: dict[str, Any] | None) -> dict[str, Any]:
    base = _default_c2()
    data = raw or {}
    ips = [str(x).strip() for x in data.get("ips", base["ips"]) if str(x).strip()]
    uris = [str(x).strip() for x in data.get("uris", base["uris"]) if str(x).strip()]
    default_ip = str(data.get("default_ip", base["default_ip"])).strip() or DEFAULT_C2_IP
    default_uri = str(data.get("default_uri", base["default_uri"])).strip() or DEFAULT_C2_URI
    if default_ip not in ips:
        ips.insert(0, default_ip)
    if default_uri not in uris:
        uris.insert(0, default_uri)
    return {
        "default_ip": default_ip,
        "default_uri": default_uri,
        "ips": ips,
        "uris": uris,
    }


def merge_c2_import(existing: dict[str, Any], imported: dict[str, list[str]]) -> dict[str, Any]:
    c2 = normalize_c2(existing)
    for ip in imported.get("ips", []):
        if ip not in c2["ips"]:
            c2["ips"].append(ip)
    for uri in imported.get("uris", []):
        if uri not in c2["uris"]:
            c2["uris"].append(uri)
    return c2
