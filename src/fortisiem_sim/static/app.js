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
  eventCatalog: [],
  eventsByTactic: {},
  emailCatalog: [],
  runPhaseNames: [],
  phaseSequence: null,
  waitingContinue: false,
};

/* ========== EJECUTAR ========== */
function isAllPhasesRun() {
  return !$("run-phase").value;
}

function runParams(phaseOverride) {
  const p = new URLSearchParams();
  p.set("scenario", $("run-scenario").value);
  const phase = phaseOverride !== undefined ? phaseOverride : $("run-phase").value;
  if (phase) p.set("phase", phase);
  const count = $("run-count").value;
  const seed = $("run-seed").value;
  if (count) p.set("count", count);
  if (seed) p.set("seed", seed);
  if ($("run-send").checked) p.set("send", "1");
  if ($("run-nospoof").checked) p.set("no_spoof", "1");
  return p;
}

function resetPhaseSequence() {
  state.phaseSequence = null;
  state.waitingContinue = false;
  $("btn-continue").style.display = "none";
}

function setWaitingContinue(on) {
  state.waitingContinue = on;
  $("btn-continue").style.display = on ? "block" : "none";
  $("btn-run").disabled = on;
  $("btn-stop").style.display = on ? "block" : "none";
}

function setRunning(on) {
  if (state.waitingContinue) return;
  $("btn-run").disabled = on;
  $("btn-stop").style.display = on ? "block" : "none";
  if (!on) $("btn-continue").style.display = "none";
}

function onPhaseRunComplete(msg) {
  const seq = state.phaseSequence;
  if (!seq?.active) {
    banner($("run-banner"), msg.live ? "live" : "dry", msg.live
      ? `Completado: ${msg.summary.sent} enviados`
      : `Completado: ${msg.summary.total} eventos (dry-run)`);
    setRunning(false);
    return;
  }
  const current = seq.names[seq.index];
  const remaining = seq.names.length - seq.index - 1;
  if (remaining > 0) {
    setRunning(false);
    setWaitingContinue(true);
    banner(
      $("run-banner"),
      msg.live ? "live" : "dry",
      `Fase «${current}» completada. Quedan ${remaining}. Pulsa Continuar ▶`
    );
  } else {
    banner($("run-banner"), msg.live ? "live" : "dry", msg.live
      ? `Escenario completo: ${msg.summary.sent} enviados en ${seq.names.length} fases`
      : `Escenario completo: ${seq.names.length} fases (dry-run)`);
    resetPhaseSequence();
    setRunning(false);
  }
}

function continueNextPhase() {
  const seq = state.phaseSequence;
  if (!seq?.active || !state.waitingContinue) return;
  seq.index += 1;
  state.waitingContinue = false;
  $("btn-continue").style.display = "none";
  if ($("run-sse").checked) runSse({ phaseName: seq.names[seq.index], append: true });
  else runBatch({ phaseName: seq.names[seq.index], append: true });
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
  state.runPhaseNames = (sc.phases || []).map((p) => p.name);
  $("run-phase").innerHTML =
    '<option value="">(todas)</option>' +
    sc.phases.map((p) => `<option value="${p.name}">${p.name} (~${p.total})</option>`).join("");
  resetPhaseSequence();
}

function stopRun() {
  if (state.es) {
    state.es.close();
    state.es = null;
  }
  resetPhaseSequence();
  setRunning(false);
  banner($("run-banner"), "dry", "Detenido por el usuario.");
}

function startRun() {
  resetPhaseSequence();
  if (isAllPhasesRun() && state.runPhaseNames.length > 1) {
    state.phaseSequence = {
      active: true,
      index: 0,
      names: state.runPhaseNames.slice(),
    };
    if ($("run-sse").checked) runSse({ phaseName: state.runPhaseNames[0], append: false });
    else runBatch({ phaseName: state.runPhaseNames[0], append: false });
    return;
  }
  if ($("run-sse").checked) runSse({ append: false });
  else runBatch({ append: false });
}

