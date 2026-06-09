from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class LabProfile:
    target: str = "10.255.9.3"
    port: int = 514
    org_id: int = 1
    version: str = "7.5"
    edition: str = "enterprise"
    marker: str = "simulated=true"
    default_delay: float = 0.5
    default_jitter: float = 0.2


@dataclass
class EventTemplate:
    id: str
    name: str
    format: str
    severity: str
    body: str
    category: str = "generic"
    source_system: str = ""
    mitre_tactics: list[str] = field(default_factory=list)
    mitre_techniques: list[str] = field(default_factory=list)
    syslog_hostname: str = "lab-host"
    pri: int = 134
    fields: list[str] = field(default_factory=list)
    mitre: list[str] = field(default_factory=list)
    fortisiem_hints: dict[str, str] = field(default_factory=dict)
    defaults: dict[str, str] = field(default_factory=dict)
    tags: list[str] = field(default_factory=list)


@dataclass
class ActorProfile:
    name: str
    user: str = "lab.user"
    domain: str = "lab.local"
    src_ip: str = "10.10.10.50"
    reporting_ip: str = "10.255.9.21"
    hostname: str = "ws-lab-01"
    extra: dict[str, str] = field(default_factory=dict)


@dataclass
class ActorPools:
    users: list[str] = field(default_factory=lambda: ["lab.user"])
    hostnames: list[str] = field(default_factory=lambda: ["ws-lab-01"])
    src_ips: list[str] = field(default_factory=lambda: ["10.10.10.50"])
    reporting_ips: list[str] = field(default_factory=lambda: ["10.255.9.21"])
    domains: list[str] = field(default_factory=lambda: ["lab.local"])
    c2_ips: list[str] = field(default_factory=list)
    c2_uris: list[str] = field(default_factory=list)
    c2_default_ip: str = "203.0.113.50"
    c2_default_uri: str = "https://lab-c2.example/beacon"


@dataclass
class ScenarioActors:
    profiles: dict[str, ActorProfile] = field(default_factory=dict)
    pools: ActorPools = field(default_factory=ActorPools)
    default_profile: str = "default"


@dataclass
class ScenarioEvent:
    id: str
    count: int = 1
    delay: float | None = None
    jitter: float | None = None
    actor: str = ""
    overrides: dict[str, str] = field(default_factory=dict)


@dataclass
class ScenarioPhase:
    name: str
    description: str = ""
    delay_before: float = 0.0
    events: list[ScenarioEvent] = field(default_factory=list)


@dataclass
class Scenario:
    name: str
    description: str = ""
    org_id: int = 1
    actors: ScenarioActors = field(default_factory=ScenarioActors)
    phases: list[ScenarioPhase] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    timeline_minutes: int = 0


# El contexto de render es un dict[str, str] plano (ver render.build_context).

@dataclass
class SendOptions:
    target: str = "10.255.9.3"
    port: int = 514
    org_id: int = 1
    dry_run: bool = True
    count: int | None = None
    delay: float = 0.0
    jitter: float = 0.0
    output_file: str = ""
    output_format: str = "text"
    randomize_src: bool = False
    randomize_user: bool = False
    randomize_timestamps: bool = False
    randomize_reporting_ip: bool = False
    spoof_src: bool = True
    iface: str = ""
    templates_path: str = ""
    lab_path: str = ""
    seed: int | None = None
    quiet: bool = False
    verbose: bool = False
    simulation_marker: str = "simulated=true"


@dataclass
class EmittedEvent:
    event_id: str
    phase: str
    format: str
    wire: str
    packet_src: str
    reporting_ip: str
    spoof: bool
    sent: bool
    actor: str = ""


@dataclass
class RunSummary:
    total: int = 0
    sent: int = 0
    dry_run: int = 0
    by_format: dict[str, int] = field(default_factory=dict)
    by_phase: dict[str, int] = field(default_factory=dict)
    by_event: dict[str, int] = field(default_factory=dict)
