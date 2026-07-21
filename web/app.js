// Arctus.ai dashboard client
const $ = (id) => document.getElementById(id);

function ts() {
  return new Date().toLocaleTimeString([], { hour12: false });
}

function logEntry(msg, kind = "info") {
  const el = document.createElement("div");
  el.className = "entry";
  el.innerHTML = `<span class="t">[${ts()}]</span>${escapeHtml(msg)}`;
  $("log").appendChild(el);
  $("log").scrollTop = $("log").scrollHeight;
}

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  })[c]);
}

async function getJSON(url, opts) {
  const r = await fetch(url, opts);
  if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
  return r.json();
}

// ---- agents ----
async function refreshAgents() {
  try {
    const d = await getJSON("/api/agents");
    const s = d.summary || {};
    const lines = Object.entries(s)
      .sort((a, b) => b[1] - a[1])
      .map(([k, v]) => `${k}: <b>${v}</b>`);
    $("agent-summary").innerHTML = `Total: <b>${d.total}</b><br>` + lines.join("<br>");
  } catch (e) {
    $("agent-summary").textContent = "Error: " + e.message;
  }
}

// ---- MCP ----
async function refreshMCP() {
  try {
    const d = await getJSON("/api/mcp/list");
    const cs = d.connectors || [];
    if (!cs.length) { $("mcp-list").textContent = "None yet."; return; }
    $("mcp-list").innerHTML = cs.map(
      (c) => `${c.name} <span style="color:var(--text-dim)">(${c.transport}, ${c.tools.length} tools)</span>`
    ).join("<br>");
  } catch (e) {
    $("mcp-list").textContent = "Error: " + e.message;
  }
}

function openMCPModal() { $("mcp-modal").classList.remove("hidden"); }
function closeMCPModal() { $("mcp-modal").classList.add("hidden"); }

async function addMCPConnector() {
  const name = $("mcp-name").value.trim();
  const transport = $("mcp-transport").value;
  const url = $("mcp-url").value.trim();
  const command = $("mcp-command").value.trim();
  const apiKey = $("mcp-key").value.trim();
  const tools = $("mcp-tools").value.split(",").map((s) => s.trim()).filter(Boolean);
  if (!name) { alert("Name required"); return; }
  const config = { transport, url, command, api_key: apiKey, tools };
  try {
    await getJSON("/api/mcp/connect", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name, config }),
    });
    closeMCPModal();
    logEntry(`MCP connector '${name}' connected`, "ok");
    refreshMCP();
  } catch (e) {
    alert("Failed: " + e.message);
  }
}

// ---- peers ----
async function refreshPeers() {
  try {
    const d = await getJSON("/api/federation/peers");
    const ps = d.peers || [];
    if (!ps.length) { $("peer-list").textContent = "No peers."; return; }
    $("peer-list").innerHTML = ps.map(
      (p) => `${p.name} <span style="color:var(--text-dim)">(${p.base_url})</span>`
    ).join("<br>");
  } catch (e) {
    $("peer-list").textContent = "Error: " + e.message;
  }
}

// ---- orchestrate ----
async function submitTask() {
  const prompt = $("prompt").value.trim();
  if (!prompt) return;
  $("prompt").value = "";
  logEntry(`> ${prompt}`);
  try {
    const d = await getJSON("/api/orchestrate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ prompt, session_id: "web" }),
    });
    if (d.error) { logEntry(`✗ ${d.error}`, "err"); return; }
    logEntry(`complexity=${d.complexity} mode=${d.mode} steps=${(d.steps || []).length}`);
    for (const w of (d.work || [])) {
      logEntry(`  [${w.tier}] ${w.step} → ${String(w.result).slice(0, 120)}`);
    }
    if (d.verification) {
      logEntry(`verify done=${d.verification.done} — ${d.verification.notes}`);
    }
  } catch (e) {
    logEntry(`✗ ${e.message}`, "err");
  }
}

$("prompt").addEventListener("keydown", (e) => {
  if (e.key === "Enter") submitTask();
});

// init
refreshAgents();
refreshMCP();
refreshPeers();
logEntry("Arctus.ai dashboard ready.");