function runSse({ phaseName, append } = {}) {
  const out = $("run-out");
  if (!append) {
    out.innerHTML = "";
    state.eventCount = 0;
    state.expectedTotal = 0;
  }
  updateRunCounter();
  $("run-progress").style.display = "block";
  setRunning(true);
  const label = phaseName || $("run-phase").value || "(todas)";
  banner($("run-banner"), "stream", `Conectando SSE · ${label}…`);

  state.es = new EventSource("/api/run/stream?" + runParams(phaseName || "").toString());
  state.es.onmessage = (ev) => {
    const msg = JSON.parse(ev.data);
    if (msg.type === "start") {
      if (!append) state.expectedTotal = msg.expected || 0;
      else state.expectedTotal += msg.expected || 0;
      updateRunCounter();
      banner($("run-banner"), msg.live ? "live" : "dry", msg.live
        ? `LIVE SSE → ${msg.target}:${msg.port} · ${label}`
        : `DRY-RUN SSE · ${label}`);
    } else if (msg.type === "phase") {
      out.insertAdjacentHTML(
        "beforeend",
        `<div class="line-phase">▶ ${msg.name}${msg.description ? " — " + msg.description : ""}</div>`
      );
      out.scrollTop = out.scrollHeight;
    } else if (msg.type === "email") {
      state.eventCount++;
      updateRunCounter();
      out.insertAdjacentHTML(
        "beforeend",
        `<div class="line-email">📧 [${msg.dry_run ? "DRY" : msg.sent ? "SENT" : "FAIL"}] ${esc(msg.subject)} → ${esc(msg.to_address)}</div>`
      );
      out.scrollTop = out.scrollHeight;
    } else if (msg.type === "event") {
      renderRunEvent(msg, out);
      state.eventCount++;
      updateRunCounter();
    } else if (msg.type === "done") {
      state.es.close();
      state.es = null;
      onPhaseRunComplete(msg);
    } else if (msg.type === "error") {
      banner($("run-banner"), "live", "ERROR: " + msg.message);
      out.insertAdjacentHTML("beforeend", `<div class="line-dry">ERROR: ${esc(msg.message)}</div>`);
      state.es.close();
      state.es = null;
      resetPhaseSequence();
      setRunning(false);
    }
  };
  state.es.onerror = () => {
    if (state.es) {
      state.es.close();
      state.es = null;
    }
    resetPhaseSequence();
    setRunning(false);
  };
}

async function runBatch({ phaseName, append } = {}) {
  const out = $("run-out");
  if (!append) {
    out.textContent = "Ejecutando (batch)…";
    state.eventCount = 0;
  } else {
    out.insertAdjacentHTML("beforeend", `<div class="line-phase">— siguiente fase —</div>`);
  }
  $("run-progress").style.display = append ? "block" : "none";
  setRunning(true);
  const body = Object.fromEntries(runParams(phaseName || ""));
  body.send = $("run-send").checked;
  body.no_spoof = $("run-nospoof").checked;
  try {
    const res = await api("/api/run", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (!append) out.innerHTML = "";
    res.events.forEach((e) => {
      renderRunEvent(e, out);
      state.eventCount++;
    });
    $("run-counter").textContent = state.eventCount;
    onPhaseRunComplete({
      live: res.live,
      summary: res.summary,
    });
  } catch (e) {
    banner($("run-banner"), "live", "ERROR: " + e.message);
    if (!append) out.textContent = e.message;
    resetPhaseSequence();
    setRunning(false);
  }
}

$("btn-run").addEventListener("click", startRun);
$("btn-continue").addEventListener("click", continueNextPhase);
$("btn-stop").addEventListener("click", stopRun);
$("run-phase").addEventListener("change", resetPhaseSequence);

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
  const c2 = data.c2 || {};
  $("cfg-c2-default-ip").value = c2.default_ip || "";
  $("cfg-c2-default-uri").value = c2.default_uri || "";
  $("cfg-c2-ips").value = arrToLines(c2.ips);
  $("cfg-c2-uris").value = arrToLines(c2.uris);
  const smtp = data.smtp || {};
  $("cfg-smtp-enabled").checked = !!smtp.enabled;
  $("cfg-smtp-host").value = smtp.host || "";
  $("cfg-smtp-port").value = smtp.port ?? 587;
  $("cfg-smtp-user").value = smtp.username || "";
  $("cfg-smtp-pass").value = smtp.password || "";
  $("cfg-smtp-from").value = smtp.from_address || "";
  $("cfg-smtp-from-name").value = smtp.from_name || "";
  $("cfg-smtp-tls").checked = smtp.use_tls !== false;
  $("cfg-smtp-ssl").checked = !!smtp.use_ssl;

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
    c2: {
      default_ip: $("cfg-c2-default-ip").value.trim() || "203.0.113.50",
      default_uri: $("cfg-c2-default-uri").value.trim() || "https://lab-c2.example/beacon",
      ips: linesToArr($("cfg-c2-ips")),
      uris: linesToArr($("cfg-c2-uris")),
    },
    pools: {
      src_ips: linesToArr($("cfg-src-ips")),
      reporting_ips: linesToArr($("cfg-reporting-ips")),
    },
    smtp: {
      enabled: $("cfg-smtp-enabled").checked,
      host: $("cfg-smtp-host").value.trim(),
      port: +$("cfg-smtp-port").value || 587,
      username: $("cfg-smtp-user").value.trim(),
      password: $("cfg-smtp-pass").value,
      from_address: $("cfg-smtp-from").value.trim(),
      from_name: $("cfg-smtp-from-name").value.trim() || "FortiSIEM Sim Lab",
      use_tls: $("cfg-smtp-tls").checked,
      use_ssl: $("cfg-smtp-ssl").checked,
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
    banner($("config-banner"), "ok", "Config guardada (SQLite)");
  } catch (e) {
    banner($("config-banner"), "live", "Error: " + e.message);
  }
});

