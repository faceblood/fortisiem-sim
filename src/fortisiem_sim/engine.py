from __future__ import annotations

import random
import time
from pathlib import Path

from .config import default_templates_path, load_lab_profile, merge_lab_into_options
from .loaders import load_templates
from .models import (
    EmittedEvent,
    EventTemplate,
    RunSummary,
    Scenario,
    ScenarioEvent,
    SendOptions,
)
from .render import build_context, render_wire
from .reporting import format_jsonl, format_text_line, print_summary, record
from .syslog import resolve_local_ip, send_syslog_scapy


def resolve_templates_path(options: SendOptions) -> Path:
    if options.templates_path:
        return Path(options.templates_path)
    return default_templates_path()


def apply_seed(seed: int | None) -> None:
    if seed is not None:
        random.seed(seed)


def list_events_table(templates: dict[str, EventTemplate]) -> None:
    print(f"{'ID':<32} {'FORMAT':<18} {'CATEGORY':<14} {'SEVERITY':<10} NAME")
    print("-" * 100)
    for event_id, tmpl in sorted(templates.items()):
        print(
            f"{event_id:<32} {tmpl.format:<18} {tmpl.category:<14} "
            f"{tmpl.severity:<10} {tmpl.name}"
        )


def show_event_detail(templates: dict[str, EventTemplate], event_id: str) -> int:
    tmpl = templates.get(event_id)
    if not tmpl:
        print(f"Evento no encontrado: {event_id}")
        return 1
    print(f"ID       : {tmpl.id}")
    print(f"Nombre   : {tmpl.name}")
    print(f"Formato  : {tmpl.format}")
    print(f"Categoría: {tmpl.category}")
    print(f"Severidad: {tmpl.severity}")
    print(f"Campos   : {', '.join(tmpl.fields) or '-'}")
    print(f"MITRE    : {', '.join(tmpl.mitre) or '-'}")
    print(f"Tags     : {', '.join(tmpl.tags) or '-'}")
    if tmpl.fortisiem_hints:
        print("FortiSIEM hints:")
        for k, v in tmpl.fortisiem_hints.items():
            print(f"  {k}: {v}")
    print("--- body (plantilla) ---")
    print(tmpl.body)
    return 0


def _effective_count(event: ScenarioEvent, options: SendOptions) -> int:
    if options.count is not None:
        return max(1, options.count)
    return max(1, event.count)


def _effective_delay(event: ScenarioEvent, options: SendOptions, lab_default: float) -> float:
    if options.delay > 0:
        return options.delay
    if event.delay is not None:
        return event.delay
    return lab_default


def _effective_jitter(event: ScenarioEvent, options: SendOptions, lab_default: float) -> float:
    if options.jitter > 0:
        return options.jitter
    if event.jitter is not None:
        return event.jitter
    return lab_default


def _sleep(delay: float, jitter: float) -> None:
    if delay <= 0 and jitter <= 0:
        return
    total = delay + (random.uniform(0, jitter) if jitter > 0 else 0.0)
    if total > 0:
        time.sleep(total)


def _count_timeline_events(scenario: Scenario, phase_filter: str) -> int:
    total = 0
    for phase in scenario.phases:
        if phase_filter and phase.name != phase_filter:
            continue
        for event in phase.events:
            total += event.count
    return total


