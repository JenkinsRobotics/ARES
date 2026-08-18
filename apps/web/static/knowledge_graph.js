/**
 * ARES Knowledge Vault - Interactive Force-Directed Knowledge Graph (Web Map)
 * 
 * Provides an Obsidian-style 2D force-directed knowledge map rendered on Canvas 2D.
 * Features smooth 60fps physics, pan/zoom, node dragging, cluster coloring,
 * search highlighting, and click-to-inspect side panel.
 */

(function() {
  'use strict';

  // State
  let _canvas = null;
  let _ctx = null;
  let _graphData = { nodes: [], links: [], clusters: [], tags: [], stats: {} };
  let _nodes = [];
  let _links = [];
  let _nodeMap = new Map();
  let _animId = null;
  let _isSimulating = true;
  let _activeCluster = 'all';
  let _activeTag = 'all';
  let _searchQuery = '';
  let _hoveredNode = null;
  let _selectedNode = null;
  let _draggedNode = null;

  // Viewport transform
  let _panX = 0;
  let _panY = 0;
  let _zoom = 1.0;
  let _isPanning = false;
  let _startX = 0;
  let _startY = 0;

  // Color palette for clusters (Cyberpunk / ARES dark aesthetic)
  const CLUSTER_COLORS = [
    '#08ebf1', // Neon Cyan
    '#a855f7', // Vivid Purple
    '#3b82f6', // Bright Blue
    '#10b981', // Emerald
    '#f59e0b', // Amber
    '#ec4899', // Pink
    '#6366f1', // Indigo
    '#14b8a6', // Teal
    '#f97316', // Orange
    '#8b5cf6', // Violet
  ];

  function _getClusterColor(cluster) {
    if (!cluster || cluster === 'General') return '#08ebf1';
    let hash = 0;
    for (let i = 0; i < cluster.length; i++) {
      hash = cluster.charCodeAt(i) + ((hash << 5) - hash);
    }
    const idx = Math.abs(hash) % CLUSTER_COLORS.length;
    return CLUSTER_COLORS[idx];
  }

  // ── Physics Simulation Step ──
  function _stepPhysics() {
    if (!_isSimulating) return;

    const width = _canvas ? _canvas.width : 800;
    const height = _canvas ? _canvas.height : 600;
    const cx = width / 2;
    const cy = height / 2;

    const repulsion = 450;
    const springLength = 65;
    const springStrength = 0.04;
    const centerGravity = 0.015;
    const damping = 0.88;

    // Center gravity
    for (let i = 0; i < _nodes.length; i++) {
      const n = _nodes[i];
      if (n === _draggedNode) continue;
      n.vx += (cx - n.x) * centerGravity;
      n.vy += (cy - n.y) * centerGravity;
    }

    // Node-node repulsion (Coulomb)
    for (let i = 0; i < _nodes.length; i++) {
      const n1 = _nodes[i];
      for (let j = i + 1; j < _nodes.length; j++) {
        const n2 = _nodes[j];
        let dx = n2.x - n1.x;
        let dy = n2.y - n1.y;
        let dist = Math.sqrt(dx * dx + dy * dy) || 1;
        if (dist < 350) {
          const force = (repulsion / (dist * dist)) * (n1.cluster === n2.cluster ? 0.7 : 1.2);
          const fx = (dx / dist) * force;
          const fy = (dy / dist) * force;
          if (n1 !== _draggedNode) { n1.vx -= fx; n1.vy -= fy; }
          if (n2 !== _draggedNode) { n2.vx += fx; n2.vy += fy; }
        }
      }
    }

    // Link spring forces (Hooke)
    for (let i = 0; i < _links.length; i++) {
      const link = _links[i];
      const s = link.sourceNode;
      const t = link.targetNode;
      if (!s || !t) continue;
      let dx = t.x - s.x;
      let dy = t.y - s.y;
      let dist = Math.sqrt(dx * dx + dy * dy) || 1;
      const displacement = dist - springLength;
      const force = displacement * springStrength;
      const fx = (dx / dist) * force;
      const fy = (dy / dist) * force;
      if (s !== _draggedNode) { s.vx += fx; s.vy += fy; }
      if (t !== _draggedNode) { t.vx -= fx; t.vy -= fy; }
    }

    // Update positions and apply velocity damping
    for (let i = 0; i < _nodes.length; i++) {
      const n = _nodes[i];
      if (n === _draggedNode) continue;
      n.vx *= damping;
      n.vy *= damping;
      n.x += n.vx;
      n.y += n.vy;
    }
  }

  // ── Render Frame ──
  function _renderFrame() {
    if (!_canvas || !_ctx) return;

    _stepPhysics();

    const w = _canvas.width;
    const h = _canvas.height;

    _ctx.save();
    _ctx.clearRect(0, 0, w, h);

    // Apply pan and zoom transform
    _ctx.translate(_panX, _panY);
    _ctx.scale(_zoom, _zoom);

    // Render subtle grid lines
    _renderGrid(w, h);

    // Find connected nodes if a node is hovered or selected
    const focusNode = _hoveredNode || _selectedNode;
    const connectedIds = new Set();
    if (focusNode) {
      connectedIds.add(focusNode.id);
      for (const link of _links) {
        if (link.source === focusNode.id) connectedIds.add(link.target);
        if (link.target === focusNode.id) connectedIds.add(link.source);
      }
    }

    // 1. Draw Links
    for (let i = 0; i < _links.length; i++) {
      const link = _links[i];
      const s = link.sourceNode;
      const t = link.targetNode;
      if (!s || !t) continue;

      const isConnected = focusNode && (s === focusNode || t === focusNode);
      const isDimmed = focusNode && !isConnected;

      _ctx.beginPath();
      _ctx.moveTo(s.x, s.y);
      _ctx.lineTo(t.x, t.y);

      if (isConnected) {
        _ctx.strokeStyle = '#08ebf1';
        _ctx.lineWidth = 1.8 / _zoom;
        _ctx.globalAlpha = 0.85;
      } else if (isDimmed) {
        _ctx.strokeStyle = '#1e293b';
        _ctx.lineWidth = 0.5 / _zoom;
        _ctx.globalAlpha = 0.15;
      } else {
        _ctx.strokeStyle = '#334155';
        _ctx.lineWidth = 0.8 / _zoom;
        _ctx.globalAlpha = 0.4;
      }
      _ctx.stroke();
    }
    _ctx.globalAlpha = 1.0;

    // 2. Draw Nodes
    for (let i = 0; i < _nodes.length; i++) {
      const node = _nodes[i];
      const isFocused = focusNode === node;
      const isConnected = focusNode && connectedIds.has(node.id);
      const isDimmed = focusNode && !isConnected;
      const isMatch = _searchQuery && node.title.toLowerCase().includes(_searchQuery);

      const radius = isFocused ? node.size * 1.3 : node.size;
      const color = _getClusterColor(node.cluster);

      _ctx.save();
      if (isDimmed && !isMatch) {
        _ctx.globalAlpha = 0.2;
      }

      // Outer glow for focused or matching nodes
      if (isFocused || isMatch) {
        _ctx.shadowColor = color;
        _ctx.shadowBlur = 16;
      }

      // Node Body
      _ctx.beginPath();
      _ctx.arc(node.x, node.y, radius, 0, Math.PI * 2);
      _ctx.fillStyle = color;
      _ctx.fill();

      // Node Border
      _ctx.lineWidth = (isFocused ? 2.5 : 1) / _zoom;
      _ctx.strokeStyle = isFocused ? '#ffffff' : 'rgba(0,0,0,0.5)';
      _ctx.stroke();

      // Node Label (shown if focused, high degree, or zoom > 1.2)
      const showLabel = isFocused || isConnected || isMatch || node.degree > 3 || _zoom > 1.3;
      if (showLabel) {
        _ctx.font = `${Math.max(10, Math.min(14, 11 / _zoom))}px -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif`;
        _ctx.fillStyle = isFocused ? '#ffffff' : '#cbd5e1';
        _ctx.shadowBlur = 4;
        _ctx.shadowColor = '#000000';
        _ctx.textAlign = 'center';
        _ctx.fillText(node.title, node.x, node.y + radius + 13 / _zoom);
      }

      _ctx.restore();
    }

    _ctx.restore();

    _animId = requestAnimationFrame(_renderFrame);
  }

  function _renderGrid(w, h) {
    _ctx.save();
    _ctx.strokeStyle = 'rgba(255,255,255,0.03)';
    _ctx.lineWidth = 1 / _zoom;
    const step = 80;
    const startX = -(_panX / _zoom) % step - step;
    const startY = -(_panY / _zoom) % step - step;
    const endX = startX + (w / _zoom) + step * 2;
    const endY = startY + (h / _zoom) + step * 2;

    _ctx.beginPath();
    for (let x = startX; x < endX; x += step) {
      _ctx.moveTo(x, startY);
      _ctx.lineTo(x, endY);
    }
    for (let y = startY; y < endY; y += step) {
      _ctx.moveTo(startX, y);
      _ctx.lineTo(endX, y);
    }
    _ctx.stroke();
    _ctx.restore();
  }

  // ── Mouse & Touch Event Handlers ──
  function _setupInteractions() {
    if (!_canvas) return;

    _canvas.addEventListener('mousedown', function(e) {
      const rect = _canvas.getBoundingClientRect();
      const mouseX = e.clientX - rect.left;
      const mouseY = e.clientY - rect.top;
      const worldPos = _screenToWorld(mouseX, mouseY);
      const clicked = _findNodeAt(worldPos.x, worldPos.y);

      if (clicked) {
        _draggedNode = clicked;
        _selectedNode = clicked;
        _openInspector(clicked);
      } else {
        _isPanning = true;
        _startX = mouseX - _panX;
        _startY = mouseY - _panY;
      }
    });

    window.addEventListener('mousemove', function(e) {
      if (!_canvas) return;
      const rect = _canvas.getBoundingClientRect();
      const mouseX = e.clientX - rect.left;
      const mouseY = e.clientY - rect.top;

      if (_draggedNode) {
        const worldPos = _screenToWorld(mouseX, mouseY);
        _draggedNode.x = worldPos.x;
        _draggedNode.y = worldPos.y;
        _draggedNode.vx = 0;
        _draggedNode.vy = 0;
        return;
      }

      if (_isPanning) {
        _panX = mouseX - _startX;
        _panY = mouseY - _startY;
        return;
      }

      // Hover check
      const worldPos = _screenToWorld(mouseX, mouseY);
      const hovered = _findNodeAt(worldPos.x, worldPos.y);
      if (hovered !== _hoveredNode) {
        _hoveredNode = hovered;
        _canvas.style.cursor = hovered ? 'pointer' : 'default';
      }
    });

    window.addEventListener('mouseup', function() {
      _draggedNode = null;
      _isPanning = false;
    });

    _canvas.addEventListener('wheel', function(e) {
      e.preventDefault();
      const rect = _canvas.getBoundingClientRect();
      const mouseX = e.clientX - rect.left;
      const mouseY = e.clientY - rect.top;

      const zoomFactor = e.deltaY < 0 ? 1.15 : 0.85;
      const newZoom = Math.max(0.2, Math.min(4.0, _zoom * zoomFactor));

      // Zoom towards mouse pointer
      _panX = mouseX - (mouseX - _panX) * (newZoom / _zoom);
      _panY = mouseY - (mouseY - _panY) * (newZoom / _zoom);
      _zoom = newZoom;
    }, { passive: false });
  }

  function _screenToWorld(sx, sy) {
    return {
      x: (sx - _panX) / _zoom,
      y: (sy - _panY) / _zoom,
    };
  }

  function _findNodeAt(wx, wy) {
    for (let i = _nodes.length - 1; i >= 0; i--) {
      const n = _nodes[i];
      const dx = n.x - wx;
      const dy = n.y - wy;
      const dist = Math.sqrt(dx * dx + dy * dy);
      if (dist <= n.size + 4) return n;
    }
    return null;
  }

  // ── Inspector Drawer & Interaction ──
  async function _openInspector(node) {
    const drawer = document.getElementById('knowledgeInspectorDrawer');
    if (!drawer) return;

    drawer.innerHTML = `
      <div class="inspector-header">
        <div class="inspector-title-wrap">
          <span class="inspector-badge" style="background:${_getClusterColor(node.cluster)}22;color:${_getClusterColor(node.cluster)};border:1px solid ${_getClusterColor(node.cluster)}55">${node.cluster}</span>
          <h3 class="inspector-title">${_esc(node.title)}</h3>
          <div class="inspector-meta">${node.rel_path} • ${node.degree} connection(s)</div>
        </div>
        <button class="inspector-close-btn" onclick="window.AresKnowledgeGraph.closeInspector()">&times;</button>
      </div>
      <div class="inspector-tags">
        ${(node.tags || []).map(t => `<span class="inspector-tag">#${_esc(t)}</span>`).join('')}
      </div>
      <div class="inspector-actions">
        <button class="inspector-btn primary" onclick="window.AresKnowledgeGraph.askAssistantAbout('${_esc(node.title)}')">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>
          Ask ${_esc(_assistantName())}
        </button>
        <button class="inspector-btn" onclick="window.AresKnowledgeGraph.openInEditor('${_esc(node.full_path)}')">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/><path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/></svg>
          Open in Editor
        </button>
      </div>
      <div class="inspector-body" id="inspectorDocContent">
        <div style="padding:16px;color:var(--muted);font-size:13px">Loading note transcript...</div>
      </div>
    `;
    drawer.classList.add('open');

    try {
      const res = await fetch(`/api/knowledge/document?path=${encodeURIComponent(node.full_path)}`);
      const data = await res.json();
      const bodyEl = document.getElementById('inspectorDocContent');
      if (bodyEl && data.ok) {
        bodyEl.innerHTML = `<pre class="inspector-markdown-view">${_esc(data.content)}</pre>`;
      }
    } catch (e) {
      console.warn('Failed loading document:', e);
    }
  }

  function _closeInspector() {
    const drawer = document.getElementById('knowledgeInspectorDrawer');
    if (drawer) drawer.classList.remove('open');
    _selectedNode = null;
  }

  // The assistant's name is owned by the runtime and surfaced by ui.js.
  // Hardcoding it here drifts the moment a user renames their companion.
  function _assistantName() {
    if (typeof assistantDisplayName === 'function') return assistantDisplayName();
    return window._botName || 'ARES';
  }

  function _esc(str) {
    if (!str) return '';
    return String(str).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  }

  // ── Public API ──
  window.AresKnowledgeGraph = {
    async init(containerEl) {
      if (!containerEl) return;
      containerEl.innerHTML = `
        <div class="knowledge-graph-shell">
          <div class="graph-top-toolbar">
            <div class="graph-search-wrap">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="11" cy="11" r="8"/><path d="M21 21l-4.35-4.35"/></svg>
              <input id="graphSearchInput" type="search" placeholder="Search knowledge graph..." oninput="window.AresKnowledgeGraph.filterSearch(this.value)">
            </div>
            <div class="graph-controls-wrap">
              <select id="graphClusterSelect" onchange="window.AresKnowledgeGraph.filterCluster(this.value)">
                <option value="all">All Folders</option>
              </select>
              <button class="graph-ctrl-btn" onclick="window.AresKnowledgeGraph.zoomIn()" title="Zoom In">+</button>
              <button class="graph-ctrl-btn" onclick="window.AresKnowledgeGraph.zoomOut()" title="Zoom Out">-</button>
              <button class="graph-ctrl-btn" onclick="window.AresKnowledgeGraph.resetView()" title="Center View">⊙</button>
              <button class="graph-ctrl-btn" onclick="window.AresKnowledgeGraph.togglePhysics()" id="btnGraphPhysics" title="Pause Physics">⏸</button>
              <button class="graph-ctrl-btn" onclick="window.AresKnowledgeGraph.reload()" title="Refresh Graph">⟳</button>
            </div>
          </div>
          <div class="graph-canvas-wrap" id="graphCanvasWrap">
            <canvas id="knowledgeGraphCanvas"></canvas>
            <div class="graph-stats-chip" id="graphStatsChip">Loading vault...</div>
            <div class="knowledge-inspector-drawer" id="knowledgeInspectorDrawer"></div>
          </div>
        </div>
      `;

      _canvas = document.getElementById('knowledgeGraphCanvas');
      if (!_canvas) return;
      _ctx = _canvas.getContext('2d');

      this.resize();
      window.addEventListener('resize', () => this.resize());
      _setupInteractions();

      await this.reload();

      if (!_animId) _renderFrame();
    },

    resize() {
      const wrap = document.getElementById('graphCanvasWrap');
      if (wrap && _canvas) {
        _canvas.width = wrap.clientWidth;
        _canvas.height = wrap.clientHeight;
      }
    },

    async reload() {
      const statsChip = document.getElementById('graphStatsChip');
      if (statsChip) statsChip.textContent = 'Scanning vault...';

      try {
        const res = await fetch('/api/knowledge/graph?max_nodes=500');
        _graphData = await res.json();

        if (!_graphData.ok || !_graphData.nodes) {
          if (statsChip) statsChip.textContent = 'No knowledge files found';
          return;
        }

        const width = _canvas ? _canvas.width : 800;
        const height = _canvas ? _canvas.height : 600;

        _nodeMap.clear();
        _nodes = _graphData.nodes.map((n, i) => {
          const angle = (i / _graphData.nodes.length) * Math.PI * 2;
          const r = Math.min(width, height) * 0.35 * Math.sqrt(Math.random());
          const node = {
            ...n,
            x: width / 2 + Math.cos(angle) * r + (Math.random() - 0.5) * 50,
            y: height / 2 + Math.sin(angle) * r + (Math.random() - 0.5) * 50,
            vx: 0,
            vy: 0,
          };
          _nodeMap.set(node.id, node);
          return node;
        });

        _links = (_graphData.links || []).map(l => ({
          ...l,
          sourceNode: _nodeMap.get(l.source),
          targetNode: _nodeMap.get(l.target),
        })).filter(l => l.sourceNode && l.targetNode);

        // Update cluster dropdown
        const clusterSelect = document.getElementById('graphClusterSelect');
        if (clusterSelect && _graphData.clusters) {
          clusterSelect.innerHTML = `<option value="all">All Folders (${_graphData.clusters.length})</option>` +
            _graphData.clusters.map(c => `<option value="${_esc(c)}">${_esc(c)}</option>`).join('');
        }

        if (statsChip && _graphData.stats) {
          statsChip.textContent = `${_graphData.stats.total_documents} documents • ${_graphData.stats.visible_links} links`;
        }

        this.resetView();
      } catch (e) {
        if (statsChip) statsChip.textContent = 'Failed to load graph';
        console.error('Failed loading knowledge graph:', e);
      }
    },

    filterSearch(query) {
      _searchQuery = (query || '').toLowerCase().trim();
    },

    filterCluster(cluster) {
      _activeCluster = cluster || 'all';
      if (_activeCluster === 'all') {
        _nodes = _graphData.nodes.map(n => _nodeMap.get(n.id) || n);
      } else {
        _nodes = _graphData.nodes.filter(n => n.cluster === _activeCluster).map(n => _nodeMap.get(n.id) || n);
      }
      const activeIds = new Set(_nodes.map(n => n.id));
      _links = (_graphData.links || []).map(l => ({
        ...l,
        sourceNode: _nodeMap.get(l.source),
        targetNode: _nodeMap.get(l.target),
      })).filter(l => l.sourceNode && l.targetNode && activeIds.has(l.source) && activeIds.has(l.target));
    },

    zoomIn() {
      _zoom = Math.min(4.0, _zoom * 1.25);
    },

    zoomOut() {
      _zoom = Math.max(0.2, _zoom * 0.8);
    },

    resetView() {
      _zoom = 1.0;
      _panX = 0;
      _panY = 0;
    },

    togglePhysics() {
      _isSimulating = !_isSimulating;
      const btn = document.getElementById('btnGraphPhysics');
      if (btn) btn.textContent = _isSimulating ? '⏸' : '▶';
    },

    closeInspector() {
      _closeInspector();
    },

    askAssistantAbout(title) {
      _closeInspector();
      if (typeof switchPanel === 'function') switchPanel('chat');
      const msgInput = document.getElementById('msg');
      if (msgInput) {
        msgInput.value = `Tell me about what our knowledge base says regarding: ${title}`;
        msgInput.focus();
      }
    },

    openInEditor(filePath) {
      _closeInspector();
      if (typeof openExternalNotesSourcePath === 'function') {
        openExternalNotesSourcePath(filePath);
      } else if (typeof switchPanel === 'function') {
        switchPanel('memory');
      }
    },
  };
})();
