# FortiSIEM Sim v2

Framework Python **mejorado** para simular logs hacia **FortiSIEM 7.5 Enterprise** en laboratorio/tabletop. Independiente de otros proyectos del repo. Solo generación segura de syslog vía **Scapy**.

## Mejoras respecto a v1

| Capacidad | v1 (`fortisiem-lab-framework`) | v2 (`fortisiem-sim`) |
|-----------|-------------------------------|----------------------|
| Perfil lab central | Hardcoded | `lab.yaml` |
| Actores | Pools simples | **Perfiles nombrados** (`attacker`, `victim`, …) |
| Validación | Runtime básico | `--validate` escenario + plantillas |
| Reproducibilidad | No | `--seed` |
| Timeline | No | `timeline_minutes` en escenario |
| Salida | Texto | **text** o **jsonl** + resumen |
| Catálogo | `--list-events` | + `--show-event ID` |
| Health check | No | `--probe` |
| Instalación | manual | `pip install .` → `fortisiem-sim` |
| Tests | No | `pytest` |

## Instalación (HTTPS)

```bash
git clone https://github.com/faceblood/fortisiem-sim.git
cd fortisiem-sim
chmod +x install.sh && ./install.sh
```

O manualmente:

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install --upgrade pip setuptools wheel
pip install -r requirements.txt && pip install -e .
```

**Importante:** tras instalar debes activar el venv (`source .venv/bin/activate`) o usar la ruta completa `.venv/bin/fortisiem-sim`. El comando `fortisiem-sim` no existe en el sistema hasta que actives el venv.

`requirements.txt`:

```
scapy>=2.5.0
PyYAML>=6.0
```

## Uso rápido (simple)

Hay dos formas. La **más simple** es el wrapper `./fsim` (no necesitas activar el venv ni escribir `sudo`/rutas):

```bash
./fsim --list-scenarios                 # qué escenarios hay
./fsim ransomware                       # dry-run completo (solo pantalla)
./fsim ransomware recon_and_access      # dry-run de una fase
./fsim ransomware --send                # envío real (pide sudo solo)
./fsim ransomware recon_and_access --send --no-spoof
```

Equivalente con el comando instalado (requiere `source .venv/bin/activate`):

```bash
# Nombre corto en lugar de ruta completa
fortisiem-sim --list-scenarios
fortisiem-sim ransomware                       # = scenarios/ransomware-tabletop.yml
fortisiem-sim ransomware --phase execution
fortisiem-sim --validate ransomware
fortisiem-sim --list-phases ransomware

# Envío real
sudo .venv/bin/fortisiem-sim ransomware --phase recon_and_access --send --no-spoof
```

Antes (verboso) vs ahora:

```bash
# ANTES
sudo .venv/bin/fortisiem-sim --config scenarios/ransomware-tabletop.yml --phase recon_and_access --send --no-spoof
# AHORA
./fsim ransomware recon_and_access --send --no-spoof
```

## Estructura

```
fortisiem-sim/
├── lab.yaml                 # FortiSIEM 10.255.9.3:514, org 1
├── templates/events.yaml    # 27 plantillas reutilizables
├── scenarios/tabletop.yml   # Escenario con perfiles de actor
├── schemas/                 # JSON Schema (referencia)
├── src/fortisiem_sim/       # Paquete
└── tests/
```

## Perfil de actor (nuevo)

```yaml
actors:
  default_profile: victim
  profiles:
    attacker:
      user: jgarcia
      src_ip: 198.51.100.77
      reporting_ip: 192.0.2.10
      hostname: ws-remote-01
  pools:
    users: [jgarcia, svc_finance]
```

Evento con actor:

```yaml
- id: login_failed
  actor: attacker
  count: 10
  delay: 0.4
  jitter: 0.2
```

## Scapy — `send_syslog_scapy()`

```python
from fortisiem_sim.syslog import send_syslog_scapy