$("btn-c2-import").addEventListener("click", async () => {
  const input = $("cfg-c2-file");
  const file = input.files && input.files[0];
  if (!file) {
    banner($("config-banner"), "dry", "Elige un fichero .txt con IOCs (una por línea).");
    return;
  }
  try {
    const text = await file.text();
    const res = await api("/api/config/c2/import", {
      method: "POST",
      headers: { "Content-Type": "text/plain" },
      body: text,
    });
    fillConfigUI(res);
    banner($("config-banner"), "ok", `IOCs importados desde ${file.name} y guardados.`);
    input.value = "";
  } catch (e) {
    banner($("config-banner"), "live", "Error importando: " + e.message);
  }
});

/* ========== ESCENARIO BUILDER ========== */
let scPhases = [];
let scMode = "new";
let scItems = [];
let scLoadedId = null;
let mitreTactics = [];

function mitreOptions(selected) {
  return mitreTactics
    .map(
      (t) =>
        `<option value="${esc(t.id)}"${t.id === selected ? " selected" : ""}>${esc(t.id)} · ${esc(t.name)}</option>`
    )
    .join("");
}

function normalizeScenarioEvent(ev) {
  return {
    id: ev.id,
    count: ev.count ?? 1,
    actor: ev.actor || "",
  };
}

function phaseSlugFromTacticId(tacticId) {
  const tactic = getTacticById(tacticId);
  return tactic ? tactic.slug : "";
}

const _PHASE_SLUG_ALIASES = {
  recon_and_access: "initial_access",
  staging_and_exfil: "collection",
  impact_identity: "impact",
  ot_and_crisis: "impact",
  ot_crisis: "impact",
};

function syncPhaseWithMitre(ph) {
  if (ph.phase_type === "email") return ph;
  let tid = ph.mitre_tactic || "";
  if (!tid && ph.name) {
    const bySlug = mitreTactics.find((t) => t.slug === ph.name);
    if (bySlug) tid = bySlug.id;
    else if (_PHASE_SLUG_ALIASES[ph.name]) {
      const t = mitreTactics.find((x) => x.slug === _PHASE_SLUG_ALIASES[ph.name]);
      if (t) tid = t.id;
    }
  }
  if (tid) {
    const tactic = getTacticById(tid);
    if (tactic) {
      ph.mitre_tactic = tactic.id;
      ph.name = tactic.slug;
      ph.mitre_techniques = ph.mitre_techniques?.length ? ph.mitre_techniques : tactic.techniques || [];
      if (!ph.description) ph.description = tactic.description;
    }
  }
  return ph;
}

function fillMitreAddSelect() {
  const sel = $("sc-add-tactic");
  if (!sel) return;
  sel.innerHTML = mitreTactics
    .map((t) => `<option value="${esc(t.id)}">${esc(t.id)} · ${esc(t.name)}</option>`)
    .join("");
}

function getTacticById(id) {
  return mitreTactics.find((t) => t.id === id);
}

function applyMitreToPhaseBlock(block, tacticId, replaceEvents) {
  const tactic = getTacticById(tacticId);
  if (!tactic) return;
  block.querySelector(".ph-mitre").value = tactic.id;
  block.querySelector(".ph-desc").value = tactic.description;
  const badge = block.querySelector(".mitre-badge");
  if (badge) {
    badge.textContent = `${tactic.slug} · ${tactic.id} · ${tactic.name} · ${(tactic.techniques || []).join(", ")}`;
  }
  if (replaceEvents && tactic.suggested_events?.length) {
    const wrap = block.querySelector(".steps-wrap");
    wrap.innerHTML = "";
    tactic.suggested_events.forEach((ev) =>
      wrap.appendChild(renderEventRow(normalizeScenarioEvent({ ...ev, actor: "" }), block))
    );
  }
  refreshPhaseEventSelects(block);
}

function phaseFromTactic(tacticId, withEvents) {
  const tactic = getTacticById(tacticId);
  if (!tactic) return { name: "fase", description: "", events: [] };
  return {
    phase_type: "mitre",
    name: tactic.slug,
    description: tactic.description,
    mitre_tactic: tactic.id,
    mitre_techniques: tactic.techniques || [],
    events: withEvents
      ? (tactic.suggested_events || []).map((ev) => normalizeScenarioEvent({ ...ev, actor: "" }))
      : [normalizeScenarioEvent({ id: firstAllowedEventId(tactic.id) || "login_failed", count: 1, actor: "" })],
    emails: [],
  };
}

function mitrePhaseSteps(ph) {
  const steps = [];
  (ph.events || []).forEach((ev, i) => {
    steps.push({
      type: "event",
      sort_order: ev.sort_order ?? i,
      data: normalizeScenarioEvent(ev),
    });
  });
  (ph.emails || []).forEach((em, i) => {
    steps.push({
      type: "email",
      sort_order: em.sort_order ?? (ph.events?.length || 0) + i,
      data: em,
    });
  });
  steps.sort((a, b) => a.sort_order - b.sort_order);
  return steps;
}

