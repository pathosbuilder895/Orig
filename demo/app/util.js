// util.js — small shared helpers (fetch concurrency, formatting).

// Bounded-concurrency map — avoids firing N simultaneous requests on load.
export async function mapPool(items, fn, poolSize = 8) {
  const out = new Array(items.length);
  let i = 0;
  await Promise.all(
    Array.from({ length: Math.min(poolSize, items.length) }, async () => {
      while (i < items.length) { const idx = i++; out[idx] = await fn(items[idx]); }
    })
  );
  return out;
}

// Score display format is a real, saved preference (Settings → Display),
// not decorative — every score everywhere in the app reads it back.
export const SCORE_FORMAT_KEY = 'original_pref_score_pct';
export function fmtScore(v) {
  if (v == null) return '—';
  let pct = false;
  try { pct = localStorage.getItem(SCORE_FORMAT_KEY) === '1'; } catch (e) { /* unavailable */ }
  return pct ? `${Math.round(v * 100)}%` : Number(v).toFixed(2);
}

export function fmtDate(iso) {
  if (!iso) return '—';
  const d = new Date(iso);
  if (isNaN(d)) return String(iso).slice(0, 10);
  return d.toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
}

export function daysAgo(iso) {
  if (!iso) return Infinity;
  const d = new Date(iso);
  if (isNaN(d)) return Infinity;
  return (Date.now() - d.getTime()) / 86400000;
}

export function humanize(s) {
  return String(s || '').replace(/_/g, ' ');
}

// Readiness verdict, computed client-side from StudentStateResponse fields —
// mirrors the thresholds documented on ReadinessResponse in original/schemas.py:
// "ready" (>=5 authenticated AND >=3 effective), "developing" (>=2 authenticated), else "insufficient".
export function verdictFor(student) {
  if (!student) return 'insufficient';
  const auth = student.authenticated_count || 0;
  const eff = student.effective_sample_count || 0;
  if (auth >= 5 && eff >= 3) return 'ready';
  if (auth >= 2) return 'developing';
  return 'insufficient';
}

// Short display label for an opaque id like "pilot-seminary:erahman" or "whitfield_j".
export function shortLabel(id) {
  const local = id.includes(':') ? id.split(':').pop() : id;
  return local.replace(/[_-]/g, ' ');
}

export function initials(id) {
  const label = shortLabel(id);
  const parts = label.split(/\s+/).filter(Boolean);
  if (parts.length >= 2) return (parts[0][0] + parts[1][0]).toUpperCase();
  return label.slice(0, 2).toUpperCase();
}

// ── Last-score stash ───────────────────────────────────────────────────────
// The Submissions page stashes each successful Layer7 score result here; the
// Research pages (Interference entirely, Fingerprint/Quantum compare overlays)
// consume it. Per-student keys, sessionStorage (per-tab, cleared on close) —
// per-feature contributions aren't stored server-side, so this is the only
// honest source for "the last analysis you ran".
const LAST_SCORE_PREFIX = 'original_last_score_';

export function saveLastScore(studentId, result, assignment = '') {
  try {
    sessionStorage.setItem(
      LAST_SCORE_PREFIX + studentId,
      JSON.stringify({ saved_at: new Date().toISOString(), assignment, result })
    );
  } catch (e) { /* quota/unavailable — stash is an enhancement, never fatal */ }
}

export function loadLastScore(studentId) {
  try {
    const raw = sessionStorage.getItem(LAST_SCORE_PREFIX + studentId);
    if (!raw) return null;
    const parsed = JSON.parse(raw);
    return parsed && parsed.result ? parsed : null;
  } catch (e) {
    return null;
  }
}

// Recommendation-action color/label scheme — matches demo/professor.html's
// existing rec-badge classes so the two apps read as one product.
export const ACTION_META = {
  no_action:             { label: 'No Action',            cls: 'no_action' },
  monitor:                { label: 'Monitor',               cls: 'monitor' },
  schedule_conversation:  { label: 'Schedule Conversation',  cls: 'schedule_conversation' },
  escalate:               { label: 'Escalate',               cls: 'escalate' },
};
export function actionMeta(action) {
  return ACTION_META[action] || { label: humanize(action) || 'Unknown', cls: 'monitor' };
}
