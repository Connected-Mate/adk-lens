// Holds everything the hub sent: topologies, versions, runs and their steps.
// Every field of every event is optional and untrusted.

const AGENT_TOOL_KINDS = new Set(['tool', 'toolset']);
export const USER = '@user';

export const store = {
  events: [],
  apps: {},        // app -> topology
  versions: {},    // app -> [{v, ts, hash, topology}]
  extra: {},       // app -> {nodes: [], edges: []} created on the fly from events
  runs: new Map(), // run id -> run
  lastSeq: 0,
  stale: false,    // true when we show an old recording after a hub restart
  hubNotes: null,
};

const str = (v) => (typeof v === 'string' ? v : v === null || v === undefined ? '' : String(v));
const arr = (v) => (Array.isArray(v) ? v : []);
const obj = (v) => (v && typeof v === 'object' && !Array.isArray(v) ? v : {});
// `path` is a list of names, or a string like "wf@1/clean@1".
const pathNames = (p) => (Array.isArray(p) ? p : typeof p === 'string' ? p.split('/') : [])
  .map((x) => str(x).replace(/@\d+$/, '')).filter(Boolean);
const TRANSFER = 'transfer_to_agent';

function cleanTopology(t, app) {
  const raw = obj(t);
  const seen = new Set();
  const nodes = [];
  for (const n of arr(raw.nodes)) {
    if (!n || typeof n !== 'object') continue;
    const id = str(n.id || n.name);
    if (!id || seen.has(id)) continue;
    seen.add(id);
    nodes.push({ ...n, id, name: str(n.name || id), kind: str(n.kind || 'custom'), parent: n.parent ? str(n.parent) : null });
  }
  const edges = [];
  for (const e of arr(raw.edges)) {
    if (!e || typeof e !== 'object') continue;
    const from = str(e.from), to = str(e.to);
    if (!seen.has(from) || !seen.has(to)) continue;
    edges.push({ ...e, from, to, kind: str(e.kind || 'delegate') });
  }
  let root = str(raw.root);
  if (!seen.has(root)) root = (nodes.find((n) => !n.parent && !AGENT_TOOL_KINDS.has(n.kind)) || nodes[0] || {}).id || '';
  return { app, root, nodes, edges };
}

export function resetStore() {
  store.events = [];
  store.apps = {};
  store.versions = {};
  store.extra = {};
  store.runs = new Map();
  store.lastSeq = 0;
  store.stale = false;
}

export function loadState(state) {
  resetStore();
  const st = obj(state);
  applyShapes(st);
  for (const ev of arr(st.events)) ingest(ev, true);
  store.lastSeq = Math.max(store.lastSeq, Number(st.seq) || 0);
  store.hubNotes = st.notes ?? null;
}

// Topologies and versions only (used when a topology event arrives).
export function applyShapes(state) {
  const st = obj(state);
  for (const [app, t] of Object.entries(obj(st.apps))) store.apps[app] = cleanTopology(t, app);
  for (const [app, list] of Object.entries(obj(st.versions))) {
    store.versions[app] = arr(list)
      .filter((v) => v && typeof v === 'object')
      .map((v, i) => ({ v: Number(v.v) || i + 1, ts: Number(v.ts) || 0, seen: Number(v.seen) || 0, current: !!v.current, hash: str(v.hash), topology: cleanTopology(v.topology, app) }));
    // The current version is not always the newest: an app can go back to a shape it already had.
    const cur = Number(obj(st.current)[app]) || 0;
    if (cur) for (const v of store.versions[app]) v.current = v.v === cur;
    if (!store.apps[app] && store.versions[app].length) store.apps[app] = currentVersion(app).topology;
  }
}

export function currentVersion(app) {
  const list = store.versions[app] || [];
  return list.find((v) => v.current) || list[list.length - 1] || null;
}

export function isEmpty() {
  return !Object.keys(store.apps).length && !store.runs.size;
}

