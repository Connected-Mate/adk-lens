// ADK Lens: wiring of the whole page.
import { h, clear, clipped, short, fmtDuration, lsGet, lsSet, reducedMotion, put } from './dom.js';
import { icon } from './icons.js';
import { initLang, setLang, getLang, t, tn } from './i18n.js';
import {
  store, loadState, applyShapes, ingest, isEmpty, resetStore, runsOf, stepsOf, frameAt, nodeActivity,
  withExtras, diffTopologies, unionTopology, USER,
} from './store.js';
import { createMap } from './map.js';
import { createStory, sentence, sentenceText } from './story.js';
import { createNotes, STAMPS } from './notes.js';
import { buildPrompt, copyText } from './prompt.js';

const params = new URLSearchParams(location.search);
const HEAD = { 'X-ADK-Lens': '1', 'Content-Type': 'application/json' };
const SPEEDS = [0.5, 1, 2, 4];
const TOOLS = new Set(['tool', 'toolset']);

const ui = {
  app: null, runId: null, idx: 0, playing: false, speed: 1, follow: true,
  view: lsGet('adk-lens.view') === 'linear' ? 'linear' : 'journey',
  version: null, compare: null, panel: null, conn: 'connecting', fixture: false, theme: lsGet('adk-lens.theme') || 'auto',
};
const el = {};
let map, story, notes;
let playTimer = 0;
let mapKey = '';
let pop = null;
let es = null;
let retryT = 0;
let refreshRaf = 0;
let toastT = 0;
let notesLocalOnly = false;

// ---------------------------------------------------------------- shell

function btn(cls, label, kids, onClick, extra = {}) {
  const b = h('button', { class: cls, type: 'button', 'aria-label': label, title: extra.noTitle ? null : label, ...extra.attrs }, kids);
  if (onClick) b.addEventListener('click', onClick);
  return b;
}

function logo() {
  // Original mark: a small lens looking at three connected dots.
  const NS = 'http://www.w3.org/2000/svg';
  const svg = document.createElementNS(NS, 'svg');
  svg.setAttribute('viewBox', '0 0 32 32');
  svg.setAttribute('class', 'logo');
  svg.setAttribute('aria-hidden', 'true');
  const mk = (tag, attrs) => {
    const n = document.createElementNS(NS, tag);
    for (const [k, v] of Object.entries(attrs)) n.setAttribute(k, v);
    put(svg, n);
  };
  mk('circle', { cx: 14, cy: 14, r: 9.5, class: 'logo-ring' });
  mk('path', { d: 'M21 21l6.500 6.500', class: 'logo-handle' });
  mk('circle', { cx: 10.500, cy: 15.500, r: 2, class: 'logo-dot d1' });
  mk('circle', { cx: 14.500, cy: 10.500, r: 2, class: 'logo-dot d2' });
  mk('circle', { cx: 18, cy: 16, r: 2, class: 'logo-dot d3' });
  return svg;
}

function buildShell() {
  const root = document.getElementById('app');
  clear(root);
  el.appBtn = btn('chip-btn app-btn', t('top.apps'), [], (e) => openApps(e.currentTarget), { noTitle: true });
  el.verBtn = btn('chip-btn ver-btn', t('top.versions'), [], (e) => openVersions(e.currentTarget), { noTitle: true });
  el.tabs = h('div', { class: 'seg', role: 'group', 'aria-label': t('view.label') },
    ...['journey', 'linear'].map((v) => {
      const b = btn('seg-btn', t(`view.${v}.hint`), [icon(v === 'journey' ? 'map' : 'story', 17), h('span', { text: t(`view.${v}`) })], () => setView(v), { noTitle: true });
      b.dataset.view = v;
      return b;
    }));
  el.runsBtn = btn('chip-btn runs-btn', t('top.runs'), [], (e) => openRuns(e.currentTarget), { noTitle: true });
  el.copyBtn = btn('primary-btn copy-btn', t('top.copy'), [], () => copyPrompt(), { noTitle: true });
  el.moreBtn = btn('icon-btn', t('top.more'), [icon('more', 20)], (e) => openMore(e.currentTarget));
  el.top = h('header', { class: 'top' },
    h('div', { class: 'top-left' }, h('div', { class: 'brand' }, logo(), h('span', { class: 'brand-name', text: t('app.title') })), el.appBtn, el.verBtn),
    el.tabs,
    h('div', { class: 'top-right' }, el.runsBtn, el.copyBtn, el.moreBtn));

  el.banner = h('div', { class: 'banner', role: 'status', 'aria-live': 'polite', hidden: true });
  el.stage = h('section', { class: 'stage', id: 'board', tabindex: '-1', 'aria-label': t('view.journey.hint') });
  el.story = h('section', { class: 'story', id: 'story', hidden: true, tabindex: '-1', 'aria-label': t('view.linear.hint') });
  el.empty = h('div', { class: 'empty', hidden: true });
  el.hint = h('div', { class: 'tool-hint', role: 'status', 'aria-live': 'polite', hidden: true });

  // Annotation tools.
  el.palette = h('div', { class: 'palette', role: 'toolbar', 'aria-label': t('tools.label'), 'aria-orientation': 'vertical' });
  const tool = (id, label, face) => {
    const b = btn('tool-btn', label, [face], (e) => {
      if (id !== 'select' && e.detail === 0) notes.placeAtCenter(id); // keyboard: drop it in the middle
      else notes.setTool(notes.tool() === id ? 'select' : id);
    });
    b.dataset.tool = id;
    b.setAttribute('aria-pressed', 'false');
    return b;
  };
  put(el.palette, 
    tool('select', t('tools.select'), icon('cursor', 20)),
    tool('sticky', t('tools.sticky'), icon('note', 20)),
    tool('ellipse', t('tools.ellipse'), icon('ellipse', 20)),
    tool('lasso', t('tools.lasso'), icon('lasso', 20)),
    h('span', { class: 'palette-sep', 'aria-hidden': 'true' }),
    ...Object.keys(STAMPS).map((sId) => tool(`stamp:${sId}`, t(`tools.stamp.${sId}`), h('span', { class: `stamp-face stamp-${sId} mini`, text: STAMPS[sId] }))));

  el.zoom = h('div', { class: 'zoom', role: 'group', 'aria-label': t('zoom.fit') },
    btn('icon-btn', t('zoom.out'), [icon('minus', 18)], () => map.zoomBy(1 / 1.25)),
    btn('icon-btn', t('zoom.fit'), [icon('fit', 18)], () => map.fit()),
    btn('icon-btn', t('zoom.in'), [icon('plus', 18)], () => map.zoomBy(1.25)));

  // Player.
  el.caption = h('div', { class: 'caption', 'aria-live': 'polite' });
  el.prev = btn('icon-btn', t('player.prev'), [icon('prev', 20)], () => step(-1));
  el.play = btn('play-btn', t('player.play'), [icon('play', 22)], () => togglePlay());
  el.next = btn('icon-btn', t('player.next'), [icon('next', 20)], () => step(1));
  el.scrub = h('input', { class: 'scrub', type: 'range', min: '0', max: '0', step: '1', value: '0', 'aria-label': t('player.scrub') });
  el.scrub.addEventListener('input', () => {
    pause();
    ui.follow = false;
    setIdx(Number(el.scrub.value), { animate: false });
  });
  el.count = h('span', { class: 'count', 'aria-hidden': 'true' });
  el.speed = btn('speed-btn', '', [], () => {
    ui.speed = SPEEDS[(SPEEDS.indexOf(ui.speed) + 1) % SPEEDS.length];
    renderPlayer();
    schedule();
  }, { noTitle: true });
  el.liveBtn = btn('live-btn', t('player.live'), [h('span', { class: 'live-dot' }), h('span', { text: t('player.live') })], () => followLive(), { noTitle: true });
  el.player = h('div', { class: 'player', role: 'group', 'aria-label': t('player.label') }, el.prev, el.play, el.next, el.scrub, el.count, el.speed, el.liveBtn);
  el.dock = h('div', { class: 'dock', hidden: true }, el.caption, el.player);

  el.panel = h('aside', { class: 'panel', hidden: true, tabindex: '-1' });
  el.toast = h('div', { class: 'toast', role: 'status', 'aria-live': 'polite' });
  el.wave = h('div', { class: 'wave', 'aria-hidden': 'true' });

  el.main = h('main', { class: 'main' }, el.stage, el.story, el.empty, el.palette, el.zoom, el.hint, el.dock, el.panel);
  put(root, h('a', { class: 'skip', href: '#board', text: t('app.skip') }), el.wave, el.top, el.banner, el.main, el.toast);

  map = createMap(el.stage, {
    canPan: () => notes.tool() === 'select',
    inset: () => (ui.panel ? 384 : 0),
    onNode: (id) => openNode(id),
    onBackground: () => { if (!notes.deselect() && ui.panel && ui.panel.type === 'node') closePanel(); },
  });
  notes = createNotes(map, el.stage, {
    getApp: () => ui.app,
    onChange: () => { renderTop(); refreshNotesViews(); },
    onTool: (tool) => {
      for (const b of el.palette.querySelectorAll('.tool-btn')) b.setAttribute('aria-pressed', String(b.dataset.tool === tool));
      const key = tool === 'select' ? '' : tool.startsWith('stamp:') ? 'tools.hint.stamp' : `tools.hint.${tool}`;
      el.hint.hidden = !key;
      el.hint.textContent = key ? t(key) : '';
    },
    buildPrompt: () => promptText(),
    push: (doc) => {
      if (ui.fixture) return;
      fetch('/api/notes', { method: 'PUT', headers: HEAD, body: JSON.stringify(doc) })
        .then((r) => { if (!r.ok) throw new Error('refused'); notesLocalOnly = false; })
        .catch(() => {
          if (!notesLocalOnly) toast(t('note.saved.local'));
          notesLocalOnly = true;
        });
    },
  });
  notes.setTool('select');
  map.onView((v) => map.notesHtml.style.setProperty('--inv', String(Math.min(2.6, Math.max(0.85, 1 / v.k)))));
  story = createStory(el.story, {
    onStep: (i) => { pause(); ui.follow = false; setIdx(i); },
    onComment: (st) => {
      const run = currentRun();
      if (!run) return;
      const sn = sentence(st);
      const item = notes.addStepComment(run, st, { runTitle: short(run.userMessage, 120), sentence: sentenceText(st), content: short(sn.body || '', 500) });
      const field = el.story.querySelector(`[data-note="${CSS.escape(item.id)}"] textarea`);
      if (field) field.focus();
    },
    fillNotes: (container, runId, st) => notes.fillStepNotes(container, runId, st),
  });
}

