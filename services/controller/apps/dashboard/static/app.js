const $ = id => document.getElementById(id);
const esc = value => String(value ?? '').replace(
  /[&<>"']/g,
  char => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[char]),
);

let snapshot = {agents: [], threads: [], goals: [], runs: [], approvals: [], integrations: [], models: [], paused: false, stats: null, probes: {}};
let configurationAgent = '';
let activeRunId = null;
let activeRunPoll = null;
let activeThreadId = window.localStorage.getItem('ares.activeThreadId') || '';
let chatMessages = [];
const isLocalBrowser = ['127.0.0.1', 'localhost', '::1'].includes(window.location.hostname);

function serviceUrl(service) {
  if (isLocalBrowser) {
    return {
      hermes: 'http://127.0.0.1:8787/',
      jaeger: 'http://127.0.0.1:8790/',
      n8n: 'http://127.0.0.1:5678/',
      gateway: 'http://127.0.0.1:8811/',
    }[service];
  }
  const host = window.location.hostname;
  return {hermes: `https://${host}/`, jaeger: `https://${host}:8443/`}[service] || '';
}

function agentDisplay(agent) {
  return {
    hermes: '⚡ Hermes',
    jaeger: '🐺 JaegerAI',
    openclaw: '🦞 OpenClaw',
  }[agent] || `🤖 ${agent}`;
}

function configureServiceLinks() {
  for (const [id, service] of [
    ['hermesLink', 'hermes'], ['jaegerLink', 'jaeger'],
    ['n8nLink', 'n8n'], ['gatewayLink', 'gateway'],
  ]) {
    const element = $(id);
    if (!element) continue;
    const href = serviceUrl(service);
    if (href) element.href = href;
    else element.hidden = true;
  }
}

