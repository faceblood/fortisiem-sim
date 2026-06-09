#!/usr/bin/env python3
"""FortiSIEM Sim v2 — CLI."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .config import default_lab_path, load_lab_profile, merge_lab_into_options
from .engine import (
    list_events_table,
    probe,
    resolve_templates_path,
    run_scenario,
    show_event_detail,
)
from .formats import SUPPORTED_FORMATS
from .loaders import load_scenario, load_templates
from .models import Scenario, ScenarioActors, SendOptions
from .reporting import print_summary
from .validators import validate_all


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="fortisiem-sim",
        description="FortiSIEM Sim v2 — simulación segura de logs (Scapy, escenarios YAML/JSON)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Ejemplos:\n"
            "  fortisiem-sim --validate --config scenarios/tabletop.yml\n"
            "  fortisiem-sim --config scenarios/tabletop.yml --phase initial_access\n"
            "  sudo fortisiem-sim --config scenarios/tabletop.yml --send --no-spoof\n"
            "  fortisiem-sim --event login_failed --count 5 --seed 42 --output-format jsonl\n"
        ),
    )
    p.add_argument("--config", type=Path, help="Escenario YAML/JSON")
    p.add_argument("--lab", type=Path, help=f"Perfil lab (default: {default_lab_path()})")
    p.add_argument("--templates", type=Path, help="Biblioteca events.yaml")
    p.add_argument("--list-events", action="store_true", help="Tabla de eventos")
    p.add_argument("--list-formats", action="store_true", help="Formatos soportados")
    p.add_argument("--show-event", metavar="ID", help="Detalle de un evento")
    p.add_argument("--validate", action="store_true", help="Validar escenario + plantillas")
    p.add_argument("--list-phases", action="store_true", help="Listar fases del escenario (--config)")
    p.add_argument("--probe", action="store_true", help="Enviar 1 evento de prueba")
    p.add_argument("--phase", default="", help="Solo esta fase")
    p.add_argument("--event", default="", help="Solo este evento")
    p.add_argument("--count", type=int, default=None)
    p.add_argument("--delay", type=float, default=0.0)
    p.add_argument("--jitter", type=float, default=0.0)
    p.add_argument("--seed", type=int, default=None, help="Semilla RNG (reproducible)")
    p.add_argument("--dry-run", dest="dry_run", action="store_true", default=True)
    p.add_argument("--send", dest="dry_run", action="store_false")
    p.add_argument("--output-file", default="")
    p.add_argument("--output-format", choices=["text", "jsonl"], default="text")
    p.add_argument("--randomize-src", action="store_true")
    p.add_argument("--randomize-user", action="store_true")
    p.add_argument("--randomize-timestamps", action="store_true")
    p.add_argument("--randomize-reporting-ip", action="store_true")
    p.add_argument("--target", default="10.255.9.3")
    p.add_argument("--port", type=int, default=514)
    p.add_argument("--org-id", type=int, default=1)
    p.add_argument("--iface", default="")
    p.add_argument("--no-spoof", action="store_true")
    p.add_argument("-q", "--quiet", action="store_true")
    p.add_argument("-v", "--verbose", action="store_true")
    return p


def _minimal_scenario(org_id: int) -> Scenario:
    return Scenario(name="inline", org_id=org_id, actors=ScenarioActors())


def _build_options(args: argparse.Namespace) -> SendOptions:
    opts = SendOptions(
        target=args.target,
        port=args.port,
        org_id=args.org_id,
        dry_run=args.dry_run,
        count=args.count,
        delay=args.delay,
        jitter=args.jitter,
        output_file=args.output_file,
        output_format=args.output_format,
        randomize_src=args.randomize_src,
        randomize_user=args.randomize_user,
        randomize_timestamps=args.randomize_timestamps,
        randomize_reporting_ip=args.randomize_reporting_ip,
        spoof_src=not args.no_spoof,
        iface=args.iface,
        templates_path=str(args.templates) if args.templates else "",
        lab_path=str(args.lab) if args.lab else "",
        seed=args.seed,
        quiet=args.quiet,
        verbose=args.verbose,
    )
    lab = load_lab_profile(args.lab or default_lab_path())
    merge_lab_into_options(opts, lab)
    return opts


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    options = _build_options(args)
    templates_path = resolve_templates_path(options)

    if not templates_path.exists():
        print(f"ERROR: plantillas no encontradas: {templates_path}", file=sys.stderr)
        return 1
    templates = load_templates(templates_path)

    if args.list_formats:
        for fmt, desc in sorted(SUPPORTED_FORMATS.items()):
            print(f"{fmt:<20} {desc}")
        return 0

    if args.list_events:
        list_events_table(templates)
        return 0

    if args.show_event:
        return show_event_detail(templates, args.show_event)

    if args.list_phases:
        if not args.config:
            print("ERROR: --list-phases requiere --config", file=sys.stderr)
            return 1
        scenario = load_scenario(args.config)
        print(f"Fases en {args.config}:")
        for phase in scenario.phases:
            n = sum(e.count for e in phase.events)
            print(f"  {phase.name:<28} {len(phase.events)} tipos, ~{n} eventos  # {phase.description}")
        return 0

    if args.validate:
        if not args.config:
            print("ERROR: --validate requiere --config", file=sys.stderr)
            return 1
        errors = validate_all(args.config, templates_path)
        if errors:
            print("VALIDACIÓN FALLIDA:")
            for err in errors:
                print(f"  - {err}")
            return 1
        print(f"OK: {args.config} + {templates_path}")
        return 0

    if args.probe:
        if not args.dry_run:
            print("Probe hacia", options.target, file=sys.stderr)
        summary = probe(options, templates)
        print_summary(summary, dry_run=options.dry_run)
        return 0

    if args.config:
        scenario = load_scenario(args.config)
        if scenario.org_id == 1 and options.org_id != 1:
            scenario.org_id = options.org_id
    elif args.event:
        scenario = _minimal_scenario(options.org_id)
    else:
        build_parser().print_help()
        print("\nERROR: indica --config <escenario.yml> o --event <id>", file=sys.stderr)
        return 1

    if args.dry_run and not args.quiet:
        print(
            "MODO: dry-run (solo genera logs en pantalla; NO envía a FortiSIEM).\n"
            "      Para envío real: añade --send y ejecuta con sudo.\n",
            file=sys.stderr,
        )

    if not args.dry_run and options.spoof_src:
        print(
            "AVISO LAB: spoofing IP origen activo. Si FortiSIEM no ve el reporting IP, usa --no-spoof.\n",
            file=sys.stderr,
        )

    try:
        summary = run_scenario(
            scenario,
            templates,
            options,
            phase_filter=args.phase,
            event_filter=args.event,
        )
    except (KeyError, ValueError, RuntimeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    if summary.total == 0:
        print("AVISO: 0 eventos procesados.", file=sys.stderr)
        if args.phase:
            print(f"  ¿Fase correcta? Prueba: fortisiem-sim --list-phases --config {args.config}", file=sys.stderr)
        if args.event:
            print("  ¿Event ID correcto? Prueba: fortisiem-sim --list-events", file=sys.stderr)
        return 1

    if not args.quiet:
        print_summary(summary, dry_run=options.dry_run)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
