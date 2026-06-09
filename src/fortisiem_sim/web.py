from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from .engine import iter_scenario_stream, run_scenario
from .loaders import (
    list_scenarios,
    load_scenario,
    load_templates,
    resolve_scenario,
    resolve_templates_path,
)
from .models import EmittedEvent, RunSummary, SendOptions

INDEX_HTML = r"""<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>FortiSIEM Sim — Consola de fases</title>
<style>
  :root { --bg:#0e1117; --panel:#161b22; --border:#30363d; --fg:#e6edf3; --muted:#8b949e;
          --accent:#2f81f7; --green:#3fb950; --amber:#d29922; --red:#f85149; --purple:#a371f7; }
  * { box-sizing:border-box; }
  body { margin:0; font:14px/1.5 -apple-system,Segoe UI,Roboto,sans-serif; background:var(--bg); color:var(--fg); }
  header { padding:16px 24px; border-bottom:1px solid var(--border); display:flex; align-items:center; gap:12px; }
  header h1 { font-size:16px; margin:0; font-weight:600; }
  .tag { font-size:11px; padding:2px 8px; border-radius:999px; background:#1f6feb22; color:var(--accent); border:1px solid #1f6feb44; }
  .layout { display:grid; grid-template-columns:320px 1fr; height:calc(100vh - 57px); }
  .sidebar { border-right:1px solid var(--border); overflow:auto; padding:16px; }
  .main { overflow:auto; padding:16px 24px; }
  label { display:block; font-size:12px; color:var(--muted); margin:10px 0 4px; }
  select, input { width:100%; padding:8px; background:var(--panel); border:1px solid var(--border);
                  border-radius:6px; color:var(--fg); }
  .row { display:flex; gap:10px; }
  .row > * { flex:1; }
  .check { display:flex; align-items:center; gap:8px; margin:12px 0; }
  .check input { width:auto; }
  button { cursor:pointer; border:none; border-radius:6px; padding:9px 14px; font-weight:600; }
  .btn-run { background:var(--accent); color:#fff; width:100%; margin-top:12px; }
  .btn-run:hover { filter:brightness(1.1); }
  .btn-run:disabled { opacity:.5; cursor:not-allowed; }
  .btn-stop { background:var(--red); color:#fff; width:100%; margin-top:8px; display:none; }
  .btn-ghost { background:var(--panel); color:var(--fg); border:1px solid var(--border); }
  .phase-card { background:var(--panel); border:1px solid var(--border); border-radius:8px; padding:12px; margin-bottom:10px; }
  .phase-card h3 { margin:0 0 4px; font-size:14px; }
  .phase-card p { margin:0 0 8px; color:var(--muted); font-size:12px; }
  .ev { font-size:12px; color:var(--muted); display:flex; justify-content:space-between; padding:2px 0; }
  .ev b { color:var(--fg); font-weight:500; }
  .out { background:#010409; border:1px solid var(--border); border-radius:8px; padding:12px;
         font-family:ui-monospace,SFMono-Regular,Menlo,monospace; font-size:12px; white-space:pre-wrap;
         word-break:break-all; max-height:55vh; overflow:auto; }
  .line-sent { color:var(--green); }
  .line-dry  { color:var(--amber); }
  .line-phase { color:var(--purple); font-weight:600; margin:10px 0 4px; }
  .wire { color:var(--fg); margin-bottom:8px; }
  .banner { padding:10px 12px; border-radius:6px; margin-bottom:12px; font-size:13px; }
  .banner.dry { background:#d2992222; border:1px solid #d2992255; color:var(--amber); }
  .banner.live { background:#f8514922; border:1px solid #f8514955; color:var(--red); }
  .banner.stream { background:#a371f722; border:1px solid #a371f755; color:var(--purple); }
  .meta { color:var(--muted); font-size:12px; margin:8px 0; }
  .pill { display:inline-block; font-size:11px; padding:1px 7px; border-radius:999px; border:1px solid var(--border); margin-left:6px; }
  .progress { height:4px; background:var(--border); border-radius:2px; margin:8px 0 12px; overflow:hidden; }
  .progress-bar { height:100%; background:var(--accent); width:0%; transition:width .3s; }
</style>
</head>
<body>
<header>
  <h1>FortiSIEM Sim</h1>
  <span class="tag">lab tabletop · org 1 · 10.255.9.3:514</span>
</header>
<div class="layout">
  <aside class="sidebar">
    <label>Escenario</label>
    <select id="scenario"></select>

    <label>Fase</label>
    <select id="phase"><option value="">(todas las fases)</option></select>

    <div class="row">
      <div><label>count (override)</label><input id="count" type="number" min="1" placeholder="auto"></div>
      <div><label>seed</label><input id="seed" type="number" placeholder="—"></div>
    </div>

    <div class="check"><input type="checkbox" id="sse" checked><label for="sse" style="margin:0;color:var(--fg)">Streaming en vivo (SSE + delays reales)</label></div>
    <div class="check"><input type="checkbox" id="send"><label for="send" style="margin:0;color:var(--fg)">Enviar de verdad (--send, requiere sudo)</label></div>
    <div class="check"><input type="checkbox" id="nospoof"><label for="nospoof" style="margin:0;color:var(--fg)">Sin spoofing (--no-spoof)</label></div>

    <button class="btn-run" id="btnRun" onclick="run()">Instanciar fase ▶</button>
    <button class="btn-stop" id="btnStop" onclick="stopRun()">Detener ■</button>
    <button class="btn-ghost" style="width:100%;margin-top:8px" onclick="loadScenario()">Recargar info</button>
  </aside>

  <main class="main">
    <div id="banner"></div>
    <div class="progress" id="progressWrap" style="display:none"><div class="progress-bar" id="progressBar"></div></div>
    <div id="info"></div>
    <h3 style="margin:16px 0 8px">Salida <span id="counter" class="pill">0 eventos</span></h3>
    <div id="out" class="out">Selecciona un escenario y pulsa «Instanciar fase».</div>
  </main>
</div>

<script>
let es = null;
let eventCount = 0;
let expectedTotal = 0;

async function j(url, opts) { const r = await fetch(url, opts); return r.json(); }

function escapeHtml(s){return s.replace(/[&<>]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]));}

function renderEvent(e, out) {
  const cls = e.sent ? 'line-sent' : 'line-dry';
  const head = `[${e.sent?'SENT':'DRY'}] ${e.event_id} · ${e.phase||'-'} · ${e.actor||'-'} · src=${e.packet_src}`;
  out.insertAdjacentHTML('beforeend',
    `<div class="${cls}">${head}</div><div class="wire">${escapeHtml(e.wire)}</div>`);
  out.scrollTop = out.scrollHeight;
}

function setRunning(on) {
  document.getElementById('btnRun').disabled = on;
  document.getElementById('btnStop').style.display = on ? 'block' : 'none';
}

function updateCounter() {
  document.getElementById('counter').textContent = `${eventCount} eventos` +
    (expectedTotal ? ` / ~${expectedTotal}` : '');
  if (expectedTotal) {
    document.getElementById('progressBar').style.width =
      Math.min(100, Math.round(eventCount / expectedTotal * 100)) + '%';
  }
}

async function init() {
  const data = await j('/api/scenarios');
  const sel = document.getElementById('scenario');
  sel.innerHTML = data.scenarios.map(s => `<option value="${s}">${s}</option>`).join('');
  sel.onchange = loadScenario;
  if (data.scenarios.length) loadScenario();
}

async function loadScenario() {
  const name = document.getElementById('scenario').value;
  if (!name) return;
  const sc = await j('/api/scenarios/' + encodeURIComponent(name));
  const ph = document.getElementById('phase');
  ph.innerHTML = '<option value="">(todas las fases)</option>' +
    sc.phases.map(p => `<option value="${p.name}">${p.name} (~${p.total} ev.)</option>`).join('');
  document.getElementById('info').innerHTML =
    `<div class="meta">${sc.description || ''}</div>` +
    sc.phases.map(p => `
      <div class="phase-card">
        <h3>${p.name} <span class="pill">${p.total} eventos</span></h3>
        <p>${p.description || ''}</p>
        ${p.events.map(e => `<div class="ev"><b>${e.id}</b><span>×${e.count} · ${e.actor || 'default'}</span></div>`).join('')}
      </div>`).join('');
}

function params() {
  const p = new URLSearchParams();
  p.set('scenario', document.getElementById('scenario').value);
  const phase = document.getElementById('phase').value;
  if (phase) p.set('phase', phase);
  const count = document.getElementById('count').value;
  const seed = document.getElementById('seed').value;
  if (count) p.set('count', count);
  if (seed) p.set('seed', seed);
  if (document.getElementById('send').checked) p.set('send', '1');
  if (document.getElementById('nospoof').checked) p.set('no_spoof', '1');
  return p;
}

function stopRun() {
  if (es) { es.close(); es = null; }
  setRunning(false);
  document.getElementById('banner').className = 'banner dry';
  document.getElementById('banner').textContent = 'Detenido por el usuario.';
}

function runSse() {
  const out = document.getElementById('out');
  const banner = document.getElementById('banner');
  out.innerHTML = '';
  eventCount = 0;
  expectedTotal = 0;
  updateCounter();
  document.getElementById('progressWrap').style.display = 'block';
  setRunning(true);
  banner.className = 'banner stream';
  banner.textContent = 'Conectando stream SSE…';

  es = new EventSource('/api/run/stream?' + params().toString());
  es.onmessage = (ev) => {
    const msg = JSON.parse(ev.data);
    if (msg.type === 'start') {
      expectedTotal = msg.expected || 0;
      updateCounter();
      banner.className = 'banner ' + (msg.live ? 'live' : 'dry');
      banner.textContent = msg.live
        ? `LIVE SSE → ${msg.target}:${msg.port} (delays reales)`
        : `DRY-RUN SSE (delays reales, sin envío)`;
    } else if (msg.type === 'phase') {
      out.insertAdjacentHTML('beforeend',
        `<div class="line-phase">▶ Fase: ${msg.name}${msg.description ? ' — ' + msg.description : ''}</div>`);
      out.scrollTop = out.scrollHeight;
    } else if (msg.type === 'event') {
      renderEvent(msg, out);
      eventCount++;
      updateCounter();
    } else if (msg.type === 'done') {
      banner.className = 'banner ' + (msg.live ? 'live' : 'dry');
      banner.textContent = msg.live
        ? `Completado: ${msg.summary.sent} enviados a ${msg.target}:${msg.port}`
        : `Completado: ${msg.summary.total} eventos generados (dry-run)`;
      es.close(); es = null; setRunning(false);
    } else if (msg.type === 'error') {
      banner.className = 'banner live';
      banner.textContent = 'ERROR: ' + msg.message;
      out.insertAdjacentHTML('beforeend', `<div class="line-dry">ERROR: ${escapeHtml(msg.message)}</div>`);
      es.close(); es = null; setRunning(false);
    }
  };
  es.onerror = () => {
    if (es) { es.close(); es = null; }
    setRunning(false);
    if (!banner.textContent.startsWith('Completado') && !banner.textContent.startsWith('ERROR')) {
      banner.className = 'banner live';
      banner.textContent = 'Conexión SSE interrumpida.';
    }
  };
}

async function runBatch() {
  const out = document.getElementById('out');
  out.textContent = 'Ejecutando (batch)…';
  document.getElementById('progressWrap').style.display = 'none';
  setRunning(true);
  const body = Object.fromEntries(params());
  body.send = document.getElementById('send').checked;
  body.no_spoof = document.getElementById('nospoof').checked;
  const res = await j('/api/run', {
    method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(body)
  });
  setRunning(false);
  const banner = document.getElementById('banner');
  if (res.error) { out.textContent = 'ERROR: ' + res.error; banner.innerHTML=''; return; }
  banner.className = 'banner ' + (res.live ? 'live' : 'dry');
  banner.textContent = res.live
    ? `LIVE: ${res.summary.sent} eventos ENVIADOS a ${res.target}:${res.port}`
    : `DRY-RUN: ${res.summary.total} eventos generados (instantáneo)`;
  out.innerHTML = '';
  eventCount = res.events.length;
  document.getElementById('counter').textContent = `${eventCount} eventos`;
  res.events.forEach(e => renderEvent(e, out));
}

function run() {
  if (document.getElementById('sse').checked) runSse();
  else runBatch();
}

init();
</script>
</body>
</html>
"""


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


def create_app(templates_path: Path | None = None):
    try:
        from flask import Flask, Response, jsonify, request
    except ImportError as exc:
        raise RuntimeError("Flask no instalado. Ejecuta: pip install flask") from exc

    app = Flask(__name__)
    tpath = templates_path or resolve_templates_path(SendOptions())
    templates = load_templates(tpath)

    def _sse(payload: dict) -> str:
        return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"

    @app.get("/")
    def index():
        return INDEX_HTML

    @app.get("/api/scenarios")
    def api_scenarios():
        return jsonify({"scenarios": [p.stem for p in list_scenarios()]})

    @app.get("/api/scenarios/<name>")
    def api_scenario(name: str):
        try:
            return jsonify(_scenario_payload(resolve_scenario(name)))
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 404

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
