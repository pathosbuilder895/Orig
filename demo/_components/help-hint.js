/* ─────────────────────────────────────────────────────────────────────────
   <HelpHint> wiring — adds title tooltip + click-to-explainer.

   Markup:
     <span class="help-hint"
           data-hint="One-line tooltip."
           data-topic="fingerprint"  // optional; deep-links the explainer
           ></span>

   The script sets `title` from data-hint (so native hover works for free),
   adds role="button" + tabindex for keyboard access, and opens a popover
   with a longer explainer on click or Enter/Space.
   ───────────────────────────────────────────────────────────────────────── */

(function() {
  'use strict';

  // Per-topic longer explainer. Keep these in plain English — no jargon.
  // The "How it works" page (demo/_components/explainer.html) is the source
  // of truth; these are pull-quotes for the popover preview.
  const TOPICS = {
    fingerprint: {
      title: 'Voice fingerprint',
      body:  'Your writing is summarised into seven blended dimensions — cadence, diction, texture, register, restraint, architecture, resonance. None of these dimensions correspond to a single feature; each is a blend, so you cannot reverse-engineer the underlying math from the chart. We use the same blends for every student.',
    },
    arc: {
      title: 'Voice arc',
      body:  'A timeline of how strongly each submission reads like your established voice. The value shown is a 0–100 fidelity score: higher means the system recognises this piece as yours. The arc tells you whether your voice is strengthening, holding steady, or moving.',
    },
    voiceNotes: {
      title: 'Voice notes',
      body:  'Written notes from your instructors when they have read a piece and want to leave you a remark — encouragement, a passage they liked, a stylistic observation. These are the words a person wrote about your work, not anything the system inferred.',
    },
    milestones: {
      title: 'Formation milestones',
      body:  'Named milestones in your formation record — Voice Sampled (your first piece is on file), Voice Established (enough on file to recognise your patterns), Voice Affirmed (a verified piece confirms it). They are not deadlines; they describe what is already true about your record.',
    },
    formation: {
      title: 'Formation pathway',
      body:  'An optional structured path of three short writing sessions — Baseline, Formation, Verification — designed to strengthen your writing rather than assess it. Your instructor opens a pathway when they want to invest in a particular piece together.',
    },
    baseline: {
      title: 'Baseline samples',
      body:  'A baseline sample is a piece of writing your instructor has confirmed is genuinely yours. The more baseline samples we have, the more confidently the system recognises your voice on future submissions. There are three levels: proctored (highest trust), verified, and unverified.',
    },
    proctored: {
      title: 'Proctored sittings',
      body:  'A proctored sitting is a writing session in a locked-down environment — no AI assistants, no web, no copy-paste — where the rhythm and pauses of your typing are also recorded. Proctored samples carry the highest weight in your voice profile.',
    },
    review: {
      title: 'Worth a conversation',
      body:  'When part of a submission reads differently from your established voice, the system surfaces it for a conversation — never an accusation. It is an invitation to look at the piece together; it is not a score, a verdict, or an action.',
    },
    deviation: {
      title: 'How the score is computed',
      body:  'Each submission is compared with the student\'s established voice across 103 stylometric features in seventeen tiers. The comparison produces a deviation score in [0, 1] which we present as authenticity = (1 − deviation) × 100. Higher is closer to the voice we already know.',
    },
    tiers: {
      title: 'Tier breakdown',
      body:  'Seventeen tiers group the 103 features by what they measure — sentence rhythm, character habits, citation style, etc. Tiers most resistant to editing (character n-grams, error patterns) weight slightly more heavily when something looks unusual.',
    },
  };

  function ensurePopover() {
    let dlg = document.querySelector('dialog.help-popover');
    if (dlg) return dlg;
    dlg = document.createElement('dialog');
    dlg.className = 'help-popover';
    document.body.appendChild(dlg);
    return dlg;
  }

  function openPopover(el) {
    const topic = el.getAttribute('data-topic');
    const hint  = el.getAttribute('data-hint') || '';
    const fromTopic = topic && TOPICS[topic];
    const title = fromTopic ? fromTopic.title : (hint || 'About this');
    const body  = fromTopic ? fromTopic.body  : (hint || '');

    const dlg = ensurePopover();
    dlg.innerHTML = ''
      + `<h3>${escapeHtml(title)}</h3>`
      + `<p>${escapeHtml(body)}</p>`
      + `<div class="help-popover-actions">`
      +   `<a href="/_components/explainer.html${topic ? '#' + encodeURIComponent(topic) : ''}" target="_blank">Read more →</a>`
      +   `<button type="button" data-close>Close</button>`
      + `</div>`;
    dlg.querySelector('[data-close]').addEventListener('click', () => dlg.close());
    if (typeof dlg.showModal === 'function') dlg.showModal(); else dlg.setAttribute('open', '');
  }

  function escapeHtml(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, c => ({
      '&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'
    })[c]);
  }

  function decorate(el) {
    if (el.__helpHintReady) return;
    const hint = el.getAttribute('data-hint') || el.getAttribute('title') || 'What is this?';
    el.setAttribute('title', hint);
    el.setAttribute('role', 'button');
    el.setAttribute('tabindex', '0');
    el.setAttribute('aria-label', 'Explain: ' + hint);
    el.__helpHintReady = true;
  }

  function decorateAll(root) {
    (root || document).querySelectorAll('.help-hint').forEach(decorate);
  }

  // Delegated click + keyboard handlers.
  document.addEventListener('click', (e) => {
    const el = e.target.closest && e.target.closest('.help-hint');
    if (el) openPopover(el);
  });
  document.addEventListener('keydown', (e) => {
    if (e.key !== 'Enter' && e.key !== ' ') return;
    const el = e.target.closest && e.target.closest('.help-hint');
    if (el) { e.preventDefault(); openPopover(el); }
  });

  if (document.readyState !== 'loading') {
    decorateAll();
  } else {
    document.addEventListener('DOMContentLoaded', () => decorateAll());
  }

  window.OriginalHelpHint = {
    decorate,
    decorateAll,
    TOPICS,
  };
})();
