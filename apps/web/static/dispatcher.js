// ─────────────────────────────────────────────────────────────────────────────
// ARES Dispatcher — Claude-Inspired Persistent Mission Control Canvas
// ─────────────────────────────────────────────────────────────────────────────

const DISPATCHER_SESSION_KEY = 'ares-dispatcher-session-id';
const DISPATCHER_STATE_KEY = 'ares-dispatcher-state';
const DISPATCHER_TITLE = 'Dispatcher';

const DISPATCHER_PERMISSIONS = [
  {id: 'auto', label: 'Auto', mode: 'auto', desc: 'Ares handles permission decisions', shortcut: '1'},
  {id: 'manual', label: 'Manual', mode: 'manual', desc: 'Always ask before making changes', shortcut: '2'},
  {id: 'edits', label: 'Accept edits', mode: 'auto', desc: 'Automatically accept all file edits', shortcut: '3'},
  {id: 'plan', label: 'Plan', mode: 'plan', desc: 'Create a plan before making changes', shortcut: '4'},
];

const DISPATCHER_SLASH_COMMANDS = [
  {name: '/schedule', desc: 'Schedule recurring background routines or timers'},
  {name: '/plan', desc: 'Switch to planning mode before making changes'},
  {name: '/diff', desc: 'Review uncommitted changes in current workspace'},
  {name: '/fork', desc: 'Fork this turn into a new branch/session'},
  {name: '/rewind', desc: 'Rollback conversation to a previous turn'},
  {name: '/mcp', desc: 'Manage Model Context Protocol servers and tools'},
  {name: '/skills', desc: 'Browse and execute workspace skills'},
  {name: '/feedback', desc: 'Submit telemetry or workflow feedback'},
  {name: '/usage', desc: 'View detailed token consumption and quotas'},
  {name: '/cd', desc: 'Change working directory or repository scope'},
];

let _dispatcherState = {
  keepAlive: true,
  mobileNotifs: true,
  permission: 'auto',
  bypassPermissions: false,
  effort: 'high',
  fastMode: false,
  hudCollapsed: false,
  outputsCollapsed: false,
  pins: [],
};

let _chatSessionBeforeDispatcher = null;
let _dispatcherHealthy = true;
let _dispatcherHealthTimer = null;
let _dispatcherSuggestItems = [];
let _dispatcherSuggestIndex = 0;
let _dispatcherSuggestMode = '';
let _activePopover = null;

function _dispatcherEsc(value) {
  if (typeof esc === 'function') return esc(value);
  return String(value ?? '').replace(/[&<>"']/g, c => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
  }[c]));
}

function _readDispatcherState() {
  try {
    const raw = localStorage.getItem(DISPATCHER_STATE_KEY);
    if (!raw) return;
    const parsed = JSON.parse(raw);
    if (!parsed || typeof parsed !== 'object') return;
    if (typeof parsed.keepAlive === 'boolean') _dispatcherState.keepAlive = parsed.keepAlive;
    if (typeof parsed.mobileNotifs === 'boolean') _dispatcherState.mobileNotifs = parsed.mobileNotifs;
    if (DISPATCHER_PERMISSIONS.some(p => p.id === parsed.permission)) _dispatcherState.permission = parsed.permission;
    if (typeof parsed.bypassPermissions === 'boolean') _dispatcherState.bypassPermissions = parsed.bypassPermissions;
    if (typeof parsed.effort === 'string') _dispatcherState.effort = parsed.effort;
    if (typeof parsed.fastMode === 'boolean') _dispatcherState.fastMode = parsed.fastMode;
    if (typeof parsed.hudCollapsed === 'boolean') _dispatcherState.hudCollapsed = parsed.hudCollapsed;
    if (typeof parsed.outputsCollapsed === 'boolean') _dispatcherState.outputsCollapsed = parsed.outputsCollapsed;
    if (Array.isArray(parsed.pins)) {
      _dispatcherState.pins = parsed.pins.filter(p => typeof p === 'string' && p.trim()).slice(0, 24);
    }
  } catch (_) {}
}

function _writeDispatcherState() {
  try { localStorage.setItem(DISPATCHER_STATE_KEY, JSON.stringify(_dispatcherState)); } catch (_) {}
}

function _dispatcherSessionId() {
  try { return localStorage.getItem(DISPATCHER_SESSION_KEY) || ''; } catch (_) { return ''; }
}

function _setDispatcherSessionId(sid) {
  if (!sid) return;
  try { localStorage.setItem(DISPATCHER_SESSION_KEY, sid); } catch (_) {}
}

function _isDispatcherPanel() {
  return typeof _currentPanel !== 'undefined' && _currentPanel === 'dispatcher';
}

function _isDispatcherSession(session) {
  if (!session || !session.session_id) return false;
  const stored = _dispatcherSessionId();
  if (stored && session.session_id === stored) return true;
  return String(session.title || '') === DISPATCHER_TITLE;
}

function _workspaceShort(path) {
  const raw = String(path || '').replace(/\\/g, '/').replace(/\/+$/, '');
  if (!raw) return '';
  const parts = raw.split('/').filter(Boolean);
  if (parts.length <= 2) return raw.startsWith('/') ? raw : '/' + raw;
  return '/' + parts.slice(-2).join('/');
}

function _dispatcherTimestamp(message) {
  const raw = message && (message._ts || message.timestamp || message.created_at);
  const n = Number(raw);
  if (Number.isFinite(n) && n > 0) return n < 1e12 ? n * 1000 : n;
  return 0;
}

function _dispatcherClock(ts) {
  if (!ts) return '';
  try {
    return new Date(ts).toLocaleTimeString([], {hour: 'numeric', minute: '2-digit'});
  } catch (_) { return ''; }
}

function _dispatcherDayLabel(ts) {
  if (!ts) return '';
  try {
    return new Date(ts).toLocaleString([], {
      weekday: 'long', month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit',
    });
  } catch (_) { return ''; }
}

function _dispatcherMarkdown(text) {
  const source = String(text || '');
  const host = document.createElement('div');
  if (window.smd && typeof window.smd.parser === 'function' && typeof window.smd.default_renderer === 'function') {
    try {
      const renderer = window.smd.default_renderer(host);
      const parser = window.smd.parser(renderer);
      window.smd.parser_write(parser, source);
      window.smd.parser_end(parser);
      return host.innerHTML || '<p></p>';
    } catch (_) {}
  }
  return '<p>' + _dispatcherEsc(source).replace(/\n/g, '<br>') + '</p>';
}

function _dispatcherToolCategory(name) {
  const n = String(name || '').toLowerCase();
  if (n.includes('list') || n.includes('dir') || n.includes('ls')) return {icon: '📁', verb: 'listed files in'};
  if (n.includes('read') || n.includes('file_view') || n.includes('cat') || n.includes('view_file')) return {icon: '📄', verb: 'read'};
  if (n.includes('write') || n.includes('replace') || n.includes('edit') || n.includes('patch') || n.includes('modify')) return {icon: '✏️', verb: 'edited'};
  if (n.includes('run') || n.includes('terminal') || n.includes('bash') || n.includes('command') || n.includes('exec')) return {icon: '⚡', verb: 'ran'};
  if (n.includes('search') || n.includes('grep') || n.includes('find')) return {icon: '🔍', verb: 'searched'};
  if (n.includes('memory') || n.includes('remember')) return {icon: '🧠', verb: 'remembered'};
  if (n.includes('web') || n.includes('browse') || n.includes('fetch')) return {icon: '🌐', verb: 'fetched'};
  if (n.startsWith('mcp')) return {icon: '🔌', verb: 'invoked'};
  return {icon: '🛠️', verb: 'ran'};
}

