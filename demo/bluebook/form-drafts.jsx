// Drafts of forms that are not saved on the server until they are sent:
// the New collection form (per teacher) and the "Share a past paper" text
// (per student). Kept in this browser's localStorage so closing the tab, a
// crash or a lapsed sign-in never loses what was typed. Each draft belongs
// to one account, so on a shared computer one person's draft never opens
// for another. Nothing here is sent anywhere.

export const FORM_DRAFT_PREFIX = 'bb_form_draft_';

function store(s) {
  if (s) return s;
  try { return typeof localStorage !== 'undefined' ? localStorage : null; } catch (e) { return null; }
}

// The account a draft belongs to: the signed-in email (staff) or student id.
export function formDraftOwner(s) {
  const ls = store(s);
  if (!ls) return '';
  try {
    if (ls.getItem('original_role') === 'student') return 'student:' + (ls.getItem('original_student_id') || '');
    const email = ls.getItem('original_email') || '';
    const tenant = ls.getItem('original_tenant') || '';
    return email ? 'staff:' + tenant + ':' + email.toLowerCase() : '';
  } catch (e) { return ''; }
}

export function formDraftKey(form, owner) {
  return FORM_DRAFT_PREFIX + form + '|' + (owner || 'anon');
}

export function loadFormDraft(form, s) {
  const ls = store(s);
  if (!ls) return null;
  try {
    const d = JSON.parse(ls.getItem(formDraftKey(form, formDraftOwner(ls))) || 'null');
    return d && typeof d === 'object' && d.values && typeof d.values === 'object' ? d.values : null;
  } catch (e) { return null; }
}

// Saves only when something was typed; an empty form clears the draft.
export function saveFormDraft(form, values, isEmpty, s) {
  const ls = store(s);
  if (!ls) return false;
  const key = formDraftKey(form, formDraftOwner(ls));
  try {
    if (isEmpty) { ls.removeItem(key); return true; }
    ls.setItem(key, JSON.stringify({ values, savedAt: Date.now() }));
    return true;
  } catch (e) { return false; }
}

export function clearFormDraft(form, s) {
  const ls = store(s);
  if (!ls) return;
  try { ls.removeItem(formDraftKey(form, formDraftOwner(ls))); } catch (e) {}
}

// When a staff principal token ends (its payload is base64url JSON with
// `exp` in seconds; original/principal.py). Null if it cannot be read.
export function tokenExpiryMs(token) {
  if (!token || token.indexOf('.') < 0) return null;
  try {
    let p = token.split('.')[0].replace(/-/g, '+').replace(/_/g, '/');
    while (p.length % 4) p += '=';
    const json = typeof atob === 'function' ? atob(p) : Buffer.from(p, 'base64').toString('binary');
    const exp = Number(JSON.parse(json).exp);
    return exp > 0 ? exp * 1000 : null;
  } catch (e) { return null; }
}

export const EXPIRY_WARN_MS = 10 * 60 * 1000;

// ms until the warning should show (0 = show now), or null for no warning.
export function expiryWarnDelay(expMs, nowMs) {
  if (!expMs) return null;
  return Math.max(0, expMs - EXPIRY_WARN_MS - nowMs);
}