function setScenarioMode(mode) {
  scMode = mode;
  $("sc-mode-new").classList.toggle("active", mode === "new");
  $("sc-mode-load").classList.toggle("active", mode === "load");
  $("sc-load-panel").style.display = mode === "load" ? "block" : "none";
  $("sc-new-hint").style.display = mode === "new" ? "block" : "none";
  if (mode === "new") {
    scLoadedId = null;
    renderScenarioPreview(null);
    document.querySelectorAll(".scenario-item").forEach((el) => el.classList.remove("active"));
  }
}

function renderScenarioPreview(item) {
  const box = $("sc-preview");
  if (!item) {
    box.style.display = "none";
    box.innerHTML = "";
    return;
  }
  box.style.display = "block";
  box.innerHTML = `
    <h4>${esc(item.name || item.id)}</h4>
    <div class="meta">${esc(item.description || "Sin descripción")}</div>
    <div class="meta">${item.phases} fases · ~${item.events} eventos · timeline ${item.timeline_minutes || 0} min · <code>${esc(item.file || item.id + ".yml")}</code></div>`;
}

function renderScenarioList(items, selectedId) {
  scItems = items;
  const list = $("sc-scenario-list");
  if (!items.length) {
    list.innerHTML = '<div class="meta">No hay escenarios en scenarios/. Crea uno nuevo y guárdalo.</div>';
    return;
  }
  list.innerHTML = items
    .map(
      (it) => `
    <button type="button" class="scenario-item${it.id === selectedId ? " active" : ""}" data-id="${esc(it.id)}">
      <div class="si-title">${esc(it.name || it.id)}</div>
      <div class="si-meta">${it.phases} fases · ~${it.events} ev. · ${esc(it.file)}</div>
    </button>`
    )
    .join("");
  list.querySelectorAll(".scenario-item").forEach((btn) => {
    btn.addEventListener("click", () => {
      $("sc-load").value = btn.dataset.id;
      loadScenarioBuilder(btn.dataset.id);
    });
  });
}

function fillScenarioSelect(items, selectedId) {
  const sel = $("sc-load");
  sel.innerHTML =
    '<option value="">— elegir escenario —</option>' +
    items.map((it) => `<option value="${esc(it.id)}">${esc(it.name || it.id)} (${it.phases} fases)</option>`).join("");
  if (selectedId) sel.value = selectedId;
}

async function refreshScenarioCatalog(selectId) {
  const data = await api("/api/scenarios");
  const items = data.items || data.scenarios.map((id) => ({ id, name: id, phases: "?", events: "?", file: id + ".yml" }));
  renderScenarioList(items, selectId || scLoadedId);
  fillScenarioSelect(items, selectId || scLoadedId);
  return items;
}

function actorOptions(selected) {
  const keys = state.actorKeys.length ? state.actorKeys : ["default"];
  return (
    '<option value="">(default)</option>' +
    keys.map((k) => `<option value="${esc(k)}"${k === selected ? " selected" : ""}>${esc(k)}</option>`).join("")
  );
}

function getCatalogEntry(eventId) {
  return state.eventCatalog.find((e) => e.id === eventId);
}

function allowedEventIds(tacticId) {
  if (!tacticId) return [];
  return state.eventsByTactic[tacticId] || [];
}

function firstAllowedEventId(tacticId) {
  const ids = allowedEventIds(tacticId);
  return ids[0] || "";
}

function eventOptions(selected, tacticId) {
  const ids = tacticId ? allowedEventIds(tacticId) : [];
  if (!tacticId) {
    return `<option value="">— elige táctica MITRE primero —</option>`;
  }
  if (!ids.length) {
    return `<option value="">— sin eventos para ${esc(tacticId)} —</option>`;
  }
  return ids
    .map((id) => {
      const entry = getCatalogEntry(id);
      const sys = entry?.system ? `${entry.system} · ` : "";
      const ttp = entry ? entry.techniques.join(", ") : "";
      const label = ttp ? `${sys}${id} (${ttp})` : sys ? `${sys}${id}` : id;
      return `<option value="${esc(id)}"${id === selected ? " selected" : ""}>${esc(label)}</option>`;
    })
    .join("");
}

function updatePhaseEventHint(block) {
  const hint = block.querySelector(".ph-event-hint");
  if (!hint) return;
  const tid = block.querySelector(".ph-mitre").value;
  if (!tid) {
    hint.textContent = "Selecciona una táctica MITRE para habilitar eventos compatibles.";
    return;
  }
  const ids = allowedEventIds(tid);
  hint.textContent = ids.length
    ? `${ids.length} evento(s) disponibles para ${tid}: ${ids.join(", ")}`
    : `No hay eventos mapeados para ${tid}.`;
}

function refreshPhaseEventSelects(block) {
  const tid = block.querySelector(".ph-mitre")?.value;
  if (!tid) return;
  const allowed = new Set(allowedEventIds(tid));
  block.querySelectorAll(".steps-wrap > .event-row").forEach((row) => {
    const sel = row.querySelector(".ev-id");
    const cur = sel.value;
    sel.innerHTML = eventOptions(cur, tid);
    if (tid && cur && !allowed.has(cur)) {
      sel.value = firstAllowedEventId(tid);
    }
    updateEventRowTtp(row, sel.value);
  });
  updatePhaseEventHint(block);
  const addBtn = block.querySelector(".add-event");
  if (addBtn) addBtn.disabled = !tid || !allowed.size;
}

