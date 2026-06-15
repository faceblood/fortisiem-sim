from __future__ import annotations

import json
import re
from dataclasses import asdict
from pathlib import Path
from typing import Any

import yaml

from .assets import assets_to_actors, load_assets, save_assets, save_scenario_from_builder
from .c2 import merge_c2_import, parse_c2_text
from .db.connection import db_path
from .loaders import package_root
from .engine import iter_scenario_stream, run_scenario
from .loaders import (
    default_templates_path,
    merge_custom_events_import,
    parse_events_import,
)
from .mitre import (
    build_event_catalog,
    index_events_by_tactic,
    list_tactics,
    phase_run_display_label,
    phase_tactic_id,
    phase_tactic_name,
    phase_technique_ids,
    phase_technique_label,
)
from .models import EmittedEmail, EmittedEvent, RunSummary, Scenario, SendOptions
from .db.scenario_steps_repo import list_step_scenario_ids, load_steps_builder_payload
from .mitre import FORTIGATE_PLACEHOLDERS
from .storage import (
    enable_sql_storage,
    list_scenario_refs,
    load_all_event_templates,
    load_scenario_data,
    scenario_builder_data,
    storage_label,
)

_STATIC = Path(__file__).resolve().parent / "static"


def _parse_run_args(data: dict) -> tuple[str, Scenario, SendOptions, str]:
    from .storage import resolve_scenario_ref

    try:
        scenario_id = resolve_scenario_ref(str(data.get("scenario", "")))
    except ValueError as exc:
        raise ValueError(str(exc)) from exc
    scenario = load_scenario_data(scenario_id)
    count = data.get("count")
    seed = data.get("seed")
    options = SendOptions(
        dry_run=not bool(data.get("send")),
        spoof_src=not bool(data.get("no_spoof")),
        count=int(count) if count else None,
        seed=int(seed) if seed else None,
        quiet=True,
    )
    phase = str(data.get("phase", ""))
    return scenario_id, scenario, options, phase


def _event_units(event, chain_counts: dict[str, int], count_override: int | None) -> int:
    chain_id = str(getattr(event, "chain_id", "") or "").strip()
    if chain_id:
        return max(1, chain_counts.get(chain_id, 1))
    n = count_override if count_override is not None else event.count
    return max(1, n)


def _expected_events(scenario: Scenario, phase_filter: str, count_override: int | None) -> int:
    from .db.activity_chains_repo import step_counts_by_id

    chain_counts = step_counts_by_id()
    total = 0
    for phase in scenario.phases:
        if phase_filter and phase.name != phase_filter:
            continue
        if getattr(phase, "phase_type", "mitre") == "email":
            total += len(phase.emails)
            continue
        if getattr(phase, "phase_type", "mitre") == "chain":
            for event in phase.events:
                total += _event_units(event, chain_counts, count_override)
            continue
        for event in phase.events:
            total += _event_units(event, chain_counts, count_override)
        total += len(phase.emails)
    return total


def _summary_dict(summary: RunSummary) -> dict:
    return {"total": summary.total, "sent": summary.sent, "dry_run": summary.dry_run}


def _phase_run_total(ph, chain_counts: dict[str, int] | None = None) -> int:
    ptype = getattr(ph, "phase_type", "mitre")
    if ptype == "email":
        return len(ph.emails)
    if chain_counts is None:
        from .db.activity_chains_repo import step_counts_by_id

        chain_counts = step_counts_by_id()
    if ptype == "chain":
        return sum(_event_units(e, chain_counts, None) for e in ph.events)
    return sum(_event_units(e, chain_counts, None) for e in ph.events) + len(ph.emails)


