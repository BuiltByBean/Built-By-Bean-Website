/* Pluralism Within — Obsidian-style force-directed map of Christian
 * denominations. Ported from Data-Dungeon's /dev/graph viewer.
 *
 * Tech: d3-force handles the physics (link spring + charge repulsion +
 * collision avoidance + center gravity). Render path is custom canvas-2D
 * so the visual style matches the rest of the page.
 *
 * Default view: full graph as an unfocused map. Search "From" to focus
 * a denomination + 1-hop neighbours. Fill "To" as well to see the
 * schism path between two traditions.
 */
(function () {
  'use strict';

  const canvas      = document.getElementById('pg_canvas');
  const ctx         = canvas.getContext('2d');
  const meta        = document.getElementById('pg_meta');
  const searchA     = document.getElementById('pg_search_a');
  const searchB     = document.getElementById('pg_search_b');
  const taA         = document.getElementById('pg_ta_a');
  const taB         = document.getElementById('pg_ta_b');
  const kindChips   = document.getElementById('pg_kind_chips');
  const extinctTog  = document.getElementById('pg_extinct_toggle');
  const sidePanel   = document.getElementById('pg_side');
  const gearBtn     = document.getElementById('pg_gear_btn');
  const gearPanel   = document.getElementById('pg_gear');
  const gearClose   = document.getElementById('pg_gear_close');
  const gearReset   = document.getElementById('pg_gear_reset');
  const sliders = {
    node:       document.getElementById('pg_s_node'),
    link_w:     document.getElementById('pg_s_link_w'),
    label_zoom: document.getElementById('pg_s_label_zoom'),
    center:     document.getElementById('pg_f_center'),
    charge:     document.getElementById('pg_f_charge'),
    link:       document.getElementById('pg_f_link'),
    distance:   document.getElementById('pg_f_distance'),
  };

  // ── Theme ──────────────────────────────────────────────────────
  // FAMILY_* maps are populated from the server payload (meta.families)
  // so the colour vocabulary stays single-sourced in pluralism/__init__.py.
  let FAMILY_COLORS = {};
  let FAMILY_LABELS = {};
  let FAMILY_ORDER  = [];

  // ── State ──────────────────────────────────────────────────────
  let graph = { nodes: [], edges: [] };
  let nodeIndex = new Map();
  let neighbors = new Map();
  const kindEnabled = new Map();
  let endA = { text: '', id: null };
  let endB = { text: '', id: null };
  let extinctOnly = false;
  let selectedId = null;
  let hoveredId = null;
  let snapshotPositions = null;
  let snapshotCam = null;

  let camX = 0, camY = 0, scale = 1;
  let dpr = 1;
  let needsRedraw = true;
  function requestRedraw() { needsRedraw = true; }

  const DEFAULTS = {
    node: 1.0, link_w: 0.7, label_zoom: 1.2,
    center: 0.18, charge: -280, link: 0.4, distance: 80,
  };
  const tune = Object.assign({}, DEFAULTS);

  const LS_KEY = 'pluralism.graph.v1';

  let sim = null;
  let linkForce = null, chargeForce = null, collideForce = null;

  // ── Init ───────────────────────────────────────────────────────
  fetchGraph().then(setup).catch(err => {
    meta.textContent = 'Failed to load graph data';
    console.error(err);
  });

  function fetchGraph() {
    return fetch('/Pluralism/api/graph')
      .then(r => r.json())
      .then(d => {
        if (!d || !d.ok) throw new Error('graph fetch failed');
        return d;
      });
  }

  function setup(g) {
    if (typeof d3 === 'undefined') {
      meta.textContent = 'd3 failed to load — graph unavailable';
      return;
    }
    ingest(g);
    resize();
    initSliders();
    loadState();
    applyState();
    runInitialLayout();

    window.addEventListener('resize', () => { resize(); requestRedraw(); });
    // ResizeObserver catches canvas/stage size changes from layout (e.g.
    // iframe resizes, sidebar mount, font load) — `window.resize` alone
    // misses those because the window isn't what's resizing.
    if (typeof ResizeObserver !== 'undefined') {
      const ro = new ResizeObserver(() => { resize(); requestRedraw(); });
      ro.observe(canvas);
    }
    canvas.addEventListener('pointerdown', onPointerDown);
    canvas.addEventListener('pointermove', onPointerMove);
    canvas.addEventListener('pointerup', onPointerUp);
    canvas.addEventListener('pointercancel', onPointerUp);
    canvas.addEventListener('pointerleave', onPointerLeave);
    canvas.addEventListener('wheel', onWheel, { passive: false });
    document.addEventListener('keydown', onKeyDown);

    bindEndpointInput(endA, searchA, taA);
    bindEndpointInput(endB, searchB, taB);
    extinctTog.addEventListener('change', () => {
      extinctOnly = extinctTog.checked;
      requestRedraw(); saveState();
    });

    gearBtn.addEventListener('click', () => {
      const open = gearPanel.classList.toggle('is-open');
      gearPanel.setAttribute('aria-hidden', open ? 'false' : 'true');
    });
    gearClose.addEventListener('click', () => {
      gearPanel.classList.remove('is-open');
      gearPanel.setAttribute('aria-hidden', 'true');
    });
    gearReset.addEventListener('click', () => {
      Object.assign(tune, DEFAULTS);
      reflectSlidersFromTune();
      applyForces();
      requestRedraw();
      saveState();
    });

    requestAnimationFrame(tick);
  }

  function ingest(g) {
    graph = g;
    nodeIndex.clear();
    neighbors.clear();

    // Theme tables come from the server so colour edits stay in one
    // place (pluralism/__init__.py).
    FAMILY_ORDER  = [];
    FAMILY_COLORS = {};
    FAMILY_LABELS = {};
    const fams = (g.meta && g.meta.families) || [];
    for (const f of fams) {
      FAMILY_ORDER.push(f.slug);
      FAMILY_COLORS[f.slug] = f.color;
      FAMILY_LABELS[f.slug] = f.label;
      if (!kindEnabled.has(f.slug)) kindEnabled.set(f.slug, true);
    }

    // Sqrt-scale adherent counts → node radius so the visual conveys
    // influence (Roman Catholicism dwarfs everything; extinct sects sit
    // at the floor). Sqrt because the range spans 0 → 1.4B, and a linear
    // scale would shrink everything but Catholicism to a dot.
    const maxAdh = Math.max(1, ...graph.nodes.map(n => n.adherents || 0));
    const sqrtMax = Math.sqrt(maxAdh);
    const R_MIN = 4;
    const R_MAX = 28;
    const R_EXTINCT = 6; // small but still clickable

    const N = graph.nodes.length;
    for (let i = 0; i < N; i++) {
      const n = graph.nodes[i];
      const angle = Math.random() * Math.PI * 2;
      const r = Math.sqrt(Math.random()) * 200 + 30;
      n.x = Math.cos(angle) * r;
      n.y = Math.sin(angle) * r;
      n.vx = 0; n.vy = 0;
      n._dim = false;
      n._hidden = false;
      n._matchHit = false;
      n._searchText = (
        (n.id || '') + ' ' + (n.label || '') + ' ' + (n.name || '') +
        ' ' + (n.summary || '') + ' ' + (n.location || '') + ' ' +
        (n.founder || '') + ' ' + (n.founded != null ? n.founded : '') + ' ' +
        ((n.keyDoctrines || []).join(' '))
      ).toLowerCase();
      if (n.extinct) {
        n._radius = R_EXTINCT;
      } else {
        const adh = Math.max(0, n.adherents || 0);
        const t = Math.sqrt(adh) / sqrtMax; // 0..1
        n._radius = Math.max(R_MIN, R_MIN + t * (R_MAX - R_MIN));
      }
      const c = FAMILY_COLORS[n.kind] || '#888';
      n._rgb = hexToRgb(c);
      nodeIndex.set(n.id, n);
      neighbors.set(n.id, []);
    }
    for (const e of graph.edges) {
      const arr1 = neighbors.get(e.source);
      const arr2 = neighbors.get(e.target);
      if (arr1) arr1.push({ id: e.target, kind: e.kind, dir: 'out' });
      if (arr2) arr2.push({ id: e.source, kind: e.kind, dir: 'in' });
    }
    renderKindChips();
    selectedId = null;
    hoveredId = null;
    snapshotPositions = null;
    snapshotCam = null;
    renderSidePanel();
    updateMeta();
  }

  function hexToRgb(hex) {
    const h = (hex || '#888888').replace('#', '');
    const n = parseInt(h.length === 3
      ? h.split('').map(c => c + c).join('')
      : h, 16);
    return [(n >> 16) & 0xff, (n >> 8) & 0xff, n & 0xff];
  }

  // ── d3-force simulation ────────────────────────────────────────
  function buildSim(activeNodes, activeEdges) {
    if (sim) sim.stop();
    chargeForce = d3.forceManyBody().strength(tune.charge).distanceMax(700);
    linkForce = d3.forceLink(activeEdges)
      .id(d => d.id)
      .distance(d => tune.distance)
      .strength(d => tune.link);
    collideForce = d3.forceCollide().radius(d => d._radius + 3).iterations(2);

    sim = d3.forceSimulation(activeNodes)
      .force('charge', chargeForce)
      .force('link', linkForce)
      .force('center', d3.forceX().strength(tune.center))
      .force('centerY', d3.forceY().strength(tune.center))
      .force('collide', collideForce)
      .alpha(1)
      .alphaDecay(0.025)
      .velocityDecay(0.42)
      .on('tick', () => { needsRedraw = true; updateMeta(); })
      .on('end', () => { needsRedraw = true; updateMeta(); });
  }

  let _forceRefitT = null;
  function applyForces() {
    if (!sim) return;
    if (chargeForce) chargeForce.strength(tune.charge);
    if (linkForce) {
      linkForce.distance(tune.distance);
      linkForce.strength(d => tune.link);
    }
    sim.force('center', d3.forceX().strength(tune.center));
    sim.force('centerY', d3.forceY().strength(tune.center));
    sim.alpha(0.25).restart();
    if (_forceRefitT) clearTimeout(_forceRefitT);
    _forceRefitT = setTimeout(() => {
      if (searchActive()) fitToVisible(0.82); else fitToView(0.85);
    }, 350);
  }

  function runInitialLayout() {
    const nodes = graph.nodes.filter(n => kindEnabled.get(n.kind));
    const edges = graph.edges
      .filter(e => {
        const A = nodeIndex.get(e.source);
        const B = nodeIndex.get(e.target);
        return A && B && kindEnabled.get(A.kind) && kindEnabled.get(B.kind);
      })
      .map(e => ({ source: e.source, target: e.target, kind: e.kind }));
    buildSim(nodes, edges);
    sim.tick(220);
    sim.alpha(0).stop();
    fitToView(0.85);
    updateMeta();
    requestRedraw();
  }

  function runFocusedLayout() {
    const visibleSet = computeVisibleSet();
    if (!visibleSet) return runInitialLayout();
    const nodes = graph.nodes.filter(n =>
      kindEnabled.get(n.kind) && visibleSet.has(n.id));
    if (nodes.length === 0) return;
    const edges = graph.edges
      .filter(e => visibleSet.has(e.source) && visibleSet.has(e.target))
      .map(e => ({ source: e.source, target: e.target, kind: e.kind }));
    let cx = 0, cy = 0;
    for (const n of nodes) { cx += n.x; cy += n.y; }
    cx /= nodes.length; cy /= nodes.length;
    for (const n of nodes) {
      n.x = (n.x - cx) * 0.5;
      n.y = (n.y - cy) * 0.5;
      n.vx = 0; n.vy = 0;
    }
    buildSim(nodes, edges);
    sim.tick(180);
    sim.alpha(0).stop();
    // recomputeDim sets _hidden on out-of-focus nodes — must run before
    // fitToVisible or the bounding box includes stale positions.
    recomputeDim();
    fitToVisible(0.78);
    updateMeta();
    requestRedraw();
  }

  // ── Search resolution ──────────────────────────────────────────
  // A keyword that matches a family slug or label expands to every
  // member of that family, so "Catholic" → all Catholic nodes.
  function familyFromKeyword(t) {
    if (FAMILY_LABELS[t]) return t;
    for (const slug of FAMILY_ORDER) {
      if (FAMILY_LABELS[slug].toLowerCase() === t) return slug;
    }
    return null;
  }

  function resolveEndpoint(end) {
    if (end.id) return new Set([end.id]);
    const t = (end.text || '').trim().toLowerCase();
    if (!t) return null;
    const ids = new Set();
    const fam = familyFromKeyword(t);
    if (fam) {
      for (const n of graph.nodes) if (n.kind === fam) ids.add(n.id);
      return ids;
    }
    for (const n of graph.nodes) {
      if (n._searchText.indexOf(t) !== -1) ids.add(n.id);
    }
    return ids;
  }

  function computeVisibleSet() {
    const aSet = resolveEndpoint(endA);
    const bSet = resolveEndpoint(endB);
    if (!aSet && !bSet) return null;

    if (aSet && !bSet) {
      const visible = new Set(aSet);
      for (const id of aSet) {
        for (const l of (neighbors.get(id) || [])) visible.add(l.id);
      }
      return visible;
    }
    if (!aSet && bSet) {
      const visible = new Set(bSet);
      for (const id of bSet) {
        for (const l of (neighbors.get(id) || [])) visible.add(l.id);
      }
      return visible;
    }

    // PATH mode: BFS from each A toward any B.
    const MAX_HOPS = 8;
    const visible = new Set([...aSet, ...bSet]);
    for (const start of aSet) {
      if (bSet.has(start)) continue;
      const parent = new Map([[start, null]]);
      const queue = [start];
      let depth = 0;
      let found = null;
      while (queue.length && depth < MAX_HOPS) {
        const next = [];
        for (const cur of queue) {
          for (const link of (neighbors.get(cur) || [])) {
            if (parent.has(link.id)) continue;
            parent.set(link.id, cur);
            if (bSet.has(link.id)) { found = link.id; break; }
            next.push(link.id);
          }
          if (found) break;
        }
        if (found) break;
        queue.length = 0;
        for (const id of next) queue.push(id);
        depth++;
      }
      if (found) {
        let cur = found;
        while (cur != null) { visible.add(cur); cur = parent.get(cur); }
      }
    }
    return visible;
  }

  function recomputeDim() {
    const aSet = resolveEndpoint(endA);
    const bSet = resolveEndpoint(endB);
    const visible = (aSet || bSet) ? computeVisibleSet() : null;
    for (const n of graph.nodes) {
      n._matchHit = !!((aSet && aSet.has(n.id)) || (bSet && bSet.has(n.id)));
    }
    const hoverNeighbours = hoveredId
      ? new Set([hoveredId, ...((neighbors.get(hoveredId) || []).map(l => l.id))])
      : null;
    for (const n of graph.nodes) {
      let dim = false, hidden = false;
      if (!kindEnabled.get(n.kind)) hidden = true;
      if (visible && !visible.has(n.id)) hidden = true;
      if (hoverNeighbours && !hoverNeighbours.has(n.id)) dim = true;
      if (extinctOnly && !n.extinct) dim = true;
      n._hidden = hidden;
      n._dim = dim && !hidden;
    }
  }

  // ── Sliders / persistence ──────────────────────────────────────
  function initSliders() {
    sliders.node.addEventListener('input', () => {
      tune.node = parseFloat(sliders.node.value); requestRedraw(); saveState();
    });
    sliders.link_w.addEventListener('input', () => {
      tune.link_w = parseFloat(sliders.link_w.value); requestRedraw(); saveState();
    });
    sliders.label_zoom.addEventListener('input', () => {
      tune.label_zoom = parseFloat(sliders.label_zoom.value); requestRedraw(); saveState();
    });
    sliders.center.addEventListener('input', () => {
      tune.center = parseFloat(sliders.center.value); applyForces(); saveState();
    });
    sliders.charge.addEventListener('input', () => {
      tune.charge = parseFloat(sliders.charge.value); applyForces(); saveState();
    });
    sliders.link.addEventListener('input', () => {
      tune.link = parseFloat(sliders.link.value); applyForces(); saveState();
    });
    sliders.distance.addEventListener('input', () => {
      tune.distance = parseFloat(sliders.distance.value); applyForces(); saveState();
    });
  }
  function reflectSlidersFromTune() {
    sliders.node.value = tune.node;
    sliders.link_w.value = tune.link_w;
    sliders.label_zoom.value = tune.label_zoom;
    sliders.center.value = tune.center;
    sliders.charge.value = tune.charge;
    sliders.link.value = tune.link;
    sliders.distance.value = tune.distance;
  }
  function saveState() {
    try {
      localStorage.setItem(LS_KEY, JSON.stringify({
        endA, endB, extinctOnly,
        kindOff: FAMILY_ORDER.filter(k => !kindEnabled.get(k)),
        tune,
      }));
    } catch (_) {}
  }
  function loadState() {
    try {
      const raw = localStorage.getItem(LS_KEY);
      if (!raw) return;
      const s = JSON.parse(raw);
      if (s.endA && typeof s.endA === 'object') {
        endA.text = s.endA.text || ''; endA.id = s.endA.id || null;
      }
      if (s.endB && typeof s.endB === 'object') {
        endB.text = s.endB.text || ''; endB.id = s.endB.id || null;
      }
      if (typeof s.extinctOnly === 'boolean') extinctOnly = s.extinctOnly;
      if (Array.isArray(s.kindOff)) {
        for (const k of s.kindOff) kindEnabled.set(k, false);
      }
      if (s.tune && typeof s.tune === 'object') Object.assign(tune, s.tune);
    } catch (_) {}
  }
  function applyState() {
    extinctTog.checked = extinctOnly;
    if (endA.text) searchA.value = endA.text;
    if (endB.text) searchB.value = endB.text;
    if (searchActive()) _lastSearchActive = true;
    FAMILY_ORDER.forEach(slug => {
      const chip = kindChips.querySelector(`[data-kind="${slug}"]`);
      if (chip) chip.classList.toggle('is-off', !kindEnabled.get(slug));
    });
    reflectSlidersFromTune();
  }

  function renderKindChips() {
    const counts = (graph.meta && graph.meta.family_counts) || {};
    kindChips.innerHTML = '';
    FAMILY_ORDER.forEach(slug => {
      const chip = document.createElement('button');
      chip.type = 'button';
      chip.className = 'pg-kind-chip';
      chip.dataset.kind = slug;
      chip.innerHTML =
        '<span class="pg-kind-chip-dot" style="background:' + FAMILY_COLORS[slug] + ';"></span>' +
        '<span class="pg-kind-chip-label">' + escapeHtml(FAMILY_LABELS[slug]) + '</span>' +
        '<span class="pg-kind-chip-count">' + (counts[slug] || 0) + '</span>';
      chip.addEventListener('click', () => {
        kindEnabled.set(slug, !kindEnabled.get(slug));
        chip.classList.toggle('is-off', !kindEnabled.get(slug));
        if (searchActive()) runFocusedLayout(); else runInitialLayout();
        saveState();
      });
      kindChips.appendChild(chip);
    });
  }

  function updateMeta() {
    const m = graph.meta || {};
    const a = sim ? sim.alpha() : 0;
    meta.textContent =
      (m.node_count || 0) + ' traditions · ' +
      (m.edge_count || 0) + ' connections · ' +
      'zoom ' + scale.toFixed(2) + 'x' +
      (a > 0.01 ? ' · settling' : '');
  }

  function resize() {
    dpr = window.devicePixelRatio || 1;
    const rect = canvas.getBoundingClientRect();
    canvas.width = Math.floor(rect.width * dpr);
    canvas.height = Math.floor(rect.height * dpr);
  }

  // ── Camera ──────────────────────────────────────────────────────
  function worldToScreen(x, y) {
    const w = canvas.width / dpr;
    const h = canvas.height / dpr;
    return { x: (x - camX) * scale + w / 2, y: (y - camY) * scale + h / 2 };
  }
  function screenToWorld(sx, sy) {
    const w = canvas.width / dpr;
    const h = canvas.height / dpr;
    return { x: (sx - w / 2) / scale + camX, y: (sy - h / 2) / scale + camY };
  }
  function clampScale(s) { return Math.max(0.05, Math.min(8, s)); }
  function zoomAt(sx, sy, newScale) {
    const before = screenToWorld(sx, sy);
    scale = newScale;
    const after = screenToWorld(sx, sy);
    camX += before.x - after.x;
    camY += before.y - after.y;
    requestRedraw();
  }

  function fitToView(fillRatio) {
    fitNodes(graph.nodes.filter(n => kindEnabled.get(n.kind)), fillRatio);
  }
  function fitToVisible(fillRatio) {
    const set = graph.nodes.filter(n => kindEnabled.get(n.kind) && !n._hidden);
    if (set.length === 0) return;
    fitNodes(set, fillRatio);
  }
  function fitNodes(set, fillRatio) {
    const w = canvas.width / dpr;
    const h = canvas.height / dpr;
    let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
    for (const n of set) {
      if (n.x < x0) x0 = n.x; if (n.y < y0) y0 = n.y;
      if (n.x > x1) x1 = n.x; if (n.y > y1) y1 = n.y;
    }
    if (!Number.isFinite(x0)) return;
    const pad = 60;
    const bw = Math.max(80, (x1 - x0) + pad * 2);
    const bh = Math.max(80, (y1 - y0) + pad * 2);
    const sidebar = document.querySelector('.pg-sidebar');
    let leftInset = 0;
    if (sidebar && getComputedStyle(sidebar).position === 'absolute') {
      const r = sidebar.getBoundingClientRect();
      leftInset = r.right - canvas.getBoundingClientRect().left;
      if (leftInset < 0) leftInset = 0;
    }
    const usableW = Math.max(120, w - leftInset);
    scale = clampScale(Math.min(usableW * fillRatio / bw, h * fillRatio / bh));
    const shiftWorld = (leftInset / 2) / scale;
    camX = (x0 + x1) / 2 - shiftWorld;
    camY = (y0 + y1) / 2;
    requestRedraw();
  }

  function nodeAt(sx, sy) {
    const wp = screenToWorld(sx, sy);
    let best = null, bestD2 = Infinity;
    for (const n of graph.nodes) {
      if (!kindEnabled.get(n.kind)) continue;
      if (n._hidden) continue;
      const dx = n.x - wp.x;
      const dy = n.y - wp.y;
      const d2 = dx * dx + dy * dy;
      const r = (n._radius * tune.node + 4) / scale;
      if (d2 < r * r && d2 < bestD2) { best = n; bestD2 = d2; }
    }
    return best;
  }

  // ── Pointer / keyboard ─────────────────────────────────────────
  let dragMode = null;
  let dragNode = null;
  let dragStart = { x: 0, y: 0, camX: 0, camY: 0 };
  let pinch = null;
  const pointers = new Map();

  function onPointerDown(ev) {
    canvas.setPointerCapture(ev.pointerId);
    const rect = canvas.getBoundingClientRect();
    const sx = ev.clientX - rect.left;
    const sy = ev.clientY - rect.top;
    pointers.set(ev.pointerId, { x: sx, y: sy });
    if (pointers.size === 2) {
      const arr = Array.from(pointers.values());
      pinch = {
        startDist: Math.hypot(arr[1].x - arr[0].x, arr[1].y - arr[0].y),
        startScale: scale,
      };
      dragMode = null;
      return;
    }
    const node = nodeAt(sx, sy);
    if (node) {
      dragMode = 'node';
      dragNode = node;
      node.fx = node.x; node.fy = node.y;
      if (sim) sim.alphaTarget(0.3).restart();
    } else {
      dragMode = 'pan';
      canvas.classList.add('is-dragging');
      dragStart = { x: sx, y: sy, camX, camY };
    }
  }

  function onPointerMove(ev) {
    const rect = canvas.getBoundingClientRect();
    const sx = ev.clientX - rect.left;
    const sy = ev.clientY - rect.top;
    if (!pointers.has(ev.pointerId)) {
      const n = nodeAt(sx, sy);
      const newHover = n ? n.id : null;
      if (newHover !== hoveredId) { hoveredId = newHover; requestRedraw(); }
      canvas.style.cursor = n ? 'pointer' : (dragMode ? 'grabbing' : 'grab');
      return;
    }
    pointers.set(ev.pointerId, { x: sx, y: sy });
    if (pinch && pointers.size === 2) {
      const arr = Array.from(pointers.values());
      const dist = Math.hypot(arr[1].x - arr[0].x, arr[1].y - arr[0].y);
      const mid = { x: (arr[0].x + arr[1].x) / 2, y: (arr[0].y + arr[1].y) / 2 };
      zoomAt(mid.x, mid.y, clampScale(pinch.startScale * (dist / pinch.startDist)));
      return;
    }
    if (dragMode === 'node' && dragNode) {
      const wp = screenToWorld(sx, sy);
      dragNode.fx = wp.x; dragNode.fy = wp.y;
      requestRedraw();
    } else if (dragMode === 'pan') {
      camX = dragStart.camX - (sx - dragStart.x) / scale;
      camY = dragStart.camY - (sy - dragStart.y) / scale;
      requestRedraw();
    }
  }

  function onPointerUp(ev) {
    pointers.delete(ev.pointerId);
    if (pointers.size < 2) pinch = null;
    if (dragMode === 'node' && dragNode) {
      dragNode.fx = null; dragNode.fy = null;
      if (sim) sim.alphaTarget(0);
      selectNode(dragNode.id);
      dragNode = null;
    } else if (dragMode === 'pan') {
      const rect = canvas.getBoundingClientRect();
      const sx = ev.clientX - rect.left;
      const sy = ev.clientY - rect.top;
      if (Math.hypot(sx - dragStart.x, sy - dragStart.y) < 4) selectNode(null);
    }
    dragMode = null;
    canvas.classList.remove('is-dragging');
  }
  function onPointerLeave() {
    if (hoveredId) { hoveredId = null; requestRedraw(); }
  }

  function onWheel(ev) {
    ev.preventDefault();
    const rect = canvas.getBoundingClientRect();
    const sx = ev.clientX - rect.left;
    const sy = ev.clientY - rect.top;
    const isMouseWheel = ev.deltaMode === 1;
    const dy = isMouseWheel ? -ev.deltaY : ev.deltaY;
    const k = Math.exp(dy * 0.0018);
    zoomAt(sx, sy, clampScale(scale * k));
  }

  function onKeyDown(ev) {
    if (ev.target && (ev.target.tagName === 'INPUT' || ev.target.tagName === 'TEXTAREA')) return;
    const PAN = ev.shiftKey ? 120 : 40;
    let used = true;
    if (ev.key === 'ArrowLeft')       { camX -= PAN / scale; requestRedraw(); }
    else if (ev.key === 'ArrowRight') { camX += PAN / scale; requestRedraw(); }
    else if (ev.key === 'ArrowUp')    { camY -= PAN / scale; requestRedraw(); }
    else if (ev.key === 'ArrowDown')  { camY += PAN / scale; requestRedraw(); }
    else if (ev.key === '+' || ev.key === '=') zoomCenter(1.18);
    else if (ev.key === '-' || ev.key === '_') zoomCenter(1 / 1.18);
    else if (ev.key === 'Escape') {
      if (searchActive()) {
        endA = { text: '', id: null };
        endB = { text: '', id: null };
        searchA.value = ''; searchB.value = '';
        taA.hidden = true; taB.hidden = true;
        applySearchChange();
      } else {
        selectNode(null);
      }
    }
    else if (ev.key === 'f' || ev.key === 'F') { fitToView(0.85); }
    else used = false;
    if (used) ev.preventDefault();
  }
  function zoomCenter(factor) {
    const w = canvas.width / dpr;
    const h = canvas.height / dpr;
    zoomAt(w / 2, h / 2, clampScale(scale * factor));
  }

  // ── Search wiring ─────────────────────────────────────────────
  let _searchT = null;
  let _lastSearchActive = false;

  function searchActive() {
    return !!(endA.text || endA.id || endB.text || endB.id);
  }

  function applySearchChange() {
    const isActive = searchActive();
    requestRedraw();
    if (_searchT) clearTimeout(_searchT);
    _searchT = setTimeout(() => {
      if (isActive && !_lastSearchActive) {
        snapshotPositions = new Map();
        for (const n of graph.nodes) {
          snapshotPositions.set(n.id, { x: n.x, y: n.y });
        }
        snapshotCam = { x: camX, y: camY, scale };
        runFocusedLayout();
      } else if (isActive) {
        runFocusedLayout();
      } else if (!isActive && _lastSearchActive) {
        if (snapshotPositions) {
          for (const n of graph.nodes) {
            const p = snapshotPositions.get(n.id);
            if (p) { n.x = p.x; n.y = p.y; n.vx = 0; n.vy = 0; }
          }
          snapshotPositions = null;
        }
        if (snapshotCam) {
          camX = snapshotCam.x; camY = snapshotCam.y; scale = snapshotCam.scale;
          snapshotCam = null;
        }
        recomputeDim();
        requestRedraw();
      }
      _lastSearchActive = isActive;
      saveState();
    }, 280);
  }

  // ── Typeahead ─────────────────────────────────────────────────
  function rankedSuggestions(rawText, limit) {
    const term = (rawText || '').trim().toLowerCase();
    if (!term) return [];
    const fam = familyFromKeyword(term);
    const out = [];
    if (fam) {
      for (const n of graph.nodes) {
        if (n.kind === fam) out.push({ n, score: -(n.degree || 0) });
      }
      out.sort((a, b) => a.score - b.score);
      return out.slice(0, limit).map(x => x.n);
    }
    for (const n of graph.nodes) {
      const label = (n.label || '').toLowerCase();
      const idl = n.id.toLowerCase();
      let score = 0;
      if (label === term) score = 100;
      else if (label.startsWith(term)) score = 80;
      else if (label.indexOf(term) !== -1) score = 60;
      else if (idl.indexOf(term) !== -1) score = 50;
      else if ((n._searchText || '').indexOf(term) !== -1) score = 20;
      if (score === 0) continue;
      score += Math.min(15, (n.degree || 0) / 5);
      out.push({ n, score });
    }
    out.sort((a, b) => b.score - a.score);
    return out.slice(0, limit).map(x => x.n);
  }

  function renderTypeahead(panel, suggestions, activeIdx) {
    if (suggestions.length === 0) {
      panel.innerHTML = '<div class="pg-ta-empty">No matches</div>';
      panel.hidden = false;
      return;
    }
    let html = '';
    for (let i = 0; i < suggestions.length; i++) {
      const n = suggestions[i];
      const klass = 'pg-ta-row' + (i === activeIdx ? ' is-active' : '');
      html += '<div class="' + klass + '" role="option" data-id="' + escapeAttr(n.id) + '">' +
        '<span class="pg-ta-kind"><span class="pg-ta-kind-dot" style="background:' +
          FAMILY_COLORS[n.kind] + ';"></span>' + escapeHtml(FAMILY_LABELS[n.kind] || n.kind) + '</span>' +
        '<span class="pg-ta-name">' + escapeHtml(n.label || n.id) +
          (n.founded ? '<span class="pg-ta-year"> · ' + escapeHtml(String(n.founded)) + '</span>' : '') +
        '</span>' +
      '</div>';
    }
    panel.innerHTML = html;
    panel.hidden = false;
  }

  function bindEndpointInput(end, input, panel) {
    let activeIdx = -1;
    let suggestions = [];
    const refresh = () => {
      suggestions = rankedSuggestions(input.value, 14);
      activeIdx = suggestions.length ? 0 : -1;
      renderTypeahead(panel, suggestions, activeIdx);
    };
    const choose = (n) => {
      end.id = n.id;
      end.text = n.label || n.id;
      input.value = end.text;
      panel.hidden = true;
      applySearchChange();
    };
    input.addEventListener('input', () => {
      end.text = input.value;
      end.id = null;
      if (input.value.trim()) refresh(); else panel.hidden = true;
      applySearchChange();
    });
    input.addEventListener('focus', () => { if (input.value.trim()) refresh(); });
    input.addEventListener('blur', () => {
      setTimeout(() => { panel.hidden = true; }, 150);
    });
    input.addEventListener('keydown', (ev) => {
      if (panel.hidden || suggestions.length === 0) return;
      if (ev.key === 'ArrowDown') {
        activeIdx = (activeIdx + 1) % suggestions.length;
        renderTypeahead(panel, suggestions, activeIdx);
        ev.preventDefault();
      } else if (ev.key === 'ArrowUp') {
        activeIdx = (activeIdx - 1 + suggestions.length) % suggestions.length;
        renderTypeahead(panel, suggestions, activeIdx);
        ev.preventDefault();
      } else if (ev.key === 'Enter' && activeIdx >= 0) {
        choose(suggestions[activeIdx]);
        ev.preventDefault();
      } else if (ev.key === 'Escape') {
        panel.hidden = true;
      }
    });
    panel.addEventListener('mousedown', (ev) => {
      const row = ev.target.closest('.pg-ta-row');
      if (!row) return;
      ev.preventDefault();
      const n = nodeIndex.get(row.getAttribute('data-id'));
      if (n) choose(n);
    });
  }

  // ── Selection + side panel ─────────────────────────────────────
  function selectNode(id) {
    selectedId = id;
    sidePanel.classList.toggle('is-open', !!id);
    renderSidePanel();
    requestRedraw();
  }

  function fmtAdherents(v) {
    if (v == null) return null;
    const n = Number(v);
    if (!isFinite(n) || n <= 0) return null;
    if (n >= 1e9) return (n / 1e9).toFixed(1).replace(/\.0$/, '') + 'B';
    if (n >= 1e6) return (n / 1e6).toFixed(1).replace(/\.0$/, '') + 'M';
    if (n >= 1e3) return (n / 1e3).toFixed(0) + 'K';
    return String(n);
  }

  function fmtFounded(v) {
    if (v == null || v === '') return null;
    const n = Number(v);
    if (!isFinite(n)) return String(v);
    return n + ' CE';
  }

  function renderSidePanel() {
    if (!selectedId) { sidePanel.innerHTML = ''; return; }
    const n = nodeIndex.get(selectedId);
    if (!n) return;
    const links = (neighbors.get(selectedId) || []).slice().sort((a, b) => {
      if (a.dir !== b.dir) return a.dir === 'in' ? -1 : 1;
      const an = nodeIndex.get(a.id), bn = nodeIndex.get(b.id);
      return ((an && an.label) || '') < ((bn && bn.label) || '') ? -1 : 1;
    });

    const founded = fmtFounded(n.founded);
    const adher = fmtAdherents(n.adherents);
    const metaBits = [];
    if (founded) metaBits.push(founded);
    if (n.location) metaBits.push(n.location);
    if (adher) metaBits.push(adher + ' adherents');
    if (n.extinct) metaBits.push('extinct');

    let html =
      '<button class="pg-side-close" type="button" aria-label="Close">&times;</button>' +
      '<div class="pg-side-head">' +
        '<span class="pg-side-kind"><span class="pg-side-kind-dot" style="background:' +
          FAMILY_COLORS[n.kind] + ';"></span>' + escapeHtml(FAMILY_LABELS[n.kind] || n.kind) + '</span>' +
      '</div>' +
      '<div class="pg-side-name">' + escapeHtml(n.name || n.label || n.id) + '</div>';
    if (n.founder) html += '<div class="pg-side-founder">Founded by ' + escapeHtml(n.founder) + '</div>';
    if (metaBits.length) html += '<div class="pg-side-meta">' + escapeHtml(metaBits.join(' · ')) + '</div>';
    if (n.summary) html += '<p class="pg-side-desc">' + escapeHtml(n.summary) + '</p>';

    if (n.keyDoctrines && n.keyDoctrines.length) {
      html += '<div class="pg-side-section-title">Key Doctrines</div>';
      html += '<ul class="pg-side-doctrines">';
      for (const d of n.keyDoctrines) {
        html += '<li>' + escapeHtml(d) + '</li>';
      }
      html += '</ul>';
    }

    if (n.scriptureStance) {
      html += '<div class="pg-side-section-title">Scripture</div>';
      html += '<p class="pg-side-prose">' + escapeHtml(n.scriptureStance) + '</p>';
    }
    if (n.salvationView) {
      html += '<div class="pg-side-section-title">Salvation</div>';
      html += '<p class="pg-side-prose">' + escapeHtml(n.salvationView) + '</p>';
    }

    if (links.length) {
      html += '<div class="pg-side-section-title">Connections (' + links.length + ')</div>';
      html += '<ul class="pg-side-links">';
      for (const link of links) {
        const tgt = nodeIndex.get(link.id);
        if (!tgt) continue;
        const arrow = link.dir === 'out' ? '↳' : '↰';
        const role = link.dir === 'out' ? 'descendant' : 'parent';
        html +=
          '<li class="pg-side-link-row" data-target="' + escapeAttr(link.id) + '">' +
            '<span class="pg-side-link-edge">' + arrow + ' ' + role + '</span>' +
            '<span class="pg-side-link-target"><span class="pg-side-link-kind" style="background:' +
              FAMILY_COLORS[tgt.kind] + ';"></span>' +
              escapeHtml(tgt.label || tgt.id) + '</span>' +
          '</li>';
      }
      html += '</ul>';
    }
    sidePanel.innerHTML = html;
    const closeBtn = sidePanel.querySelector('.pg-side-close');
    if (closeBtn) closeBtn.addEventListener('click', () => selectNode(null));
    sidePanel.querySelectorAll('.pg-side-link-row').forEach(row => {
      row.addEventListener('click', () => {
        const tid = row.getAttribute('data-target');
        if (tid) {
          const tn = nodeIndex.get(tid);
          if (tn) {
            camX = tn.x; camY = tn.y;
            scale = clampScale(Math.max(scale, 1.4));
          }
          selectNode(tid);
        }
      });
    });
  }

  function escapeHtml(s) {
    return String(s == null ? '' : s)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
  }
  function escapeAttr(s) { return escapeHtml(s); }

  // ── Render ─────────────────────────────────────────────────────
  function tick() {
    if (needsRedraw) { draw(); needsRedraw = false; }
    requestAnimationFrame(tick);
  }

  function draw() {
    recomputeDim();
    const w = canvas.width / dpr;
    const h = canvas.height / dpr;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    // Match the page background (--pg-bg) so the canvas blends seamlessly.
    ctx.fillStyle = '#0d0d0d';
    ctx.fillRect(0, 0, w, h);
    drawEdges(w, h);
    drawNodes(w, h);
  }

  function drawEdges(w, h) {
    const sel = selectedId ? nodeIndex.get(selectedId) : null;
    ctx.lineCap = 'round';
    for (const e of graph.edges) {
      const A = nodeIndex.get(e.source);
      const B = nodeIndex.get(e.target);
      if (!A || !B) continue;
      if (!kindEnabled.get(A.kind) || !kindEnabled.get(B.kind)) continue;
      if (A._hidden || B._hidden) continue;
      const sa = worldToScreen(A.x, A.y);
      const sb = worldToScreen(B.x, B.y);
      if ((sa.x < 0 && sb.x < 0) || (sa.x > w && sb.x > w) ||
          (sa.y < 0 && sb.y < 0) || (sa.y > h && sb.y > h)) continue;
      const isSel = sel && (e.source === sel.id || e.target === sel.id);
      let alpha, stroke, width;
      if (isSel)                 { alpha = 0.95; stroke = '#c9b458'; width = 1.6; }
      else if (sel)              { alpha = 0.06; stroke = '#5a5040'; width = 0.5; }
      else if (A._dim || B._dim) { alpha = 0.05; stroke = '#5a5040'; width = 0.5; }
      else                       { alpha = 0.32; stroke = '#7c6f54'; width = tune.link_w; }
      ctx.globalAlpha = alpha;
      ctx.strokeStyle = stroke;
      ctx.lineWidth = width;
      ctx.beginPath();
      ctx.moveTo(sa.x, sa.y);
      ctx.lineTo(sb.x, sb.y);
      ctx.stroke();
    }
    ctx.globalAlpha = 1;
  }

  function drawNodes(w, h) {
    const sel = selectedId ? nodeIndex.get(selectedId) : null;
    const selectedNeighbors = sel
      ? new Set((neighbors.get(sel.id) || []).map(l => l.id))
      : null;
    const hasSearch = searchActive();
    const sizeMult = tune.node;

    const dim = [], vivid = [];
    for (const n of graph.nodes) {
      if (!kindEnabled.get(n.kind)) continue;
      if (n._hidden) continue;
      if (n._dim && !(sel && n.id === sel.id)) dim.push(n);
      else vivid.push(n);
    }
    function paint(list, isDim) {
      for (const n of list) {
        const s = worldToScreen(n.x, n.y);
        if (s.x < -30 || s.y < -30 || s.x > w + 30 || s.y > h + 30) continue;
        const r = n._radius * sizeMult * Math.max(0.6, Math.min(1.6, scale));
        let nodeAlpha = 1, stroke = 'rgba(212,197,160,0.30)', strokeW = 0.8;
        if (sel && n.id === sel.id) { stroke = '#c9b458'; strokeW = 2.4; }
        else if (sel && selectedNeighbors && selectedNeighbors.has(n.id)) { stroke = '#c9b458'; strokeW = 1.6; }
        else if (sel) nodeAlpha = 0.28;
        else if (hasSearch && n._matchHit) { stroke = '#c9b458'; strokeW = 1.6; }
        if (isDim) nodeAlpha = 0.18;
        const [r8, g8, b8] = n._rgb;
        ctx.globalAlpha = nodeAlpha;
        ctx.fillStyle = `rgb(${r8},${g8},${b8})`;
        ctx.beginPath();
        ctx.arc(s.x, s.y, r, 0, Math.PI * 2);
        ctx.fill();
        ctx.lineWidth = strokeW;
        ctx.strokeStyle = stroke;
        ctx.stroke();
        // Thin red outer ring marks extinct traditions — sits just
        // outside the dot so it reads as a halo, not a fat border.
        if (n.extinct) {
          ctx.globalAlpha = Math.min(1, nodeAlpha + 0.1);
          ctx.lineWidth = 1.2;
          ctx.strokeStyle = '#d04a3f';
          ctx.beginPath();
          ctx.arc(s.x, s.y, r + 2.2, 0, Math.PI * 2);
          ctx.stroke();
        }
      }
      ctx.globalAlpha = 1;
    }
    paint(dim, true);
    paint(vivid, false);

    // Labels run on every frame — the priority + MAX_LABELS cap below
    // keeps the global view calm, while focus + hover surface specifics.
    {
      ctx.font = '600 12px "Source Serif 4", Georgia, serif';
      ctx.textBaseline = 'middle';
      ctx.lineWidth = 3;

      const candidates = [];
      for (const n of graph.nodes) {
        if (!kindEnabled.get(n.kind)) continue;
        if (n._hidden) continue;
        const s = worldToScreen(n.x, n.y);
        if (s.x < -100 || s.y < -100 || s.x > w + 100 || s.y > h + 100) continue;
        // Priority by adherent count (which already drives node size),
        // so the visually biggest traditions get labeled first. +1 so
        // zero-adherent nodes still rank above unset entries.
        let priority = (n.adherents || 0) + 1;
        if (sel && n.id === sel.id)                                       priority = 1e15;
        else if (hoveredId === n.id)                                      priority = 1e14;
        else if (n._matchHit && hasSearch)                                priority += 1e12;
        else if (sel && selectedNeighbors && selectedNeighbors.has(n.id)) priority += 1e11;
        candidates.push({ n, s, priority });
      }
      candidates.sort((a, b) => b.priority - a.priority);

      // Cap by zoom + mode. Hover/select/match always survive because
      // their priorities (1e11+) sort them to the top, well within any
      // cap. Global view at low zoom shows just the heaviest hubs.
      const MAX_LABELS = hasSearch
        ? (scale < 0.6 ? 22 : scale < 1.0 ? 45 : scale < 1.6 ? 90 : 250)
        : (scale < 0.6 ? 10 : scale < 1.0 ? 22 : scale < 1.6 ? 45 : scale < 2.4 ? 90 : 200);
      if (candidates.length > MAX_LABELS) candidates.length = MAX_LABELS;

      const placed = [];
      const HALF = 8;
      const PAD  = 5;
      for (const c of candidates) {
        const n = c.n;
        const s = c.s;
        const label = (n.label || n.id || '').slice(0, 38);
        const tw = ctx.measureText(label).width;
        const dotR = n._radius * sizeMult;
        let tx = s.x + dotR + 5;
        const ty = s.y;
        let bx0 = tx - PAD;
        let bx1 = tx + tw + PAD;
        const by0 = ty - HALF - PAD;
        const by1 = ty + HALF + PAD;
        let collides = false;
        for (let i = 0; i < placed.length; i++) {
          const p = placed[i];
          if (bx0 < p.x1 && bx1 > p.x0 && by0 < p.y1 && by1 > p.y0) {
            collides = true; break;
          }
        }
        if (collides) {
          tx = s.x - dotR - 5 - tw;
          bx0 = tx - PAD; bx1 = tx + tw + PAD;
          collides = false;
          for (let i = 0; i < placed.length; i++) {
            const p = placed[i];
            if (bx0 < p.x1 && bx1 > p.x0 && by0 < p.y1 && by1 > p.y0) {
              collides = true; break;
            }
          }
        }
        if (collides) continue;
        placed.push({ x0: bx0, y0: by0, x1: bx1, y1: by1 });
        ctx.strokeStyle = 'rgba(13,13,13,0.9)';
        ctx.strokeText(label, tx, ty);
        ctx.fillStyle = '#e8dcb6';
        ctx.fillText(label, tx, ty);
      }
    }
  }
})();