function updateEventRowTtp(row, eventId) {
  const el = row.querySelector(".ev-ttp");
  if (!el) return;
  const entry = getCatalogEntry(eventId);
  el.textContent = entry
    ? `${entry.system} · ${entry.tactics.join(" · ")} — ${entry.techniques.join(", ")}`
    : "";
}

function applyEventCatalog(events) {
  state.eventIds = events.ids || [];
  state.eventCatalog = events.catalog || [];
  state.eventsByTactic = events.by_tactic || {};
  renderEventCatalogTable();
  document.querySelectorAll(".phase-block").forEach((block) => refreshPhaseEventSelects(block));
}

async function refreshEventCatalog() {
  return applyEventCatalog(await api("/api/events"));
}

function renderEventCatalogTable() {
  const body = $("event-catalog-body");
  const countEl = $("catalog-count");
  if (!body) return;
  if (countEl) countEl.textContent = state.eventCatalog.length;
  body.innerHTML = state.eventCatalog
    .map(
      (e) => `
    <tr>
      <td><code>${esc(e.id)}</code></td>
      <td>${esc(e.name)}</td>
      <td><span class="pill pill-system">${esc(e.system || "—")}</span></td>
      <td>${(e.tactics || []).map((t) => `<span class="pill">${esc(t)}</span>`).join(" ")}</td>
      <td><span class="meta">${esc((e.techniques || []).join(", "))}</span></td>
    </tr>`
    )
    .join("");
}

function phaseFromEmail(name) {
  const slug = (name || "correo_crisis").trim().replace(/\s+/g, "_").toLowerCase();
  const firstTpl = state.emailCatalog[0]?.id || "ir_alert_tabletop";
  return {
    phase_type: "email",
    name: slug,
    description: "Fase de correos HTML (tabletop)",
    emails: [{ template_id: firstTpl, to_address: "{{user}}@{{domain}}", cc: "", actor: "" }],
  };
}

function emailTemplateOptions(selected) {
  if (!state.emailCatalog.length) {
    return `<option value="">— crea plantillas abajo —</option>`;
  }
  return state.emailCatalog
    .map(
      (t) =>
        `<option value="${esc(t.id)}"${t.id === selected ? " selected" : ""}>${esc(t.id)} · ${esc(t.name)}</option>`
    )
    .join("");
}

function renderEmailPhaseBlock(ph, pi) {
  const div = document.createElement("div");
  div.className = "phase-block phase-email";
  div.dataset.pi = pi;
  div.dataset.phaseType = "email";
  div.innerHTML = `
    <div class="mitre-badge pill-email">📧 Fase correo · ${esc(ph.name || "email")}</div>
    <div class="row">
      <div><label>Nombre fase (slug)</label><input class="ph-name" value="${esc(ph.name || "email")}"></div>
      <div style="flex:0"><label>&nbsp;</label><button type="button" class="btn btn-danger btn-sm rm-phase">Eliminar</button></div>
    </div>
    <label>Descripción</label>
    <input class="ph-desc" value="${esc(ph.description || "")}">
    <div class="emails-wrap"></div>
    <button type="button" class="btn btn-ghost btn-sm add-email">+ Correo</button>`;
  const wrap = div.querySelector(".emails-wrap");
  (ph.emails || []).forEach((em) => wrap.appendChild(renderEmailRow(em, div, false)));
  div.querySelector(".add-email").addEventListener("click", () => {
    wrap.appendChild(
      renderEmailRow(
        { template_id: state.emailCatalog[0]?.id || "", to_address: "{{user}}@{{domain}}", cc: "", actor: "" },
        div,
        false
      )
    );
  });
  div.querySelector(".rm-phase").addEventListener("click", () => {
    scPhases.splice(pi, 1);
    renderAllPhases();
  });
  return div;
}

function renderEmailRow(em, block, inline) {
  const row = document.createElement("div");
  row.className = "event-row email-row" + (inline ? " email-row-inline" : "");
  row.innerHTML = `
    ${inline ? '<div class="email-step-tag">📧 Correo</div>' : ""}
    <div><label>Plantilla</label><select class="em-tpl">${emailTemplateOptions(em.template_id)}</select></div>
    <div><label>Para (to)</label><input class="em-to" value="${esc(em.to_address || "")}" placeholder="{{user}}@{{domain}}"></div>
    <div><label>CC</label><input class="em-cc" value="${esc(em.cc || "")}"></div>
    <div><label>&nbsp;</label><button type="button" class="btn btn-ghost btn-sm rm-em">×</button></div>`;
  row.querySelector(".rm-em").addEventListener("click", () => row.remove());
  return row;
}

