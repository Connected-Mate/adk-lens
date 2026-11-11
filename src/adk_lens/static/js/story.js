// The "Story" view: one plain sentence per step, details behind a click.
import { h, clear, clipped, pretty, short, fmtDuration, put } from './dom.js';
import { icon } from './icons.js';
import { t, tn } from './i18n.js';
import { stepsOf } from './store.js';

const TONE_ICON = {
  ask: 'user', agent: 'llm', think: 'llm', thought: 'llm', tool: 'tool', tool_result: 'tool', handoff: 'handoff',
  memory: 'memory', file: 'doc', output: 'check', escalate: 'loop', answer: 'comment', done: 'check', error: 'warn',
};

function argsShort(args) {
  if (!args || typeof args !== 'object') return args === undefined || args === null ? '' : short(String(args), 60);
  const entries = Object.entries(args);
  const shown = entries.slice(0, 3).map(([k, v]) => `${k} = ${short(typeof v === 'string' ? v : JSON.stringify(v), 36)}`);
  if (entries.length > 3) shown.push('…');
  return shown.join(', ');
}

function bodyOf(value) {
  if (value === undefined || value === null || value === '') return '';
  if (typeof value === 'string') return value;
  if (typeof value === 'object') {
    const keys = Object.keys(value);
    if (keys.length === 1 && typeof value[keys[0]] !== 'object') return String(value[keys[0]]);
    return Object.entries(value).map(([k, v]) => `${k}: ${typeof v === 'string' ? v : JSON.stringify(v)}`).join('\n');
  }
  return String(value);
}

// {key, vars, body}: the sentence of a step, in the current language.
export function sentence(step) {
  const ev = step.ev || {};
  const agent = step.agent || '?';
  switch (step.kind) {
    case 'ask': return { key: 's.ask', vars: {}, body: step.text };
    case 'agent': return { key: 's.agent', vars: { agent } };
    case 'think': return ev.model ? { key: 's.think.model', vars: { agent, model: String(ev.model) } } : { key: 's.think', vars: { agent } };
    case 'thought': {
      const meta = fmtDuration(ev.duration_ms);
      if (step.calls && step.calls.length) return { key: 's.thought.calls', vars: { agent, tools: step.calls.join(', ') }, meta, body: step.text };
      if (step.transfers) return { key: 's.thought.transfer', vars: { agent }, meta, body: step.text };
      if (step.text) return { key: 's.thought.text', vars: { agent }, body: step.text, meta };
      return { key: 's.thought.none', vars: { agent }, meta };
    }
    case 'tool': {
      if (step.agentTool) return { key: 's.tool.agent', vars: { agent, tool: step.tool }, body: bodyOf(ev.args) };
      const args = argsShort(ev.args);
      return args ? { key: 's.tool.args', vars: { agent, tool: step.tool, args } } : { key: 's.tool', vars: { agent, tool: step.tool } };
    }
    case 'tool_result': return { key: step.agentTool ? 's.tool_result.agent' : 's.tool_result', vars: { tool: step.tool, agent }, body: bodyOf(ev.result), meta: fmtDuration(ev.duration_ms) };
    case 'handoff': return { key: 's.handoff', vars: { agent, target: step.target } };
    case 'memory': return { key: 's.memory', vars: { agent, keys: step.keys.join(', ') }, body: bodyOf(step.delta) };
    case 'file': return { key: 's.file', vars: { agent, files: step.files.join(', ') } };
    case 'output': return { key: 's.output', vars: { agent }, body: bodyOf(step.output) };
    case 'escalate': return { key: 's.escalate', vars: { agent } };
    case 'answer': return { key: 's.answer', vars: { agent }, body: step.text };
    case 'done': return ev.duration_ms ? { key: 's.done.d', vars: { d: fmtDuration(ev.duration_ms) } } : { key: 's.done', vars: {} };
    case 'error': return { key: `s.error.${step.what || 'run'}`, vars: { agent, tool: step.tool || '?' }, body: step.text };
    default: return { key: 's.done', vars: {} };
  }
}

export function sentenceText(step) {
  const sn = sentence(step);
  return t(sn.key, sn.vars);
}

const labels = () => ({ more: t('more'), less: t('less') });

function block(title, value) {
  if (value === undefined || value === null || value === '' || (Array.isArray(value) && !value.length)) return null;
  const text = pretty(value);
  return h('div', { class: 'kv' }, h('div', { class: 'kv-k', text: title }),
    typeof value === 'string' ? h('div', { class: 'kv-v' }, clipped(text, 600, labels())) : h('pre', { class: 'json', tabindex: '0', text }));
}

