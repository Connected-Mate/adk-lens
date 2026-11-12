/* ADK Lens site: the playable board. Original code.
   A small stand-in for the real tool: pick a request, watch it travel through the agents of the
   bundled example, replay it step by step, switch between the two views. Without JavaScript the
   static drawing stays in place. With reduced motion nothing plays by itself and steps are instant. */
(function () {
  'use strict';
  var root = document.querySelector('[data-play]');
  if (!root || !document.createElementNS || !root.getBoundingClientRect) return;

  var NS = 'http://www.w3.org/2000/svg';
  var fr = root.getAttribute('data-lang') === 'fr';
  var reduce = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  var L = function (f, e) { return fr ? f : e; };

  var NODES = {
    you: { label: L('Toi', 'You'), kind: 'you' },
    concierge: { label: 'concierge', kind: 'agent' },
    weather_agent: { label: 'weather_agent', kind: 'agent' },
    get_weather: { label: 'get_weather', kind: 'tool' },
    trip_planner: { label: 'trip_planner', kind: 'agent' },
    researcher: { label: 'researcher', kind: 'agent' },
    search_places: { label: 'search_places', kind: 'tool' },
    writer: { label: 'writer', kind: 'agent' }
  };
  var EDGES = [['you', 'concierge'], ['concierge', 'weather_agent'], ['weather_agent', 'get_weather'], ['concierge', 'trip_planner'],
    ['trip_planner', 'researcher'], ['researcher', 'search_places'], ['trip_planner', 'writer']];
  var LAYOUTS = {
    wide: { w: 1040, h: 440, nh: 46, font: 16, tool: 13.5, cw: 9, tw: 8.2, pad: 36, min: 84,
      at: { you: [70, 220], concierge: [240, 220], weather_agent: [480, 110], get_weather: [740, 110], trip_planner: [480, 330],
        researcher: [720, 270], search_places: [940, 270], writer: [720, 390] } },
    tall: { w: 390, h: 400, nh: 38, font: 13, tool: 11.5, cw: 7.4, tw: 7, pad: 24, min: 62,
      at: { you: [195, 34], concierge: [195, 112], weather_agent: [84, 196], get_weather: [84, 280], trip_planner: [286, 196],
        researcher: [232, 280], search_places: [232, 364], writer: [338, 280] } }
  };

  // Each step: the legs the dot travels, where it lands, and one plain sentence.
  var ASKS = [
    { label: L('Quel temps à Lisbonne ?', 'Weather in Lisbon?'), steps: [
      { legs: [['you', 'concierge']], at: 'concierge', say: L('Tu demandes la météo à Lisbonne. concierge reçoit ta demande.', 'You ask for the weather in Lisbon. concierge gets your request.') },
      { legs: [['concierge', 'weather_agent']], at: 'weather_agent', say: L('concierge passe la main à weather_agent.', 'concierge hands over to weather_agent.') },
      { legs: [['weather_agent', 'get_weather']], at: 'get_weather', say: L('weather_agent utilise l\'outil get_weather.', 'weather_agent uses the get_weather tool.') },
      { legs: [['get_weather', 'weather_agent']], at: 'weather_agent', say: L('L\'outil répond : soleil, 15 à 24 °C.', 'The tool answers: sunny, 15 to 24 °C.') },
      { legs: [['weather_agent', 'concierge'], ['concierge', 'you']], at: 'you', done: true, say: L('Tu reçois la réponse : « Lisbon: sunny, 15 to 24 °C. »', 'You get the answer: “Lisbon: sunny, 15 to 24 °C.”') }
    ] },
    { label: L('Un week-end à Marseille', 'A weekend in Marseille'), steps: [
      { legs: [['you', 'concierge']], at: 'concierge', say: L('Tu demandes un week-end à Marseille.', 'You ask for a weekend in Marseille.') },
      { legs: [['concierge', 'trip_planner']], at: 'trip_planner', say: L('concierge passe la main à trip_planner.', 'concierge hands over to trip_planner.') },
      { legs: [['trip_planner', 'researcher']], at: 'researcher', say: L('trip_planner lance d\'abord researcher.', 'trip_planner starts with researcher.') },
      { legs: [['researcher', 'search_places']], at: 'search_places', say: L('researcher cherche des lieux avec l\'outil search_places.', 'researcher looks for places with the search_places tool.') },
      { legs: [['search_places', 'researcher']], at: 'researcher', say: L('L\'outil renvoie trois lieux à visiter.', 'The tool returns three places to visit.') },
      { legs: [['researcher', 'trip_planner'], ['trip_planner', 'writer']], at: 'writer', say: L('Ensuite, writer rédige le programme.', 'Then writer writes the plan.') },
      { legs: [['writer', 'trip_planner'], ['trip_planner', 'concierge'], ['concierge', 'you']], at: 'you', done: true, say: L('Tu reçois ton week-end, jour par jour.', 'You get your weekend, day by day.') }
    ] },
    { label: L('Et à Atlantis ?', 'And in Atlantis?'), steps: [
      { legs: [['you', 'concierge']], at: 'concierge', say: L('Tu demandes la météo à Atlantis.', 'You ask for the weather in Atlantis.') },
      { legs: [['concierge', 'weather_agent']], at: 'weather_agent', say: L('concierge passe la main à weather_agent.', 'concierge hands over to weather_agent.') },
      { legs: [['weather_agent', 'get_weather']], at: 'get_weather', say: L('weather_agent utilise l\'outil get_weather.', 'weather_agent uses the get_weather tool.') },
      { legs: [], at: 'get_weather', err: true, say: L('L\'outil échoue : ville inconnue. Tu vois tout de suite où ça casse.', 'The tool fails: unknown city. You see at once where it breaks.') }
    ] }
  ];

  var T = {
    asks: L('Choisis une demande', 'Pick a request'),
    views: L('Choisis une vue', 'Pick a view'),
    journey: L('Trajet', 'Journey'), story: L('Récit', 'Story'),
    map: L('Carte des agents de l\'exemple. La demande passe d\'un agent à l\'autre.', 'Map of the example agents. The request travels from one agent to the next.'),
    prev: L('Étape précédente', 'Previous step'), next: L('Étape suivante', 'Next step'),
    play: L('Lecture', 'Play'), pause: L('Pause', 'Pause'), replay: L('Rejouer', 'Replay'),
    idle: L('Appuie sur lecture, ou choisis une demande.', 'Press play, or pick a request.'),
    hint: L('Clique un agent pour y poser une question.', 'Click an agent to pin a question on it.'),
    one: L('1 question posée. Dans ADK Lens, tu la copies comme prompt pour ton agent de code.', '1 question pinned. In ADK Lens, you copy it as a prompt for your coding agent.'),
    many: L(' questions posées. Dans ADK Lens, tu les copies comme prompt pour ton agent de code.', ' questions pinned. In ADK Lens, you copy them as a prompt for your coding agent.'),
    ask: L('Poser une question sur ', 'Pin a question on '),
    step: L('Étape ', 'Step ')
  };
  var ICON = {
    prev: '<path d="M11 5 5 10l6 5V5Zm4 0h-2v10h2V5Z"/>',
    next: '<path d="m9 5 6 5-6 5V5ZM5 5h2v10H5V5Z"/>',
    play: '<path d="M7 4.5v11l9-5.5-9-5.5Z"/>',
    pause: '<path d="M6 4.5h3v11H6v-11Zm5 0h3v11h-3v-11Z"/>',
    replay: '<path d="M10 4a6 6 0 1 1-5.66 4H2.3A8 8 0 1 0 10 2V0L6 3l4 3V4Z"/>'
  };

  var el = function (tag, cls, text) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text != null) n.textContent = text;
    return n;
  };
  var svg = function (tag, attrs) {
    var n = document.createElementNS(NS, tag);
    for (var k in attrs) n.setAttribute(k, attrs[k]);
    return n;
  };
  var iconButton = function (cls, label, icon) {
    var b = el('button', cls);
    b.type = 'button';
    b.setAttribute('aria-label', label);
    b.innerHTML = '<svg viewBox="0 0 20 20" width="18" height="18" aria-hidden="true" fill="currentColor">' + ICON[icon] + '</svg>';
    return b;
  };

  // ---- state ----
  var ask = 0, step = -1, playing = false, auto = !reduce, view = 'journey', token = 0, timer = 0, raf = 0;
  var layoutName = '', nodeEls = {}, edgeEls = {}, dot = null, pins = {};

  // ---- skeleton ----
  root.textContent = '';
  root.classList.add('is-live');
  var bar = el('div', 'play__bar');
  var asksBox = el('div', 'play__asks'); asksBox.setAttribute('role', 'group'); asksBox.setAttribute('aria-label', T.asks);
  var askBtns = ASKS.map(function (a, i) {
    var b = el('button', 'play__ask', a.label); b.type = 'button';
    b.addEventListener('click', function () { auto = false; choose(i, true); });
    asksBox.appendChild(b); return b;
  });
  var viewsBox = el('div', 'play__views'); viewsBox.setAttribute('role', 'group'); viewsBox.setAttribute('aria-label', T.views);
  var viewBtns = {};
  ['journey', 'story'].forEach(function (v) {
    var b = el('button', 'play__view', T[v]); b.type = 'button';
    b.addEventListener('click', function () { setView(v); });
    viewsBox.appendChild(b); viewBtns[v] = b;
  });
  bar.appendChild(asksBox); bar.appendChild(viewsBox);

  var stage = el('div', 'play__stage');
  var mapBox = el('div', 'play__map');
  var storyBox = el('ol', 'play__story');
  stage.appendChild(mapBox); stage.appendChild(storyBox);

  var foot = el('div', 'play__foot');
  var say = el('p', 'play__say', T.idle);
  var ctl = el('div', 'play__ctl');
  var prevBtn = iconButton('play__btn', T.prev, 'prev');
  var playBtn = iconButton('play__btn play__btn--main', T.play, 'play');
  var nextBtn = iconButton('play__btn', T.next, 'next');
  ctl.appendChild(prevBtn); ctl.appendChild(playBtn); ctl.appendChild(nextBtn);
  var ticks = el('div', 'play__ticks'); ticks.setAttribute('aria-hidden', 'true');
  foot.appendChild(say); foot.appendChild(ctl);
  var hint = el('p', 'play__hint caption', T.hint);

  root.appendChild(bar); root.appendChild(stage); root.appendChild(ticks); root.appendChild(foot); root.appendChild(hint);

  // ---- map ----
  function nodeWidth(id, lay) {
    var n = NODES[id];
    return Math.max(lay.min, Math.round(n.label.length * (n.kind === 'tool' ? lay.tw : lay.cw) + lay.pad));
  }
  function edgePath(a, b, lay) {
    var s = lay.at[a], t = lay.at[b];
    if (layoutName === 'wide') { var mx = (s[0] + t[0]) / 2; return 'M' + s[0] + ' ' + s[1] + ' C' + mx + ' ' + s[1] + ' ' + mx + ' ' + t[1] + ' ' + t[0] + ' ' + t[1]; }
    var my = (s[1] + t[1]) / 2;
    return 'M' + s[0] + ' ' + s[1] + ' C' + s[0] + ' ' + my + ' ' + t[0] + ' ' + my + ' ' + t[0] + ' ' + t[1];
  }
  function buildMap() {
    var want = root.getBoundingClientRect().width < 620 ? 'tall' : 'wide';
    if (want === layoutName) return;
    layoutName = want;
    var lay = LAYOUTS[want];
    mapBox.textContent = '';
    nodeEls = {}; edgeEls = {};
    var s = svg('svg', { viewBox: '0 0 ' + lay.w + ' ' + lay.h, role: 'group', 'aria-label': T.map, 'class': 'play__svg play__svg--' + want });
    EDGES.forEach(function (e) {
      var p = svg('path', { d: edgePath(e[0], e[1], lay), 'class': 'p-edge' + (NODES[e[1]].kind === 'tool' ? ' p-edge--tool' : '') });
      s.appendChild(p); edgeEls[e[0] + '>' + e[1]] = p;
    });
    Object.keys(NODES).forEach(function (id) {
      var n = NODES[id], c = lay.at[id], w = nodeWidth(id, lay), h = n.kind === 'tool' ? lay.nh - 6 : lay.nh;
      var g = svg('g', { 'class': 'p-node p-node--' + n.kind, transform: 'translate(' + c[0] + ' ' + c[1] + ')' });
      g.appendChild(svg('rect', { 'class': 'p-halo', x: -w / 2 - 6, y: -h / 2 - 6, width: w + 12, height: h + 12, rx: h / 2 + 6 }));
      g.appendChild(svg('rect', { 'class': 'p-box', x: -w / 2, y: -h / 2, width: w, height: h, rx: h / 2 }));
      var t = svg('text', { 'text-anchor': 'middle', y: (n.kind === 'tool' ? lay.tool : lay.font) * 0.34, 'font-size': n.kind === 'tool' ? lay.tool : lay.font });
      t.textContent = n.label; g.appendChild(t);
      if (n.kind !== 'you') {
        var pin = svg('g', { 'class': 'p-pin', transform: 'translate(' + (w / 2 - 6) + ' ' + (-h / 2 - 2) + ')' });
        pin.appendChild(svg('circle', { r: lay.nh * 0.3 }));
        var q = svg('text', { 'text-anchor': 'middle', y: lay.font * 0.3, 'font-size': lay.font * 0.86 }); q.textContent = '?';
        pin.appendChild(q); g.appendChild(pin);
        g.setAttribute('role', 'button'); g.setAttribute('tabindex', '0');
        g.setAttribute('aria-label', T.ask + n.label); g.setAttribute('aria-pressed', pins[id] ? 'true' : 'false');
        if (pins[id]) g.classList.add('is-pinned');
        var toggle = function () { togglePin(id); };
        g.addEventListener('click', toggle);
        g.addEventListener('keydown', function (ev) { if (ev.key === 'Enter' || ev.key === ' ') { ev.preventDefault(); toggle(); } });
      }
      s.appendChild(g); nodeEls[id] = g;
    });
    dot = svg('g', { 'class': 'p-dot' });
    dot.appendChild(svg('circle', { r: want === 'wide' ? 15 : 12, 'class': 'p-dot__glow' }));
    dot.appendChild(svg('circle', { r: want === 'wide' ? 6.5 : 5.5 }));
    s.appendChild(dot);
    mapBox.appendChild(s);
    paint();
  }
  function togglePin(id) {
    pins[id] = !pins[id];
    var g = nodeEls[id];
    g.classList.toggle('is-pinned', !!pins[id]);
    g.setAttribute('aria-pressed', pins[id] ? 'true' : 'false');
    var n = Object.keys(pins).filter(function (k) { return pins[k]; }).length;
    hint.textContent = n === 0 ? T.hint : n === 1 ? T.one : n + T.many;
    hint.classList.toggle('is-on', n > 0);
  }

  // ---- painting the current state ----
  function paint() {
    var steps = ASKS[ask].steps, seenN = {}, seenE = {}, i, j;
    for (i = 0; i <= step; i++) {
      seenN[steps[i].at] = 1;
      for (j = 0; j < steps[i].legs.length; j++) { seenN[steps[i].legs[j][0]] = 1; seenE[steps[i].legs[j].join('>')] = 1; seenE[steps[i].legs[j].slice().reverse().join('>')] = 1; }
    }
    var cur = step >= 0 ? steps[step] : null;
    Object.keys(nodeEls).forEach(function (id) {
      var c = nodeEls[id].classList;
      c.toggle('is-seen', !!seenN[id]);
      c.toggle('is-on', !!cur && cur.at === id && !cur.err);
      c.toggle('is-err', !!cur && cur.at === id && !!cur.err);
    });
    Object.keys(edgeEls).forEach(function (k) { edgeEls[k].classList.toggle('is-lit', !!seenE[k]); });
    root.classList.toggle('is-done', !!cur && !!cur.done);
    root.classList.toggle('is-failed', !!cur && !!cur.err);
    say.textContent = cur ? cur.say : T.idle;
    say.classList.toggle('is-err', !!cur && !!cur.err);
    askBtns.forEach(function (b, n) { b.setAttribute('aria-pressed', n === ask ? 'true' : 'false'); });
    [].forEach.call(storyBox.children, function (li, n) {
      li.classList.toggle('is-past', n < step); li.classList.toggle('is-now', n === step);
      li.firstChild.setAttribute('aria-current', n === step ? 'step' : 'false');
    });
    [].forEach.call(ticks.children, function (t, n) { t.classList.toggle('is-past', n <= step); });
    var atEnd = step >= steps.length - 1;
    var mode = playing ? 'pause' : atEnd ? 'replay' : 'play';
    playBtn.setAttribute('aria-label', T[mode]);
    playBtn.firstChild.innerHTML = ICON[mode];
    prevBtn.disabled = step <= 0;
    nextBtn.disabled = atEnd;
  }
  function buildStory() {
    storyBox.textContent = ''; ticks.textContent = '';
    ASKS[ask].steps.forEach(function (s, n) {
      var li = el('li'), b = el('button', s.err ? 'is-err' : '', s.say);
      b.type = 'button';
      b.addEventListener('click', function () { auto = false; stop(); go(n, false, true); });
      li.appendChild(b); storyBox.appendChild(li);
      ticks.appendChild(el('i'));
    });
  }

  // ---- movement ----
  function leg(a, b) {
    var p = edgeEls[a + '>' + b];
    if (p) return { p: p, rev: false };
    p = edgeEls[b + '>' + a];
    return p ? { p: p, rev: true } : null;
  }
  function travel(legs, mine, done) {
    if (!legs.length || reduce || view !== 'journey' || !dot) { done(); return; }
    var i = 0;
    dot.classList.add('is-moving');
    var run = function () {
      if (mine !== token) return;
      if (i >= legs.length) { dot.classList.remove('is-moving'); done(); return; }
      var l = leg(legs[i][0], legs[i][1]); i++;
      if (!l) { run(); return; }
      var len = l.p.getTotalLength(), t0 = 0, dur = Math.min(900, 380 + len * 1.5);
      var frame = function (ms) {
        if (mine !== token) return;
        if (!t0) t0 = ms;
        var t = Math.min(1, (ms - t0) / dur);
        var k = t < .5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2;
        var pt = l.p.getPointAtLength(len * (l.rev ? 1 - k : k));
        dot.setAttribute('transform', 'translate(' + pt.x.toFixed(1) + ' ' + pt.y.toFixed(1) + ')');
        if (t < 1) raf = requestAnimationFrame(frame); else run();
      };
      raf = requestAnimationFrame(frame);
    };
    run();
  }
  function stop() {
    token++; playing = false;
    clearTimeout(timer); cancelAnimationFrame(raf);
    if (dot) dot.classList.remove('is-moving');
  }
  // Go to step n. `animate` moves the dot first; `spoken` lets screen readers hear the sentence.
  function go(n, animate, spoken) {
    var steps = ASKS[ask].steps;
    n = Math.max(0, Math.min(steps.length - 1, n));
    var mine = ++token;
    clearTimeout(timer); cancelAnimationFrame(raf);
    say.setAttribute('aria-live', spoken ? 'polite' : 'off');
    var land = function () {
      if (mine !== token) return;
      step = n; paint();
      if (!playing) return;
      var last = n >= steps.length - 1;
      timer = setTimeout(function () {
        if (mine !== token) return;
        if (!last) { go(n + 1, true, false); return; }
        if (auto) { choose((ask + 1) % ASKS.length, true); return; }
        playing = false; paint();
      }, last ? 2600 : steps[n].err ? 1800 : 1250);
    };
    if (animate) travel(steps[n].legs, mine, land); else land();
  }
  function choose(i, andPlay) {
    stop();
    ask = i; step = -1;
    buildStory();
    playing = !!andPlay && !reduce;
    paint();
    if (andPlay) go(0, true, !auto);
  }
  function setView(v) {
    view = v;
    root.setAttribute('data-view', v);
    viewBtns.journey.setAttribute('aria-pressed', v === 'journey' ? 'true' : 'false');
    viewBtns.story.setAttribute('aria-pressed', v === 'story' ? 'true' : 'false');
    mapBox.inert = v !== 'journey'; storyBox.inert = v !== 'story';
  }

  playBtn.addEventListener('click', function () {
    auto = false;
    if (playing) { stop(); paint(); return; }
    var atEnd = step >= ASKS[ask].steps.length - 1;
    if (reduce) { go(atEnd ? 0 : step + 1, false, true); return; }
    playing = true;
    go(atEnd ? 0 : step + 1, true, true);
  });
  prevBtn.addEventListener('click', function () { auto = false; stop(); go(step - 1, false, true); });
  nextBtn.addEventListener('click', function () { auto = false; stop(); go(step + 1, true, true); });

  // ---- life cycle ----
  buildStory();
  setView('journey');
  buildMap();
  var resizeTimer;
  window.addEventListener('resize', function () { clearTimeout(resizeTimer); resizeTimer = setTimeout(buildMap, 120); });

  // Plays by itself only while it is on screen, and only until the visitor takes over.
  var started = false, paused = false;
  var wake = function (on) {
    if (reduce) return;
    if (on && !started) { started = true; choose(0, true); return; }
    if (!on && playing) { paused = true; stop(); paint(); }
    else if (on && paused) { paused = false; playing = true; go(Math.min(step + 1, ASKS[ask].steps.length - 1), true, false); }
  };
  if ('IntersectionObserver' in window) {
    new IntersectionObserver(function (e) { wake(e[0].isIntersecting && !document.hidden); }, { threshold: 0.35 }).observe(root);
  } else { wake(true); }
  document.addEventListener('visibilitychange', function () { if (document.hidden) wake(false); else if (paused) wake(true); });
})();
