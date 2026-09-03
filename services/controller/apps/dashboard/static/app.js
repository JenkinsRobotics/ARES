const $ = id => document.getElementById(id);
const esc = value => String(value ?? '').replace(
  /[&<>"']/g,
  char => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[char]),
);
let snapshot = {agents: [], goals: [], runs: [], approvals: [], paused: false};
let configurationAgent = '';
const isLocalBrowser = ['127.0.0.1', 'localhost', '::1'].includes(window.location.hostname);

// Standard service port map — local port for local browsing, Tailscale HTTPS port for remote.
// Tailscale serve maps: 443→8787 (Hermes), 8443→8785 (Jaeger), 8444→8788 (ARES).
const SERVICE_PORTS = {
  hermes:    { local: 8787,  remote: 443,   label: 'Hermes WebUI' },
  jaeger:    { local: 8790,  remote: 8443,  label: 'Jaeger WebUI' },
  openclaw:  { local: 18789, remote: null,  label: 'OpenClaw UI' },
  ares:      { local: 8788,  remote: 8444,  label: 'ARES Controller' },
  gateway:   { local: 8811,  remote: null,  label: 'Agentgateway', path: '/mcp' },
  n8n:       { local: 5678,  remote: null,  label: 'n8n', path: '/' },
  beszel:    { local: 8090,  remote: null,  label: 'Beszel Monitor', path: '/' },
};

function serviceUrl(service) {
  const cfg = SERVICE_PORTS[service];
  if (!cfg) return '';
  if (isLocalBrowser) {
    return `http://127.0.0.1:${cfg.local}${cfg.path || '/'}`;
  }
  // Remote (Tailscale) — only services with a remote port are accessible
  if (!cfg.remote) return '';
  return `https://${window.location.hostname}:${cfg.remote}${cfg.path || '/'}`;
}

function configureServiceLinks() {
  for (const [id, service] of [
    ['hermesLink', 'hermes'], ['jaegerLink', 'jaeger'], ['openclawLink', 'openclaw'],
    ['n8nLink', 'n8n'], ['gatewayLink', 'gateway'], ['beszelLink', 'beszel'],
  ]) {
    const element = $(id);
    if (!element) continue;
    const href = serviceUrl(service);
    if (href) element.href = href;
    else element.hidden = true;
  }
  // Fleet strip links (data-service attributes)
  document.querySelectorAll('.fleet-item[data-service]').forEach(function(el) {
    var href = serviceUrl(el.dataset.service);
    if (href) el.href = href;
    else el.hidden = true;
  });
}

const CONTROLLER_DOWN =
  'Controller is not running on http://127.0.0.1:8788/. Process start is owned by Core/Install — this UI will not start launchd.';

function isControllerDown(error) {
  const message = String(error?.message || error || '');
  return /failed to fetch|networkerror|load failed|econnrefused|err_connection/i.test(message);
}

function reportControllerDown() {
  const empty = $('chatEmpty');
  if (empty) {
    empty.hidden = false;
    empty.classList.add('controller-down');
    const heading = empty.querySelector('h3');
    const copy = empty.querySelector('p');
    if (heading) heading.textContent = 'Controller offline';
    if (copy) copy.textContent = CONTROLLER_DOWN;
  }
  if ($('system')) $('system').textContent = CONTROLLER_DOWN;
  if ($('siTagline')) $('siTagline').textContent = 'Controller offline';
  const send = $('sendSystem');
  const box = $('systemMessage');
  if (send) send.disabled = true;
  if (box) box.placeholder = 'Controller offline';
}

function clearControllerDown() {
  const empty = $('chatEmpty');
  if (empty) empty.classList.remove('controller-down');
  const send = $('sendSystem');
  const box = $('systemMessage');
  if (send) send.disabled = false;
  if (box) box.placeholder = `Message ${siIdentity.name || 'ARES'}`;
}

async function api(path, options = {}) {
  const headers = {'Content-Type': 'application/json', ...(options.headers || {})};
  const token = window.__ARES_BOOT__?.csrfToken;
  if (token) {
    headers['X-Ares-CSRF-Token'] = token;
    headers['X-CSRF-Token'] = token;
  }
  let response;
  try {
    response = await fetch(path, {...options, headers, credentials: 'same-origin'});
  } catch (error) {
    if (isControllerDown(error)) {
      reportControllerDown();
      throw new Error(CONTROLLER_DOWN);
    }
    throw error;
  }
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.error || data.detail || `${response.status}`);
  clearControllerDown();
  return data;
}