function detailsContent(step) {
  const ev = step.ev || {};
  const out = [];
  if (step.kind === 'think') {
    out.push(block(t('story.system'), ev.system), block(t('story.sent'), partsText(ev.last)), block(t('story.tools.offered'), Array.isArray(ev.tools) ? ev.tools.join(', ') : ''));
  } else if (step.kind === 'thought') {
    out.push(block(t('story.received'), step.text), block(t('story.args'), Array.isArray(ev.calls) && ev.calls.length ? ev.calls : null));
    if (ev.tokens_in !== undefined || ev.tokens_out !== undefined) out.push(h('p', { class: 'kv-note', text: t('story.tokens', { a: ev.tokens_in ?? '?', b: ev.tokens_out ?? '?' }) }));
  } else if (step.kind === 'tool') out.push(block(t('story.args'), ev.args));
  else if (step.kind === 'tool_result') out.push(block(t('story.result'), ev.result));
  else if (step.kind === 'memory') out.push(block(t('story.result'), step.delta));
  else if (step.kind === 'output') out.push(block(t('story.result'), step.output));
  const shown = out.filter(Boolean);
  const raw = h('details', { class: 'raw' }, h('summary', { text: t('story.raw') }));
  raw.addEventListener('toggle', () => {
    if (raw.open && raw.children.length === 1) put(raw, h('pre', { class: 'json', tabindex: '0', text: pretty(ev) }));
  });
  return [...shown, raw];
}

function partsText(parts) {
  if (!Array.isArray(parts)) return '';
  return parts.map((p) => {
    if (!p || typeof p !== 'object') return '';
    if (p.kind === 'text' || p.kind === 'thought') return String(p.text ?? '');
    if (p.kind === 'call') return `→ ${p.name}(${argsShort(p.args)})`;
    if (p.kind === 'result') return `← ${p.name}: ${short(pretty(p.response), 200)}`;
    if (p.kind === 'file') return `[${p.mime || 'file'}]`;
    return '';
  }).filter(Boolean).join('\n');
}

export function createStory(root, opts) {
  const list = h('ol', { class: 'story-list' });
  const empty = h('p', { class: 'story-empty' });
  put(root, empty, list);
  let runId = null;
  let count = 0;
  let langAt = '';
  const rows = [];

  function row(step, i) {
    const sn = sentence(step);
    const line = h('button', { class: 'st-line', type: 'button', 'aria-label': `${t('story.step', { i: i + 1 })}: ${t(sn.key, sn.vars)}` }, tn(sn.key, sn.vars));
    line.addEventListener('click', () => opts.onStep(i));
    const body = sn.body ? h('div', { class: 'st-text' }, clipped(sn.body, 260, labels())) : null;
    const det = h('details', { class: 'st-details' }, h('summary', { text: t('story.details') }));
    det.addEventListener('toggle', () => {
      if (det.open && det.children.length === 1) put(det, h('div', { class: 'st-detail-body' }, detailsContent(step)));
    });
    const commentBtn = h('button', { class: 'st-comment', type: 'button', 'aria-label': t('story.comment.aria') }, icon('comment', 15), h('span', { text: t('story.comment') }));
    commentBtn.addEventListener('click', () => opts.onComment(step, i));
    const notes = h('div', { class: 'st-notes' });
    const li = h('li', { class: `st tone-${step.kind}`, dataset: { i: String(i), id: step.id } },
      h('span', { class: 'st-ico', 'aria-hidden': 'true' }, icon(TONE_ICON[step.kind] || 'custom', 17)),
      h('div', { class: 'st-main' },
        h('div', { class: 'st-head' }, line, sn.meta ? h('span', { class: 'st-meta', text: sn.meta }) : null),
        body,
        h('div', { class: 'st-actions' }, det.querySelector('summary') ? det : null, commentBtn),
        notes));
    li.style.setProperty('--i', String(Math.min(i, 24)));
    return { li, notes, step };
  }

  function update(run, idx, o = {}) {
    const steps = run ? stepsOf(run) : [];
    empty.textContent = run ? '' : t('story.empty');
    empty.hidden = !!run;
    const rebuild = o.force || !run || run.id !== runId || steps.length < count || langAt !== document.documentElement.lang;
    if (rebuild) {
      clear(list);
      rows.length = 0;
      count = 0;
      runId = run ? run.id : null;
      langAt = document.documentElement.lang;
    }
    for (let i = count; i < steps.length; i++) {
      const r = row(steps[i], i);
      rows.push(r);
      put(list, r.li);
    }
    const grew = steps.length > count;
    count = steps.length;
    rows.forEach((r, i) => {
      r.li.classList.toggle('is-current', i === idx);
      r.li.classList.toggle('is-future', i > idx);
      if (i === idx) r.li.setAttribute('aria-current', 'step'); else r.li.removeAttribute('aria-current');
    });
    if (rebuild || grew || o.notes) for (const r of rows) opts.fillNotes(r.notes, runId, r.step);
    if (o.scroll !== false && rows[idx] && !root.hidden) {
      const el = rows[idx].li;
      const rr = root.getBoundingClientRect(), er = el.getBoundingClientRect();
      if (er.top < rr.top + 90 || er.bottom > rr.bottom - 190) {
        root.scrollTo({ top: root.scrollTop + er.top - rr.top - rr.height * 0.35, behavior: o.instant ? 'auto' : 'smooth' });
      }
    }
  }

  return { update };
}