def _scenario_payload(scenario_id: str) -> dict:
    from .db.activity_chains_repo import step_counts_by_id

    sc = load_scenario_data(scenario_id)
    chain_counts = step_counts_by_id()
    return {
        "name": sc.name,
        "description": sc.description,
        "org_id": sc.org_id,
        "phases": [
            {
                "name": ph.name,
                "label": phase_technique_label(ph),
                "display_label": phase_run_display_label(ph),
                "description": ph.description,
                "phase_type": getattr(ph, "phase_type", "mitre"),
                "mitre_tactic": phase_tactic_id(ph) or ph.mitre_tactic,
                "tactic_name": phase_tactic_name(ph),
                "mitre_techniques": phase_technique_ids(ph),
                "total": _phase_run_total(ph, chain_counts),
                "events": [
                    {
                        "id": e.id,
                        "chain_id": getattr(e, "chain_id", "") or "",
                        "count": e.count,
                        "actor": e.actor,
                    }
                    for e in ph.events
                ],
            }
            for ph in sc.phases
        ],
    }


def _email_templates_dict() -> dict[str, dict[str, str]]:
    from .db.email_repo import load_all_email_templates

    return {
        k: {
            "id": v.id,
            "name": v.name,
            "subject": v.subject,
            "html_body": v.html_body,
            "description": v.description,
        }
        for k, v in load_all_email_templates().items()
    }


def _scenario_list_payload() -> list[dict]:
    items: list[dict] = []
    seen: set[str] = set()
    try:
        for scenario_id in list_step_scenario_ids():
            seen.add(scenario_id)
            payload = load_steps_builder_payload(scenario_id)
            total = sum(len(p.get("events", [])) for p in payload.get("phases", []))
            items.append({
                "id": scenario_id,
                "file": f"{scenario_id}.sql",
                "name": payload.get("name", scenario_id),
                "description": payload.get("description", ""),
                "phases": len(payload.get("phases", [])),
                "events": total,
                "timeline_minutes": 0,
                "source": "scenario_steps",
            })
    except Exception:
        pass
    for scenario_id in list_scenario_refs():
        if scenario_id in seen:
            continue
        sc = load_scenario_data(scenario_id)
        from .db.activity_chains_repo import step_counts_by_id

        chain_counts = step_counts_by_id()
        total_events = 0
        for ph in sc.phases:
            total_events += _phase_run_total(ph, chain_counts)
        items.append({
            "id": scenario_id,
            "file": f"{scenario_id}.yml",
            "name": sc.name,
            "description": sc.description,
            "phases": len(sc.phases),
            "events": total_events,
            "timeline_minutes": sc.timeline_minutes,
        })
    return items


