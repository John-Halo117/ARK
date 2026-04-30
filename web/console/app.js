const state = {
  view: "overview",
  eventCursor: null,
  lastEventsQuery: { source: "", type: "", limit: 50 },
};

const titles = {
  overview: "Overview",
  events: "Events",
  agents: "Agents",
  trace: "Trace",
  config: "Config",
};

const qs = (selector) => document.querySelector(selector);
const qsa = (selector) => Array.from(document.querySelectorAll(selector));

function stringify(value) {
  return JSON.stringify(value, null, 2);
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options,
  });
  const data = await response.json();
  if (!response.ok || data.status === "error") {
    const reason = data.reason || data.error || `Request failed with ${response.status}`;
    throw new Error(reason);
  }
  return data;
}

function setStatus(status, detail) {
  qs("#sidebarStatus").textContent = status;
  qs("#sidebarDetail").textContent = detail;
}

function setView(view) {
  state.view = view;
  qsa(".view").forEach((node) => node.classList.toggle("active", node.id === view));
  qsa(".nav-item").forEach((node) => node.classList.toggle("active", node.dataset.view === view));
  qs("#viewTitle").textContent = titles[view] || view;
  refresh();
}

function renderServiceGrid(services) {
  const grid = qs("#serviceGrid");
  grid.innerHTML = "";
  services.forEach((service) => {
    const card = document.createElement("article");
    card.className = `status-card status-${service.status}`;
    card.innerHTML = `
      <span class="label">${escapeHtml(service.name)}</span>
      <strong>${escapeHtml(service.status)}</strong>
      <small>${Number(service.latency_ms || 0)} ms</small>
    `;
    grid.appendChild(card);
  });
}

function renderCaps(caps) {
  const list = qs("#capsList");
  list.innerHTML = "";
  Object.entries(caps || {}).forEach(([key, value]) => {
    const dt = document.createElement("dt");
    const dd = document.createElement("dd");
    dt.textContent = key;
    dd.textContent = String(value);
    list.append(dt, dd);
  });
}

async function loadOverview() {
  const data = await api("/api/console/status");
  renderServiceGrid(data.services || []);
  renderCaps(data.caps || {});
  qs("#meshStamp").textContent = data.generated_at || "fresh";
  qs("#meshJson").textContent = stringify(data.mesh || {});
  setStatus(data.status || "ok", `${(data.services || []).length} bounded checks`);
}

function eventQueryParams(cursor) {
  const params = new URLSearchParams();
  Object.entries(state.lastEventsQuery).forEach(([key, value]) => {
    if (value !== "" && value !== null && value !== undefined) params.set(key, value);
  });
  if (cursor) params.set("cursor", cursor);
  return params.toString();
}

async function loadEvents(cursor = null) {
  const data = await api(`/api/console/events?${eventQueryParams(cursor)}`);
  const list = qs("#eventList");
  if (!cursor) list.innerHTML = "";
  (data.events || []).forEach((event) => {
    const row = document.createElement("article");
    row.className = "row-card";
    row.innerHTML = `
      <header>
        <div>
          <strong>${escapeHtml(event.event_id || "event")}</strong>
          <div class="muted">${escapeHtml(event.source || "")} / ${escapeHtml(event.event_type || "")}</div>
        </div>
        <span class="pill">${escapeHtml(String(event.timestamp || ""))}</span>
      </header>
      <pre class="code-block">${escapeHtml(stringify(event))}</pre>
    `;
    list.appendChild(row);
  });
  state.eventCursor = data.next_cursor || null;
  qs("#nextEvents").disabled = !state.eventCursor;
  if ((data.events || []).length === 0 && !cursor) {
    list.innerHTML = '<article class="row-card muted">No events matched this bounded query.</article>';
  }
  setStatus("ok", `${data.count || 0} events loaded`);
}

async function loadAgents() {
  const data = await api("/api/console/agents");
  const list = qs("#agentList");
  list.innerHTML = "";
  (data.agents || []).forEach((agent) => {
    const row = document.createElement("article");
    row.className = "row-card";
    row.innerHTML = `
      <header>
        <div>
          <strong>${escapeHtml(agent.service)}</strong>
          <div class="muted">${Number(agent.instance_count || 0)} instances / load ${Number(agent.total_load || 0).toFixed(2)}</div>
        </div>
        <span class="pill">${Array.isArray(agent.capabilities) ? agent.capabilities.length : 0} caps</span>
      </header>
      <pre class="code-block">${escapeHtml(stringify(agent.raw || agent))}</pre>
    `;
    list.appendChild(row);
  });
  if ((data.agents || []).length === 0) {
    list.innerHTML = '<article class="row-card muted">No agents reported by the mesh yet.</article>';
  }
  setStatus("ok", `${(data.agents || []).length} agents visible`);
}

