"""Cadena de actividad: clase de dominio que encapsula logs ordenados con delays."""
from __future__ import annotations

import random
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Callable, Iterator

if TYPE_CHECKING:
    from .models import EmittedEvent, EventTemplate, RunSummary, Scenario, SendOptions


@dataclass
class ChainLog:
    """Un log dentro de una cadena (plantilla + comando opcional + delay)."""

    sort_order: int
    event_id: str
    command_line: str = ""
    command_ref: str = ""
    step_kind: str = "event"
    min_delay_ms: int = 0
    max_delay_ms: int = 0
    optional: bool = False
    legitimacy: str = ""

    def effective_legitimacy(self, chain_default: str = "legitimate") -> str:
        val = (self.legitimacy or chain_default or "legitimate").strip().lower()
        if val in {"legit", "legitimate"}:
            return "legitimate"
        if val in {"non-legit", "illegitimate", "non_legit"}:
            return "illegitimate"
        return val

    def delay_ms(self) -> int:
        lo = max(0, self.min_delay_ms)
        hi = max(lo, self.max_delay_ms)
        if hi == lo:
            return lo
        return random.randint(lo, hi)

    def render_overrides(self, legitimacy: str) -> dict[str, str]:
        if not self.command_line:
            return {}
        return {
            "command_line": self.command_line,
            "command_legitimacy": legitimacy,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "sort_order": self.sort_order,
            "step_kind": self.step_kind,
            "event_id": self.event_id,
            "command_ref": self.command_ref,
            "command_line": self.command_line,
            "min_delay_ms": self.min_delay_ms,
            "max_delay_ms": self.max_delay_ms,
            "optional": self.optional,
            "legitimacy": self.legitimacy,
        }

    @classmethod
    def from_row(cls, row: dict[str, Any] | Any) -> ChainLog:
        get = row.__getitem__ if hasattr(row, "__getitem__") else row.get
        return cls(
            sort_order=int(get("sort_order") or 0),
            step_kind=str(get("step_kind") or "event"),
            event_id=str(get("event_id") or ""),
            command_ref=str(get("command_ref") or ""),
            command_line=str(get("command_line") or ""),
            min_delay_ms=int(get("min_delay_ms") or 0),
            max_delay_ms=int(get("max_delay_ms") or 0),
            optional=bool(get("optional")),
            legitimacy=str(get("legitimacy") or ""),
        )


def derive_chain_legitimacy(logs: list[ChainLog], fallback: str = "legitimate") -> str:
    if not logs:
        return fallback if fallback != "mixed" else "legitimate"
    kinds = {lg.effective_legitimacy(fallback) for lg in logs}
    kinds.discard("")
    if len(kinds) > 1:
        return "mixed"
    if kinds == {"illegitimate"}:
        return "illegitimate"
    if kinds == {"legitimate"}:
        return "legitimate"
    return fallback or "legitimate"


@dataclass
class ActivityChain:
    """Cadena de actividad Linux: portadora de logs ordenados."""

    id: str
    name: str
    legitimacy: str
    logs: list[ChainLog] = field(default_factory=list)
    category: str = ""
    severity: str = "info"
    description: str = ""
    objective: str = ""
    source_system: str = "linux"
    mitre: list[str] = field(default_factory=list)

    @property
    def steps(self) -> list[ChainLog]:
        """Alias retrocompatible."""
        return self.logs

    def __len__(self) -> int:
        return len(self.logs)

    def add_log(self, log: ChainLog) -> None:
        self.logs.append(log)

    def sorted_logs(self) -> list[ChainLog]:
        return sorted(self.logs, key=lambda lg: lg.sort_order)

    def effective_legitimacy(self) -> str:
        if self.legitimacy == "mixed":
            return "mixed"
        return derive_chain_legitimacy(self.logs, self.legitimacy)

    def to_payload(self) -> dict[str, Any]:
        eff = self.effective_legitimacy()
        return {
            "id": self.id,
            "name": self.name,
            "legitimacy": self.legitimacy,
            "effective_legitimacy": eff,
            "category": self.category,
            "severity": self.severity,
            "description": self.description,
            "objective": self.objective,
            "source_system": self.source_system,
            "mitre": self.mitre,
            "step_count": len(self.logs),
            "steps": [lg.to_dict() for lg in self.sorted_logs()],
            "logs": [lg.to_dict() for lg in self.sorted_logs()],
        }

    def emit(
        self,
        scenario: Scenario,
        templates: dict[str, EventTemplate],
        options: SendOptions,
        *,
        phase_name: str,
        actor_name: str,
        base_overrides: dict[str, str] | None = None,
        sequence_start: int = 0,
        timeline_total: int = 1,
        no_delay: bool = False,
        out_fp=None,
        summary: RunSummary | None = None,
        emit_one: Callable[..., EmittedEvent] | None = None,
        sleep_ms: Callable[[int], None] | None = None,
    ) -> Iterator[tuple[str, EmittedEvent]]:
        """Expande la cadena emitiendo cada log interno con delays."""
        if emit_one is None:
            from .engine import emit_one as _emit_one

            emit_one = _emit_one
        if sleep_ms is None:
            sleep_ms = lambda ms: time.sleep(ms / 1000.0) if ms > 0 else None

        seq = sequence_start
        for log in self.sorted_logs():
            if not no_delay and log.sort_order > 1:
                sleep_ms(log.delay_ms())

            tmpl = templates.get(log.event_id)
            if not tmpl:
                raise KeyError(f"Plantilla no encontrada para cadena {self.id}: {log.event_id}")

            overrides = dict(base_overrides or {})
            leg = log.effective_legitimacy(self.legitimacy)
            overrides.update(log.render_overrides(leg))

            yield (
                "event",
                emit_one(
                    scenario,
                    tmpl,
                    options,
                    phase_name=phase_name,
                    actor_name=actor_name,
                    overrides=overrides,
                    sequence_index=seq,
                    timeline_total=max(timeline_total, 1),
                    out_fp=out_fp,
                    summary=summary,
                ),
            )
            seq += 1
