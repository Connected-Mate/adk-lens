// The whiteboard: draws a topology, pans, zooms and plays a run frame.
import { h, s, clear, reducedMotion, put } from './dom.js';
import { icon } from './icons.js';
import { layout, freePath, MODEL, MEMORY } from './layout.js';
import { USER } from './store.js';
import { t, tp } from './i18n.js';

const GROUPS = new Set(['sequential', 'parallel', 'loop', 'workflow']);
const EDGE_LABEL = { ask: 'edge.ask', delegate: 'edge.delegate', then: 'edge.then', again: 'edge.again', uses_agent: 'edge.uses_agent', wraps: 'edge.wraps' };
// Room kept free around the map: the tools on the left, and at the bottom the caption and the player,
// which must never sit on the thing they explain.
const PAD = { top: 84, right: 40, bottom: 216, left: 84 };
const PAD_NARROW = { top: 70, right: 16, bottom: 190, left: 16 };
const MAX_ZOOM = 2.4;

export function createMap(stage, opts) {
  const world = h('div', { class: 'world' });
  const edgeSvg = s('svg', { class: 'edges', 'aria-hidden': 'true' });
  const nodeLayer = h('div', { class: 'nodes' });
  const labelLayer = h('div', { class: 'edge-labels', 'aria-hidden': 'true' });
  const notesSvg = s('svg', { class: 'notes-svg' });
  const notesHtml = h('div', { class: 'notes-html' });
  const travelSvg = s('svg', { class: 'travel', 'aria-hidden': 'true' });
  put(world, edgeSvg, labelLayer, nodeLayer, notesSvg, travelSvg, notesHtml);
  put(stage, world);

  const view = { x: 0, y: 0, k: 1 };
  let lay = { boxes: new Map(), edges: [], width: 0, height: 0 };
  let topo = null;
  const nodeEls = new Map();
  const edgeEls = new Map();
  const baseEls = new Map();
  let userFitted = false;
  let travelRaf = 0;
  let lastFrameKey = '';
  // The token that carries the request: one element for the whole request, moved with transform.
  const token = s('g', { class: 'token is-off' }, s('circle', { r: 15, class: 'dot-halo' }), s('circle', { r: 8, class: 'dot' }));
  let tokenAt = null; // where it is, in map coordinates
  let tokenOn = false;
  let ghost = null; // the dotted path of a journey that has no drawn connector
  let activeId = null;
  const viewListeners = [];

  function applyView() {
    world.style.transform = `translate(${view.x}px, ${view.y}px) scale(${view.k})`;
    let gap = 26 * view.k;
    while (gap < 14) gap *= 2;
    stage.style.backgroundSize = `${gap}px ${gap}px`;
    stage.style.backgroundPosition = `${view.x}px ${view.y}px`;
    for (const fn of viewListeners) fn(view);
  }

  // ----- camera -----
  // Every camera move is one glide of the view itself (position and scale together, the dotted
  // background with it). It starts from where the view is, so a new move can replace one under way.
  let cam = 0;
  function stopCam() {
    cancelAnimationFrame(cam);
    cam = 0;
  }
  function glide(to, ms = 480) {
    stopCam();
    if (reducedMotion() || ms <= 0 || (Math.abs(to.x - view.x) < 0.5 && Math.abs(to.y - view.y) < 0.5 && Math.abs(to.k - view.k) < 0.001)) {
      view.x = to.x; view.y = to.y; view.k = to.k;
      applyView();
      return;
    }
    const r = stage.getBoundingClientRect();
    const cx = r.width / 2, cy = r.height / 2;
    const k0 = view.k;
    // The point of the map under the centre of the screen moves in a straight line while the scale changes.
    const c0 = { x: (cx - view.x) / view.k, y: (cy - view.y) / view.k };
    const c1 = { x: (cx - to.x) / to.k, y: (cy - to.y) / to.k };
    const t0 = performance.now();
    const ease = (x) => (x < 0.5 ? 4 * x * x * x : 1 - Math.pow(-2 * x + 2, 3) / 2);
    const tick = (now) => {
      const p = Math.min(1, (now - t0) / ms);
      const e = ease(p);
      view.k = k0 * Math.pow(to.k / k0, e);
      view.x = cx - (c0.x + (c1.x - c0.x) * e) * view.k;
      view.y = cy - (c0.y + (c1.y - c0.y) * e) * view.k;
      if (p >= 1) { view.x = to.x; view.y = to.y; view.k = to.k; }
      applyView();
      cam = p < 1 ? requestAnimationFrame(tick) : 0;
    };
    cam = requestAnimationFrame(tick);
  }

  function safeArea(r) {
    const narrow = r.width < 720;
    const inset = !narrow && opts.inset ? opts.inset() : 0;
    const pad = narrow ? PAD_NARROW : { ...PAD, right: PAD.right + inset };
    return { narrow, pad, w: r.width - pad.left - pad.right, h: r.height - pad.top - pad.bottom };
  }

  function fit(animated = true) {
    const r = stage.getBoundingClientRect();
    if (!r.width || !lay.width) return;
    const { narrow, pad, w, h } = safeArea(r);
    // Always show the whole map, phones included: seeing every agent matters more than the size of the letters
    // (Focus, pinch or + to read closer). Only a really huge map is left to scroll sideways.
    const k = Math.max(narrow ? 0.2 : 0.08, Math.min(w / lay.width, h / Math.max(lay.height, 1), 1.1));
    const free = w - lay.width * k;
    glide({ k, x: free >= 0 ? pad.left + free / 2 : pad.left, y: pad.top + (h - lay.height * k) / 2 }, animated ? 480 : 0);
  }

  // Frame a few blocks (the one at work and the one it talks to) so that their names read comfortably.
  function focusOn(ids, animated = true) {
    const r = stage.getBoundingClientRect();
    const bs = ids.map((id) => lay.boxes.get(id)).filter(Boolean);
    if (!r.width || !bs.length) return false;
    const { narrow, pad, w, h } = safeArea(r);
    const box = (list) => {
      const x1 = Math.min(...list.map((b) => b.x)), y1 = Math.min(...list.map((b) => b.y));
      return { x: x1, y: y1, w: Math.max(...list.map((b) => b.x + b.w)) - x1, h: Math.max(...list.map((b) => b.y + b.h)) - y1 };
    };
    const lo = narrow ? 0.55 : 0.85, hi = narrow ? 1 : 1.2;
    let bb = box(bs);
    const scale = (b) => Math.min(w / (b.w + 72), h / (b.h + 56));
    // Too far apart to read both: stay on the one at work.
    if (scale(bb) < lo && bs.length > 1) bb = box([bs[0]]);
    const k = Math.max(lo, Math.min(hi, scale(bb)));
    // A block bigger than the screen (a wide frame) is shown from its start.
    const x = bb.w * k > w ? pad.left + 20 - bb.x * k : pad.left + (w - bb.w * k) / 2 - bb.x * k;
    const y = bb.h * k > h ? pad.top + 12 - bb.y * k : pad.top + (h - bb.h * k) / 2 - bb.y * k;
    userFitted = true;
    // A long way to go takes a little longer, so the eye can follow.
    const far = Math.hypot(x - view.x, y - view.y);
    glide({ k, x, y }, animated ? Math.max(520, Math.min(1000, 440 + far * 0.3)) : 0);
    return true;
  }

  function zoomAt(factor, cx, cy, ms = 0) {
    const r = stage.getBoundingClientRect();
    const px = cx === undefined ? r.width / 2 : cx - r.left;
    const py = cy === undefined ? r.height / 2 : cy - r.top;
    const k = Math.min(MAX_ZOOM, Math.max(0.06, view.k * factor));
    glide({ k, x: px - ((px - view.x) / view.k) * k, y: py - ((py - view.y) / view.k) * k }, ms);
  }

  function toWorld(clientX, clientY) {
    const r = stage.getBoundingClientRect();
    return { x: (clientX - r.left - view.x) / view.k, y: (clientY - r.top - view.y) / view.k };
  }

  function centerWorld() {
    const r = stage.getBoundingClientRect();
    return toWorld(r.left + r.width / 2, r.top + r.height / 2);
  }

  function ensureVisible(id) {
    const b = lay.boxes.get(id);
    if (!b) return;
    const r = stage.getBoundingClientRect();
    const x1 = b.x * view.k + view.x, y1 = b.y * view.k + view.y;
    const x2 = x1 + b.w * view.k, y2 = y1 + b.h * view.k;
    let dx = 0, dy = 0;
    // Inside the margins of fit(), so a map that fits is never nudged around while it plays.
    const { pad } = safeArea(r);
    const m = { left: pad.left - 6, right: pad.right - 6, top: pad.top - 8, bottom: pad.bottom - 10 };
    if (x1 < m.left) dx = m.left - x1; else if (x2 > r.width - m.right) dx = r.width - m.right - x2;
    if (y1 < m.top) dy = m.top - y1; else if (y2 > r.height - m.bottom) dy = r.height - m.bottom - y2;
    if (!dx && !dy) return;
    glide({ k: view.k, x: view.x + dx, y: view.y + dy }, 420);
  }

  // ----- drawing -----
  function kindLabel(kind) {
    const key = `kind.${kind}`;
    const txt = t(key);
    return txt === key ? t('kind.custom') : txt;
  }

  function setTopology(next, o = {}) {
    topo = next;
    const diff = o.diff || null;
    lay = layout(topo);
    cancelAnimationFrame(travelRaf);
    travelRaf = 0;
    clear(edgeSvg); clear(nodeLayer); clear(labelLayer); clear(travelSvg);
    nodeEls.clear(); edgeEls.clear();
    lastFrameKey = '';
    ghost = null;
    tokenAt = null;
    tokenOn = false;
    token.classList.add('is-off');
    put(travelSvg, token);
    const W = lay.width, H = lay.height;
    for (const svg of [edgeSvg, notesSvg, travelSvg]) {
      svg.setAttribute('width', W); svg.setAttribute('height', H);
      svg.setAttribute('viewBox', `0 0 ${W} ${H}`);
    }
    world.style.width = `${W}px`; world.style.height = `${H}px`;
    world.classList.toggle('is-diff', !!diff);
    world.classList.toggle('is-big', topo.nodes.length > 60);

    const byId = new Map(topo.nodes.map((n) => [n.id, n]));
    const place = (el, b) => {
      el.style.left = `${b.x}px`; el.style.top = `${b.y}px`;
      el.style.width = `${b.w}px`; el.style.height = `${b.h}px`;
    };

    // The person asking.
    const ub = lay.boxes.get(USER);
    const userEl = h('button', { class: 'node k-user', type: 'button', dataset: { id: USER }, 'aria-label': t('node.user.aria') },
      h('span', { class: 'node-ico' }, icon('user', 22)),
      h('span', { class: 'node-txt' }, h('span', { class: 'node-name', text: t('node.user') }), h('span', { class: 'node-sub', text: t('node.user.sub') })));
    place(userEl, ub);
    put(nodeLayer, userEl);
    nodeEls.set(USER, userEl);

    // Frames first so they sit behind their members.
    const sorted = [...lay.boxes.values()].filter((b) => b.id !== USER).sort((a, b) => (a.type === 'group' ? 0 : 1) - (b.type === 'group' ? 0 : 1) || b.w * b.h - a.w * a.h);
    let i = 0;
    for (const b of sorted) {
      const n = byId.get(b.id);
      if (!n) continue;
      const status = diff ? diff.nodes.get(n.id) : null;
      let el;
      if (b.type === 'group') {
        el = h('div', { class: `frame k-${n.kind}`, dataset: { id: n.id } },
          h('button', { class: 'frame-head', type: 'button', dataset: { id: n.id }, 'aria-label': `${n.name}, ${kindLabel(n.kind)}` },
            icon(n.kind, 16), h('span', { class: 'frame-name', text: n.name }), h('span', { class: 'frame-kind', text: kindLabel(n.kind) })));
      } else {
        const isTool = b.type === 'tool';
        const sub = isTool ? null : h('span', { class: 'node-sub', text: kindLabel(n.kind) });
        el = h('button', {
          class: `node k-${GROUPS.has(n.kind) ? 'custom' : n.kind}${isTool ? ' is-tool' : ''}${n.dynamic ? ' is-dynamic' : ''}`, type: 'button', dataset: { id: n.id },
          'aria-label': `${n.name}, ${kindLabel(n.kind)}`,
        },
        h('span', { class: 'node-ico' }, icon(isTool ? n.kind : (n.kind in { llm: 1, remote: 1, step: 1 } ? n.kind : GROUPS.has(n.kind) ? n.kind : 'custom'), isTool ? 16 : 20)),
        h('span', { class: 'node-txt' }, h('span', { class: 'node-name', text: n.name }), sub));
        if (n.guards && n.guards.length) {
          // Protected: a small shield on its corner.
          const what = `${tp('guard.mark', n.guards.length)}: ${n.guards.map((g) => g.name).join(', ')}`;
          el.setAttribute('aria-label', `${n.name}, ${kindLabel(n.kind)}, ${what}`);
          put(el, h('span', { class: 'guard-tag', title: what }, icon('shield', 14)));
        }
      }
      if (status) {
        el.classList.add(`d-${status}`);
        (b.type === 'group' ? el.firstChild : el).append(h('span', { class: 'diff-tag', text: t(`diff.${status}`) }));
      }
      el.style.setProperty('--i', String(Math.min(i++, 30)));
      place(el, b);
      put(nodeLayer, el);
      nodeEls.set(n.id, el);
    }

    // What the app stands on.
    baseEls.clear();
    for (const b of lay.bases || []) {
      if (b.kind === 'guards') b.text = b.n ? t('base.guards.sub', b) : t('base.guards.none', b);
      const el = h('div', { class: `base k-${b.kind}${b.kind === 'guards' && !b.n ? ' is-none' : ''}`, role: 'img', 'aria-label': t(`base.${b.kind}.aria`, { text: b.text }), title: b.text, dataset: { id: b.id } },
        h('span', { class: 'base-ico' }, icon(b.kind === 'model' ? 'chip' : b.kind === 'guards' ? 'shield' : 'memory', 17)),
        h('span', { class: 'node-txt' }, h('span', { class: 'base-name', text: t(`base.${b.kind}`) }), h('span', { class: 'base-sub', text: b.text })));
      place(el, lay.boxes.get(b.id));
      put(nodeLayer, el);
      baseEls.set(b.id, el);
    }

    for (const e of lay.edges) {
      const status = diff ? diff.edges.get(e.key) : null;
      const g = s('g', { class: `edge k-${e.kind}${status ? ` d-${status}` : ''}` });
      const path = s('path', { d: e.d, class: 'edge-line' });
      put(g, path);
      put(edgeSvg, g);
      if (e.kind !== 'uses_tool') {
        const len = path.getTotalLength();
        if (len > 12) {
          const p2 = path.getPointAtLength(len), p1 = path.getPointAtLength(len - 6);
          const ang = (Math.atan2(p2.y - p1.y, p2.x - p1.x) * 180) / Math.PI;
          put(g, s('path', { class: 'edge-head', d: 'M-8 -4.500 L0 0 L-8 4.500 Z', transform: `translate(${p2.x} ${p2.y}) rotate(${ang})` }));
        }
      }
      const labelKey = e.label ? null : EDGE_LABEL[e.kind];
      let label = null;
      if (e.label || labelKey) {
        label = h('span', { class: `edge-label k-${e.kind}`, text: e.label || t(labelKey) });
        label.style.left = `${e.lx}px`; label.style.top = `${e.ly}px`;
        put(labelLayer, label);
      }
      edgeEls.set(e.key, { g, path, label, e });
    }
    if (o.refit) userFitted = false; // a new map (other app, other version): show all of it again
    if (!userFitted) fit(false);
    else applyView();
  }

  function findEdge(from, to) {
    const f = edgeEls.get(`${from}>${to}`);
    if (f) return { ...f, reverse: false };
    const r = edgeEls.get(`${to}>${from}`);
    if (r) return { ...r, reverse: true };
    return null;
  }

  function setFrame(frame, o = {}) {
    const hasRun = !!frame.step;
    activeId = hasRun ? frame.active : null;
    world.classList.toggle('has-run', hasRun);
    for (const [id, el] of nodeEls) {
      const active = frame.active === id;
      el.classList.toggle('is-visited', frame.visited.has(id));
      el.classList.toggle('is-active', active);
      el.classList.toggle('is-thinking', active && frame.kind === 'think');
      el.classList.toggle('is-guarding', active && (frame.kind === 'guard' || frame.kind === 'blocked'));
      const err = frame.errors.get(id);
      el.classList.toggle('is-error', err !== undefined);
      let tag = el.querySelector(':scope > .err-tag');
      if (err !== undefined && !tag) {
        tag = h('span', { class: 'err-tag' }, icon('warn', 13), h('span', { text: t('node.failed') }));
        put(el, tag);
      } else if (err === undefined && tag) tag.remove();
      if (err !== undefined) el.title = err; else el.removeAttribute('title');
      // A tool that came back saying no (refused, an error in its result): marked, but not a failure of the request.
      const warn = err === undefined ? frame.warns.get(id) : undefined;
      el.classList.toggle('is-warn', warn !== undefined);
      let wtag = el.querySelector(':scope > .warn-tag');
      if (warn !== undefined && !wtag) put(el, h('span', { class: 'warn-tag', title: warn }, icon('warn', 12), h('span', { text: t('node.problem') })));
      else if (warn === undefined && wtag) wtag.remove();
    }
    const model = baseEls.get(MODEL), memory = baseEls.get(MEMORY);
    if (model) model.classList.toggle('is-busy', hasRun && frame.kind === 'think');
    if (memory) memory.classList.toggle('is-on', hasRun && frame.memory);
    for (const [key, { g, label }] of edgeEls) {
      const [a, b] = key.split('>');
      const visited = frame.edges.has(key) || frame.edges.has(`${b}>${a}`);
      const active = !!frame.travel && ((frame.travel.from === a && frame.travel.to === b) || (frame.travel.from === b && frame.travel.to === a));
      g.classList.toggle('is-visited', visited);
      g.classList.toggle('is-active', active);
      g.classList.toggle('is-back', active && frame.travel.from === b); // the dashes run the way the request goes
      if (label) label.classList.toggle('is-visited', visited);
      if (label) label.classList.toggle('is-active', active);
    }
    const key = frame.step ? frame.step.id : '';
    const changed = key !== lastFrameKey;
    lastFrameKey = key;
    if (!hasRun) { stopTravel(); hideToken(); return; }
    if (frame.active && nodeEls.has(frame.active) && changed) {
      const el = nodeEls.get(frame.active);
      if (frame.kind === 'tool' || frame.kind === 'tool_result' || frame.kind === 'answer') {
        el.classList.remove('flash');
        void el.offsetWidth;
        el.classList.add('flash');
      }
      if (o.focus) focusOn([frame.active, frame.travel && (frame.travel.from === frame.active ? frame.travel.to : frame.travel.from)].filter(Boolean));
      else if (o.follow !== false) ensureVisible(frame.active);
    }
    if (changed && memory && frame.kind === 'memory' && !reducedMotion()) {
      memory.classList.remove('flash');
      void memory.offsetWidth;
      memory.classList.add('flash');
    }
    // The same step drawn again (a live request refreshes at every event): the journey under way goes on.
    if (!changed) return;
    stopTravel();
    if (frame.travel) runTravel(frame.travel, frame.kind, changed && o.animate !== false, o.duration || 700);
    else { dropGhost(); hideToken(); }
  }

  function stopTravel() {
    cancelAnimationFrame(travelRaf);
    travelRaf = 0;
    token.classList.remove('is-hop');
  }

  function hideToken() {
    tokenOn = false;
    token.classList.add('is-off');
  }

  function placeToken(x, y) {
    tokenAt = { x, y };
    token.style.transform = `translate(${x.toFixed(2)}px, ${y.toFixed(2)}px)`;
  }

  // The dotted path fades away instead of vanishing.
  function dropGhost() {
    const old = ghost;
    ghost = null;
    if (!old) return;
    if (reducedMotion()) { old.remove(); return; }
    old.classList.add('is-out');
    setTimeout(() => old.remove(), 240);
  }

  function runTravel(tr, kind, animate, duration) {
    const found = findEdge(tr.from, tr.to);
    let path, reverse = false;
    dropGhost();
    if (found) {
      path = found.path; reverse = found.reverse;
    } else {
      const a = lay.boxes.get(tr.from), b = lay.boxes.get(tr.to);
      if (!a || !b) { hideToken(); return; }
      path = s('path', { d: freePath(a, b), class: 'ghost-line' });
      travelSvg.insertBefore(path, token);
      ghost = path;
    }
    const len = path.getTotalLength();
    const pt = (p) => path.getPointAtLength(reverse ? len * (1 - p) : len * p);
    token.lastChild.setAttribute('class', `dot tone-${kind}`);
    token.firstChild.setAttribute('class', `dot-halo tone-${kind}`);
    const wasOn = tokenOn && !!tokenAt;
    if (!animate || reducedMotion()) {
      const e = pt(1);
      placeToken(e.x, e.y);
      tokenOn = true;
      token.classList.remove('is-off');
      return;
    }
    // It leaves from where it is: when the last journey ended next to this one, it joins the new path in a curve.
    // When it ended far away (the answer went back to the person), it fades there and comes back here:
    // no dash across the whole map, and never a blink.
    const a = pt(0);
    let off = wasOn ? { x: tokenAt.x - a.x, y: tokenAt.y - a.y } : { x: 0, y: 0 };
    const hop = Math.hypot(off.x, off.y) > 150 ? Math.min(150, duration * 0.25) : 0;
    if (hop) { token.classList.add('is-hop'); off = { x: 0, y: 0 }; } else if (!wasOn) placeToken(a.x, a.y);
    tokenOn = true;
    token.classList.remove('is-off');
    const start = performance.now();
    const ease = (x) => (x < 0.5 ? 4 * x * x * x : 1 - Math.pow(-2 * x + 2, 3) / 2);
    const tick = (now) => {
      const el = now - start;
      if (el < hop) { travelRaf = requestAnimationFrame(tick); return; }
      token.classList.remove('is-hop');
      const p = Math.max(0, Math.min(1, (el - hop) / (duration - hop)));
      const q = pt(ease(p));
      const k = Math.pow(1 - Math.min(1, p * 2.2), 3); // how much of the old place is left
      placeToken(q.x + off.x * k, q.y + off.y * k);
      travelRaf = p < 1 ? requestAnimationFrame(tick) : 0;
    };
    travelRaf = requestAnimationFrame(tick);
  }

  function select(id) {
    for (const [nid, el] of nodeEls) el.classList.toggle('is-selected', nid === id);
  }

  // ----- pan & zoom -----
  // The person took the map in hand: it stays where they put it (and Focus lets go).
  function moved() {
    userFitted = true;
    if (opts.onUserMove) opts.onUserMove();
  }
  const pointers = new Map();
  let drag = null;
  let pinch = null;
  stage.addEventListener('pointerdown', (e) => {
    if (e.button !== 0 && e.pointerType === 'mouse') return;
    if (e.target.closest('.node, .frame-head, .note, .zone-hit, .note-bar, button, textarea, input')) return;
    if (opts.canPan && !opts.canPan()) return;
    pointers.set(e.pointerId, { x: e.clientX, y: e.clientY });
    stage.setPointerCapture(e.pointerId);
    stopCam();
    if (pointers.size === 1) {
      drag = { x: e.clientX, y: e.clientY, vx: view.x, vy: view.y, moved: false };
      stage.classList.add('is-panning');
    } else if (pointers.size === 2) {
      const [a, b] = [...pointers.values()];
      pinch = { d: Math.hypot(a.x - b.x, a.y - b.y), k: view.k };
      drag = null;
    }
  });
  stage.addEventListener('pointermove', (e) => {
    if (!pointers.has(e.pointerId)) return;
    pointers.set(e.pointerId, { x: e.clientX, y: e.clientY });
    if (pinch && pointers.size === 2) {
      const [a, b] = [...pointers.values()];
      const d = Math.hypot(a.x - b.x, a.y - b.y);
      moved();
      zoomAt((pinch.k * (d / pinch.d)) / view.k, (a.x + b.x) / 2, (a.y + b.y) / 2);
    } else if (drag) {
      const dx = e.clientX - drag.x, dy = e.clientY - drag.y;
      if (Math.abs(dx) + Math.abs(dy) > 3) drag.moved = true;
      view.x = drag.vx + dx; view.y = drag.vy + dy;
      if (drag.moved) moved();
      applyView();
    }
  });
  const end = (e) => {
    if (!pointers.has(e.pointerId)) return;
    pointers.delete(e.pointerId);
    if (pointers.size < 2) pinch = null;
    if (!pointers.size) {
      stage.classList.remove('is-panning');
      if (drag && !drag.moved && opts.onBackground) opts.onBackground(e);
      drag = null;
    }
  };
  stage.addEventListener('pointerup', end);
  stage.addEventListener('pointercancel', end);
  stage.addEventListener('wheel', (e) => {
    if (e.target.closest('textarea, .note-bar')) return;
    e.preventDefault();
    stopCam();
    moved();
    if (e.ctrlKey || e.metaKey) zoomAt(Math.exp(-e.deltaY * 0.01), e.clientX, e.clientY);
    else {
      view.x -= e.deltaX; view.y -= e.deltaY;
      applyView();
    }
  }, { passive: false });

  // Focusing a block that is off screen (Tab key) makes the browser scroll the stage, which would leave the
  // map shifted under its own controls: turn that scroll into a move of the map instead.
  stage.addEventListener('scroll', () => {
    const dx = stage.scrollLeft, dy = stage.scrollTop;
    if (!dx && !dy) return;
    stage.scrollLeft = 0; stage.scrollTop = 0;
    if (cam) return; // the camera is already on its way somewhere
    view.x -= dx; view.y -= dy;
    applyView();
  });

  nodeLayer.addEventListener('click', (e) => {
    const el = e.target.closest('[data-id]');
    if (el && opts.onNode) opts.onNode(el.dataset.id, el);
  });

  let resizeT = 0;
  new ResizeObserver(() => {
    clearTimeout(resizeT);
    resizeT = setTimeout(() => {
      if (userFitted) return;
      fit(false);
      if (activeId) ensureVisible(activeId);
    }, 60);
  }).observe(stage);

  applyView();
  return {
    world, notesSvg, notesHtml,
    setTopology, setFrame, select, toWorld, centerWorld,
    fit: () => { userFitted = false; fit(true); },
    zoomBy: (f) => { moved(); zoomAt(f, undefined, undefined, 260); },
    reveal: ensureVisible,
    focusOn,
    // The scale at which the whole map fits: tells whether its names can be read without Focus.
    fitScale: () => {
      const r = stage.getBoundingClientRect();
      if (!r.width || !lay.width) return 1;
      const { w, h } = safeArea(r);
      return Math.min(w / lay.width, h / Math.max(lay.height, 1), 1.1);
    },
    box: (id) => lay.boxes.get(id),
    boxes: () => lay.boxes,
    nodeEl: (id) => nodeEls.get(id),
    view,
    onView: (fn) => viewListeners.push(fn),
  };
}