// ---------------------------------------------------------------- helpers

const currentRun = () => (ui.runId ? store.runs.get(ui.runId) : null);
const versionsOf = (app) => store.versions[app] || [];
const latestVersion = (app) => { const l = versionsOf(app); return l.length ? l[l.length - 1] : null; };

function shownVersion() {
  const list = versionsOf(ui.app);
  if (!list.length) return null;
  if (ui.version !== null) return list.find((v) => v.v === ui.version) || list[list.length - 1];
  const run = currentRun();
  if (run && run.startTs) {
    const before = list.filter((v) => v.ts && v.ts <= run.startTs + 0.5);
    if (before.length) return before[before.length - 1];
  }
  return list[list.length - 1];
}

function shownTopology() {
  const ver = shownVersion();
  const base = ver ? ver.topology : store.apps[ui.app];
  return withExtras(ui.app, base);
}

function toast(text) {
  el.toast.textContent = text;
  el.toast.classList.add('is-on');
  clearTimeout(toastT);
  toastT = setTimeout(() => el.toast.classList.remove('is-on'), 2600);
}

function ago(ts) {
  if (!ts) return '';
  const sec = Math.max(0, Date.now() / 1000 - ts);
  if (sec < 60) return t('runs.ago.now');
  if (sec < 3600) return t('runs.ago.min', { n: Math.floor(sec / 60) });
  if (sec < 86400) return t('runs.ago.h', { n: Math.floor(sec / 3600) });
  return t('runs.ago.d', { n: Math.floor(sec / 86400) });
}

function promptText() {
  if (!ui.app) return '';
  const ver = shownVersion();
  return buildPrompt({ app: ui.app, topo: shownTopology(), version: ver ? ver.v : 1, items: notes.all(), boxes: map.boxes(), notes });
}

// ---------------------------------------------------------------- rendering

function renderAll(o = {}) {
  const apps = Object.keys(store.apps);
  if (!ui.app || !store.apps[ui.app]) {
    ui.app = apps[0] || null;
    const latest = [...store.runs.values()].sort((a, b) => b.startTs - a.startTs)[0];
    if (latest && store.apps[latest.app]) ui.app = latest.app;
    ui.runId = null;
  }
  if (ui.runId && !store.runs.has(ui.runId)) { ui.runId = null; ui.idx = 0; }
  const emptyState = isEmpty();
  document.body.classList.toggle('is-empty', emptyState);
  renderEmpty(emptyState);
  renderTop();
  renderBanner();
  drawMap(o.refit);
  renderRun({ instant: true });
  notes.render();
  renderPanel();
}