function stepIdFrom(result) {
  if (!result || typeof result !== 'object') return '';
  if (result.step_id) return result.step_id;
  const step = result.step;
  if (step && (step.step_id || step.id)) return step.step_id || step.id;
  if (result.gated_step_id) return result.gated_step_id;
  const steps = Array.isArray(result.steps) ? result.steps : [];
  const gated = steps.find(row => /await|pend|approv|gate/i.test(String(row.status || ''))) || steps[0];
  if (gated && (gated.step_id || gated.id)) return gated.step_id || gated.id;
  return '';
}

function needsApproval(result) {
  if (!result) return false;
  const status = String(result.status || '');
  return status === 'awaiting_approval'
    || result.needs_approval === true
    || status === 'approval_required';
}

const SI_THREAD_KEY = 'ares.si.conversation_id';
function conversationId() {
  let id = sessionStorage.getItem(SI_THREAD_KEY);
  if (!id) {
    id = (crypto.randomUUID && crypto.randomUUID()) || String(Date.now());
    sessionStorage.setItem(SI_THREAD_KEY, id);
  }
  return id;
}
function resetConversation() {
  sessionStorage.removeItem(SI_THREAD_KEY);
  conversationId();
}

let siIdentity = {name: 'ARES', owner_name: ''};

function applyIdentity(ident) {
  if (!ident) return;
  const name = ident.name || ident.si_name || 'ARES';
  const owner = ident.owner_name || ident.owner || '';
  siIdentity = {name, owner_name: owner};
  const set = (id, text) => { const el = $(id); if (el) el.textContent = text; };
  set('siName', name);
  set('siEmptyName', name);
  set('siTagline', owner ? `SI for ${owner}` : 'Your SI');
  document.title = name;
  const box = $('systemMessage');
  if (box && !box.placeholder.startsWith('Controller')) box.placeholder = `Message ${name}`;
}

function hideEmptyState() {
  const empty = $('chatEmpty');
  if (empty) empty.hidden = true;
}

function appendBubble(role, text, extra) {
  hideEmptyState();
  const stream = $('chatStream');
  if (!stream) return null;
  const row = document.createElement('div');
  row.className = `chat-row ${role}`;
  const bubble = document.createElement('div');
  bubble.className = 'chat-bubble';
  bubble.textContent = text || '';
  row.appendChild(bubble);
  if (extra) row.appendChild(extra);
  stream.appendChild(row);
  stream.scrollTop = stream.scrollHeight;
  return {row, bubble};
}

function approvalBar(planId, stepId, reason) {
  const wrap = document.createElement('div');
  wrap.className = 'chat-approval';
  if (reason) {
    const note = document.createElement('p');
    note.className = 'chat-approval-reason';
    note.textContent = reason;
    wrap.appendChild(note);
  }
  const actions = document.createElement('div');
  actions.className = 'chat-approval-actions';
  const yes = document.createElement('button');
  yes.className = 'primary';
  yes.type = 'button';
  yes.textContent = 'Approve';
  const no = document.createElement('button');
  no.type = 'button';
  no.textContent = 'Deny';
  const lock = () => { yes.disabled = true; no.disabled = true; };
  yes.onclick = async () => {
    lock();
    try {
      await api('/api/dispatch/approve', {method: 'POST', body: JSON.stringify({plan_id: planId, step_id: stepId})});
      wrap.replaceChildren(document.createTextNode('Approved. Send another message to continue.'));
    } catch (err) {
      wrap.replaceChildren(document.createTextNode(err.message));
    }
  };
  no.onclick = async () => {
    lock();
    try {
      await api('/api/dispatch/reject', {method: 'POST', body: JSON.stringify({plan_id: planId, step_id: stepId, reason: 'Owner denied'})});
      wrap.replaceChildren(document.createTextNode('Denied.'));
    } catch (err) {
      wrap.replaceChildren(document.createTextNode(err.message));
    }
  };
  actions.append(yes, no);
  wrap.appendChild(actions);
  return wrap;
}

async function attachApproval(row, result) {
  if (!row || !needsApproval(result) || !result.plan_id) return;
  let stepId = stepIdFrom(result);
  if (!stepId) {
    try {
      const plan = await api(`/api/dispatch/plan/${encodeURIComponent(result.plan_id)}`);
      stepId = stepIdFrom(plan);
    } catch {
      stepId = '';
    }
  }
  if (!stepId) return;
  row.appendChild(approvalBar(result.plan_id, stepId, result.approval_reason || result.reason || ''));
}

async function load() {
  const [agents, goals, runs, approvals] = await Promise.all([
    api('/api/agents'), api('/api/goals'), api('/api/runs'), api('/api/approvals'),
  ]);
  snapshot = {agents: agents.agents, paused: agents.paused, goals, runs, approvals};
  render();
}

