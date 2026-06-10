from __future__ import annotations

import json
import random
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any, Iterator

from .assets import apply_config_c2_to_scenario
from .loaders import load_lab_profile, merge_lab_into_options
from .models import EmittedEmail, EmittedEvent, EventTemplate, RunSummary, Scenario, ScenarioEvent, ScenarioPhase, SendOptions
from .mail import render_email, send_html_email
from .render import build_context, render_wire
from .syslog import resolve_local_ip, send_syslog_scapy


# --------------------------------------------------------------------------- #
# Catálogo
# --------------------------------------------------------------------------- #

def list_events_table(templates: dict[str, EventTemplate]) -> None:
    print(f"{'ID':<32} {'FORMAT':<18} {'CATEGORY':<14} {'SEVERITY':<10} NAME")
    print("-" * 100)
    for event_id, tmpl in sorted(templates.items()):
        print(f"{event_id:<32} {tmpl.format:<18} {tmpl.category:<14} {tmpl.severity:<10} {tmpl.name}")


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
    if tmpl.fortisiem_hints:
        print("FortiSIEM hints:")
        for k, v in tmpl.fortisiem_hints.items():
            print(f"  {k}: {v}")
    print("--- body (plantilla) ---")
    print(tmpl.body)
    return 0


# --------------------------------------------------------------------------- #
# Salida / resumen
# --------------------------------------------------------------------------- #

def _format_line(emitted: EmittedEvent, target: str, port: int, as_json: bool) -> str:
    if as_json:
        payload = asdict(emitted)
        payload["target"] = target
        payload["port"] = port
        return json.dumps(payload, ensure_ascii=False)
    mode = "SPOOF" if emitted.spoof else "NO-SPOOF"
    status = "SENT" if emitted.sent else "DRY"
    return (
        f"[{status}|{mode}] target={target}:{port} event={emitted.event_id} "
        f"phase={emitted.phase or '-'} actor={emitted.actor or '-'} "
        f"packet_src={emitted.packet_src} reporting_ip={emitted.reporting_ip}\n{emitted.wire}"
    )


def _record(summary: RunSummary, e: EmittedEvent) -> None:
    summary.total += 1
    summary.sent += int(e.sent)
    summary.dry_run += int(not e.sent)
    summary.by_format[e.format] = summary.by_format.get(e.format, 0) + 1
    summary.by_phase[e.phase or "(inline)"] = summary.by_phase.get(e.phase or "(inline)", 0) + 1
    summary.by_event[e.event_id] = summary.by_event.get(e.event_id, 0) + 1


def print_summary(summary: RunSummary, *, dry_run: bool) -> None:
    print(f"\n=== Resumen [{'DRY-RUN' if dry_run else 'LIVE (Scapy)'}] ===")
    print(f"  Total eventos : {summary.total}")
    print(f"  Enviados      : {summary.sent}")
    print(f"  Simulados     : {summary.dry_run}")
    if summary.by_phase:
        print("  Por fase:")
        for phase, count in sorted(summary.by_phase.items()):
            print(f"    - {phase}: {count}")
    if summary.by_format:
        print("  Por formato:")
        for fmt, count in sorted(summary.by_format.items()):
            print(f"    - {fmt}: {count}")


# --------------------------------------------------------------------------- #
# Emisión
# --------------------------------------------------------------------------- #

def _sleep(delay: float, jitter: float) -> None:
    total = max(0.0, delay) + (random.uniform(0, jitter) if jitter > 0 else 0.0)
    if total > 0:
        time.sleep(total)


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
        scenario, template, options,
        actor_name=actor_name, overrides=overrides,
        sequence_index=sequence_index, timeline_total=timeline_total,
    )
    wire = render_wire(template, ctx)
    packet_src = ctx["reporting_ip"] if options.spoof_src else resolve_local_ip()
    sent = not options.dry_run

    if sent:
        send_syslog_scapy(
            options.target, options.port, wire,
            src_ip=packet_src if options.spoof_src else None,
            iface=options.iface, use_spoof=options.spoof_src,
        )

    emitted = EmittedEvent(
        event_id=template.id, phase=phase_name, format=template.format, wire=wire,
        packet_src=packet_src, reporting_ip=ctx["reporting_ip"],
        spoof=options.spoof_src, sent=sent, actor=actor_name,
    )
    _record(summary, emitted)

    as_json = options.output_format == "jsonl"
    line = _format_line(emitted, options.target, options.port, as_json)
    if not options.quiet:
        print(line)
    if out_fp:
        out_fp.write(line + ("\n" if as_json else "\n\n"))
    return emitted


