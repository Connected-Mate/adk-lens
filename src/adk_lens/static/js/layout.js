// A small layered layout written for agent apps: the person on the left,
// agents flowing to the right, tools tucked under their agent, and frames
// around "one after the other / at the same time / again and again" groups.
import { USER } from './store.js';

const GROUPS = new Set(['sequential', 'parallel', 'loop', 'workflow']);
const TOOLS = new Set(['tool', 'toolset']);

const AG = { w: 208, h: 72 };
const TL = { w: 172, h: 38, gap: 10, perCol: 6, indent: 26 };
const US = { w: 196, h: 72 };
const GAP_X = 168; // room for the trunk of a fan of connectors, and for a label on each branch
const TRUNK = 36;
const BASE = { h: 50, gap: 10 }; // what an app stands on: its model, its session memory
export const MODEL = '@model';
export const MEMORY = '@memory';
export const GUARDS = '@guards';
const GAP_Y = 34;
const PAD = 26;
const HEAD = 46;

export function layout(topo) {
  const byId = new Map(topo.nodes.map((n) => [n.id, n]));
  const kids = new Map();
  for (const n of topo.nodes) {
    const p = n.parent && byId.has(n.parent) && n.parent !== n.id ? n.parent : null;
    if (!kids.has(p)) kids.set(p, []);
    kids.get(p).push(n);
  }
  const orderOf = new Map();
  for (const e of topo.edges) if (typeof e.order === 'number') orderOf.set(`${e.from}>${e.to}`, e.order);

  // The foundations, shown once under the first agent: the model the agents think with (when they all share one)
  // and the session memory (when some agent writes to it).
  const models = [...new Set(topo.nodes.map((n) => n.model).filter(Boolean).map(String))];
  const keys = [...new Set(topo.nodes.map((n) => n.output_key).filter(Boolean).map(String))];
  const bases = [];
  if (models.length === 1) bases.push({ id: MODEL, kind: 'model', text: models[0] });
  if (keys.length) bases.push({ id: MEMORY, kind: 'memory', text: keys.join(', ') });
  // Safety: how many checks, on how many of the agents. Said even when there is none.
  const agentsAll = topo.nodes.filter((n) => !TOOLS.has(n.kind) && !GROUPS.has(n.kind));
  const guarded = agentsAll.filter((n) => n.guards && n.guards.length);
  if (agentsAll.length) bases.push({ id: GUARDS, kind: 'guards', n: guarded.reduce((sum, n) => sum + n.guards.length, 0), a: guarded.length, total: agentsAll.length });

  const seen = new Set();
  const synth = []; // arrows we add inside groups ("then", "again")

  function block(id) {
    // Returns {w, h, ay, items:[{id, x, y, w, h, type}]} in local coordinates.
    const node = byId.get(id);
    seen.add(id);
    const children = (kids.get(id) || []).filter((c) => !seen.has(c.id));
    const tools = children.filter((c) => TOOLS.has(c.kind));
    const agents = children.filter((c) => !TOOLS.has(c.kind));
    tools.forEach((t) => seen.add(t.id));
    return GROUPS.has(node.kind) && agents.length ? groupBlock(node, agents, tools) : agentBlock(node, agents, tools);
  }

  function toolItems(tools, x0, y0, items) {
    const longest = Math.max(...tools.map((t) => String(t.name).length));
    const TLw = Math.round(Math.max(TL.w, Math.min(280, 64 + longest * 8.4)));
    const cols = Math.ceil(tools.length / TL.perCol);
    tools.forEach((t, i) => {
      const col = Math.floor(i / TL.perCol), row = i % TL.perCol;
      items.push({ id: t.id, type: 'tool', x: x0 + TL.indent + col * (TLw + TL.gap), y: y0 + row * (TL.h + TL.gap), w: TLw, h: TL.h, col });
    });
    const rows = Math.min(tools.length, TL.perCol);
    return { w: TL.indent + cols * (TLw + TL.gap) - TL.gap, h: rows * (TL.h + TL.gap) - TL.gap };
  }

  function stack(blocks, gap, perCol) {
    // Vertical stack, wrapping into columns when there are many.
    const out = { w: 0, h: 0, placed: [] };
    let x = 0;
    for (let i = 0; i < blocks.length; i += perCol) {
      const col = blocks.slice(i, i + perCol);
      const cw = Math.max(...col.map((b) => b.w));
      let y = 0;
      for (const b of col) {
        out.placed.push({ b, x, y });
        y += b.h + gap;
      }
      out.h = Math.max(out.h, y - gap);
      x += cw + GAP_X * 0.6;
      out.w = x - GAP_X * 0.6;
    }
    return out;
  }

  function agentBlock(node, agents, tools) {
    const items = [];
    const aw = Math.round(Math.max(AG.w, Math.min(320, 92 + String(node.name).length * 9.6)));
    const self = { id: node.id, type: 'agent', x: 0, y: 0, w: aw, h: AG.h };
    let selfW = aw, selfH = AG.h;
    if (tools.length) {
      const tb = toolItems(tools, 0, AG.h + 16, items);
      selfW = Math.max(selfW, tb.w);
      selfH = AG.h + 16 + tb.h;
    }
    if (node.id === topo.root) {
      for (const b of bases) {
        items.push({ id: b.id, type: 'base', x: 0, y: selfH + (selfH === AG.h ? 22 : 18), w: aw, h: BASE.h });
        selfH += (selfH === AG.h ? 22 : 18) + BASE.h;
      }
    }
    self.bw = selfW; // connectors leave beyond the tools, never through them
    items.push(self);
    if (!agents.length) return { w: selfW, h: selfH, ay: AG.h / 2, items };
    const blocks = agents.map((a) => block(a.id));
    const col = stack(blocks, GAP_Y, 8);
    // Centre the agent on its sub-agents when it has no tall tool list.
    const firstAy = col.placed.length === 1 ? col.placed[0].b.ay : col.h / 2;
    const shift = Math.max(0, Math.min(firstAy - AG.h / 2, col.h - selfH));
    for (const it of items) it.y += shift;
    const x0 = selfW + GAP_X;
    for (const { b, x, y } of col.placed) for (const it of b.items) items.push({ ...it, x: it.x + x0 + x, y: it.y + y });
    return { w: x0 + col.w, h: Math.max(selfH + shift, col.h), ay: shift + AG.h / 2, items };
  }

  function groupBlock(node, agents, tools) {
    const items = [];
    const ordered = agents
      .map((a, i) => ({ a, o: orderOf.get(`${node.id}>${a.id}`) ?? i + 1 }))
      .sort((p, q) => p.o - q.o)
      .map((p) => p.a);
    let ranks;
    if (node.kind === 'parallel') ranks = [ordered];
    else if (node.kind === 'workflow') ranks = rankByFlow(node, ordered);
    else ranks = ordered.map((a) => [a]);

    let x = PAD;
    let innerH = 0;
    const cols = [];
    for (const rank of ranks) {
      const blocks = rank.map((a) => ({ a, b: block(a.id) }));
      const cw = Math.max(...blocks.map((p) => p.b.w));
      const ch = blocks.reduce((sum, p) => sum + p.b.h, 0) + GAP_Y * (blocks.length - 1);
      cols.push({ blocks, x, cw, ch });
      innerH = Math.max(innerH, ch);
      x += cw + (node.kind === 'workflow' ? 132 : 88);
    }
    const innerW = x - (node.kind === 'workflow' ? 132 : 88) - PAD;
    const single = cols.every((c) => c.blocks.length === 1);
    const maxAy = single ? Math.max(...cols.map((c) => c.blocks[0].b.ay)) : 0;
    for (const c of cols) {
      let y = HEAD + (single ? maxAy - c.blocks[0].b.ay : (innerH - c.ch) / 2);
      for (const { b } of c.blocks) {
        for (const it of b.items) items.push({ ...it, x: it.x + c.x, y: it.y + y });
        y += b.h + GAP_Y;
      }
    }
    if (single) innerH = Math.max(...cols.map((c) => maxAy - c.blocks[0].b.ay + c.blocks[0].b.h));
    if (node.kind === 'sequential' || node.kind === 'loop') {
      for (let i = 0; i + 1 < ordered.length; i++) synth.push({ from: ordered[i].id, to: ordered[i + 1].id, kind: 'then' });
      if (node.kind === 'loop' && ordered.length) synth.push({ from: ordered[ordered.length - 1].id, to: ordered[0].id, kind: 'again', under: node.id });
    }
    const loopPad = node.kind === 'loop' ? 44 : 0;
    let w = Math.max(innerW + PAD * 2, 260);
    let hgt = HEAD + innerH + PAD + loopPad;
    if (tools.length) {
      const tb = toolItems(tools, PAD - TL.indent, hgt, items);
      hgt += tb.h + PAD;
      w = Math.max(w, tb.w + PAD * 2);
    }
    items.unshift({ id: node.id, type: 'group', x: 0, y: 0, w, h: hgt, ay: single ? HEAD + maxAy : hgt / 2 });
    return { w, h: hgt, ay: single ? HEAD + maxAy : hgt / 2, items };
  }

  function rankByFlow(node, members) {
    const ids = new Set(members.map((m) => m.id));
    const flows = topo.edges.filter((e) => e.kind === 'flow' && ids.has(e.from) && ids.has(e.to) && e.from !== e.to);
    const rank = new Map(members.map((m) => [m.id, 0]));
    for (let pass = 0; pass < members.length; pass++) {
      let moved = false;
      for (const e of flows) {
        if (rank.get(e.to) < rank.get(e.from) + 1 && rank.get(e.from) + 1 < members.length) {
          rank.set(e.to, rank.get(e.from) + 1);
          moved = true;
        }
      }
      if (!moved) break;
    }
    if (!flows.length) return members.map((m) => [m]);
    const out = [];
    for (const m of members) (out[rank.get(m.id)] || (out[rank.get(m.id)] = [])).push(m);
    return out.filter(Boolean);
  }

  // ----- place everything -----
  const boxes = new Map();
  const roots = [];
  if (byId.has(topo.root)) roots.push(topo.root);
  for (const n of topo.nodes) if (!n.parent || !byId.has(n.parent)) if (n.id !== topo.root) roots.push(n.id);

  let y = 0;
  let width = 0;
  const x0 = US.w + GAP_X;
  let userY = 0;
  let first = true;
  for (const r of roots) {
    if (seen.has(r)) continue;
    const b = block(r);
    for (const it of b.items) boxes.set(it.id, { ...it, x: it.x + x0, y: it.y + y });
    if (first) userY = y + b.ay - US.h / 2;
    first = false;
    y += b.h + 70;
    width = Math.max(width, x0 + b.w);
  }
  // Nodes caught in a parent cycle would otherwise vanish: line them up below.
  for (const n of topo.nodes) {
    if (boxes.has(n.id)) continue;
    const tool = TOOLS.has(n.kind);
    boxes.set(n.id, { id: n.id, type: tool ? 'tool' : 'agent', x: x0, y, w: tool ? TL.w : AG.w, h: tool ? TL.h : AG.h });
    y += (tool ? TL.h : AG.h) + 20;
  }
  boxes.set(USER, { id: USER, type: 'user', x: 0, y: Math.max(0, userY), w: US.w, h: US.h });
  const height = Math.max(y - 70, US.h);

  // ----- connectors -----
  const edges = [];
  const drawn = new Set();
  const push = (from, to, kind, extra = {}) => {
    const a = boxes.get(from), b = boxes.get(to);
    if (!a || !b || from === to) return;
    const key = `${from}>${to}`;
    if (drawn.has(key)) return;
    drawn.add(key);
    edges.push({ key, from, to, kind, ...route(a, b, kind, extra, boxes), ...extra });
  };
  if (byId.has(topo.root)) push(USER, topo.root, 'ask');
  for (const e of synth) push(e.from, e.to, e.kind, e.under ? { under: e.under } : {});
  for (const e of topo.edges) {
    if (e.kind === 'then' || e.kind === 'together' || e.kind === 'repeat') {
      const parent = byId.get(e.from);
      if (parent && GROUPS.has(parent.kind)) continue; // the frame already says it
    }
    push(e.from, e.to, e.kind, e.label ? { label: String(e.label) } : {});
  }
  return { boxes, edges, bases: bases.filter((b) => boxes.has(b.id)), width: Math.max(width, x0 + AG.w), height };
}

