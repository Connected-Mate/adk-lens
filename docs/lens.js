/* ADK Lens site behaviour. Original code. Every feature fails safe:
   no JavaScript, no storage, no clipboard, no canvas: the page still reads and works. */
(function () {
  'use strict';
  var reduce = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  // Remember an explicit language choice so the automatic redirect never fights the visitor.
  document.querySelectorAll('[data-lang][data-lang-key]').forEach(function (link) {
    link.addEventListener('click', function () {
      try { localStorage.setItem(link.getAttribute('data-lang-key'), link.getAttribute('data-lang')); } catch (e) {}
    });
  });

  // Header hairline once the page is scrolled.
  var top = document.querySelector('.top');
  if (top) {
    var stuck = function () { top.classList.toggle('is-stuck', window.scrollY > 8); };
    window.addEventListener('scroll', stuck, { passive: true });
    stuck();
  }

  // Copy the prompt. The button keeps its width; the label swaps, and a live region says it.
  var live;
  function announce(msg) {
    if (!live) {
      live = document.createElement('p');
      live.className = 'sr-only';
      live.setAttribute('aria-live', 'polite');
      document.body.appendChild(live);
    }
    live.textContent = '';
    setTimeout(function () { live.textContent = msg; }, 50);
  }
  function legacyCopy(text) {
    try {
      var ta = document.createElement('textarea');
      ta.value = text;
      ta.setAttribute('readonly', '');
      ta.style.cssText = 'position:fixed;top:0;left:0;opacity:0';
      document.body.appendChild(ta);
      ta.select();
      var ok = document.execCommand('copy');
      document.body.removeChild(ta);
      return ok;
    } catch (e) { return false; }
  }
  function selectPrompt() {
    var code = document.querySelector('.prompt');
    if (!code || !window.getSelection) return;
    var range = document.createRange();
    range.selectNodeContents(code);
    var sel = window.getSelection();
    sel.removeAllRanges();
    sel.addRange(range);
    code.scrollIntoView({ block: 'center' });
  }
  document.querySelectorAll('[data-copy]').forEach(function (btn) {
    var timer;
    btn.addEventListener('click', function () {
      var text = btn.getAttribute('data-copy');
      var done = function () {
        btn.classList.add('is-copied');
        announce(btn.getAttribute('data-copied'));
        clearTimeout(timer);
        timer = setTimeout(function () { btn.classList.remove('is-copied'); }, 2200);
      };
      if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(text).then(done, function () { legacyCopy(text) ? done() : selectPrompt(); });
      } else {
        legacyCopy(text) ? done() : selectPrompt();
      }
    });
  });

  // Real screenshots: shown only when the files exist.
  var shots = document.querySelector('[data-shots]');
  if (shots) {
    shots.querySelectorAll('[data-shot]').forEach(function (fig) {
      var probe = new Image();
      probe.onload = function () {
        if (!probe.naturalWidth) return;
        var img = document.createElement('img');
        img.src = fig.getAttribute('data-shot');
        img.alt = fig.getAttribute('data-alt') || '';
        img.width = probe.naturalWidth;
        img.height = probe.naturalHeight;
        img.loading = 'lazy';
        img.decoding = 'async';
        fig.insertBefore(img, fig.firstChild);
        fig.hidden = false;
        shots.hidden = false;
      };
      probe.src = fig.getAttribute('data-shot');
    });
  }

  // Scroll zoom for browsers without CSS scroll-driven animations.
  var cssScroll = window.CSS && CSS.supports && CSS.supports('animation-timeline: view()');
  var zooms = document.querySelectorAll('.zoom');
  if (!reduce && !cssScroll && zooms.length) {
    var ticking = false;
    var paint = function () {
      ticking = false;
      var vh = window.innerHeight;
      zooms.forEach(function (el) {
        var r = el.getBoundingClientRect();
        var p = Math.min(1, Math.max(0, (vh - r.top) / (vh * 0.42 + r.height * 0.42)));
        el.style.transform = 'scale(' + (0.86 + 0.14 * p).toFixed(4) + ')';
        if (el.firstElementChild) el.firstElementChild.style.transform = 'scale(' + (1.14 - 0.14 * p).toFixed(4) + ')';
      });
    };
    var ask = function () { if (!ticking) { ticking = true; requestAnimationFrame(paint); } };
    window.addEventListener('scroll', ask, { passive: true });
    window.addEventListener('resize', ask);
    paint();
  }

  // Hero field: fine coloured dashes drifting on rings around the title.
  var canvas = document.querySelector('canvas.field');
  var ctx = canvas && canvas.getContext && canvas.getContext('2d');
  if (ctx) {
    var hero = canvas.parentNode;
    var dpr = Math.min(window.devicePixelRatio || 1, 2);
    var W = 0, H = 0, parts = [], running = false, visible = true, raf = 0;
    var px = 0, py = 0, tx = 0, ty = 0;
    var dark = window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)');
    var COLORS = [[66, 133, 244], [66, 133, 244], [234, 67, 53], [251, 188, 4], [66, 133, 244], [140, 146, 160]];

    var build = function () {
      var rect = hero.getBoundingClientRect();
      W = rect.width; H = rect.height;
      canvas.width = Math.round(W * dpr); canvas.height = Math.round(H * dpr);
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      parts = [];
      var maxR = Math.hypot(W, H) * 0.56;
      var seed = 7;
      var rand = function () { seed = (seed * 16807) % 2147483647; return seed / 2147483647; };
      for (var r = 150; r < maxR; r += 30) {
        var n = Math.floor((2 * Math.PI * r) / 56);
        for (var i = 0; i < n; i++) {
          var a = (i / n) * Math.PI * 2 + rand() * 0.12 + r * 0.011;
          parts.push({ r: r + (rand() - 0.5) * 16, a: a, len: 2 + rand() * 4.5, w: 1 + rand() * 0.9, ph: rand() * 6.283, c: COLORS[Math.floor(rand() * COLORS.length)] });
        }
      }
    };

    var draw = function (ms) {
      var t = ms / 1000;
      px += (tx - px) * 0.04; py += (ty - py) * 0.04;
      var cx = W * 0.5 + px, cy = H * 0.46 + py;
      var boost = dark && dark.matches ? 1.25 : 1;
      ctx.clearRect(0, 0, W, H);
      ctx.lineCap = 'round';
      for (var i = 0; i < parts.length; i++) {
        var p = parts[i];
        var a = p.a + t * (9 / p.r);                       // inner rings turn a little faster
        var r = p.r + Math.sin(t * 0.5 + p.r * 0.018) * 9;  // slow breathing
        var x = cx + Math.cos(a) * r, y = cy + Math.sin(a) * r * 0.86;
        if (x < -10 || x > W + 10 || y < -10 || y > H + 10) continue;
        var wave = 0.5 + 0.5 * Math.sin(a * 2 - t * 0.35 + p.ph * 0.25); // a soft band of light going round
        var alpha = (0.16 + 0.74 * wave * wave) * boost;
        var dx = -Math.sin(a) * p.len, dy = Math.cos(a) * p.len * 0.86;
        ctx.strokeStyle = 'rgba(' + p.c[0] + ',' + p.c[1] + ',' + p.c[2] + ',' + Math.min(1, alpha).toFixed(3) + ')';
        ctx.lineWidth = p.w;
        ctx.beginPath(); ctx.moveTo(x - dx / 2, y - dy / 2); ctx.lineTo(x + dx / 2, y + dy / 2); ctx.stroke();
      }
    };
    var loop = function (ms) { draw(ms); raf = running ? requestAnimationFrame(loop) : 0; };
    var sync = function () {
      var want = !reduce && visible && !document.hidden;
      if (want && !running) { running = true; raf = requestAnimationFrame(loop); }
      else if (!want && running) { running = false; cancelAnimationFrame(raf); }
    };

    build();
    draw(reduce ? 4000 : 0);
    if ('IntersectionObserver' in window) {
      new IntersectionObserver(function (e) { visible = e[0].isIntersecting; sync(); }).observe(hero);
    }
    document.addEventListener('visibilitychange', sync);
    var resizeTimer;
    window.addEventListener('resize', function () {
      clearTimeout(resizeTimer);
      resizeTimer = setTimeout(function () { build(); if (!running) draw(4000); }, 150);
    });
    if (!reduce && window.matchMedia('(hover: hover) and (pointer: fine)').matches) {
      hero.addEventListener('pointermove', function (e) {
        var rect = hero.getBoundingClientRect();
        tx = ((e.clientX - rect.left) / rect.width - 0.5) * -36;
        ty = ((e.clientY - rect.top) / rect.height - 0.5) * -28;
      });
      hero.addEventListener('pointerleave', function () { tx = 0; ty = 0; });
    }
    sync();
  }
})();
