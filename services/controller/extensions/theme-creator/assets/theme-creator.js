/* Theme Creator extension for ARES — build custom themes with live preview, image upload, glassmorphism */
;(() => {
  'use strict'

  if (window.__hermesThemeCreatorLoaded) return
  window.__hermesThemeCreatorLoaded = true

  const EXT = 'theme-creator', STORE_KEY = 'hermes-ext-custom-themes', KEY_PREFIX = 'custom-'
  const RAIL_BTN_ID = 'hwxThemeCreatorRailBtn', PANEL_ID = 'hwxThemeCreatorPanel', BG_STYLE_ID = 'hwxThemeCreatorBgStyles'
  const MAX_IMAGE_DIM = 1920, IMAGE_QUALITY = 0.7, MAX_THEMES = 50, MAX_STORE_BYTES = 2 * 1024 * 1024
  const THEME_KEY_RE = /^custom-[a-z0-9_-]+$/
  const DATA_IMAGE_RE = /^data:image\/(?:png|jpeg|jpg|gif|webp);base64,[A-Za-z0-9+/]+={0,2}$/
  const FIELDS = [
    { id: 'bg', label: 'Background', def: '#0d0d1a' },
    { id: 'surface', label: 'Panels / surfaces', def: '#16161f' },
    { id: 'text', label: 'Text', def: '#f5f5f5' },
    { id: 'muted', label: 'Muted text', def: '#9aa0b5' },
    { id: 'accent', label: 'Accent', def: '#f5c542' },
    { id: 'border', label: 'Borders', def: '#2a2a3a' },
    { id: 'userBubble', label: 'Your message bubble', def: '#26314a' },
  ]
  let editing = null, previewKey = null, prevSkinBeforePreview = null, _currentBgImage = null, _currentGlassOpacity = .08, _currentBlur = 20

  // ── helpers ──
  const $ = (s, p = document) => p.querySelector(s)
  const $$ = (s, p = document) => p.querySelectorAll(s)
  const hexToRgb = h => { h = (h || '').trim().replace('#', ''); if (h.length === 3) h = h.split('').map(c => c + c).join(''); return /^[0-9a-fA-F]{6}$/.test(h) ? { r: parseInt(h.slice(0, 2), 16), g: parseInt(h.slice(2, 4), 16), b: parseInt(h.slice(4, 6), 16) } : null }
  const rgbStr = h => { const c = hexToRgb(h); return c ? c.r + ',' + c.g + ',' + c.b : '0,0,0' }
  const clamp = n => Math.max(0, Math.min(255, Math.round(n)))
  const toHex = c => '#' + [c.r, c.g, c.b].map(v => clamp(v).toString(16).padStart(2, '0')).join('')
  const mix = (a, b, t) => { const ca = hexToRgb(a), cb = hexToRgb(b); if (!ca || !cb) return a; return toHex({ r: ca.r + (cb.r - ca.r) * t, g: ca.g + (cb.g - ca.g) * t, b: ca.b + (cb.b - ca.b) * t }) }
  const luminance = h => { const c = hexToRgb(h); return c ? (.2126 * c.r + .7152 * c.g + .0722 * c.b) / 255 : 0 }
  const readableOn = h => luminance(h) > .5 ? '#111111' : '#ffffff'
  const isHex = s => /^#([0-9a-fA-F]{3}|[0-9a-fA-F]{6})$/.test(String(s || '').trim())
  const esc = s => String(s == null ? '' : s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#39;')
  const slugify = name => {
    const body = String(name || '').toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '').slice(0, 32).replace(/-+$/g, '')
    return KEY_PREFIX + (body || 'theme')
  }
  const hasCap = () => typeof window.registerHermesSkin === 'function'
  const sliderSection = (cls, label, min, max, unit, val) =>
    '<div class="hwx-tc-' + cls + '-section"><div class="hwx-tc-section-title" style="margin-top:14px">' + label + ' <span class="hwx-tc-muted">(' + min + '-' + max + unit + ')</span></div>'
    + '<div class="hwx-tc-' + cls + '-row"><input type="range" class="hwx-tc-' + cls + '-slider" min="' + min + '" max="' + max + '" value="' + val + '" aria-label="' + label + '"><span class="hwx-tc-' + cls + '-label">' + val + unit + '</span></div></div>'
  function bindSlider(host, name, fn) {
    const el = $('.hwx-tc-' + name + '-slider', host)
    if (!el) return
    el.addEventListener('input', function () { const v = Number(this.value); fn(v); const lbl = $('.hwx-tc-' + name + '-label', host); if (lbl) lbl.textContent = this.value + (name === 'glass' ? '%' : 'px'); if (previewKey) updatePreview() })
  }

  // ── storage ──
  function loadThemes() { try { const r = localStorage.getItem(STORE_KEY); if (!r) return []; const a = JSON.parse(r); return Array.isArray(a) ? a.reduce((acc, t) => { const v = validTheme(t); if (v) acc.push(v); return acc }, []) : [] } catch (_) { return [] } }
  function saveThemes(t) { try { const capped = (t || []).slice(0, MAX_THEMES), json = JSON.stringify(capped); if (json.length > MAX_STORE_BYTES) return false; localStorage.setItem(STORE_KEY, json); return true } catch (_) { return false } }
  function validTheme(t) {
    if (!t || typeof t !== 'object') return null; const key = String(t.key || ''); if (!THEME_KEY_RE.test(key)) return null; if (!t.base || typeof t.base !== 'object') return null
    const base = {}; for (const f of FIELDS) { const v = t.base[f.id]; if (!isHex(v)) return null; base[f.id] = v }
    // bgImage is interpolated into background-image:url("...") — validate strictly
    // on READ (a tampered localStorage record must not break out of the CSS string
    // or smuggle an external url()). Require a real base64 raster data-URL and cap size.
    base.bgImage = (typeof t.base.bgImage === 'string' && DATA_IMAGE_RE.test(t.base.bgImage) && t.base.bgImage.length <= 500000) ? t.base.bgImage : null
    base.glassOpacity = typeof t.base.glassOpacity === 'number' && t.base.glassOpacity > 0 && t.base.glassOpacity <= .5 ? t.base.glassOpacity : .08
    base.blur = typeof t.base.blur === 'number' && t.base.blur >= 0 && t.base.blur <= 50 ? t.base.blur : 20
    return { key, name: String(t.name || key).slice(0, 28), base }
  }

  // ── image upload ──
  function compressImage(file, maxW, quality) {
    return new Promise((resolve, reject) => {
      const reader = new FileReader()
      reader.onload = e => {
        const img = new Image()
        img.onload = () => {
          let w = img.width, h = img.height
          if (w > maxW) { h = h * maxW / w; w = maxW }
          const canvas = document.createElement('canvas'); canvas.width = w; canvas.height = h
          const ctx = canvas.getContext('2d'); ctx.drawImage(img, 0, 0, w, h)
          resolve(canvas.toDataURL('image/jpeg', quality))
        }
        img.onerror = () => reject(new Error('Image decode failed'))
        img.src = e.target.result
      }
      reader.onerror = () => reject(new Error('File read failed'))
      reader.readAsDataURL(file)
    })
  }

  // ── CSS rule generator (scopes each selector in a group to the theme key) ──
  function _rule(key, selGroup, props) {
    const prefix = ':root[data-skin="' + key + '"]', darkPrefix = ':root.dark[data-skin="' + key + '"]'
    return selGroup.split(',').map(s => {
      const trimmed = s.trim(); const suffix = trimmed ? ' ' + trimmed : ''
      return prefix + suffix + ',' + darkPrefix + suffix
    }).join(',') + '{' + props + '}'
  }

  function renderStyles(extra) {
    let el = document.getElementById(BG_STYLE_ID)
    if (!el) { el = document.createElement('style'); el.id = BG_STYLE_ID; document.head.appendChild(el) }
    const themes = loadThemes().map(t => ({ key: t.key, base: t.base }))
    if (extra && extra.key && extra.base) themes.push(extra)
    
    const rules = []
    for (const e of themes) {
      // 1. Core color tokens — always needed (solid fallback, glass mode overrides later)
      const ct = deriveTokens(e.base)
      rules.push(_rule(e.key, '', Object.keys(ct).map(k => k + ':' + ct[k] + '!important').join(';')))
      // 2. Glass / background-image mode
      if (e.base.bgImage) {
        const brgb = rgbStr(e.base.bg), sRgb = rgbStr(e.base.surface), uRgb = rgbStr(e.base.userBubble)
        const op = e.base.glassOpacity || .08, bgOp = Math.min(op * 1.5, .4), sOp = op, iOp = op * .85, cOp = op * .7
        const blurPx = Math.max(0, Math.min(50, Number.isFinite(e.base.blur) ? e.base.blur : 20))
        const blur = 'backdrop-filter:blur(' + blurPx + 'px)!important;-webkit-backdrop-filter:blur(' + blurPx + 'px)!important'
        rules.push(
          _rule(e.key, '', 'background-image:url("' + e.base.bgImage + '")!important;background-size:cover!important;background-position:center!important;background-repeat:no-repeat!important;background-attachment:fixed!important;'
            + '--bg:rgba(' + brgb + ',' + bgOp + ')!important;--surface:rgba(' + sRgb + ',' + sOp + ')!important;--surface2:rgba(' + sRgb + ',' + iOp + ')!important;--surface-subtle:rgba(' + sRgb + ',' + iOp + ')!important;'
            + '--sidebar:rgba(' + sRgb + ',' + sOp + ')!important;--user-bubble:rgba(' + uRgb + ',' + cOp + ')!important;--assistant-bubble:rgba(' + sRgb + ',' + sOp + ')!important;--main-bg:transparent!important'),
          _rule(e.key, 'nav, main, body', blur + ';background:transparent!important'),
          _rule(e.key, '.rail, .sidebar, .rightpanel', 'background:rgba(' + sRgb + ',' + sOp + ')!important;' + blur),
          _rule(e.key, '.main-view', 'background:rgba(' + brgb + ',' + bgOp + ')!important;' + blur),
          _rule(e.key, '.messages-shell, .composer-wrap, .composer-box', blur),
          _rule(e.key, '.composer-flyout, .approval-card, .clarify-card', 'background:rgba(' + sRgb + ',' + cOp + ')!important;' + blur),
          _rule(e.key, '.composer-terminal-panel, .empty-state', blur)
        )
      }
      // 3. Code/chat token overrides
      const toks = codeTokensFor(e.base)
      rules.push(_rule(e.key, '', Object.keys(toks).map(k => k + ':' + toks[k] + '!important').join(';')))
    }
    el.textContent = rules.join('\n')
  }

  // ── token derivation ──
  function deriveTokens(b) {
    const dark = luminance(b.bg) < .5, isW = dark ? '#ffffff' : '#000000'
    return {
      '--bg': b.bg, '--surface': b.surface, '--surface2': mix(b.surface, isW, .06), '--surface-subtle': mix(b.surface, isW, .06),
      '--text': b.text, '--text2': mix(b.text, b.bg, .15), '--muted': b.muted,
      '--accent': b.accent, '--accent2': b.accent, '--accent-hover': mix(b.accent, isW, .18),
      '--accent-text': b.accent, '--accent-contrast': readableOn(b.accent),
      '--accent-bg': 'rgba(' + rgbStr(b.accent) + ',.14)', '--accent-bg-strong': 'rgba(' + rgbStr(b.accent) + ',.26)', '--accent-rgb': rgbStr(b.accent),
      '--border': b.border, '--border2': mix(b.border, b.text, .18), '--hover-bg': mix(b.surface, b.text, .08),
      '--code-bg': mix(b.bg, isW, .04), '--code-text': b.text, '--sidebar': b.surface, '--sidebar-text': b.text,
      '--user-bubble': b.userBubble, '--assistant-bubble': b.surface, '--link': b.accent,
    }
  }
  function descriptorFor(t) { return { name: t.name, value: t.key, colors: [t.base.accent, t.base.bg, t.base.surface], tokens: deriveTokens(t.base) } }

  // ── code / chat token coverage (bridges core allowlist gaps) ──
  function codeTokensFor(b) {
    const dark = luminance(b.bg) < .5
    return {
      '--strong': mix(b.text, dark ? '#ffffff' : '#000000', .15),
      '--code-bg': mix(b.bg, dark ? '#ffffff' : '#000000', .04), '--code-text': b.text,
      '--code-inline-bg': 'rgba(' + rgbStr(dark ? '#ffffff' : '#000000') + ',' + (dark ? '.08' : '.06') + ')',
      '--pre-text': b.text, '--input-bg': mix(b.surface, dark ? '#ffffff' : '#000000', .03),
    }
  }

  // ── skin registration ──
  function registerAll() {
    if (!hasCap()) return 0
    let n = 0
    for (const t of loadThemes()) { try { if (window.registerHermesSkin(descriptorFor(t))) n++ } catch (_) {} }
    renderStyles()
    // Re-apply the active custom skin (core may have tried before skins were registered)
    try { const a = localStorage.getItem('hermes-skin') || ''; if (THEME_KEY_RE.test(a) && loadThemes().some(t => t.key === a)) applySkin(a) } catch (_) {}
    return n
  }

  // ── rail button ──
  function ensureRailButton() {
    if (document.getElementById(RAIL_BTN_ID)) return
    const rail = document.querySelector('.rail')
    if (!rail) return
    const btn = document.createElement('button')
    btn.id = RAIL_BTN_ID; btn.type = 'button'; btn.className = 'rail-btn nav-tab has-tooltip hwx-tc-rail'
    btn.dataset.tooltip = 'Theme Creator'; btn.setAttribute('aria-label', 'Theme Creator')
    btn.innerHTML = '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="13.5" cy="6.5" r="2.5"/><circle cx="6.5" cy="11.5" r="2.5"/><circle cx="16.5" cy="14.5" r="2.5"/><path d="M3 21h18"/></svg>'
    btn.addEventListener('click', ev => { ev.preventDefault(); openPanel() })
    const spacer = rail.querySelector('.rail-spacer')
    if (spacer) rail.insertBefore(btn, spacer); else rail.appendChild(btn)
  }

  // ── editor panel ──
  function defaultBase() { const b = {}; FIELDS.forEach(f => { b[f.id] = f.def }); b.bgImage = null; b.glassOpacity = .08; b.blur = 20; return b }
  function currentBaseFromInputs() {
    const panel = document.getElementById(PANEL_ID)
    const base = {}; FIELDS.forEach(f => { const inp = $('.hwx-tc-color-' + f.id, panel); base[f.id] = inp && isHex(inp.value) ? inp.value : f.def })
    base.bgImage = _currentBgImage; base.glassOpacity = _currentGlassOpacity; base.blur = _currentBlur; return base
  }
  function showErr(msg) { const e = $('#' + PANEL_ID + ' .hwx-tc-err'); if (e) { e.hidden = !msg; e.textContent = msg || '' } }

  function openPanel() {
    closePanel(); editing = null; _currentBgImage = null; _currentGlassOpacity = .08; _currentBlur = 20
    const panel = document.createElement('div')
    panel.id = PANEL_ID; panel.className = 'hwx-tc-panel'
    panel.innerHTML =
      '<div class="hwx-tc-card" role="dialog" aria-label="Theme Creator"><div class="hwx-tc-head">'
      + '<span class="hwx-tc-title">Theme Creator</span>'
      + '<button type="button" class="hwx-tc-x" aria-label="Close">\u2715</button></div>'
      + (hasCap() ? '' : '<div class="hwx-tc-warn">The theme-registration capability isn\u2019t available in this WebUI build (needs core PR #5100). You can still design a theme, but it can\u2019t be applied yet.</div>')
      + '<div class="hwx-tc-body"><div class="hwx-tc-editor"></div><div class="hwx-tc-saved"></div></div></div>'
    document.body.appendChild(panel)
    $('.hwx-tc-x', panel).addEventListener('click', closePanel)
    panel.addEventListener('click', e => { if (e.target === panel) closePanel() })
    document.addEventListener('keydown', escClose, true)
    renderEditor(); renderSaved()
  }
  function escClose(ev) { if (ev.key === 'Escape') closePanel() }
  function closePanel() { cancelPreview(); _currentBgImage = null; _currentGlassOpacity = .08; _currentBlur = 20; const p = document.getElementById(PANEL_ID); if (p) p.remove(); document.removeEventListener('keydown', escClose, true) }

  // ── image handlers ──
  function handleBgUpload(ev) {
    const file = ev.target.files && ev.target.files[0]
    if (!file) return; showErr('')
    compressImage(file, MAX_IMAGE_DIM, IMAGE_QUALITY).then(dataUrl => { _currentBgImage = dataUrl; updateBgPreviewUI(); if (previewKey) updatePreview() }).catch(() => showErr('Failed to process image.'))
  }
  function removeBgImage() { _currentBgImage = null; updateBgPreviewUI(); if (previewKey) updatePreview() }
  function updateBgPreviewUI() {
    const panel = document.getElementById(PANEL_ID); if (!panel) return
    const wrap = $('.hwx-tc-bg-preview-wrap', panel), none = $('.hwx-tc-bg-none', panel), fi = $('.hwx-tc-fileinput', panel)
    if (wrap) wrap.hidden = !_currentBgImage; if (none) none.hidden = !!_currentBgImage
    if (_currentBgImage && wrap) { const img = $('.hwx-tc-bg-preview', wrap); if (img) img.src = _currentBgImage }
    if (fi) fi.value = ''
  }

  // ── editor rendering ──
  function renderEditor() {
    const panel = document.getElementById(PANEL_ID); if (!panel) return
    const host = $('.hwx-tc-editor', panel), base = editing ? editing.base : defaultBase()
    _currentBgImage = base.bgImage || null
    _currentGlassOpacity = base.glassOpacity > 0 ? base.glassOpacity : .08
    _currentBlur = Number.isFinite(base.blur) ? base.blur : 20
    const nameVal = editing ? editing.name : '', hasBg = !!_currentBgImage
    let rows = ''
    FIELDS.forEach(f => { const v = base[f.id] || f.def; rows += '<label class="hwx-tc-row"><span>' + esc(f.label) + '</span><span class="hwx-tc-swatchwrap"><input type="color" class="hwx-tc-color hwx-tc-color-' + f.id + '" value="' + esc(v) + '"><input type="text" class="hwx-tc-hex hwx-tc-hex-' + f.id + '" value="' + esc(v) + '" maxlength="7"></span></label>' })
    host.innerHTML =
      '<div class="hwx-tc-section-title">' + (editing ? 'Edit theme' : 'New theme') + '</div>'
      + '<label class="hwx-tc-namerow"><span>Name</span><input type="text" class="hwx-tc-name" maxlength="28" placeholder="My Theme" value="' + esc(nameVal) + '"></label>'
      + rows
      + '<div class="hwx-tc-bg-section"><div class="hwx-tc-section-title" style="margin-top:14px">Background image <span class="hwx-tc-muted">(optional)</span></div>'
      + '<div class="hwx-tc-bg-row"><label class="hwx-tc-filelabel"><input type="file" accept="image/*" class="hwx-tc-fileinput"><span class="hwx-tc-filelabel-text">Choose image\u2026</span></label>'
      + '<span class="hwx-tc-bg-none"' + (hasBg ? ' hidden' : '') + '>None</span>'
      + '<div class="hwx-tc-bg-preview-wrap"' + (!hasBg ? ' hidden' : '') + '><img class="hwx-tc-bg-preview" src="' + (hasBg ? esc(_currentBgImage) : '') + '" alt="Background"><button type="button" class="hwx-tc-link hwx-tc-remove-img">Remove</button></div></div></div>'
      + sliderSection('glass', 'Glass opacity', 1, 50, '%', Math.round(Math.max(1, Math.min(50, _currentGlassOpacity * 100))))
      + sliderSection('blur', 'Blur intensity', 0, 50, 'px', Math.round(Math.max(0, Math.min(50, _currentBlur))))
      + '<div class="hwx-tc-actions"><button type="button" class="hwx-tc-btn hwx-tc-preview">Live preview</button><button type="button" class="hwx-tc-btn hwx-tc-stoppreview" hidden>Stop preview</button><span class="hwx-tc-spacer"></span>'
      + (editing ? '<button type="button" class="hwx-tc-btn hwx-tc-newbtn">New</button>' : '') + '<button type="button" class="hwx-tc-btn hwx-tc-save">' + (editing ? 'Update' : 'Save') + '</button></div>'
      + '<div class="hwx-tc-err" hidden></div>'

    FIELDS.forEach(f => {
      const color = $('.hwx-tc-color-' + f.id, host), hex = $('.hwx-tc-hex-' + f.id, host)
      color.addEventListener('input', () => { hex.value = color.value; if (previewKey) updatePreview() })
      hex.addEventListener('input', () => { if (isHex(hex.value)) { const val = hex.value; color.value = val.length === 4 ? '#' + val.slice(1).split('').map(c => c + c).join('') : val; if (previewKey) updatePreview() } })
    })
    $('.hwx-tc-preview', host).addEventListener('click', startPreview)
    $('.hwx-tc-stoppreview', host).addEventListener('click', cancelPreview)
    $('.hwx-tc-save', host).addEventListener('click', () => { try { saveCurrent() } catch(e) { console.error('[TC] save error:', e); alert('[TC] ' + e.message) } })
    const nb = $('.hwx-tc-newbtn', host); if (nb) nb.addEventListener('click', () => { editing = null; cancelPreview(); renderEditor() })
    const fileInput = $('.hwx-tc-fileinput', host); if (fileInput) fileInput.addEventListener('change', handleBgUpload)
    const rm = $('.hwx-tc-remove-img', host); if (rm) rm.addEventListener('click', removeBgImage)
    bindSlider(host, 'glass', v => { _currentGlassOpacity = Math.max(.01, Math.min(.5, v / 100)) })
    bindSlider(host, 'blur', v => { _currentBlur = Math.max(0, Math.min(50, v)) })
  }

  // ── live preview ──
  function startPreview() {
    if (!hasCap()) return; const base = currentBaseFromInputs(); previewKey = KEY_PREFIX + 'preview'
    if (prevSkinBeforePreview === null) { try { prevSkinBeforePreview = localStorage.getItem('hermes-skin') || 'default' } catch (_) { prevSkinBeforePreview = 'default' } }
    try { window.registerHermesSkin({ name: 'Preview', value: previewKey, colors: [base.accent, base.bg, base.surface], tokens: deriveTokens(base) }); renderStyles({ key: previewKey, base }); applySkin(previewKey) } catch (_) {}
    togglePreview(true)
  }
  function updatePreview() {
    if (!previewKey || !hasCap()) return; const base = currentBaseFromInputs()
    try { window.registerHermesSkin({ name: 'Preview', value: previewKey, colors: [base.accent, base.bg, base.surface], tokens: deriveTokens(base) }); renderStyles({ key: previewKey, base }); applySkin(previewKey) } catch (_) {}
  }
  function cancelPreview() { if (previewKey && prevSkinBeforePreview !== null) { try { applySkin(prevSkinBeforePreview) } catch (_) {} } previewKey = null; prevSkinBeforePreview = null; togglePreview(false) }
  function togglePreview(on) { const p = document.getElementById(PANEL_ID); if (!p) return; const b1 = $('.hwx-tc-preview', p), b2 = $('.hwx-tc-stoppreview', p); if (b1) b1.hidden = on; if (b2) b2.hidden = !on }
  function applySkin(key) { if (typeof window._pickSkin === 'function') { try { window._pickSkin(key); return } catch (_) {} } document.documentElement.dataset.skin = key === 'default' ? '' : key; try { localStorage.setItem('hermes-skin', key) } catch (_) {} if (!document.documentElement.dataset.skin) delete document.documentElement.dataset.skin }

  // ── save / manage ──
  function saveCurrent() {
    const panel = document.getElementById(PANEL_ID)
    const name = ($('.hwx-tc-name', panel).value || '').trim()
    if (!name) { showErr('Give your theme a name.'); return }
    const base = currentBaseFromInputs()
    for (const f of FIELDS) { if (!isHex(base[f.id])) { showErr('"' + f.label + '" is not a valid colour.'); return } }
    let themes = loadThemes()
    const key = editing ? editing.key : slugify(name), existingIdx = themes.findIndex(t => t.key === key)
    if (!THEME_KEY_RE.test(key)) { showErr('Could not derive a valid theme id from that name \u2014 try a name with letters or numbers.'); return }
    const rec = { key, name: name.slice(0, 28), base }
    if (existingIdx >= 0) themes[existingIdx] = rec
    else { if (themes.length >= MAX_THEMES) { showErr('Theme limit reached (' + MAX_THEMES + '). Delete one before adding another.'); return }; themes.push(rec) }
    if (!saveThemes(themes)) { showErr('Could not save \u2014 theme storage is full. Delete a theme and try again.'); return }
    if (hasCap()) { try { window.registerHermesSkin(descriptorFor(rec)) } catch (_) {} renderStyles(); cancelPreview(); applySkin(key) }
    editing = rec; showErr(''); renderEditor(); renderSaved()
  }

  function renderSaved() {
    const panel = document.getElementById(PANEL_ID); if (!panel) return
    const host = $('.hwx-tc-saved', panel), themes = loadThemes()
    if (!themes.length) { host.innerHTML = '<div class="hwx-tc-section-title">Saved themes</div><div class="hwx-tc-muted">No custom themes yet.</div>'; return }
    let items = ''
    themes.forEach(t => {
      const sw = c => '<span class="hwx-tc-mini" style="background:' + esc(c) + '"></span>'
      const bgIcon = t.base.bgImage
        ? '<span class="hwx-tc-bg-indicator" title="Has background image"><svg width="12" height="12" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="1.5" y="2.5" width="13" height="11" rx="1.5"/><circle cx="5" cy="6.5" r="1"/><path d="M1.5 12l4-4 2 2 3-3 4 4"/></svg></span>'
        : ''
      items += '<div class="hwx-tc-saved-row" data-key="' + esc(t.key) + '"><span class="hwx-tc-swatches">' + sw(t.base.bg) + sw(t.base.surface) + sw(t.base.accent) + '</span>' + bgIcon + '<span class="hwx-tc-saved-name">' + esc(t.name) + '</span><span class="hwx-tc-spacer"></span><button type="button" class="hwx-tc-link hwx-tc-apply">Apply</button><button type="button" class="hwx-tc-link hwx-tc-edit">Edit</button><button type="button" class="hwx-tc-link hwx-tc-del">Delete</button></div>'
    })
    host.innerHTML = '<div class="hwx-tc-section-title">Saved themes</div>' + items
    $$('.hwx-tc-saved-row', host).forEach(row => {
      const key = row.dataset.key
      $('.hwx-tc-apply', row).addEventListener('click', () => { if (hasCap()) applySkin(key) })
      $('.hwx-tc-edit', row).addEventListener('click', () => { const t = loadThemes().find(x => x.key === key); if (t) { editing = JSON.parse(JSON.stringify(t)); cancelPreview(); renderEditor() } })
      $('.hwx-tc-del', row).addEventListener('click', () => {
        let themes = loadThemes().filter(x => x.key !== key); saveThemes(themes); if (editing && editing.key === key) editing = null
        try { if ((localStorage.getItem('hermes-skin') || '') === key) applySkin('default') } catch (_) {}
        renderStyles(); renderEditor(); renderSaved()
      })
    })
  }

  // ── install ──
  function install(attempt) {
    attempt = attempt || 0
    if (document.querySelector('.rail')) {
      ensureRailButton(); registerAll()
      window.HermesThemeCreatorExtension = { version: '0.3.6', themes: loadThemes, open: openPanel, registerAll }
      return true
    }
    if (attempt < 80) { setTimeout(() => install(attempt + 1), 150); return false }
    console.warn('[' + EXT + '] rail not found; not installed')
    return false
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', () => install(), { once: true })
  else install()
})()