function _dispatcherToolTimeline(message, agentName) {
  const tools = [];
  if (Array.isArray(message && message.tool_calls)) {
    for (const tc of message.tool_calls) {
      if (!tc) continue;
      const rawName = String(tc.name || (tc.function && tc.function.name) || 'tool').replace(/^functions\./, '');
      let args = tc.args || {};
      if (tc.function && tc.function.arguments && typeof tc.function.arguments === 'string') {
        try { args = JSON.parse(tc.function.arguments); } catch (_) { args = {raw: tc.function.arguments}; }
      }
      tools.push({
        name: rawName,
        args: args,
        snippet: tc.snippet || tc.result || tc.output || '',
        preview: tc.preview || '',
        done: tc.done !== false,
        is_error: !!tc.is_error,
      });
    }
  }
  if (Array.isArray(message && message.content)) {
    for (const part of message.content) {
      if (part && part.type === 'tool_use' && part.name) {
        tools.push({
          name: String(part.name),
          args: part.input || {},
          snippet: '',
          preview: '',
          done: true,
          is_error: false,
        });
      }
    }
  }
  if (!tools.length) return '';

  const who = agentName || 'Ares';
  const rowsHtml = tools.map(t => {
    const cat = _dispatcherToolCategory(t.name);
    let target = '';
    if (t.args && typeof t.args === 'object') {
      target = t.args.path || t.args.file_path || t.args.command || t.args.query || t.args.target || t.args.url || '';
      if (typeof target === 'string' && target.length > 80) target = target.slice(0, 77) + '…';
    }
    const statusText = t.done ? (t.is_error ? '✕ Failed' : '✓') : '⚡ Running';
    const statusClass = t.done ? (t.is_error ? 'is-error' : 'is-ok') : 'is-busy';
    const detailContent = [
      Object.keys(t.args || {}).length ? 'Arguments:\n' + JSON.stringify(t.args, null, 2) : '',
      t.snippet ? '\nOutput:\n' + t.snippet : (t.preview ? '\nPreview:\n' + t.preview : '')
    ].filter(Boolean).join('\n');

    return `
      <div class="dispatcher-tool-row" onclick="this.classList.toggle('is-open')">
        <span class="dispatcher-tool-icon">${cat.icon}</span>
        <span class="dispatcher-tool-action">${_dispatcherEsc(who)} ${cat.verb} ${target ? `<span class="dispatcher-tool-target">${_dispatcherEsc(target)}</span>` : `<code>${_dispatcherEsc(t.name)}</code>`}</span>
        <span class="dispatcher-tool-status ${statusClass}">${statusText}</span>
        ${detailContent ? `<span class="dispatcher-tool-chevron">▶</span>` : ''}
      </div>
      ${detailContent ? `<div class="dispatcher-tool-detail">${_dispatcherEsc(detailContent)}</div>` : ''}
    `;
  }).join('');

  return `<div class="dispatcher-tool-timeline">${rowsHtml}</div>`;
}

function _dispatcherToolPills(message) {
  const calls = [];
  if (Array.isArray(message && message.tool_calls)) {
    for (const tc of message.tool_calls) {
      const name = (tc && (tc.name || (tc.function && tc.function.name))) || '';
      if (name) calls.push(String(name).replace(/^functions\./, ''));
    }
  }
  if (Array.isArray(message && message.content)) {
    for (const part of message.content) {
      if (part && part.type === 'tool_use' && part.name) calls.push(String(part.name));
    }
  }
  return calls;
}

function _syncDispatcherPermissionToAgent() {
  const spec = DISPATCHER_PERMISSIONS.find(p => p.id === _dispatcherState.permission) || DISPATCHER_PERMISSIONS[0];
  if (typeof setAgentMode === 'function') setAgentMode(spec.mode, {toast: false});
}

function _closeAllPopovers() {
  const popovers = document.querySelectorAll('.dispatcher-popover');
  popovers.forEach(p => p.hidden = true);
  _activePopover = null;
}

function _togglePopover(id) {
  const target = $(id);
  if (!target) return;
  const isHidden = target.hidden;
  _closeAllPopovers();
  _closeDispatcherSuggest();
  if (isHidden) {
    target.hidden = false;
    _activePopover = id;
    if (id === 'dispatcherModelsPopover') _fillDispatcherModels();
  }
}

function _fillDispatcherModels() {
  const list = $('dispatcherModelList');
  if (!list) return;
  const currentModel = (S && S.session && S.session.model) || 'qwen3.5:397b';
  const available = (S && Array.isArray(S.models) && S.models.length)
    ? S.models.map(m => typeof m === 'string' ? m : (m.id || m.name || '')).filter(Boolean)
    : ['Opus 5', 'Sonnet 5', 'Haiku 4.5', 'qwen3.5:397b', 'llama3.3:70b'];

  const items = [];
  available.forEach((mod, idx) => {
    const isSelected = mod === currentModel || (idx === 0 && !available.includes(currentModel));
    const shortcut = idx < 4 ? String(idx + 1) : '';
    items.push(`
      <button type="button" class="dispatcher-model-option ${isSelected ? 'is-selected' : ''}" data-model="${_dispatcherEsc(mod)}">
        <div class="dispatcher-model-option-left">
          <span>${_dispatcherEsc(mod)}</span>
          ${isSelected ? '<span class="dispatcher-tag">Default</span>' : ''}
        </div>
        <div class="dispatcher-model-option-right">
          ${isSelected ? '<span class="dispatcher-check-blue">✓</span>' : ''}
          ${shortcut ? `<span class="dispatcher-shortcut">${shortcut}</span>` : ''}
        </div>
      </button>
    `);
  });

  list.innerHTML = items.join('');
}

async function ensureDispatcherSession() {
  const stored = _dispatcherSessionId();
  const current = S && S.session ? S.session : null;
  if (current && _isDispatcherSession(current)) {
    _setDispatcherSessionId(current.session_id);
    return current.session_id;
  }
  const cached = (typeof _allSessions !== 'undefined' && Array.isArray(_allSessions) ? _allSessions : [])
    .find(s => s && (s.session_id === stored || String(s.title || '') === DISPATCHER_TITLE));
  const target = (cached && cached.session_id) || stored;
  if (target && typeof loadSession === 'function') {
    try {
      await loadSession(target);
      if (S.session && S.session.session_id === target) {
        _setDispatcherSessionId(target);
        return target;
      }
    } catch (_) {}
  }
  if (typeof newSession === 'function') {
    await newSession(false, {worktree: false});
  }
  const created = S && S.session && S.session.session_id;
  if (!created) return '';
  _setDispatcherSessionId(created);
  try {
    await api('/api/session/rename', {method: 'POST', body: JSON.stringify({session_id: created, title: DISPATCHER_TITLE})});
    S.session.title = DISPATCHER_TITLE;
  } catch (_) {}
  try {
    await api('/api/session/pin', {method: 'POST', body: JSON.stringify({session_id: created, pinned: true})});
    S.session.pinned = true;
  } catch (_) {}
  return created;
}

