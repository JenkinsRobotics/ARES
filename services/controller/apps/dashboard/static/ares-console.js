/* Engineering-console additions: specifications, hardware telemetry, the
   component schematic, and the live terminal.
   Kept out of app.js so the existing dashboard logic is untouched. Everything
   here fails soft: a dead endpoint leaves its panel showing "unavailable"
   rather than throwing and stopping the other panels. */
(() => {
  "use strict";

  const $ = (id) => document.getElementById(id);
  const REFRESH_MS = 5000;

  function csrfHeaders() {
    const headers = { Accept: "application/json" };
    const token = window.__ARES_BOOT__ && window.__ARES_BOOT__.csrfToken;
    if (token) {
      headers["X-Ares-CSRF-Token"] = token;
      headers["X-CSRF-Token"] = token;
    }
    return headers;
  }

  async function getJSON(url) {
    const res = await fetch(url, { headers: csrfHeaders(), credentials: "same-origin" });
    if (!res.ok) throw new Error(`${url} → ${res.status}`);
    return res.json();
  }

  const fmtPct = (n) => `${Number(n || 0).toFixed(0)}%`;
  const asList = (d, key) =>
    Array.isArray(d) ? d : Array.isArray(d?.[key]) ? d[key] : [];

  function facts(el, rows) {
    if (!el) return;
    el.innerHTML = rows
      .map(
        ([k, v]) =>
          `<div><dt>${k}</dt><dd>${v === undefined || v === null || v === "" ? "—" : v}</dd></div>`
      )
      .join("");
  }

  function tiles(el, rows) {
    if (!el) return;
    el.innerHTML = rows
      .map(
        ([label, value, detail, state]) => `
      <article class="capacity-card ${state || "normal"}">
        <span>${label}</span><strong>${value}</strong><small>${detail || ""}</small>
      </article>`
      )
      .join("");
  }

  /* Latency is measured, not estimated: runs carry started_at/finished_at, so
     this reports the real median and p95 of completed runs rather than a
     synthetic number. */
  function runLatency(runs) {
    const ms = [];
    for (const r of runs) {
      const a = Date.parse(r.started_at || ""), b = Date.parse(r.finished_at || "");
      if (Number.isFinite(a) && Number.isFinite(b) && b >= a) ms.push(b - a);
    }
    if (!ms.length) return null;
    ms.sort((x, y) => x - y);
    const at = (q) => ms[Math.min(ms.length - 1, Math.floor(ms.length * q))];
    return { n: ms.length, median: at(0.5), p95: at(0.95) };
  }

  const dur = (ms) =>
    ms == null ? "—" : ms < 1000 ? `${ms} ms` : ms < 60000
      ? `${(ms / 1000).toFixed(1)} s` : `${(ms / 60000).toFixed(1)} min`;

  async function refresh() {
    const [stats, runs, goals, approvals, agentsRaw, integrations] = await Promise.all([
      getJSON("/api/system/stats?include_processes=true&process_limit=8").catch(() => null),
      getJSON("/api/runs").catch(() => []),
      getJSON("/api/goals").catch(() => []),
      getJSON("/api/approvals").catch(() => []),
      getJSON("/api/agents").catch(() => null),
      getJSON("/api/integrations").catch(() => []),
    ]);

    const runList = asList(runs, "runs");
    const goalList = asList(goals, "goals");
    const approvalList = asList(approvals, "approvals");
    const agentList = asList(agentsRaw, "agents");
    const integrationList = asList(integrations, "integrations");

    const active = runList.filter((r) =>
      ["running", "queued", "continue"].includes(String(r.status))).length;
    const pending = approvalList.filter((a) =>
      !["approved", "denied", "expired", "resolved"].includes(String(a.status || ""))).length;
    const openGoals = goalList.filter((g) =>
      !["complete", "cancelled", "failed"].includes(String(g.status || ""))).length;

    const host = stats?.host || {};
    const ollama = stats?.ai_runtimes?.ollama || {};
    const jaeger = stats?.ai_runtimes?.jaeger || {};
    const lat = runLatency(runList);

    const heroHost = $("heroHost");
    if (heroHost && host.metrics_source) {
      heroHost.textContent = `${host.cpu_count || "?"} cores · ${host.metrics_source}`;
    }

    facts($("specRuntime"), [
      ["Runtimes", agentList.length ? `${agentList.length} registered` : "—"],
      ["Ollama", ollama.available ? (ollama.status || "ready") : "offline"],
      ["Jaeger bridge", jaeger.available ? (jaeger.status || "connected") : "offline"],
      ["Paused", agentsRaw && agentsRaw.paused ? "yes" : "no"],
    ]);

    facts($("specSecurity"), [
      ["Integrations", integrationList.length || "—"],
      ["Pending approvals", pending],
      ["Transport", "loopback + Tailscale Serve"],
      ["Credentials", "keychain-backed"],
    ]);

    facts($("specTelemetry"), [
      ["VRAM in use", ollama.total_vram_formatted || "0.0 GB"],
      ["Models resident", ollama.loaded_models_count ?? 0],
      ["Run latency (median)", lat ? dur(lat.median) : "no completed runs"],
      ["Source", host.metrics_source || "—"],
    ]);

    tiles($("capacityMetrics"), [
      ["CPU", fmtPct(host.cpu_percent),
        `${host.cpu_count || "?"} cores · ${host.metrics_source || "host"}`,
        host.cpu_percent > 90 ? "critical" : host.cpu_percent > 75 ? "warning" : "normal"],
      ["Memory", fmtPct(host.memory?.percent),
        host.memory?.total_bytes
          ? `${((host.memory.used_bytes || 0) / 1e9).toFixed(1)} / ${(host.memory.total_bytes / 1e9).toFixed(1)} GB`
          : "",
        host.memory?.percent > 90 ? "critical" : host.memory?.percent > 75 ? "warning" : "normal"],
      ["Disk", fmtPct(host.disk?.percent),
        host.disk?.total_bytes
          ? `${(host.disk.used_bytes / 1e12).toFixed(2)} / ${(host.disk.total_bytes / 1e12).toFixed(2)} TB`
          : "",
        host.disk?.percent > 90 ? "critical" : host.disk?.percent > 75 ? "warning" : "normal"],
      ["Active runs", String(active),
        `${openGoals} open goals · ${pending} approvals`,
        pending > 0 ? "warning" : "normal"],
    ]);
    const capSrc = $("capacitySource");
    if (capSrc) capSrc.textContent = host.metrics_source || "";

    tiles($("telemetryExtra"), [
      ["VRAM", ollama.total_vram_formatted || "0.0 GB",
        `${ollama.loaded_models_count ?? 0} model(s) resident`,
        ollama.available ? "normal" : "warning"],
      ["Disk", fmtPct(host.disk?.percent),
        host.disk?.total_bytes
          ? `${(host.disk.used_bytes / 1e12).toFixed(2)} / ${(host.disk.total_bytes / 1e12).toFixed(2)} TB`
          : "",
        host.disk?.percent > 90 ? "critical" : host.disk?.percent > 75 ? "warning" : "normal"],
      ["Run latency", lat ? dur(lat.median) : "—",
        lat ? `p95 ${dur(lat.p95)} · n=${lat.n}` : "no completed runs", "normal"],
      ["Task queue", String(active),
        `${openGoals} open goals · ${pending} approvals`,
        pending > 0 ? "warning" : "normal"],
    ]);

    return { active, pending, openGoals, ollama, jaeger, host, lat };
  }

  /* ── Component schematic ─────────────────────────────────────────── */
  const NODE_DETAIL = {
    iface:     "Browsers and phones reach ARES only through Tailscale Serve. Nothing binds a public interface.",
    clients:   "Claude Code, Codex, Gemini and VS Code connect over MCP. They currently attach to the ares-system server directly by stdio.",
    tailscale: "Serve terminates tailnet TLS on the host and injects an authenticated user identity before proxying to loopback.",
    ares:      "The controller owns goals, run leases, approvals and the audit journal. It never executes inference itself.",
    store:     "SQLite holds automation state and the context store; sqlite-vec backs embedding search.",
    gateway:   "Agentgateway federates MCP servers behind one endpoint and enforces per-identity authorization rules.",
    hermes:    "Hermes Agent runs in an Apple container, reached through its installed launcher and WebUI.",
    jaeger:    "JaegerAI runs natively on the host and is reached through its versioned runner API.",
    openclaw:  "OpenClaw runs in an Apple container; its gateway binds lan inside the container and is published to loopback.",
    ollama:    "Ollama is the model layer: local weights plus the cloud catalog, served under :cloud ids with no local weights.",
  };

  function wireSchematic() {
    const svg = $("schematic"), detail = $("schematicDetail");
    if (!svg || !detail) return;
    const base = detail.textContent;
    const nodes = [...svg.querySelectorAll(".sch-node")];

    const select = (node) => {
      nodes.forEach((n) => n.classList.toggle("is-active", n === node));
      svg.classList.toggle("has-selection", Boolean(node));
      detail.textContent = node ? (NODE_DETAIL[node.dataset.node] || base) : base;
    };

    nodes.forEach((node) => {
      node.addEventListener("click", () =>
        select(node.classList.contains("is-active") ? null : node));
      node.addEventListener("keydown", (e) => {
        if (e.key === "Enter" || e.key === " ") { e.preventDefault(); node.click(); }
      });
    });
    svg.addEventListener("click", (e) => { if (!e.target.closest(".sch-node")) select(null); });
  }

  /* ── Live terminal ───────────────────────────────────────────────── */
  function wireTerminal() {
    const out = $("terminalStream"), meta = $("terminalMeta"), btn = $("terminalPause");
    if (!out) return;
    let paused = false, seen = new Set(), timer = null;

    const line = (t, cls) => {
      const el = document.createElement("div");
      el.className = `term-line ${cls || ""}`;
      el.textContent = t;
      out.appendChild(el);
      while (out.childElementCount > 300) out.removeChild(out.firstChild);
      if (!paused) out.scrollTop = out.scrollHeight;
    };

    const stamp = (d) =>
      (d ? new Date(d) : new Date()).toLocaleTimeString([], { hour12: false });

    async function tick() {
      if (paused) return;
      try {
        const [stats, runs] = await Promise.all([
          getJSON("/api/system/stats").catch(() => null),
          getJSON("/api/runs").catch(() => []),
        ]);
        const runList = asList(runs, "runs");

        for (const r of runList.slice(0, 40)) {
          const key = `${r.id}:${r.status}`;
          if (seen.has(key)) continue;
          seen.add(key);
          if (seen.size > 800) seen = new Set([...seen].slice(-400));
          const cls = ["failed", "blocked"].includes(String(r.status)) ? "term-err"
            : String(r.status) === "complete" ? "term-ok"
            : String(r.status) === "approval_required" ? "term-warn" : "";
          line(`${stamp(r.finished_at || r.started_at || r.created_at)}  run ${String(r.id).slice(0, 12)}  ${r.agent_id || "?"}  ${r.status}`, cls);
        }

        if (stats) {
          const o = stats.ai_runtimes?.ollama || {};
          meta.textContent =
            `ollama ${o.available ? o.status || "ready" : "offline"} · ` +
            `cpu ${fmtPct(stats.host?.cpu_percent)} · mem ${fmtPct(stats.host?.memory?.percent)}`;
        }
      } catch (err) {
        meta.textContent = "stream unavailable";
      }
    }

    btn?.addEventListener("click", () => {
      paused = !paused;
      btn.textContent = paused ? "Resume" : "Pause";
      btn.classList.toggle("is-paused", paused);
    });

    line(`${stamp()}  ares console attached`, "term-ok");
    tick();
    timer = setInterval(tick, REFRESH_MS);
    window.addEventListener("beforeunload", () => clearInterval(timer));
  }

  async function loop() {
    try { await refresh(); } catch (err) { /* panels keep their last value */ }
  }

  function start() {
    wireSchematic();
    wireTerminal();
    loop();
    setInterval(loop, REFRESH_MS);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", start);
  } else {
    start();
  }
})();