def create_app(templates_path: Path | None = None):
    try:
        from flask import Flask, Response, jsonify, request, send_from_directory
    except ImportError as exc:
        raise RuntimeError(
            'Flask no instalado. Ejecuta desde fortisiem-sim: '
            'python3 -m pip install -e ".[web]"'
        ) from exc

    enable_sql_storage(seed_from_yaml=False)
    app = Flask(__name__, static_folder=str(_STATIC), static_url_path="/static")
    base_tpath = templates_path or default_templates_path()
    catalog_state: dict[str, Any] = {
        "base": base_tpath,
        "templates": load_all_event_templates(base_tpath),
    }

    def _current_templates():
        return catalog_state["templates"]

    def _reload_templates():
        catalog_state["templates"] = load_all_event_templates(catalog_state["base"])
        return catalog_state["templates"]

    def _sse(payload: dict) -> str:
        return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"

    @app.get("/")
    def index():
        return send_from_directory(_STATIC, "index.html")

    @app.get("/api/storage")
    def api_storage():
        root = package_root()
        db = db_path()
        try:
            rel = str(db.relative_to(root))
        except ValueError:
            rel = str(db)
        return jsonify({
            "backend": storage_label().lower(),
            "db_path": rel,
        })

    @app.get("/api/scenarios")
    def api_scenarios():
        items = _scenario_list_payload()
        return jsonify({
            "scenarios": [i["id"] for i in items],
            "items": items,
        })

    @app.get("/api/scenarios/<name>")
    def api_scenario(name: str):
        try:
            return jsonify(_scenario_payload(name))
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 404

    @app.get("/api/scenarios/<name>/builder")
    def api_scenario_builder(name: str):
        try:
            return jsonify(scenario_builder_data(name))
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 404

    @app.post("/api/scenarios/builder")
    def api_save_scenario_builder():
        data = request.get_json(force=True) or {}
        try:
            assets = load_assets() if data.get("use_config_actors", True) else None
            path = save_scenario_from_builder(data, assets)
            return jsonify({
                "ok": True,
                "name": path.stem,
                "path": str(db_path()) if storage_label() == "SQLite" else str(path.relative_to(path.parent.parent)),
                "storage": storage_label(),
            })
        except (ValueError, KeyError, TypeError) as exc:
            return jsonify({"error": str(exc)}), 400

    @app.get("/api/config")
    def api_get_config():
        assets = load_assets()
        actors = assets_to_actors(assets)
        return jsonify({**assets, "actor_keys": list(actors.get("profiles", {}).keys())})

    @app.put("/api/config")
    def api_put_config():
        data = request.get_json(force=True) or {}
        try:
            save_assets(data)
            assets = load_assets()
            actors = assets_to_actors(assets)
            return jsonify({**assets, "actor_keys": list(actors.get("profiles", {}).keys())})
        except (ValueError, TypeError) as exc:
            return jsonify({"error": str(exc)}), 400

    @app.post("/api/config/c2/import")
    def api_import_c2():
        if request.files.get("file"):
            text = request.files["file"].read().decode("utf-8", errors="replace")
        else:
            text = request.get_data(as_text=True) or ""
        if not text.strip():
            return jsonify({"error": "Fichero o cuerpo vacío"}), 400
        try:
            imported = parse_c2_text(text)
            assets = load_assets()
            assets["c2"] = merge_c2_import(assets.get("c2"), imported)
            save_assets(assets)
            assets = load_assets()
            actors = assets_to_actors(assets)
            return jsonify({
                **assets,
                "actor_keys": list(actors.get("profiles", {}).keys()),
                "imported": imported,
            })
        except (ValueError, TypeError) as exc:
            return jsonify({"error": str(exc)}), 400

    @app.post("/api/events/import")
    def api_import_events():
        if request.files.get("file"):
            text = request.files["file"].read().decode("utf-8", errors="replace")
        else:
            text = request.get_data(as_text=True) or ""
        if not text.strip():
            return jsonify({"error": "Fichero o cuerpo vacío"}), 400
        try:
            imported = parse_events_import(text)
            added, updated = merge_custom_events_import(imported)
            templates = _reload_templates()
            catalog = build_event_catalog(templates)
            return jsonify({
                "ok": True,
                "added": added,
                "updated": updated,
                "count": len(templates),
                "ids": sorted(templates.keys()),
                "catalog": catalog,
                "by_tactic": index_events_by_tactic(catalog),
            })
        except (ValueError, TypeError, yaml.YAMLError) as exc:
            return jsonify({"error": str(exc)}), 400

    @app.get("/api/emails")
    def api_emails_list():
        from .db.email_repo import list_email_catalog

        catalog = list_email_catalog()
        return jsonify({"catalog": catalog, "count": len(catalog), "ids": [c["id"] for c in catalog]})

    @app.get("/api/emails/<template_id>")
    def api_email_get(template_id: str):
        from .db.email_repo import load_all_email_templates

        templates = load_all_email_templates()
        tmpl = templates.get(template_id)
        if not tmpl:
            return jsonify({"error": "Plantilla no encontrada"}), 404
        return jsonify(asdict(tmpl))

    @app.post("/api/emails")
    def api_email_save():
        from .db.email_repo import upsert_email_template

        data = request.get_json(force=True) or {}
        eid = str(data.get("id", "")).strip()
        if not eid:
            return jsonify({"error": "id requerido"}), 400
        if not str(data.get("subject", "")).strip():
            return jsonify({"error": "subject requerido"}), 400
        if not str(data.get("html_body", "")).strip():
            return jsonify({"error": "html_body requerido"}), 400
        upsert_email_template(data, is_builtin=False)
        from .db.email_repo import list_email_catalog as lec
        return jsonify({"ok": True, "id": eid, "catalog": lec()})

    @app.delete("/api/emails/<template_id>")
    def api_email_delete(template_id: str):
        from .db.email_repo import delete_email_template, list_email_catalog

        try:
            if not delete_email_template(template_id):
                return jsonify({"error": "No encontrada"}), 404
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        return jsonify({"ok": True, "catalog": list_email_catalog()})

    @app.get("/api/events/<event_id>")
    def api_event_get(event_id: str):
        from .db.events_repo import load_event_detail

        detail = load_event_detail(event_id)
        if not detail:
            return jsonify({"error": "Evento no encontrado"}), 404
        return jsonify(detail)

    @app.put("/api/events/<event_id>")
    def api_event_update(event_id: str):
        from .db.events_repo import load_event_detail, save_event_from_api

        data = request.get_json(force=True) or {}
        if not str(data.get("body", "")).strip():
            return jsonify({"error": "body requerido"}), 400
        if not str(data.get("name", "")).strip():
            return jsonify({"error": "name requerido"}), 400
        try:
            save_event_from_api(event_id, data)
        except (ValueError, TypeError) as exc:
            return jsonify({"error": str(exc)}), 400
        templates = _reload_templates()
        detail = load_event_detail(event_id)
        catalog = build_event_catalog(templates)
        return jsonify({
            "ok": True,
            "event": detail,
            "count": len(templates),
            "catalog": catalog,
            "by_tactic": index_events_by_tactic(catalog),
        })

    @app.post("/api/events")
    def api_event_create():
        from .db.events_repo import load_event_detail, save_event_from_api

        data = request.get_json(force=True) or {}
        event_id = str(data.get("id", "")).strip()
        if not event_id:
            return jsonify({"error": "id requerido"}), 400
        if not re.match(r"^[a-zA-Z0-9_.-]+$", event_id):
            return jsonify({"error": "id inválido (usa letras, números, _, -, .)"}), 400
        templates = _current_templates()
        if event_id in templates:
            return jsonify({"error": f"El evento {event_id!r} ya existe"}), 409
        try:
            save_event_from_api(event_id, data)
        except (ValueError, TypeError) as exc:
            return jsonify({"error": str(exc)}), 400
        templates = _reload_templates()
        detail = load_event_detail(event_id)
        catalog = build_event_catalog(templates)
        return jsonify({
            "ok": True,
            "event": detail,
            "count": len(templates),
            "catalog": catalog,
            "by_tactic": index_events_by_tactic(catalog),
        })

    @app.delete("/api/events/<event_id>")
    def api_event_delete(event_id: str):
        from .db.events_repo import delete_event

        try:
            if not delete_event(event_id):
                return jsonify({"error": "Evento no encontrado"}), 404
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        templates = _reload_templates()
        catalog = build_event_catalog(templates)
        return jsonify({
            "ok": True,
            "count": len(templates),
            "catalog": catalog,
            "by_tactic": index_events_by_tactic(catalog),
        })

    @app.get("/api/commands")
    def api_commands_list():
        from .db.command_repo import LINUX_POOL, load_commands, command_pool_stats

        pool = request.args.get("pool", LINUX_POOL).strip() or LINUX_POOL
        legitimacy = request.args.get("legitimacy", "").strip()
        commands = load_commands(pool, legitimacy=legitimacy)
        stats = command_pool_stats()
        return jsonify({
            "pool": pool,
            "commands": commands,
            "count": len(commands),
            "stats": stats,
        })

    @app.post("/api/commands")
    def api_commands_add():
        from .db.command_repo import LINUX_POOL, upsert_command
        from .db.connection import get_connection

        data = request.get_json(force=True) or {}
        value = str(data.get("value") or data.get("command") or "").strip()
        if not value:
            return jsonify({"error": "value requerido"}), 400
        legitimacy = str(data.get("legitimacy", "illegitimate")).strip().lower()
        if legitimacy not in {"legitimate", "illegitimate"}:
            return jsonify({"error": "legitimacy debe ser legitimate o illegitimate"}), 400
        pool = str(data.get("pool_name", LINUX_POOL)).strip() or LINUX_POOL
        conn = get_connection()
        try:
            upsert_command(
                conn,
                pool_name=pool,
                value=value,
                legitimacy=legitimacy,
                category=str(data.get("category", "")).strip(),
                description=str(data.get("description", "")).strip(),
            )
            conn.commit()
        finally:
            conn.close()
        from .db.command_repo import load_commands, command_pool_stats

        return jsonify({
            "ok": True,
            "commands": load_commands(pool),
            "stats": command_pool_stats(),
        })

    @app.put("/api/commands/<int:command_id>")
    def api_commands_update(command_id: int):
        from .db.command_repo import load_commands, command_pool_stats, update_command_by_id

        data = request.get_json(force=True) or {}
        if not update_command_by_id(command_id, data):
            return jsonify({"error": "Comando no encontrado o value vacío"}), 404
        return jsonify({"ok": True, "commands": load_commands(), "stats": command_pool_stats()})

    @app.delete("/api/commands/<int:command_id>")
    def api_commands_delete(command_id: int):
        from .db.command_repo import delete_command, load_commands, command_pool_stats

        if not delete_command(command_id):
            return jsonify({"error": "Comando no encontrado"}), 404
        return jsonify({
            "ok": True,
            "commands": load_commands(),
            "stats": command_pool_stats(),
        })

    @app.get("/api/chains")
    def api_chains_list():
        from .db.activity_chains_repo import chain_stats, list_chains

        legitimacy = request.args.get("legitimacy", "").strip()
        source = request.args.get("source", "linux").strip() or "linux"
        chains = list_chains(legitimacy=legitimacy, source_system=source)
        return jsonify({
            "chains": chains,
            "count": len(chains),
            "stats": chain_stats(),
        })

    @app.get("/api/chains/<chain_id>")
    def api_chain_detail(chain_id: str):
        from .db.activity_chains_repo import chain_detail_payload

        detail = chain_detail_payload(chain_id)
        if not detail:
            return jsonify({"error": "Cadena no encontrada"}), 404
        return jsonify(detail)

    @app.post("/api/chains/import")
    def api_chains_import():
        from .db.import_activity_chains import import_activity_chains

        result = import_activity_chains()
        return jsonify({k: v for k, v in result.items() if k != "ids"})

    @app.put("/api/chains/<chain_id>")
    def api_chain_update(chain_id: str):
        from .db.activity_chains_repo import save_chain_from_api

        data = request.get_json(force=True) or {}
        if not (data.get("logs") or data.get("steps")):
            return jsonify({"error": "logs requeridos"}), 400
        try:
            chain = save_chain_from_api(chain_id, data)
        except (ValueError, TypeError) as exc:
            return jsonify({"error": str(exc)}), 400
        return jsonify({"ok": True, "chain": chain.to_payload()})

    @app.post("/api/chains")
    def api_chain_create():
        from .db.activity_chains_repo import load_chain, save_chain_from_api

        data = request.get_json(force=True) or {}
        chain_id = str(data.get("id", "")).strip()
        if not chain_id:
            return jsonify({"error": "id requerido"}), 400
        if load_chain(chain_id):
            return jsonify({"error": f"La cadena {chain_id!r} ya existe"}), 409
        try:
            chain = save_chain_from_api(chain_id, data)
        except (ValueError, TypeError) as exc:
            return jsonify({"error": str(exc)}), 400
        return jsonify({"ok": True, "chain": chain.to_payload()})

    @app.get("/api/events")
    def api_events():
        templates = _current_templates()
        catalog = build_event_catalog(templates)
        fmt = request.args.get("format", "").strip().lower()
        source = request.args.get("source", "").strip().lower()
        category = request.args.get("category", "").strip().lower()
        if fmt or source or category:
            catalog = [
                c for c in catalog
                if (not fmt or c.get("format", "").lower() == fmt)
                and (not source or c.get("system", "").lower() == source)
                and (not category or c.get("category", "").lower() == category)
            ]
        return jsonify({
            "ids": sorted(c["id"] for c in catalog),
            "count": len(catalog),
            "catalog": catalog,
            "by_tactic": index_events_by_tactic(catalog),
            "fortigate_placeholders": FORTIGATE_PLACEHOLDERS,
        })

    @app.get("/api/mitre/tactics")
    def api_mitre_tactics():
        return jsonify({"tactics": list_tactics()})

    @app.get("/api/run/stream")
    def api_run_stream():
        args = {
            "scenario": request.args.get("scenario", ""),
            "phase": request.args.get("phase", ""),
            "count": request.args.get("count"),
            "seed": request.args.get("seed"),
            "send": request.args.get("send") in ("1", "true", "yes"),
            "no_spoof": request.args.get("no_spoof") in ("1", "true", "yes"),
        }

        def generate():
            try:
                _, scenario, options, phase = _parse_run_args(args)
            except ValueError as exc:
                yield _sse({"type": "error", "message": str(exc)})
                return

            summary = RunSummary()
            expected = _expected_events(scenario, phase, options.count)
            yield _sse({
                "type": "start",
                "live": not options.dry_run,
                "target": options.target,
                "port": options.port,
                "scenario": scenario.name,
                "phase": phase or "(todas)",
                "expected": expected,
            })
            try:
                templates = _current_templates()
                assets = load_assets()
                for kind, payload in iter_scenario_stream(
                    scenario, templates, options, summary,
                    phase_filter=phase, no_delay=False,
                    email_templates=_email_templates_dict(),
                    smtp_cfg=assets.get("smtp", {}),
                ):
                    if kind == "phase":
                        yield _sse({"type": "phase", **payload})
                    elif kind == "email":
                        yield _sse({"type": "email", **asdict(payload)})
                    else:
                        yield _sse({"type": "event", **asdict(payload)})
                yield _sse({
                    "type": "done",
                    "live": not options.dry_run,
                    "target": options.target,
                    "port": options.port,
                    "summary": _summary_dict(summary),
                })
            except (KeyError, ValueError, RuntimeError) as exc:
                yield _sse({"type": "error", "message": str(exc)})

        return Response(
            generate(),
            mimetype="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "Connection": "keep-alive"},
        )

    @app.post("/api/run")
    def api_run():
        data = request.get_json(force=True) or {}
        try:
            _, scenario, options, phase = _parse_run_args(data)
        except ValueError as exc:
            return jsonify({"error": str(exc)})

        collected: list[EmittedEvent] = []
        try:
            templates = _current_templates()
            assets = load_assets()
            summary = run_scenario(
                scenario, templates, options,
                phase_filter=phase, no_delay=True, collect=collected,
                email_templates=_email_templates_dict(),
                smtp_cfg=assets.get("smtp", {}),
            )
        except (KeyError, ValueError, RuntimeError) as exc:
            return jsonify({"error": str(exc)})

        return jsonify({
            "live": not options.dry_run,
            "target": options.target,
            "port": options.port,
            "summary": _summary_dict(summary),
            "events": [asdict(e) for e in collected],
        })

    return app


def serve(host: str = "127.0.0.1", port: int = 8800, templates_path: Path | None = None) -> None:
    app = create_app(templates_path)
    print(f"FortiSIEM Sim web en http://{host}:{port}  (SQLite: {db_path()})")
    app.run(host=host, port=port, debug=False, threaded=True)
