// Motion of the player: a progress line that glides, a caption and figures that change without popping.
// Everything here moves with transform / opacity and can be interrupted at any moment.
import { h, clear, put, reducedMotion } from './dom.js';

const TAU = 70; // ms: how fast the knob catches up with where it should be (about 200 ms to settle)
const TAU_LEN = 190; // ms: how fast the line takes a new length when steps arrive (calmer)
const KNOB = 16; // px, same as the native thumb underneath

// The progress line. `input` is the real <input type="range">: it keeps the keyboard, the pointer and the
// screen reader; it is only made invisible, and a fill and a knob are drawn over it.
// `read(now)` says where the request is: { pos: step shown (fractional while it plays), last: index of the
// last step, moving: it is playing through a step, tail: it is playing right behind the newest step }.
export function createScrub(input, read) {
  const fill = h('span', { class: 'scrub-fill' });
  const rail = h('span', { class: 'scrub-rail' }, h('span', { class: 'scrub-knob' }));
  const wrap = h('span', { class: 'scrub-wrap' }, input, h('span', { class: 'scrub-track' }, fill), rail);
  let shown = null; // fraction on screen
  let pos = 0; // the two things it is made of, each one easing on its own
  let len = 0;
  let raf = 0;
  let last = 0;
  let drag = null;

  // One step alone fills the line; from there to two steps the line empties smoothly (no 100% -> 0% flip).
  const fraction = (p, l) => Math.max(0, Math.min(1, l >= 1 ? p / l : 1 - (1 - p) * l));

  function paint() {
    const x = `translateX(${(shown * 100).toFixed(3)}%)`;
    fill.style.transform = x;
    rail.style.transform = x;
  }

  function frame(now) {
    raf = 0;
    if (drag && drag.on) return;
    const tg = read(now);
    const dt = Math.max(0, Math.min(now - last, 120));
    last = now;
    if (shown === null || reducedMotion()) {
      pos = tg.pos;
      len = tg.last;
      shown = fraction(pos, len);
      paint();
      return;
    }
    pos += (tg.pos - pos) * (1 - Math.exp(-dt / TAU));
    if (Math.abs(tg.pos - pos) < 0.002) pos = tg.pos;
    let want = len + (tg.last - len) * (1 - Math.exp(-dt / TAU_LEN));
    if (Math.abs(tg.last - want) < 0.004) want = tg.last;
    // Following live, right behind the newest step: the line grows only as fast as the knob advances,
    // so the knob stays at the front instead of stepping back and forth at every new step.
    let capped = false;
    if (tg.tail && want > len && shown > 0) {
      const cap = Math.max(len, pos / shown);
      if (want > cap) { want = cap; capped = true; }
    }
    len = want;
    const next = fraction(pos, len);
    if (next !== shown) { shown = next; paint(); }
    if (tg.moving || pos !== tg.pos || (len !== tg.last && !capped)) raf = requestAnimationFrame(frame);
  }

  function sync() {
    if (raf || (drag && drag.on)) return;
    if (shown === null || reducedMotion()) { frame(performance.now()); return; }
    last = performance.now() - 16;
    raf = requestAnimationFrame(frame);
  }

  // After a drag the knob is where the finger left it: it eases from there to its step.
  function adopt() {
    const tg = read(performance.now());
    len = tg.last;
    pos = len >= 1 ? shown * len : tg.pos;
  }

  // Dragging: the knob stays under the finger, whatever the steps; it settles on the step when released.
  const move = (e) => {
    if (!drag || e.pointerId !== drag.id) return;
    if (!drag.on && Math.abs(e.clientX - drag.x) < 3) return;
    if (!drag.on) { drag.on = true; wrap.classList.add('is-dragging'); cancelAnimationFrame(raf); raf = 0; }
    shown = Math.max(0, Math.min(1, (e.clientX - drag.left - KNOB / 2) / Math.max(1, drag.width - KNOB)));
    paint();
  };
  const up = (e) => {
    if (!drag || e.pointerId !== drag.id) return;
    if (drag.on && shown !== null) adopt();
    drag = null;
    wrap.classList.remove('is-dragging');
    window.removeEventListener('pointermove', move);
    window.removeEventListener('pointerup', up);
    window.removeEventListener('pointercancel', up);
    sync();
  };
  input.addEventListener('pointerdown', (e) => {
    if (drag || (e.pointerType === 'mouse' && e.button !== 0)) return;
    const r = input.getBoundingClientRect();
    drag = { id: e.pointerId, x: e.clientX, left: r.left, width: r.width, on: false };
    window.addEventListener('pointermove', move);
    window.addEventListener('pointerup', up);
    window.addEventListener('pointercancel', up);
  });

  return { el: wrap, sync, shown: () => shown };
}

// The caption: the old sentence leaves, the new one arrives, the pill takes its new size.
// Never more than one sentence leaving and one arriving, however fast the steps go.
export function createCaption(box) {
  let key = null;
  let cur = null;
  let out = null;
  let doneT = 0;

  function settle() {
    clearTimeout(doneT);
    if (out) { out.remove(); out = null; }
    box.style.width = '';
    box.style.height = '';
    if (cur) cur.style.width = '';
  }

  // `build()` returns the nodes of the sentence, or null when there is nothing to say.
  function set(k, build, o = {}) {
    if (k === key && (cur || box.hidden)) return;
    key = k;
    const kids = build();
    if (!kids) {
      settle();
      clear(box);
      cur = null;
      box.hidden = true;
      return;
    }
    const next = h('div', { class: 'cap-in' }, kids);
    if (o.tone) next.dataset.tone = o.tone;
    const visible = !!cur && !box.hidden && box.getClientRects().length > 0;
    if (!visible || o.instant || reducedMotion()) {
      settle();
      clear(box);
      box.hidden = false;
      put(box, next);
      cur = next;
      return;
    }
    clearTimeout(doneT);
    const first = box.getBoundingClientRect();
    if (out) out.remove();
    out = cur;
    const or = out.getBoundingClientRect();
    out.style.width = `${or.width}px`;
    out.style.marginLeft = `${-or.width / 2}px`;
    out.style.marginTop = `${-or.height / 2}px`;
    out.setAttribute('aria-hidden', 'true');
    out.classList.add('is-out');
    box.style.setProperty('--cap-dy', o.back ? '-7px' : '7px');
    box.style.transition = 'none';
    box.style.width = '';
    box.style.height = '';
    next.classList.add('is-new');
    put(box, next);
    cur = next;
    const last = box.getBoundingClientRect();
    next.style.width = `${next.getBoundingClientRect().width}px`; // its lines stay put while the pill resizes
    box.style.width = `${first.width}px`;
    box.style.height = `${first.height}px`;
    void box.offsetWidth;
    box.style.transition = '';
    box.style.width = `${last.width}px`;
    box.style.height = `${last.height}px`;
    next.classList.remove('is-new');
    doneT = setTimeout(settle, 380);
  }

  return { set };
}

// A figure that changes: the new one rolls in. `dir` < 0 comes from above.
export function swapText(el, text, o = {}) {
  const str = String(text);
  if (el.dataset.v === str) return;
  const had = el.dataset.v !== undefined;
  const now = performance.now();
  const calm = now - (Number(el.dataset.at) || 0) > 140; // stepping fast: no roll, just the figure
  el.dataset.v = str;
  el.dataset.at = String(now);
  const span = h('span', { class: 'roll', text: str });
  if (had && calm && !o.instant && !reducedMotion()) span.classList.add(o.dir < 0 ? 'from-above' : 'from-below');
  clear(el);
  put(el, span);
}