async function loadDispatcher() {
  _readDispatcherState();
  const current = S && S.session && S.session.session_id;
  if (current && !_isDispatcherSession(S.session)) _chatSessionBeforeDispatcher = current;
  document.body.classList.add('dispatcher-active');
  await ensureDispatcherSession();
  _syncDispatcherPermissionToAgent();
  renderDispatcherSidebar();
  renderDispatcherTimeline();
  syncDispatcherChrome();
  _bindDispatcherOnce();
  _startDispatcherHealth();
  _fetchGitHudState();
  if (typeof _closeMobileSidebarAfterPanelSelection === 'function') _closeMobileSidebarAfterPanelSelection();
  const input = $('dispatcherInput');
  if (input) setTimeout(() => { try { input.focus(); } catch (_) {} }, 40);
}

async function leaveDispatcher(nextPanel) {
  document.body.classList.remove('dispatcher-active');
  _stopDispatcherHealth();
  _closeDispatcherSuggest();
  _closeAllPopovers();
  const menu = $('dispatcherMenu');
  if (menu) menu.hidden = true;
  if (nextPanel === 'chat' && _chatSessionBeforeDispatcher && typeof loadSession === 'function') {
    const sid = _chatSessionBeforeDispatcher;
    _chatSessionBeforeDispatcher = null;
    if (!(S.session && S.session.session_id === sid)) await loadSession(sid);
  }
}

function renderDispatcherSidebar() {
  const mount = $('dispatcherBrief');
  if (!mount) return;
  const ws = (S.session && S.session.workspace) || '';
  const daemon = _dispatcherState.keepAlive && _dispatcherHealthy;
  const pins = _dispatcherState.pins || [];
  mount.innerHTML =
    `<div class="dispatcher-brief-card">
      <div class="dispatcher-brief-kicker">${_dispatcherEsc(t('dispatcher_brief_session') || 'Persistent session')}</div>
      <div class="dispatcher-brief-copy">${_dispatcherEsc(t('dispatcher_brief_copy') || 'One uninterrupted thread with the autonomous agent. Scratchpad chats stay in Chat.')}</div>
    </div>
    <div class="dispatcher-brief-card">
      <div class="dispatcher-brief-kicker">${_dispatcherEsc(t('dispatcher_brief_daemon') || 'Daemon')}</div>
      <div class="dispatcher-brief-copy">${daemon
        ? _dispatcherEsc(t('dispatcher_daemon_active') || 'Daemon active')
        : _dispatcherEsc(t('dispatcher_daemon_paused') || 'Daemon paused')}</div>
    </div>
    <div class="dispatcher-brief-card">
      <div class="dispatcher-brief-kicker">${_dispatcherEsc(t('dispatcher_brief_workspace') || 'Workspace')}</div>
      <div class="dispatcher-brief-copy">${_dispatcherEsc(ws || (t('dispatcher_no_workspace') || 'No workspace bound'))}</div>
    </div>
    <div class="dispatcher-brief-card">
      <div class="dispatcher-brief-kicker">${_dispatcherEsc(t('dispatcher_brief_pins') || 'Pinned')}</div>
      ${pins.length
        ? `<div class="dispatcher-brief-list">${pins.map(p => `<button type="button" class="dispatcher-pin" data-pin="${_dispatcherEsc(p)}"><span class="dispatcher-pin-name">@${_dispatcherEsc(p)}</span></button>`).join('')}</div>`
        : `<div class="dispatcher-empty-hint">${_dispatcherEsc(t('dispatcher_pins_empty') || 'Pin files or folders from the command deck.')}</div>`}
    </div>`;
}

function _dispatcherVisibleMessages() {
  const rows = [];
  for (const message of (S && Array.isArray(S.messages) ? S.messages : [])) {
    if (!message || !message.role || message.role === 'tool') continue;
    if (typeof _messageIsRenderable === 'function' && !_messageIsRenderable(message)) continue;
    rows.push(message);
  }
  return rows;
}

