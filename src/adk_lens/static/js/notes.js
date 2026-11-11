// Whiteboard annotations: sticky notes, stamps, circled areas, comments.
import { h, s, clear, lsGet, lsSet, put } from './dom.js';
import { icon } from './icons.js';
import { t } from './i18n.js';

const LS_KEY = 'adk-lens.notes';
export const KINDS = ['comment', 'question', 'idea', 'bug'];
export const STAMPS = { question: '?', idea: '💡', bug: '🐞', like: '👍' };

const uid = () => `n${Date.now().toString(36)}${Math.random().toString(36).slice(2, 7)}`;

export function createNotes(map, stage, opts) {
  let items = [];
  let tool = 'select';
  let selected = null;
  let saveT = 0;
  let swallowClick = 0;
  let draft = null;

  // ----- persistence -----
  function load(hubDoc) {
    let local = null;
    try { local = JSON.parse(lsGet(LS_KEY) || 'null'); } catch { local = null; }
    const pick = [hubDoc, local].filter((d) => d && typeof d === 'object' && Array.isArray(d.items))
      .sort((a, b) => (Number(b.updated) || 0) - (Number(a.updated) || 0))[0];
    items = pick ? pick.items.filter(valid).map((it) => ({ ...it })) : [];
    selected = null;
    render();
    opts.onChange();
  }

  function valid(it) {
    return it && typeof it === 'object' && typeof it.id === 'string' && ['sticky', 'stamp', 'zone', 'comment'].includes(it.type);
  }

  function changed(redraw = true) {
    if (redraw) render();
    opts.onChange();
    clearTimeout(saveT);
    saveT = setTimeout(save, 450);
  }

  function save() {
    const doc = { v: 1, updated: Date.now(), items, prompt: opts.buildPrompt() };
    lsSet(LS_KEY, JSON.stringify(doc));
    opts.push(doc);
  }

  // ----- small shared parts -----
  function kindPicker(item, onPick) {
    const wrap = h('div', { class: 'kind-picker', role: 'group', 'aria-label': t('note.kind') });
    for (const k of KINDS) {
      const b = h('button', { type: 'button', class: `kind-chip kind-${k}`, 'aria-pressed': String(item.kind === k), text: t(`note.kind.${k}`) });
      b.addEventListener('click', (e) => {
        e.stopPropagation();
        item.kind = k;
        onPick ? onPick() : changed();
      });
      put(wrap, b);
    }
    return wrap;
  }

  function autoGrow(ta) {
    ta.style.height = 'auto';
    ta.style.height = `${Math.max(ta.scrollHeight, 44)}px`;
  }

  function textArea(item, placeholder) {
    const ta = h('textarea', { class: 'note-text', rows: '2', placeholder, 'aria-label': placeholder, maxlength: '2000' });
    ta.value = item.text || '';
    ta.addEventListener('input', () => {
      item.text = ta.value;
      autoGrow(ta);
      changed(false);
    });
    ta.addEventListener('keydown', (e) => {
      e.stopPropagation();
      if (e.key === 'Escape') ta.blur();
    });
    requestAnimationFrame(() => autoGrow(ta));
    return ta;
  }

  function deleteBtn(item) {
    const b = h('button', { type: 'button', class: 'icon-btn note-del', 'aria-label': t('note.delete'), title: t('note.delete') }, icon('trash', 16));
    b.addEventListener('click', (e) => {
      e.stopPropagation();
      remove(item.id);
    });
    return b;
  }

  // A note shown inside a panel or under a story step.
  function inlineNote(item) {
    const el = h('div', { class: `note-inline kind-${item.kind}` });
    const redraw = () => {
      el.className = `note-inline kind-${item.kind}`;
      for (const b of el.querySelectorAll('.kind-chip')) b.setAttribute('aria-pressed', String(b.classList.contains(`kind-${item.kind}`)));
      changed(true);
    };
    put(el, h('div', { class: 'note-inline-top' }, kindPicker(item, redraw), deleteBtn(item)), textArea(item, t('note.placeholder')));
    return el;
  }

  // ----- geometry -----
  function pos(item) {
    if (item.target && item.target.type === 'node') {
      const b = map.box(item.target.id);
      if (b) return { x: b.x + b.w - 24 + (item.dx || 0), y: b.y - 132 + (item.dy || 0) };
    }
    return { x: item.x || 0, y: item.y || 0 };
  }

  function zonePath(item) {
    if (item.shape === 'lasso' && Array.isArray(item.pts) && item.pts.length > 2) {
      const p = item.pts;
      let d = `M${(p[0][0] + p[1][0]) / 2} ${(p[0][1] + p[1][1]) / 2}`;
      for (let i = 1; i < p.length; i++) {
        const n = p[(i + 1) % p.length];
        d += ` Q${p[i][0]} ${p[i][1]} ${(p[i][0] + n[0]) / 2} ${(p[i][1] + n[1]) / 2}`;
      }
      return `${d} Q${p[0][0]} ${p[0][1]} ${(p[0][0] + p[1][0]) / 2} ${(p[0][1] + p[1][1]) / 2} Z`;
    }
    const rx = item.w / 2, ry = item.h / 2, cx = item.x + rx, cy = item.y + ry;
    return `M${cx - rx} ${cy} a${rx} ${ry} 0 1 0 ${rx * 2} 0 a${rx} ${ry} 0 1 0 ${-rx * 2} 0 Z`;
  }

  function bbox(item) {
    if (item.shape === 'lasso' && Array.isArray(item.pts) && item.pts.length) {
      const xs = item.pts.map((p) => p[0]), ys = item.pts.map((p) => p[1]);
      const x = Math.min(...xs), y = Math.min(...ys);
      return { x, y, w: Math.max(...xs) - x, h: Math.max(...ys) - y };
    }
    return { x: item.x, y: item.y, w: item.w, h: item.h };
  }

  // ----- drawing the notes on the board -----
  function render() {
    clear(map.notesHtml);
    clear(map.notesSvg);
    const app = opts.getApp();
    for (const item of items) {
      if (item.app !== app || item.type === 'comment') continue;
      if (item.type === 'zone') drawZone(item);
      else drawNote(item);
    }
    if (draft) put(map.notesSvg, draft.el);
  }

  function drawNote(item) {
    const p = pos(item);
    const isSel = selected === item.id;
    const el = h('div', {
      class: `note ${item.type} kind-${item.kind}${isSel ? ' is-selected' : ''}`, tabindex: '0', role: 'group', dataset: { id: item.id },
      'aria-label': `${t(`note.aria.${item.type}`)}, ${t(`note.kind.${item.kind}`)}${item.text ? `: ${item.text}` : ''}`,
    });
    el.style.left = `${p.x}px`;
    el.style.top = `${p.y}px`;
    el.style.setProperty('--tilt', `${((item.id.charCodeAt(item.id.length - 1) % 5) - 2) * 0.8}deg`);
    if (item.type === 'sticky') {
      put(el, h('div', { class: 'note-grip', 'aria-hidden': 'true' },
        h('span', { class: 'note-tag', text: item.target && item.target.type === 'node' ? t('note.on', { name: item.target.name || item.target.id }) : t(`note.kind.${item.kind}`) })));
      put(el, textArea(item, t('note.placeholder')));
    } else {
      put(el, h('span', { class: `stamp-face stamp-${item.stamp}`, 'aria-hidden': 'true', text: STAMPS[item.stamp] || '?' }));
      if (item.text) put(el, h('span', { class: 'stamp-text', text: item.text }));
    }
    if (isSel) put(el, bar(item));
    put(map.notesHtml, el);
  }

  function drawZone(item) {
    const d = zonePath(item);
    const isSel = selected === item.id;
    const g = s('g', { class: `zone kind-${item.kind}${isSel ? ' is-selected' : ''}`, 'data-id': item.id });
    put(g, s('path', { d, class: 'zone-line' }), s('path', { d, class: 'zone-hit' }));
    put(map.notesSvg, g);
    const b = bbox(item);
    const label = h('div', {
      class: `note zone-label kind-${item.kind}${isSel ? ' is-selected' : ''}${item.text ? '' : ' is-blank'}`, tabindex: '0', role: 'group', dataset: { id: item.id },
      'aria-label': `${t('note.aria.zone')}, ${t(`note.kind.${item.kind}`)}${item.text ? `: ${item.text}` : ''}`,
    }, h('span', { class: 'zone-text', text: item.text || t(`note.kind.${item.kind}`) }));
    label.style.left = `${b.x + b.w / 2}px`;
    label.style.top = `${b.y + b.h + 6}px`;
    if (isSel) put(label, bar(item));
    put(map.notesHtml, label);
  }

  // The little bar shown next to the selected note.
  function bar(item) {
    const el = h('div', { class: 'note-bar' });
    el.addEventListener('pointerdown', (e) => e.stopPropagation());
    if (item.type !== 'stamp') put(el, kindPicker(item));
    if (item.type !== 'sticky') {
      const ph = t(item.type === 'zone' ? 'note.zone.placeholder' : 'note.stamp.placeholder');
      const input = h('input', { class: 'note-input', type: 'text', placeholder: ph, 'aria-label': ph, maxlength: '400' });
      input.value = item.text || '';
      input.addEventListener('input', () => { item.text = input.value; changed(false); });
      input.addEventListener('keydown', (e) => {
        e.stopPropagation();
        if (e.key === 'Enter' || e.key === 'Escape') { select(null); }
      });
      input.addEventListener('blur', () => setTimeout(() => { if (selected === item.id && !el.contains(document.activeElement)) render(); }, 0));
      put(el, input);
    }
    put(el, deleteBtn(item));
    return el;
  }

  function select(id, focus) {
    selected = id;
    render();
    if (id && focus) {
      const el = map.notesHtml.querySelector(`[data-id="${CSS.escape(id)}"]`);
      const field = el && el.querySelector(focus === 'field' ? '.note-text, .note-input' : null);
      if (field) field.focus({ preventScroll: true });
      else if (el) el.focus({ preventScroll: true });
    }
  }

  function remove(id) {
    items = items.filter((it) => it.id !== id);
    if (selected === id) selected = null;
    changed();
  }

  function add(partial, focus = 'field') {
    const item = { id: uid(), app: opts.getApp(), kind: 'comment', text: '', ts: Date.now(), ...partial };
    items.push(item);
    selected = item.id;
    changed();
    if (focus) select(item.id, focus);
    return item;
  }

  // ----- tools -----
  function setTool(next) {
    tool = next;
    stage.dataset.tool = tool;
    opts.onTool(tool);
  }

  function place(kind, pt) {
    if (kind === 'sticky') add({ type: 'sticky', x: pt.x - 90, y: pt.y - 60 });
    else if (kind.startsWith('stamp:')) {
      const stamp = kind.slice(6);
      add({ type: 'stamp', stamp, kind: stamp === 'like' ? 'like' : stamp, x: pt.x - 26, y: pt.y - 26 }, 'self');
    } else add({ type: 'zone', shape: 'ellipse', x: pt.x - 150, y: pt.y - 95, w: 300, h: 190 });
    setTool('select');
  }

  // Keyboard users: activating a tool drops the note in the middle of the view.
  function placeAtCenter(kind) {
    place(kind, map.centerWorld());
  }

  stage.addEventListener('pointerdown', (e) => {
    if (tool === 'select') return;
    if (e.target.closest('.note-bar')) return;
    if (e.button !== 0 && e.pointerType === 'mouse') return;
    e.preventDefault();
    e.stopImmediatePropagation();
    swallowClick = Date.now();
    const start = map.toWorld(e.clientX, e.clientY);
    if (tool === 'sticky' || tool.startsWith('stamp:')) {
      place(tool, start);
      return;
    }
    const shape = tool;
    draft = { el: s('path', { class: 'zone-line is-draft' }), pts: [[start.x, start.y]] };
    put(map.notesSvg, draft.el);
    stage.setPointerCapture(e.pointerId);
    const move = (ev) => {
      const p = map.toWorld(ev.clientX, ev.clientY);
      if (shape === 'lasso') {
        const last = draft.pts[draft.pts.length - 1];
        if (Math.hypot(p.x - last[0], p.y - last[1]) > 9) draft.pts.push([Math.round(p.x), Math.round(p.y)]);
        draft.el.setAttribute('d', `M${draft.pts.map((q) => q.join(' ')).join(' L')}`);
      } else {
        draft.box = { x: Math.min(start.x, p.x), y: Math.min(start.y, p.y), w: Math.abs(p.x - start.x), h: Math.abs(p.y - start.y) };
        draft.el.setAttribute('d', zonePath({ shape: 'ellipse', ...draft.box }));
      }
    };
    const up = () => {
      stage.removeEventListener('pointermove', move);
      stage.removeEventListener('pointerup', up);
      stage.removeEventListener('pointercancel', up);
      const d = draft;
      draft = null;
      swallowClick = Date.now();
      if (shape === 'lasso' && d.pts.length > 5) add({ type: 'zone', shape: 'lasso', pts: d.pts });
      else if (shape === 'ellipse' && d.box && d.box.w > 24 && d.box.h > 24) add({ type: 'zone', shape: 'ellipse', ...d.box });
      else if (shape === 'ellipse') add({ type: 'zone', shape: 'ellipse', x: start.x - 150, y: start.y - 95, w: 300, h: 190 });
      else render();
      setTool('select');
    };
    stage.addEventListener('pointermove', move);
    stage.addEventListener('pointerup', up);
    stage.addEventListener('pointercancel', up);
  }, true);

  stage.addEventListener('click', (e) => {
    if (Date.now() - swallowClick < 350) {
      e.stopPropagation();
      e.preventDefault();
    }
  }, true);

  // ----- select, move, delete -----
  function itemOf(target) {
    const el = target.closest('[data-id]');
    if (!el || !(map.notesHtml.contains(el) || map.notesSvg.contains(el))) return null;
    return items.find((it) => it.id === el.dataset.id) || null;
  }

  function startDrag(e) {
    if (tool !== 'select') return;
    if (e.target.closest('.note-bar')) return;
    const item = itemOf(e.target);
    if (!item) return;
    e.stopPropagation();
    const typing = e.target.closest('textarea, input');
    if (typing) return; // focus will select it
    const host = e.currentTarget;
    const sx = e.clientX, sy = e.clientY;
    let moved = false;
    const orig = JSON.parse(JSON.stringify(item));
    let el = null;
    const move = (ev) => {
      if (!el || !el.isConnected) el = map.notesHtml.querySelector(`[data-id="${CSS.escape(item.id)}"]`);
      const dx = (ev.clientX - sx) / map.view.k, dy = (ev.clientY - sy) / map.view.k;
      if (!moved && Math.hypot(ev.clientX - sx, ev.clientY - sy) < 4) return;
      moved = true;
      if (item.target && item.target.type === 'node') {
        item.dx = (orig.dx || 0) + dx; item.dy = (orig.dy || 0) + dy;
      } else if (item.shape === 'lasso') item.pts = orig.pts.map((p) => [p[0] + dx, p[1] + dy]);
      else { item.x = orig.x + dx; item.y = orig.y + dy; }
      if (item.type === 'zone') render();
      else if (el) {
        const p = pos(item);
        el.style.left = `${p.x}px`; el.style.top = `${p.y}px`;
        el.classList.add('is-dragging');
      }
    };
    const up = () => {
      host.removeEventListener('pointermove', move);
      host.removeEventListener('pointerup', up);
      host.removeEventListener('pointercancel', up);
      if (moved) { selected = item.id; changed(); } else select(item.id, item.type === 'sticky' ? 'field' : 'self');
    };
    try { host.setPointerCapture(e.pointerId); } catch { /* ignore */ }
    host.addEventListener('pointermove', move);
    host.addEventListener('pointerup', up);
    host.addEventListener('pointercancel', up);
  }
  map.notesHtml.addEventListener('pointerdown', startDrag);
  map.notesSvg.addEventListener('pointerdown', startDrag);

  map.notesHtml.addEventListener('focusin', (e) => {
    const item = itemOf(e.target);
    if (item && selected !== item.id && !e.target.closest('.note-bar')) {
      // Show the bar for keyboard users without stealing focus.
      selected = item.id;
      const keep = e.target.matches('.note') ? 'self' : 'field';
      select(item.id, keep);
    }
  });

  map.notesHtml.addEventListener('keydown', (e) => {
    const item = itemOf(e.target);
    if (!item || !e.target.matches('.note')) return;
    const step = e.shiftKey ? 40 : 10;
    const moves = { ArrowLeft: [-step, 0], ArrowRight: [step, 0], ArrowUp: [0, -step], ArrowDown: [0, step] };
    if (e.key === 'Delete' || e.key === 'Backspace') {
      e.preventDefault(); e.stopPropagation();
      remove(item.id);
    } else if (moves[e.key]) {
      e.preventDefault(); e.stopPropagation();
      const [dx, dy] = moves[e.key];
      if (item.target && item.target.type === 'node') { item.dx = (item.dx || 0) + dx; item.dy = (item.dy || 0) + dy; }
      else if (item.shape === 'lasso') item.pts = item.pts.map((p) => [p[0] + dx, p[1] + dy]);
      else { item.x += dx; item.y += dy; }
      changed();
      select(item.id, 'self');
    } else if (e.key === 'Enter') {
      e.preventDefault(); e.stopPropagation();
      select(item.id, 'field');
    } else if (e.key === 'Escape') {
      e.stopPropagation();
      select(null);
    }
  });

  return {
    load, render, setTool, placeAtCenter, remove,
    tool: () => tool,
    selected: () => selected,
    deselect: () => { if (selected) { select(null); return true; } return false; },
    all: () => items,
    forApp: (app) => items.filter((it) => it.app === app),
    forNode: (id) => items.filter((it) => it.app === opts.getApp() && it.target && it.target.type === 'node' && it.target.id === id),
    addNodeComment(node) {
      return add({ type: 'sticky', target: { type: 'node', id: node.id, name: node.name } });
    },
    addStepComment(run, step, snapshot) {
      return add({ type: 'comment', target: { type: 'step', run: run.id, step: step.id, ...snapshot } }, null);
    },
    fillStepNotes(container, runId, step) {
      const mine = items.filter((it) => it.type === 'comment' && it.target && it.target.run === runId && it.target.step === step.id);
      if (!mine.length && !container.firstChild) return;
      const active = document.activeElement;
      const keepId = active && container.contains(active) ? active.closest('[data-note]')?.dataset.note : null;
      if (keepId && mine.some((m) => m.id === keepId) && container.children.length === mine.length) return; // typing: leave it alone
      clear(container);
      for (const it of mine) {
        const el = inlineNote(it);
        el.dataset.note = it.id;
        put(container, el);
      }
    },
    inlineNote,
    clearApp(app) {
      items = items.filter((it) => it.app !== app);
      selected = null;
      changed();
    },
    zoneBox: bbox,
    position: pos,
    flush: save,
  };
}