function renderEmpty(show) {
  el.empty.hidden = !show;
  if (!show) { clear(el.empty); return; }
  if (el.empty.firstChild && el.empty.dataset.lang === getLang()) return;
  el.empty.dataset.lang = getLang();
  clear(el.empty);
  const cmd = (text) => {
    const b = btn('cmd', `${t('empty.copy')}: ${text}`, [h('code', { text }), icon('copy', 15)], async () => {
      toast((await copyText(text)) ? t('prompt.copied') : text);
    }, { noTitle: true });
    return b;
  };
  const card = (n, cls, title, body, command) => h('li', { class: `how ${cls}`, style: { '--i': String(n) } },
    h('span', { class: 'how-n', 'aria-hidden': 'true', text: String(n) }), h('h3', { text: title }), h('p', { text: body }), command ? cmd(command) : null);
  put(el.empty, 
    h('h1', { class: 'empty-title', text: t('empty.title') }),
    h('p', { class: 'empty-lead', text: t('empty.lead') }),
    h('ol', { class: 'how-list' },
      card(1, 'kind-comment', t('empty.s1.t'), t('empty.s1.b'), 'adk-lens demo'),
      card(2, 'kind-question', t('empty.s2.t'), t('empty.s2.b'), 'adk-lens web'),
      card(3, 'kind-idea', t('empty.s3.t'), t('empty.s3.b'))),
    h('p', { class: 'empty-wait' }, h('span', { class: 'live-dot' }), h('span', { text: t('empty.wait') })));
}

function renderTop() {
  const apps = Object.keys(store.apps);
  clear(el.appBtn);
  el.appBtn.hidden = !ui.app;
  if (ui.app) {
    put(el.appBtn, h('span', { class: 'chip-label', text: short(ui.app, 28) }), apps.length > 1 ? icon('chevron', 16) : null);
    el.appBtn.disabled = apps.length < 2;
    el.appBtn.setAttribute('aria-label', `${t('top.app')}: ${ui.app}${apps.length > 1 ? `. ${t('top.apps')}` : ''}`);
  }
  const vers = versionsOf(ui.app);
  const ver = shownVersion();
  clear(el.verBtn);
  el.verBtn.hidden = vers.length < 2;
  if (ver) put(el.verBtn, icon('layers', 16), h('span', { class: 'chip-label', text: `v${ver.v}` }));
  el.verBtn.classList.toggle('is-old', !!ver && ver !== latestVersion(ui.app));
  if (ver) el.verBtn.setAttribute('aria-label', `${t('top.version', { v: ver.v })}. ${t('top.versions')}`);

  for (const b of el.tabs.children) b.setAttribute('aria-pressed', String(b.dataset.view === ui.view));
  el.tabs.hidden = !ui.app;

  const runs = ui.app ? runsOf(ui.app) : [];
  const live = runs.some((r) => r.status === 'live');
  clear(el.runsBtn);
  el.runsBtn.hidden = !ui.app;
  put(el.runsBtn, live ? h('span', { class: 'live-dot' }) : icon('list', 17), h('span', { class: 'chip-label', text: t('top.runs') }), runs.length ? h('span', { class: 'chip-count', text: String(runs.length) }) : null);

  const n = ui.app ? notes.forApp(ui.app).length : 0;
  clear(el.copyBtn);
  el.copyBtn.hidden = !ui.app;
  put(el.copyBtn, icon('copy', 17), h('span', { class: 'copy-long', text: t('top.copy') }), h('span', { class: 'copy-short', text: t('top.copy.short') }), n ? h('span', { class: 'chip-count', text: String(n) }) : null);
  el.palette.hidden = !ui.app || ui.view !== 'journey';
  el.zoom.hidden = !ui.app || ui.view !== 'journey';
}

function renderBanner() {
  clear(el.banner);
  const ver = shownVersion();
  const latest = latestVersion(ui.app);
  let show = true;
  if (ui.conn === 'lost') {
    el.banner.dataset.tone = 'warn';
    put(el.banner, icon('warn', 17), h('span', { text: t('conn.lost') }), h('span', { class: 'banner-sub', text: t('conn.retry') }));
  } else if (ui.compare !== null && ver) {
    el.banner.dataset.tone = 'info';
    put(el.banner, icon('layers', 17), h('span', { text: t('diff.title', { a: ui.compare, b: ver.v }) }),
      btn('linkish', t('versions.compare.off'), [t('versions.compare.off')], () => stopCompare(), { noTitle: true }));
  } else if (ver && latest && ver !== latest && ui.version !== null) {
    el.banner.dataset.tone = 'info';
    put(el.banner, icon('layers', 17), h('span', { text: t('versions.viewing', { v: ver.v }) }),
      btn('linkish', t('versions.back'), [t('versions.back')], () => { ui.version = null; renderAll(); }, { noTitle: true }));
  } else if (ui.fixture && !isEmpty() && ui.view === 'journey') {
    el.banner.dataset.tone = 'quiet';
    put(el.banner, h('span', { text: t('conn.fixture') }));
  } else show = false;
  el.banner.hidden = !show;
}

function drawMap(refit) {
  if (!ui.app || !store.apps[ui.app]) return;
  const ver = shownVersion();
  const extraN = (store.extra[ui.app] || { nodes: [] }).nodes.length;
  const key = [ui.app, ver ? ver.v : 0, ui.compare, extraN, getLang(), store.apps[ui.app].nodes.length, ver ? ver.hash : ''].join('|');
  if (key === mapKey && !refit) return;
  const appChanged = mapKey.split('|')[0] !== ui.app;
  mapKey = key;
  let topo = shownTopology();
  let diff = null;
  if (ui.compare !== null && ver) {
    const base = versionsOf(ui.app).find((v) => v.v === ui.compare);
    if (base) {
      diff = diffTopologies(base.topology, ver.topology);
      topo = unionTopology(base.topology, ver.topology);
    }
  }
  map.setTopology(topo, { diff, refit: refit || appChanged });
  if (appChanged) map.fit();
  notes.render();
}

function renderRun(o = {}) {
  drawMap();
  const run = currentRun();
  const steps = run ? stepsOf(run) : [];
  if (run) ui.idx = Math.max(0, Math.min(ui.idx, steps.length - 1));
  const comparing = ui.compare !== null;
  const frame = run && !comparing ? frameAt(run, ui.idx) : frameAt(null, -1);
  map.setFrame(frame, { animate: o.animate !== false && ui.view === 'journey', duration: Math.min(900, 720 / ui.speed), follow: ui.view === 'journey' });
  el.story.hidden = ui.view !== 'linear' || !ui.app;
  el.dock.classList.toggle('in-story', ui.view === 'linear');
  story.update(run, ui.idx, { instant: o.instant, notes: o.notes, force: o.force });
  renderPlayer();
  el.stage.classList.toggle('is-behind', ui.view !== 'journey');
  el.stage.inert = ui.view !== 'journey';
}

