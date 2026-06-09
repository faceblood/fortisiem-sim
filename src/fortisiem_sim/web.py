from __future__ import annotations

from dataclasses import asdict
from pathlib import Path

from .engine import run_scenario
from .loaders import (
    list_scenarios,
    load_scenario,
    load_templates,
    resolve_scenario,
    resolve_templates_path,
)
from .models import EmittedEvent, SendOptions

INDEX_HTML = r"""<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>FortiSIEM Sim — Consola de fases</title>
<style>
  :root { --bg:#0e1117; --panel:#161b22; --border:#30363d; --fg:#e6edf3; --muted:#8b949e;
          --accent:#2f81f7; --green:#3fb950; --amber:#d29922; --red:#f85149; }
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
  .wire { color:var(--fg); }
  .banner { padding:10px 12px; border-radius:6px; margin-bottom:12px; font-size:13px; }
  .banner.dry { background:#d2992222; border:1px solid #d2992255; color:var(--amber); }
  .banner.live { background:#f8514922; border:1px solid #f8514955; color:var(--red); }
  .meta { color:var(--muted); font-size:12px; margin:8px 0; }
  .pill { display:inline-block; font-size:11px; padding:1px 7px; border-radius:999px; border:1px solid var(--border); margin-left:6px; }
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

    <div class="check"><input type="checkbox" id="send"><label for="send" style="margin:0;color:var(--fg)">Enviar de verdad (--send, requiere sudo)</label></div>
    <div class="check"><input type="checkbox" id="nospoof"><label for="nospoof" style="margin:0;color:var(--fg)">Sin spoofing (--no-spoof)</label></div>

    <button class="btn-run" onclick="run()">Instanciar fase ▶</button>
    <button class="btn-ghost" style="width:100%;margin-top:8px" onclick="loadScenario()">Recargar info</button>
  </aside>

  <main class="main">
    <div id="banner"></div>
    <div id="info"></div>
    <h3 style="margin:16px 0 8px">Salida</h3>
    <div id="out" class="out">Selecciona un escenario y pulsa «Instanciar fase».</div>
  </main>
</div>

<script>
async function j(url, opts) { const r = await fetch(url, opts); return r.json(); }

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

async function run() {
  const out = document.getElementById('out');
  out.textContent = 'Ejecutando…';
  const body = {
    scenario: document.getElementById('scenario').value,
    phase: document.getElementById('phase').value,
    count: document.getElementById('count').value || null,
    seed: document.getElementById('seed').value || null,
    send: document.getElementById('send').checked,
    no_spoof: document.getElementById('nospoof').checked,
  };
  const res = await j('/api/run', {
    method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(body)
  });
  const banner = document.getElementById('banner');
  if (res.error) { out.textContent = 'ERROR: ' + res.error; banner.innerHTML=''; return; }
  banner.className = 'banner ' + (res.live ? 'live' : 'dry');
  banner.innerHTML = res.live
    ? `LIVE: ${res.summary.sent} eventos ENVIADOS a ${res.target}:${res.port}`
    : `DRY-RUN: ${res.summary.total} eventos generados (no enviados)`;
  out.innerHTML = res.events.map(e => {
    const cls = e.sent ? 'line-sent' : 'line-dry';
    const head = `[${e.sent?'SENT':'DRY'}] ${e.event_id} · ${e.phase||'-'} · ${e.actor||'-'} · src=${e.packet_src}`;
    return `<div class="${cls}">${head}</div><div class="wire">${escapeHtml(e.wire)}</div>`;
  }).join('\n');
}

function escapeHtml(s){return s.replace(/[&<>]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]));}
init();
</script>
</body>
</html>
"""


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
        from flask import Flask, jsonify, request
    except ImportError as exc:
        raise RuntimeError("Flask no instalado. Ejecuta: pip install flask") from exc

    app = Flask(__name__)
    tpath = templates_path or resolve_templates_path(SendOptions())
    templates = load_templates(tpath)

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

    @app.post("/api/run")
    def api_run():
        data = request.get_json(force=True) or {}
        try:
            scenario_path = resolve_scenario(str(data.get("scenario", "")))
        except ValueError as exc:
            return jsonify({"error": str(exc)})
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
        collected: list[EmittedEvent] = []
        try:
            summary = run_scenario(
                scenario, templates, options,
                phase_filter=str(data.get("phase", "")),
                no_delay=True, collect=collected,
            )
        except (KeyError, ValueError, RuntimeError) as exc:
            return jsonify({"error": str(exc)})

        return jsonify({
            "live": not options.dry_run,
            "target": options.target,
            "port": options.port,
            "summary": {"total": summary.total, "sent": summary.sent, "dry_run": summary.dry_run},
            "events": [asdict(e) for e in collected],
        })

    return app


def serve(host: str = "127.0.0.1", port: int = 8800, templates_path: Path | None = None) -> None:
    app = create_app(templates_path)
    print(f"FortiSIEM Sim web en http://{host}:{port}  (Ctrl+C para salir)")
    app.run(host=host, port=port, debug=False)