function renderPhaseBlock(ph, pi) {
  if (ph.phase_type === "email") return renderEmailPhaseBlock(ph, pi);
  return renderMitrePhaseBlock(ph, pi);
}

function renderMitrePhaseBlock(ph, pi) {
  const tactic = ph.mitre_tactic ? getTacticById(ph.mitre_tactic) : null;
  const synced = syncPhaseWithMitre({ ...ph });
  const showTactic = tactic || getTacticById(synced.mitre_tactic);
  const badgeText = showTactic
    ? `${showTactic.slug} · ${showTactic.id} · ${showTactic.name} · ${(showTactic.techniques || synced.mitre_techniques || []).join(", ")}`
    : "Elige una táctica MITRE ATT&CK";
  const mitreVal = synced.mitre_tactic || mitreTactics[0]?.id || "";
  const div = document.createElement("div");
  div.className = "phase-block";
  div.dataset.pi = pi;
  div.dataset.phaseType = "mitre";
  div.innerHTML = `
    <div class="mitre-badge">${esc(badgeText)}</div>
    <div class="row">
      <div><label>Táctica MITRE ATT&CK (nombre de fase en YAML)</label><select class="ph-mitre">${mitreOptions(mitreVal)}</select></div>
      <div style="flex:0"><label>&nbsp;</label><button type="button" class="btn btn-danger btn-sm rm-phase">Eliminar</button></div>
    </div>
    <label>Descripción (TTP)</label>
    <input class="ph-desc" value="${esc(synced.description || "")}">
    <div class="row" style="margin:6px 0">
      <button type="button" class="btn btn-ghost btn-sm ph-apply-events">Aplicar eventos sugeridos MITRE</button>
    </div>
    <div class="meta ph-event-hint"></div>
    <div class="steps-wrap"></div>
    <div class="row phase-step-actions">
      <button type="button" class="btn btn-ghost btn-sm add-event" disabled>+ Evento (MITRE)</button>
      <button type="button" class="btn btn-ghost btn-sm add-email-inline pill-email">+ Correo</button>
    </div>`;

  const wrap = div.querySelector(".steps-wrap");
  mitrePhaseSteps(synced).forEach((step) => {
    if (step.type === "email") {
      wrap.appendChild(renderEmailRow(step.data, div, true));
    } else {
      wrap.appendChild(renderEventRow(step.data, div));
    }
  });

  div.querySelector(".ph-mitre").addEventListener("change", (e) => {
    applyMitreToPhaseBlock(div, e.target.value, false);
  });
  div.querySelector(".ph-apply-events").addEventListener("click", () => {
    const tid = div.querySelector(".ph-mitre").value;
    if (tid) applyMitreToPhaseBlock(div, tid, true);
  });
  div.querySelector(".add-event").addEventListener("click", () => {
    const tid = div.querySelector(".ph-mitre").value;
    wrap.appendChild(
      renderEventRow(
        normalizeScenarioEvent({ id: firstAllowedEventId(tid) || "", count: 1, actor: "" }),
        div
      )
    );
  });
  div.querySelector(".add-email-inline").addEventListener("click", () => {
    wrap.appendChild(
      renderEmailRow(
        {
          template_id: state.emailCatalog[0]?.id || "ir_alert_tabletop",
          to_address: "{{user}}@{{domain}}",
          cc: "",
          actor: "",
        },
        div,
        true
      )
    );
  });
  div.querySelector(".rm-phase").addEventListener("click", () => {
    scPhases.splice(pi, 1);
    renderAllPhases();
  });
  refreshPhaseEventSelects(div);
  return div;
}

function renderEventRow(ev, block) {
  const tid = block.querySelector(".ph-mitre").value;
  const row = document.createElement("div");
  row.className = "event-row";
  row.innerHTML = `
    <div><label>event id</label><select class="ev-id">${eventOptions(ev.id, tid)}</select><div class="ev-ttp"></div></div>
    <div><label>count</label><input class="ev-count" type="number" min="1" value="${ev.count ?? 1}"></div>
    <div><label>actor</label><select class="ev-actor">${actorOptions(ev.actor)}</select></div>
    <div><label>&nbsp;</label><button type="button" class="btn btn-ghost btn-sm rm-ev">×</button></div>`;
  row.querySelector(".ev-id").addEventListener("change", (e) => updateEventRowTtp(row, e.target.value));
  updateEventRowTtp(row, row.querySelector(".ev-id").value);
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
    const ptype = block.dataset.phaseType || "mitre";
    if (ptype === "email") {
      const emails = [];
      block.querySelectorAll(".email-row").forEach((row) => {
        emails.push({
          template_id: row.querySelector(".em-tpl").value,
          to_address: row.querySelector(".em-to").value.trim(),
          cc: row.querySelector(".em-cc").value.trim(),
        });
      });
      phases.push({
        phase_type: "email",
        name: block.querySelector(".ph-name").value.trim().replace(/\s+/g, "_").toLowerCase() || "email",
        description: block.querySelector(".ph-desc").value.trim(),
        emails,
      });
      return;
    }
    const events = [];
    const emails = [];
    let order = 0;
    block.querySelectorAll(".steps-wrap > .event-row, .steps-wrap > .email-row").forEach((row) => {
      if (row.classList.contains("email-row")) {
        emails.push({
          template_id: row.querySelector(".em-tpl").value,
          to_address: row.querySelector(".em-to").value.trim(),
          cc: row.querySelector(".em-cc").value.trim(),
          sort_order: order++,
        });
      } else {
        events.push(
          normalizeScenarioEvent({
            id: row.querySelector(".ev-id").value,
            count: +row.querySelector(".ev-count").value || 1,
            actor: row.querySelector(".ev-actor").value,
            sort_order: order++,
          })
        );
      }
    });
    phases.push({
      phase_type: "mitre",
      name: phaseSlugFromTacticId(block.querySelector(".ph-mitre").value) || "phase",
      description: block.querySelector(".ph-desc").value.trim(),
      mitre_tactic: block.querySelector(".ph-mitre").value,
      mitre_techniques: (getTacticById(block.querySelector(".ph-mitre").value)?.techniques) || [],
      events,
      emails,
    });
  });
  return phases;
}