function renderDispatcherTimeline() {
  const root = $('dispatcherTimeline');
  if (!root) return;
  const messages = _dispatcherVisibleMessages();
  const agentName = (typeof assistantDisplayName === 'function' && assistantDisplayName()) || 'Ares';
  const ws = (S.session && S.session.workspace) || '';

  if (!messages.length) {
    const now = new Date();
    const dateLabel = now.toLocaleString([], {weekday: 'long', month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit'});
    root.innerHTML =
      `<div class="dispatcher-day">${_dispatcherEsc(dateLabel)}</div>
      <article class="dispatcher-event is-agent dispatcher-welcome">
        <div class="dispatcher-bubble">
          <div class="dispatcher-bubble-head"><span class="dispatcher-who">${_dispatcherEsc(agentName)}</span><span class="dispatcher-when">${_dispatcherEsc(t('dispatcher_persistent_agent') || 'Persistent agent')}</span></div>
          <div class="dispatcher-bubble-body">
            <p>Hey, glad you're here. Tell me what's on your plate, no ask is too big or small. You could ask me to:</p>
            <ul class="dispatcher-welcome-bullets">
              <li>Find a confirmation in Downloads and check the order status on the site.</li>
              <li>Open a GitHub project on your computer, make a quick code change, and run the tests.</li>
              <li>Scan Slack for a bug report, find the file, and open a Code session to fix it.</li>
              <li>Search your repos for an error message and trace where it comes from.</li>
            </ul>
            <p style="font-size:12px;color:var(--dispatcher-muted);margin-top:8px">This thread survives reboots and daemon restarts. Type <code>/</code> for commands or <code>@</code> to attach a file or folder.</p>
          </div>
        </div>
      </article>`;
    return;
  }

  const html = [];
  let lastDay = '';
  for (const message of messages) {
    const ts = _dispatcherTimestamp(message);
    const day = _dispatcherDayLabel(ts);
    if (day && day !== lastDay) {
      html.push(`<div class="dispatcher-day">${_dispatcherEsc(day)}</div>`);
      lastDay = day;
    }
    const isUser = message.role === 'user';
    const who = isUser
      ? (t('dispatcher_you') || 'You')
      : agentName;
    const body = typeof msgContent === 'function' ? msgContent(message) : String(message.content || '');
    let cleanBody = body;
    let reasoning = message.reasoning || '';
    if (typeof _extractInlineThinkingFromContent === 'function') {
      const extracted = _extractInlineThinkingFromContent(body, reasoning);
      reasoning = extracted.reasoning || reasoning;
      cleanBody = extracted.displayText || body;
    } else if (cleanBody.includes('<think>')) {
      const match = cleanBody.match(/<think>([\s\S]*?)<\/think>/i);
      if (match) {
        reasoning = match[1];
        cleanBody = cleanBody.replace(/<think>[\s\S]*?<\/think>/gi, '').trim();
      }
    }

    const thoughtHtml = reasoning ? `
      <div class="dispatcher-thought-block">
        <div class="dispatcher-thought-header" onclick="this.parentElement.classList.toggle('is-open')">
          <span class="dispatcher-thought-icon">💭</span>
          <span class="dispatcher-thought-label">Thought process</span>
          <span class="dispatcher-thought-chevron">▶</span>
        </div>
        <div class="dispatcher-thought-body">${_dispatcherMarkdown(reasoning)}</div>
      </div>
    ` : '';

    const toolTimeline = _dispatcherToolTimeline(message, who);
    html.push(
      `<article class="dispatcher-event ${isUser ? 'is-user' : 'is-agent'}">
        <div class="dispatcher-bubble">
          <div class="dispatcher-bubble-head"><span class="dispatcher-who">${_dispatcherEsc(who)}</span><span class="dispatcher-when">${_dispatcherEsc(_dispatcherClock(ts))}</span></div>
          ${thoughtHtml}
          ${toolTimeline || ''}
          <div class="dispatcher-bubble-body">${_dispatcherMarkdown(cleanBody)}</div>
        </div>
      </article>`
    );
  }
  if (S && S.busy) {
    html.push(
      `<div class="dispatcher-pills" style="justify-content:flex-start;margin:8px 0 0 4px"><span class="dispatcher-pill is-ok" style="border-color:var(--dispatcher-amber);color:var(--dispatcher-amber)">⚡ ${_dispatcherEsc(t('dispatcher_working') || 'Ares is executing…')}</span></div>`
    );
  }
  root.innerHTML = html.join('');
  root.scrollTop = root.scrollHeight;
}

function _dispatcherOutputs() {
  if (typeof collectSessionArtifacts === 'function') {
    try { return collectSessionArtifacts() || []; } catch (_) {}
  }
  return [];
}

function renderDispatcherOutputs() {
  const list = $('dispatcherOutputs');
  const count = $('dispatcherOutputCount');
  const items = _dispatcherOutputs();
  if (count) count.textContent = String(items.length);
  if (!list) return;
  if (!items.length) {
    list.innerHTML = `<div class="dispatcher-empty-hint">${_dispatcherEsc(t('dispatcher_outputs_empty') || 'Files, diffs, and reports land here as Ares writes them.')}</div>`;
    return;
  }
  list.innerHTML = items.slice(0, 24).map(item => {
    const path = item.path || item;
    const kind = item.source || item.kind || 'file';
    return `<button type="button" class="dispatcher-output" data-path="${_dispatcherEsc(path)}"><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="opacity:0.7"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/></svg><span class="dispatcher-output-name">${_dispatcherEsc(path)}</span><span class="dispatcher-faint">${_dispatcherEsc(kind)}</span></button>`;
  }).join('');
}

function renderDispatcherPins() {
  const row = $('dispatcherPinRow');
  if (!row) return;
  row.innerHTML = (_dispatcherState.pins || []).map(path =>
    `<span class="dispatcher-pin-chip">@${_dispatcherEsc(path)}<button type="button" data-unpin="${_dispatcherEsc(path)}" aria-label="${_dispatcherEsc(t('dispatcher_unpin') || 'Unpin')}">✕</button></span>`
  ).join('');
}

async function _fetchGitHudState() {
  const repoEl = $('dispatcherGitRepo');
  const branchEl = $('dispatcherGitBranch');
  const addEl = $('dispatcherDiffAdd');
  const delEl = $('dispatcherDiffDel');
  const ws = (S && S.session && S.session.workspace) || '';
  if (!ws) {
    if (repoEl) repoEl.textContent = 'ARES';
    if (branchEl) branchEl.textContent = 'main';
    return;
  }
  const parts = ws.replace(/\\/g, '/').split('/').filter(Boolean);
  const repoName = parts[parts.length - 1] || 'Workspace';
  if (repoEl) repoEl.textContent = repoName;

  try {
    const res = await api('/api/git/status', {method: 'POST', body: JSON.stringify({path: ws})});
    if (res && res.branch && branchEl) branchEl.textContent = res.branch;
    if (res && typeof res.insertions === 'number' && addEl) addEl.textContent = `+${res.insertions.toLocaleString()}`;
    if (res && typeof res.deletions === 'number' && delEl) delEl.textContent = `-${res.deletions.toLocaleString()}`;
  } catch (_) {
    if (branchEl) branchEl.textContent = 'main';
  }
}

function syncDispatcherChrome() {
  const hud = $('dispatcherHud');
  if (hud) {
    hud.classList.toggle('is-collapsed', !!_dispatcherState.hudCollapsed);
    hud.classList.toggle('is-outputs-collapsed', !!_dispatcherState.outputsCollapsed);
  }
  const keep = $('dispatcherKeepAlive');
  if (keep) keep.checked = !!_dispatcherState.keepAlive;
  const notifs = $('dispatcherMobileNotifs');
  if (notifs) notifs.checked = !!_dispatcherState.mobileNotifs;

  const daemon = $('dispatcherDaemonChip');
  const daemonDot = $('dispatcherDaemonDot');
  const busy = !!(S && S.busy);
  const active = _dispatcherState.keepAlive && _dispatcherHealthy;
  if (daemonDot) {
    daemonDot.classList.toggle('is-on', active && !busy);
    daemonDot.classList.toggle('is-busy', busy);
    daemonDot.classList.toggle('is-off', !active);
  }
  if (daemon) {
    const label = busy
      ? (t('dispatcher_working') || 'Working…')
      : active
        ? (t('dispatcher_daemon_active') || 'Daemon active')
        : (t('dispatcher_daemon_paused') || 'Daemon paused');
    const text = $('dispatcherDaemonLabel');
    if (text) text.textContent = label;
  }
  const wsChip = $('dispatcherWorkspaceLabel');
  if (wsChip) wsChip.textContent = _workspaceShort((S && S.session && S.session.workspace) || '') || (t('dispatcher_no_workspace') || 'No workspace');

  // Permission labels
  const permSpec = DISPATCHER_PERMISSIONS.find(p => p.id === _dispatcherState.permission) || DISPATCHER_PERMISSIONS[0];
  const hudPerm = $('dispatcherHudPermLabel');
  if (hudPerm) hudPerm.textContent = `⚡ ${permSpec.label}`;
  const pillPerm = $('dispatcherModePillLabel');
  if (pillPerm) pillPerm.textContent = permSpec.label;

  // Active option in Mode Popover
  document.querySelectorAll('.dispatcher-mode-option').forEach(opt => {
    opt.classList.toggle('is-selected', opt.getAttribute('data-mode') === _dispatcherState.permission);
  });

  // Model Labels
  const model = (S && S.session && S.session.model) || 'qwen3.5:397b';
  const modelPill = $('dispatcherModelPillLabel');
  if (modelPill) modelPill.textContent = model.length > 16 ? model.slice(0, 15) + '…' : model;

  // Effort Label
  const effortPill = $('dispatcherEffortPillLabel');
  const effortHead = $('dispatcherEffortValLabel');
  const effortCap = _dispatcherState.effort.charAt(0).toUpperCase() + _dispatcherState.effort.slice(1);
  if (effortPill) effortPill.textContent = effortCap;
  if (effortHead) effortHead.textContent = effortCap;

  renderDispatcherOutputs();
  renderDispatcherPins();
  _updateSendButton();
}

function _updateSendButton() {
  const send = $('dispatcherSend');
  const input = $('dispatcherInput');
  if (!send) return;
  if (S && S.busy) {
    send.disabled = false;
    send.classList.add('is-stop');
    send.innerHTML = '<svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor"><rect x="5" y="5" width="14" height="14" rx="2"/></svg>';
    send.setAttribute('aria-label', t('stop') || 'Stop');
  } else {
    send.classList.remove('is-stop');
    send.innerHTML = '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><line x1="12" y1="19" x2="12" y2="5"/><polyline points="5 12 12 5 19 12"/></svg>';
    send.setAttribute('aria-label', t('dispatcher_send') || 'Dispatch');
    send.disabled = !((input && input.value.trim()) || (_dispatcherState.pins && _dispatcherState.pins.length));
  }
}

async function sendDispatcher() {
  if (S && S.busy) {
    if (typeof stopGeneration === 'function') stopGeneration();
    return;
  }
  const input = $('dispatcherInput');
  const text = (input && input.value.trim()) || '';
  const pins = _dispatcherState.pins || [];
  if (!text && !pins.length) return;
  let composite = text;
  if (pins.length) {
    const pinHeader = 'Pinned: ' + pins.map(p => `@${p}`).join(' ') + '\n';
    composite = pinHeader + (text ? '\n' + text : '');
  }
  if (input) {
    input.value = '';
    input.style.height = 'auto';
  }
  _closeDispatcherSuggest();
  _closeAllPopovers();
  _updateSendButton();
  if (typeof send === 'function') {
    if (!composite) await send();
    else await send(composite, {fromDispatcher: true});
  }
}

function _closeDispatcherSuggest() {
  const box = $('dispatcherSuggest');
  if (!box) return;
  box.classList.remove('is-open');
  box.innerHTML = '';
  _dispatcherSuggestItems = [];
  _dispatcherSuggestIndex = 0;
  _dispatcherSuggestMode = '';
}

function _renderDispatcherSuggest(items, mode) {
  const box = $('dispatcherSuggest');
  if (!box) return;
  _dispatcherSuggestItems = items || [];
  _dispatcherSuggestMode = mode || '';
  _dispatcherSuggestIndex = 0;
  if (!items.length) {
    _closeDispatcherSuggest();
    return;
  }
  box.innerHTML = items.map((it, idx) =>
    `<button type="button" class="dispatcher-suggest-item ${idx === 0 ? 'is-active' : ''}" data-idx="${idx}">
      <span class="dispatcher-suggest-name">${_dispatcherEsc(it.name || it.label || it)}</span>
      ${it.desc ? `<span class="dispatcher-suggest-desc">${_dispatcherEsc(it.desc)}</span>` : ''}
    </button>`
  ).join('');
  box.classList.add('is-open');
}

function _handleDispatcherInputKey(e) {
  const box = $('dispatcherSuggest');
  const open = box && box.classList.contains('is-open');
  if (open) {
    if (e.key === 'ArrowDown') {
      e.preventDefault();
      _dispatcherSuggestIndex = (_dispatcherSuggestIndex + 1) % _dispatcherSuggestItems.length;
      _syncSuggestActive();
      return;
    }
    if (e.key === 'ArrowUp') {
      e.preventDefault();
      _dispatcherSuggestIndex = (_dispatcherSuggestIndex - 1 + _dispatcherSuggestItems.length) % _dispatcherSuggestItems.length;
      _syncSuggestActive();
      return;
    }
    if (e.key === 'Enter' || e.key === 'Tab') {
      e.preventDefault();
      _applyDispatcherSuggest(_dispatcherSuggestItems[_dispatcherSuggestIndex]);
      return;
    }
    if (e.key === 'Escape') {
      e.preventDefault();
      _closeDispatcherSuggest();
      return;
    }
  }

  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault();
    sendDispatcher();
    return;
  }
}

function _syncSuggestActive() {
  const box = $('dispatcherSuggest');
  if (!box) return;
  box.querySelectorAll('.dispatcher-suggest-item').forEach((el, idx) => {
    el.classList.toggle('is-active', idx === _dispatcherSuggestIndex);
  });
}

function _applyDispatcherSuggest(item) {
  if (!item) return;
  const input = $('dispatcherInput');
  if (!input) return;
  if (_dispatcherSuggestMode === 'slash') {
    const cmd = item.name || item;
    input.value = cmd + ' ';
  } else if (_dispatcherSuggestMode === 'pin') {
    const path = item.name || item;
    if (!_dispatcherState.pins.includes(path)) {
      _dispatcherState.pins.push(path);
      _writeDispatcherState();
      renderDispatcherPins();
    }
    input.value = input.value.replace(/@[^\s]*$/, '');
  }
  _closeDispatcherSuggest();
  input.focus();
  _updateSendButton();
}

function _bindDispatcherOnce() {
  if (window._dispatcherBound) return;
  window._dispatcherBound = true;

  // Toggle HUD collapses
  const topbarHudBtn = $('dispatcherHudToggleTopbar');
  if (topbarHudBtn) {
    topbarHudBtn.addEventListener('click', (e) => {
      e.stopPropagation();
      const hud = $('dispatcherHud');
      if (hud) {
        const forced = hud.classList.toggle('is-forced-open');
        topbarHudBtn.classList.toggle('is-active', forced);
      }
    });
  }

  const hudToggle = $('dispatcherHudToggle');
  if (hudToggle) {
    hudToggle.addEventListener('click', () => {
      _dispatcherState.hudCollapsed = !_dispatcherState.hudCollapsed;
      _writeDispatcherState();
      syncDispatcherChrome();
    });
  }
  const outputsToggle = $('dispatcherOutputsToggle');
  if (outputsToggle) {
    outputsToggle.addEventListener('click', () => {
      _dispatcherState.outputsCollapsed = !_dispatcherState.outputsCollapsed;
      _writeDispatcherState();
      syncDispatcherChrome();
    });
  }

  // Switches
  const keep = $('dispatcherKeepAlive');
  if (keep) {
    keep.addEventListener('change', (e) => {
      _dispatcherState.keepAlive = !!e.target.checked;
      _writeDispatcherState();
      syncDispatcherChrome();
    });
  }
  const notifs = $('dispatcherMobileNotifs');
  if (notifs) {
    notifs.addEventListener('change', (e) => {
      _dispatcherState.mobileNotifs = !!e.target.checked;
      _writeDispatcherState();
    });
  }

  // Popover Toggles
  const modePill = $('dispatcherModePill');
  if (modePill) modePill.addEventListener('click', (e) => { e.stopPropagation(); _togglePopover('dispatcherModePopover'); });
  const hudPermBtn = $('dispatcherHudPermBtn');
  if (hudPermBtn) hudPermBtn.addEventListener('click', (e) => { e.stopPropagation(); _togglePopover('dispatcherModePopover'); });

  const plusPill = $('dispatcherPlusPill');
  if (plusPill) plusPill.addEventListener('click', (e) => { e.stopPropagation(); _togglePopover('dispatcherPlusPopover'); });

  const modelPill = $('dispatcherModelPill');
  if (modelPill) modelPill.addEventListener('click', (e) => { e.stopPropagation(); _togglePopover('dispatcherModelsPopover'); });

  const effortPill = $('dispatcherEffortPill');
  if (effortPill) effortPill.addEventListener('click', (e) => { e.stopPropagation(); _togglePopover('dispatcherEffortPopover'); });

  const ringBtn = $('dispatcherRingBtn');
  if (ringBtn) ringBtn.addEventListener('click', (e) => { e.stopPropagation(); _togglePopover('dispatcherTelemetryPopover'); });

  // Mode selection clicks
  document.querySelectorAll('.dispatcher-mode-option').forEach(btn => {
    btn.addEventListener('click', () => {
      const mode = btn.getAttribute('data-mode');
      if (mode) {
        _dispatcherState.permission = mode;
        _writeDispatcherState();
        _syncDispatcherPermissionToAgent();
        syncDispatcherChrome();
        _closeAllPopovers();
      }
    });
  });

  // Plus popover items
  const addFilesBtn = $('dispatcherAddFilesBtn');
  if (addFilesBtn) {
    addFilesBtn.addEventListener('click', () => {
      _closeAllPopovers();
      const fileInput = $('fileInput') || $('composerFileInput');
      if (fileInput) fileInput.click();
    });
  }
  const addFolderBtn = $('dispatcherAddFolderBtn');
  if (addFolderBtn) {
    addFolderBtn.addEventListener('click', () => {
      _closeAllPopovers();
      const ws = (S && S.session && S.session.workspace) || '';
      if (ws && !_dispatcherState.pins.includes(ws)) {
        _dispatcherState.pins.push(ws);
        _writeDispatcherState();
        renderDispatcherPins();
      }
    });
  }
  const slashBtn = $('dispatcherSlashBtn');
  if (slashBtn) {
    slashBtn.addEventListener('click', () => {
      _closeAllPopovers();
      const input = $('dispatcherInput');
      if (input) {
        input.value = '/';
        input.focus();
        _renderDispatcherSuggest(DISPATCHER_SLASH_COMMANDS, 'slash');
      }
    });
  }

  // Model option selection delegation
  const modelList = $('dispatcherModelList');
  if (modelList) {
    modelList.addEventListener('click', (e) => {
      const opt = e.target.closest('.dispatcher-model-option');
      if (opt) {
        const mod = opt.getAttribute('data-model');
        if (mod && typeof selectModel === 'function') {
          selectModel(mod);
          if (S && S.session) S.session.model = mod;
        }
        syncDispatcherChrome();
        _closeAllPopovers();
      }
    });
  }

  // Fast mode toggle
  const fastMode = $('dispatcherFastMode');
  if (fastMode) {
    fastMode.addEventListener('change', (e) => {
      _dispatcherState.fastMode = !!e.target.checked;
      _writeDispatcherState();
    });
  }

  // Effort range slider
  const effortRange = $('dispatcherEffortRange');
  if (effortRange) {
    effortRange.addEventListener('input', (e) => {
      const val = Number(e.target.value);
      const map = {1: 'minimal', 2: 'low', 3: 'medium', 4: 'high', 5: 'max'};
      _dispatcherState.effort = map[val] || 'high';
      _writeDispatcherState();
      syncDispatcherChrome();
    });
  }

  // Topbar menu toggle & actions
  const menuBtn = $('dispatcherMenuBtn');
  const menu = $('dispatcherMenu');
  if (menuBtn && menu) {
    menuBtn.addEventListener('click', (e) => {
      e.stopPropagation();
      menu.hidden = !menu.hidden;
    });
  }

  const seeBgTasks = $('dispatcherSeeBgTasks');
  if (seeBgTasks) {
    seeBgTasks.addEventListener('click', () => {
      menu.hidden = true;
      if (typeof switchPanel === 'function') switchPanel('tasks');
    });
  }

  const clearBgTasks = $('dispatcherClearBgTasks');
  if (clearBgTasks) {
    clearBgTasks.addEventListener('click', async () => {
      menu.hidden = true;
      try {
        await api('/api/tasks/clear', {method: 'POST'});
        if (typeof showToast === 'function') showToast('Background tasks cleared');
      } catch (_) {}
    });
  }

  const clearMemory = $('dispatcherClearMemory');
  if (clearMemory) {
    clearMemory.addEventListener('click', async () => {
      menu.hidden = true;
      try {
        const sid = _dispatcherSessionId();
        if (sid) await api('/api/memory/clear', {method: 'POST', body: JSON.stringify({session_id: sid})});
        if (typeof showToast === 'function') showToast('Dispatcher memory cleared');
      } catch (_) {}
    });
  }

  const deleteConversation = $('dispatcherDeleteConversation');
  if (deleteConversation) {
    deleteConversation.addEventListener('click', async () => {
      menu.hidden = true;
      const sid = _dispatcherSessionId();
      if (sid && typeof deleteSession === 'function') {
        localStorage.removeItem(DISPATCHER_SESSION_KEY);
        await newSession(false, {worktree: false});
        await loadDispatcher();
      }
    });
  }

  const openInChat = $('dispatcherOpenInChat');
  if (openInChat) {
    openInChat.addEventListener('click', () => {
      menu.hidden = true;
      if (typeof switchPanel === 'function') switchPanel('chat');
    });
  }

  // Input & textarea auto-resize
  const input = $('dispatcherInput');
  if (input) {
    input.addEventListener('input', () => {
      input.style.height = 'auto';
      input.style.height = Math.min(input.scrollHeight, 180) + 'px';
      _updateSendButton();

      const val = input.value;
      if (val.startsWith('/')) {
        const q = val.slice(1).toLowerCase();
        const filtered = DISPATCHER_SLASH_COMMANDS.filter(c => c.name.toLowerCase().includes(q));
        _renderDispatcherSuggest(filtered, 'slash');
      } else if (val.includes('@')) {
        const match = val.match(/@([^\s]*)$/);
        if (match) {
          const q = match[1].toLowerCase();
          const tree = typeof collectWorkspaceFiles === 'function' ? collectWorkspaceFiles() : [];
          const files = (tree.length ? tree : ['apps', 'core', 'services', 'tools', 'README.md'])
            .filter(f => typeof f === 'string' && f.toLowerCase().includes(q))
            .slice(0, 10)
            .map(f => ({name: f, desc: 'Workspace file/folder'}));
          _renderDispatcherSuggest(files, 'pin');
        } else {
          _closeDispatcherSuggest();
        }
      } else {
        _closeDispatcherSuggest();
      }
    });

    input.addEventListener('keydown', _handleDispatcherInputKey);
  }

  // Document click closes popovers
  document.addEventListener('click', (e) => {
    if (!e.target.closest('.dispatcher-popover') && !e.target.closest('.dispatcher-deck-pill') && !e.target.closest('.dispatcher-icon-pill') && !e.target.closest('.dispatcher-ring-btn') && !e.target.closest('#dispatcherHudPermBtn')) {
      _closeAllPopovers();
    }
    if (!e.target.closest('#dispatcherMenu') && !e.target.closest('#dispatcherMenuBtn')) {
      if (menu) menu.hidden = true;
    }
  });

  // Hotkeys: 1, 2, 3, 4 when Mode or Models popover is open, ⌘U for upload
  document.addEventListener('keydown', (e) => {
    if (_activePopover === 'dispatcherModePopover') {
      if (['1', '2', '3', '4'].includes(e.key)) {
        e.preventDefault();
        const map = {'1': 'auto', '2': 'manual', '3': 'edits', '4': 'plan'};
        const m = map[e.key];
        if (m) {
          _dispatcherState.permission = m;
          _writeDispatcherState();
          _syncDispatcherPermissionToAgent();
          syncDispatcherChrome();
          _closeAllPopovers();
        }
      }
    }
    if (_activePopover === 'dispatcherModelsPopover') {
      if (['1', '2', '3', '4'].includes(e.key)) {
        e.preventDefault();
        const opts = document.querySelectorAll('.dispatcher-model-option');
        const idx = Number(e.key) - 1;
        if (opts[idx]) {
          const mod = opts[idx].getAttribute('data-model');
          if (mod && typeof selectModel === 'function') {
            selectModel(mod);
            if (S && S.session) S.session.model = mod;
          }
          syncDispatcherChrome();
          _closeAllPopovers();
        }
      }
    }
    if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'u') {
      if (_isDispatcherPanel()) {
        e.preventDefault();
        const fileInput = $('fileInput') || $('composerFileInput');
        if (fileInput) fileInput.click();
      }
    }
  });

  // Pin & Unpin delegations
  document.addEventListener('click', (e) => {
    const unpin = e.target.closest('[data-unpin]');
    if (unpin) {
      const path = unpin.getAttribute('data-unpin');
      _dispatcherState.pins = (_dispatcherState.pins || []).filter(p => p !== path);
      _writeDispatcherState();
      renderDispatcherPins();
      _updateSendButton();
    }
    const pin = e.target.closest('[data-pin]');
    if (pin) {
      const path = pin.getAttribute('data-pin');
      if (path && !_dispatcherState.pins.includes(path)) {
        _dispatcherState.pins.push(path);
        _writeDispatcherState();
        renderDispatcherPins();
        _updateSendButton();
      }
    }
    const out = e.target.closest('.dispatcher-output');
    if (out) {
      const path = out.getAttribute('data-path');
      if (path && typeof viewFile === 'function') viewFile(path);
    }
    const suggest = e.target.closest('.dispatcher-suggest-item');
    if (suggest) {
      const idx = Number(suggest.getAttribute('data-idx'));
      if (Number.isFinite(idx) && _dispatcherSuggestItems[idx]) {
        _applyDispatcherSuggest(_dispatcherSuggestItems[idx]);
      }
    }
  });

  const sendBtn = $('dispatcherSend');
  if (sendBtn) sendBtn.addEventListener('click', sendDispatcher);

  // Live Voice Mode Handlers
  const voiceModeBtn = $('dispatcherVoiceModeBtn');
  if (voiceModeBtn) {
    voiceModeBtn.addEventListener('click', () => {
      startDispatcherVoiceMode();
    });
  }

  const voiceCloseBtn = $('dispatcherVoiceCloseBtn');
  if (voiceCloseBtn) {
    voiceCloseBtn.addEventListener('click', () => {
      closeDispatcherVoiceMode();
    });
  }

  const voiceEndBtn = $('dispatcherVoiceEndBtn');
  if (voiceEndBtn) {
    voiceEndBtn.addEventListener('click', () => {
      closeDispatcherVoiceMode();
    });
  }

  const voiceMicToggle = $('dispatcherVoiceMicToggle');
  if (voiceMicToggle) {
    voiceMicToggle.addEventListener('click', () => {
      _dispVoiceMuted = !_dispVoiceMuted;
      voiceMicToggle.classList.toggle('is-muted', _dispVoiceMuted);
      if (_dispVoiceMuted) {
        _stopDispVoiceListening();
        _setDispVoiceState('idle', 'Microphone muted');
      } else {
        _startDispVoiceListening();
      }
    });
  }
}

