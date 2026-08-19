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
// The character offered as the default pick on first run.
const AVATAR_DEFAULT_CHARACTER = 'clanker';
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

function _avatarCharacters() {
  const comp = _avatar.comp || {};
  const rows = Array.isArray(comp.characters) ? comp.characters.slice() : [];
  // The default lands first on first run — it is the answer to "just
  // pick one for me", and it should not be hunted for in an A-Z list.
  rows.sort((a, b) => {
    if (a.id === AVATAR_DEFAULT_CHARACTER) return -1;
    if (b.id === AVATAR_DEFAULT_CHARACTER) return 1;
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
    const isDefault = ch.id === AVATAR_DEFAULT_CHARACTER;
    return `<button type="button" class="avatar-roster-row${isActive ? ' active' : ''}"
        onclick="avatarChooseCharacter('${esc(ch.id)}')" data-character="${esc(ch.id)}">
      <span class="avatar-roster-face" data-card-for="${esc(ch.id)}">${esc((ch.name || ch.id || '?').charAt(0).toUpperCase())}</span>
      <span class="avatar-roster-text">
        <span class="avatar-roster-name">${esc(ch.name || ch.id)}${isDefault ? '<span class="avatar-roster-tag">default</span>' : ''}</span>
        <span class="avatar-roster-role">${esc(ch.role || 'Companion')}</span>
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

function _avatarRenderStage() {
  const stage = document.getElementById('avatarStage');
  if (!stage) return;
  if (!_avatarChosen()) { _avatarRenderPicker(stage); return; }
  const comp = _avatar.comp || {};
  const ch = comp.character || {};
  const agent = comp.agent || {};
  const name = String(agent.name || '').trim();
  stage.innerHTML = `
    <div class="avatar-stage-grid">
      <div class="avatar-portrait-col">
        <div class="avatar-portrait" id="avatarPortrait" data-state="idle">
          <div class="avatar-portrait-art" id="avatarPortraitArt">${esc((ch.name || '?').charAt(0).toUpperCase())}</div>
          <div class="avatar-portrait-ring" aria-hidden="true"></div>
        </div>
        <div class="avatar-identity">
          <div class="avatar-identity-name">${esc(name || ch.name || 'Companion')}</div>
          <div class="avatar-identity-role">${name && ch.name && name !== ch.name
              ? `playing ${esc(ch.name)} · ${esc(ch.role || 'Companion')}`
              : esc(ch.role || 'Companion')}</div>
        </div>
        <div class="avatar-status" id="avatarStatus"><span class="avatar-status-dot"></span><span id="avatarStatusText">Idle</span></div>
        <button type="button" class="avatar-btn avatar-btn-quiet" onclick="avatarReopenPicker()">Change character</button>
      </div>
      <div class="avatar-feed-col">
        <section class="avatar-card">
          <header class="avatar-card-head">
            <span>Thinking</span>
            <span class="avatar-card-note" id="avatarThoughtNote">between turns and decisions</span>
          </header>
          <div class="avatar-thought" id="avatarThought"><div class="avatar-thought-idle">Nothing on its mind right now.</div></div>
        </section>
        <section class="avatar-card">
          <header class="avatar-card-head"><span>Doing</span><span class="avatar-card-note" id="avatarToolNote"></span></header>
          <div class="avatar-tools" id="avatarTools"><div class="avatar-thought-idle">No tools in flight.</div></div>
        </section>
        <div class="avatar-controls">
          <textarea id="avatarInput" rows="2" placeholder="Say something — or type while it works to steer it"
            onkeydown="_avatarInputKey(event)"></textarea>
          <div class="avatar-control-row">
            <button type="button" class="avatar-btn avatar-btn-primary" id="avatarSendBtn" onclick="avatarSend()">Send</button>
            <button type="button" class="avatar-btn avatar-btn-danger" id="avatarStopBtn" onclick="avatarInterrupt()" disabled>Interrupt</button>
            <span class="avatar-control-hint" id="avatarControlHint">It is idle — anything you type starts a turn.</span>
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
    const isDefault = ch.id === AVATAR_DEFAULT_CHARACTER;
    return `<button type="button" class="avatar-pick${isDefault ? ' is-default' : ''}"
        onclick="avatarChooseCharacter('${esc(ch.id)}')">
      <span class="avatar-pick-face" data-card-for="${esc(ch.id)}">${esc((ch.name || ch.id || '?').charAt(0).toUpperCase())}</span>
      <span class="avatar-pick-name">${esc(ch.name || ch.id)}</span>
      <span class="avatar-pick-role">${esc(ch.role || 'Companion')}</span>
      ${isDefault ? '<span class="avatar-pick-tag">Default</span>' : ''}
    </button>`;
  }).join('');
  stage.innerHTML = `
    <div class="avatar-picker">
      <div class="avatar-picker-head">
        <h2>Who are you talking to?</h2>
        <p>Pick a character for your Companion. It changes the voice and manner, not what the agent can do — and you can switch whenever you like.</p>
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
  idle: 'Idle — waiting on you',
  thinking: 'Thinking',
  tool: 'Using a tool',
  working: 'Working',
};

function _avatarTick() {
  const stage = document.getElementById('avatarStage');
  if (!stage || !document.getElementById('avatarThought')) return;
  const running = _avatarRunning();
  const thought = _avatarThoughtText();
  const tools = _avatarToolFeed();
  const phase = _avatarPhase(thought, tools);

  const portrait = document.getElementById('avatarPortrait');
  if (portrait) portrait.dataset.state = phase;
  const statusText = document.getElementById('avatarStatusText');
  if (statusText) {
    const active = tools.find(t => t.state === 'running');
    statusText.textContent = phase === 'tool' && active
      ? `Using ${active.label}` : _AVATAR_PHASE_TEXT[phase];
  }
  const statusEl = document.getElementById('avatarStatus');
  if (statusEl) statusEl.dataset.state = phase;

  if (thought !== _avatar.lastThought) {
    _avatar.lastThought = thought;
    const host = document.getElementById('avatarThought');
    if (host) {
      if (thought) {
        // Rendered as text, never HTML: this is model output.
        host.textContent = thought;
        host.classList.add('has-text');
        host.scrollTop = host.scrollHeight;
      } else {
        host.classList.remove('has-text');
        host.innerHTML = `<div class="avatar-thought-idle">${running
          ? 'Working without narrating.' : 'Nothing on its mind right now.'}</div>`;
      }
    }
    const note = document.getElementById('avatarThoughtNote');
    if (note) note.textContent = thought ? 'live' : 'between turns and decisions';
  }

  const toolHost = document.getElementById('avatarTools');
  if (toolHost) {
    toolHost.innerHTML = tools.length
      ? tools.map(tool => `<div class="avatar-tool-row" data-state="${tool.state}">
          <span class="avatar-tool-dot"></span><span class="avatar-tool-label">${esc(tool.label)}</span>
        </div>`).join('')
      : '<div class="avatar-thought-idle">No tools in flight.</div>';
    toolHost.scrollTop = toolHost.scrollHeight;
  }
  const toolNote = document.getElementById('avatarToolNote');
  if (toolNote) toolNote.textContent = tools.length ? `${tools.length} this turn` : '';

  const stopBtn = document.getElementById('avatarStopBtn');
  if (stopBtn) stopBtn.disabled = !running;
  const sendBtn = document.getElementById('avatarSendBtn');
  if (sendBtn) sendBtn.textContent = running ? 'Steer' : 'Send';
  const hint = document.getElementById('avatarControlHint');
  if (hint && phase !== _avatar.lastPhase) {
    hint.textContent = running
      ? 'It is mid-turn — what you send steers it without stopping it. Interrupt halts it and keeps what it already did.'
      : 'It is idle — anything you type starts a turn.';
  }
  _avatar.lastPhase = phase;
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

/**
 * One button, two meanings, decided by what the agent is doing: idle →
 * start a turn; mid-turn → steer the turn that is already running.
 * Both go through the chat composer's own paths, so an avatar-sent
 * message is indistinguishable downstream from a typed one.
 */
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

/** Halt the running turn. Partial work stays in the transcript. */
async function avatarInterrupt() {
  if (!_avatarRunning()) return;
  try {
    if (typeof cancelStream === 'function') await cancelStream('avatar-interrupt');
    if (typeof showToast === 'function') showToast('Interrupted — it stopped where it was', 2000);
  } catch (err) {
    if (typeof showToast === 'function') showToast('Could not interrupt: ' + (err && err.message), 'error');
  }
  _avatarTick();
}
