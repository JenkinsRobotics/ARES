/**
 * Avatar — the agent as a face you watch work.
 *
 * The chat tab is a transcript: you read what the agent SAID. This tab is
 * the other half — who it is, what it is thinking right now, and what it
 * is touching while it thinks. First run asks who you are talking to
 * (any JaegerAI character, or the default), and after that the stage
 * shows that character's card, a live thought stream, and the tool feed,
 * with steer/interrupt controls that reach the running turn.
 *
 * Two rules shape the implementation:
 *
 *  1. **JaegerAI owns characters.** The roster, the selection, and even
 *     the card image come over the versioned bridge (`/api/companion`,
 *     `/api/companion/card`). This file never assumes a path inside the
 *     peer's install, and card art is capability-gated — no art means a
 *     drawn placeholder, not an error.
 *  2. **One turn engine.** The stage does not run its own stream. It
 *     mirrors the live turn the chat panel is already rendering (the
 *     `#liveAssistantTurn` DOM) and drives the SAME controls the
 *     composer uses — `send()`, `cmdSteer()`, `cancelStream()`. A second
 *     engine would be a second source of truth about what the agent is
 *     doing, and they would disagree the first time one dropped a frame.
 */

// Chosen-once flag. The Companion always HAS an active character, so
// "first run" is about whether the operator has been asked in this view,
// not about the runtime's state.
const AVATAR_CHOSEN_KEY = 'ares-avatar-persona-chosen';
// The neutral sheet's id — the plain assistant, offered as the default
// pick on first run. Used only as a fall-back for a runtime too old to
// send the `neutral` flag (JaegerAI contract < 10); prefer
// `_avatarIsNeutral`, which reads the runtime's own answer.
const AVATAR_NEUTRAL_CHARACTER = 'assistant';
// Stage refresh while a turn runs. Fast enough that thought text reads as
// live, slow enough that it costs nothing next to the stream itself.
const AVATAR_TICK_MS = 220;
// How much of the tool feed to keep on screen.
const AVATAR_TOOL_ROWS = 8;

const _avatar = {
  comp: null,          // last /api/companion snapshot
  cardUrls: {},        // character id → object URL for its card art
  timer: null,
  lastThought: '',
  lastPhase: '',
  loading: false,
};

function _avatarChosen() {
  try { return localStorage.getItem(AVATAR_CHOSEN_KEY) === '1'; } catch (_) { return false; }
}

function _avatarMarkChosen() {
  try { localStorage.setItem(AVATAR_CHOSEN_KEY, '1'); } catch (_) { /* private mode */ }
}

// ── data ────────────────────────────────────────────────────────────

async function loadAvatarPanel(force) {
  if (_avatar.loading) return;
  _avatar.loading = true;
  try {
    if (force || !_avatar.comp) _avatar.comp = await api('/api/companion');
  } catch (err) {
    _avatar.comp = null;
    _avatarRenderUnavailable(err && err.message);
    _avatar.loading = false;
    return;
  }
  _avatar.loading = false;
  _avatarRenderRoster();
  _avatarRenderStage();
  _avatarStartTicker();
}

/**
 * Card art for a character, as an object URL. JaegerAI serves the bytes
 * over the bridge; a 404 is the ordinary "this character has no art"
 * answer and resolves to null so the caller draws a placeholder.
 */
async function _avatarCardUrl(id) {
  if (!id) return null;
  if (Object.prototype.hasOwnProperty.call(_avatar.cardUrls, id)) return _avatar.cardUrls[id];
  let url = null;
  try {
    const res = await fetch(`/api/companion/card?character_id=${encodeURIComponent(id)}`,
                            { credentials: 'same-origin' });
    if (res.ok) {
      const blob = await res.blob();
      if (blob && blob.size) url = URL.createObjectURL(blob);
    }
  } catch (_) { url = null; }
  _avatar.cardUrls[id] = url;
  return url;
}

/**
 * True for the one sheet that is nobody in particular — the plain
 * assistant. Picking it means "no character": the agent keeps its own
 * name and drops the roleplay. Every other sheet IS somebody, and while
 * it is selected that somebody's name is the agent's name.
 */
function _avatarIsNeutral(ch) {
  if (!ch) return false;
  if (typeof ch.neutral === 'boolean') return ch.neutral;
  return String(ch.id || '') === AVATAR_NEUTRAL_CHARACTER;
}

