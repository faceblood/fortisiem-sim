/* FortiSIEM Sim — GUI: Ejecutar · Config · Escenario */

const $ = (id) => document.getElementById(id);

async function api(url, opts) {
  const r = await fetch(url, opts);
  const data = await r.json();
  if (!r.ok) throw new Error(data.error || r.statusText);
  return data;
}

function esc(s) {
  return String(s).replace(/[&<>]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" }[c]));
}

function banner(el, cls, text) {
  el.className = "banner " + cls;
  el.textContent = text;
}

function linesToArr(ta) {
  return ta.value.split("\n").map((s) => s.trim()).filter(Boolean);
}

function arrToLines(arr) {
  return (arr || []).join("\n");
}

/* ---------- Tabs ---------- */
document.querySelectorAll("nav.tabs button").forEach((btn) => {
  btn.addEventListener("click", () => {
    document.querySelectorAll("nav.tabs button").forEach((b) => b.classList.remove("active"));
    document.querySelectorAll(".panel").forEach((p) => p.classList.remove("active"));
    btn.classList.add("active");
    $(`panel-${btn.dataset.tab}`).classList.add("active");
    if (btn.dataset.tab === "config" && !state.configLoaded) loadConfig();
    if (btn.dataset.tab === "scenario" && !state.scenarioReady) initScenarioTab();
  });
});

const state = {
  configLoaded: false,
  config: null,
  actorKeys: [],
  eventIds: [],
  scenarioReady: false,
  es: null,
  eventCount: 0,
  expectedTotal: 0,
};

/* ========== EJECUTAR ========== */
function runParams() {
  const p = new URLSearchParams();
  p.set("scenario", $("run-scenario").value);
  const phase = $("run-phase").value;
  if (phase) p.set("phase", phase);
  const count = $("run-count").value;
  const seed = $("run-seed").value;
  if (count) p.set("count", count);
  if (seed) p.set("seed", seed);
  if ($("run-send").checked) p.set("send", "1");
  if ($("run-nospoof").checked) p.set("no_spoof", "1");
  return p;
}

function setRunning(on) {
  $("btn-run").disabled = on;
  $("btn-stop").style.display = on ? "block" : "none";
}

function updateRunCounter() {
  $("run-counter").textContent =
    state.eventCount + (state.expectedTotal ? ` / ~${state.expectedTotal}` : "");
  if (state.expectedTotal) {
    $("run-progress-bar").style.width =
      Math.min(100, Math.round((state.eventCount / state.expectedTotal) * 100)) + "%";
  }
}

function renderRunEvent(e, out) {
  const cls = e.sent ? "line-sent" : "line-dry";
  const head = `[${e.sent ? "SENT" : "DRY"}] ${e.event_id} · ${e.phase || "-"} · ${e.actor || "-"} · src=${e.packet_src}`;
  out.insertAdjacentHTML(
    "beforeend",
    `<div class="${cls}">${head}</div><div class="wire">${esc(e.wire)}</div>`
  );
  out.scrollTop = out.scrollHeight;
}

async function initRunTab() {
  const data = await api("/api/scenarios");
  const sel = $("run-scenario");
  sel.innerHTML = data.scenarios.map((s) => `<option value="${s}">${s}</option>`).join("");
  sel.onchange = loadRunPhases;
  if (data.scenarios.length) loadRunPhases();
}

async function loadRunPhases() {
  const name = $("run-scenario").value;
  if (!name) return;
  const sc = await api("/api/scenarios/" + encodeURIComponent(name));
  $("run-phase").innerHTML =
    '<option value="">(todas)</option>' +
    sc.phases.map((p) => `<option value="${p.name}">${p.name} (~${p.total})</option>`).join("");
}

function stopRun() {
  if (state.es) {
    state.es.close();
    state.es = null;
  }
  setRunning(false);
  banner($("run-banner"), "dry", "Detenido por el usuario.");
}

function runSse() {
  const out = $("run-out");
  out.innerHTML = "";
  state.eventCount = 0;
  state.expectedTotal = 0;
  updateRunCounter();
  $("run-progress").style.display = "block";
  setRunning(true);
  banner($("run-banner"), "stream", "Conectando stream SSE…");

  state.es = new EventSource("/api/run/stream?" + runParams().toString());
  state.es.onmessage = (ev) => {
    const msg = JSON.parse(ev.data);
    if (msg.type === "start") {
      state.expectedTotal = msg.expected || 0;
      updateRunCounter();
      banner($("run-banner"), msg.live ? "live" : "dry", msg.live
        ? `LIVE SSE → ${msg.target}:${msg.port}`
        : "DRY-RUN SSE (delays reales)");
    } else if (msg.type === "phase") {
      out.insertAdjacentHTML(
        "beforeend",
        `<div class="line-phase">▶ ${msg.name}${msg.description ? " — " + msg.description : ""}</div>`
      );
      out.scrollTop = out.scrollHeight;
    } else if (msg.type === "event") {
      renderRunEvent(msg, out);
      state.eventCount++;
      updateRunCounter();
    } else if (msg.type === "done") {
      banner($("run-banner"), msg.live ? "live" : "dry", msg.live
        ? `Completado: ${msg.summary.sent} enviados`
        : `Completado: ${msg.summary.total} eventos (dry-run)`);
      state.es.close();
      state.es = null;
      setRunning(false);
    } else if (msg.type === "error") {
      banner($("run-banner"), "live", "ERROR: " + msg.message);
      out.insertAdjacentHTML("beforeend", `<div class="line-dry">ERROR: ${esc(msg.message)}</div>`);
      state.es.close();
      state.es = null;
      setRunning(false);
    }
  };
  state.es.onerror = () => {
    if (state.es) {
      state.es.close();
      state.es = null;
    }
    setRunning(false);
  };
}

async function runBatch() {
  const out = $("run-out");
  out.textContent = "Ejecutando (batch)…";
  $("run-progress").style.display = "none";
  setRunning(true);
  const body = Object.fromEntries(runParams());
  body.send = $("run-send").checked;
  body.no_spoof = $("run-nospoof").checked;
  try {
    const res = await api("/api/run", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    banner($("run-banner"), res.live ? "live" : "dry", res.live
      ? `LIVE: ${res.summary.sent} enviados`
      : `DRY-RUN: ${res.summary.total} eventos`);
    out.innerHTML = "";
    state.eventCount = res.events.length;
    $("run-counter").textContent = state.eventCount;
    res.events.forEach((e) => renderRunEvent(e, out));
  } catch (e) {
    banner($("run-banner"), "live", "ERROR: " + e.message);
    out.textContent = e.message;
  }
  setRunning(false);
}

$("btn-run").addEventListener("click", () => {
  if ($("run-sse").checked) runSse();
  else runBatch();
});
$("btn-stop").addEventListener("click", stopRun);

/* ========== CONFIG ========== */
function renderUserChips(users) {
  $("cfg-users").innerHTML = users
    .map(
      (u, i) =>
        `<span class="chip">${esc(u)}<button type="button" data-i="${i}" class="rm-user" title="Quitar">×</button></span>`
    )
    .join("");
  $("cfg-users").querySelectorAll(".rm-user").forEach((btn) => {
    btn.addEventListener("click", () => {
      users.splice(+btn.dataset.i, 1);
      renderUserChips(users);
    });
  });
}

function hostRow(host, type, idx) {
  const tr = document.createElement("tr");
  tr.innerHTML = `
    <td><input data-f="hostname" value="${esc(host.hostname || "")}"></td>
    <td><input data-f="user" value="${esc(host.user || "")}"></td>
    <td><input data-f="src_ip" value="${esc(host.src_ip || "")}"></td>
    <td><input data-f="reporting_ip" value="${esc(host.reporting_ip || "")}"></td>
    <td><button type="button" class="btn btn-ghost btn-sm rm-row">×</button></td>`;
  if (type === "fw") {
    tr.innerHTML = `
      <td><input data-f="name" value="${esc(host.name || "")}"></td>
      <td><input data-f="serial" value="${esc(host.serial || "")}"></td>
      <td><input data-f="src_ip" value="${esc(host.src_ip || "")}"></td>
      <td><input data-f="reporting_ip" value="${esc(host.reporting_ip || "")}"></td>
      <td><button type="button" class="btn btn-ghost btn-sm rm-row">×</button></td>`;
  }
  tr.querySelector(".rm-row").addEventListener("click", () => tr.remove());
  return tr;
}

function readHostTable(tbodyId, isFw) {
  const rows = [];
  $(tbodyId).querySelectorAll("tr").forEach((tr) => {
    const obj = {};
    tr.querySelectorAll("input[data-f]").forEach((inp) => {
      obj[inp.dataset.f] = inp.value.trim();
    });
    if (isFw) obj.devname = obj.name || "FGT-LAB";
    if (obj.hostname || obj.name) rows.push(obj);
  });
  return rows;
}

function fillConfigUI(data) {
  state.config = data;
  const ad = data.ad || {};
  $("cfg-domain").value = ad.primary_domain || "";
  $("cfg-domains").value = arrToLines(ad.domains);
  renderUserChips(ad.users || []);
  $("cfg-src-ips").value = arrToLines(data.pools?.src_ips);
  $("cfg-reporting-ips").value = arrToLines(data.pools?.reporting_ips);

  const fwBody = $("cfg-firewalls");
  fwBody.innerHTML = "";
  (data.firewalls || []).forEach((fw) => fwBody.appendChild(hostRow(fw, "fw")));

  const winBody = $("cfg-windows");
  winBody.innerHTML = "";
  (data.windows_hosts || []).forEach((h) => winBody.appendChild(hostRow(h)));

  const linBody = $("cfg-linux");
  linBody.innerHTML = "";
  (data.linux_hosts || []).forEach((h) => linBody.appendChild(hostRow(h)));

  state.actorKeys = data.actor_keys || [];
  state.configLoaded = true;
}

async function loadConfig() {
  try {
    const data = await api("/api/config");
    fillConfigUI(data);
  } catch (e) {
    banner($("config-banner"), "live", "Error cargando config: " + e.message);
  }
}

function collectConfig() {
  const users = [];
  $("cfg-users").querySelectorAll(".chip").forEach((c) => {
    users.push(c.textContent.replace("×", "").trim());
  });
  return {
    ad: {
      primary_domain: $("cfg-domain").value.trim() || "lab.local",
      domains: linesToArr($("cfg-domains")),
      users,
    },
    firewalls: readHostTable("cfg-firewalls", true),
    windows_hosts: readHostTable("cfg-windows"),
    linux_hosts: readHostTable("cfg-linux"),
    pools: {
      src_ips: linesToArr($("cfg-src-ips")),
      reporting_ips: linesToArr($("cfg-reporting-ips")),
    },
  };
}

$("btn-add-user").addEventListener("click", () => {
  const v = $("cfg-user-new").value.trim();
  if (!v) return;
  const users = [];
  $("cfg-users").querySelectorAll(".chip").forEach((c) =>
    users.push(c.textContent.replace("×", "").trim())
  );
  if (!users.includes(v)) users.push(v);
  renderUserChips(users);
  $("cfg-user-new").value = "";
});

$("btn-add-fw").addEventListener("click", () => {
  $("cfg-firewalls").appendChild(
    hostRow({ name: "FGT-NEW", serial: "FGT000", src_ip: "10.0.0.1", reporting_ip: "10.0.0.1" }, "fw")
  );
});
$("btn-add-win").addEventListener("click", () => {
  $("cfg-windows").appendChild(
    hostRow({ hostname: "ws-new", user: "lab.user", src_ip: "10.0.0.2", reporting_ip: "10.255.9.21" })
  );
});
$("btn-add-linux").addEventListener("click", () => {
  $("cfg-linux").appendChild(
    hostRow({ hostname: "linux-new", user: "root", src_ip: "10.0.0.3", reporting_ip: "10.255.9.21" })
  );
});

$("btn-save-config").addEventListener("click", async () => {
  try {
    const res = await api("/api/config", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(collectConfig()),
    });
    fillConfigUI(res);
    banner($("config-banner"), "ok", "Config guardada en assets.yaml");
  } catch (e) {
    banner($("config-banner"), "live", "Error: " + e.message);
  }
});

/* ========== ESCENARIO BUILDER ========== */
let scPhases = [];

function actorOptions(selected) {
  const keys = state.actorKeys.length ? state.actorKeys : ["default"];
  return (
    '<option value="">(default)</option>' +
    keys.map((k) => `<option value="${esc(k)}"${k === selected ? " selected" : ""}>${esc(k)}</option>`).join("")
  );
}

function eventOptions(selected) {
  return state.eventIds
    .map((id) => `<option value="${esc(id)}"${id === selected ? " selected" : ""}>${esc(id)}</option>`)
    .join("");
}

function renderPhaseBlock(ph, pi) {
  const div = document.createElement("div");
  div.className = "phase-block";
  div.dataset.pi = pi;
  div.innerHTML = `
    <div class="row">
      <div><label>Nombre fase</label><input class="ph-name" value="${esc(ph.name)}"></div>
      <div><label>delay_before (s)</label><input class="ph-delay" type="number" step="0.1" value="${ph.delay_before ?? 0}"></div>
      <div style="flex:0"><label>&nbsp;</label><button type="button" class="btn btn-danger btn-sm rm-phase">Eliminar fase</button></div>
    </div>
    <label>Descripción</label>
    <input class="ph-desc" value="${esc(ph.description || "")}">
    <div class="events-wrap"></div>
    <button type="button" class="btn btn-ghost btn-sm add-event">+ Evento</button>`;

  const wrap = div.querySelector(".events-wrap");
  (ph.events || []).forEach((ev, ei) => wrap.appendChild(renderEventRow(ev, pi, ei)));

  div.querySelector(".add-event").addEventListener("click", () => {
    const ev = { id: state.eventIds[0] || "login_failed", count: 1, actor: "", delay: 0.5, jitter: 0.2 };
    wrap.appendChild(renderEventRow(ev, pi, wrap.children.length));
  });
  div.querySelector(".rm-phase").addEventListener("click", () => {
    scPhases.splice(pi, 1);
    renderAllPhases();
  });
  return div;
}

function renderEventRow(ev, pi, ei) {
  const row = document.createElement("div");
  row.className = "event-row";
  row.innerHTML = `
    <div><label>event id</label><select class="ev-id">${eventOptions(ev.id)}</select></div>
    <div><label>count</label><input class="ev-count" type="number" min="1" value="${ev.count ?? 1}"></div>
    <div><label>delay</label><input class="ev-delay" type="number" step="0.1" value="${ev.delay ?? ""}"></div>
    <div><label>jitter</label><input class="ev-jitter" type="number" step="0.1" value="${ev.jitter ?? ""}"></div>
    <div><label>actor</label><select class="ev-actor">${actorOptions(ev.actor)}</select></div>
    <div><label>&nbsp;</label><button type="button" class="btn btn-ghost btn-sm rm-ev">×</button></div>`;
  row.querySelector(".rm-ev").addEventListener("click", () => row.remove());
  return row;
}

function renderAllPhases() {
  const container = $("sc-phases");
  container.innerHTML = "";
  scPhases.forEach((ph, i) => container.appendChild(renderPhaseBlock(ph, i)));
}

function readPhasesFromUI() {
  const phases = [];
  $("sc-phases").querySelectorAll(".phase-block").forEach((block) => {
    const events = [];
    block.querySelectorAll(".event-row").forEach((row) => {
      events.push({
        id: row.querySelector(".ev-id").value,
        count: +row.querySelector(".ev-count").value || 1,
        actor: row.querySelector(".ev-actor").value,
        delay: row.querySelector(".ev-delay").value,
        jitter: row.querySelector(".ev-jitter").value,
      });
    });
    phases.push({
      name: block.querySelector(".ph-name").value.trim() || "phase",
      description: block.querySelector(".ph-desc").value.trim(),
      delay_before: +block.querySelector(".ph-delay").value || 0,
      events,
    });
  });
  return phases;
}

async function initScenarioTab() {
  try {
    const [events, scenarios] = await Promise.all([api("/api/events"), api("/api/scenarios")]);
    state.eventIds = events.ids || [];
    const sel = $("sc-load");
    sel.innerHTML = scenarios.scenarios.map((s) => `<option value="${s}">${s}</option>`).join("");
    if (!state.configLoaded) await loadConfig();
    if (!scPhases.length) newScenario();
    state.scenarioReady = true;
  } catch (e) {
    banner($("sc-banner"), "live", "Error: " + e.message);
  }
}

function newScenario() {
  $("sc-name").value = "mi-ejercicio";
  $("sc-desc").value = "";
  $("sc-org").value = "1";
  $("sc-timeline").value = "0";
  $("sc-use-config").checked = true;
  scPhases = [
    {
      name: "fase_1",
      description: "Primera fase",
      delay_before: 0,
      events: [{ id: state.eventIds[0] || "login_failed", count: 5, actor: "", delay: 0.5, jitter: 0.2 }],
    },
  ];
  renderAllPhases();
  banner($("sc-banner"), "dry", "Escenario nuevo — edita fases y guarda.");
}

async function loadScenarioBuilder() {
  const name = $("sc-load").value;
  if (!name) return;
  try {
    const sc = await api("/api/scenarios/" + encodeURIComponent(name) + "/builder");
    $("sc-name").value = sc.name || name;
    $("sc-desc").value = sc.description || "";
    $("sc-org").value = sc.org_id ?? 1;
    $("sc-timeline").value = sc.timeline_minutes ?? 0;
    $("sc-use-config").checked = !!sc.use_config_actors;
    scPhases = sc.phases || [];
    renderAllPhases();
    banner($("sc-banner"), "ok", `Cargado: ${name}`);
  } catch (e) {
    banner($("sc-banner"), "live", "Error: " + e.message);
  }
}

$("btn-sc-new").addEventListener("click", newScenario);
$("btn-sc-load").addEventListener("click", loadScenarioBuilder);
$("btn-add-phase").addEventListener("click", () => {
  scPhases.push({
    name: "fase_" + (scPhases.length + 1),
    description: "",
    delay_before: 0,
    events: [{ id: state.eventIds[0] || "login_failed", count: 1, actor: "", delay: 0.5, jitter: 0.2 }],
  });
  renderAllPhases();
});

$("btn-save-scenario").addEventListener("click", async () => {
  const payload = {
    name: $("sc-name").value.trim(),
    description: $("sc-desc").value.trim(),
    org_id: +$("sc-org").value || 1,
    timeline_minutes: +$("sc-timeline").value || 0,
    use_config_actors: $("sc-use-config").checked,
    phases: readPhasesFromUI(),
  };
  try {
    const res = await api("/api/scenarios/builder", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    banner($("sc-banner"), "ok", `Guardado: ${res.path}`);
    await initRunTab();
    const sel = $("sc-load");
    const data = await api("/api/scenarios");
    sel.innerHTML = data.scenarios.map((s) => `<option value="${s}">${s}</option>`).join("");
    sel.value = res.name;
  } catch (e) {
    banner($("sc-banner"), "live", "Error: " + e.message);
  }
});

/* ---------- Init ---------- */
initRunTab();