// ── Dispatcher OpenAI-Style Advanced Voice Space ─────────────────────────────
let _dispVoiceRecognition = null;
let _dispVoiceActive = false;
let _dispVoiceMuted = false;
let _dispVoiceState = 'idle'; // 'idle' | 'listening' | 'thinking' | 'speaking'
let _dispVoiceSilenceTimer = null;
let _dispVoiceInterimText = '';
let _dispVoiceFinalText = '';

function _setDispVoiceState(state, captionText) {
  _dispVoiceState = state;
  const overlay = $('dispatcherVoiceOverlay');
  const stateLabel = $('dispatcherVoiceStateLabel');
  const caption = $('dispatcherVoiceCaption');
  if (!overlay) return;

  overlay.classList.remove('is-listening', 'is-thinking', 'is-speaking');
  if (state === 'listening') {
    overlay.classList.add('is-listening');
    if (stateLabel) stateLabel.textContent = 'Listening…';
    if (caption && captionText !== undefined) caption.textContent = captionText || 'Listening…';
  } else if (state === 'thinking') {
    overlay.classList.add('is-thinking');
    if (stateLabel) stateLabel.textContent = 'Thinking…';
    if (caption && captionText !== undefined) caption.textContent = captionText || 'Thinking…';
  } else if (state === 'speaking') {
    overlay.classList.add('is-speaking');
    if (stateLabel) stateLabel.textContent = 'Speaking…';
    if (caption && captionText !== undefined) caption.textContent = captionText || '…';
  } else {
    if (stateLabel) stateLabel.textContent = 'Ready';
    if (caption && captionText !== undefined) caption.textContent = captionText || 'Tap the mic or speak…';
  }
}

