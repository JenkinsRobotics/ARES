const $ = id => document.getElementById(id);
const esc = value => String(value ?? '').replace(
  /[&<>"']/g,
  char => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[char]),
);
let snapshot = {agents: [], goals: [], runs: [], approvals: [], paused: false};
let configurationAgent = '';

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
        <a class="button" href="${agent.runtime === 'hermes' ? 'http://127.0.0.1:8787' : 'http://127.0.0.1:8790'}">Open UI</a>
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

load().catch(error => $('system').textContent = error.message);
setInterval(load, 10000);
