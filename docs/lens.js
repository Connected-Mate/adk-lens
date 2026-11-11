/* ADK Lens site: show the real screenshots only when the files exist.
   No file, slow network or no JavaScript: the section simply stays hidden. */
(function () {
  'use strict';
  var section = document.querySelector('[data-shots]');
  if (!section) return;
  var shown = 0;
  section.querySelectorAll('[data-shot]').forEach(function (fig) {
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
      shown += 1;
      section.hidden = false;
    };
    probe.src = fig.getAttribute('data-shot');
  });
})();