// Returns {run, topology} flags so the UI knows what to refresh.
export function ingest(ev, bulk = false) {
  if (!ev || typeof ev !== 'object') return null;
  const seq = Number(ev.seq) || 0;
  if (!bulk && seq && seq <= store.lastSeq) return null; // duplicate after a reconnect
  if (seq > store.lastSeq) store.lastSeq = seq;
  store.events.push(ev);
  const type = str(ev.type);
  const app = str(ev.app) || 'app';

  if (type === 'cleared') {
    store.runs = new Map();
    store.events = [];
    return { cleared: true };
  }
  if (type === 'topology') {
    const topo = cleanTopology(ev, app);
    if (!bulk || !store.apps[app]) store.apps[app] = topo;
    if (!bulk) {
      // Keep a local version list until the hub's own list is fetched again.
      const list = store.versions[app] || (store.versions[app] = []);
      const sig = JSON.stringify([topo.nodes, topo.edges]);
      const now = Number(ev.ts) || Date.now() / 1000;
      // A shape already seen is that version again, not a new one.
      let hit = list.find((v) => (ev.version ? v.v === Number(ev.version) : JSON.stringify([v.topology.nodes, v.topology.edges]) === sig));
      if (!hit) {
        hit = { v: Number(ev.version) || list.reduce((m, v) => Math.max(m, v.v), 0) + 1, ts: now, hash: '', topology: topo };
        list.push(hit);
      }
      hit.seen = now;
      for (const v of list) v.current = v === hit;
    }
    return { topology: app };
  }

  if (!store.apps[app]) store.apps[app] = { app, root: '', nodes: [], edges: [] };
  let runId = str(ev.run);
  if (!runId) {
    // No run id: attach to the latest unfinished run of this app, or open one.
    const live = [...store.runs.values()].reverse().find((r) => r.app === app && r.status === 'live');
    runId = live ? live.id : `${app}:${str(ev.session) || 'run'}:${seq}`;
  }
  let run = store.runs.get(runId);
  if (!run) {
    run = { id: runId, app, session: str(ev.session), events: [], status: 'live', startTs: Number(ev.ts) || 0, userMessage: '', error: '', started: false, steps: null, stepsAt: -1 };
    store.runs.set(runId, run);
  }
  run.events.push(ev);
  run.lastTs = Number(ev.ts) || run.lastTs || 0;
  if (type === 'run_start') {
    run.userMessage = str(ev.user_message) || textOfParts(ev.parts);
    run.startTs = Number(ev.ts) || run.startTs;
    run.status = 'live';
    run.started = true;
    // A session handles one request at a time: an older one still "live" was cut short.
    for (const other of store.runs.values()) {
      if (other !== run && other.app === app && other.session === run.session && other.status === 'live') other.status = 'stalled';
    }
  } else if (type === 'run_end') {
    // `interrupted`: the hub closed the request itself (the agent's process went away, or it was cancelled).
    if (ev.interrupted) run.status = 'interrupted';
    else if (run.status !== 'error') run.status = 'done';
    run.duration = Number(ev.duration_ms) || undefined;
  } else if (type === 'run_error') {
    run.status = 'error';
    run.error = str(ev.error) || str(ev.error_type);
  }
  return { run: runId, app, started: type === 'run_start' };
}

export function textOfParts(parts) {
  return arr(parts)
    .filter((p) => p && p.kind === 'text' && p.text)
    .map((p) => str(p.text))
    .join('\n');
}

export function runsOf(app) {
  return [...store.runs.values()].filter((r) => r.app === app).sort((a, b) => b.startTs - a.startTs || (a.id < b.id ? 1 : -1));
}

// ---------- names -> node ids ----------

function extraOf(app) {
  return store.extra[app] || (store.extra[app] = { nodes: [], edges: [] });
}

function allNodes(app) {
  const topo = store.apps[app];
  return [...(topo ? topo.nodes : []), ...extraOf(app).nodes];
}

