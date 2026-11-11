// Turns the annotations into one clear message for a coding agent.
import { short, put } from './dom.js';
import { t } from './i18n.js';

const TOOLS = new Set(['tool', 'toolset']);
const one = (text, max = 300) => short(text, max);

function outline(topo) {
  const lines = [];
  const kids = new Map();
  const ids = new Set(topo.nodes.map((n) => n.id));
  for (const n of topo.nodes) {
    const p = n.parent && ids.has(n.parent) ? n.parent : null;
    if (!kids.has(p)) kids.set(p, []);
    kids.get(p).push(n);
  }
  const seen = new Set();
  const walk = (n, depth) => {
    if (seen.has(n.id) || lines.length > 150) return;
    seen.add(n.id);
    const pad = '  '.repeat(depth);
    if (TOOLS.has(n.kind)) {
      lines.push(`${pad}- ${t(`kind.${n.kind}`)} \`${n.name}\`${n.description ? `: ${one(n.description, 90)}` : ''}`);
      return;
    }
    const bits = [t(`kind.${n.kind}`) === `kind.${n.kind}` ? n.kind : t(`kind.${n.kind}`)];
    if (n.model) bits.push(String(n.model));
    if (n.id === topo.root) bits.push(t('p.root'));
    lines.push(`${pad}- \`${n.name}\` (${bits.join(', ')})${n.description ? `: ${one(n.description, 110)}` : ''}`);
    for (const c of kids.get(n.id) || []) walk(c, depth + 1);
  };
  const root = topo.nodes.find((n) => n.id === topo.root);
  if (root) walk(root, 0);
  for (const n of kids.get(null) || []) walk(n, 0);
  return lines;
}

function nodeLine(n) {
  const kind = t(`kind.${n.kind}`) === `kind.${n.kind}` ? n.kind : t(`kind.${n.kind}`);
  return `${kind} \`${n.name}\``;
}

function nodesIn(box, boxes, topo, margin = 0) {
  const out = [];
  for (const n of topo.nodes) {
    const b = boxes.get(n.id);
    if (!b || b.type === 'group') continue;
    const cx = b.x + b.w / 2, cy = b.y + b.h / 2;
    if (cx >= box.x - margin && cx <= box.x + box.w + margin && cy >= box.y - margin && cy <= box.y + box.h + margin) out.push(n);
  }
  return out;
}

export function buildPrompt({ app, topo, version, items, boxes, notes }) {
  const mine = items.filter((it) => it.app === app);
  const out = [];
  out.push(`# ${t('p.title', { app })}`, '', t('p.intro'), '');
  if (topo && topo.nodes.length) {
    out.push(`## ${t('p.structure', { v: version ?? 1 })}`, '', ...outline(topo), '');
  }
  out.push(`## ${t('p.notes', { n: mine.length })}`, '');
  if (!mine.length) out.push(t('p.none'));
  const byId = new Map((topo ? topo.nodes : []).map((n) => [n.id, n]));
  mine.forEach((it, i) => {
    const kind = t(`note.kind.${it.kind}`);
    let where = t('p.on.board');
    const facts = [];
    const describe = (n) => {
      facts.push(`- ${t('p.points')}: ${nodeLine(n)}`);
      if (n.model) facts.push(`- ${t('p.model')}: ${n.model}`);
      if (n.instruction) facts.push(`- ${t('p.instruction')}: "${one(n.instruction, 280)}"`);
      else if (n.description) facts.push(`- ${one(n.description, 200)}`);
    };
    if (it.target && it.target.type === 'node') {
      const n = byId.get(it.target.id) || { id: it.target.id, name: it.target.name || it.target.id, kind: 'custom' };
      where = t('p.on.node', { kind: t(`kind.${n.kind}`) === `kind.${n.kind}` ? n.kind : t(`kind.${n.kind}`), name: n.name });
      describe(n);
    } else if (it.target && it.target.type === 'step') {
      where = t('p.on.step', { run: one(it.target.runTitle || '', 80) });
      if (it.target.sentence) facts.push(`- ${t('p.step')}: ${one(it.target.sentence, 240)}`);
      if (it.target.content) facts.push(`- ${t('p.content')}: "${one(it.target.content, 400)}"`);
    } else if (it.type === 'zone' && topo) {
      where = t('p.on.zone');
      const inside = nodesIn(notes.zoneBox(it), boxes, topo);
      if (inside.length) facts.push(`- ${t('p.inside')}: ${inside.slice(0, 12).map(nodeLine).join(', ')}${inside.length > 12 ? ', …' : ''}`);
    } else if (topo) {
      const p = notes.position(it);
      const near = nodesIn({ x: p.x, y: p.y, w: it.type === 'stamp' ? 52 : 180, h: it.type === 'stamp' ? 52 : 120 }, boxes, topo, 70);
      if (near.length === 1) describe(near[0]);
      else if (near.length) facts.push(`- ${t('p.near')}: ${near.slice(0, 6).map(nodeLine).join(', ')}`);
    }
    out.push(`### ${i + 1}. ${kind} ${where}`, '');
    const text = (it.text || '').trim();
    out.push(text ? text.split('\n').map((l) => `> ${l}`).join('\n') : `> ${t('p.notext')}`, '');
    if (facts.length) out.push(...facts, '');
  });
  return out.join('\n').replace(/\n{3,}/g, '\n\n').trim() + '\n';
}

export async function copyText(text) {
  try {
    if (navigator.clipboard && window.isSecureContext) {
      await navigator.clipboard.writeText(text);
      return true;
    }
  } catch { /* fall through */ }
  try {
    const ta = document.createElement('textarea');
    ta.value = text;
    ta.setAttribute('readonly', '');
    ta.style.position = 'fixed';
    ta.style.opacity = '0';
    put(document.body, ta);
    ta.select();
    const ok = document.execCommand('copy');
    ta.remove();
    return ok;
  } catch {
    return false;
  }
}