// A path made of straight runs with small rounded elbows.
function ortho(pts, r = 9) {
  const p = pts.filter((q, i) => !i || q[0] !== pts[i - 1][0] || q[1] !== pts[i - 1][1]);
  let d = `M${p[0][0]} ${p[0][1]}`;
  for (let i = 1; i < p.length - 1; i++) {
    const [ax, ay] = p[i - 1], [cx, cy] = p[i], [bx, by] = p[i + 1];
    const inL = Math.hypot(cx - ax, cy - ay), outL = Math.hypot(bx - cx, by - cy);
    const k = Math.min(r, inL / 2, outL / 2);
    if (k < 0.5) { d += ` L${cx} ${cy}`; continue; }
    d += ` L${cx - ((cx - ax) / inL) * k} ${cy - ((cy - ay) / inL) * k} Q${cx} ${cy} ${cx + ((bx - cx) / outL) * k} ${cy + ((by - cy) / outL) * k}`;
  }
  const e = p[p.length - 1];
  return `${d} L${e[0]} ${e[1]}`;
}

// Connectors are drawn like on an architecture diagram: horizontal and vertical runs only.
// Several connectors leaving the same block share one vertical trunk, and each one carries its label
// on its own last run, so labels never pile up.
function route(a, b, kind, extra, boxes) {
  const acx = a.x + a.w / 2, acy = a.y + a.h / 2, bcx = b.x + b.w / 2, bcy = b.y + b.h / 2;
  // Agent -> its tool chip, first column: a tidy elbow along the left side.
  if (kind === 'uses_tool' && b.type === 'tool' && b.col === 0 && b.y >= a.y + a.h) {
    const x = a.x + 12;
    return { d: ortho([[x, a.y + a.h], [x, bcy], [b.x, bcy]], 8), lx: x, ly: bcy };
  }
  if (extra.under && boxes.get(extra.under)) {
    // Loop "again" arrow: under the members, inside the frame.
    // It goes round the members (out by the right of the last, back in by the left of the first), clear of their tools.
    const g = boxes.get(extra.under);
    const yb = g.y + g.h - 22;
    const xr = a.x + a.w + 13, xl = b.x - 13;
    return { d: ortho([[a.x + a.w, acy], [xr, acy], [xr, yb], [xl, yb], [xl, bcy], [b.x, bcy]], 10), lx: (xr + xl) / 2, ly: yb };
  }
  // A frame is entered on the line its members stand on.
  const anchorY = (box) => (box.type === 'group' ? box.y + (box.ay || box.h / 2) : box.y + box.h / 2);
  if (b.x >= a.x + a.w - 8) {
    const p = [a.x + a.w, anchorY(a)], q = [b.x, anchorY(b)];
    if (Math.abs(p[1] - q[1]) < 1) return { d: ortho([p, q]), lx: (p[0] + q[0]) / 2, ly: p[1] };
    const tx = Math.min(Math.max(a.x + (a.bw || a.w) + TRUNK, p[0] + 16), q[0] - 20);
    return { d: ortho([p, [tx, p[1]], [tx, q[1]], q]), lx: (tx + q[0]) / 2 + 2, ly: q[1] };
  }
  if (b.x + b.w <= a.x + 8) {
    const p = [a.x, anchorY(a)], q = [b.x + b.w, anchorY(b)];
    if (Math.abs(p[1] - q[1]) < 1) return { d: ortho([p, q]), lx: (p[0] + q[0]) / 2, ly: p[1] };
    const tx = Math.max(p[0] - TRUNK, q[0] + 20);
    return { d: ortho([p, [tx, p[1]], [tx, q[1]], q]), lx: (tx + q[0]) / 2 - 2, ly: q[1] };
  }
  const down = bcy >= acy;
  const p = [acx, down ? a.y + a.h : a.y], q = [bcx, down ? b.y : b.y + b.h];
  if (Math.abs(p[0] - q[0]) < 1) return { d: ortho([p, q]), lx: p[0], ly: (p[1] + q[1]) / 2 };
  const my = (p[1] + q[1]) / 2;
  return { d: ortho([p, [p[0], my], [q[0], my], q]), lx: (p[0] + q[0]) / 2, ly: my };
}

// A free path between two boxes, for journeys that have no drawn connector.
export function freePath(a, b) {
  const ax = a.x + a.w / 2, bx = b.x + b.w / 2;
  if (Math.abs(ax - bx) > 260) {
    // Far apart (an answer going back to the person): a calm arc under the map.
    const ay = a.y + a.h, by = b.y + b.h;
    const dip = Math.max(ay, by) + Math.min(220, 70 + Math.abs(ax - bx) * 0.16);
    return `M${ax} ${ay} C${ax} ${dip} ${bx} ${dip} ${bx} ${by}`;
  }
  return route(a, b, 'free', {}, new Map()).d;
}