export function agentNodeId(app, name, parentName) {
  const n = str(name);
  if (!n) return '';
  const nodes = allNodes(app);
  const hit = nodes.find((x) => x.name === n && !AGENT_TOOL_KINDS.has(x.kind)) || nodes.find((x) => x.id === n && !AGENT_TOOL_KINDS.has(x.kind));
  if (hit) return hit.id;
  const parent = parentName ? agentNodeId(app, parentName) : null;
  const node = { id: n, name: n, kind: 'custom', parent: parent || null, dynamic: true };
  const ex = extraOf(app);
  ex.nodes.push(node);
  if (parent) ex.edges.push({ from: parent, to: n, kind: 'delegate', dynamic: true });
  return n;
}

export function toolNodeId(app, agentName, toolName, isAgentTool) {
  const tool = str(toolName) || 'tool';
  const nodes = allNodes(app);
  if (isAgentTool) {
    const a = nodes.find((x) => x.name === tool && !AGENT_TOOL_KINDS.has(x.kind));
    if (a) return a.id;
  }
  const agentId = agentName ? agentNodeId(app, agentName) : '';
  const id = agentId ? `${agentId}::${tool}` : `::${tool}`;
  if (nodes.some((x) => x.id === id)) return id;
  const ex = extraOf(app);
  ex.nodes.push({ id, name: tool, kind: 'tool', parent: agentId || null, dynamic: true });
  if (agentId) ex.edges.push({ from: agentId, to: id, kind: 'uses_tool', dynamic: true });
  return id;
}

// A topology plus the nodes discovered while running.
export function withExtras(app, topo) {
  const base = topo || store.apps[app] || { app, root: '', nodes: [], edges: [] };
  const ex = extraOf(app);
  if (!ex.nodes.length) return base;
  const ids = new Set(base.nodes.map((n) => n.id));
  const nodes = [...base.nodes];
  for (const n of ex.nodes) {
    if (ids.has(n.id)) continue;
    ids.add(n.id);
    nodes.push(n.parent && !ids.has(n.parent) ? { ...n, parent: null } : n);
  }
  const edges = [...base.edges];
  for (const e of ex.edges) {
    if (ids.has(e.from) && ids.has(e.to) && !edges.some((b) => b.from === e.from && b.to === e.to)) edges.push(e);
  }
  return { ...base, root: base.root || (nodes[0] ? nodes[0].id : ''), nodes, edges };
}

// ---------- events -> steps (what the player walks through) ----------

export function stepsOf(run) {
  if (!run) return [];
  if (run.steps && run.stepsAt === run.events.length) return run.steps;
  run.steps = buildSteps(run);
  run.stepsAt = run.events.length;
  return run.steps;
}

