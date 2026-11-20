/* ─────────────────────────────────────────────────────────────────────────
   <Metric> wiring — converts raw values to percent + status word + bar,
   and handles the Technical view popover.

   Usage in a dashboard:
     <div class="metric" data-metric data-raw="0.18" data-domain="deviation01">
       (children rendered by this script)
     </div>

   data-domain values:
     "deviation01"   raw ∈ [0,1] where LOWER is better (Original deviation).
                     authenticity = (1 - raw) * 100.
     "score100"      raw ∈ [0,100] where HIGHER is better (Bbook score).
                     authenticity = raw.
     "growth01"      raw ∈ [0,1] where HIGHER is better (e.g. fidelity).
                     authenticity = raw * 100.

   The script can be loaded once per page; it observes any .metric in the
   DOM and (re)renders them. Idempotent — safe to call render() repeatedly.

   The math is unchanged. Only presentation is affected.
   ───────────────────────────────────────────────────────────────────────── */

(function() {
  'use strict';

  // ── Thresholds (mirror bbook/DESIGN_SYSTEM.md §2) ──
  function classifyPercent(pct) {
    if (pct == null || Number.isNaN(pct)) return 'unknown';
    if (pct >= 70) return 'calm';
    if (pct >= 40) return 'watch';
    return 'attend';
  }

  function rawToPercent(raw, domain) {
    if (raw == null || Number.isNaN(+raw)) return null;
    raw = +raw;
    switch (domain) {
      case 'deviation01':   return Math.round((1 - clamp01(raw)) * 100);
      case 'score100':      return Math.round(clampN(raw, 0, 100));
      case 'growth01':
      default:              return Math.round(clamp01(raw) * 100);
    }
  }

  function clamp01(n) { return Math.max(0, Math.min(1, n)); }
  function clampN(n, lo, hi) { return Math.max(lo, Math.min(hi, n)); }

  const STATUS_WORD = {
    calm:    'Consistent',
    watch:   'Worth a look',
    attend:  'Diverged',
    unknown: '—',
  };
  const STATUS_ICON = {
    calm:    '✓',
    watch:   '⚠',
    attend:  '✗',
    unknown: '·',
  };

  // ── Render one metric element ──
  function render(el) {
    if (!el) return;
    const raw    = el.getAttribute('data-raw');
    const domain = el.getAttribute('data-domain') || 'growth01';
    const wordOverride = el.getAttribute('data-word');     // optional custom word
    const labelOverride = el.getAttribute('data-label');   // optional context label
    const pct    = rawToPercent(raw, domain);
    const status = classifyPercent(pct);

    // Reset variant classes
    el.classList.remove('metric--calm', 'metric--watch', 'metric--attend', 'metric--loading');
    if (status !== 'unknown') el.classList.add('metric--' + status);

    el.innerHTML = ''
      + `<span class="metric-icon" aria-hidden="true">${STATUS_ICON[status]}</span>`
      + `<span class="metric-word">${wordOverride || STATUS_WORD[status]}</span>`
      + `<span class="metric-percent">${pct == null ? '—' : pct + '%'}</span>`
      + `<div class="metric-bar" role="img" aria-label="${pct == null ? 'value unknown' : pct + ' percent'}">
           <div class="metric-bar-fill" style="width:${pct == null ? 0 : pct}%"></div>
         </div>`
      + `<button type="button" class="metric-technical"
                 aria-label="Show technical detail for this metric"
                 data-raw="${raw || ''}"
                 data-domain="${domain}"
                 data-label="${labelOverride || ''}">Technical view</button>`;
  }

  // ── Single shared <dialog> popover ──
  let dlg = null;
  function ensurePopover() {
    if (dlg) return dlg;
    dlg = document.createElement('dialog');
    dlg.className = 'metric-popover';
    document.body.appendChild(dlg);
    return dlg;
  }

  function openPopover(btn) {
    const raw    = btn.getAttribute('data-raw');
    const domain = btn.getAttribute('data-domain') || 'growth01';
    const label  = btn.getAttribute('data-label') || 'Metric';
    const pct    = rawToPercent(raw, domain);
    const status = classifyPercent(pct);

    const interpretation = ({
      deviation01: 'Lower deviation means the submission stays closer to the established voice. The percentage shown is authenticity = (1 − deviation) × 100.',
      score100:    'A 0–100 authenticity score derived from the deviation. Higher means more consistent with the established voice.',
      growth01:    'A 0–1 fidelity value. The percentage shown is fidelity × 100. Higher means a clearer signal of the student\'s voice.',
    })[domain] || '';

    const d = ensurePopover();
    d.innerHTML = ''
      + `<h3>${escapeHtml(label)} — technical view</h3>`
      + `<p style="margin:6px 0;font-size:0.88rem;color:var(--text-muted,#666);line-height:1.5">${escapeHtml(interpretation)}</p>`
      + `<dl>`
      +   `<dt>Raw value</dt><dd>${escapeHtml(raw || '—')}</dd>`
      +   `<dt>Domain</dt><dd>${escapeHtml(domain)}</dd>`
      +   `<dt>Presented as</dt><dd>${pct == null ? '—' : pct + '%'} (${STATUS_WORD[status] || '—'})</dd>`
      + `</dl>`
      + `<div class="metric-popover-actions">`
      +   `<a href="/_components/explainer.html#metrics" target="_blank">How this is computed →</a>`
      +   `<button type="button" data-close>Close</button>`
      + `</div>`;
    d.querySelector('[data-close]').addEventListener('click', () => d.close());
    if (typeof d.showModal === 'function') d.showModal(); else d.setAttribute('open', '');
  }

  function escapeHtml(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, c => ({
      '&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'
    })[c]);
  }

  // ── Public API ──
  function renderAll(root) {
    (root || document).querySelectorAll('.metric[data-metric]').forEach(render);
  }

  // Delegated click handler — single listener, works for elements added later.
  document.addEventListener('click', (e) => {
    const btn = e.target.closest && e.target.closest('.metric-technical');
    if (btn) {
      e.preventDefault();
      openPopover(btn);
    }
  });

  // Initial render on DOMContentLoaded (or now if already loaded).
  if (document.readyState !== 'loading') {
    renderAll();
  } else {
    document.addEventListener('DOMContentLoaded', () => renderAll());
  }

  // Expose for dashboards that need to re-render after fetching data.
  window.OriginalMetric = {
    render,
    renderAll,
    rawToPercent,
    classifyPercent,
    STATUS_WORD,
    STATUS_ICON,
  };
})();