function render() {
  const running = snapshot.runs.filter(run => run.status === 'running').length;
  $('system').innerHTML = `<div class="tag">Controller</div><h2>${snapshot.paused ? 'Paused' : 'Ready'}</h2><p>${snapshot.agents.length} agents · ${running} active runs · ${snapshot.approvals.filter(row => row.status === 'pending').length} pending approvals</p>`;
  $('pause').textContent = snapshot.paused ? 'Resume all' : 'Pause all';
  $('agents').innerHTML = snapshot.agents.map(agent => `
    <article class="card">
      <div class="status">Configured</div>
      <h3>${esc(agent.name)}</h3>
      <p>${esc(agent.identity)}</p>
      <div class="muted">${esc(agent.runtime)} · ${esc(agent.model || 'agent default')}</div>
      <div class="actions">
        <a class="button" href="${serviceUrl(agent.runtime)}">Open UI</a>
        <button class="primary" onclick="wake('${esc(agent.id)}')">Wake</button>
        ${agent.runtime === 'hermes' ? `<button onclick="configure('${esc(agent.id)}')">Configure</button>` : ''}
      </div>
    </article>`).join('') || '<p class="muted">No agents configured.</p>';
  $('goalAgent').innerHTML = snapshot.agents.map(agent => `<option value="${esc(agent.id)}">${esc(agent.name)}</option>`).join('');
  $('goals').innerHTML = snapshot.goals.map(goal => `<div class="row"><div><span class="tag">${esc(goal.status)}</span><strong>${esc(goal.objective)}</strong><p>${esc(goal.agent_id)}</p></div><button onclick="wake('${esc(goal.agent_id)}','${esc(goal.id)}')">Run</button></div>`).join('') || '<p class="muted">No goals yet.</p>';
  $('approvals').innerHTML = snapshot.approvals.filter(row => row.status === 'pending').map(row => `<div class="row"><div><strong>${esc(row.operation)}</strong><p>${esc(row.reason)}</p></div><div><button onclick="approval('${row.id}','denied')">Deny</button><button class="primary" onclick="approval('${row.id}','approved')">Approve</button></div></div>`).join('') || '<p class="muted">Nothing waiting.</p>';
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
  const objective = $('systemMessage').value.trim();
  if (!objective) return;
  $('sendSystem').disabled = true;
  $('systemMessage').value = '';
  appendBubble('user', objective);
  const pending = appendBubble('si', '…');
  try {
    const result = await api('/api/dispatch/turn', {
      method: 'POST',
      body: JSON.stringify({
        message: objective,
        conversation_id: conversationId(),
        local_only_mode: false,
        si_name: siIdentity.name || 'ARES',
        owner_name: siIdentity.owner_name || 'User',
      }),
    });
    const text = result.output || result.content || result.error || result.reason || result.approval_reason || JSON.stringify(result);
    if (pending) pending.bubble.textContent = text;
    if (pending) await attachApproval(pending.row, result);
    if ($('systemResult')) {
      $('systemResult').textContent = typeof text === 'string' ? text : JSON.stringify(result);
    }
    await load();
  } catch (error) {
    if (pending) pending.bubble.textContent = error.message;
    if ($('systemResult')) $('systemResult').textContent = error.message;
  } finally {
    $('sendSystem').disabled = false;
    $('systemMessage').focus();
  }
}

async function approval(id, decision) {
  try {
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

$('pause').onclick = async () => {
  await api(snapshot.paused ? '/api/control/resume' : '/api/control/pause', {method: 'POST', body: '{}'});
  await load();
};
$('refresh').onclick = load;
$('sendSystem').onclick = sendSystemMessage;
$('systemMessage').addEventListener('keydown', event => {
  if (event.key === 'Enter' && !event.shiftKey) {
    event.preventDefault();
    sendSystemMessage();
  }
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
api('/api/si/identity').then(applyIdentity).catch(error => {
  if (isControllerDown(error) || /controller is not running/i.test(String(error?.message || ''))) {
    reportControllerDown();
    return;
  }
  applyIdentity({name: 'ARES', owner_name: ''});
});
const newThreadBtn = $('newThread');
if (newThreadBtn) newThreadBtn.onclick = () => {
  resetConversation();
  const stream = $('chatStream');
  const empty = $('chatEmpty');
  if (stream) {
    [...stream.querySelectorAll('.chat-row')].forEach(n => n.remove());
  }
  if (empty) empty.hidden = false;
};
load().catch(error => {
  if (isControllerDown(error) || /controller is not running/i.test(String(error.message || ''))) {
    reportControllerDown();
    return;
  }
  if ($('system')) $('system').textContent = error.message;
});
setInterval(load, 10000);
