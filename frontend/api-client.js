/**
 * api-client.js — Live data bridge between Original backend and frontend pages.
 *
 * On DOMContentLoaded, fetches POST /students/{id}/score from the matching
 * FastAPI demo server and patches page-specific DOM elements with live values.
 * Falls back gracefully if the server is offline.
 *
 * Supported pages: original-review.html, original-features.html,
 *                  original-quantum.html, original-decomposition.html
 *
 * API resolution order:
 *   1. ?api=http://host:port query parameter
 *   2. window.ORIGINAL_API_BASE global
 *   3. localStorage["original_api_base"]
 *   4. Same-origin when served over http(s)
 *   5. http://localhost:8000 fallback for file:// usage
 *
 * Usage: <script src="api-client.js"></script> immediately before </body>
 */

(function () {
  'use strict';

  // ── Configuration ─────────────────────────────────────────────────────────────

  function stripTrailingSlash(url) {
    return url ? url.replace(/\/+$/, '') : url;
  }

  function resolveApiBase() {
    var override = null;

    if (typeof window !== 'undefined') {
      try {
        var params = new URLSearchParams(window.location.search || '');
        override = params.get('api');
      } catch (_err) {}

      if (override) {
        override = stripTrailingSlash(override);
        try { window.localStorage.setItem('original_api_base', override); } catch (_err) {}
        return override;
      }

      if (window.ORIGINAL_API_BASE) {
        return stripTrailingSlash(window.ORIGINAL_API_BASE);
      }

      try {
        override = window.localStorage.getItem('original_api_base');
      } catch (_err) {}
      if (override) return stripTrailingSlash(override);

      if (/^https?:$/.test(window.location.protocol) && window.location.origin) {
        return stripTrailingSlash(window.location.origin);
      }
    }

    return 'http://localhost:8000';
  }

  var ORIGINAL_API = resolveApiBase();

  // ── Dynamic student ID resolution ─────────────────────────────────────────────
  function getStudentId() {
    try {
      var params = new URLSearchParams(window.location.search || '');
      var studentId = params.get('student');
      if (studentId) return studentId;
    } catch (_err) {}
    throw new Error('Student ID is required. Pass ?student=<id> in the URL or set window.STUDENT_ID');
  }

  // ── Feature metadata (matches backend ALL_FEATURE_CODES order exactly) ────────

  var CODES = [
    // Tier 1 — Surface (9)
    'type_token_ratio', 'hapax_legomena_rate', 'mean_sentence_length',
    'sentence_length_variance', 'function_word_ratio', 'passive_voice_ratio',
    'modal_verb_ratio', 'stop_word_ratio', 'avg_word_length',
    // Tier 2 — Discourse (13)
    'discourse_marker_density', 'additive_ratio', 'adversative_ratio', 'causal_ratio',
    'temporal_ratio', 'thematic_progression_score', 'pronoun_reference_density',
    'lexical_chain_density', 'paragraph_topic_position', 'avg_paragraph_length',
    'sentence_opener_variety', 'cohesion_device_ratio', 'transition_density',
    // Tier 3 — Rhetorical (12)
    'epistemic_certainty_ratio', 'hedging_density', 'assertion_density',
    'source_integration_style', 'counter_argument_ratio', 'claim_density',
    'question_ratio', 'imperative_density', 'first_person_ratio',
    'appeal_to_authority_density', 'conclusion_strategy_score', 'theological_register_score',
  ];

  var NAMES = [
    'Type-Token Ratio', 'Hapax Legomena Rate', 'Mean Sentence Length',
    'Sentence Length Variance', 'Function Word Ratio', 'Passive Voice Ratio',
    'Modal Verb Ratio', 'Stop Word Ratio', 'Avg Word Length',
    'Discourse Marker Density', 'Additive Ratio', 'Adversative Ratio', 'Causal Ratio',
    'Temporal Ratio', 'Thematic Progression', 'Pronoun Ref. Density',
    'Lexical Chain Density', 'Paragraph Topic Pos.', 'Avg Paragraph Length',
    'Sentence Opener Variety', 'Cohesion Device Ratio', 'Transition Density',
    'Epistemic Certainty', 'Hedging Density', 'Assertion Density',
    'Source Integration Style', 'Counter-Argument Ratio', 'Claim Density',
    'Question Ratio', 'Imperative Density', 'First-Person Ratio',
    'Authority Appeal Density', 'Conclusion Strategy', 'Theological Register',
  ];

  var DESCS = [
    'Lexical diversity', 'Once-occurring word rate', 'Avg words per sentence',
    'Sentence length spread', 'Grammatical word frequency', 'Passive constructions / sentences',
    'Modal verbs / verb-like tokens', 'High-frequency words', 'Characters per word token',
    'Connectives per 100 words', 'Additive markers / all markers', 'However / but / yet markers',
    'Therefore / because / thus', 'First / then / finally', 'Linear vs. constant-theme flow',
    'Anaphoric pronouns per sentence', 'Repeated content words / sentence', 'Fronted topic sentences',
    'Mean sentences per paragraph', 'Shannon entropy of openers', 'All cohesion devices / words',
    'Explicit transitions / boundaries', 'Assert / (assert + hedge)', 'Hedge markers per 100 words',
    'Strong assertion markers / 100w', 'Cite-move → synthesise scale', 'Adversative sentences / total',
    'Toulmin claim markers / 100w', 'Interrogative sentences / total', 'Imperative constructions / 100w',
    '1st-person / all pronouns', 'Citation/authority language / 100w', 'Summary → implication → open',
    'Seminary vocabulary density',
  ];

  var TIERS = [].concat(
    Array(9).fill('t1'),
    Array(13).fill('t2'),
    Array(12).fill('t3')
  );

  // ── API fetch ─────────────────────────────────────────────────────────────────

  /**
   * Normalise a production ScoreResponse (flat fields) into the nested
   * Layer7OutputResponse shape that the patchers were written against.
   * This lets the patchers remain unchanged while the backend evolves.
   */
  function _normaliseScoreResponse(data) {
    if (data && data.authorship) return data; // already in legacy nested format
    return {
      authorship: {
        deviation_score:        data.deviation_score,
        authorship_probability: data.authorship_probability,
      },
      interference: data.interference || { destructive_features: [], constructive_features: [] },
      baseline_confidence: data.baseline_confidence || { purity: 0, sample_count: 0, authenticated_count: 0 },
      recommendation: { action: data.recommended_action || 'no_action' },
      feature_vector:   data.feature_vector  || {},
      baseline_vector:  data.baseline_vector || {},
      human_explanation: data.human_explanation || null,
      catastrophic_drift: data.catastrophic_drift || false,
      catastrophic_drift_rms_z: data.catastrophic_drift_rms_z || 0,
    };
  }

  function fetchScore(options) {
    options = options || {};
    var studentId = options.studentId || getStudentId();
    var submissionText = options.submissionText;
    var assignment = options.assignment || 'Auto-submitted work';

    if (!submissionText) {
      return Promise.reject(new Error('submissionText is required in fetchScore options'));
    }

    var body = JSON.stringify({ text: submissionText, assignment: assignment });

    // Production API path (requires auth). Falls back to unauthenticated for
    // demo mode (ENVIRONMENT=development + DEMO_MODE=true) or file:// usage.
    var prodPath = '/api/v1/submissions/' + studentId + '/score';

    var doFetch;
    if (window.OriginalAuth && window.OriginalAuth.isAuthenticated && window.OriginalAuth.isAuthenticated()) {
      doFetch = window.OriginalAuth.apiFetch(prodPath, { method: 'POST', body: body });
    } else {
      doFetch = fetch(ORIGINAL_API + prodPath, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: body,
      });
    }

    return doFetch
      .then(function (resp) {
        if (!resp.ok) throw new Error('HTTP ' + resp.status);
        return resp.json();
      })
      .then(_normaliseScoreResponse);
  }

  // ── Accessibility helpers ─────────────────────────────────────────────────────

  function injectA11yStyles() {
    var s = document.createElement('style');
    s.textContent = [
      ':focus-visible{',
      '  outline:3px solid #1a6fb5;',
      '  outline-offset:2px;',
      '  border-radius:2px;',
      '}',
      'a:focus-visible,button:focus-visible,input:focus-visible,',
      'select:focus-visible,textarea:focus-visible,[tabindex]:focus-visible{',
      '  outline:3px solid #1a6fb5;',
      '  outline-offset:2px;',
      '}',
      '#orig-skip-link{',
      '  position:absolute;left:-999px;top:auto;width:1px;height:1px;',
      '  overflow:hidden;z-index:9999;',
      '  font-family:Inter,system-ui,sans-serif;font-size:0.875rem;font-weight:600;',
      '}',
      '#orig-skip-link:focus{',
      '  left:1rem;top:1rem;width:auto;height:auto;',
      '  padding:0.5rem 1rem;border-radius:4px;',
      '  background:#1a130a;color:#f7f3ea;',
      '  text-decoration:none;',
      '}',
    ].join('\n');
    document.head.appendChild(s);
  }

  function injectSkipLink() {
    var main = document.querySelector('main') || document.querySelector('.content') ||
               document.querySelector('.main');
    if (!main) return;
    if (!main.id) main.id = 'orig-main-content';
    var a = document.createElement('a');
    a.id   = 'orig-skip-link';
    a.href = '#' + main.id;
    a.textContent = 'Skip to main content';
    document.body.insertBefore(a, document.body.firstChild);
  }

  // ── Loading overlay ────────────────────────────────────────────────────────────

  function showLoading() {
    var overlay = document.createElement('div');
    overlay.id = 'orig-loading';
    overlay.setAttribute('role', 'status');
    overlay.setAttribute('aria-label', 'Loading live data from Original API');
    overlay.style.cssText = [
      'position:fixed;bottom:1.5rem;right:1.5rem;z-index:8000;',
      'display:flex;align-items:center;gap:0.5rem;',
      'background:#fff;border:1px solid #e2dccf;',
      'border-radius:20px;padding:0.35rem 0.9rem 0.35rem 0.6rem;',
      'box-shadow:0 2px 8px rgba(0,0,0,0.08);',
      'font-family:Inter,system-ui,sans-serif;',
      'font-size:0.72rem;font-weight:600;letter-spacing:0.08em;',
      'text-transform:uppercase;color:#5a4030;',
    ].join('');

    // CSS keyframe spinner
    var spinStyle = document.createElement('style');
    spinStyle.textContent = '@keyframes orig-spin{to{transform:rotate(360deg)}}';
    document.head.appendChild(spinStyle);

    var spinner = document.createElement('span');
    spinner.setAttribute('aria-hidden', 'true');
    spinner.style.cssText = [
      'display:inline-block;width:12px;height:12px;',
      'border:2px solid rgba(26,111,181,0.2);',
      'border-top-color:#1a6fb5;border-radius:50%;',
      'animation:orig-spin 0.7s linear infinite;',
    ].join('');

    overlay.appendChild(spinner);
    overlay.appendChild(document.createTextNode('Loading…'));
    document.body.appendChild(overlay);
    return overlay;
  }

  function hideLoading(overlay) {
    if (overlay && overlay.parentNode) overlay.parentNode.removeChild(overlay);
  }

  // ── ARIA error banner ──────────────────────────────────────────────────────────

  function showErrorBanner(err) {
    var banner = document.createElement('div');
    banner.setAttribute('role', 'alert');
    banner.setAttribute('aria-live', 'assertive');
    banner.style.cssText = [
      'position:fixed;bottom:1.5rem;right:1.5rem;z-index:8000;',
      'max-width:340px;padding:0.75rem 1rem;',
      'background:#fdf2f2;border:1px solid rgba(192,57,43,0.35);border-radius:6px;',
      'box-shadow:0 2px 8px rgba(0,0,0,0.08);',
      'font-family:Inter,system-ui,sans-serif;font-size:0.82rem;',
      'color:#8b1c14;line-height:1.45;',
    ].join('');

    var msg = err && err.message ? err.message : String(err);
    banner.innerHTML =
      '<strong style="display:block;margin-bottom:0.2rem;">API offline — showing static data</strong>' +
      '<span style="opacity:0.8;">' + msg + '</span>';

    // Auto-dismiss after 8 s
    var closeBtn = document.createElement('button');
    closeBtn.setAttribute('aria-label', 'Dismiss');
    closeBtn.style.cssText = [
      'position:absolute;top:0.4rem;right:0.5rem;',
      'background:none;border:none;cursor:pointer;',
      'font-size:1rem;line-height:1;color:#8b1c14;opacity:0.6;',
    ].join('');
    closeBtn.textContent = '×';
    closeBtn.onclick = function () { banner.remove(); };
    banner.style.position = 'fixed';
    banner.appendChild(closeBtn);

    document.body.appendChild(banner);
    setTimeout(function () { if (banner.parentNode) banner.remove(); }, 8000);
  }

  // ── Live status badge ─────────────────────────────────────────────────────────

  function showBadge(live) {
    var topbar = document.querySelector('.topbar-right') || document.querySelector('.topbar');
    if (!topbar) return;
    var chip = document.createElement('span');
    // role="status" + aria-live so screen readers announce the data state
    chip.setAttribute('role', 'status');
    chip.setAttribute('aria-live', 'polite');
    chip.style.cssText = [
      'font-size:0.62rem; font-weight:700; letter-spacing:0.12em;',
      'text-transform:uppercase; padding:0.2rem 0.65rem;',
      'border-radius:20px; flex-shrink:0;',
      live
        ? 'background:rgba(42,107,69,0.12);color:#2a6b45;border:1px solid rgba(42,107,69,0.3);'
        : 'background:rgba(192,57,43,0.08);color:#c0392b;border:1px solid rgba(192,57,43,0.2);',
    ].join('');
    chip.title = live ? 'Live data from Original API' : 'API offline — showing static data';
    chip.textContent = live ? '● Live' : '○ Offline';
    topbar.insertBefore(chip, topbar.firstChild);
  }

  // ── Helpers ───────────────────────────────────────────────────────────────────

  function devColour(dev) {
    if (dev >= 0.75) return '#c0392b';  // red   — passes AA on cream (5.74:1)
    if (dev >= 0.55) return '#916020';  // amber — passes AA on cream (4.86:1)
    return '#2a6b45';                   // green — passes AA on cream (6.09:1)
  }

  function devLabel(dev) {
    if (dev >= 0.75) return 'High';
    if (dev >= 0.55) return 'Elevated';
    if (dev >= 0.40) return 'Moderate';
    return 'Low';
  }

  function devThreshold(dev) {
    if (dev >= 0.75) return 0.75;
    if (dev >= 0.55) return 0.55;
    return 0.40;
  }

  // ── Patcher: original-review.html ────────────────────────────────────────────

  function patchReview(data) {
    var auth = data.authorship;
    var ifd  = data.interference;
    var dev  = auth.deviation_score;
    var nDestr = ifd.destructive_features.length;

    // Score ring value and label
    var scoreVal = document.querySelector('.score-value');
    if (scoreVal) {
      scoreVal.textContent = dev.toFixed(2);
      scoreVal.style.color = devColour(dev);
    }
    var scoreLabel = document.querySelector('.score-label');
    if (scoreLabel) scoreLabel.style.color = devColour(dev);

    var scoreSub = document.querySelector('.score-sub');
    if (scoreSub) {
      scoreSub.textContent = devLabel(dev) + ' — above ' + devThreshold(dev).toFixed(2) + ' threshold';
    }

    // Score ring border + background
    var ring = document.querySelector('.score-ring');
    if (ring) {
      var rgb = dev >= 0.75 ? '192,57,43' : dev >= 0.55 ? '201,160,40' : '42,107,69';
      ring.style.borderColor = 'rgba(' + rgb + ',0.3)';
      ring.style.background  = 'rgba(' + rgb + ',0.07)';
    }

    // Alert bar — replace the span content entirely (it contains the em)
    var alertSpan = document.querySelector('.review-alert-bar span');
    if (alertSpan) {
      var severity = dev >= 0.75 ? 'High' : 'Elevated';
      alertSpan.innerHTML =
        severity + ' deviation detected' +
        ' <em>— ' + nDestr + ' of 34 stylometric features outside baseline range</em>';
    }

    // Deep-analysis card subtitles (the coloured "17 destructive →" links)
    document.querySelectorAll('[style*="destructive"]').forEach(function (el) {
      if (el.textContent.includes('destructive')) {
        el.textContent = nDestr + ' destructive →';
      }
    });

    // Purity and sample info in the right sidebar
    var bc = data.baseline_confidence;
    document.querySelectorAll('strong').forEach(function (el) {
      var t = el.textContent.trim();
      if (t.match(/^\d+ authenticated$/)) {
        el.textContent = bc.authenticated_count + ' authenticated';
      }
      if (t.match(/^0\.\d{3}$/) && parseFloat(t) < 0.6) {
        el.textContent = bc.purity.toFixed(3);
      }
    });
  }

  // ── Patcher: original-features.html ──────────────────────────────────────────

  function patchFeatures(data) {
    // FEATURES is a const object defined in the page script — we can mutate it.
    if (typeof FEATURES === 'undefined' || typeof renderAll !== 'function') return;

    var fv = data.feature_vector;
    var bv = data.baseline_vector;
    var destructiveCodes = {};
    data.interference.destructive_features.forEach(function (f) {
      destructiveCodes[f.code] = true;
    });

    function buildFeatures(startIdx, endIdx) {
      var result = [];
      for (var i = startIdx; i < endIdx; i++) {
        var code = CODES[i];
        result.push({
          name:    NAMES[i],
          code:    code,
          desc:    DESCS[i],
          base:    bv[code] !== undefined ? bv[code] : 0,
          sub:     fv[code] !== undefined ? fv[code] : 0,
          flagged: !!destructiveCodes[code],
        });
      }
      return result;
    }

    FEATURES.tier1.features = buildFeatures(0, 9);
    FEATURES.tier2.features = buildFeatures(9, 22);
    FEATURES.tier3.features = buildFeatures(22, 34);

    renderAll();

    // Patch deviation score (the large "0.5949" text)
    var dev = data.authorship.deviation_score;
    document.querySelectorAll('*').forEach(function (el) {
      if (el.children.length === 0 && el.textContent.trim() === '0.5949') {
        el.textContent = dev.toFixed(4);
        el.style.color = devColour(dev);
      }
    });

    // Patch authorship probability display "40.5%"
    document.querySelectorAll('strong').forEach(function (el) {
      if (el.textContent.trim().match(/^\d+\.\d+%$/)) {
        el.textContent = (data.authorship.authorship_probability * 100).toFixed(1) + '%';
      }
    });

    // Patch sample count
    var bc = data.baseline_confidence;
    document.querySelectorAll('strong').forEach(function (el) {
      if (el.textContent.trim().match(/^\d+ authenticated$/)) {
        el.textContent = bc.authenticated_count + ' authenticated';
      }
    });

    // Patch purity
    document.querySelectorAll('strong').forEach(function (el) {
      if (el.textContent.trim().match(/^0\.\d{3}$/) && parseFloat(el.textContent) < 0.5) {
        el.textContent = bc.purity.toFixed(3);
      }
    });

    // Update the SVG gauge arc (stroke-dasharray 213.6 means r=34 circle, 2π×34)
    var gaugeArc = document.querySelector('circle[stroke="#c9a028"][stroke-dasharray]');
    if (gaugeArc) {
      var circ = parseFloat(gaugeArc.getAttribute('stroke-dasharray'));
      if (circ > 0) {
        gaugeArc.setAttribute('stroke-dashoffset', (circ * (1 - dev)).toFixed(1));
      }
    }

    // Update the FLAG/CLEAR label in the gauge
    var gaugeLabel = document.querySelector('[style*="0.75rem"][style*="amber"]');
    if (gaugeLabel) {
      var label = dev >= 0.75 ? 'ESCALATE' : dev >= 0.55 ? 'FLAG' : dev >= 0.40 ? 'MONITOR' : 'CLEAR';
      gaugeLabel.textContent = label;
      gaugeLabel.style.color = devColour(dev);
    }
  }

  // ── Patcher: original-quantum.html ───────────────────────────────────────────

  function patchQuantum(data) {
    // PSI and XI are const arrays — we can mutate elements in-place
    if (typeof PSI === 'undefined' || typeof XI === 'undefined') return;

    var fv = data.feature_vector;
    var bv = data.baseline_vector;

    // Update vectors in-place
    for (var i = 0; i < CODES.length; i++) {
      var code = CODES[i];
      if (bv[code] !== undefined) PSI[i] = bv[code];
      if (fv[code] !== undefined) XI[i]  = fv[code];
    }

    // Re-render heatmap
    var heatmapEl = document.getElementById('heatmap');
    var labelsEl  = document.getElementById('heatmap-labels');
    var tooltipEl = document.getElementById('tooltip');

    if (heatmapEl && labelsEl && typeof TIER_COLORS !== 'undefined') {
      heatmapEl.innerHTML = '';
      labelsEl.innerHTML  = '';

      PSI.forEach(function (v, idx) {
        var sub   = XI[idx];
        var diff  = sub - v;
        var isDev = Math.abs(diff) > 0.12;

        var col = document.createElement('div');
        col.style.cssText =
          'display:flex;flex-direction:column;align-items:center;gap:2px;' +
          'position:relative;cursor:default;';

        // Baseline bar
        var baseAlpha = (0.20 + v * 0.70).toFixed(2);
        var baseH     = Math.round(16 + v * 40);
        var baseBar   = document.createElement('div');
        baseBar.style.cssText =
          'width:10px;height:' + baseH + 'px;border-radius:2px 2px 0 0;' +
          'background:' + TIER_COLORS[idx] + ';opacity:' + baseAlpha + ';align-self:flex-end;';

        // Submission tick marker
        var subH      = Math.round(16 + sub * 40);
        var subColor  = isDev ? (diff < 0 ? '#c0392b' : '#2a6b45') : '#c9a028';
        var marker    = document.createElement('div');
        marker.style.cssText =
          'position:absolute;bottom:0;left:50%;' +
          'transform:translateX(-50%) translateY(' + (-subH) + 'px);' +
          'width:14px;height:2px;border-radius:1px;background:' + subColor + ';opacity:0.9;';

        col.appendChild(baseBar);
        col.appendChild(marker);

        // Tooltip
        if (tooltipEl) {
          (function (i, v, sub, diff, subColor) {
            col.addEventListener('mousemove', function (e) {
              var dir = diff > 0.01
                ? '+' + (diff * 100).toFixed(0) + '% above baseline'
                : diff < -0.01
                  ? (diff * 100).toFixed(0) + '% below baseline'
                  : 'within baseline range';
              tooltipEl.innerHTML =
                '<strong>' + NAMES[i] + '</strong><br>' +
                'Baseline: ' + v.toFixed(3) + ' &nbsp;·&nbsp; Submission: ' + sub.toFixed(3) + '<br>' +
                '<span style="color:' + subColor + '">' + dir + '</span>';
              tooltipEl.classList.add('visible');
              tooltipEl.style.left = (e.clientX + 12) + 'px';
              tooltipEl.style.top  = (e.clientY - 48) + 'px';
            });
            col.addEventListener('mouseleave', function () {
              tooltipEl.classList.remove('visible');
            });
          })(idx, v, sub, diff, subColor);
        }

        heatmapEl.appendChild(col);

        var lbl = document.createElement('div');
        lbl.className   = 'heatmap-label';
        lbl.textContent = NAMES[idx].split(' ')[0];
        labelsEl.appendChild(lbl);
      });
    }

    // Re-draw radar using updated PSI values (drawRadar reads PSI from outer scope)
    if (typeof drawRadar === 'function') drawRadar();

    // Patch metric boxes
    var bc = data.baseline_confidence;
    var metricVals = document.querySelectorAll('.metric-val');
    metricVals.forEach(function (el) {
      var parent = el.closest('.metric-box');
      if (!parent) return;
      var lbl = parent.querySelector('.metric-label');
      if (!lbl) return;
      if (lbl.textContent.includes('Samples')) {
        el.textContent = bc.sample_count;
      } else if (lbl.textContent.includes('Purity')) {
        el.textContent = bc.purity.toFixed(3);
        el.style.color = bc.purity < 0.5 ? 'var(--amber)' : 'var(--green-deep)';
      }
    });

    // Patch purity ring arc — r=56 circle, circumference = 2π×56 ≈ 351.86
    var purityArc = document.querySelector('circle[stroke="#c9a028"][stroke-dasharray]');
    if (purityArc) {
      var circ   = 2 * Math.PI * 56;
      var offset = circ * (1 - bc.purity);
      purityArc.setAttribute('stroke-dasharray', circ.toFixed(1));
      purityArc.setAttribute('stroke-dashoffset', offset.toFixed(1));
    }

    // Patch purity text
    var purityValEl = document.querySelector('.purity-val');
    if (purityValEl) purityValEl.textContent = bc.purity.toFixed(3);

    document.querySelectorAll('.purity-legend-val').forEach(function (el) {
      // Target the "Current purity" row (no colour style)
      if (!el.style.color && el.textContent.match(/^0\.\d{3}$/)) {
        el.textContent = bc.purity.toFixed(3);
      }
    });
  }

  // ── Patcher: original-decomposition.html ─────────────────────────────────────

  function patchDecomposition(data) {
    // SIGNALS is a const array — mutate in-place.
    if (typeof SIGNALS === 'undefined') return;

    var fv = data.feature_vector;
    var bv = data.baseline_vector;

    // Build per-feature interpretation strings from API destructive/constructive lists
    var interps = {};
    data.interference.destructive_features.forEach(function (f) {
      var pct = (Math.abs(f.delta) * 100).toFixed(0);
      var dir = f.delta < 0 ? pct + '% below baseline' : pct + '% above baseline';
      interps[f.code] = f.name + ': submission is ' + dir + '. Primary stylometric signal.';
    });
    data.interference.constructive_features.forEach(function (f) {
      interps[f.code] = f.name + ': aligns with student\'s established baseline pattern.';
    });

    // Build new SIGNALS for all 34 features
    // contrib = (sub − base) * max(base, 0.05) — signed, scaled by baseline weight
    var newSignals = CODES.map(function (code, i) {
      var base    = bv[code] !== undefined ? bv[code] : 0;
      var sub     = fv[code] !== undefined ? fv[code] : 0;
      var weight  = Math.max(base, 0.05);
      var contrib = (sub - base) * weight;
      var interp  = interps[code] || NAMES[i] + ': within expected baseline range.';
      return {
        name: NAMES[i],
        code: code,
        contrib: contrib,
        base: base,
        sub: sub,
        tier: TIERS[i],
        interp: interp,
      };
    });

    // Mutate SIGNALS in-place (can't reassign const)
    SIGNALS.length = 0;
    newSignals.forEach(function (s) { SIGNALS.push(s); });
    SIGNALS.sort(function (a, b) { return a.contrib - b.contrib; });

    // Compute adaptive threshold for signal cards (features with contrib in bottom 25%)
    var maxAbs = Math.max.apply(null, SIGNALS.map(function (s) { return Math.abs(s.contrib); }));
    var sigThreshold = -maxAbs * 0.25;

    // Override renderSignalCards to use adaptive threshold instead of hardcoded -0.04
    window.renderSignalCards = function () {
      var container = document.getElementById('signal-cards');
      if (!container) return;
      var top = SIGNALS.filter(function (s) { return s.contrib < sigThreshold; }).slice(0, 8);
      container.innerHTML = top.map(function (s) {
        var deltaPct = ((s.sub - s.base) * 100).toFixed(0);
        return [
          '<div class="signal-card destructive">',
          '  <div class="signal-name">' + s.name + '</div>',
          '  <div class="signal-code">' + s.code + '</div>',
          '  <div class="signal-vals">',
          '    <div class="signal-val">',
          '      <div class="signal-val-label">Baseline</div>',
          '      <div class="signal-val-num">' + s.base.toFixed(3) + '</div>',
          '    </div>',
          '    <div class="signal-val">',
          '      <div class="signal-val-label">Submission</div>',
          '      <div class="signal-val-num" style="color:var(--destr);">' + s.sub.toFixed(3) + '</div>',
          '    </div>',
          '  </div>',
          '  <div class="signal-delta big-d">Δ ' + deltaPct + '%</div>',
          '  <div class="signal-interp">' + s.interp + '</div>',
          '</div>',
        ].join('\n');
      }).join('');
    };

    // Override updateCounts with adaptive threshold
    window.updateCounts = function () {
      var nD = document.getElementById('n-destr');
      var nC = document.getElementById('n-constr');
      var n_d = SIGNALS.filter(function (s) { return s.contrib < sigThreshold; }).length;
      var n_c = SIGNALS.filter(function (s) { return s.contrib > -sigThreshold; }).length;
      if (nD) nD.textContent = n_d;
      if (nC) nC.textContent = n_c;
    };

    // Re-render all decomposition charts
    if (typeof renderTornado === 'function')       renderTornado();
    renderSignalCards();
    if (typeof renderTierBreakdown === 'function') renderTierBreakdown();
    updateCounts();

    // Patch score strip values
    var auth = data.authorship;
    var dev  = auth.deviation_score;
    document.querySelectorAll('.score-metric').forEach(function (metric) {
      var valEl = metric.querySelector('.score-val');
      var lblEl = metric.querySelector('.score-label');
      if (!valEl || !lblEl) return;
      var lbl = lblEl.textContent.trim();
      if (lbl === 'Deviation Score') {
        valEl.textContent = dev.toFixed(4);
        valEl.style.color = devColour(dev);
      } else if (lbl === 'Authorship Prob.') {
        valEl.textContent = (auth.authorship_probability * 100).toFixed(1) + '%';
      }
    });

    // Patch risk chip
    var riskChip = document.querySelector('.risk-chip');
    if (riskChip) {
      var action = data.recommendation.action;
      var chipLabels = {
        no_action: 'CLEAR', monitor: 'MONITOR',
        schedule_conversation: 'FLAG', escalate: 'ESCALATE',
      };
      riskChip.textContent = chipLabels[action] || action.toUpperCase();
      if (action === 'no_action') {
        riskChip.style.background = 'rgba(42,107,69,0.12)';
        riskChip.style.color = '#2a6b45';
        riskChip.style.border = '1px solid rgba(42,107,69,0.3)';
      } else if (action === 'monitor') {
        riskChip.style.background = 'rgba(201,160,40,0.12)';
        riskChip.style.color = '#c9a028';
        riskChip.style.border = '1px solid rgba(201,160,40,0.35)';
      }
    }
  }

  // ── Main ──────────────────────────────────────────────────────────────────────

  document.addEventListener('DOMContentLoaded', function () {
    var path = window.location.pathname;

    var isReview       = path.includes('original-review');
    var isFeatures     = path.includes('original-features');
    var isQuantum      = path.includes('original-quantum');
    var isDecompos     = path.includes('original-decomposition');

    if (!isReview && !isFeatures && !isQuantum && !isDecompos) return;

    // Inject accessibility enhancements
    injectA11yStyles();
    injectSkipLink();

    var loader = showLoading();

    // Get submission options from page context or global
    var submissionOptions = {
      studentId: window.ORIGINAL_STUDENT_ID,
      submissionText: window.ORIGINAL_SUBMISSION_TEXT,
      submissionId: window.ORIGINAL_SUBMISSION_ID,
      assignment: window.ORIGINAL_ASSIGNMENT,
    };

    fetchScore(submissionOptions).then(function (data) {
      hideLoading(loader);
      window._origApiData = data; // expose for dev inspection

      if (isReview)    patchReview(data);
      if (isFeatures)  patchFeatures(data);
      if (isQuantum)   patchQuantum(data);
      if (isDecompos)  patchDecomposition(data);

      showBadge(true);
    }).catch(function (err) {
      hideLoading(loader);
      console.warn('[Original API] Offline or error:', err.message || err);
      showBadge(false);
      showErrorBanner(err);
    });
  });

})();