function renderPlayer() {
  const run = currentRun();
  const steps = run ? stepsOf(run) : [];
  const runs = ui.app ? runsOf(ui.app) : [];
  el.dock.hidden = !ui.app || ui.compare !== null;
  el.dock.classList.toggle('no-run', !run);
  clear(el.caption);
  if (!run) {
    if (ui.app) put(el.caption, h('span', { class: 'cap-line', text: runs.length ? t('story.empty') : t('norun.title') }), h('span', { class: 'cap-body', text: runs.length ? '' : t('norun.body', { app: ui.app }) }));
    return;
  }
  const st = steps[ui.idx];
  if (st) {
    const sn = sentence(st);
    el.caption.dataset.tone = st.kind;
    put(el.caption, h('span', { class: 'cap-line' }, tn(sn.key, sn.vars)), sn.body ? h('span', { class: 'cap-body', text: short(sn.body, 220) }) : null);
  }
  const atEnd = ui.idx >= steps.length - 1;
  const waiting = ui.playing && atEnd && run.status === 'live';
  clear(el.play);
  put(el.play, icon(ui.playing ? 'pause' : 'play', 22));
  const playLabel = ui.playing ? t('player.pause') : atEnd && run.status !== 'live' ? t('player.replay') : t('player.play');
  el.play.setAttribute('aria-label', playLabel);
  el.play.title = playLabel;
  el.play.classList.toggle('is-waiting', waiting);
  el.prev.disabled = ui.idx <= 0;
  el.next.disabled = atEnd;
  el.scrub.max = String(Math.max(0, steps.length - 1));
  el.scrub.value = String(ui.idx);
  el.scrub.style.setProperty('--p', steps.length > 1 ? `${(ui.idx / (steps.length - 1)) * 100}%` : '100%');
  el.scrub.setAttribute('aria-valuetext', st ? `${t('story.step', { i: ui.idx + 1 })}: ${sentenceText(st)}` : '');
  el.count.textContent = t('player.count', { i: steps.length ? ui.idx + 1 : 0, n: steps.length });
  el.speed.textContent = `${ui.speed}×`;
  el.speed.setAttribute('aria-label', t('player.speed', { s: ui.speed }));
  const liveRun = runs.find((r) => r.status === 'live');
  el.liveBtn.hidden = ui.follow || !(liveRun || (runs[0] && runs[0].id !== ui.runId));
  el.player.classList.toggle('is-live', run.status === 'live');
}

function refreshNotesViews() {
  const run = currentRun();
  if (ui.view === 'linear') story.update(run, ui.idx, { notes: true, scroll: false });
  if (ui.panel && ui.panel.type === 'prompt') refreshPromptPanel();
  if (ui.panel && ui.panel.type === 'node') refreshNodeComments();
}

// ---------------------------------------------------------------- player

function setIdx(i, o = {}) {
  const run = currentRun();
  if (!run) return;
  const steps = stepsOf(run);
  ui.idx = Math.max(0, Math.min(i, steps.length - 1));
  renderRun(o);
  if (ui.panel && ui.panel.type === 'node') renderPanel();
}

function schedule() {
  clearTimeout(playTimer);
  playTimer = 0;
  if (!ui.playing) return;
  const run = currentRun();
  if (!run) { ui.playing = false; return; }
  const steps = stepsOf(run);
  if (ui.idx >= steps.length - 1) {
    const next = ui.follow ? nextRunAfter(run) : null;
    // Still live: wait for its next event, unless it went silent and another request started.
    if (run.status === 'live' && !(next && next.startTs > (run.lastTs || 0) + 5)) { renderPlayer(); return; }
    if (next) {
      playTimer = setTimeout(() => selectRun(next.id, { at: 'start', play: true }), 1300 / ui.speed);
      return;
    }
    ui.playing = false;
    renderPlayer();
    return;
  }
  const behind = steps.length - 1 - ui.idx;
  const cur = steps[ui.idx];
  let delay = (cur && (cur.kind === 'answer' || cur.kind === 'ask') ? 1500 : 1050) / ui.speed;
  if (run.status === 'live' && ui.follow && behind > 3) delay = Math.min(delay, 420);
  playTimer = setTimeout(() => {
    playTimer = 0;
    setIdx(ui.idx + 1);
    schedule();
  }, delay);
}

// When following, requests are shown one after the other, never cut short.
function nextRunAfter(run) {
  const later = runsOf(run.app).filter((r) => r.id !== run.id && r.startTs >= run.startTs && later_than(r, run)).reverse();
  if (!later.length) return null;
  return later.length > 3 ? later[later.length - 1] : later[0];
}
function later_than(a, b) {
  if (a.startTs !== b.startTs) return a.startTs > b.startTs;
  return (a.events[0]?.seq || 0) > (b.events[0]?.seq || 0);
}

function play() {
  const run = currentRun();
  if (!run) return;
  const steps = stepsOf(run);
  if (ui.idx >= steps.length - 1 && run.status !== 'live') setIdx(0, { animate: false });
  if (run.status === 'live') ui.follow = true;
  ui.playing = true;
  renderPlayer();
  schedule();
}

function pause() {
  if (!ui.playing) return;
  ui.playing = false;
  clearTimeout(playTimer);
  renderPlayer();
}

function togglePlay() {
  if (ui.playing) { pause(); ui.follow = false; } else play();
}

function step(d) {
  pause();
  ui.follow = false;
  setIdx(ui.idx + d);
}

function selectRun(id, o = {}) {
  const run = store.runs.get(id);
  if (!run) return;
  clearTimeout(playTimer);
  if (run.app !== ui.app) { ui.app = run.app; ui.version = null; ui.compare = null; }
  ui.runId = id;
  const steps = stepsOf(run);
  ui.idx = o.at === 'start' ? 0 : Math.max(0, steps.length - 1);
  ui.playing = !!o.play;
  if (ui.version === null) mapKey = mapKey; // version may follow the run: drawMap checks the key
  renderTop();
  renderBanner();
  renderRun({ animate: false, instant: true, force: true });
  renderPanel();
  if (ui.playing) schedule();
}

function followLive() {
  const runs = runsOf(ui.app);
  const target = runs.find((r) => r.status === 'live') || runs[0];
  if (!target) return;
  ui.follow = true;
  selectRun(target.id, { at: target.status === 'live' ? 'end' : 'start', play: true });
}

function setView(v) {
  ui.view = v;
  lsSet('adk-lens.view', v);
  if (v !== 'journey') notes.setTool('select');
  renderTop();
  renderBanner();
  renderRun({ animate: false, instant: true });
  if (v === 'journey') requestAnimationFrame(() => map.fit());
}

// ---------------------------------------------------------------- popovers

function closePop(refocus = true) {
  if (!pop) return;
  const { node, anchor } = pop;
  pop = null;
  node.remove();
  anchor.setAttribute('aria-expanded', 'false');
  if (refocus) anchor.focus({ preventScroll: true });
}