function buildSteps(run) {
  const app = run.app;
  const steps = [];
  const stack = [];
  const topo = store.apps[app];
  let lastHandoffTo = '';
  const lastChild = new Map();
  const add = (ev, kind, extra) => {
    const n = steps.filter((x) => x.seq === ev.seq).length;
    steps.push({ id: `${ev.seq ?? steps.length}:${n}`, seq: ev.seq, ts: Number(ev.ts) || 0, kind, ev, ...extra });
  };
  // A failure usually arrives three times in a row (the tool, then its agent, then the request).
  // Keep one step, at the place where it first broke; the rest stays available as details.
  const fail = (ev, extra) => {
    const prev = steps[steps.length - 1];
    if (prev && prev.kind === 'error') {
      prev.chain.push({ ev, ...extra });
      if (extra.what === 'run') prev.fatal = true;
      return;
    }
    add(ev, 'error', { ...extra, fatal: extra.what === 'run', chain: [{ ev, ...extra }] });
  };

  for (const ev of run.events) {
    const type = str(ev.type);
    const agentName = str(ev.agent);
    const top = stack[stack.length - 1] || '';
    switch (type) {
      case 'run_start': {
        const rootName = str(ev.root_agent) || (topo && topo.nodes.find((n) => n.id === topo.root) || {}).name || '';
        const root = rootName ? agentNodeId(app, rootName) : '';
        add(ev, 'ask', { node: root || USER, from: USER, to: root || null, text: str(ev.user_message) || textOfParts(ev.parts) });
        break;
      }
      case 'agent_start': {
        const path = pathNames(ev.path);
        const parentName = path.length > 1 && path[path.length - 1] === agentName ? path[path.length - 2] : top;
        const id = agentNodeId(app, agentName, parentName && parentName !== agentName ? parentName : '');
        const prev = steps[steps.length - 1];
        const viaHandoff = lastHandoffTo === agentName;
        if (!(prev && prev.to === id) && !viaHandoff) {
          let from = parentName && parentName !== agentName ? agentNodeId(app, parentName) : null;
          const pk = from ? (allNodes(app).find((x) => x.id === from) || {}).kind : '';
          if (pk === 'sequential' || pk === 'loop') {
            // Inside a "one after the other" group, the work comes from the previous member.
            const before = lastChild.get(from);
            lastChild.set(from, id);
            from = before && before !== id ? before : null;
          } else if (pk === 'parallel' || pk === 'workflow') from = null;
          add(ev, 'agent', { node: id, from, to: from ? id : null, agent: agentName });
        }
        stack.push(agentName);
        lastHandoffTo = '';
        break;
      }
      case 'agent_end': {
        const i = stack.lastIndexOf(agentName);
        if (i >= 0) stack.splice(i, 1);
        break;
      }
      case 'model_start':
        add(ev, 'think', { node: agentNodeId(app, agentName || top), agent: agentName || top });
        break;
      case 'model_end': {
        const calls = arr(ev.calls).filter((c) => c && typeof c === 'object');
        const fromParts = arr(ev.parts).filter((p) => p && p.kind === 'call');
        add(ev, 'thought', {
          node: agentNodeId(app, agentName || top), agent: agentName || top,
          calls: (calls.length ? calls : fromParts).map((c) => str(c.name)).filter((n) => n && n !== TRANSFER),
          transfers: (calls.length ? calls : fromParts).some((c) => str(c.name) === TRANSFER),
          text: str(ev.text) || textOfParts(ev.parts),
        });
        break;
      }
      case 'model_error':
        fail(ev, { node: agentNodeId(app, agentName || top), agent: agentName || top, what: 'model', text: str(ev.error) || str(ev.error_type) });
        break;
      case 'tool_start': {
        if (str(ev.tool) === TRANSFER) break;
        const a = agentNodeId(app, agentName || top);
        const tid = toolNodeId(app, agentName || top, ev.tool, !!ev.agent_tool);
        add(ev, 'tool', { node: tid, from: a, to: tid, agent: agentName || top, tool: str(ev.tool), agentTool: !!ev.agent_tool });
        break;
      }
      case 'tool_end': {
        if (str(ev.tool) === TRANSFER) break;
        const a = agentNodeId(app, agentName || top);
        const tid = toolNodeId(app, agentName || top, ev.tool, false);
        const real = steps.slice().reverse().find((x) => x.kind === 'tool' && x.ev.call_id === ev.call_id && ev.call_id);
        add(ev, 'tool_result', { node: a, from: real ? real.node : tid, to: a, toolNode: real ? real.node : tid, agent: agentName || top, tool: str(ev.tool), agentTool: !!(real && real.agentTool) });
        break;
      }
      case 'tool_error': {
        if (str(ev.tool) === TRANSFER && !ev.error) break;
        const real = steps.slice().reverse().find((x) => x.kind === 'tool' && x.ev.call_id === ev.call_id && ev.call_id);
        const tid = real ? real.node : toolNodeId(app, agentName || top, ev.tool, false);
        fail(ev, { node: tid, agent: agentName || top, tool: str(ev.tool), what: 'tool', text: str(ev.error) || str(ev.error_type) });
        break;
      }
      case 'event': {
        if (ev.partial) break;
        const author = str(ev.author);
        if (author === 'user') break;
        const path = pathNames(ev.path);
        const worker = path[path.length - 1] || '';
        const hasOutput = ev.output !== undefined && ev.output !== null && ev.output !== '';
        // Workflow steps have no agent_start: the path says who just worked.
        const who = hasOutput && worker ? worker : author || worker || top;
        const a = agentNodeId(app, who, hasOutput && path.length > 1 ? path[path.length - 2] : '');
        if (hasOutput) add(ev, 'output', { node: a, agent: who, output: ev.output });
        const delta = obj(ev.state_delta);
        const keys = Object.keys(delta);
        if (keys.length) add(ev, 'memory', { node: a, agent: author || top, keys, delta });
        const files = arr(ev.artifacts).map(str).filter(Boolean);
        if (files.length) add(ev, 'file', { node: a, agent: author || top, files });
        if (ev.transfer_to) {
          const target = agentNodeId(app, str(ev.transfer_to), author || top);
          add(ev, 'handoff', { node: target, from: a, to: target, agent: author || top, target: str(ev.transfer_to) });
          lastHandoffTo = str(ev.transfer_to);
          const gone = stack.lastIndexOf(author);
          if (gone >= 0) stack.splice(gone, 1); // the agent that hands over often gets no agent_end
        }
        if (ev.escalate) add(ev, 'escalate', { node: a, agent: author || top });
        const text = str(ev.text) || textOfParts(ev.parts);
        // An answer needs words. Without content recording (no text, no parts at all) it is still shown;
        // an empty final event, as ADK sends when a request breaks, is not an answer.
        const unrecorded = ev.text === undefined && ev.parts === undefined;
        if (ev.final && (text || unrecorded) && !ev.error && !ev.transfer_to) {
          add(ev, 'answer', { node: USER, from: a, to: USER, agent: author || top, text });
        }
        break;
      }
      case 'agent_error':
        fail(ev, { node: agentNodeId(app, agentName || top), agent: agentName || top, what: 'agent', text: str(ev.error) || str(ev.error_type) });
        break;
      case 'run_end':
        add(ev, 'done', { node: USER, interrupted: !!ev.interrupted });
        break;
      case 'run_error': {
        const prev = steps[steps.length - 1];
        const where = prev && prev.kind === 'error' ? prev.node : (steps.slice().reverse().find((x) => x.node && x.node !== USER) || {}).node || USER;
        fail(ev, { node: where, what: 'run', text: str(ev.error) || str(ev.error_type) });
        break;
      }
      default:
        break;
    }
  }
  return steps;
}