def _count_timeline_events(scenario: Scenario, phase_filter: str) -> int:
    total = 0
    for phase in scenario.phases:
        if phase_filter and phase.name != phase_filter:
            continue
        if getattr(phase, "phase_type", "mitre") == "email":
            total += len(phase.emails)
        else:
            total += sum(e.count for e in phase.events)
            total += len(phase.emails)
    return total


def _iter_mitre_phase_steps(phase: ScenarioPhase):
    """Eventos y correos de una fase MITRE en orden de sort_order."""
    steps: list[tuple[int, str, Any]] = []
    for ev in phase.events:
        steps.append((int(getattr(ev, "sort_order", 0)), "event", ev))
    for em in phase.emails:
        steps.append((int(getattr(em, "sort_order", 0)), "email", em))
    steps.sort(key=lambda item: item[0])
    for _, kind, payload in steps:
        yield kind, payload


def emit_email_one(
    scenario: Scenario,
    template: dict[str, Any],
    smtp_cfg: dict[str, Any],
    options: SendOptions,
    *,
    phase_name: str,
    actor_name: str,
    to_address: str,
    cc: str = "",
    overrides: dict[str, str] | None = None,
    out_fp=None,
    summary: RunSummary | None = None,
) -> EmittedEmail:
    from .models import EventTemplate as ET
    from .render import build_context

    actor = actor_name or scenario.actors.default_profile
    to_rendered = to_address
    if "{{" in to_rendered:
        dummy = ET(id="_email", name="", format="email", severity="info", body="")
        ctx = build_context(scenario, dummy, options, actor_name=actor, overrides=overrides)
        for key, val in ctx.items():
            to_rendered = to_rendered.replace(f"{{{{{key}}}}}", val)
    subject, html = render_email(template, scenario, actor, overrides, options)
    result = send_html_email(
        smtp_cfg,
        to_address=to_rendered,
        cc=cc,
        subject=subject,
        html_body=html,
        dry_run=options.dry_run,
    )
    emitted = EmittedEmail(
        template_id=str(template.get("id", "")),
        phase=phase_name,
        to_address=result["to"],
        subject=subject,
        html_preview=html[:500],
        sent=bool(result.get("sent")),
        dry_run=options.dry_run,
        actor=actor,
        error=result.get("error", ""),
    )
    if summary:
        summary.total += 1
        if emitted.sent:
            summary.sent += 1
        else:
            summary.dry_run += 1
        summary.by_phase[phase_name or "(inline)"] = summary.by_phase.get(phase_name or "(inline)", 0) + 1
    if out_fp:
        out_fp.write(f"[EMAIL] to={emitted.to_address} subject={emitted.subject}\n")
    if not options.quiet:
        mode = "DRY" if options.dry_run else ("SENT" if emitted.sent else "FAIL")
        print(f"[{mode}|EMAIL] phase={phase_name} to={emitted.to_address} subject={subject}")
    return emitted