function openPop(anchor, build, cls = '') {
  if (pop && pop.anchor === anchor) { closePop(); return null; }
  closePop(false);
  const node = h('div', { class: `pop ${cls}`, role: 'dialog' });
  build(node);
  put(document.body, node);
  const r = anchor.getBoundingClientRect();
  const w = node.offsetWidth;
  const left = Math.max(12, Math.min(r.left + r.width / 2 - w / 2, window.innerWidth - w - 12));
  node.style.left = `${left}px`;
  node.style.top = `${r.bottom + 10}px`;
  node.style.setProperty('--ox', `${r.left + r.width / 2 - left}px`);
  node.style.maxHeight = `${window.innerHeight - r.bottom - 26}px`;
  anchor.setAttribute('aria-expanded', 'true');
  pop = { node, anchor };
  const first = node.querySelector('button, select, input');
  if (first) first.focus({ preventScroll: true });
  return node;
}

function popItem(kids, onClick, o = {}) {
  const b = h('button', { class: `pop-item${o.current ? ' is-current' : ''}`, type: 'button', 'aria-current': o.current ? 'true' : null }, kids);
  b.addEventListener('click', () => { closePop(); onClick(); });
  return b;
}

function openApps(anchor) {
  openPop(anchor, (node) => {
    put(node, h('h2', { class: 'pop-title', text: t('top.apps') }));
    for (const app of Object.keys(store.apps)) {
      const n = runsOf(app).length;
      put(node, popItem([h('span', { class: 'pop-main', text: app }), h('span', { class: 'pop-sub', text: n ? `${n} · ${t('top.runs').toLowerCase()}` : t('top.runs.none') })], () => selectApp(app), { current: app === ui.app }));
    }
  });
}

function selectApp(app) {
  if (app === ui.app) return;
  pause();
  ui.app = app; ui.runId = null; ui.idx = 0; ui.version = null; ui.compare = null; ui.panel = null;
  const latest = runsOf(app)[0];
  if (latest) ui.runId = latest.id, ui.idx = Math.max(0, stepsOf(latest).length - 1);
  renderAll({ refit: true });
}

function openRuns(anchor) {
  openPop(anchor, (node) => {
    put(node, h('h2', { class: 'pop-title', text: t('runs.title') }));
    const runs = runsOf(ui.app);
    if (!runs.length) put(node, h('p', { class: 'pop-empty', text: t('top.runs.none') }));
    for (const r of runs) {
      const badge = r.status === 'live' ? h('span', { class: 'badge is-live' }, h('span', { class: 'live-dot' }), t('runs.live'))
        : r.status === 'error' ? h('span', { class: 'badge is-error', text: t('runs.failed') })
          : r.status === 'stalled' ? h('span', { class: 'badge', text: t('runs.stalled') }) : null;
      put(node, popItem([
        h('span', { class: 'pop-main', text: short(r.userMessage, 90) || t('runs.untitled') }),
        h('span', { class: 'pop-sub' }, badge, h('span', { text: [ago(r.startTs), t('runs.steps', { n: stepsOf(r).length })].filter(Boolean).join(' · ') })),
      ], () => {
        ui.follow = r.status === 'live';
        selectRun(r.id, { at: 'start', play: true });
      }, { current: r.id === ui.runId }));
    }
  }, 'pop-runs');
}

function openVersions(anchor) {
  openPop(anchor, (node) => {
    const list = versionsOf(ui.app);
    const cur = shownVersion();
    const latest = latestVersion(ui.app);
    put(node, h('h2', { class: 'pop-title', text: t('versions.title', { app: ui.app }) }), h('p', { class: 'pop-lead', text: t('versions.lead') }));
    for (const v of [...list].reverse()) {
      const when = v.ts ? new Date(v.ts * 1000).toLocaleString(getLang(), { dateStyle: 'medium', timeStyle: 'short' }) : '';
      put(node, popItem([
        h('span', { class: 'pop-main' }, t('top.version', { v: v.v }), v === latest ? h('span', { class: 'badge', text: t('versions.current') }) : null),
        h('span', { class: 'pop-sub', text: when }),
      ], () => { ui.version = v === latest ? null : v.v; ui.compare = null; if (ui.panel && ui.panel.type === 'diff') ui.panel = null; renderAll(); }, { current: v === cur }));
    }
    if (list.length > 1 && cur && cur.v > list[0].v) {
      const prev = [...list].reverse().find((v) => v.v < cur.v);
      const b = h('button', { class: 'pop-action', type: 'button' }, icon('layers', 16), h('span', { text: t('versions.compare') }));
      b.addEventListener('click', () => { closePop(); startCompare(prev.v); });
      put(node, b);
    }
  });
}

function startCompare(base) {
  pause();
  const cur = shownVersion();
  ui.version = cur ? cur.v : null;
  ui.compare = base;
  ui.panel = { type: 'diff' };
  renderAll();
  map.fit();
}

function stopCompare() {
  ui.compare = null;
  const cur = shownVersion();
  if (cur && cur === latestVersion(ui.app)) ui.version = null;
  if (ui.panel && ui.panel.type === 'diff') ui.panel = null;
  renderAll();
}

function applyTheme() {
  if (ui.theme === 'auto') document.documentElement.removeAttribute('data-theme');
  else document.documentElement.setAttribute('data-theme', ui.theme);
}

function isDark() {
  return ui.theme === 'dark' || (ui.theme === 'auto' && window.matchMedia('(prefers-color-scheme: dark)').matches);
}

function openMore(anchor) {
  openPop(anchor, (node) => {
    put(node, popItem([icon('globe', 18), h('span', { class: 'pop-main', text: t('menu.lang'), lang: getLang() === 'fr' ? 'en' : 'fr' })], () => {
      setLang(getLang() === 'fr' ? 'en' : 'fr');
      notes.flush();
      const doc = { v: 1, updated: Date.now() + 1000, items: notes.all() };
      buildShell();
      mapKey = '';
      notes.load(doc);
      renderAll({ refit: true });
      if (ui.playing) schedule();
    }));
    put(node, popItem([icon(isDark() ? 'sun' : 'moon', 18), h('span', { class: 'pop-main', text: t(isDark() ? 'menu.theme.light' : 'menu.theme.dark') })], () => {
      ui.theme = isDark() ? 'light' : 'dark';
      lsSet('adk-lens.theme', ui.theme);
      applyTheme();
    }));
    if (ui.theme !== 'auto') put(node, popItem([icon('check', 18), h('span', { class: 'pop-main', text: t('menu.theme.auto') })], () => {
      ui.theme = 'auto';
      lsSet('adk-lens.theme', 'auto');
      applyTheme();
    }));
    if (ui.app && notes.forApp(ui.app).length) put(node, popItem([icon('trash', 18), h('span', { class: 'pop-main', text: t('menu.notes.clear') })], () => {
      if (window.confirm(t('menu.notes.confirm'))) notes.clearApp(ui.app);
    }));
    if (!ui.fixture && store.runs.size) put(node, popItem([icon('trash', 18), h('span', { class: 'pop-main', text: t('menu.clear') })], () => {
      if (!window.confirm(t('menu.clear.confirm'))) return;
      fetch('/api/clear', { method: 'POST', headers: HEAD }).then(() => {
        store.runs = new Map();
        ui.runId = null;
        renderAll();
      }).catch(() => {});
    }));
  }, 'pop-menu');
}