/**
 * The one name the agent answers to. The runtime decides it (contract
 * v10's `agent.display_name`); the fall-back reproduces the same rule for
 * an older peer. Never a blend of two names — "Jarvis playing Clanker"
 * was the bug this replaces.
 */
function _avatarDisplayName() {
  const comp = _avatar.comp || {};
  const agent = comp.agent || {};
  const ch = comp.character || {};
  const fromRuntime = String(agent.display_name || '').trim();
  if (fromRuntime) return fromRuntime;
  const own = String(agent.name || '').trim();
  return (_avatarIsNeutral(ch) ? own : String(ch.name || '').trim() || own)
    || own || 'Companion';
}

function _avatarCharacters() {
  const comp = _avatar.comp || {};
  const rows = Array.isArray(comp.characters) ? comp.characters.slice() : [];
  // The neutral sheet lands first — it is both the answer to "just give
  // me a normal assistant" and the way back out of a character, so it
  // should not be hunted for in an A-Z list.
  rows.sort((a, b) => {
    if (_avatarIsNeutral(a) !== _avatarIsNeutral(b)) return _avatarIsNeutral(a) ? -1 : 1;
    return String(a.name || a.id).localeCompare(String(b.name || b.id));
  });
  return rows;
}

function _avatarActiveId() {
  const comp = _avatar.comp || {};
  return String((comp.character && comp.character.id) || '');
}

// ── sidebar roster ──────────────────────────────────────────────────

function _avatarRenderRoster() {
  const host = document.getElementById('avatarRoster');
  if (!host) return;
  const activeId = _avatarActiveId();
  const rows = _avatarCharacters();
  if (!rows.length) {
    host.innerHTML = '<div class="avatar-roster-empty">No characters available from the runtime.</div>';
    return;
  }
  host.innerHTML = rows.map(ch => {
    const isActive = ch.id === activeId;
    const isNeutral = _avatarIsNeutral(ch);
    return `<button type="button" class="avatar-roster-row${isActive ? ' active' : ''}"
        onclick="avatarChooseCharacter('${esc(ch.id)}')" data-character="${esc(ch.id)}">
      <span class="avatar-roster-face" data-card-for="${esc(ch.id)}">${esc((ch.name || ch.id || '?').charAt(0).toUpperCase())}</span>
      <span class="avatar-roster-text">
        <span class="avatar-roster-name">${esc(ch.name || ch.id)}${isNeutral ? '<span class="avatar-roster-tag">no character</span>' : ''}</span>
        <span class="avatar-roster-role">${isNeutral ? 'Plain assistant — keeps its own name' : esc(ch.role || 'Companion')}</span>
      </span>
      ${isActive ? '<span class="avatar-roster-active" aria-label="Active">●</span>' : ''}
    </button>`;
  }).join('');
  rows.forEach(ch => {
    _avatarCardUrl(ch.id).then(url => {
      if (!url) return;
      const face = host.querySelector(`.avatar-roster-face[data-card-for="${CSS.escape(ch.id)}"]`);
      if (face) {
        face.textContent = '';
        face.style.backgroundImage = `url(${url})`;
        face.classList.add('has-art');
      }
    });
  });
}

function _avatarRenderUnavailable(message) {
  const host = document.getElementById('avatarRoster');
  if (host) {
    host.innerHTML = `<div class="avatar-roster-empty">The Companion runtime is unavailable.
      <div class="avatar-roster-empty-sub">${esc(message || 'The bridge did not answer.')}</div></div>`;
  }
  const stage = document.getElementById('avatarStage');
  if (stage) {
    stage.innerHTML = `<div class="avatar-empty">
      <div class="avatar-empty-title">No Companion connected</div>
      <div class="avatar-empty-sub">Start JaegerAI, then reopen this tab.</div>
      <button type="button" class="avatar-btn" onclick="loadAvatarPanel(true)">Retry</button>
    </div>`;
  }
}

// ── the stage ───────────────────────────────────────────────────────

