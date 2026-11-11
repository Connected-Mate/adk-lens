/* Connected Mate project site — shared behaviour.
   Every feature fails safe: no storage, no network, no clipboard → the page still works. */
(function () {
  'use strict';

  // Remember an explicit language choice so the root redirect never fights the visitor.
  document.querySelectorAll('[data-lang][data-lang-key]').forEach(function (link) {
    link.addEventListener('click', function () {
      try { localStorage.setItem(link.getAttribute('data-lang-key'), link.getAttribute('data-lang')); } catch (e) {}
    });
  });

  // Download buttons: if the GitHub repo has no release yet, say "coming soon" instead of a 404.
  var dl = document.querySelectorAll('[data-download][data-repo]');
  if (dl.length && window.fetch) {
    var repo = dl[0].getAttribute('data-repo');
    var ctrl = window.AbortController ? new AbortController() : null;
    var timer = setTimeout(function () { if (ctrl) ctrl.abort(); }, 6000);
    fetch('https://api.github.com/repos/' + repo + '/releases/latest', {
      headers: { Accept: 'application/vnd.github+json' },
      signal: ctrl ? ctrl.signal : undefined
    }).then(function (res) {
      clearTimeout(timer);
      if (res.status !== 404) return; // 200 = release exists; 403/5xx = unknown → keep the link
      dl.forEach(function (a) {
        a.setAttribute('href', a.getAttribute('data-releases'));
        a.classList.add('is-soon');
        var label = a.querySelector('[data-download-label]');
        if (label) label.textContent = a.getAttribute('data-soon');
      });
      var note = document.querySelector('[data-download-note]');
      if (note) { note.textContent = dl[0].getAttribute('data-soon-note'); note.hidden = false; }
    }).catch(function () { clearTimeout(timer); });
  }

  // Copy-the-command buttons.
  document.querySelectorAll('[data-copy]').forEach(function (btn) {
    var original = btn.textContent;
    var busy = false;
    btn.addEventListener('click', function () {
      if (busy) return;
      var text = btn.getAttribute('data-copy');
      var done = function () {
        busy = true;
        announce(btn.getAttribute('data-copied'));
        btn.textContent = btn.getAttribute('data-copied');
        setTimeout(function () { btn.textContent = original; busy = false; }, 1800);
      };
      if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(text).then(done, function () { legacyCopy(text) ? done() : selectCode(btn); });
      } else {
        legacyCopy(text) ? done() : selectCode(btn);
      }
    });
  });
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
  function selectCode(btn) {
    var code = btn.parentNode.querySelector('code') || document.querySelector('.prompt__box code');
    if (!code || !window.getSelection) return;
    var range = document.createRange();
    range.selectNodeContents(code);
    var sel = window.getSelection();
    sel.removeAllRanges();
    sel.addRange(range);
  }

  // Scroll reveal: sections glide in once. Skipped entirely with reduced motion or without IO.
  var reduce = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  var reveals = document.querySelectorAll('[data-reveal]');
  if (!reduce && 'IntersectionObserver' in window && reveals.length) {
    var io = new IntersectionObserver(function (entries) {
      entries.forEach(function (e) {
        if (e.isIntersecting) { e.target.classList.add('is-in'); io.unobserve(e.target); }
      });
    }, { rootMargin: '0px 0px -10% 0px' });
    reveals.forEach(function (el) { el.classList.add('will-reveal'); io.observe(el); });
  }

  // Quick-nav capsule appears once the hero is scrolled past.
  var capsule = document.querySelector('.capsule');
  var hero = document.querySelector('.hero');
  if (capsule && hero && 'IntersectionObserver' in window) {
    new IntersectionObserver(function (entries) {
      capsule.classList.toggle('is-on', !entries[0].isIntersecting);
    }).observe(hero);
  }
})();