let lastNotesDoc = null;

// ---------------------------------------------------------------- panels

function closePanel(refocus) {
  const was = ui.panel;
  ui.panel = null;
  renderPanel();
  map.select(null);
  if (refocus && was && was.type === 'node') { const n = map.nodeEl(was.id); if (n) n.focus({ preventScroll: true }); }
  if (refocus && was && was.type === 'prompt') el.copyBtn.focus({ preventScroll: true });
  if (was && was.type !== 'node' && ui.view === 'journey') map.fit();
}

function panelHead(title, sub, ico) {
  return h('div', { class: 'panel-head' },
    ico ? h('span', { class: 'panel-ico' }, ico) : null,
    h('div', { class: 'panel-titles' }, h('h2', { class: 'panel-title', text: title }), sub ? h('p', { class: 'panel-sub', text: sub }) : null),
    btn('icon-btn panel-close', t('card.close'), [icon('close', 18)], () => closePanel(true)));
}

function renderPanel() {
  const p = ui.panel;
  clear(el.panel);
  el.panel.hidden = !p;
  document.body.classList.toggle('has-panel', !!p);
  if (!p) return;
  el.panel.dataset.type = p.type;
  if (p.type === 'node') nodeCard(p.id);
  else if (p.type === 'prompt') promptPanel();
  else if (p.type === 'diff') diffPanel();
}

function section(title, ...kids) {
  const body = kids.flat().filter(Boolean);
  if (!body.length) return null;
  return h('section', { class: 'sec' }, h('h3', { class: 'sec-title', text: title }), ...body);
}

function openNode(id) {
  ui.panel = { type: 'node', id };
  renderPanel();
  map.select(id);
  map.reveal(id);
  el.panel.focus({ preventScroll: true });
}

function kindName(kind) {
  const k = t(`kind.${kind}`);
  return k === `kind.${kind}` ? t('kind.custom') : k;
}

function nodeCard(id) {
  const topo = shownTopology();
  const labels = { more: t('more'), less: t('less') };
  const isUser = id === USER;
  const node = isUser ? { id, name: t('node.user'), kind: 'user' } : topo.nodes.find((n) => n.id === id);
  if (!node) { ui.panel = null; el.panel.hidden = true; document.body.classList.remove('has-panel'); return; }
  el.panel.setAttribute('aria-label', node.name);
  put(el.panel, panelHead(node.name, isUser ? '' : kindName(node.kind), icon(isUser ? 'user' : node.kind, 20)));
  const body = h('div', { class: 'panel-body' });
  const what = t(`what.${node.kind}`);
  put(body, section(t('card.what'),
    h('p', { class: 'lead', text: what === `what.${node.kind}` ? t('what.custom') : what }),
    node.description ? h('p', { class: 'desc' }, clipped(node.description, 260, labels)) : null,
    node.dynamic ? h('p', { class: 'muted', text: t('what.dynamic') }) : null));
  if (node.instruction) put(body, section(t('card.instruction'), h('blockquote', { class: 'quote' }, clipped(node.instruction, 220, labels))));
  const facts = [];
  if (node.model) facts.push([t('card.model'), String(node.model)]);
  if (node.output_key) facts.push([t('card.output_key'), String(node.output_key)]);
  if (node.max_iterations) facts.push([t('card.max_iterations'), t('card.max_iterations.v', { n: node.max_iterations })]);
  if (facts.length) put(body, h('dl', { class: 'facts' }, ...facts.map(([k, v]) => [h('dt', { text: k }), h('dd', { text: v })])));
  const chip = (n) => btn(`mini-chip k-${n.kind}`, n.name, [icon(TOOLS.has(n.kind) ? n.kind : 'llm', 14), h('span', { text: short(n.name, 30) })], () => openNode(n.id), { noTitle: true });
  const kids = topo.nodes.filter((n) => n.parent === id);
  const linked = topo.edges.filter((e) => e.from === id && e.kind === 'uses_agent').map((e) => topo.nodes.find((n) => n.id === e.to)).filter(Boolean);
  const tools = kids.filter((n) => TOOLS.has(n.kind));
  const agents = [...kids.filter((n) => !TOOLS.has(n.kind)), ...linked.filter((n) => n.parent !== id)];
  if (tools.length) put(body, section(t('card.tools'), h('div', { class: 'chips' }, tools.slice(0, 60).map(chip))));
  if (agents.length) put(body, section(t('card.agents'), h('div', { class: 'chips' }, agents.slice(0, 60).map(chip))));

  // What it did in the selected request.
  const run = currentRun();
  if (!run) put(body, section(t('card.run'), h('p', { class: 'muted', text: t('card.run.pick') })));
  else {
    const act = nodeActivity(run, id);
    if (!act.steps.length) put(body, section(t('card.run'), h('p', { class: 'muted', text: t('card.run.none') })));
    else {
      const bits = [];
      if (act.sum.thinks) bits.push(t('card.sum.thinks', { n: act.sum.thinks }));
      if (act.sum.uses) bits.push(t('card.sum.uses', { n: act.sum.uses }));
      if (act.sum.tokensIn || act.sum.tokensOut) bits.push(t('card.sum.tokens', { a: act.sum.tokensIn, b: act.sum.tokensOut }));
      const total = act.sum.total || act.sum.ms;
      if (total) bits.push(t('card.sum.time', { d: fmtDuration(total) }));
      if (act.sum.errors) bits.push(t('card.sum.errors', { n: act.sum.errors }));
      const list = h('ol', { class: 'mini-steps' });
      for (const { i, step: st } of act.steps.slice(0, 40)) {
        const sn = sentence(st);
        const b = h('button', { class: `mini-step tone-${st.kind}${i === ui.idx ? ' is-current' : ''}`, type: 'button', title: t('card.goto') },
          h('span', { class: 'mini-line' }, tn(sn.key, sn.vars)), sn.body ? h('span', { class: 'mini-body', text: short(sn.body, 110) }) : null);
        b.addEventListener('click', () => { pause(); ui.follow = false; setIdx(i); });
        put(list, h('li', null, b));
      }
      put(body, section(t('card.run'), bits.length ? h('p', { class: 'sum', text: bits.join(' · ') }) : null, list));
    }
  }
  if (!isUser) {
    el.nodeComments = h('div', { class: 'node-comments' });
    const add = btn('ghost-btn', t('card.comment'), [icon('comment', 16), h('span', { text: t('card.comment') })], () => {
      notes.addNodeComment(node);
      refreshNodeComments(true);
    }, { noTitle: true });
    put(body, section(t('card.comments'), el.nodeComments, add));
    refreshNodeComments();
  }
  put(el.panel, body);
}