function renderEmailCatalogTable() {
  const body = $("email-catalog-body");
  const countEl = $("email-catalog-count");
  if (!body) return;
  if (countEl) countEl.textContent = state.emailCatalog.length;
  body.innerHTML = state.emailCatalog
    .map(
      (t) => `
    <tr>
      <td><code>${esc(t.id)}</code></td>
      <td>${esc(t.name)}</td>
      <td><span class="meta">${esc(t.subject)}</span></td>
      <td><button type="button" class="btn btn-ghost btn-sm em-edit" data-id="${esc(t.id)}">Editar</button></td>
    </tr>`
    )
    .join("");
  body.querySelectorAll(".em-edit").forEach((btn) => {
    btn.addEventListener("click", () => loadEmailTemplateEditor(btn.dataset.id));
  });
}

async function loadEmailTemplateEditor(id) {
  try {
    const t = await api("/api/emails/" + encodeURIComponent(id));
    $("em-tpl-id").value = t.id;
    $("em-tpl-name").value = t.name || "";
    $("em-tpl-subject").value = t.subject || "";
    $("em-tpl-desc").value = t.description || "";
    $("em-tpl-html").value = t.html_body || "";
  } catch (e) {
    banner($("email-catalog-banner"), "live", e.message);
  }
}

async function refreshEmailCatalog() {
  const data = await api("/api/emails");
  state.emailCatalog = data.catalog || [];
  renderEmailCatalogTable();
  document.querySelectorAll(".phase-block.phase-email").forEach((block) => {
    block.querySelectorAll(".em-tpl").forEach((sel) => {
      const cur = sel.value;
      sel.innerHTML = emailTemplateOptions(cur);
    });
  });
}

async function initScenarioTab() {
  try {
    const [events, mitre, emails] = await Promise.all([
      api("/api/events"),
      api("/api/mitre/tactics"),
      api("/api/emails"),
    ]);
    applyEventCatalog(events);
    state.emailCatalog = emails.catalog || [];
    renderEmailCatalogTable();
    mitreTactics = mitre.tactics || [];
    fillMitreAddSelect();
    if (!state.configLoaded) await loadConfig();
    await refreshScenarioCatalog();
    if (!state.scenarioReady) {
      setScenarioMode("load");
      if (scItems.length) {
        await loadScenarioBuilder(scItems[0].id);
      } else {
        setScenarioMode("new");
        newScenario();
      }
    }
    state.scenarioReady = true;
  } catch (e) {
    banner($("sc-banner"), "live", "Error: " + e.message);
  }
}

function newScenario() {
  scLoadedId = null;
  $("sc-name").value = "mi-ejercicio";
  $("sc-desc").value = "";
  $("sc-org").value = "1";
  $("sc-timeline").value = "0";
  $("sc-use-config").checked = true;
  if (state.actorKeys.length) state.actorKeys = state.config?.actor_keys || state.actorKeys;
  scPhases = [phaseFromTactic("TA0001", true)];
  renderAllPhases();
  renderScenarioPreview(null);
  document.querySelectorAll(".scenario-item").forEach((el) => el.classList.remove("active"));
  banner($("sc-banner"), "dry", "Escenario nuevo — edita fases y guarda.");
}

