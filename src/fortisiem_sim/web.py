from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

import yaml

from .assets import assets_to_actors, load_assets, save_assets, save_scenario_from_builder
from .engine import iter_scenario_stream, run_scenario
from .loaders import (
    list_scenarios,
    load_scenario,
    load_templates,
    resolve_scenario,
    resolve_templates_path,
)
from .mitre import (
    build_event_catalog,
    guess_tactic_from_phase,
    index_events_by_tactic,
    list_tactics,
)
from .models import EmittedEvent, RunSummary, Scenario, SendOptions

_STATIC = Path(__file__).resolve().parent / "static"


def _parse_run_args(data: dict) -> tuple[Path, Scenario, SendOptions, str]:
    try:
        scenario_path = resolve_scenario(str(data.get("scenario", "")))
    except ValueError as exc:
        raise ValueError(str(exc)) from exc
    scenario = load_scenario(scenario_path)
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
    return scenario_path, scenario, options, phase


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


def _scenario_payload(path: Path) -> dict:
    sc = load_scenario(path)
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
    for path in list_scenarios():
        sc = load_scenario(path)
        total_events = sum(sum(e.count for e in ph.events) for ph in sc.phases)
        items.append({
            "id": path.stem,
            "file": path.name,
            "name": sc.name,
            "description": sc.description,
            "phases": len(sc.phases),
            "events": total_events,
            "timeline_minutes": sc.timeline_minutes,
        })
    return items


def _scenario_builder_payload(path: Path) -> dict:
    sc = load_scenario(path)
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    phases_raw = raw.get("phases", {}) if isinstance(raw.get("phases"), dict) else {}
    actor_keys = list(sc.actors.profiles.keys()) if sc.actors.profiles else []
    phases_out = []
    for ph in sc.phases:
        raw_ph = phases_raw.get(ph.name, {}) if isinstance(phases_raw, dict) else {}
        mitre_raw = raw_ph.get("mitre", {}) if isinstance(raw_ph, dict) else {}
        mitre_tactic = str(mitre_raw.get("tactic", "")) if mitre_raw else ""
        if not mitre_tactic:
            mitre_tactic = guess_tactic_from_phase(ph.name, ph.description)
        mitre_techniques = mitre_raw.get("techniques", []) if mitre_raw else []
        phases_out.append({
            "name": ph.name,
            "description": ph.description,
            "delay_before": ph.delay_before,
            "mitre_tactic": mitre_tactic,
            "mitre_techniques": mitre_techniques,
            "events": [
                {
                    "id": e.id,
                    "count": e.count,
                    "actor": e.actor or "",
                    "delay": e.delay,
                    "jitter": e.jitter,
                }
                for e in ph.events
            ],
        })
    return {
        "id": path.stem,
        "name": sc.name,
        "description": sc.description,
        "org_id": sc.org_id,
        "timeline_minutes": sc.timeline_minutes,
        "use_config_actors": False,
        "actor_keys": actor_keys,
        "phases": phases_out,
    }


def create_app(templates_path: Path | None = None):
    try:
        from flask import Flask, Response, jsonify, request, send_from_directory
    except ImportError as exc:
        raise RuntimeError("Flask no instalado. Ejecuta: pip install flask") from exc

    app = Flask(__name__, static_folder=str(_STATIC), static_url_path="/static")
    tpath = templates_path or resolve_templates_path(SendOptions())
    templates = load_templates(tpath)

    def _sse(payload: dict) -> str:
        return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"

    @app.get("/")
    def index():
        return send_from_directory(_STATIC, "index.html")

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
            return jsonify(_scenario_payload(resolve_scenario(name)))
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 404

    @app.get("/api/scenarios/<name>/builder")
    def api_scenario_builder(name: str):
        try:
            return jsonify(_scenario_builder_payload(resolve_scenario(name)))
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 404

    @app.post("/api/scenarios/builder")
    def api_save_scenario_builder():
        data = request.get_json(force=True) or {}
        try:
            assets = load_assets() if data.get("use_config_actors", True) else None
            path = save_scenario_from_builder(data, assets)
            return jsonify({"ok": True, "name": path.stem, "path": str(path.relative_to(path.parent.parent))})
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
            saved = save_assets(data)
            assets = load_assets(saved)
            actors = assets_to_actors(assets)
            return jsonify({**assets, "actor_keys": list(actors.get("profiles", {}).keys())})
        except (ValueError, TypeError) as exc:
            return jsonify({"error": str(exc)}), 400

    @app.get("/api/events")
    def api_events():
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
        """SSE: eventos uno a uno con delays reales del escenario."""
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
        """Batch instantáneo (sin delays) — fallback si SSE desactivado."""
        data = request.get_json(force=True) or {}
        try:
            _, scenario, options, phase = _parse_run_args(data)
        except ValueError as exc:
            return jsonify({"error": str(exc)})

        collected: list[EmittedEvent] = []
        try:
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
    print(f"FortiSIEM Sim web en http://{host}:{port}  (Ctrl+C para salir)")
    app.run(host=host, port=port, debug=False, threaded=True)