// What the map looks like at step `idx` of a run.
export function frameAt(run, idx) {
  const steps = stepsOf(run);
  const frame = { active: null, travel: null, visited: new Set(), edges: new Set(), errors: new Map(), kind: null, step: null };
  if (!steps.length || idx < 0) return frame;
  const last = Math.min(idx, steps.length - 1);
  for (let i = 0; i <= last; i++) {
    const st = steps[i];
    if (st.node) frame.visited.add(st.node);
    if (st.from) frame.visited.add(st.from);
    if (st.from && st.to) frame.edges.add(`${st.from}>${st.to}`);
    if (st.kind === 'error' && st.node) frame.errors.set(st.node, st.text || '');
  }
  const cur = steps[last];
  frame.step = cur;
  frame.kind = cur.kind;
  frame.active = cur.node || null;
  if (cur.from && cur.to) frame.travel = { from: cur.from, to: cur.to };
  return frame;
}

// What one node did during a run.
export function nodeActivity(run, nodeId) {
  const steps = stepsOf(run);
  const mine = [];
  const sum = { thinks: 0, tokensIn: 0, tokensOut: 0, ms: 0, uses: 0, errors: 0 };
  steps.forEach((st, i) => {
    const touches = st.node === nodeId || st.from === nodeId || st.to === nodeId || st.toolNode === nodeId;
    if (!touches) return;
    mine.push({ i, step: st });
    if (st.kind === 'thought' && st.node === nodeId) {
      sum.thinks += 1;
      sum.tokensIn += Number(st.ev.tokens_in) || 0;
      sum.tokensOut += Number(st.ev.tokens_out) || 0;
      sum.ms += Number(st.ev.duration_ms) || 0;
    }
    if (st.kind === 'tool' && st.node === nodeId) sum.uses += 1;
    if (st.kind === 'tool_result' && st.toolNode === nodeId) sum.ms += Number(st.ev.duration_ms) || 0;
    if (st.kind === 'error' && st.node === nodeId) sum.errors += 1;
  });
  for (const ev of run.events) {
    if (ev.type === 'agent_end' && agentNodeIdQuiet(run.app, ev.agent) === nodeId) sum.total = Number(ev.duration_ms) || sum.total;
  }
  return { steps: mine, sum };
}