// Lightweight, secure zero-dependency markdown formatter
function renderMarkdown(raw) {
  if (!raw) return '';
  let text = String(raw);

  // Extract code blocks first to protect them from regex formatting
  const codeBlocks = [];
  text = text.replace(/```([a-zA-Z0-9_-]*)\n?([\s\S]*?)```/g, (_, lang, code) => {
    const index = codeBlocks.length;
    const cleanLang = esc(lang || 'text');
    const escapedCode = esc(code.trimEnd());
    codeBlocks.push(
      `<pre><code class="language-${cleanLang}">${escapedCode}</code></pre>`
    );
    return `<!--CODE_BLOCK_${index}-->`;
  });

  // Escape HTML in the remaining text
  text = esc(text);

  // Inline code: `code`
  text = text.replace(/`([^`]+)`/g, '<code>$1</code>');

  // Headings
  text = text.replace(/^### (.*$)/gim, '<h4>$1</h4>');
  text = text.replace(/^## (.*$)/gim, '<h3>$1</h3>');
  text = text.replace(/^# (.*$)/gim, '<h3>$1</h3>');

  // Bold and Italics
  text = text.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
  text = text.replace(/\*([^*]+)\*/g, '<em>$1</em>');

  // Bullet items
  text = text.replace(/^\s*[-*]\s+(.*)$/gim, '<li>$1</li>');
  text = text.replace(/(<li>.*<\/li>)/s, '<ul>$1</ul>');

  // Paragraphs & Linebreaks
  text = text.replace(/\n\n+/g, '</p><p>');
  text = text.replace(/\n/g, '<br>');

  // Wrap in paragraph if not starting with tag
  if (!text.startsWith('<h') && !text.startsWith('<ul>') && !text.startsWith('<p>')) {
    text = `<p>${text}</p>`;
  }

  // Restore code blocks
  text = text.replace(/&lt;!--CODE_BLOCK_(\d+)--&gt;|<!--CODE_BLOCK_(\d+)-->/g, (_, id1, id2) => {
    const idx = parseInt(id1 || id2, 10);
    return codeBlocks[idx] || '';
  });

  return text;
}

async function api(path, options = {}) {
  const headers = {'Content-Type': 'application/json', ...(options.headers || {})};
  const token = window.__ARES_BOOT__?.csrfToken;
  if (token) headers['X-CSRF-Token'] = token;
  const response = await fetch(path, {...options, headers});
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.error || `${response.status}`);
  return data;
}

async function load() {
  const [agents, threads, goals, runs, approvals, integrations, models, stats] = await Promise.all([
    api('/api/agents'), api('/api/threads'), api('/api/goals'), api('/api/runs'), api('/api/approvals'), api('/api/integrations'),
    api('/api/agent-models').catch(() => ({providers: []})),
    api('/api/system/stats?include_processes=true&process_limit=8').catch(() => null),
  ]);
  const probes = Object.fromEntries(await Promise.all((agents.agents || []).map(async agent => [
    agent.id,
    await api(`/api/agents/${encodeURIComponent(agent.id)}/probe`).catch(error => ({available: false, error: error.message})),
  ])));
  snapshot = {
    agents: agents.agents || [],
    paused: agents.paused,
    threads: threads || [],
    goals: goals || [],
    runs: runs || [],
    approvals: approvals || [],
    integrations: integrations.integrations || [],
    models: models.providers || [],
    stats,
    probes,
  };
  if (!snapshot.threads.some(row => row.id === activeThreadId)) {
    activeThreadId = snapshot.threads[0]?.id || '';
  }
  if (!activeThreadId && snapshot.agents.length) {
    const created = await api('/api/threads', {
      method: 'POST',
      body: JSON.stringify({agent_id: snapshot.agents[0].id, title: 'New conversation'}),
    });
    activeThreadId = created.id;
    snapshot.threads.unshift(created);
  }
  if (activeThreadId) {
    window.localStorage.setItem('ares.activeThreadId', activeThreadId);
    const detail = await api(`/api/threads/${encodeURIComponent(activeThreadId)}`);
    await restoreThread(detail);
    if ($('activeThreadLabel')) $('activeThreadLabel').textContent = detail.title || 'Conversation';
  }
  render();
}

async function restoreThread(detail) {
  const messages = Array.isArray(detail.messages) ? detail.messages : [];
  chatMessages = messages.map(row => {
    const pendingApproval = snapshot.approvals.find(
      item => item.run_id === row.run_id && item.status === 'pending',
    );
    return {
      role: row.role,
      text: row.content || '',
      agent: row.agent_id || detail.selected_agent_id || '',
      runId: row.run_id || '',
      status: row.status || '',
      timestamp: Number(row.created_at || 0) * 1000,
      tools: [],
      approvalPending: Boolean(pendingApproval),
      approvalId: pendingApproval?.id || '',
      approvalReason: pendingApproval?.reason || '',
    };
  });

  // If the page refreshed mid-run, reconstruct the assistant card from the
  // durable run/event ledger instead of inventing a new browser-only turn.
  const assistantRunIds = new Set(
    messages.filter(row => row.role === 'assistant' && row.run_id).map(row => row.run_id),
  );
  const unfinished = messages.filter(
    row => row.role === 'user' && row.run_id && !assistantRunIds.has(row.run_id),
  );
  for (const row of unfinished.slice(-5)) {
    const run = snapshot.runs.find(item => item.id === row.run_id);
    if (!run) continue;
    const eventsList = await api(`/api/runs/${encodeURIComponent(row.run_id)}/events`).catch(() => []);
    const tools = [];
    const toolKeys = new Set();
    let eventText = '';
    let approvalId = '';
    let approvalReason = '';
    for (const event of eventsList) {
      const data = event.data || {};
      if (event.type === 'text_delta' && data.text) eventText += data.text;
      if (event.type === 'tool_result') {
        const key = JSON.stringify([data.tool || data.name || 'tool', data.call_id || data.id || data]);
        if (!toolKeys.has(key)) {
          toolKeys.add(key);
          tools.push(data);
        }
      }
      if (event.type === 'approval_required') {
        approvalId = data.approval_id || '';
        approvalReason = data.reason || data.description || '';
      }
    }
    chatMessages.push({
      role: 'assistant', agent: run.agent_id, runId: run.id,
      status: run.status, text: eventText || run.result || run.error || '',
      tools, approvalPending: run.status === 'approval_required' && Boolean(approvalId),
      approvalId, approvalReason, timestamp: Number(run.created_at || 0) * 1000,
    });
  }
}

function parseApproval(row) {
  const reason = row.reason || '';
  let capability = '';
  let agentId = '';
  let root = '';

  const capMatch = reason.match(/capability '([^']+)'/);
  if (capMatch) capability = capMatch[1];

  const agentMatch = row.operation?.match(/grant_capability:(\w+)/);
  if (agentMatch) agentId = agentMatch[1];

  const rootMatch = reason.match(/root '([^']+)'/);
  if (rootMatch) root = rootMatch[1];

  let kind = 'generic';
  if (row.kind === 'capability') kind = 'capability';
  else if (row.kind === 'configuration') kind = 'config';
  else if (row.operation?.includes('runtime_request')) kind = 'runtime';

  return {capability, agentId, root, kind, reason};
}

function capabilityBadge(cap) {
  if (!cap) return '';
  const colors = {
    'calendar': '#3b82f6', 'notes': '#f59e0b', 'reminders': '#10b981',
    'email': '#8b5cf6', 'safari': '#06b6d4', 'system': '#ef4444',
    'finder': '#f97316', 'contacts': '#ec4899', 'messages': '#14b8a6',
    'terminal': '#dc2626', 'applescript': '#a855f7', 'workspace': '#6366f1',
    'git': '#f43f5e', 'service': '#84cc16', 'capability': '#64748b',
  };
  const prefix = cap.split('.')[0];
  const color = colors[prefix] || colors[cap] || '#64748b';
  return `<span class="cap-badge" style="background:${color}20;color:${color};border:1px solid ${color}40">${esc(cap)}</span>`;
}

function renderChat() {
  const stream = $('chatStream');
  const empty = $('chatEmpty');
  if (!stream) return;

  if (chatMessages.length === 0) {
    if (empty) empty.style.display = 'block';
    return;
  }
  if (empty) empty.style.display = 'none';

  stream.innerHTML = chatMessages.map(msg => {
    if (msg.role === 'user') {
      return `
        <div class="chat-msg user-msg">
          <div class="user-bubble">${esc(msg.text)}</div>
          <div class="user-meta">Routed to: @${esc(msg.agent)} · ${new Date(msg.timestamp).toLocaleTimeString([], {hour: '2-digit', minute: '2-digit'})}</div>
        </div>`;
    }

    // Assistant message card
    const isRunning = msg.status === 'running' || msg.status === 'queued';
    const statusClass = `status-badge-${msg.status || 'running'}`;
    const agentName = esc(agentDisplay(msg.agent));
    // Runtime adapters currently return durable checkpoints/results, not a
    // guaranteed token stream. Label that honestly instead of drawing a fake
    // token cursor.
    const cursorHtml = isRunning ? '<span class="processing-indicator">Runtime working…</span>' : '';

    const thoughtHtml = msg.thoughts ? `
      <details class="thought-box"${isRunning ? ' open' : ''}>
        <summary>Decision rationale and evidence</summary>
        <div class="thought-content">${esc(msg.thoughts)}</div>
      </details>` : '';

    const toolsHtml = (msg.tools && msg.tools.length > 0) ? `
      <div class="tool-badge-list">
        ${msg.tools.map(t => `<span class="tool-run-badge">🛠️ ${esc(t.name || t.tool || 'tool')}</span>`).join('')}
      </div>` : '';

    const approvalRow = snapshot.approvals.find(row => row.id === msg.approvalId);
    const approvalInformed = approvalRow && approvalRow.benefit && approvalRow.scope
      && approvalRow.duration && approvalRow.reversible && approvalRow.safer_alternative
      && (approvalRow.risks || []).length;
    const approvalCardHtml = msg.approvalPending ? `
      <div class="chat-approval-card">
        <div class="chat-approval-header">⚠️ Consequential Action Requested</div>
        <div class="chat-approval-reason">${esc(msg.approvalReason || 'The agent requested an operation requiring explicit authorization.')}</div>
        ${approvalInformed ? `<dl class="approval-context">
          <dt>What you gain</dt><dd>${esc(approvalRow.benefit)}</dd>
          <dt>What could go wrong</dt><dd><ul>${approvalRow.risks.map(risk => `<li>${esc(risk)}</li>`).join('')}</ul></dd>
          <dt>Exact scope</dt><dd>${esc(approvalRow.scope)}</dd>
          <dt>How long</dt><dd>${esc(approvalRow.duration)}</dd>
          ${approvalRow.provider ? `<dt>Provider/location</dt><dd>${esc(approvalRow.provider)}</dd>` : ''}
          ${approvalRow.data_destination ? `<dt>Data destination</dt><dd>${esc(approvalRow.data_destination)}</dd>` : ''}
          <dt>Can it be undone?</dt><dd>${esc(approvalRow.reversible)}</dd>
          <dt>Safer option</dt><dd>${esc(approvalRow.safer_alternative)}</dd>
        </dl>` : '<p class="approval-warning">Approval is disabled until ARES provides the benefit, risks, exact scope, duration, reversibility, and a safer option.</p>'}
        <div class="chat-approval-actions">
          <button class="primary" ${approvalInformed ? '' : 'disabled'} onclick="resolveChatApproval('${esc(msg.approvalId)}', 'approved')">Review and approve</button>
          <button onclick="resolveChatApproval('${esc(msg.approvalId)}', 'denied')">Deny</button>
        </div>
      </div>` : '';

    return `
      <div class="chat-msg assistant-msg ${isRunning ? 'status-running' : ''}" id="chat-msg-${esc(msg.runId)}">
        <div class="msg-header">
          <div class="msg-agent">
            <span>${agentName}</span>
            <span class="tag">${esc(msg.runId || 'run')}</span>
          </div>
          <div class="msg-badges">
            <span class="run-status-badge ${statusClass}">${esc(msg.status || 'running')}</span>
          </div>
        </div>
        ${thoughtHtml}
        ${toolsHtml}
        <div class="msg-content">${renderMarkdown(msg.text || (isRunning ? 'Processing goal…' : 'No output produced.'))}${cursorHtml}</div>
        ${approvalCardHtml}
      </div>`;
  }).join('');

  stream.scrollTop = stream.scrollHeight;
}

async function resolveChatApproval(approvalId, decision) {
  if (!approvalId) return;
  try {
    const row = snapshot.approvals.find(item => item.id === approvalId);
    const informed = row && row.benefit && row.scope && row.duration
      && row.reversible && row.safer_alternative && (row.risks || []).length;
    if (decision === 'approved' && !informed) {
      throw new Error('ARES blocked approval because the request does not explain its benefit, risks, exact scope, duration, reversibility, and safer option.');
    }
    await api('/api/approvals', {method: 'POST', body: JSON.stringify({id: approvalId, decision})});
    const msg = chatMessages.find(m => m.approvalId === approvalId);
    if (msg) {
      msg.approvalPending = false;
      msg.status = decision === 'approved' ? 'running' : 'denied';
    }
    renderChat();
    await load();
  } catch (error) {
    alert(error.message);
  }
}

function pressureClass(percent, warning = 75, critical = 90) {
  const value = Number(percent || 0);
  return value >= critical ? 'critical' : (value >= warning ? 'warning' : 'normal');
}

function renderCapacity() {
  const target = $('capacityMetrics');
  const stats = snapshot.stats;
  if (!target) return;
  if (!stats?.host) {
    target.innerHTML = '<p class="muted">System telemetry is unavailable.</p>';
    return;
  }
  const host = stats.host;
  const memory = host.memory || {};
  const swap = host.swap || {};
  const ollama = stats.ai_runtimes?.ollama || {};
  const rows = [
    ['RAM', `${Number(memory.percent || 0).toFixed(0)}%`, memory.formatted || 'unknown', pressureClass(memory.percent)],
    ['CPU', `${Number(host.cpu_percent || 0).toFixed(0)}%`, `${host.cpu_count || '?'} logical cores`, pressureClass(host.cpu_percent, 80, 95)],
    ['Swap', `${Number(swap.gb || 0).toFixed(1)} GB`, `${Number(swap.percent || 0).toFixed(0)}% allocated`, pressureClass(swap.percent, 25, 60)],
    ['Local models', String(ollama.loaded_models_count || 0), ollama.total_vram_formatted || '0 GB in memory', ollama.available ? 'normal' : 'warning'],
  ];
  target.innerHTML = rows.map(([label, value, detail, state]) => `
    <article class="capacity-card ${esc(state)}">
      <span>${esc(label)}</span><strong>${esc(value)}</strong><small>${esc(detail)}</small>
    </article>`).join('');
  if ($('capacitySource')) $('capacitySource').textContent = `${host.metrics_source || 'native counters'} · ${new Date(stats.timestamp).toLocaleTimeString()}`;
  const processes = host.top_processes || [];
  if ($('topProcesses')) $('topProcesses').innerHTML = processes.map(row => `
    <div><span>${esc(row.name)} <small>PID ${esc(row.pid)}</small></span><strong>${Number(row.memory_gb || 0).toFixed(2)} GB</strong></div>
  `).join('') || '<p class="muted">No process inventory available.</p>';
}

function renderFleet() {
  const mapping = {hermes: 'fleetHermes', jaeger: 'fleetJaeger', openclaw: 'fleetOpenClaw'};
  for (const [agent, elementId] of Object.entries(mapping)) {
    const element = $(elementId);
    if (!element) continue;
    const probe = snapshot.probes[agent] || {};
    const online = Boolean(probe.available || probe.ok || probe.status === 'ok' || probe.status === 'ready');
    element.classList.toggle('offline', !online);
    element.title = online ? `${agent} owner endpoint responded` : (probe.error || probe.message || `${agent} unavailable`);
  }
  const gateway = $('fleetGateway');
  if (gateway) gateway.classList.remove('offline');
}

function render() {
  const running = snapshot.runs.filter(run => run.status === 'running').length;
  const pendingApprovals = snapshot.approvals.filter(row => row.status === 'pending');

  $('system').innerHTML = `<div class="tag">Controller</div><h2>${snapshot.paused ? 'Paused' : 'Ready'}</h2><p>${snapshot.agents.length} agents · ${running} active runs · ${pendingApprovals.length} pending approvals</p>`;
  $('pause').textContent = snapshot.paused ? 'Resume all' : 'Pause all';
  renderFleet();
  renderCapacity();

  const previousAgent = $('systemAgent').value;
  $('systemAgent').innerHTML = snapshot.agents.map(agent =>
    `<option value="${esc(agent.id)}">${esc(agent.name)}</option>`
  ).join('');
  const selectedAgent = snapshot.agents.some(agent => agent.id === previousAgent)
    ? previousAgent
    : (snapshot.agents.some(agent => agent.id === 'hermes') ? 'hermes' : snapshot.agents[0]?.id || '');
  $('systemAgent').value = selectedAgent;
  $('agentPills').innerHTML = snapshot.agents.map(agent => `
    <button type="button" class="agent-pill ${agent.id === selectedAgent ? 'active' : ''}"
      data-agent="${esc(agent.id)}">${esc(agentDisplay(agent.id))}</button>
  `).join('');

  $('agents').innerHTML = snapshot.agents.map(agent => {
    const directUrl = serviceUrl(agent.runtime);
    return `
    <article class="card">
      <div class="status">Configured</div>
      <h3>${esc(agent.name)}</h3>
      <p>${esc(agent.identity)}</p>
      <div class="muted">${esc(agent.runtime)} · ${esc(agent.model_provider || 'owner-default')} · ${esc(agent.model_location || 'owner-default')} · ${esc(agent.model || 'agent default')}</div>
      <div class="actions">
        ${directUrl ? `<a class="button" href="${esc(directUrl)}" target="_blank" rel="noopener">Open UI</a>` : ''}
        <button class="primary" onclick="wake('${esc(agent.id)}')">Wake</button>
        ${agent.runtime === 'hermes' ? `<button onclick="configure('${esc(agent.id)}')">Configure</button>` : ''}
      </div>
    </article>`;
  }).join('') || '<p class="muted">No agents configured.</p>';

  $('modelRoutes').innerHTML = snapshot.models.map(provider => `
    <article class="card model-route ${esc(provider.location)}">
      <div class="status">${esc(provider.location)}</div>
      <h3>${esc(provider.label)}</h3>
      <div class="model-list">${(provider.models || []).map(model => `<code>${esc(model.id)}</code>`).join('') || '<span class="muted">No suitable models available</span>'}</div>
    </article>`).join('') || '<p class="muted">Ollama model inventory is unavailable.</p>';

  $('integrations').innerHTML = snapshot.integrations.map(item => `
    <article class="card">
      <div class="status">${esc(item.state || item.mode)}</div>
      <h3>${esc(item.id)}</h3>
      <p>${esc(item.kind)} · ${item.installed === false ? 'not installed' : (item.configured ? 'configured' : 'installed')}</p>
      ${item.detail ? `<p class="muted">${esc(item.detail)}</p>` : ''}
      <div class="muted">Risk: ${esc(item.risk)} · Authority: ${esc(item.authority)}</div>
    </article>`).join('') || '<p class="muted">No integrations discovered.</p>';

  $('goalAgent').innerHTML = snapshot.agents.map(agent => `<option value="${esc(agent.id)}">${esc(agent.name)}</option>`).join('');
  $('goals').innerHTML = snapshot.goals.map(goal => `<div class="row"><div><span class="tag">${esc(goal.status)}</span><strong>${esc(goal.objective)}</strong><p>${esc(goal.agent_id)}</p></div><button onclick="wake('${esc(goal.agent_id)}','${esc(goal.id)}')">Run</button></div>`).join('') || '<p class="muted">No goals yet.</p>';

  // Approvals are deliberately individual: informed consent cannot be bulked.
  if (pendingApprovals.length === 0) {
    $('approvals').innerHTML = '<p class="muted">Nothing waiting.</p>';
    $('approvalsHeader').innerHTML = '<h2>Pending approvals</h2>';
  } else {
    $('approvalsHeader').innerHTML = `
      <h2>Pending approvals <span class="count-badge">${pendingApprovals.length}</span></h2>`;
    $('approvals').innerHTML = pendingApprovals.map(row => {
      const info = parseApproval(row);
      const agentLabel = info.agentId ? `<span class="agent-badge">${esc(info.agentId)}</span>` : '';
      const capLabel = capabilityBadge(info.capability);
      const rootLabel = info.root ? `<span class="root-badge">📁 ${esc(info.root)}</span>` : '';
      const kindLabel = info.kind !== 'generic' ? `<span class="kind-badge">${esc(info.kind)}</span>` : '';
      const informed = row.benefit && row.scope && row.duration && row.reversible && row.safer_alternative && (row.risks || []).length;
      return `<div class="row approval-row">
        <div>
          <div class="approval-header">${kindLabel}${agentLabel}${capLabel}${rootLabel}</div>
          <p class="approval-reason">${esc(info.reason)}</p>
          ${informed ? `<dl class="approval-context">
            <dt>What you gain</dt><dd>${esc(row.benefit)}</dd>
            <dt>What could go wrong</dt><dd><ul>${row.risks.map(risk => `<li>${esc(risk)}</li>`).join('')}</ul></dd>
            <dt>Exact scope</dt><dd>${esc(row.scope)}</dd>
            <dt>How long</dt><dd>${esc(row.duration)}</dd>
            ${row.provider ? `<dt>Provider/location</dt><dd>${esc(row.provider)}</dd>` : ''}
            ${row.data_destination ? `<dt>Data destination</dt><dd>${esc(row.data_destination)}</dd>` : ''}
            <dt>Approval expires</dt><dd>${row.expires_at ? new Date(row.expires_at * 1000).toLocaleString() : 'Legacy request; no deadline recorded'}</dd>
            <dt>Can it be undone?</dt><dd>${esc(row.reversible)}</dd>
            <dt>Safer option</dt><dd>${esc(row.safer_alternative)}</dd>
          </dl>` : `<p class="approval-warning">Cannot approve: ARES did not provide enough plain-language context. Deny and ask the agent to submit a complete request.</p>`}
        </div>
        <div class="approval-actions">
          <button onclick="approval('${row.id}','denied')">Deny</button>
          <button class="primary" ${informed ? '' : 'disabled'} onclick="approval('${row.id}','approved')">Review and approve</button>
        </div>
      </div>`;
    }).join('');
  }

  $('runs').innerHTML = snapshot.runs.slice(0, 30).map(run => `<div class="row"><div><span class="tag">${esc(run.status)}</span><strong>${esc(run.agent_id)}</strong><p>${new Date(run.created_at * 1000).toLocaleString()} · ${esc(run.trigger)}</p></div><button onclick="events('${run.id}')">Evidence</button></div>`).join('') || '<p class="muted">No runs recorded.</p>';
}

async function wake(agent, goalId = '') {
  try {
    await api(`/api/agents/${encodeURIComponent(agent)}/wake`, {
      method: 'POST',
      body: JSON.stringify({goal_id: goalId, trigger: 'dashboard', idempotency_key: crypto.randomUUID()}),
    });
    await load();
  } catch (error) {
    alert(error.message);
  }
}

async function sendSystemMessage() {
  let objective = $('systemMessage').value.trim();
  let agent = $('systemAgent').value;

  // Route any registered @agent prefix without hard-coding runtime ids.
  const tag = objective.match(/^@([A-Za-z0-9_.-]+)(?:\s+|$)/);
  if (tag && snapshot.agents.some(item => item.id.toLowerCase() === tag[1].toLowerCase())) {
    agent = snapshot.agents.find(item => item.id.toLowerCase() === tag[1].toLowerCase()).id;
    objective = objective.slice(tag[0].length).trimStart();
    selectAgentPill(agent);
  }

  if (!objective) return;
  if (!activeThreadId) {
    const created = await api('/api/threads', {
      method: 'POST', body: JSON.stringify({agent_id: agent, title: 'New conversation'}),
    });
    activeThreadId = created.id;
    window.localStorage.setItem('ares.activeThreadId', activeThreadId);
  }

  $('sendSystem').disabled = true;
  const cancelBtn = $('cancelSystem');
  if (cancelBtn) cancelBtn.style.display = 'block';

  // Push user message into chat stream
  chatMessages.push({
    role: 'user',
    text: objective,
    agent: agent,
    timestamp: Date.now(),
  });

  // Push pending assistant placeholder
  const assistantMsg = {
    role: 'assistant',
    agent: agent,
    runId: 'starting…',
    status: 'queued',
    thoughts: '',
    tools: [],
    text: '',
    approvalPending: false,
    timestamp: Date.now(),
  };
  chatMessages.push(assistantMsg);
  renderChat();

  $('systemMessage').value = '';
  $('systemResult').textContent = 'Creating a durable goal…';

  try {
    const dispatched = await api(`/api/threads/${encodeURIComponent(activeThreadId)}/messages`, {
      method: 'POST',
      body: JSON.stringify({agent_id: agent, content: objective, idempotency_key: crypto.randomUUID()}),
    });
    const run = dispatched.run;

    activeRunId = run.id;
    assistantMsg.runId = run.id;
    assistantMsg.status = run.status;
    renderChat();

    let seenEventCount = 0;
    let accumulatedText = '';
    const toolsSeen = new Set();

    activeRunPoll = setInterval(async () => {
      try {
        const [runs, eventsList] = await Promise.all([
          api('/api/runs'),
          api(`/api/runs/${run.id}/events`).catch(() => []),
        ]);

        const current = runs.find(row => row.id === run.id);
        if (!current) return;

        // Process new streaming events
        if (Array.isArray(eventsList)) {
          for (let i = seenEventCount; i < eventsList.length; i++) {
            const ev = eventsList[i];
            const data = ev.data || {};
            if (ev.type === 'text_delta' && data.text) {
              accumulatedText += data.text;
            } else if (ev.type === 'tool_result') {
              const toolKey = JSON.stringify([data.tool || data.name || 'tool', data.call_id || data.id || data]);
              if (!toolsSeen.has(toolKey)) {
                toolsSeen.add(toolKey);
                assistantMsg.tools.push(data);
              }
            } else if (ev.type === 'approval_required') {
              assistantMsg.approvalPending = true;
              assistantMsg.approvalReason = data.reason;
              assistantMsg.approvalId = data.approval_id;
            }
          }
          seenEventCount = eventsList.length;
        }

        // Update assistant message text and status
        assistantMsg.text = accumulatedText || current.result || current.error || '';
        assistantMsg.status = current.status;

        $('systemResult').textContent = `Agent: ${agent}\nRun: ${run.id}\nStatus: ${current.status}\n\n${current.result || current.error || accumulatedText || 'Working…'}`;
        renderChat();

        if (!['queued', 'running'].includes(current.status)) {
          clearInterval(activeRunPoll);
          activeRunPoll = null;
          activeRunId = null;
          $('sendSystem').disabled = false;
          if (cancelBtn) cancelBtn.style.display = 'none';
          await load();
        }
      } catch (error) {
        clearInterval(activeRunPoll);
        activeRunPoll = null;
        activeRunId = null;
        $('sendSystem').disabled = false;
        if (cancelBtn) cancelBtn.style.display = 'none';
        $('systemResult').textContent = error.message;
      }
    }, 450);

  } catch (error) {
    assistantMsg.status = 'failed';
    assistantMsg.text = `Failed to start run: ${error.message}`;
    renderChat();
    $('systemResult').textContent = error.message;
    $('sendSystem').disabled = false;
    if (cancelBtn) cancelBtn.style.display = 'none';
  }
}

async function cancelActiveRun() {
  if (!activeRunId) return;
  try {
    await api(`/api/runs/${activeRunId}/cancel`, {method: 'POST'});
    if (activeRunPoll) {
      clearInterval(activeRunPoll);
      activeRunPoll = null;
    }
    const msg = chatMessages.find(m => m.runId === activeRunId);
    if (msg) msg.status = 'cancelled';
    activeRunId = null;
    $('sendSystem').disabled = false;
    $('cancelSystem').style.display = 'none';
    renderChat();
    await load();
  } catch (error) {
    alert(error.message);
  }
}

async function approval(id, decision) {
  try {
    const row = snapshot.approvals.find(item => item.id === id);
    if (decision === 'approved') {
      const summary = `Approve this specific request?\n\nBenefit: ${row.benefit}\n\nRisks:\n- ${(row.risks || []).join('\n- ')}\n\nScope: ${row.scope}\nDuration: ${row.duration}\nReversible: ${row.reversible}\nSafer option: ${row.safer_alternative}`;
      if (!confirm(summary)) return;
    }
    await api('/api/approvals', {method: 'POST', body: JSON.stringify({id, decision})});
    await load();
  } catch (error) {
    alert(error.message);
    await load();
  }
}

async function configure(agent) {
  try {
    const data = await api(`/api/agents/${encodeURIComponent(agent)}/configuration`);
    configurationAgent = agent;
    $('configurationSoul').value = data.current.soul || '';
    $('configurationWorkspaces').value = (data.current.workspaces || []).map(row => row.path).join('\n');
    $('configurationDialog').showModal();
  } catch (error) {
    alert(error.message);
  }
}

async function events(id) {
  const rows = await api(`/api/runs/${id}/events`);
  alert(rows.map(row => `${row.type}: ${JSON.stringify(row.data)}`).join('\n\n') || 'No events');
}

function selectAgentPill(agent) {
  $('systemAgent').value = agent;
  document.querySelectorAll('.agent-pill').forEach(pill => {
    pill.classList.toggle('active', pill.dataset.agent === agent);
  });
}

// Attach Event Listeners
$('pause').onclick = async () => {
  await api(snapshot.paused ? '/api/control/resume' : '/api/control/pause', {method: 'POST', body: '{}'});
  await load();
};
$('refresh').onclick = load;
$('sendSystem').onclick = sendSystemMessage;
if ($('cancelSystem')) $('cancelSystem').onclick = cancelActiveRun;
if ($('newThread')) $('newThread').onclick = async () => {
  const agent = $('systemAgent').value || snapshot.agents[0]?.id;
  if (!agent) return;
  const created = await api('/api/threads', {
    method: 'POST', body: JSON.stringify({agent_id: agent, title: 'New conversation'}),
  });
  activeThreadId = created.id;
  window.localStorage.setItem('ares.activeThreadId', activeThreadId);
  chatMessages = [];
  await load();
};

$('systemMessage').addEventListener('keydown', event => {
  if ((event.metaKey || event.ctrlKey) && event.key === 'Enter') {
    event.preventDefault();
    sendSystemMessage();
  }
});

// Auto-switch agent pills on typing @
$('systemMessage').addEventListener('input', () => {
  const val = $('systemMessage').value.trimStart();
  const tag = val.match(/^@([A-Za-z0-9_.-]+)/);
  if (tag) {
    const match = snapshot.agents.find(item => item.id.toLowerCase() === tag[1].toLowerCase());
    if (match) selectAgentPill(match.id);
  }
});

// Event delegation also covers pills added after the agent inventory loads.
$('agentPills').addEventListener('click', event => {
  const pill = event.target.closest('.agent-pill');
  if (pill) {
    selectAgentPill(pill.dataset.agent);
    $('systemMessage').focus();
  }
});

// Setup Quick Prompts
document.querySelectorAll('.quick-prompt').forEach(btn => {
  btn.addEventListener('click', () => {
    const prompt = btn.dataset.prompt;
    const agent = btn.dataset.agent || 'hermes';
    selectAgentPill(agent);
    $('systemMessage').value = prompt;
    $('systemMessage').focus();
  });
});

$('newGoal').onclick = () => $('goalDialog').showModal();
$('saveGoal').onclick = async event => {
  event.preventDefault();
  await api('/api/goals', {method: 'POST', body: JSON.stringify({agent_id: $('goalAgent').value, objective: $('goalObjective').value})});
  $('goalDialog').close();
  $('goalObjective').value = '';
  await load();
};
$('saveConfiguration').onclick = async event => {
  event.preventDefault();
  try {
    const workspaces = $('configurationWorkspaces').value.split('\n').map(value => value.trim()).filter(Boolean);
    await api(`/api/agents/${encodeURIComponent(configurationAgent)}/configuration`, {
      method: 'PUT',
      body: JSON.stringify({soul: $('configurationSoul').value, workspaces}),
    });
    $('configurationDialog').close();
    await load();
  } catch (error) {
    alert(error.message);
  }
};

configureServiceLinks();
load().catch(error => $('system').textContent = error.message);
setInterval(load, 10000);