send_syslog_scapy("10.255.9.3", 514, "<134>...", src_ip="192.0.2.10", use_spoof=True)
```

- **Privilegios:** root / `CAP_NET_RAW`
- **Spoofing:** solo lab; si falla → `--no-spoof` (reporting IP en payload)
- **Limitaciones:** NAT, firewall, rp_filter, ACLs FortiSIEM

## CLI completa

```
--config, --lab, --templates
--list-events, --list-formats, --show-event ID
--validate, --probe
--phase, --event, --count, --delay, --jitter, --seed
--dry-run (default), --send
--output-file, --output-format text|jsonl
--randomize-src|user|timestamps|reporting-ip
--target 10.255.9.3, --port 514, --org-id 1
--iface, --no-spoof, -q, -v
```

## Formatos soportados

| Formato | Eventos ejemplo |
|---------|-----------------|
| syslog_generic | login_success, backup_access |
| cef | file_access_sensitive |
| fortiedr_cef | credential_access_simulated |
| fortigate | vpn_login_foreign_country, outbound_connection |
| linux_auth | ssh_login, sudo_command |
| windows_security | suspicious_powershell_simulated, privilege_change |
| esxi_vcenter | hypervisor_login |
| docker | container_exec |
| nginx_apache | web_login, web_upload |
| ot_scada | telemetry_delay, alarm_suppressed |
| crisis_comms | incident_escalation, holding_statement |

## Nuevo escenario en 10 minutos

1. `cp scenarios/tabletop.yml scenarios/mi-ejercicio.yml`
2. Editar `actors.profiles` y `phases`
3. `fortisiem-sim --validate --config scenarios/mi-ejercicio.yml`
4. `fortisiem-sim --config scenarios/mi-ejercicio.yml --dry-run`
5. Event Search en FortiSIEM → reglas
6. `sudo fortisiem-sim ... --send`

## Troubleshooting (logs sí, incidentes no)

| Problema | Acción |
|----------|--------|
| Unknown_Event_Type | Ajustar plantilla o Generic Parser |
| Sin correlación | Alinear reporting IP / `--no-spoof` |
| Regla no dispara | `--validate`, subir count, revisar lookback |
| Spoof no funciona | `--no-spoof` + campo `reportingIp` en payload |

## Reglas FortiSIEM sugeridas

- Brute force: N× `login_failed` mismo `src_ip` / 5 min
- VPN geo: `country` ∉ allowlist
- PowerShell: EventID 4104 + Simulation=true
- OT: `[OT-SIM]` + DEGRADED / ALARM_SUPPRESSED
- Crisis: cadena `[CRISIS-SIM]` ESCALATION → HOLDING_STATEMENT

## Tests

```bash
pip install pytest
pytest tests/ -q
```

## Troubleshooting — «no ejecuta nada»

| Síntoma | Causa | Solución |
|---------|-------|----------|
| `command not found: fortisiem-sim` | Venv no activado | `source .venv/bin/activate` o `.venv/bin/fortisiem-sim` |
| No llegan logs a FortiSIEM | Modo **dry-run** (default) | Añade `--send` y usa **sudo** |
| `sudo: fortisiem-sim: command not found` | sudo no ve el venv | `sudo .venv/bin/fortisiem-sim ... --send` |
| Permission denied /dev/bpf | Scapy sin root | `sudo .venv/bin/fortisiem-sim ... --send` |
| `0 eventos procesados` | Fase mal escrita | `fortisiem-sim --list-phases --config scenarios/...` |
| Solo texto en pantalla | Comportamiento normal en dry-run | Es correcto; usa `--send` para enviar |

```bash
# Diagnóstico rápido
source .venv/bin/activate
fortisiem-sim --list-phases --config scenarios/ransomware-tabletop.yml
fortisiem-sim --config scenarios/ransomware-tabletop.yml --phase recon_and_access

# Envío real
sudo .venv/bin/fortisiem-sim --config scenarios/ransomware-tabletop.yml \
  --phase recon_and_access --send --no-spoof --target 10.255.9.3
```

## Seguridad

Uso **exclusivo** en lab autorizado. Marcador `simulated=true` inyectado automáticamente. Sin actividad ofensiva real.