function agentNodeIdQuiet(app, name) {
  const n = str(name);
  const hit = allNodes(app).find((x) => x.name === n && !AGENT_TOOL_KINDS.has(x.kind));
  return hit ? hit.id : '';
}

// ---------- versions ----------

export function diffTopologies(a, b) {
  const res = { nodes: new Map(), edges: new Map(), list: [] };
  const an = new Map((a ? a.nodes : []).map((n) => [n.id, n]));
  const bn = new Map((b ? b.nodes : []).map((n) => [n.id, n]));
  const toolsOf = (t, id) => (t ? t.nodes : []).filter((n) => n.parent === id && AGENT_TOOL_KINDS.has(n.kind)).map((n) => n.name).sort().join('|');
  for (const [id, n] of bn) {
    const old = an.get(id);
    if (!old) {
      res.nodes.set(id, 'added');
      res.list.push({ status: 'added', node: n });
      continue;
    }
    const fields = [];
    for (const f of ['instruction', 'model', 'description']) if (str(old[f]) !== str(n[f])) fields.push(f);
    if (old.kind !== n.kind) fields.push('kind');
    if (toolsOf(a, id) !== toolsOf(b, id)) fields.push('tools');
    if (fields.length) {
      res.nodes.set(id, 'changed');
      res.list.push({ status: 'changed', node: n, old, fields });
    }
  }
  for (const [id, n] of an) {
    if (!bn.has(id)) {
      res.nodes.set(id, 'removed');
      res.list.push({ status: 'removed', node: n });
    }
  }
  const key = (e) => `${e.from}>${e.to}`;
  const ae = new Map((a ? a.edges : []).map((e) => [key(e), e]));
  const be = new Map((b ? b.edges : []).map((e) => [key(e), e]));
  for (const [k, e] of be) {
    if (!ae.has(k)) res.edges.set(k, 'added');
    else if (ae.get(k).kind !== e.kind || ae.get(k).order !== e.order) res.edges.set(k, 'changed');
  }
  for (const k of ae.keys()) if (!be.has(k)) res.edges.set(k, 'removed');
  return res;
}

// Both versions drawn on one board: everything from b, plus what a had and b lost.
export function unionTopology(a, b) {
  const ids = new Set(b.nodes.map((n) => n.id));
  const nodes = [...b.nodes];
  for (const n of a.nodes) {
    if (ids.has(n.id)) continue;
    ids.add(n.id);
    nodes.push(n);
  }
  const fixed = nodes.map((n) => (n.parent && !ids.has(n.parent) ? { ...n, parent: null } : n));
  const keys = new Set(b.edges.map((e) => `${e.from}>${e.to}`));
  const edges = [...b.edges];
  for (const e of a.edges) if (!keys.has(`${e.from}>${e.to}`) && ids.has(e.from) && ids.has(e.to)) edges.push(e);
  return { app: b.app, root: b.root || a.root, nodes: fixed, edges };
}