function refreshNodeComments(focusLast) {
  if (!ui.panel || ui.panel.type !== 'node' || !el.nodeComments || !el.nodeComments.isConnected) return;
  const mine = notes.forNode(ui.panel.id);
  const active = document.activeElement;
  if (!focusLast && el.nodeComments.contains(active) && el.nodeComments.children.length === mine.length) return;
  clear(el.nodeComments);
  for (const it of mine) put(el.nodeComments, notes.inlineNote(it));
  if (focusLast) { const ta = el.nodeComments.querySelector('.note-inline:last-child textarea'); if (ta) ta.focus(); }
}

async function copyPrompt() {
  const had = ui.app && notes.forApp(ui.app).length > 0;
  ui.panel = { type: 'prompt' };
  renderPanel();
  if (ui.view === 'journey') map.fit(); // make room so the notes stay visible next to the panel
  if (had) await doCopy();
  else el.panel.focus({ preventScroll: true });
}

async function doCopy() {
  const text = promptText();
  const ok = await copyText(text);
  const status = el.panel.querySelector('.copy-status');
  const area = el.panel.querySelector('.prompt-text');
  const b = el.panel.querySelector('.prompt-copy');
  if (ok) {
    toast(t('prompt.copied'));
    if (b) {
      b.classList.add('is-done');
      put(clear(b), icon('check', 17), h('span', { text: t('prompt.copied') }));
      setTimeout(() => { if (b.isConnected) { b.classList.remove('is-done'); put(clear(b), icon('copy', 17), h('span', { text: t('prompt.copy') })); } }, 2200);
    }
    if (status) status.textContent = t('prompt.copied');
  } else if (area) {
    area.focus();
    area.select();
    if (status) { status.textContent = t('prompt.fallback'); status.classList.add('is-warn'); }
  }
}

function promptPanel() {
  const n = notes.forApp(ui.app).length;
  el.panel.setAttribute('aria-label', t('prompt.title'));
  put(el.panel, panelHead(t('prompt.title'), t('prompt.lead'), icon('copy', 20)));
  const body = h('div', { class: 'panel-body' });
  if (!n) put(body, h('p', { class: 'muted prompt-empty', text: t('prompt.empty') }));
  const area = h('textarea', { class: 'prompt-text', readonly: true, spellcheck: 'false', 'aria-label': t('prompt.aria') });
  area.value = promptText();
  const copy = btn('primary-btn prompt-copy', t('prompt.copy'), [icon('copy', 17), h('span', { text: t('prompt.copy') })], () => doCopy(), { noTitle: true });
  put(body, h('div', { class: 'prompt-bar' }, h('span', { class: 'muted', text: t('prompt.count', { n }) }), copy),
    h('p', { class: 'copy-status', role: 'status', 'aria-live': 'polite' }), area);
  put(el.panel, body);
}

function refreshPromptPanel() {
  const area = el.panel.querySelector('.prompt-text');
  if (area) area.value = promptText();
}

function diffPanel() {
  const ver = shownVersion();
  const list = versionsOf(ui.app);
  const base = list.find((v) => v.v === ui.compare);
  if (!ver || !base) { ui.panel = null; el.panel.hidden = true; return; }
  const labels = { more: t('more'), less: t('less') };
  el.panel.setAttribute('aria-label', t('diff.title', { a: base.v, b: ver.v }));
  put(el.panel, panelHead(t('diff.title', { a: base.v, b: ver.v }), '', icon('layers', 20)));
  const body = h('div', { class: 'panel-body' });
  const others = list.filter((v) => v.v !== ver.v);
  if (others.length > 1) {
    const sel = h('select', { class: 'select', 'aria-label': t('versions.compare.with', { a: ver.v }) }, others.map((v) => h('option', { value: String(v.v), selected: v.v === base.v, text: t('top.version', { v: v.v }) })));
    sel.addEventListener('change', () => { ui.compare = Number(sel.value); renderAll(); });
    put(body, h('label', { class: 'field' }, h('span', { text: t('versions.compare.with', { a: ver.v }) }), sel));
  }
  const [a, b] = base.v < ver.v ? [base, ver] : [ver, base];
  const diff = diffTopologies(a.topology, b.topology);
  if (!diff.list.length && !diff.edges.size) put(body, h('p', { class: 'muted', text: t('diff.none') }));
  const ul = h('ul', { class: 'diff-list' });
  for (const d of diff.list) {
    const kind = kindName(d.node.kind);
    const vars = { name: d.node.name, kind, fields: (d.fields || []).map((f) => t(`diff.f.${f}`)).join(', ') };
    const li = h('li', { class: `diff-item d-${d.status}` }, h('span', { class: 'diff-tag', text: t(`diff.${d.status}`) }), h('span', { class: 'diff-line' }, tn(`diff.s.${d.status}`, vars)));
    if (d.status === 'changed') {
      const det = h('details', { class: 'st-details' }, h('summary', { text: t('story.details') }));
      for (const f of d.fields.filter((x) => x === 'instruction' || x === 'model' || x === 'description')) {
        put(det, h('div', { class: 'kv' }, h('div', { class: 'kv-k', text: `${t(`diff.f.${f}`)} · ${t('diff.before')}` }), h('div', { class: 'kv-v' }, clipped(String(d.old[f] ?? '—'), 300, labels))),
          h('div', { class: 'kv' }, h('div', { class: 'kv-k', text: `${t(`diff.f.${f}`)} · ${t('diff.after')}` }), h('div', { class: 'kv-v' }, clipped(String(d.node[f] ?? '—'), 300, labels))));
      }
      if (det.children.length > 1) put(li, det);
    }
    put(ul, li);
  }
  put(body, ul);
  const added = [...diff.edges.values()].filter((x) => x === 'added').length;
  const removed = [...diff.edges.values()].filter((x) => x === 'removed').length;
  if (added || removed) put(body, h('p', { class: 'muted', text: t('diff.links', { a: added, r: removed }) }));
  put(body, btn('ghost-btn', t('versions.compare.off'), [t('versions.compare.off')], () => stopCompare(), { noTitle: true }));
  put(el.panel, body);
}

// ---------------------------------------------------------------- data

function scheduleRefresh(runId) {
  scheduleRefresh.runs.add(runId);
  if (refreshRaf) return;
  refreshRaf = requestAnimationFrame(() => {
    refreshRaf = 0;
    const touched = [...scheduleRefresh.runs];
    scheduleRefresh.runs.clear();
    onRunsTouched(touched);
  });
}
scheduleRefresh.runs = new Set();

function onRunsTouched(ids) {
  const wasEmpty = document.body.classList.contains('is-empty');
  if (wasEmpty || !ui.app) { renderAll({ refit: true }); }
  const cur = currentRun();
  if (ui.follow && !cur) {
    const first = ui.app ? runsOf(ui.app)[0] : null;
    if (first) { selectRun(first.id, { at: 'start', play: true }); return; }
  } else if (ui.follow && cur && !ui.playing && ui.idx >= stepsOf(cur).length - 1 && cur.status !== 'live') {
    const next = nextRunAfter(cur);
    if (next) { selectRun(next.id, { at: 'start', play: true }); return; }
  }
  if (ui.follow && ui.playing && cur && cur.status === 'live' && ui.idx >= stepsOf(cur).length - 1 && !playTimer) schedule();
  if (cur && ids.includes(cur.id)) {
    renderRun({ instant: true });
    if (ui.playing) { if (ui.idx >= stepsOf(cur).length - 2 || !playTimer) schedule(); }
    if (ui.panel && ui.panel.type === 'node') renderPanel();
  }
  renderTop();
}

