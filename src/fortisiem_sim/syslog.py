from __future__ import annotations

import random
import socket
from typing import Optional


def send_syslog_scapy(
    target: str,
    port: int,
    message: str,
    src_ip: Optional[str] = None,
    *,
    iface: str = "",
    use_spoof: bool = True,
) -> None:
    """
    Envía un datagrama syslog UDP con Scapy (solo laboratorio controlado).

    Paquete: IP(src=..., dst=target) / UDP(sport=ephemeral, dport=port) / Raw(load=message)

    Privilegios: root o CAP_NET_RAW habitualmente requeridos.

    Limitaciones:
    - NAT, routing, firewall, switches L3, rp_filter y ACLs del collector FortiSIEM
      pueden bloquear o reescribir IPs origen falsificadas.
    - En redes corporativas use use_spoof=False: IP real del emisor en el paquete y
      reporting_ip embebido en el payload del evento.
    """
    try:
        from scapy.all import IP, Raw, UDP, send  # type: ignore
    except ImportError as exc:
        raise RuntimeError("Scapy no instalado: pip install scapy") from exc

    sport = random.randint(1024, 65535)
    payload = message.encode("utf-8")

    if use_spoof and src_ip:
        packet = IP(src=src_ip, dst=target) / UDP(sport=sport, dport=port) / Raw(load=payload)
    else:
        packet = IP(dst=target) / UDP(sport=sport, dport=port) / Raw(load=payload)

    kwargs: dict = {"verbose": False}
    if iface:
        kwargs["iface"] = iface
    try:
        send(packet, **kwargs)
    except Exception as exc:
        msg = str(exc).lower()
        if "permission" in msg or "bpf" in msg or "root" in msg:
            raise RuntimeError(
                "Scapy necesita privilegios elevados para enviar paquetes.\n"
                "  sudo $(which fortisiem-sim) ... --send\n"
                "  o: sudo .venv/bin/fortisiem-sim ... --send\n"
                "Sin --send el modo dry-run solo imprime logs (no envía a FortiSIEM)."
            ) from exc
        raise


def resolve_local_ip() -> str:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect(("8.8.8.8", 80))
            return str(sock.getsockname()[0])
    except OSError:
        return "127.0.0.1"
