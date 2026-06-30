/* ─────────────────────────────────────────────────────────────────────────
   Tour scaffold — opt-in 60-second walkthrough.

   Behaviour:
     - On every page load, check localStorage.original_tour_{page}_seen.
       If absent, render the "Take the 60-second tour" chip top-right.
     - The chip persists until clicked (starts the tour) or its × button is
       pressed (sets the flag). The flag is also set on tour completion.
     - The active tour highlights an element with a soft gold ring + dims
       everything else with a backdrop. A small card carries prose + Next.
     - The page identifier comes from the body's data-tour-page attribute,
       set by each dashboard.

   The page identifier maps to a key in tour-content.json. Content is loaded
   lazily on first activation, not on every page load.
   ───────────────────────────────────────────────────────────────────────── */

(function() {
  'use strict';

  let CONTENT = null;        // tour-content.json once loaded
  let stopIndex = 0;
  let pageId = null;
  let stops = null;
  let backdropEl = null;
  let cardEl = null;
  let spotEl = null;

  function storageKey() {
    return 'original_tour_' + pageId + '_seen';
  }

  function dismissed() {
    try { return localStorage.getItem(storageKey()) === '1'; }
    catch (e) { return false; }
  }

  function markSeen() {
    try { localStorage.setItem(storageKey(), '1'); }
    catch (e) {}
  }

  function getPageId() {
    return (document.body && document.body.getAttribute('data-tour-page'))
        || null;
  }

  async function loadContent() {
    if (CONTENT) return CONTENT;
    try {
      const r = await fetch('/_tour/tour-content.json');
      if (!r.ok) return null;
      CONTENT = await r.json();
      return CONTENT;
    } catch (e) {
      return null;
    }
  }

  // ── The persistent chip ─────────────────────────────────────────────────
  function renderChip() {
    if (dismissed()) return;
    if (document.getElementById('tourChip')) return;
    const chip = document.createElement('button');
    chip.id = 'tourChip';
    chip.className = 'tour-chip';
    chip.type = 'button';
    chip.setAttribute('aria-label', 'Take the 60-second tour');
    chip.innerHTML =
      'Take the 60-second tour' +
      ' <span class="tour-chip-close" role="button" tabindex="0" aria-label="Dismiss the tour invitation">×</span>';
    chip.addEventListener('click', (e) => {
      if (e.target.classList.contains('tour-chip-close')) {
        markSeen();
        chip.remove();
        return;
      }
      startTour();
    });
    chip.querySelector('.tour-chip-close')
        .addEventListener('keydown', (e) => {
          if (e.key === 'Enter' || e.key === ' ') {
            e.preventDefault();
            markSeen();
            chip.remove();
          }
        });
    document.body.appendChild(chip);
  }

  // ── The tour itself ─────────────────────────────────────────────────────
  async function startTour() {
    const content = await loadContent();
    if (!content || !content[pageId]) {
      console.warn('Tour: no content for page', pageId);
      return;
    }
    stops = content[pageId].stops || [];
    if (!stops.length) return;
    stopIndex = 0;
    const chip = document.getElementById('tourChip');
    if (chip) chip.remove();
    buildOverlay();
    showStop();
  }

  function buildOverlay() {
    backdropEl = document.createElement('div');
    backdropEl.className = 'tour-backdrop';
    backdropEl.addEventListener('click', endTour);

    spotEl = document.createElement('div');
    spotEl.className = 'tour-spotlight';

    cardEl = document.createElement('div');
    cardEl.className = 'tour-card';
    cardEl.setAttribute('role', 'dialog');
    cardEl.setAttribute('aria-labelledby', 'tour-title');

    document.body.appendChild(backdropEl);
    document.body.appendChild(spotEl);
    document.body.appendChild(cardEl);
  }

  function showStop() {
    const stop = stops[stopIndex];
    if (!stop) return endTour();

    // Find the target. Selectors are comma-separated fallbacks ("first match").
    let tgt = null;
    if (stop.target) {
      try { tgt = document.querySelector(stop.target); } catch (e) {}
    }
    placeCardAndSpot(tgt);

    const isLast = stopIndex === stops.length - 1;
    cardEl.innerHTML =
      `<div class="tour-card-eye">${escapeHtml(stop.eye || '')}</div>` +
      `<h3 id="tour-title" class="tour-card-title">${escapeHtml(stop.title || '')}</h3>` +
      `<p class="tour-card-body">${escapeHtml(stop.body || '')}</p>` +
      `<div class="tour-card-actions">` +
        `<span class="tour-card-progress">${stopIndex + 1} / ${stops.length}</span>` +
        `<div class="tour-card-buttons">` +
          `<button type="button" class="tour-skip">${isLast ? 'Close' : 'Skip tour'}</button>` +
          (isLast
            ? `<button type="button" class="tour-next" data-action="finish">Finish</button>`
            : `<button type="button" class="tour-next" data-action="next">Next →</button>`) +
        `</div>` +
      `</div>`;

    cardEl.querySelector('.tour-skip').addEventListener('click', endTour);
    cardEl.querySelector('.tour-next').addEventListener('click', (e) => {
      const a = e.target.getAttribute('data-action');
      if (a === 'finish') endTour();
      else { stopIndex += 1; showStop(); }
    });
    cardEl.querySelector('.tour-next').focus();
  }

  function placeCardAndSpot(tgt) {
    if (!tgt) {
      // No target found — centre the card with no spotlight.
      spotEl.style.display = 'none';
      cardEl.style.position = 'fixed';
      cardEl.style.top = '50%';
      cardEl.style.left = '50%';
      cardEl.style.transform = 'translate(-50%, -50%)';
      return;
    }
    spotEl.style.display = 'block';
    const r = tgt.getBoundingClientRect();
    const pad = 8;
    spotEl.style.left   = (r.left   - pad) + 'px';
    spotEl.style.top    = (r.top    - pad) + 'px';
    spotEl.style.width  = (r.width  + pad * 2) + 'px';
    spotEl.style.height = (r.height + pad * 2) + 'px';

    // Position the card below the target if there's room, otherwise above.
    const cardW = 380;
    const cardH = 200;
    let left = r.left + r.width / 2 - cardW / 2;
    let top  = r.bottom + 18;
    if (top + cardH > window.innerHeight) top = Math.max(12, r.top - cardH - 18);
    left = Math.max(12, Math.min(left, window.innerWidth - cardW - 12));
    cardEl.style.position  = 'fixed';
    cardEl.style.top       = top + 'px';
    cardEl.style.left      = left + 'px';
    cardEl.style.transform = 'none';

    // Scroll target into view if needed.
    if (r.top < 0 || r.bottom > window.innerHeight) {
      tgt.scrollIntoView({ behavior: 'smooth', block: 'center' });
    }
  }

  function endTour() {
    markSeen();
    if (backdropEl) backdropEl.remove();
    if (spotEl)     spotEl.remove();
    if (cardEl)     cardEl.remove();
    backdropEl = spotEl = cardEl = null;
    stops = null;
    stopIndex = 0;
  }

  function escapeHtml(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, c => ({
      '&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'
    })[c]);
  }

  // ── Bootstrap ───────────────────────────────────────────────────────────
  function init() {
    pageId = getPageId();
    if (!pageId) return;            // dashboard didn't opt in
    renderChip();
    // Public API for "Restart tour" links / future use
    window.OriginalTour = {
      start:  startTour,
      reset:  function () {
        try { localStorage.removeItem(storageKey()); } catch (e) {}
        renderChip();
      },
      end:    endTour,
    };
  }

  if (document.readyState !== 'loading') init();
  else document.addEventListener('DOMContentLoaded', init);
})();