let shapesT = 0;
function refetchShapes() {
  clearTimeout(shapesT);
  shapesT = setTimeout(() => {
    if (ui.fixture) return;
    fetch('/api/state').then((r) => r.json()).then((st) => {
      applyShapes(st);
      renderAll();
    }).catch(() => {});
  }, 250);
}

function handleEvent(ev) {
  if (store.stale) {
    // The hub came back empty and now speaks again: start a fresh recording.
    resetStore();
    ui.runId = null; ui.app = null; mapKey = '';
  }
  const res = ingest(ev);
  if (!res) return;
  if (res.cleared) { ui.runId = null; renderAll(); return; }
  if (res.topology) {
    mapKey = '';
    renderAll();
    refetchShapes();
    return;
  }
  if (res.run) scheduleRefresh(res.run);
}

function setConn(state) {
  if (ui.conn === state) return;
  const was = ui.conn;
  ui.conn = state;
  renderBanner();
  if (state === 'live' && was === 'lost') {
    toast(t('conn.back'));
    if (notesLocalOnly) notes.flush(); // send what was written while the hub was away
  }
}

function openStream() {
  if (es) es.close();
  es = new EventSource(`/api/stream?since=${store.lastSeq}`);
  es.onopen = () => setConn('live');
  es.onmessage = (m) => {
    let ev;
    try { ev = JSON.parse(m.data); } catch { return; }
    handleEvent(ev);
  };
  es.onerror = () => {
    es.close();
    es = null;
    setConn('lost');
    // A run that was live when the hub went away will never finish.
    reconnect(1500);
  };
}

function reconnect(delay) {
  clearTimeout(retryT);
  retryT = setTimeout(async () => {
    try {
      const res = await fetch('/api/state', { cache: 'no-store' });
      if (!res.ok) throw new Error('bad status');
      const st = await res.json();
      const restarted = (Number(st.seq) || 0) < store.lastSeq;
      if (restarted) {
        const blank = !(st.events || []).length && !Object.keys(st.apps || {}).length;
        if (blank && !isEmpty()) { store.stale = true; store.lastSeq = Number(st.seq) || 0; }
        else { loadState(st); ui.runId = null; mapKey = ''; pickInitialRun(); renderAll({ refit: true }); }
      }
      openStream();
    } catch {
      reconnect(Math.min(delay * 1.5, 6000));
    }
  }, delay);
}

function pickInitialRun() {
  const runs = ui.app ? runsOf(ui.app) : [...store.runs.values()].sort((a, b) => b.startTs - a.startTs);
  if (!runs.length) return;
  const live = runs.find((r) => r.status === 'live');
  if (ui.fixture) {
    const best = [...runs].sort((a, b) => stepsOf(b).length - stepsOf(a).length)[0];
    ui.app = best.app; ui.runId = best.id; ui.idx = 0; ui.playing = !params.has('still');
    if (params.has('step')) { ui.idx = Number(params.get('step')) || 0; ui.playing = false; }
    return;
  }
  const r = live || runs[0];
  ui.app = r.app; ui.runId = r.id; ui.idx = Math.max(0, stepsOf(r).length - 1);
  ui.playing = !!live; ui.follow = true;
}

async function boot() {
  initLang();
  applyTheme();
  buildShell();
  let state = null;
  if (!params.has('fixture')) {
    try {
      const res = await fetch('/api/state', { cache: 'no-store' });
      if (res.ok) state = await res.json();
    } catch { state = null; }
  }
  if (!state || typeof state !== 'object' || !('seq' in state)) {
    // No hub here (static hosting, or ?fixture=1): play the bundled recording.
    try {
      const res = await fetch('demo-fixture.json');
      state = await res.json();
      ui.fixture = true;
    } catch { state = { seq: 0, events: [], apps: {}, versions: {}, notes: null }; ui.fixture = true; }
    if (params.has('empty')) state = { seq: 0, events: [], apps: {}, versions: {}, notes: null };
  }
  loadState(state);
  lastNotesDoc = store.hubNotes;
  ui.conn = ui.fixture ? 'fixture' : 'connecting';
  const apps = Object.keys(store.apps);
  ui.app = params.get('app') && store.apps[params.get('app')] ? params.get('app') : null;
  if (!ui.app) {
    const latest = [...store.runs.values()].sort((a, b) => b.startTs - a.startTs)[0];
    ui.app = latest ? latest.app : apps[0] || null;
  }
  pickInitialRun();
  notes.load(lastNotesDoc);
  renderAll({ refit: true });
  if (ui.playing) schedule();
  if (!ui.fixture) openStream();
  document.documentElement.classList.add('is-ready');
}

// ---------------------------------------------------------------- keyboard

document.addEventListener('keydown', (e) => {
  if (e.defaultPrevented || e.metaKey || e.ctrlKey || e.altKey) return;
  const tgt = e.target;
  const typing = tgt.closest && tgt.closest('textarea, input:not([type="range"]), select, [contenteditable="true"]');
  if (e.key === 'Escape') {
    if (pop) { closePop(); e.preventDefault(); return; }
    if (typing) { tgt.blur(); return; }
    if (notes.tool() !== 'select') { notes.setTool('select'); return; }
    if (notes.deselect()) return;
    if (ui.panel) { closePanel(true); return; }
    return;
  }
  if (typing) return;
  if (e.key === ' ' || e.code === 'Space') {
    if (tgt.closest('button, a, summary, [role="button"]')) return;
    if (!currentRun()) return;
    e.preventDefault();
    togglePlay();
  } else if (e.key === 'ArrowRight' || e.key === 'ArrowLeft') {
    if (tgt.closest('.note, input[type="range"]') || !currentRun()) return;
    e.preventDefault();
    step(e.key === 'ArrowRight' ? 1 : -1);
  } else if (ui.view === 'journey' && ui.app) {
    if (e.key === '+' || e.key === '=') map.zoomBy(1.25);
    else if (e.key === '-') map.zoomBy(1 / 1.25);
    else if (e.key === '0') map.fit();
  }
});

document.addEventListener('pointerdown', (e) => {
  if (pop && !pop.node.contains(e.target) && !pop.anchor.contains(e.target)) closePop(false);
}, true);
window.addEventListener('resize', () => closePop(false));
window.matchMedia('(prefers-color-scheme: dark)').addEventListener?.('change', () => { /* tokens follow the system on their own */ });
void reducedMotion;

boot();