function _avatarMarkdownInline(text) {
  if (!text) return '';
  return text
    .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
    .replace(/\*(.*?)\*/g, '<em>$1</em>')
    .replace(/`([^`]+)`/g, '<code>$1</code>');
}

function _avatarMarkdown(source) {
  if (!source) return '';
  if (typeof _kanbanRenderMarkdown === 'function') {
    try { return _kanbanRenderMarkdown(source); } catch (_) {}
  }
  const lines = esc(source).split(/\r?\n/);
  const out = [];
  let i = 0;
  while (i < lines.length) {
    const line = lines[i];
    const trimmed = line.trim();
    if (/^```/.test(trimmed)) {
      const code = [];
      i++;
      while (i < lines.length && !/^```/.test(lines[i].trim())) {
        code.push(lines[i]);
        i++;
      }
      i++;
      out.push(`<pre><code>${code.join('\n')}</code></pre>`);
      continue;
    }
    if (trimmed.startsWith('# ')) { out.push(`<h3>${_avatarMarkdownInline(trimmed.slice(2))}</h3>`); i++; continue; }
    if (trimmed.startsWith('## ')) { out.push(`<h4>${_avatarMarkdownInline(trimmed.slice(3))}</h4>`); i++; continue; }
    if (trimmed.startsWith('### ')) { out.push(`<h5>${_avatarMarkdownInline(trimmed.slice(4))}</h5>`); i++; continue; }
    if (/^[-*]\s/.test(trimmed)) {
      const lis = [];
      while (i < lines.length && /^[-*]\s/.test(lines[i].trim())) {
        lis.push(`<li>${_avatarMarkdownInline(lines[i].trim().replace(/^[-*]\s/, ''))}</li>`);
        i++;
      }
      out.push(`<ul>${lis.join('')}</ul>`);
      continue;
    }
    if (trimmed) {
      out.push(`<p>${_avatarMarkdownInline(trimmed)}</p>`);
    }
    i++;
  }
  return out.join('');
}

function _avatarRenderStage() {
  const stage = document.getElementById('avatarStage');
  if (!stage) return;
  if (!_avatarChosen()) { _avatarRenderPicker(stage); return; }
  const comp = _avatar.comp || {};
  const ch = comp.character || {};
  const name = _avatarDisplayName();
  const role = _avatarIsNeutral(ch)
    ? 'Plain assistant' : (String(ch.role || '').trim() || 'Companion');

  stage.innerHTML = `
    <div class="avatar-stage-grid">
      <div class="avatar-header-bar">
        <div class="avatar-header-left">
          <div class="avatar-mini-portrait" id="avatarPortraitArt">${esc((name || '?').charAt(0).toUpperCase())}</div>
          <div class="avatar-header-meta">
            <div class="avatar-header-name">
              <span>${esc(name)}</span>
              <span class="avatar-header-status" id="avatarStatus" data-state="idle">
                <span class="avatar-status-dot"></span>
                <span id="avatarStatusText">Idle</span>
              </span>
            </div>
            <div class="avatar-header-role">${esc(role)}</div>
          </div>
        </div>
        <button type="button" class="avatar-btn avatar-btn-quiet" onclick="avatarReopenPicker()">Change Character</button>
      </div>

      <div class="avatar-timeline" id="avatarTimeline">
        <div class="avatar-thought-idle" style="text-align:center;padding:40px 0;">Loading conversation...</div>
      </div>

      <div class="avatar-claude-composer">
        <div class="avatar-composer-input-row">
          <textarea id="avatarInput" rows="1" placeholder="Add feedback, prompt, or steer mid-flight..." onkeydown="_avatarInputKey(event)"></textarea>
        </div>
        <div class="avatar-composer-toolbar">
          <div class="avatar-composer-pills">
            <span class="avatar-chip" onclick="avatarReopenPicker()">
              <span class="avatar-chip-dot"></span>${esc(name)}
            </span>
            <span class="avatar-chip" id="avatarStatusChip">Idle</span>
          </div>
          <div class="avatar-composer-actions">
            <button type="button" class="avatar-claude-btn avatar-claude-btn-stop" id="avatarStopBtn" onclick="avatarInterrupt()" disabled title="Interrupt execution">■</button>
            <button type="button" class="avatar-claude-btn avatar-claude-btn-send" id="avatarSendBtn" onclick="avatarSend()" title="Send / Steer">▲</button>
          </div>
        </div>
      </div>
    </div>`;

  _avatarCardUrl(ch.id).then(url => {
    const art = document.getElementById('avatarPortraitArt');
    if (url && art) {
      art.textContent = '';
      art.style.backgroundImage = `url(${url})`;
      art.classList.add('has-art');
    }
  });
  _avatarTick();
}

function _avatarRenderPicker(stage) {
  const rows = _avatarCharacters();
  const cards = rows.map(ch => {
    const isNeutral = _avatarIsNeutral(ch);
    return `<button type="button" class="avatar-pick${isNeutral ? ' is-default' : ''}"
        onclick="avatarChooseCharacter('${esc(ch.id)}')">
      <span class="avatar-pick-face" data-card-for="${esc(ch.id)}">${esc((ch.name || ch.id || '?').charAt(0).toUpperCase())}</span>
      <span class="avatar-pick-name">${esc(ch.name || ch.id)}</span>
      <span class="avatar-pick-role">${isNeutral
          ? 'Plain assistant — keeps its own name'
          : esc(ch.role || 'Companion')}</span>
      ${isNeutral ? '<span class="avatar-pick-tag">No character</span>' : ''}
    </button>`;
  }).join('');
  stage.innerHTML = `
    <div class="avatar-picker">
      <div class="avatar-picker-head">
        <h2>Who are you talking to?</h2>
        <p>Pick a character and your Companion <em>becomes</em> it — that name, that manner. It changes how the agent talks, never what it can do, and you can switch whenever you like. Prefer a plain, neutral AI that keeps its own name? Pick the first one.</p>
      </div>
      <div class="avatar-pick-grid">${cards || '<div class="avatar-roster-empty">No characters available.</div>'}</div>
    </div>`;
  rows.forEach(ch => {
    _avatarCardUrl(ch.id).then(url => {
      if (!url) return;
      const face = stage.querySelector(`.avatar-pick-face[data-card-for="${CSS.escape(ch.id)}"]`);
      if (face) {
        face.textContent = '';
        face.style.backgroundImage = `url(${url})`;
        face.classList.add('has-art');
      }
    });
  });
}

function avatarReopenPicker() {
  try { localStorage.removeItem(AVATAR_CHOSEN_KEY); } catch (_) { /* private mode */ }
  _avatarRenderStage();
}

/**
 * Select a character. JaegerAI applies it live AND binds it as the
 * default for the next launch (that pairing is `update_companion`'s, not
 * ours) — so a choice made here survives a restart.
 */
async function avatarChooseCharacter(id) {
  const target = String(id || '').trim();
  if (!target) return;
  try {
    const res = await api('/api/companion', {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ character_id: target }),
    });
    if (res && res.character) _avatar.comp = res;
    _avatarMarkChosen();
    _avatarRenderRoster();
    _avatarRenderStage();
    if (typeof refreshAssistantIdentity === 'function') await refreshAssistantIdentity();
    if (typeof showToast === 'function') {
      const name = (res && res.character && res.character.name) || target;
      showToast(`Now talking to ${name}`, 'success');
    }
  } catch (err) {
    if (typeof showToast === 'function') showToast('Could not switch character: ' + (err && err.message), 'error');
  }
}

// ── live mirror ─────────────────────────────────────────────────────

function _avatarLiveTurn() {
  return document.getElementById('liveAssistantTurn');
}

function _avatarRunning() {
  return !!(typeof S !== 'undefined' && S.busy && S.activeStreamId);
}

/** The newest thinking text the chat stream has rendered this turn. */
function _avatarThoughtText() {
  const turn = _avatarLiveTurn();
  if (!turn) return '';
  const bodies = turn.querySelectorAll('.thinking-card-body pre');
  if (!bodies.length) return '';
  return String(bodies[bodies.length - 1].textContent || '').trim();
}

/** The newest clean narrative text the assistant is streaming. */
function _avatarResponseText() {
  if (typeof S !== 'undefined' && Array.isArray(S.messages)) {
    const last = [...S.messages].reverse().find(m => m && m.role === 'assistant' && (m._live || m.streaming));
    if (last && typeof last.content === 'string' && last.content.trim()) {
      return last.content;
    }
    if (last && typeof msgContent === 'function') {
      const txt = msgContent(last);
      if (txt) return txt;
    }
  }
  const turn = _avatarLiveTurn();
  if (!turn) return '';
  const textEl = turn.querySelector('.msg-assistant-body, .assistant-turn-text, .msg-content');
  if (textEl) return String(textEl.textContent || '').trim();
  return '';
}

/** Tool rows for this turn, newest last, with their run state. */
function _avatarToolFeed() {
  const turn = _avatarLiveTurn();
  if (!turn) return [];
  const out = [];
  turn.querySelectorAll('.tool-card-row').forEach(row => {
    const card = row.querySelector('.tool-card');
    const label = (row.dataset && row.dataset.toolActionLabel)
      || (card && card.querySelector('.tool-card-name') && card.querySelector('.tool-card-name').textContent.trim())
      || 'tool';
    const running = !!(card && card.classList.contains('tool-card-running'));
    const failed = (row.dataset && row.dataset.toolError === 'true')
      || !!(card && card.classList.contains('tool-card-error'));
    out.push({ label, state: failed ? 'error' : running ? 'running' : 'done' });
  });
  return out.slice(-AVATAR_TOOL_ROWS);
}

function _avatarPhase(thought, tools) {
  if (!_avatarRunning()) return 'idle';
  const active = tools.find(t => t.state === 'running');
  if (active) return 'tool';
  if (thought) return 'thinking';
  return 'working';
}

const _AVATAR_PHASE_TEXT = {
  idle: 'Idle',
  thinking: 'Thinking...',
  tool: 'Using tool',
  working: 'Working...',
};

let _lastAvatarTimelineSig = '';

function _avatarUpdateTimeline(running, thought, tools, liveText) {
  const timeline = document.getElementById('avatarTimeline');
  if (!timeline) return;
  const messages = (typeof S !== 'undefined' && Array.isArray(S.messages)) ? S.messages : [];
  const valid = messages.filter(m => {
    if (!m || (m.role !== 'user' && m.role !== 'assistant')) return false;
    if (typeof _isRecoveryControlMessage === 'function' && _isRecoveryControlMessage(m)) return false;
    return true;
  });

  const sig = JSON.stringify(valid.map(m => ({ r: m.role, c: typeof msgContent === 'function' ? msgContent(m) : m.content }))) + `|${running}|${thought}|${tools.length}|${liveText}`;
  if (sig === _lastAvatarTimelineSig) return;
  _lastAvatarTimelineSig = sig;

  if (!valid.length && !running && !liveText) {
    timeline.innerHTML = '<div class="avatar-thought-idle" style="text-align:center;padding:60px 0;">No messages in this session yet. Ask a question or give a command below!</div>';
    return;
  }

  let html = '';
  valid.forEach((m, idx) => {
    const isUser = m.role === 'user';
    const rawContent = typeof msgContent === 'function' ? msgContent(m) : String(m.content || '');
    if (isUser) {
      html += `
        <div class="avatar-turn avatar-turn-user">
          <div class="avatar-turn-bubble">${_avatarMarkdown(rawContent)}</div>
        </div>`;
    } else {
      // Historical assistant turn
      const reasoning = String(m.thinking || m.reasoning || '').trim();
      const toolCalls = Array.isArray(m.tool_calls) ? m.tool_calls : [];
      html += `
        <div class="avatar-turn avatar-turn-assistant">
          ${reasoning ? `
            <details class="avatar-pill">
              <summary><span class="avatar-pill-icon">⏱</span> Thought process <span class="avatar-pill-chevron">›</span></summary>
              <div class="avatar-pill-body"><pre>${esc(reasoning)}</pre></div>
            </details>` : ''}
          ${toolCalls.length ? `
            <details class="avatar-pill">
              <summary><span class="avatar-pill-icon">⚡</span> Used ${toolCalls.length} tool${toolCalls.length > 1 ? 's' : ''} <span class="avatar-pill-chevron">›</span></summary>
              <div class="avatar-pill-body">
                ${toolCalls.map(tc => {
                  const fn = tc.function || tc;
                  return `<div class="avatar-tool-item"><span class="avatar-tool-badge done">done</span> <code>${esc(fn.name || 'tool')}</code></div>`;
                }).join('')}
              </div>
            </details>` : ''}
          <div class="avatar-turn-bubble avatar-narrative">
            ${_avatarMarkdown(rawContent)}
          </div>
        </div>`;
    }
  });

  if (running) {
    html += `
      <div class="avatar-turn avatar-turn-assistant" id="avatarLiveTurnBlock">
        ${thought ? `
          <details class="avatar-pill" open>
            <summary><span class="avatar-pill-icon">⏱</span> Thought process <span class="avatar-pill-chevron">›</span></summary>
            <div class="avatar-pill-body"><pre>${esc(thought)}</pre></div>
          </details>` : ''}
        ${tools.length ? `
          <details class="avatar-pill" open>
            <summary><span class="avatar-pill-icon">⚡</span> ${tools.some(t => t.state === 'running') ? 'Running tools...' : `Used ${tools.length} tool${tools.length > 1 ? 's' : ''}`} <span class="avatar-pill-chevron">›</span></summary>
            <div class="avatar-pill-body">
              ${tools.map(t => `<div class="avatar-tool-item"><span class="avatar-tool-badge ${t.state}">${esc(t.state)}</span> <span>${esc(t.label)}</span></div>`).join('')}
            </div>
          </details>` : ''}
        <div class="avatar-turn-bubble avatar-narrative">
          ${liveText ? _avatarMarkdown(liveText) : '<span style="color:var(--muted);font-style:italic">Generating response...</span>'}
          <span class="avatar-cursor"></span>
        </div>
      </div>`;
  }

  timeline.innerHTML = html;
  timeline.scrollTop = timeline.scrollHeight;
}

function _avatarTick() {
  const stage = document.getElementById('avatarStage');
  if (!stage || !document.getElementById('avatarTimeline')) return;
  const running = _avatarRunning();
  const thought = _avatarThoughtText();
  const tools = _avatarToolFeed();
  const liveText = _avatarResponseText();
  const phase = _avatarPhase(thought, tools);

  const statusText = document.getElementById('avatarStatusText');
  if (statusText) {
    const active = tools.find(t => t.state === 'running');
    statusText.textContent = phase === 'tool' && active
      ? `Using ${active.label}` : _AVATAR_PHASE_TEXT[phase];
  }
  const statusEl = document.getElementById('avatarStatus');
  if (statusEl) statusEl.dataset.state = phase;

  const statusChip = document.getElementById('avatarStatusChip');
  if (statusChip) statusChip.textContent = _AVATAR_PHASE_TEXT[phase];

  _avatarUpdateTimeline(running, thought, tools, liveText);

  const stopBtn = document.getElementById('avatarStopBtn');
  if (stopBtn) stopBtn.disabled = !running;
  const sendBtn = document.getElementById('avatarSendBtn');
  if (sendBtn) {
    sendBtn.textContent = running ? '▲' : '▲';
    sendBtn.title = running ? 'Steer running turn' : 'Send message';
  }
  _avatarlastPhase = phase;
}

function _avatarStartTicker() {
  _avatarStopTicker();
  _avatar.timer = setInterval(_avatarTick, AVATAR_TICK_MS);
}

function _avatarStopTicker() {
  if (_avatar.timer) { clearInterval(_avatar.timer); _avatar.timer = null; }
}

// ── controls ────────────────────────────────────────────────────────

function _avatarInputKey(event) {
  if (event.key === 'Enter' && !event.shiftKey) {
    event.preventDefault();
    avatarSend();
  }
}

async function avatarSend() {
  const input = document.getElementById('avatarInput');
  const text = String((input && input.value) || '').trim();
  if (!text) return;
  const running = _avatarRunning();
  if (input) input.value = '';
  try {
    if (running && typeof cmdSteer === 'function') {
      await cmdSteer(text);
    } else {
      const composer = document.getElementById('msg');
      if (!composer || typeof send !== 'function') {
        if (typeof showToast === 'function') showToast('Chat is not ready yet', 'error');
        return;
      }
      composer.value = text;
      await send();
    }
  } catch (err) {
    if (typeof showToast === 'function') showToast('Could not deliver that: ' + (err && err.message), 'error');
  }
  _avatarTick();
}

async function avatarInterrupt() {
  if (!_avatarRunning()) return;
  try {
    if (typeof cancelStream === 'function') await cancelStream('avatar-interrupt');
    if (typeof showToast === 'function') showToast('Interrupted — stopped where it was', 2000);
  } catch (err) {
    if (typeof showToast === 'function') showToast('Could not interrupt: ' + (err && err.message), 'error');
  }
  _avatarTick();
}