function startDispatcherVoiceMode() {
  const overlay = $('dispatcherVoiceOverlay');
  if (!overlay) return;

  const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!SR) {
    if (typeof showToast === 'function') showToast('Speech recognition is not supported in this browser.', 4000, 'warning');
    return;
  }

  _dispVoiceActive = true;
  _dispVoiceMuted = false;
  overlay.classList.add('is-active');
  overlay.setAttribute('aria-hidden', 'false');

  // Update Character & Model in Voice Overlay
  const charEl = $('dispatcherVoiceCharacterName');
  const modelEl = $('dispatcherVoiceModelBadge');
  const charName = (typeof S !== 'undefined' && S.character && S.character.name) || (typeof _activeCharacterName === 'function' ? _activeCharacterName() : 'Ares');
  const modelName = (typeof S !== 'undefined' && S.session && S.session.model) || _dispatcherState.model || 'qwen3.6:35b-mlx';
  if (charEl) charEl.textContent = charName;
  if (modelEl) modelEl.textContent = '· ' + modelName;

  _startDispVoiceListening();
}

function closeDispatcherVoiceMode() {
  _dispVoiceActive = false;
  _stopDispVoiceListening();
  if (window.speechSynthesis) window.speechSynthesis.cancel();

  const overlay = $('dispatcherVoiceOverlay');
  if (overlay) {
    overlay.classList.remove('is-active', 'is-listening', 'is-thinking', 'is-speaking');
    overlay.setAttribute('aria-hidden', 'true');
  }
}

