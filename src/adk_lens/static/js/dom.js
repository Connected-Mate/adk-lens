// Safe DOM helpers. Event data is untrusted: everything goes through
// createElement / textContent, never through innerHTML.

const SVG_NS = 'http://www.w3.org/2000/svg';

function build(el, attrs, kids) {
  if (attrs) {
    for (const [k, v] of Object.entries(attrs)) {
      if (v === null || v === undefined || v === false) continue;
      if (k === 'class') el.setAttribute('class', v);
      else if (k === 'style' && typeof v === 'object') Object.assign(el.style, v);
      else if (k === 'dataset') Object.assign(el.dataset, v);
      else if (k.startsWith('on') && typeof v === 'function') el.addEventListener(k.slice(2), v);
      else if (k === 'text') el.textContent = String(v);
      else el.setAttribute(k, v === true ? '' : String(v));
    }
  }
  for (const kid of kids.flat(Infinity)) {
    if (kid === null || kid === undefined || kid === false) continue;
    el.append(kid instanceof Node ? kid : document.createTextNode(String(kid)));
  }
  return el;
}

export function h(tag, attrs, ...kids) {
  return build(document.createElement(tag), attrs, kids);
}

export function s(tag, attrs, ...kids) {
  return build(document.createElementNS(SVG_NS, tag), attrs, kids);
}

// Like el.append(), but skips null / undefined / false.
export function put(el, ...kids) {
  for (const kid of kids.flat(Infinity)) {
    if (kid === null || kid === undefined || kid === false) continue;
    el.append(kid instanceof Node ? kid : document.createTextNode(String(kid)));
  }
  return el;
}

export const $ = (sel, root = document) => root.querySelector(sel);

export function clear(el) {
  while (el.firstChild) el.removeChild(el.firstChild);
  return el;
}

export function short(text, max = 120) {
  const str = text === null || text === undefined ? '' : String(text).replace(/\s+/g, ' ').trim();
  return str.length > max ? str.slice(0, max - 1).trimEnd() + '…' : str;
}

// Long text, clipped, with a "show more" button.
export function clipped(text, max, labels) {
  const str = text === null || text === undefined ? '' : String(text);
  const wrap = h('span', { class: 'clip' });
  if (str.length <= max) {
    wrap.textContent = str;
    return wrap;
  }
  const body = h('span', { text: str.slice(0, max).trimEnd() + '…' });
  let open = false;
  const btn = h('button', { class: 'linkish', type: 'button', 'aria-expanded': 'false', text: labels.more });
  btn.addEventListener('click', (e) => {
    e.stopPropagation();
    open = !open;
    body.textContent = open ? str : str.slice(0, max).trimEnd() + '…';
    btn.textContent = open ? labels.less : labels.more;
    btn.setAttribute('aria-expanded', String(open));
  });
  wrap.append(body, ' ', btn);
  return wrap;
}

export function pretty(value) {
  if (typeof value === 'string') return value;
  try {
    return JSON.stringify(value, null, 2);
  } catch {
    return String(value);
  }
}

export function fmtDuration(ms) {
  if (typeof ms !== 'number' || !isFinite(ms) || ms < 1) return '';
  if (ms < 1000) return `${Math.round(ms)} ms`;
  if (ms < 60000) return `${(ms / 1000).toFixed(ms < 10000 ? 1 : 0)} s`;
  return `${Math.floor(ms / 60000)} min ${Math.round((ms % 60000) / 1000)} s`;
}

export const reducedMotion = () =>
  window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;

export function lsGet(key) {
  try {
    return localStorage.getItem(key);
  } catch {
    return null;
  }
}

export function lsSet(key, value) {
  try {
    localStorage.setItem(key, value);
  } catch {
    /* private mode: ignore */
  }
}