def emit_one(
    scenario: Scenario,
    template: EventTemplate,
    options: SendOptions,
    *,
    phase_name: str,
    actor_name: str,
    overrides: dict[str, str] | None,
    sequence_index: int,
    timeline_total: int,
    out_fp,
    summary: RunSummary,
) -> EmittedEvent:
    ctx = build_context(
        scenario,
        template,
        options,
        actor_name=actor_name,
        overrides=overrides,
        sequence_index=sequence_index,
        timeline_total=timeline_total,
    )
    wire = render_wire(template, ctx)
    packet_src = ctx.reporting_ip if options.spoof_src else resolve_local_ip()
    sent = not options.dry_run

    if sent:
        send_syslog_scapy(
            options.target,
            options.port,
            wire,
            src_ip=packet_src if options.spoof_src else None,
            iface=options.iface,
            use_spoof=options.spoof_src,
        )

    emitted = EmittedEvent(
        event_id=template.id,
        phase=phase_name,
        format=template.format,
        wire=wire,
        packet_src=packet_src,
        reporting_ip=ctx.reporting_ip,
        spoof=options.spoof_src,
        sent=sent,
        actor=actor_name,
    )
    record(summary, emitted)

    if not options.quiet:
        if options.output_format == "jsonl":
            line = format_jsonl(emitted, options.target, options.port)
            print(line)
        else:
            print(format_text_line(emitted, options.target, options.port))

    if out_fp:
        if options.output_format == "jsonl":
            out_fp.write(format_jsonl(emitted, options.target, options.port) + "\n")
        else:
            out_fp.write(format_text_line(emitted, options.target, options.port) + "\n\n")

    return emitted


def run_scenario(
    scenario: Scenario,
    templates: dict[str, EventTemplate],
    options: SendOptions,
    *,
    phase_filter: str = "",
    event_filter: str = "",
) -> RunSummary:
    lab = load_lab_profile(Path(options.lab_path) if options.lab_path else None)
    merge_lab_into_options(options, lab)
    apply_seed(options.seed)

    summary = RunSummary()
    out_fp = open(options.output_file, "a", encoding="utf-8") if options.output_file else None
    seq = 0
    timeline_total = _count_timeline_events(scenario, phase_filter) if scenario.timeline_minutes else 0

    try:
        if event_filter:
            tmpl = templates.get(event_filter)
            if not tmpl:
                raise KeyError(f"Evento desconocido: {event_filter}")
            count = max(1, options.count or 1)
            for i in range(count):
                emit_one(
                    scenario,
                    tmpl,
                    options,
                    phase_name="",
                    actor_name=scenario.actors.default_profile,
                    overrides=None,
                    sequence_index=seq,
                    timeline_total=max(count, timeline_total),
                    out_fp=out_fp,
                    summary=summary,
                )
                seq += 1
                if i < count - 1:
                    _sleep(options.delay or lab.default_delay, options.jitter or lab.default_jitter)
            return summary

        for phase in scenario.phases:
            if phase_filter and phase.name != phase_filter:
                continue
            if phase.delay_before > 0:
                time.sleep(phase.delay_before)
            for event in phase.events:
                tmpl = templates.get(event.id)
                if not tmpl:
                    raise KeyError(f"Plantilla no encontrada: {event.id}")
                count = _effective_count(event, options)
                delay = _effective_delay(event, options, lab.default_delay)
                jitter = _effective_jitter(event, options, lab.default_jitter)
                actor = event.actor or scenario.actors.default_profile
                for i in range(count):
                    emit_one(
                        scenario,
                        tmpl,
                        options,
                        phase_name=phase.name,
                        actor_name=actor,
                        overrides=event.overrides,
                        sequence_index=seq,
                        timeline_total=max(timeline_total, 1),
                        out_fp=out_fp,
                        summary=summary,
                    )
                    seq += 1
                    if i < count - 1:
                        _sleep(delay, jitter)
        return summary
    finally:
        if out_fp:
            out_fp.close()


def probe(options: SendOptions, templates: dict[str, EventTemplate]) -> RunSummary:
    """Envía un único evento login_success como health-check."""
    from .models import Scenario, ScenarioActors

    mini = Scenario(name="probe", org_id=options.org_id, actors=ScenarioActors())
    event_id = "login_success" if "login_success" in templates else next(iter(templates))
    tmpl = templates[event_id]
    options.count = 1
    summary = RunSummary()
    emit_one(
        mini,
        tmpl,
        options,
        phase_name="probe",
        actor_name="default",
        overrides={"user": "probe.lab"},
        sequence_index=0,
        timeline_total=1,
        out_fp=None,
        summary=summary,
    )
    return summary