function _startDispVoiceListening() {
  if (!_dispVoiceActive || _dispVoiceMuted) return;
  const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!SR) return;

  if (_dispVoiceRecognition) {
    try { _dispVoiceRecognition.abort(); } catch (_) {}
  }

  _dispVoiceInterimText = '';
  _dispVoiceFinalText = '';
  _setDispVoiceState('listening', 'Say something to Ares…');

  const rec = new SR();
  rec.continuous = true;
  rec.interimResults = true;
  rec.lang = (typeof _getPreferredSpeechLang === 'function' ? _getPreferredSpeechLang() : 'en-US');

  rec.onresult = (e) => {
    if (!_dispVoiceActive) return;
    let interim = '';
    let final = '';
    for (let i = e.resultIndex; i < e.results.length; ++i) {
      if (e.results[i].isFinal) {
        final += e.results[i][0].transcript;
      } else {
        interim += e.results[i][0].transcript;
      }
    }

    const currentText = (final || interim).trim();
    if (currentText) {
      if (window.speechSynthesis && window.speechSynthesis.speaking) {
        window.speechSynthesis.cancel();
      }
      _setDispVoiceState('listening', currentText);

      if (_dispVoiceSilenceTimer) clearTimeout(_dispVoiceSilenceTimer);
      _dispVoiceSilenceTimer = setTimeout(() => {
        if (_dispVoiceActive && currentText) {
          _dispVoiceFinalText = currentText;
          _dispatchVoiceTurn(currentText);
        }
      }, 1200);
    }
  };

  rec.onerror = (e) => {
    if (e.error === 'no-speech') {
      if (_dispVoiceActive && _dispVoiceState === 'listening') {
        setTimeout(() => { if (_dispVoiceActive && _dispVoiceState === 'listening') _startDispVoiceListening(); }, 500);
      }
    }
  };

  rec.onend = () => {
    if (_dispVoiceActive && _dispVoiceState === 'listening' && !_dispVoiceMuted) {
      setTimeout(() => { if (_dispVoiceActive && _dispVoiceState === 'listening') _startDispVoiceListening(); }, 300);
    }
  };

  try {
    rec.start();
    _dispVoiceRecognition = rec;
  } catch (_) {}
}