async function loadScenarioBuilder(nameOrId) {
  const name = nameOrId || $("sc-load").value;
  if (!name) {
    banner($("sc-banner"), "dry", "Elige un escenario de la lista.");
    return;
  }
  try {
    const sc = await api("/api/scenarios/" + encodeURIComponent(name) + "/builder");
    scLoadedId = sc.id || name;
    setScenarioMode("load");
    $("sc-name").value = sc.name || name;
    $("sc-desc").value = sc.description || "";
    $("sc-org").value = sc.org_id ?? 1;
    $("sc-timeline").value = sc.timeline_minutes ?? 0;
    $("sc-use-config").checked = !!sc.use_config_actors;
    if (sc.actor_keys?.length) state.actorKeys = sc.actor_keys;
    else if (!sc.use_config_actors && state.config?.actor_keys) state.actorKeys = state.config.actor_keys;
    scPhases = (sc.phases || []).map((p) => {
      const synced = syncPhaseWithMitre({ ...p });
      synced.events = (synced.events || []).map(normalizeScenarioEvent);
      synced.emails = synced.emails || [];
      return synced;
    });
    renderAllPhases();
    const item = scItems.find((it) => it.id === scLoadedId) || {
      id: scLoadedId,
      name: sc.name,
      description: sc.description,
      phases: sc.phases?.length || 0,
      events: sc.phases?.reduce((n, p) => n + (p.events || []).reduce((m, e) => m + (+e.count || 1), 0), 0) || 0,
      timeline_minutes: sc.timeline_minutes,
      file: scLoadedId + ".yml",
    };
    renderScenarioPreview(item);
    renderScenarioList(scItems, scLoadedId);
    fillScenarioSelect(scItems, scLoadedId);
    banner($("sc-banner"), "ok", `Cargado para editar: ${sc.name || name}`);
  } catch (e) {
    banner($("sc-banner"), "live", "Error: " + e.message);
  }
}

$("sc-mode-new").addEventListener("click", () => {
  setScenarioMode("new");
  newScenario();
});
$("sc-mode-load").addEventListener("click", () => {
  setScenarioMode("load");
  if (scItems.length && !scLoadedId) loadScenarioBuilder(scItems[0].id);
  else banner($("sc-banner"), "dry", "Selecciona un escenario de la lista o del desplegable.");
});
$("sc-load").addEventListener("change", () => {
  if ($("sc-load").value) loadScenarioBuilder($("sc-load").value);
});
$("btn-sc-reload").addEventListener("click", async () => {
  try {
    await refreshScenarioCatalog(scLoadedId);
    banner($("sc-banner"), "ok", "Lista actualizada.");
  } catch (e) {
    banner($("sc-banner"), "live", "Error: " + e.message);
  }
});
$("btn-add-phase-mitre").addEventListener("click", () => {
  const tid = $("sc-add-tactic").value;
  if (!tid) return;
  scPhases.push(phaseFromTactic(tid, false));
  renderAllPhases();
  banner($("sc-banner"), "ok", `Fase MITRE añadida: ${phaseSlugFromTacticId(tid)}`);
});

$("btn-add-phase-email").addEventListener("click", () => {
  scPhases.push(phaseFromEmail(`correo_${scPhases.length + 1}`));
  renderAllPhases();
  banner($("sc-banner"), "ok", "Fase correo añadida");
});

$("btn-em-save").addEventListener("click", async () => {
  const payload = {
    id: $("em-tpl-id").value.trim(),
    name: $("em-tpl-name").value.trim(),
    subject: $("em-tpl-subject").value.trim(),
    description: $("em-tpl-desc").value.trim(),
    html_body: $("em-tpl-html").value,
  };
  if (!payload.id) {
    banner($("email-catalog-banner"), "dry", "ID de plantilla requerido");
    return;
  }
  try {
    await api("/api/emails", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    await refreshEmailCatalog();
    banner($("email-catalog-banner"), "ok", `Plantilla guardada: ${payload.id}`);
  } catch (e) {
    banner($("email-catalog-banner"), "live", e.message);
  }
});

$("btn-em-new").addEventListener("click", () => {
  $("em-tpl-id").value = "";
  $("em-tpl-name").value = "";
  $("em-tpl-subject").value = "";
  $("em-tpl-desc").value = "";
  $("em-tpl-html").value = "<!DOCTYPE html>\n<html><body><p>Hola {{user}},</p></body></html>";
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
    scLoadedId = res.name;
    await refreshScenarioCatalog(res.name);
    setScenarioMode("load");
  } catch (e) {
    banner($("sc-banner"), "live", "Error: " + e.message);
  }
});

$("btn-catalog-import").addEventListener("click", async () => {
  const input = $("catalog-events-file");
  const file = input.files && input.files[0];
  if (!file) {
    banner($("catalog-banner"), "dry", "Elige un fichero .yaml con sección events:.");
    return;
  }
  try {
    const text = await file.text();
    const res = await api("/api/events/import", {
      method: "POST",
      headers: { "Content-Type": "text/yaml" },
      body: text,
    });
    applyEventCatalog(res);
    const parts = [];
    if (res.added?.length) parts.push(`${res.added.length} nuevos`);
    if (res.updated?.length) parts.push(`${res.updated.length} actualizados`);
    banner(
      $("catalog-banner"),
      "ok",
      `Importado desde ${file.name}: ${parts.join(", ") || "sin cambios"}. Catálogo: ${res.count} eventos.`
    );
    input.value = "";
  } catch (e) {
    banner($("catalog-banner"), "live", "Error importando: " + e.message);
  }
});

/* ---------- Init ---------- */
initRunTab();
