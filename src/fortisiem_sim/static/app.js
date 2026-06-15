/* FortiSIEM Sim — GUI: Ejecutar · Config · Eventos · Escenario */

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
    if (btn.dataset.tab === "events" && !state.eventsReady) initEventsTab();
    if (btn.dataset.tab === "activity" && !state.activityReady) initActivityTab();
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
  eventsReady: false,
  eventsSelectedId: "",
  activityReady: false,
  activityChains: [],
  activitySelectedId: "",
  activityIsNew: false,
  mitreTactics: [],
  emailCatalog: [],
  runPhaseNames: [],
  runPhasesMeta: [],
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

function phaseRunLabel(name) {
  const ph = state.runPhasesMeta.find((p) => p.name === name);
  return ph?.display_label || ph?.label || name;
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
  const current = phaseRunLabel(seq.names[seq.index]);
  const remaining = seq.names.length - seq.index - 1;
  if (remaining > 0) {
    setRunning(false);
    setWaitingContinue(true);
    banner(
      $("run-banner"),
      msg.live ? "live" : "dry",
      `Fase ${current} completada. Quedan ${remaining}. Pulsa Continuar ▶`
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
  state.runPhasesMeta = sc.phases || [];
  state.runPhaseNames = state.runPhasesMeta.map((p) => p.name);
  $("run-phase").innerHTML =
    '<option value="">(todas)</option>' +
    state.runPhasesMeta
      .map(
        (p) =>
          `<option value="${esc(p.name)}">${esc(p.display_label || p.label || p.name)} (~${p.total})</option>`
      )
      .join("");
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
  const label = phaseName ? phaseRunLabel(phaseName) : isAllPhasesRun() ? "(todas)" : phaseRunLabel($("run-phase").value);
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
      (u, i) => {
        const label = typeof u === "object" ? `${esc(u.username || u.samaccountname || "")} · ${esc(u.email || "")}` : esc(u);
        return `<span class="chip">${label}<button type="button" data-i="${i}" class="rm-user" title="Quitar">×</button></span>`;
      }
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
  $("cfg-c2-domains").value = arrToLines(c2.domains || c2.uris);
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
    const storage = await api("/api/storage");
    $("storage-badge").textContent = (storage.backend || "yaml").toUpperCase();
    const data = await api("/api/config");
    fillConfigUI(data);
    const st = data.stats || {};
    if (st.event_templates) {
      $("sql-stats").textContent = `${st.event_templates} evt · ${st.vpn_templates || 0} VPN · ${st.malware_samples || 0} malware`;
    }
    state.configLoaded = true;
  } catch (e) {
    banner($("config-banner"), "live", "Error cargando config: " + e.message);
  }
}

function collectConfig() {
  const users = [];
  $("cfg-users").querySelectorAll(".chip").forEach((c) => {
    const t = c.textContent.replace("×", "").trim();
    const parts = t.split(" · ");
    if (parts.length >= 2) users.push({ username: parts[0], email: parts.slice(1).join(" · ") });
    else users.push({ username: t, email: `${t}@age.local` });
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
      domains: linesToArr($("cfg-c2-domains")),
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
  $("cfg-users").querySelectorAll(".chip").forEach((c) => {
    const t = c.textContent.replace("×", "").trim();
    const parts = t.split(" · ");
    if (parts.length >= 2) users.push({ username: parts[0], email: parts.slice(1).join(" · ") });
    else users.push({ username: t, email: `${t}@age.local` });
  });
  const emailGuess = v.includes("@") ? v : `${v}@age.local`;
  const username = v.includes("@") ? v.split("@")[0] : v;
  if (!users.some((u) => u.username === username)) users.push({ username, email: emailGuess });
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
let scenarioCatalogView = null;
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
    id: ev.id || "",
    chain_id: ev.chain_id || "",
    count: ev.count ?? 1,
    actor: ev.actor || "",
    sort_order: ev.sort_order,
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
  if (ph.phase_type === "email" || ph.phase_type === "chain") return ph;
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
    if (ev.chain_id) {
      steps.push({
        type: "chain",
        sort_order: ev.sort_order ?? i,
        data: normalizeScenarioEvent(ev),
      });
    } else {
      steps.push({
        type: "event",
        sort_order: ev.sort_order ?? i,
        data: normalizeScenarioEvent(ev),
      });
    }
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

function scenarioStepCount(phases) {
  let n = 0;
  (phases || []).forEach((ph) => {
    if (ph.phase_type === "email") {
      n += (ph.emails || []).length;
      return;
    }
    if (ph.phase_type === "chain") {
      (ph.chains || ph.events || []).forEach((ch) => {
        const cid = ch.chain_id || "";
        const chain = state.activityChains.find((c) => c.id === cid);
        n += chain?.step_count || 1;
      });
      return;
    }
    (ph.events || []).forEach((ev) => {
      if (ev.chain_id) {
        const chain = state.activityChains.find((c) => c.id === ev.chain_id);
        n += chain?.step_count || 1;
      } else {
        n += +ev.count || 1;
      }
    });
    n += (ph.emails || []).length;
  });
  return n;
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

function phaseEventOptionIds(tacticId, selected, extraIds = []) {
  const ids = new Set(allowedEventIds(tacticId));
  (extraIds || []).forEach((id) => {
    if (id) ids.add(id);
  });
  if (selected) ids.add(selected);
  return [...ids];
}

function eventOptions(selected, tacticId, extraIds) {
  return eventOptionsGrouped(selected, tacticId, extraIds);
}

function eventOptionsGrouped(selected, tacticId, extraIds = []) {
  if (!tacticId) {
    return `<option value="">— elige táctica MITRE primero —</option>`;
  }
  const allowed = new Set(allowedEventIds(tacticId));
  const ids = phaseEventOptionIds(tacticId, selected, extraIds);
  if (!ids.length) {
    return `<option value="">— sin eventos para ${esc(tacticId)} —</option>`;
  }
  const groups = {};
  const catalogOnly = [];
  ids.forEach((id) => {
    if (!allowed.has(id)) {
      catalogOnly.push(id);
      return;
    }
    const entry = getCatalogEntry(id);
    const key = entry ? `${entry.system || "other"}/${entry.category || "generic"}` : "other";
    (groups[key] = groups[key] || []).push(id);
  });
  const renderOpt = (id) => {
    const entry = getCatalogEntry(id);
    const fmt = entry?.format === "fortigate" ? "FG" : entry?.system?.slice(0, 3)?.toUpperCase() || "";
    const label = entry ? `${fmt} · ${entry.name} (${id})` : id;
    return `<option value="${esc(id)}"${id === selected ? " selected" : ""}>${esc(label)}</option>`;
  };
  let html = Object.keys(groups)
    .sort()
    .map((key) => {
      const opts = groups[key].map(renderOpt).join("");
      return `<optgroup label="${esc(key)}">${opts}</optgroup>`;
    })
    .join("");
  if (catalogOnly.length) {
    html += `<optgroup label="catálogo (otra táctica)">${catalogOnly.map(renderOpt).join("")}</optgroup>`;
  }
  return html;
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
  const rowIds = [...block.querySelectorAll(".steps-wrap > .event-row .ev-id")]
    .map((s) => s.value)
    .filter(Boolean);
  block.querySelectorAll(".steps-wrap > .event-row").forEach((row) => {
    const sel = row.querySelector(".ev-id");
    const cur = sel.value;
    sel.innerHTML = eventOptions(cur, tid, rowIds);
    const willReset = !!(tid && cur && !allowed.has(cur) && !getCatalogEntry(cur));
    if (willReset) {
      sel.value = firstAllowedEventId(tid);
    } else if (cur) {
      sel.value = cur;
    }
    updateEventRowTtp(row, sel.value);
  });
  updatePhaseEventHint(block);
  const kindSel = block.querySelector(".ph-add-step-kind");
  const addBtn = block.querySelector(".ph-add-step");
  const eventOpt = kindSel?.querySelector('option[value="event"]');
  if (eventOpt) eventOpt.disabled = !tid || !allowed.size;
  if (addBtn) addBtn.disabled = !tid;
}

function updateEventRowTtp(row, eventId) {
  const el = row.querySelector(".ev-ttp");
  if (!el) return;
  const entry = getCatalogEntry(eventId);
  el.textContent = entry
    ? `${entry.format || entry.system} · ${entry.category || ""} · ${entry.action || ""} · ${entry.tactics.join(" · ")} — ${entry.techniques.join(", ")}`
    : "";
}

function applyEventCatalog(events) {
  state.eventIds = events.ids || [];
  state.eventCatalog = events.catalog || [];
  state.eventsByTactic = events.by_tactic || {};
  state.fortigatePlaceholders = events.fortigate_placeholders || [];
  scenarioCatalogView = null;
  const ph = $("fortigate-placeholders-list");
  if (ph && state.fortigatePlaceholders.length) ph.textContent = state.fortigatePlaceholders.join(", ");
  fillCatalogCategoryFilter();
  renderEventCatalogTable();
  fillCatalogTargetPhaseSelect();
  document.querySelectorAll(".phase-block").forEach((block) => refreshPhaseEventSelects(block));
}

function scenarioCatalogList() {
  return scenarioCatalogView !== null ? scenarioCatalogView : state.eventCatalog;
}

function fillCatalogCategoryFilter() {
  const sel = $("catalog-filter-category");
  if (!sel) return;
  const cur = sel.value;
  const cats = [...new Set((state.eventCatalog || []).map((e) => e.category).filter(Boolean))].sort();
  sel.innerHTML =
    '<option value="">Todas</option>' +
    cats.map((c) => `<option value="${esc(c)}">${esc(c)}</option>`).join("");
  if (cur && cats.includes(cur)) sel.value = cur;
}

function fillCatalogTargetPhaseSelect() {
  const sel = $("catalog-target-phase");
  if (!sel) return;
  const cur = sel.value;
  const options = [];
  scPhases.forEach((ph, i) => {
    if (ph.phase_type && ph.phase_type !== "mitre") return;
    const tactic = ph.mitre_tactic ? getTacticById(ph.mitre_tactic) : null;
    const label = tactic
      ? `${tactic.slug} · ${tactic.id}`
      : ph.name || `fase_${i + 1}`;
    options.push(`<option value="${i}">${esc(label)}</option>`);
  });
  if (!options.length) {
    sel.innerHTML = '<option value="">— crea una fase MITRE primero —</option>';
    return;
  }
  sel.innerHTML = options.join("");
  if (cur && scPhases[parseInt(cur, 10)]?.phase_type !== "email" && scPhases[parseInt(cur, 10)]?.phase_type !== "chain") {
    sel.value = cur;
  }
}

function addCatalogEventToPhase(eventId, phaseIndex) {
  const pi =
    phaseIndex !== undefined && phaseIndex !== null
      ? phaseIndex
      : parseInt($("catalog-target-phase")?.value, 10);
  if (Number.isNaN(pi) || !scPhases[pi]) {
    banner($("catalog-banner"), "dry", "Crea y selecciona una fase MITRE destino arriba del catálogo.");
    return false;
  }
  const ph = scPhases[pi];
  if (ph.phase_type && ph.phase_type !== "mitre") {
    banner($("catalog-banner"), "dry", "Solo se pueden añadir eventos a fases MITRE.");
    return false;
  }
  const entry = getCatalogEntry(eventId);
  if (!entry) {
    banner($("catalog-banner"), "dry", `Evento no encontrado: ${eventId}`);
    return false;
  }
  if (!ph.events) ph.events = [];
  const order = (ph.events?.length || 0) + (ph.emails?.length || 0);
  ph.events.push(
    normalizeScenarioEvent({ id: eventId, count: 1, actor: "", sort_order: order })
  );
  renderAllPhases();
  const tactic = ph.mitre_tactic ? getTacticById(ph.mitre_tactic) : null;
  const phaseLabel = tactic ? tactic.slug : ph.name || `fase ${pi + 1}`;
  banner($("catalog-banner"), "ok", `Añadido «${entry.name}» (${eventId}) → ${phaseLabel}`);
  const block = $("sc-phases")?.querySelector(`.phase-block[data-pi="${pi}"]`);
  block?.scrollIntoView({ behavior: "smooth", block: "nearest" });
  return true;
}

function applyScenarioCatalogFilter() {
  const source = ($("catalog-filter-system")?.value || "").toLowerCase();
  const category = ($("catalog-filter-category")?.value || "").toLowerCase();
  if (!source && !category) {
    scenarioCatalogView = null;
  } else {
    scenarioCatalogView = (state.eventCatalog || []).filter((e) => {
      if (source && (e.system || "").toLowerCase() !== source) return false;
      if (category && (e.category || "").toLowerCase() !== category) return false;
      return true;
    });
  }
  renderEventCatalogTable();
  const n = scenarioCatalogList().length;
  banner($("catalog-banner"), n ? "ok" : "dry", n ? `${n} evento(s) en vista` : "Ningún evento coincide con el filtro");
}

function addAllFilteredCatalogEvents() {
  const list = scenarioCatalogList();
  if (!list.length) {
    banner($("catalog-banner"), "dry", "No hay eventos filtrados para añadir.");
    return;
  }
  const pi = parseInt($("catalog-target-phase")?.value, 10);
  if (Number.isNaN(pi) || !scPhases[pi]) {
    banner($("catalog-banner"), "dry", "Selecciona una fase MITRE destino.");
    return;
  }
  const ph = scPhases[pi];
  if (ph.phase_type && ph.phase_type !== "mitre") {
    banner($("catalog-banner"), "dry", "Solo se pueden añadir eventos a fases MITRE.");
    return;
  }
  if (!ph.events) ph.events = [];
  let order = (ph.events?.length || 0) + (ph.emails?.length || 0);
  list.forEach((e) => {
    ph.events.push(
      normalizeScenarioEvent({ id: e.id, count: 1, actor: "", sort_order: order++ })
    );
  });
  renderAllPhases();
  const tactic = ph.mitre_tactic ? getTacticById(ph.mitre_tactic) : null;
  const phaseLabel = tactic ? tactic.slug : ph.name || `fase ${pi + 1}`;
  banner($("catalog-banner"), "ok", `${list.length} evento(s) añadidos → ${phaseLabel}`);
  $("sc-phases")?.querySelector(`.phase-block[data-pi="${pi}"]`)?.scrollIntoView({ behavior: "smooth", block: "nearest" });
}

async function refreshEventCatalog() {
  return applyEventCatalog(await api("/api/events"));
}

function renderEventCatalogTableFiltered(catalog) {
  const body = $("event-catalog-body");
  const countEl = $("catalog-count");
  if (!body) return;
  const list = catalog || scenarioCatalogList();
  if (countEl) countEl.textContent = list.length;
  if (!list.length) {
    body.innerHTML = '<tr><td colspan="9" class="meta">Sin eventos que coincidan con el filtro.</td></tr>';
    return;
  }
  body.innerHTML = list
    .map(
      (e) => `
    <tr class="catalog-ev-row" data-event-id="${esc(e.id)}">
      <td><code>${esc(e.id)}</code></td>
      <td>${esc(e.name)}</td>
      <td><span class="pill">${esc(e.format || "—")}</span></td>
      <td><span class="pill pill-system">${esc(e.system || "—")}</span></td>
      <td>${esc(e.category || "—")}</td>
      <td>${esc(e.action || "—")}</td>
      <td>${(e.tactics || []).map((t) => `<span class="pill">${esc(t)}</span>`).join(" ")}</td>
      <td><span class="meta">${esc((e.techniques || []).join(", "))}</span></td>
      <td><button type="button" class="btn btn-primary btn-sm catalog-add-ev" data-id="${esc(e.id)}">+ Añadir</button></td>
    </tr>`
    )
    .join("");
  body.querySelectorAll(".catalog-add-ev").forEach((btn) => {
    btn.addEventListener("click", (ev) => {
      ev.stopPropagation();
      addCatalogEventToPhase(btn.dataset.id);
    });
  });
  body.querySelectorAll("tr.catalog-ev-row").forEach((row) => {
    row.addEventListener("dblclick", () => addCatalogEventToPhase(row.dataset.eventId));
  });
}

function renderEventCatalogTable() {
  renderEventCatalogTableFiltered(scenarioCatalogList());
}

/* ========== EVENTOS (pestaña dedicada) ========== */
function eventsFilteredList() {
  const q = ($("events-search")?.value || "").trim().toLowerCase();
  const source = ($("events-filter-system")?.value || "").toLowerCase();
  const category = ($("events-filter-category")?.value || "").toLowerCase();
  const tactic = ($("events-filter-tactic")?.value || "").toUpperCase();
  return state.eventCatalog.filter((e) => {
    if (source && (e.system || "").toLowerCase() !== source) return false;
    if (category && (e.category || "").toLowerCase() !== category) return false;
    if (tactic && !(e.tactics || []).includes(tactic)) return false;
    if (!q) return true;
    const hay = [
      e.id,
      e.name,
      e.format,
      e.system,
      e.category,
      e.action,
      e.ttp_slug,
      (e.tactics || []).join(" "),
      (e.techniques || []).join(" "),
    ]
      .join(" ")
      .toLowerCase();
    return hay.includes(q);
  });
}

function renderEventsList() {
  const list = eventsFilteredList();
  const host = $("events-list");
  const countEl = $("events-count");
  if (!host) return;
  if (countEl) countEl.textContent = list.length;
  if (!list.length) {
    host.innerHTML = '<p class="meta">Sin eventos que coincidan con el filtro.</p>';
    return;
  }
  host.innerHTML = list
    .map((e) => {
      const active = e.id === state.eventsSelectedId ? " active" : "";
      const tactics = (e.tactics || [])
        .map((t) => `<span class="pill">${esc(t)}</span>`)
        .join(" ");
      const techs = esc((e.techniques || []).slice(0, 4).join(", "));
      return `<button type="button" class="event-list-item${active}" data-event-id="${esc(e.id)}">
        <div class="eli-id">${esc(e.id)}</div>
        <div class="eli-name">${esc(e.name)}</div>
        <div class="eli-meta">${esc(e.system || "—")} · ${esc(e.category || "—")} · ${esc(e.format || "")}</div>
        <div class="eli-meta">${tactics} <span class="meta">${techs}</span></div>
      </button>`;
    })
    .join("");
  host.querySelectorAll(".event-list-item").forEach((btn) => {
    btn.addEventListener("click", () => loadEventEditor(btn.dataset.eventId));
  });
}

function renderTacticsGrid(selected) {
  const grid = $("ev-tactics-grid");
  if (!grid) return;
  const sel = new Set(selected || []);
  grid.innerHTML = state.mitreTactics
    .map(
      (t) => `<label class="tactic-check">
        <input type="checkbox" class="ev-tactic-cb" value="${esc(t.id)}"${sel.has(t.id) ? " checked" : ""}>
        <span><span class="tc-id">${esc(t.id)}</span> ${esc(t.name)}<br><span class="meta">${esc(t.slug)}</span></span>
      </label>`
    )
    .join("");
}

function updateMitrePreview() {
  const el = $("ev-mitre-preview");
  if (!el) return;
  const tactics = [...document.querySelectorAll(".ev-tactic-cb:checked")].map((c) => c.value);
  const techniques = parseTechniquesInput($("ev-techniques")?.value || "");
  const ttp = ($("ev-ttp")?.value || "").trim();
  const tacticNames = tactics.map((id) => {
    const t = state.mitreTactics.find((x) => x.id === id);
    return t ? `${id} ${t.name}` : id;
  });
  el.innerHTML = `
    <strong>Tácticas:</strong> ${tacticNames.length ? esc(tacticNames.join(" · ")) : "—"}<br>
    <strong>Técnicas:</strong> ${techniques.length ? esc(techniques.join(", ")) : "—"}<br>
    <strong>TTP slug:</strong> ${ttp ? esc(ttp) : "—"}`;
}

function parseTechniquesInput(text) {
  return String(text || "")
    .split(/[\n,]+/)
    .map((s) => s.trim())
    .filter(Boolean);
}

function techniquesToText(list) {
  return (list || []).join(", ");
}

function fillEventEditor(ev) {
  $("events-editor").style.display = "block";
  $("events-detail-title").textContent = ev.id;
  $("events-detail-meta").textContent = ev.is_builtin
    ? `Builtin · actualizado ${ev.updated_at || "—"}`
    : `Custom · actualizado ${ev.updated_at || "—"}`;
  $("ev-id").readOnly = true;
  $("ev-id").value = ev.id;
  $("ev-name").value = ev.name || "";
  $("ev-format").value = ev.format || "syslog_generic";
  $("ev-source").value = ev.source_system || ev.system || "";
  $("ev-category").value = ev.category || "";
  $("ev-severity").value = ev.severity || "";
  $("ev-action").value = ev.action || "";
  $("ev-weight").value = ev.weight ?? 5;
  $("ev-group").value = ev.event_group || "";
  $("ev-ttp").value = ev.ttp || ev.ttp_slug || "";
  $("ev-pri").value = ev.pri ?? 134;
  $("ev-syslog-host").value = ev.syslog_hostname || "";
  $("ev-tags").value = (ev.tags || []).join(", ");
  $("ev-body").value = ev.body || "";
  $("ev-techniques").value = techniquesToText(ev.techniques);
  renderTacticsGrid(ev.tactics || []);
  $("btn-ev-delete").style.display = ev.is_builtin ? "none" : "inline-block";
  updateMitrePreview();
}

function clearEventEditorNew() {
  state.eventsSelectedId = "";
  $("events-editor").style.display = "block";
  $("events-detail-title").textContent = "Nuevo evento";
  $("events-detail-meta").textContent = "Define un ID único y guarda para crear en SQLite.";
  $("ev-id").readOnly = false;
  $("ev-id").value = "";
  $("ev-name").value = "";
  $("ev-format").value = "fortigate";
  $("ev-source").value = "fortigate";
  $("ev-category").value = "vpn";
  $("ev-severity").value = "notice";
  $("ev-action").value = "login";
  $("ev-weight").value = 5;
  $("ev-group").value = "";
  $("ev-ttp").value = "initial-access";
  $("ev-pri").value = 189;
  $("ev-syslog-host").value = "{{devname}}";
  $("ev-tags").value = "fortigate,vpn";
  $("ev-body").value =
    'date={{date}} time={{time}} devname="{{devname}}" devid="{{devserial}}" type="event" subtype="vpn" user="{{user}}" remip={{remote_access_ip}} action="login" simulated=true';
  $("ev-techniques").value = "T1078, T1133";
  renderTacticsGrid(["TA0001"]);
  $("btn-ev-delete").style.display = "none";
  updateMitrePreview();
  renderEventsList();
}

async function loadEventEditor(eventId) {
  try {
    const ev = await api("/api/events/" + encodeURIComponent(eventId));
    state.eventsSelectedId = eventId;
    fillEventEditor(ev);
    renderEventsList();
  } catch (e) {
    banner($("events-banner"), "live", e.message);
  }
}

function collectEventPayload() {
  const tactics = [...document.querySelectorAll(".ev-tactic-cb:checked")].map((c) => c.value);
  return {
    id: $("ev-id").value.trim(),
    name: $("ev-name").value.trim(),
    format: $("ev-format").value,
    source_system: $("ev-source").value.trim(),
    category: $("ev-category").value.trim(),
    severity: $("ev-severity").value.trim(),
    action: $("ev-action").value.trim(),
    weight: parseInt($("ev-weight").value, 10) || 5,
    event_group: $("ev-group").value.trim(),
    ttp: $("ev-ttp").value.trim(),
    pri: parseInt($("ev-pri").value, 10) || 134,
    syslog_hostname: $("ev-syslog-host").value.trim(),
    tags: $("ev-tags")
      .value.split(",")
      .map((s) => s.trim())
      .filter(Boolean),
    body: $("ev-body").value,
    tactics,
    techniques: parseTechniquesInput($("ev-techniques").value),
  };
}

async function saveEventEditor() {
  const payload = collectEventPayload();
  const isNew = !$("ev-id").readOnly && !state.eventsSelectedId;
  if (!payload.id) {
    banner($("events-banner"), "dry", "ID requerido");
    return;
  }
  if (!payload.name || !payload.body.trim()) {
    banner($("events-banner"), "dry", "Nombre y plantilla (body) son obligatorios");
    return;
  }
  try {
    let res;
    if (isNew) {
      res = await api("/api/events", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      state.eventsSelectedId = payload.id;
      $("ev-id").readOnly = true;
    } else {
      res = await api("/api/events/" + encodeURIComponent(payload.id), {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
    }
    applyEventCatalog(res);
    fillEventEditor(res.event);
    renderEventsList();
    banner($("events-banner"), "ok", `Guardado: ${payload.id}`);
  } catch (e) {
    banner($("events-banner"), "live", e.message);
  }
}

async function deleteEventEditor() {
  const id = $("ev-id").value.trim();
  if (!id || !confirm(`¿Eliminar evento ${id}?`)) return;
  try {
    const res = await api("/api/events/" + encodeURIComponent(id), { method: "DELETE" });
    applyEventCatalog(res);
    state.eventsSelectedId = "";
    $("events-editor").style.display = "none";
    $("events-detail-title").textContent = "Detalle del evento";
    $("events-detail-meta").textContent = "Evento eliminado. Selecciona otro de la lista.";
    renderEventsList();
    banner($("events-banner"), "ok", `Eliminado: ${id}`);
  } catch (e) {
    banner($("events-banner"), "live", e.message);
  }
}

function cloneEventEditor() {
  const src = $("ev-id").value.trim();
  if (!src) return;
  clearEventEditorNew();
  $("ev-id").value = src + "_copy";
  $("ev-name").value = ($("ev-name").value || src) + " (copia)";
  $("ev-body").value = $("ev-body").value;
  banner($("events-banner"), "dry", "Duplicado como borrador — ajusta el ID y guarda.");
}

async function refreshEventsTab() {
  const qs = new URLSearchParams();
  const source = $("events-filter-system")?.value;
  const category = $("events-filter-category")?.value;
  if (source) qs.set("source", source);
  if (category) qs.set("category", category);
  const url = qs.toString() ? "/api/events?" + qs.toString() : "/api/events";
  applyEventCatalog(await api(url));
  renderEventsList();
  if (state.eventsSelectedId) {
    try {
      fillEventEditor(await api("/api/events/" + encodeURIComponent(state.eventsSelectedId)));
    } catch (_) {
      state.eventsSelectedId = "";
    }
  }
}

/* ========== CADENAS LINUX (editor) ========== */
function actLegitimacyLabel(raw) {
  const v = (raw || "").toLowerCase();
  if (v === "mixed") return "Mixta";
  if (v === "illegitimate") return "Ilegítima";
  return "Legítima";
}

function actLegitimacyBadge(raw) {
  const v = (raw || "").toLowerCase();
  if (v === "mixed") return "mixed-badge";
  if (v === "illegitimate") return "illegit-badge";
  return "legit-badge";
}

function actEffectiveLegitimacy(chain) {
  return (chain.effective_legitimacy || chain.legitimacy || "legitimate").toLowerCase();
}

function linuxEventCatalog() {
  return (state.eventCatalog || []).filter((e) => {
    const src = (e.source_system || e.system || "").toLowerCase();
    const id = (e.id || "").toLowerCase();
    return src === "linux" || id.startsWith("linux_");
  });
}

function actEventOptionsHtml(selected) {
  const events = linuxEventCatalog();
  if (!events.length) {
    return '<option value="">(sin eventos Linux — abre pestaña Eventos)</option>';
  }
  return events
    .map(
      (e) =>
        `<option value="${esc(e.id)}"${e.id === selected ? " selected" : ""}>${esc(e.id)} — ${esc(e.name || "")}</option>`
    )
    .join("");
}

function actCategoryOptions(selected, forEditor) {
  const cats = [...new Set((state.activityChains || []).map((c) => c.category).filter(Boolean))].sort();
  const sel = (selected || "").trim();
  if (sel && !cats.includes(sel)) cats.push(sel);
  cats.sort();
  const empty = forEditor
    ? '<option value="">— sin categoría —</option>'
    : '<option value="">Todas las categorías</option>';
  return (
    empty +
    cats.map((c) => `<option value="${esc(c)}"${c === sel ? " selected" : ""}>${esc(c)}</option>`).join("")
  );
}

function fillActCategoryFilter() {
  const sel = $("act-filter-category");
  if (!sel) return;
  const cur = sel.value;
  sel.innerHTML = actCategoryOptions(cur, false);
  if (cur) sel.value = cur;
}

function fillActCategoryEditor(selected) {
  const sel = $("act-category");
  if (!sel) return;
  sel.innerHTML = actCategoryOptions(selected, true);
}

function actFilteredList() {
  const q = ($("act-search")?.value || "").trim().toLowerCase();
  const leg = ($("act-filter-legit")?.value || "").toLowerCase();
  const cat = ($("act-filter-category")?.value || "").trim();
  return (state.activityChains || []).filter((c) => {
    if (leg && actEffectiveLegitimacy(c) !== leg) return false;
    if (cat && (c.category || "") !== cat) return false;
    if (!q) return true;
    const hay = [c.id, c.name, c.category, c.description, c.objective].join(" ").toLowerCase();
    return hay.includes(q);
  });
}

function actListItemHtml(c) {
  const active = c.id === state.activitySelectedId ? " active" : "";
  const eff = actEffectiveLegitimacy(c);
  const pill = actLegitimacyBadge(eff);
  const tag = actLegitimacyLabel(eff);
  return `<button type="button" class="event-list-item${active}" data-act-id="${esc(c.id)}">
    <span class="${pill}">${tag}</span>
    <div class="eli-name">${esc(c.name)}</div>
    <div class="eli-meta"><code>${esc(c.id)}</code> · ${esc(c.category || "—")} · ${c.step_count || 0} logs</div>
  </button>`;
}

function renderActList() {
  const list = actFilteredList();
  const host = $("act-list");
  if (!host) return;
  $("act-count").textContent = list.length;
  const stats = state.activityStats || {};
  $("act-stats").textContent =
    `Total: ${stats.chains || 0} · ${stats.legitimate || 0} legítimas · ${stats.illegitimate || 0} ilegítimas · ${stats.mixed || 0} mixtas · ${stats.steps || 0} logs`;
  if (!list.length) {
    host.innerHTML = '<p class="meta">Sin cadenas. Importa YAML o crea una cadena mixta.</p>';
    return;
  }
  const legFilter = ($("act-filter-legit")?.value || "").toLowerCase();
  if (legFilter) {
    host.innerHTML = list.map(actListItemHtml).join("");
  } else {
    const groups = [
      { key: "legitimate", title: "Legítimas" },
      { key: "illegitimate", title: "Ilegítimas" },
      { key: "mixed", title: "Mixtas" },
    ];
    const buckets = { legitimate: [], illegitimate: [], mixed: [] };
    list.forEach((c) => buckets[actEffectiveLegitimacy(c)]?.push(c));
    host.innerHTML = groups
      .filter((g) => buckets[g.key].length)
      .map(
        (g) =>
          `<div class="act-group-title">${g.title} (${buckets[g.key].length})</div>` +
          buckets[g.key].map(actListItemHtml).join("")
      )
      .join("");
  }
  host.querySelectorAll("[data-act-id]").forEach((btn) => {
    btn.addEventListener("click", () => loadActivityDetail(btn.dataset.actId));
  });
}

function renderActLogsEditor(logs) {
  const host = $("act-logs-editor");
  if (!host) return;
  const items = (logs || []).length ? logs : [];
  if (!items.length) {
    host.innerHTML = '<p class="meta">Sin logs. Pulsa «+ Log» para añadir pasos editables.</p>';
    return;
  }
  host.innerHTML = items
    .map((log, idx) => {
      const leg = (log.legitimacy || "legitimate").toLowerCase();
      const legitSel = leg === "illegitimate" ? "illegitimate" : "legitimate";
      return `<div class="chain-log-edit" data-log-idx="${idx}">
        <div class="row">
          <div><label># orden</label><input type="number" class="act-log-order" min="1" value="${log.sort_order ?? idx + 1}"></div>
          <div><label>Legitimidad log</label>
            <select class="act-log-legit">
              <option value="legitimate"${legitSel === "legitimate" ? " selected" : ""}>Legítimo</option>
              <option value="illegitimate"${legitSel === "illegitimate" ? " selected" : ""}>Ilegítimo</option>
            </select>
          </div>
          <div><label>&nbsp;</label><button type="button" class="btn btn-ghost btn-sm act-log-del">Quitar</button></div>
        </div>
        <label>Evento Linux</label>
        <select class="act-log-event">${actEventOptionsHtml(log.event_id || "")}</select>
        <label>Comando simulado</label>
        <input type="text" class="act-log-cmd" value="${esc(log.command_line || "")}" placeholder="ej. ls -la /var/log">
        <div class="row">
          <div><label>Delay min (ms)</label><input type="number" class="act-log-min" min="0" value="${log.min_delay_ms ?? 0}"></div>
          <div><label>Delay max (ms)</label><input type="number" class="act-log-max" min="0" value="${log.max_delay_ms ?? 0}"></div>
          <div style="align-self:end;padding-top:18px"><label><input type="checkbox" class="act-log-opt"${log.optional ? " checked" : ""}> Opcional</label></div>
        </div>
      </div>`;
    })
    .join("");
  host.querySelectorAll(".act-log-del").forEach((btn) => {
    btn.addEventListener("click", () => {
      btn.closest(".chain-log-edit")?.remove();
      if (!host.querySelector(".chain-log-edit")) {
        host.innerHTML = '<p class="meta">Sin logs. Pulsa «+ Log» para añadir pasos editables.</p>';
      }
    });
  });
}

function collectActLogsFromEditor() {
  const rows = [...document.querySelectorAll("#act-logs-editor .chain-log-edit")];
  return rows
    .map((row, i) => ({
      sort_order: parseInt(row.querySelector(".act-log-order")?.value, 10) || i + 1,
      event_id: row.querySelector(".act-log-event")?.value || "",
      command_line: (row.querySelector(".act-log-cmd")?.value || "").trim(),
      min_delay_ms: parseInt(row.querySelector(".act-log-min")?.value, 10) || 0,
      max_delay_ms: parseInt(row.querySelector(".act-log-max")?.value, 10) || 0,
      optional: !!row.querySelector(".act-log-opt")?.checked,
      legitimacy: row.querySelector(".act-log-legit")?.value || "legitimate",
    }))
    .filter((l) => l.event_id);
}

function fillActivityEditor(detail) {
  const eff = detail.effective_legitimacy || detail.legitimacy || "legitimate";
  $("act-detail").style.display = "block";
  $("act-detail-title").textContent = detail.name || detail.id;
  $("act-detail-meta").textContent = `${actLegitimacyLabel(eff)} · ${detail.category || "—"} · ${(detail.logs || detail.steps)?.length || 0} logs editables`;
  $("act-id").value = detail.id;
  $("act-name").value = detail.name || "";
  $("act-legitimacy").value =
    detail.legitimacy === "mixed" || eff === "mixed"
      ? "mixed"
      : eff === "illegitimate"
        ? "illegitimate"
        : "legitimate";
  fillActCategoryEditor(detail.category || "");
  $("act-severity").value = detail.severity || "info";
  $("act-objective").value = detail.objective || detail.description || "";
  renderActLogsEditor(detail.logs || detail.steps || []);
}

async function loadActivityDetail(chainId) {
  state.activitySelectedId = chainId;
  state.activityIsNew = false;
  renderActList();
  try {
    const detail = await api("/api/chains/" + encodeURIComponent(chainId));
    $("act-id").readOnly = true;
    fillActivityEditor(detail);
  } catch (e) {
    banner($("act-banner"), "live", "Error: " + e.message);
  }
}

function newMixedChain() {
  state.activitySelectedId = "";
  state.activityIsNew = true;
  const id = "chain_mixed_" + Date.now().toString(36);
  $("act-id").readOnly = false;
  fillActivityEditor({
    id,
    name: "Cadena mixta nueva",
    legitimacy: "mixed",
    effective_legitimacy: "mixed",
    category: "mixed",
    severity: "info",
    objective: "",
    logs: [],
  });
  $("act-detail-title").textContent = "Nueva cadena";
  $("act-detail-meta").textContent = "Combina logs legítimos e ilegítimos y guarda.";
  renderActList();
}

function addActLogRow() {
  const host = $("act-logs-editor");
  if (!host) return;
  if (host.querySelector("p.meta") && !host.querySelector(".chain-log-edit")) {
    host.innerHTML = "";
  }
  const n = host.querySelectorAll(".chain-log-edit").length;
  const defaultEvent = linuxEventCatalog()[0]?.id || "";
  const row = document.createElement("div");
  row.innerHTML = `<div class="chain-log-edit" data-log-idx="${n}">
    <div class="row">
      <div><label># orden</label><input type="number" class="act-log-order" min="1" value="${n + 1}"></div>
      <div><label>Legitimidad log</label>
        <select class="act-log-legit">
          <option value="legitimate">Legítimo</option>
          <option value="illegitimate">Ilegítimo</option>
        </select>
      </div>
      <div><label>&nbsp;</label><button type="button" class="btn btn-ghost btn-sm act-log-del">Quitar</button></div>
    </div>
    <label>Evento Linux</label>
    <select class="act-log-event">${actEventOptionsHtml(defaultEvent)}</select>
    <label>Comando simulado</label>
    <input type="text" class="act-log-cmd" value="" placeholder="ej. whoami">
    <div class="row">
      <div><label>Delay min (ms)</label><input type="number" class="act-log-min" min="0" value="500"></div>
      <div><label>Delay max (ms)</label><input type="number" class="act-log-max" min="0" value="1500"></div>
      <div style="align-self:end;padding-top:18px"><label><input type="checkbox" class="act-log-opt"> Opcional</label></div>
    </div>
  </div>`;
  const block = row.firstElementChild;
  block.querySelector(".act-log-del").addEventListener("click", () => {
    block.remove();
    if (!host.querySelector(".chain-log-edit")) {
      host.innerHTML = '<p class="meta">Sin logs. Pulsa «+ Log» para añadir pasos editables.</p>';
    }
  });
  host.appendChild(block);
}

function collectActChainPayload() {
  return {
    id: ($("act-id")?.value || "").trim(),
    name: ($("act-name")?.value || "").trim(),
    legitimacy: $("act-legitimacy")?.value || "legitimate",
    category: ($("act-category")?.value || "").trim(),
    severity: ($("act-severity")?.value || "info").trim(),
    objective: ($("act-objective")?.value || "").trim(),
    logs: collectActLogsFromEditor(),
  };
}

async function saveActChain() {
  const payload = collectActChainPayload();
  if (!payload.id) {
    banner($("act-banner"), "dry", "ID de cadena requerido");
    return;
  }
  if (!payload.name) {
    banner($("act-banner"), "dry", "Nombre requerido");
    return;
  }
  if (!payload.logs.length) {
    banner($("act-banner"), "dry", "Añade al menos un log con evento Linux");
    return;
  }
  const isNew = state.activityIsNew;
  try {
    const url = isNew
      ? "/api/chains"
      : "/api/chains/" + encodeURIComponent(payload.id);
    const res = await api(url, {
      method: isNew ? "POST" : "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    state.activityIsNew = false;
    state.activitySelectedId = payload.id;
    $("act-id").readOnly = true;
    banner($("act-banner"), "ok", `Cadena guardada: ${payload.id}`);
    await refreshActivityTab();
    if (res.chain) fillActivityEditor(res.chain);
    else await loadActivityDetail(payload.id);
  } catch (e) {
    banner($("act-banner"), "live", "Error al guardar: " + e.message);
  }
}

async function refreshActivityTab() {
  const data = await api("/api/chains");
  state.activityChains = data.chains || [];
  state.activityStats = data.stats || {};
  fillActCategoryFilter();
  renderActList();
  if (state.activitySelectedId && !state.activityIsNew) {
    await loadActivityDetail(state.activitySelectedId);
  }
}

async function initActivityTab() {
  if (!state.eventCatalog.length) {
    try {
      await applyEventCatalog(await api("/api/events?source=linux"));
    } catch (_) {
      /* catálogo opcional para el selector */
    }
  }
  $("act-search")?.addEventListener("input", renderActList);
  $("act-filter-legit")?.addEventListener("change", renderActList);
  $("act-filter-category")?.addEventListener("change", renderActList);
  $("btn-act-refresh")?.addEventListener("click", () =>
    refreshActivityTab().catch((e) => banner($("act-banner"), "live", e.message))
  );
  $("btn-act-new-mixed")?.addEventListener("click", newMixedChain);
  $("btn-act-add-log")?.addEventListener("click", addActLogRow);
  $("btn-act-save")?.addEventListener("click", () =>
    saveActChain().catch((e) => banner($("act-banner"), "live", e.message))
  );
  $("btn-act-import")?.addEventListener("click", async () => {
    try {
      const r = await api("/api/chains/import", { method: "POST" });
      banner($("act-banner"), "ok", `Importadas ${r.chains_total} cadenas (${r.steps_total} pasos)`);
      await refreshActivityTab();
    } catch (e) {
      banner($("act-banner"), "live", "Error import: " + e.message);
    }
  });
  await refreshActivityTab();
  state.activityReady = true;
}

async function loadActivityChainsForScenario() {
  try {
    let data = await api("/api/chains");
    if (!(data.chains || []).length) {
      try {
        await api("/api/chains/import", { method: "POST" });
        data = await api("/api/chains");
      } catch (_) {
        /* import opcional si no hay YAML */
      }
    }
    state.activityChains = data.chains || [];
    state.activityStats = data.stats || {};
    const hint = $("sc-chains-hint");
    const countEl = $("sc-chains-count");
    if (countEl) countEl.textContent = state.activityChains.length;
    if (hint) {
      hint.style.display = state.activityChains.length ? "none" : "block";
    }
    fillScAddChainSelect();
  } catch (_) {
    state.activityChains = [];
  }
}

async function initEventsTab() {
  if (!state.mitreTactics.length) {
    const mt = await api("/api/mitre/tactics");
    state.mitreTactics = mt.tactics || [];
    const sel = $("events-filter-tactic");
    if (sel) {
      sel.innerHTML =
        '<option value="">Todas</option>' +
        state.mitreTactics
          .map((t) => `<option value="${esc(t.id)}">${esc(t.id)} · ${esc(t.name)}</option>`)
          .join("");
    }
    renderTacticsGrid([]);
  }
  await refreshEventsTab();
  state.eventsReady = true;
}

/* ========== COMANDOS LINUX (sub-vista Eventos) ========== */
const cmdState = { list: [], selectedId: null, ready: false };

function legitLabel(v) {
  return v === "legitimate" ? "Legítimo" : v === "illegitimate" ? "Ilegítimo" : v || "—";
}

function legitPill(v) {
  const cls = v === "legitimate" ? "pill-legit" : "pill-illegit";
  return `<span class="pill ${cls}">${esc(legitLabel(v))}</span>`;
}

function cmdFilteredList() {
  const q = ($("cmd-search")?.value || "").trim().toLowerCase();
  const leg = ($("cmd-filter-legit")?.value || "").toLowerCase();
  const cat = ($("cmd-filter-category")?.value || "").toLowerCase();
  return cmdState.list.filter((c) => {
    if (leg && (c.legitimacy || "").toLowerCase() !== leg) return false;
    if (cat && (c.category || "").toLowerCase() !== cat) return false;
    if (!q) return true;
    const hay = [c.value, c.category, c.description, c.legitimacy].join(" ").toLowerCase();
    return hay.includes(q);
  });
}

function renderCmdList() {
  const list = cmdFilteredList();
  const host = $("cmd-list");
  if (!host) return;
  $("cmd-count").textContent = list.length;
  const legitN = cmdState.list.filter((c) => c.legitimacy === "legitimate").length;
  const illegN = cmdState.list.filter((c) => c.legitimacy === "illegitimate").length;
  $("cmd-stats").textContent = `Total pool: ${cmdState.list.length} · ${legitN} legítimos · ${illegN} ilegítimos`;
  const cats = [...new Set(cmdState.list.map((c) => c.category).filter(Boolean))].sort();
  const catSel = $("cmd-filter-category");
  if (catSel && catSel.options.length <= 1) {
    catSel.innerHTML =
      '<option value="">Todas</option>' + cats.map((c) => `<option value="${esc(c)}">${esc(c)}</option>`).join("");
  }
  if (!list.length) {
    host.innerHTML = '<p class="meta">Sin comandos. Ejecuta db import-csv o añade uno.</p>';
    return;
  }
  host.innerHTML = list
    .map((c) => {
      const active = c.id === cmdState.selectedId ? " active" : "";
      return `<button type="button" class="event-list-item${active}" data-cmd-id="${c.id}">
        ${legitPill(c.legitimacy)}
        <div class="eli-name mono" style="margin-top:6px">${esc(c.value)}</div>
        <div class="eli-meta">${esc(c.category || "—")} · ${esc(c.description || "")}</div>
      </button>`;
    })
    .join("");
  host.querySelectorAll(".event-list-item").forEach((btn) => {
    btn.addEventListener("click", () => fillCmdEditor(cmdState.list.find((x) => String(x.id) === btn.dataset.cmdId)));
  });
}

function fillCmdEditor(cmd) {
  if (!cmd) return;
  cmdState.selectedId = cmd.id;
  $("cmd-editor").style.display = "block";
  $("cmd-detail-title").textContent = legitLabel(cmd.legitimacy);
  $("cmd-detail-meta").textContent = `ID ${cmd.id} · ${cmd.category || "sin categoría"}`;
  $("cmd-value").value = cmd.value || "";
  $("cmd-legitimacy").value = cmd.legitimacy === "legitimate" ? "legitimate" : "illegitimate";
  $("cmd-category").value = cmd.category || "";
  $("cmd-description").value = cmd.description || "";
  $("btn-cmd-delete").style.display = "inline-block";
  renderCmdList();
}

function clearCmdEditorNew() {
  cmdState.selectedId = null;
  $("cmd-editor").style.display = "block";
  $("cmd-detail-title").textContent = "Nuevo comando";
  $("cmd-detail-meta").textContent = "Se guardará en pool linux_shell";
  $("cmd-value").value = "";
  $("cmd-legitimacy").value = "illegitimate";
  $("cmd-category").value = "";
  $("cmd-description").value = "";
  renderCmdList();
}

async function refreshCommandsTab() {
  const leg = $("cmd-filter-legit")?.value || "";
  const qs = leg ? "?legitimacy=" + encodeURIComponent(leg) : "";
  const data = await api("/api/commands" + qs);
  cmdState.list = data.commands || [];
  renderCmdList();
}

async function saveCmdEditor() {
  const payload = {
    value: $("cmd-value").value.trim(),
    legitimacy: $("cmd-legitimacy").value,
    category: $("cmd-category").value.trim(),
    description: $("cmd-description").value.trim(),
  };
  if (!payload.value) {
    banner($("events-banner"), "dry", "El comando no puede estar vacío");
    return;
  }
  try {
    let res;
    if (cmdState.selectedId) {
      res = await api("/api/commands/" + cmdState.selectedId, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
    } else {
      res = await api("/api/commands", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
    }
    cmdState.list = res.commands || [];
    const saved = cmdState.list.find((c) => c.value === payload.value);
    if (saved) cmdState.selectedId = saved.id;
    renderCmdList();
    if (saved) fillCmdEditor(saved);
    banner($("events-banner"), "ok", "Comando guardado");
  } catch (e) {
    banner($("events-banner"), "live", e.message);
  }
}

async function deleteCmdEditor() {
  if (!cmdState.selectedId || !confirm("¿Eliminar este comando?")) return;
  try {
    const res = await api("/api/commands/" + cmdState.selectedId, { method: "DELETE" });
    cmdState.list = res.commands || [];
    cmdState.selectedId = null;
    $("cmd-editor").style.display = "none";
    renderCmdList();
    banner($("events-banner"), "ok", "Comando eliminado");
  } catch (e) {
    banner($("events-banner"), "live", e.message);
  }
}

function setEventsView(mode) {
  const templates = mode === "templates";
  $("events-mode-templates").classList.toggle("active", templates);
  $("events-mode-commands").classList.toggle("active", !templates);
  $("events-view-templates").style.display = templates ? "grid" : "none";
  $("events-view-commands").style.display = templates ? "none" : "grid";
  if (!templates && !cmdState.ready) {
    refreshCommandsTab().then(() => {
      cmdState.ready = true;
    });
  }
}

$("events-mode-templates")?.addEventListener("click", () => setEventsView("templates"));
$("events-mode-commands")?.addEventListener("click", () => setEventsView("commands"));
$("btn-cmd-refresh")?.addEventListener("click", () => refreshCommandsTab().catch((e) => banner($("events-banner"), "live", e.message)));
$("btn-cmd-new")?.addEventListener("click", clearCmdEditorNew);
$("btn-cmd-save")?.addEventListener("click", () => saveCmdEditor());
$("btn-cmd-delete")?.addEventListener("click", () => deleteCmdEditor());
$("cmd-search")?.addEventListener("input", renderCmdList);
$("cmd-filter-legit")?.addEventListener("change", () => refreshCommandsTab().catch((e) => banner($("events-banner"), "live", e.message)));
$("cmd-filter-category")?.addEventListener("change", renderCmdList);

$("btn-events-refresh")?.addEventListener("click", () => refreshEventsTab().catch((e) => banner($("events-banner"), "live", e.message)));
$("btn-events-new")?.addEventListener("click", clearEventEditorNew);
$("btn-ev-save")?.addEventListener("click", () => saveEventEditor());
$("btn-ev-delete")?.addEventListener("click", () => deleteEventEditor());
$("btn-ev-clone")?.addEventListener("click", cloneEventEditor);
$("events-search")?.addEventListener("input", renderEventsList);
$("events-filter-system")?.addEventListener("change", () => refreshEventsTab().catch((e) => banner($("events-banner"), "live", e.message)));
$("events-filter-category")?.addEventListener("change", () => refreshEventsTab().catch((e) => banner($("events-banner"), "live", e.message)));
$("events-filter-tactic")?.addEventListener("change", renderEventsList);
$("ev-ttp")?.addEventListener("input", updateMitrePreview);
$("ev-techniques")?.addEventListener("input", updateMitrePreview);
document.addEventListener("change", (ev) => {
  if (ev.target?.classList?.contains("ev-tactic-cb")) updateMitrePreview();
});

function fillScAddChainSelect() {
  const sel = $("sc-add-chain");
  if (!sel) return;
  const cur = sel.value;
  if (!(state.activityChains || []).length) {
    sel.innerHTML = '<option value="">(importa cadenas primero)</option>';
    return;
  }
  sel.innerHTML =
    '<option value="">— elegir cadena —</option>' +
    state.activityChains
      .map((c) => {
        const eff = actEffectiveLegitimacy(c);
        const tag = eff === "mixed" ? "mixta" : eff === "illegitimate" ? "ilegít" : "legit";
        const selected = c.id === cur ? " selected" : "";
        return `<option value="${esc(c.id)}"${selected}>${esc(c.id)} · ${esc(tag)} · ${esc(c.name)}</option>`;
      })
      .join("");
  if (cur && state.activityChains.some((c) => c.id === cur)) sel.value = cur;
}

function phaseFromChain(name, chainId) {
  const slug = (name || "cadena_linux").trim().replace(/\s+/g, "_").toLowerCase();
  const cid = chainId || state.activityChains[0]?.id || "";
  return {
    phase_type: "chain",
    name: slug,
    description: "Fase de cadenas Linux (logs agrupados con delays)",
    chains: [{ chain_id: cid, actor: "", sort_order: 0 }],
  };
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

function renderChainPhaseRow(ch) {
  const row = document.createElement("div");
  row.className = "chain-phase-row";
  const chain = state.activityChains.find((c) => c.id === ch.chain_id);
  row.innerHTML = `
    <div><label>Cadena</label><select class="ch-id">${chainOptions(ch.chain_id)}</select><div class="meta ch-meta">${chain ? esc(chain.name) + " · " + (chain.step_count || 0) + " logs" : ""}</div></div>
    <div><label>actor</label><select class="ch-actor">${actorOptions(ch.actor)}</select></div>
    <div><label>&nbsp;</label><button type="button" class="btn btn-ghost btn-sm rm-ch">×</button></div>`;
  row.querySelector(".ch-id").addEventListener("change", (e) => {
    const picked = state.activityChains.find((c) => c.id === e.target.value);
    row.querySelector(".ch-meta").textContent = picked
      ? `${picked.name} · ${picked.step_count || 0} logs · delays entre pasos`
      : "";
  });
  row.querySelector(".rm-ch").addEventListener("click", () => row.remove());
  return row;
}

function renderChainPhaseBlock(ph, pi) {
  const div = document.createElement("div");
  div.className = "phase-block phase-chain";
  div.dataset.pi = pi;
  div.dataset.phaseType = "chain";
  const items = ph.chains || (ph.events || []).filter((e) => e.chain_id).map((e) => ({
    chain_id: e.chain_id,
    actor: e.actor || "",
  }));
  div.innerHTML = `
    <div class="mitre-badge pill-chain">🔗 Fase cadena · ${esc(ph.name || "cadena")}</div>
    <div class="row">
      <div><label>Nombre fase (slug)</label><input class="ph-name" value="${esc(ph.name || "cadena")}"></div>
      <div style="flex:0"><label>&nbsp;</label><button type="button" class="btn btn-danger btn-sm rm-phase">Eliminar</button></div>
    </div>
    <label>Descripción</label>
    <input class="ph-desc" value="${esc(ph.description || "")}">
    <div class="chains-wrap"></div>
    <button type="button" class="btn btn-ghost btn-sm add-chain-phase">+ Cadena</button>`;
  const wrap = div.querySelector(".chains-wrap");
  items.forEach((ch) => wrap.appendChild(renderChainPhaseRow(ch)));
  div.querySelector(".add-chain-phase").addEventListener("click", () => {
    if (!state.activityChains.length) {
      banner($("sc-banner"), "dry", "Sin cadenas. Importa YAML en pestaña Cadenas.");
      return;
    }
    wrap.appendChild(
      renderChainPhaseRow({ chain_id: state.activityChains[0]?.id || "", actor: "" })
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
  if (ph.phase_type === "chain") return renderChainPhaseBlock(ph, pi);
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
      <label class="step-add-label">Añadir paso</label>
      <select class="ph-add-step-kind">
        <option value="event">Evento simple (MITRE)</option>
        <option value="chain">Cadena Linux (agrupación de logs)</option>
        <option value="email">Correo HTML</option>
      </select>
      <button type="button" class="btn btn-ghost btn-sm ph-add-step">+ Añadir</button>
    </div>`;

  const wrap = div.querySelector(".steps-wrap");
  const phaseEventIds = (synced.events || []).filter((e) => e.id && !e.chain_id).map((e) => e.id);
  mitrePhaseSteps(synced).forEach((step) => {
    if (step.type === "email") {
      wrap.appendChild(renderEmailRow(step.data, div, true));
    } else if (step.type === "chain") {
      wrap.appendChild(renderChainRow(step.data, div));
    } else {
      wrap.appendChild(renderEventRow(step.data, div, phaseEventIds));
    }
  });

  div.querySelector(".ph-mitre").addEventListener("change", (e) => {
    applyMitreToPhaseBlock(div, e.target.value, false);
  });
  div.querySelector(".ph-apply-events").addEventListener("click", () => {
    const tid = div.querySelector(".ph-mitre").value;
    if (tid) applyMitreToPhaseBlock(div, tid, true);
  });
  div.querySelector(".ph-add-step").addEventListener("click", () => {
    const kind = div.querySelector(".ph-add-step-kind").value;
    const tid = div.querySelector(".ph-mitre").value;
    if (kind === "chain") {
      if (!state.activityChains.length) {
        banner($("sc-banner"), "dry", "Sin cadenas. Importa YAML en pestaña Cadenas o pulsa «Importar cadenas» arriba.");
        return;
      }
      wrap.appendChild(
        renderChainRow(
          normalizeScenarioEvent({ chain_id: state.activityChains[0]?.id || "", count: 1, actor: "" }),
          div
        )
      );
      return;
    }
    if (kind === "email") {
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
      return;
    }
    wrap.appendChild(
      renderEventRow(
        normalizeScenarioEvent({ id: firstAllowedEventId(tid) || "", count: 1, actor: "" }),
        div,
        [...phaseEventIds, firstAllowedEventId(tid) || ""].filter(Boolean)
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

function renderEventRow(ev, block, phaseEventIds = []) {
  const tid = block.querySelector(".ph-mitre").value;
  const row = document.createElement("div");
  row.className = "event-row";
  row.innerHTML = `
    <div><label>event id</label><select class="ev-id">${eventOptions(ev.id, tid, phaseEventIds)}</select><div class="ev-ttp"></div></div>
    <div><label>count</label><input class="ev-count" type="number" min="1" value="${ev.count ?? 1}"></div>
    <div><label>actor</label><select class="ev-actor">${actorOptions(ev.actor)}</select></div>
    <div><label>&nbsp;</label><button type="button" class="btn btn-ghost btn-sm rm-ev">×</button></div>`;
  row.querySelector(".ev-id").addEventListener("change", (e) => updateEventRowTtp(row, e.target.value));
  updateEventRowTtp(row, row.querySelector(".ev-id").value);
  row.querySelector(".rm-ev").addEventListener("click", () => row.remove());
  return row;
}

function chainOptions(selected) {
  const chains = state.activityChains || [];
  if (!chains.length) return '<option value="">(importa cadenas primero)</option>';
  return chains
    .map((c) => {
      const eff = actEffectiveLegitimacy(c);
      const tag = eff === "mixed" ? "mixta" : eff === "illegitimate" ? "ilegít" : "legit";
      const sel = c.id === selected ? " selected" : "";
      return `<option value="${esc(c.id)}"${sel}>${esc(c.id)} · ${esc(tag)} · ${esc(c.name)}</option>`;
    })
    .join("");
}

function renderChainRow(ev, block) {
  const row = document.createElement("div");
  row.className = "chain-row chain-row-inline";
  const chain = state.activityChains.find((c) => c.id === ev.chain_id);
  const eff = chain ? actEffectiveLegitimacy(chain) : "";
  const badge =
    eff === "mixed"
      ? '<span class="mixed-badge">cadena mixta</span>'
      : eff === "illegitimate"
        ? '<span class="illegit-badge">cadena ilegítima</span>'
        : '<span class="legit-badge">cadena legítima</span>';
  row.innerHTML = `
    <div class="chain-step-tag">🔗 Cadena · ${badge}</div>
    <div><label>Cadena Linux</label><select class="ch-id">${chainOptions(ev.chain_id)}</select><div class="meta ch-meta">${chain ? esc(chain.name) + " · " + (chain.step_count || 0) + " logs agrupados" : ""}</div></div>
    <div><label>actor</label><select class="ch-actor">${actorOptions(ev.actor)}</select></div>
    <div><label>&nbsp;</label><button type="button" class="btn btn-ghost btn-sm rm-ch">×</button></div>`;
  row.querySelector(".ch-id").addEventListener("change", (e) => {
    const picked = state.activityChains.find((c) => c.id === e.target.value);
    row.querySelector(".ch-meta").textContent = picked
      ? `${picked.name} · ${picked.step_count || 0} pasos · delays entre logs`
      : "";
  });
  row.querySelector(".rm-ch").addEventListener("click", () => row.remove());
  return row;
}

function renderAllPhases() {
  const container = $("sc-phases");
  container.innerHTML = "";
  scPhases.forEach((ph, i) => container.appendChild(renderPhaseBlock(ph, i)));
  fillCatalogTargetPhaseSelect();
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
    if (ptype === "chain") {
      const chains = [];
      block.querySelectorAll(".chain-phase-row").forEach((row, i) => {
        const cid = row.querySelector(".ch-id").value;
        if (!cid) return;
        chains.push({
          chain_id: cid,
          actor: row.querySelector(".ch-actor").value,
          sort_order: i,
        });
      });
      phases.push({
        phase_type: "chain",
        name: block.querySelector(".ph-name").value.trim().replace(/\s+/g, "_").toLowerCase() || "cadena",
        description: block.querySelector(".ph-desc").value.trim(),
        chains,
      });
      return;
    }
    const events = [];
    const emails = [];
    let order = 0;
    block.querySelectorAll(".steps-wrap > .event-row, .steps-wrap > .email-row, .steps-wrap > .chain-row").forEach((row) => {
      if (row.classList.contains("email-row")) {
        emails.push({
          template_id: row.querySelector(".em-tpl").value,
          to_address: row.querySelector(".em-to").value.trim(),
          cc: row.querySelector(".em-cc").value.trim(),
          sort_order: order++,
        });
      } else if (row.classList.contains("chain-row")) {
        events.push(
          normalizeScenarioEvent({
            chain_id: row.querySelector(".ch-id").value,
            count: 1,
            actor: row.querySelector(".ch-actor").value,
            sort_order: order++,
          })
        );
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
      loadActivityChainsForScenario(),
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
      if (synced.phase_type === "chain") {
        synced.chains = (synced.chains || synced.events || [])
          .filter((e) => e.chain_id)
          .map((e) => normalizeScenarioEvent(e));
      } else {
        synced.events = (synced.events || []).map(normalizeScenarioEvent);
      }
      synced.emails = synced.emails || [];
      return synced;
    });
    renderAllPhases();
    const item = scItems.find((it) => it.id === scLoadedId) || {
      id: scLoadedId,
      name: sc.name,
      description: sc.description,
      phases: sc.phases?.length || 0,
      events: scenarioStepCount(sc.phases),
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

$("btn-add-phase-chain").addEventListener("click", () => {
  const chainId = $("sc-add-chain")?.value || "";
  if (!chainId) {
    banner($("sc-banner"), "dry", "Elige una cadena del desplegable o importa el catálogo YAML.");
    return;
  }
  const chain = state.activityChains.find((c) => c.id === chainId);
  const slug = (chain?.category || "cadena").replace(/\s+/g, "_").toLowerCase();
  scPhases.push(phaseFromChain(`${slug}_${scPhases.length + 1}`, chainId));
  renderAllPhases();
  banner($("sc-banner"), "ok", `Fase cadena añadida: ${chain?.name || chainId}`);
});

$("btn-sc-import-chains")?.addEventListener("click", async () => {
  try {
    const r = await api("/api/chains/import", { method: "POST" });
    await loadActivityChainsForScenario();
    document.querySelectorAll(".phase-block").forEach((block) => {
      block.querySelectorAll(".ch-id").forEach((sel) => {
        const cur = sel.value;
        sel.innerHTML = chainOptions(cur);
      });
    });
    fillScAddChainSelect();
    banner($("sc-banner"), "ok", `Cadenas importadas: ${r.chains_total} (${r.steps_total} logs)`);
  } catch (e) {
    banner($("sc-banner"), "live", "Error importando cadenas: " + e.message);
  }
});

$("btn-sc-goto-chains")?.addEventListener("click", () => {
  document.querySelector('[data-tab="activity"]')?.click();
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


$("btn-catalog-filter")?.addEventListener("click", () => applyScenarioCatalogFilter());

$("btn-catalog-add-all")?.addEventListener("click", () => addAllFilteredCatalogEvents());