function _stopDispVoiceListening() {
  if (_dispVoiceSilenceTimer) clearTimeout(_dispVoiceSilenceTimer);
  if (_dispVoiceRecognition) {
    try { _dispVoiceRecognition.abort(); } catch (_) {}
    _dispVoiceRecognition = null;
  }
}

async function _dispatchVoiceTurn(userText) {
  if (!userText || !_dispVoiceActive) return;
  _stopDispVoiceListening();
  _setDispVoiceState('thinking', `"${userText}"`);

  // Fill and send through Dispatcher
  const input = $('dispatcherInput');
  if (input) input.value = userText;

  // Track session and speech response
  const prevMessagesCount = Array.isArray(typeof S !== 'undefined' && S.session && S.session.messages) ? S.session.messages.length : 0;
  await sendDispatcher();

  // Poll for completion or assistant response
  const checkTurnResponse = setInterval(() => {
    if (!_dispVoiceActive) {
      clearInterval(checkTurnResponse);
      return;
    }
    const msgs = (typeof S !== 'undefined' && S.session && S.session.messages) || [];
    const isBusy = (typeof S !== 'undefined' && S.busy);
    if (!isBusy && msgs.length > prevMessagesCount) {
      clearInterval(checkTurnResponse);
      const lastMsg = msgs[msgs.length - 1];
      if (lastMsg && lastMsg.role === 'assistant') {
        const raw = lastMsg.content || '';
        let clean = raw.replace(/<think>[\s\S]*?<\/think>/gi, '').trim();
        _speakVoiceResponse(clean);
      } else {
        _setDispVoiceState('listening', 'Say something to Ares…');
        _startDispVoiceListening();
      }
    }
  }, 400);
}

function _speakVoiceResponse(text) {
  if (!text || !_dispVoiceActive) {
    if (_dispVoiceActive) _startDispVoiceListening();
    return;
  }

  _setDispVoiceState('speaking', text);

  if ('speechSynthesis' in window) {
    window.speechSynthesis.cancel();
    const cleanSpeech = text.replace(/```[\s\S]*?```/g, 'Code block.').replace(/`[^`]+`/g, '').slice(0, 500);
    const u = new SpeechSynthesisUtterance(cleanSpeech);
    u.rate = 1.05;
    u.pitch = 1.0;
    
    // Choose high quality neural voice if available
    const voices = window.speechSynthesis.getVoices();
    const preferred = voices.find(v => v.name.includes('Natural') || v.name.includes('Neural') || v.name.includes('Daniel') || v.name.includes('Samantha') || v.lang.startsWith('en'));
    if (preferred) u.voice = preferred;

    u.onend = () => {
      if (_dispVoiceActive) {
        setTimeout(() => {
          if (_dispVoiceActive) {
            _setDispVoiceState('listening', 'Say something to Ares…');
            _startDispVoiceListening();
          }
        }, 400);
      }
    };

    u.onerror = () => {
      if (_dispVoiceActive) {
        _setDispVoiceState('listening', 'Say something to Ares…');
        _startDispVoiceListening();
      }
    };

    window.speechSynthesis.speak(u);
  } else {
    setTimeout(() => {
      if (_dispVoiceActive) {
        _setDispVoiceState('listening', 'Say something to Ares…');
        _startDispVoiceListening();
      }
    }, 2000);
  }
}

function _startDispatcherHealth() {
  _stopDispatcherHealth();
  _dispatcherHealthTimer = setInterval(async () => {
    if (!_isDispatcherPanel()) return;
    try {
      const res = await api('/api/health');
      _dispatcherHealthy = !!(res && (res.status === 'ok' || res.healthy));
    } catch (_) {
      _dispatcherHealthy = false;
    }
    syncDispatcherChrome();
  }, 10000);
}

function _stopDispatcherHealth() {
  if (_dispatcherHealthTimer) {
    clearInterval(_dispatcherHealthTimer);
    _dispatcherHealthTimer = null;
  }
}

// Global hooks for core event pump
window.loadDispatcher = loadDispatcher;
window.leaveDispatcher = leaveDispatcher;
window.sendDispatcher = sendDispatcher;
window.renderDispatcherTimeline = renderDispatcherTimeline;
window.syncDispatcherChrome = syncDispatcherChrome;