def iter_scenario_stream(
    scenario: Scenario,
    templates: dict[str, EventTemplate],
    options: SendOptions,
    summary: RunSummary,
    *,
    phase_filter: str = "",
    event_filter: str = "",
    no_delay: bool = False,
    out_fp=None,
    email_templates: dict[str, Any] | None = None,
    smtp_cfg: dict[str, Any] | None = None,
) -> Iterator[tuple[str, Any]]:
    """Generador: ('phase', dict), ('event', EmittedEvent), ('email', EmittedEmail)."""
    apply_config_c2_to_scenario(scenario)
    lab = load_lab_profile(Path(options.lab_path) if options.lab_path else None)
    merge_lab_into_options(options, lab)
    if options.seed is not None:
        random.seed(options.seed)

    seq = 0
    timeline_total = _count_timeline_events(scenario, phase_filter) if scenario.timeline_minutes else 0

    if event_filter:
        tmpl = templates.get(event_filter)
        if not tmpl:
            raise KeyError(f"Evento desconocido: {event_filter}")
        count = max(1, options.count or 1)
        for i in range(count):
            yield (
                "event",
                emit_one(
                    scenario, tmpl, options,
                    phase_name="", actor_name=scenario.actors.default_profile, overrides=None,
                    sequence_index=seq, timeline_total=max(count, timeline_total),
                    out_fp=out_fp, summary=summary,
                ),
            )
            seq += 1
            if not no_delay and i < count - 1:
                _sleep(options.delay or lab.default_delay, options.jitter or lab.default_jitter)
        return

    for phase in scenario.phases:
        if phase_filter and phase.name != phase_filter:
            continue
        yield ("phase", {"name": phase.name, "description": phase.description, "phase_type": getattr(phase, "phase_type", "mitre")})
        if not no_delay and phase.delay_before > 0:
            time.sleep(phase.delay_before)
        if getattr(phase, "phase_type", "mitre") == "email":
            for em in phase.emails:
                tmpl_dict = (email_templates or {}).get(em.template_id)
                if not tmpl_dict:
                    raise KeyError(f"Plantilla de correo no encontrada: {em.template_id}")
                yield (
                    "email",
                    emit_email_one(
                        scenario,
                        {"id": em.template_id, **tmpl_dict},
                        smtp_cfg or {},
                        options,
                        phase_name=phase.name,
                        actor_name=em.actor or scenario.actors.default_profile,
                        to_address=em.to_address,
                        cc=em.cc,
                        overrides=em.overrides,
                        out_fp=out_fp,
                        summary=summary,
                    ),
                )
            continue
        for kind, step in _iter_mitre_phase_steps(phase):
            if kind == "email":
                tmpl_dict = (email_templates or {}).get(step.template_id)
                if not tmpl_dict:
                    raise KeyError(f"Plantilla de correo no encontrada: {step.template_id}")
                yield (
                    "email",
                    emit_email_one(
                        scenario,
                        {"id": step.template_id, **tmpl_dict},
                        smtp_cfg or {},
                        options,
                        phase_name=phase.name,
                        actor_name=step.actor or scenario.actors.default_profile,
                        to_address=step.to_address,
                        cc=step.cc,
                        overrides=step.overrides,
                        out_fp=out_fp,
                        summary=summary,
                    ),
                )
                continue
            event = step
            tmpl = templates.get(event.id)
            if not tmpl:
                raise KeyError(f"Plantilla no encontrada: {event.id}")
            count = max(1, options.count if options.count is not None else event.count)
            delay = options.delay or (event.delay if event.delay is not None else lab.default_delay)
            jitter = options.jitter or (event.jitter if event.jitter is not None else lab.default_jitter)
            actor = event.actor or scenario.actors.default_profile
            for i in range(count):
                yield (
                    "event",
                    emit_one(
                        scenario, tmpl, options,
                        phase_name=phase.name, actor_name=actor, overrides=event.overrides,
                        sequence_index=seq, timeline_total=max(timeline_total, 1),
                        out_fp=out_fp, summary=summary,
                    ),
                )
                seq += 1
                if not no_delay and i < count - 1:
                    _sleep(delay, jitter)


def run_scenario(
    scenario: Scenario,
    templates: dict[str, EventTemplate],
    options: SendOptions,
    *,
    phase_filter: str = "",
    event_filter: str = "",
    no_delay: bool = False,
    collect: list[EmittedEvent] | None = None,
    email_templates: dict[str, Any] | None = None,
    smtp_cfg: dict[str, Any] | None = None,
) -> RunSummary:
    """Ejecuta el escenario. Con no_delay=True omite esperas. Con collect acumula eventos."""
    summary = RunSummary()
    out_fp = open(options.output_file, "a", encoding="utf-8") if options.output_file else None
    try:
        for kind, payload in iter_scenario_stream(
            scenario, templates, options, summary,
            phase_filter=phase_filter, event_filter=event_filter,
            no_delay=no_delay, out_fp=out_fp,
            email_templates=email_templates, smtp_cfg=smtp_cfg,
        ):
            if kind == "event" and collect is not None:
                collect.append(payload)
        return summary
    finally:
        if out_fp:
            out_fp.close()


def probe(options: SendOptions, templates: dict[str, EventTemplate]) -> RunSummary:
    """Envía un único evento (health-check)."""
    from .models import ScenarioActors

    mini = Scenario(name="probe", org_id=options.org_id, actors=ScenarioActors())
    event_id = "login_success" if "login_success" in templates else next(iter(templates))
    options.count = 1
    summary = RunSummary()
    emit_one(
        mini, templates[event_id], options,
        phase_name="probe", actor_name="default", overrides={"user": "probe.lab"},
        sequence_index=0, timeline_total=1, out_fp=None, summary=summary,
    )
    return summary
