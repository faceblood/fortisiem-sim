from __future__ import annotations

import json
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
from .mitre import build_event_catalog, index_events_by_tactic, list_tactics
from .models import EmittedEvent, RunSummary, Scenario, SendOptions
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


def _expected_events(scenario: Scenario, phase_filter: str, count_override: int | None) -> int:
    total = 0
    for phase in scenario.phases:
        if phase_filter and phase.name != phase_filter:
            continue
        for event in phase.events:
            n = count_override if count_override is not None else event.count
            total += max(1, n)
    return total


def _summary_dict(summary: RunSummary) -> dict:
    return {"total": summary.total, "sent": summary.sent, "dry_run": summary.dry_run}


def _scenario_payload(scenario_id: str) -> dict:
    sc = load_scenario_data(scenario_id)
    return {
        "name": sc.name,
        "description": sc.description,
        "org_id": sc.org_id,
        "phases": [
            {
                "name": ph.name,
                "description": ph.description,
                "total": sum(e.count for e in ph.events),
                "events": [{"id": e.id, "count": e.count, "actor": e.actor} for e in ph.events],
            }
            for ph in sc.phases
        ],
    }


def _scenario_list_payload() -> list[dict]:
    items: list[dict] = []
    for scenario_id in list_scenario_refs():
        sc = load_scenario_data(scenario_id)
        total_events = sum(sum(e.count for e in ph.events) for ph in sc.phases)
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
        raise RuntimeError("Flask no instalado. Ejecuta: pip install flask") from exc

    enable_sql_storage(seed_from_yaml=True)
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

    @app.get("/api/events")
    def api_events():
        templates = _current_templates()
        catalog = build_event_catalog(templates)
        return jsonify({
            "ids": sorted(templates.keys()),
            "count": len(templates),
            "catalog": catalog,
            "by_tactic": index_events_by_tactic(catalog),
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
                for kind, payload in iter_scenario_stream(
                    scenario, templates, options, summary,
                    phase_filter=phase, no_delay=False,
                ):
                    if kind == "phase":
                        yield _sse({"type": "phase", **payload})
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
            summary = run_scenario(
                scenario, templates, options,
                phase_filter=phase, no_delay=True, collect=collected,
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
