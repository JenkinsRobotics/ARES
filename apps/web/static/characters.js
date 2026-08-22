/* ARES character pill + panel.
   Jaeger owns the roster. ARES only projects /api/companion. */
(function () {
  'use strict';

  var _characters = [];
  var _activeId = '';
  var _selectedId = '';
  var _detail = null;

  function $(id) { return document.getElementById(id); }
  function esc(s) {
    return String(s || '').replace(/[&<>"']/g, function (c) {
      return ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c];
    });
  }
  function cardUrl(id) {
    return '/api/companion/card?character_id=' + encodeURIComponent(id || '');
  }
  function toast(msg) {
    if (typeof showToast === 'function') showToast(msg);
  }
  function apiCall(path, opts) {
    if (typeof api === 'function') return api(path, opts || {});
    return fetch(path, opts || {}).then(function (r) { return r.json(); });
  }

  function traitColor(val) {
    if (val >= 0.75) return 'good';
    if (val >= 0.5) return 'accent';
    if (val >= 0.25) return 'warn';
    return 'danger';
  }
  function traitBar(label, val) {
    var v = Number(val) || 0;
    return '<div class="char-trait-row">' +
      '<span class="char-trait-label">' + esc(label.replace(/_/g, ' ')) + '</span>' +
      '<div class="char-trait-bar"><div class="char-trait-fill ' + traitColor(v) + '" style="width:' + (v * 100) + '%"></div></div>' +
      '<span class="char-trait-val">' + Math.round(v * 100) + '%</span>' +
      '</div>';
  }

  function renderChip() {
    var label = $('aresCharacterLabel');
    var current = _characters.find(function (c) { return c.id === _activeId; })
      || _characters.find(function (c) { return c.active; });
    var name = current && !current.neutral
      ? (current.name || current.id || 'ARES')
      : 'ARES';
    if (label) label.textContent = name;
    var chip = $('aresCharacterChip');
    if (chip) chip.title = 'Select character — ' + name;
  }

  function renderDropdown() {
    var dd = $('aresCharacterDropdown');
    if (!dd) return;
    if (!_characters.length) {
      dd.innerHTML = '<div style="padding:12px;color:var(--muted);font-size:12px">No characters available</div>';
      return;
    }
    dd.innerHTML = _characters.map(function (c) {
      var isNeutral = !!c.neutral;
      var active = isNeutral
        ? (!_activeId || _activeId === 'assistant' || c.active)
        : (c.id === _activeId);
      var name = isNeutral ? 'ARES' : (c.name || c.id);
      var role = isNeutral ? 'Default identity (no character overlay)' : (c.role || c.id);
      var imgHtml = isNeutral
        ? '<span class="char-dropdown-face" style="display:inline-flex;align-items:center;justify-content:center;font-size:13px;font-weight:700;color:var(--text);background:var(--hover-bg)">⚡</span>'
        : '<img class="char-dropdown-face" src="' + cardUrl(c.id) + '" alt="" onerror="this.style.display=\'none\'">';
      return '<button class="profile-dropdown-item' + (active ? ' active' : '') + '" type="button" data-char-id="' + esc(c.id) + '">' +
        '<span class="profile-dropdown-check">' + (active ? '✓' : '') + '</span>' +
        imgHtml +
        '<span class="char-dropdown-copy"><strong>' + esc(name) + '</strong>' +
        '<small class="char-dropdown-role">' + esc(role) + '</small></span></button>';
    }).join('');
    dd.querySelectorAll('[data-char-id]').forEach(function (btn) {
      btn.addEventListener('click', function () {
        select(btn.getAttribute('data-char-id'));
        closeDropdown();
      });
    });
  }

  function listItem(c) {
    var name = c.name || c.id;
    var on = c.id === _selectedId || c.id === _activeId;
    return '<div class="char-list-item' + (on ? ' active' : '') + '" data-char-id="' + esc(c.id) + '">' +
      '<img class="char-list-card" src="' + cardUrl(c.id) + '" alt="' + esc(name) + '" onerror="this.style.display=\'none\'">' +
      '<div class="char-list-info">' +
        '<span class="char-list-name">' + esc(name) + '</span>' +
        '<span class="char-list-role">' + esc(c.role || '—') + '</span>' +
      '</div>' +
      (c.id === _activeId ? '<span class="char-list-badge">ACTIVE</span>' : '') +
      '</div>';
  }

  function renderList() {
    var listEl = $('charsList');
    if (!listEl) return;
    var q = (($('charsSearch') || {}).value || '').trim().toLowerCase();
    var rows = _characters.filter(function (c) {
      if (!q) return true;
      return (c.name || '').toLowerCase().indexOf(q) >= 0
        || (c.role || '').toLowerCase().indexOf(q) >= 0
        || (c.id || '').toLowerCase().indexOf(q) >= 0;
    });
    if (!rows.length) {
      listEl.innerHTML = '<div style="padding:12px;color:var(--muted);font-size:12px">No characters</div>';
      return;
    }
    listEl.innerHTML = rows.map(listItem).join('');
    listEl.querySelectorAll('[data-char-id]').forEach(function (el) {
      el.addEventListener('click', function () {
        showDetail(el.getAttribute('data-char-id'));
      });
    });
  }

  function traitSection(title, map) {
    if (!map || !Object.keys(map).length) return '';
    var html = Object.keys(map).map(function (k) { return traitBar(k, map[k]); }).join('');
    return '<div class="char-trait-section"><h3>' + esc(title) + '</h3><div class="char-trait-grid">' + html + '</div></div>';
  }

  function renderDetail(char) {
    var body = $('characterDetailBody');
    var empty = $('characterDetailEmpty');
    var title = $('characterDetailTitle');
    var selectBtn = $('btnCharSelect');
    if (!body || !empty) return;
    if (!char) {
      body.style.display = 'none';
      empty.style.display = '';
      if (title) title.textContent = '';
      if (selectBtn) selectBtn.style.display = 'none';
      return;
    }
    empty.style.display = 'none';
    body.style.display = '';
    if (title) title.textContent = char.name || char.id;
    if (selectBtn) {
      selectBtn.style.display = '';
      selectBtn.classList.toggle('primary', char.id !== _activeId);
    }
    var traits = char.traits || {};
    var bio = char.backstory || char.soul || '';
    var isActive = char.id === _activeId;
    body.innerHTML = '<div class="char-detail-content">' +
      '<div class="char-detail-hero">' +
        '<img class="char-detail-art" src="' + cardUrl(char.id) + '" alt="' + esc(char.name) + '" onerror="this.style.opacity=0.15">' +
        '<div class="char-detail-meta">' +
          '<h2 class="char-detail-name">' + esc(char.name || char.id) + '</h2>' +
          '<div class="char-detail-role">' + esc(char.role || '—') + '</div>' +
          '<div class="char-detail-voice">' + esc(char.voice_tone || '') + '</div>' +
          '<button class="char-btn-select' + (isActive ? ' active' : '') + '" type="button" data-select-id="' + esc(char.id) + '">' +
            (isActive ? '✓ Active' : 'Set as active') + '</button>' +
        '</div>' +
      '</div>' +
      (bio ? '<div class="char-detail-bio">' + esc(bio) + '</div>' : '') +
      traitSection('Personality (HEXACO)', traits.hexaco) +
      traitSection('Attributes (SPECIAL)', traits.special) +
      traitSection('Expression', traits.expression) +
      traitSection('Domains', traits.domains) +
    '</div>';
    var btn = body.querySelector('[data-select-id]');
    if (btn) btn.addEventListener('click', function () { select(btn.getAttribute('data-select-id')); });
  }

  function showDetail(id) {
    _selectedId = id;
    renderList();
    apiCall('/api/ares/character?id=' + encodeURIComponent(id))
      .then(function (data) {
        _detail = (data && data.character) || _characters.find(function (c) { return c.id === id; }) || { id: id };
        renderDetail(_detail);
      })
      .catch(function () {
        _detail = _characters.find(function (c) { return c.id === id; }) || { id: id };
        renderDetail(_detail);
      });
  }

  function select(id) {
    if (!id) return Promise.resolve();
    return apiCall('/api/companion', {
      method: 'PATCH',
      body: JSON.stringify({ character_id: id }),
    }).then(function (snap) {
      applySnapshot(snap);
      toast('Character set to ' + ((_characters.find(function (c) { return c.id === id; }) || {}).name || id));
      if (_selectedId === id || !_selectedId) showDetail(id);
    }).catch(function (err) {
      toast('Could not set character: ' + (err && err.message ? err.message : err));
    });
  }

  function applySnapshot(snap) {
    var chars = (snap && snap.characters) || [];
    var active = (snap && snap.character) || {};
    _characters = chars;
    _activeId = active.id || (chars.find(function (c) { return c.active; }) || {}).id || '';
    renderChip();
    renderDropdown();
    renderList();
  }

  function load() {
    var listEl = $('charsList');
    if (listEl) listEl.innerHTML = '<div class="chars-loading"><div class="chars-loading-spinner"></div></div>';
    return apiCall('/api/companion')
      .then(function (snap) {
        applySnapshot(snap);
        if (_selectedId) showDetail(_selectedId);
        else if (_activeId) showDetail(_activeId);
        else renderDetail(null);
      })
      .catch(function (err) {
        if (listEl) {
          listEl.innerHTML = '<div style="padding:12px;color:var(--muted);font-size:12px">' +
            esc(err && err.message ? err.message : 'JaegerAI Companion is unavailable') + '</div>';
        }
      });
  }

  function toggleDropdown() {
    var dd = $('aresCharacterDropdown');
    if (!dd) return;
    var open = dd.style.display === 'block';
    if (open) {
      closeDropdown();
      return;
    }
    if (typeof closeProfileDropdown === 'function') closeProfileDropdown();
    if (typeof closeWsDropdown === 'function') closeWsDropdown();
    if (typeof closeModelDropdown === 'function') closeModelDropdown();
    renderDropdown();
    var chip = $('aresCharacterChip') || $('profileChipWrap');
    if (chip) {
      var rect = chip.getBoundingClientRect();
      dd.style.position = 'fixed';
      dd.style.left = Math.max(8, rect.left) + 'px';
      dd.style.bottom = (window.innerHeight - rect.top + 8) + 'px';
      dd.style.zIndex = '300';
    }
    dd.style.display = 'block';
  }
  function closeDropdown() {
    var dd = $('aresCharacterDropdown');
    if (dd) dd.style.display = 'none';
  }

  document.addEventListener('click', function (e) {
    if (!e.target.closest || !e.target.closest('#profileChipWrap')) closeDropdown();
  });

  window.AresCharacters = {
    load: load,
    refreshChip: load,
    select: select,
    filter: function () { renderList(); },
    selectCurrent: function () { if (_selectedId) select(_selectedId); },
    toggleDropdown: toggleDropdown,
    showDetail: showDetail,
  };

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', load);
  } else {
    load();
  }
})();
