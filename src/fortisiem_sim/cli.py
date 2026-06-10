#!/usr/bin/env python3
"""FortiSIEM Sim v2 — CLI."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .engine import (
    list_events_table,
    print_summary,
    probe,
    run_scenario,
    show_event_detail,
)
from .loaders import (
    default_lab_path,
    load_lab_profile,
    load_templates_merged,
    merge_lab_into_options,
    resolve_templates_path,
    validate_all,
)
from .models import Scenario, ScenarioActors, SendOptions
from .render import SUPPORTED_FORMATS


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
    p.add_argument(
        "scenario",
        nargs="?",
        default="",
        help="Escenario: nombre corto (ej. 'ransomware') o ruta a YAML/JSON",
    )
    p.add_argument("--config", type=Path, help="(alias de scenario) ruta a YAML/JSON")
    p.add_argument("--lab", type=Path, help=f"Perfil lab (default: {default_lab_path()})")
    p.add_argument("--templates", type=Path, help="Biblioteca events.yaml")
    p.add_argument("--web", action="store_true", help="Lanzar frontend web (Flask)")
    p.add_argument("--web-host", default="127.0.0.1", help="Host del frontend (default 127.0.0.1)")
    p.add_argument("--web-port", type=int, default=8800, help="Puerto del frontend (default 8800)")
    p.add_argument("--list-scenarios", action="store_true", help="Listar escenarios disponibles")
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

    db = p.add_subparsers(dest="command")
    db_p = db.add_parser("db", help="Base SQLite local (config/fortisiem.db)")
    db_p.add_argument(
        "action",
        choices=["init", "seed", "status"],
        help="init=crear schema; seed=importar YAML; status=resumen",
    )
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


def _resolve_config(args: argparse.Namespace) -> str | None:
    raw = args.scenario or (str(args.config) if args.config else "")
    if not raw:
        return None
    from .loaders import resolve_scenario
    from .storage import resolve_scenario_ref, use_sql_storage

    if use_sql_storage():
        return resolve_scenario_ref(raw)
    return resolve_scenario(raw).stem


def _run_db_command(action: str) -> int:
    from .db.connection import db_path, get_connection, init_schema
    from .storage import enable_sql_storage

    path = db_path()
    if action == "init":
        conn = get_connection(path)
        init_schema(conn)
        conn.close()
        print(f"SQLite inicializada: {path}")
        return 0
    if action == "seed":
        enable_sql_storage(seed_from_yaml=True)
        print(f"Seed completado en {path}")
        return 0
    if action == "status":
        if not path.exists():
            print(f"SQLite no existe: {path}\n  Ejecuta: fortisiem-sim db init && fortisiem-sim db seed")
            return 1
        conn = get_connection(path)
        try:
            events = conn.execute("SELECT COUNT(*) AS n FROM event_templates").fetchone()["n"]
            scenarios = conn.execute("SELECT COUNT(*) AS n FROM scenarios").fetchone()["n"]
        finally:
            conn.close()
        print(f"SQLite: {path}")
        print(f"  Eventos:    {events}")
        print(f"  Escenarios: {scenarios}")
        return 0
    return 1


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if args.command == "db":
        return _run_db_command(args.action)

    options = _build_options(args)
    templates_path = resolve_templates_path(options)

    if not templates_path.exists():
        print(f"ERROR: plantillas no encontradas: {templates_path}", file=sys.stderr)
        return 1
    templates = load_templates_merged(templates_path)

    if args.web:
        from .web import serve

        serve(host=args.web_host, port=args.web_port, templates_path=templates_path)
        return 0

    if args.list_scenarios:
        from .storage import list_scenario_refs

        ids = list_scenario_refs()
        if not ids:
            print("No hay escenarios (YAML o SQLite)")
            return 0
        print("Escenarios disponibles (usa el nombre corto):")
        for sid in ids:
            print(f"  {sid}")
        return 0

    if args.list_formats:
        for fmt, desc in sorted(SUPPORTED_FORMATS.items()):
            print(f"{fmt:<20} {desc}")
        return 0

    if args.list_events:
        list_events_table(templates)
        return 0

    if args.show_event:
        return show_event_detail(templates, args.show_event)

    try:
        config_id = _resolve_config(args)
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    if args.list_phases:
        if not config_id:
            print("ERROR: --list-phases requiere un escenario", file=sys.stderr)
            return 1
        from .storage import load_scenario_data
        from .mitre import phase_run_display_label, phase_technique_label

        scenario = load_scenario_data(config_id)
        print(f"Fases en {config_id}:")
        for phase in scenario.phases:
            n = sum(e.count for e in phase.events) + len(phase.emails)
            label = phase_run_display_label(phase)
            print(f"  {label:<48} {len(phase.events)} tipos, ~{n} eventos  # {phase.description}")
        return 0

    if args.validate:
        if not config_id:
            print("ERROR: --validate requiere un escenario", file=sys.stderr)
            return 1
        from .storage import load_scenario_data, use_sql_storage

        if use_sql_storage():
            scenario = load_scenario_data(config_id)
            errors = []
            if not scenario.phases:
                errors.append("Escenario sin fases")
            for phase in scenario.phases:
                for event in phase.events:
                    if event.id not in templates:
                        errors.append(f"Fase {phase.name}: evento desconocido {event.id!r}")
        else:
            from .loaders import resolve_scenario

            errors = validate_all(resolve_scenario(config_id), templates_path)
        if errors:
            print("VALIDACIÓN FALLIDA:")
            for err in errors:
                print(f"  - {err}")
            return 1
        print(f"OK: {config_id} + {templates_path.name}")
        return 0

    if args.probe:
        if not args.dry_run:
            print("Probe hacia", options.target, file=sys.stderr)
        summary = probe(options, templates)
        print_summary(summary, dry_run=options.dry_run)
        return 0

    if config_id:
        from .storage import load_scenario_data

        scenario = load_scenario_data(config_id)
        if scenario.org_id == 1 and options.org_id != 1:
            scenario.org_id = options.org_id
    elif args.event:
        scenario = _minimal_scenario(options.org_id)
    else:
        build_parser().print_help()
        print(
            "\nERROR: indica un escenario (ej. 'fortisiem-sim ransomware') o --event <id>.\n"
            "       Lista: fortisiem-sim --list-scenarios",
            file=sys.stderr,
        )
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
            print(f"  ¿Fase correcta? Prueba: fortisiem-sim --list-phases {config_id}", file=sys.stderr)
        if args.event:
            print("  ¿Event ID correcto? Prueba: fortisiem-sim --list-events", file=sys.stderr)
        return 1

    if not args.quiet:
        print_summary(summary, dry_run=options.dry_run)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