async function loadConfigIndex() {
  const data = await api("/api/console/config");
  const list = qs("#configList");
  list.innerHTML = "";
  (data.files || []).forEach((file) => {
    const row = document.createElement("article");
    row.className = "row-card";
    row.innerHTML = `
      <header>
        <div>
          <strong>${escapeHtml(file.path)}</strong>
          <div class="muted">${file.available ? `${file.bytes} bytes` : "missing"}</div>
        </div>
        <button type="button" ${file.available ? "" : "disabled"}>Open</button>
      </header>
    `;
    const button = row.querySelector("button");
    button.addEventListener("click", () => openConfig(file.path));
    list.appendChild(row);
  });
  setStatus("ok", `${(data.files || []).length} config entries`);
}

async function openConfig(path) {
  const data = await api(`/api/console/config/file?path=${encodeURIComponent(path)}`);
  qs("#configTitle").textContent = data.path;
  qs("#configContent").textContent = data.content;
}

async function submitTrace(event) {
  event.preventDefault();
  const form = new FormData(event.currentTarget);
  const eventBody = await buildEventBody(form);
  if (!eventBody) return;
  const data = await api("/api/console/trace", {
    method: "POST",
    body: JSON.stringify({
      event: eventBody,
      constraints: {
        confidence_threshold: 0.5,
        allowed_actions: ["record"],
      },
    }),
  });
  qs("#traceOutput").textContent = stringify(data);
  setStatus(data.status || "ok", "trace preview complete");
}

async function buildEventBody(form) {
  let payload = {};
  try {
    payload = JSON.parse(String(form.get("payload") || "{}"));
  } catch (error) {
    qs("#traceOutput").textContent = stringify({ status: "error", reason: "Payload JSON is invalid" });
    return null;
  }
  const observations = String(form.get("observations") || "")
    .split(",")
    .map((value) => value.trim())
    .filter(Boolean)
    .map(Number);
  const eventBody = {
    id: String(form.get("id") || ""),
    kind: String(form.get("kind") || ""),
    entity_id: String(form.get("entity_id") || ""),
    schema_version: String(form.get("schema_version") || ""),
    payload,
    observations,
  };
  eventBody.hash = await hashEventBody(eventBody);
  const hashInput = qs('#traceForm input[name="hash"]');
  if (hashInput) hashInput.value = eventBody.hash;
  return eventBody;
}

async function hashEventBody(eventBody) {
  const hashInput = {
    id: eventBody.id,
    kind: eventBody.kind,
    entity_id: eventBody.entity_id,
    schema_version: eventBody.schema_version,
    payload: eventBody.payload,
    observations: eventBody.observations,
  };
  const canonical = canonicalJson(hashInput);
  const bytes = new TextEncoder().encode(canonical);
  const digest = await crypto.subtle.digest("SHA-256", bytes);
  return `sha256:${Array.from(new Uint8Array(digest)).map((byte) => byte.toString(16).padStart(2, "0")).join("")}`;
}

function canonicalJson(value) {
  if (Array.isArray(value)) return `[${value.map(canonicalJson).join(",")}]`;
  if (value && typeof value === "object") {
    return `{${Object.keys(value).sort().map((key) => `${JSON.stringify(key)}:${canonicalJson(value[key])}`).join(",")}}`;
  }
  return JSON.stringify(value);
}

async function refresh() {
  try {
    if (state.view === "overview") await loadOverview();
    if (state.view === "events") await loadEvents();
    if (state.view === "agents") await loadAgents();
    if (state.view === "config") await loadConfigIndex();
  } catch (error) {
    setStatus("error", error.message);
  }
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

qsa(".nav-item").forEach((button) => {
  button.addEventListener("click", () => setView(button.dataset.view));
});

qs("#refreshButton").addEventListener("click", refresh);
qs("#eventFilters").addEventListener("submit", (event) => {
  event.preventDefault();
  const form = new FormData(event.currentTarget);
  state.lastEventsQuery = {
    source: String(form.get("source") || ""),
    type: String(form.get("type") || ""),
    limit: Number(form.get("limit") || 50),
  };
  state.eventCursor = null;
  loadEvents();
});
qs("#nextEvents").addEventListener("click", () => loadEvents(state.eventCursor));
qs("#traceForm").addEventListener("submit", submitTrace);
qsa('#traceForm input, #traceForm textarea').forEach((input) => {
  input.addEventListener("input", async () => {
    const form = new FormData(qs("#traceForm"));
    await buildEventBody(form);
  });
});

refresh();
buildEventBody(new FormData(qs("#traceForm")));
