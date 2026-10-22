// ════════════════════════════════════════════════════════════════
//  BLUEBOOK: resume where you left off, on any device (2026-10-21)
// ════════════════════════════════════════════════════════════════
// The signed-in account's place (screen, the item it shows, the tab, and how
// far down the page) is saved on the server, about 2 seconds after it changes
// and at once when the page is hidden or closed. Signing in on another device
// (password sign-in or a set-password / reset link) opens that place instead
// of the home screen, if the server says the account may still open it.
//
// What is saved is built from the app's own state, never from the address
// bar, so a set-password or reset link's code can never be stored. The scroll
// position is kept twice: as the first row on screen (data-resume-anchor),
// which survives a different screen size, and as a fraction of the page, used
// when that row is gone. It is restored after the screen's data has loaded.
//
// A student is never resumed into a sitting: an exam is saved and restored as
// that exam's briefing (the start/resume screen), where the start rules apply
// (original/routers/bluebook_accounts.py does the same on the server).
import { BB_API } from './components.jsx';
import { parseDeepLink } from './deep-link.jsx';

export const SAVE_DELAY_MS = 2000;
// How long a restore waits for the page's data before giving up.
const RESTORE_WAIT_MS = 8000;
// The server keeps only short identifiers (bluebook_accounts.py _ID_RE).
const ID_RE = /^[A-Za-z0-9_:@-][A-Za-z0-9_:@.-]{0,127}$/;
const TAB_RE = /^[a-z0-9_-]{1,32}$/;

// The screens kept, with the global each one reads its item from (Teacher.jsx,
// Account.jsx). Everything else (sign-in, set password, a new form, the
// submitted page) is never saved: the last kept place stays.
const STAFF_SCREENS = {
  dashboard: null, sessions: null, collections: null, exams: null, courses: null,
  students: null, results: null, account: null,
  proctor: ['exam', (w, v) => v.exam || w.BB_PROCTOR_EXAM],
  'manage-exam': ['exam', w => w.BB_MANAGE_EXAM],
  roster: ['course', w => w.BB_ROSTER_COURSE && w.BB_ROSTER_COURSE.id],
};
const STUDENT_SCREENS = {
  'student-home': null, 'student-account': null,
  'student-submission': ['submission', w => w.BB_VIEW_SUBMISSION],
  // Saved as the exam's briefing, never as the sitting itself.
  briefing: ['exam', w => w.BB_EXAM_CONFIG && w.BB_EXAM_CONFIG.id],
  exam: ['exam', w => w.BB_EXAM_CONFIG && w.BB_EXAM_CONFIG.id],
};
const SCREEN_ALIAS = { collections: 'sessions', exams: 'sessions' };

const clean = (v, re) => (typeof v === 'string' && re.test(v) ? v : '');

export function scrollFraction(scrollY, scrollHeight, viewHeight) {
  const room = (scrollHeight || 0) - (viewHeight || 0);
  if (!(room > 0)) return 0;
  return Math.round(Math.min(1, Math.max(0, (scrollY || 0) / room)) * 10000) / 10000;
}

// The place to save for this screen, or null when the screen is not kept.
// `view` holds what the screen itself reported (noteView): the selected
// student, the tab. `scroll` is { fraction, anchor }.
export function locationFor(screen, { student, w = {}, view = {}, scroll = {} } = {}) {
  const table = student ? STUDENT_SCREENS : STAFF_SCREENS;
  if (!Object.prototype.hasOwnProperty.call(table, screen)) return null;
  const spec = table[screen];
  const out = { screen: SCREEN_ALIAS[screen] || screen };
  if (student && screen === 'exam') out.screen = 'briefing';
  if (spec) {
    const id = clean(String(spec[1](w, view) || ''), ID_RE);
    if (!id) return null;
    out.entity_kind = spec[0];
    out.entity_id = id;
  } else if (screen === 'students' && clean(view.student, ID_RE)) {
    out.entity_kind = 'student';
    out.entity_id = view.student;
  }
  if (clean(view.tab, TAB_RE)) out.tab = view.tab;
  if (out.screen !== 'briefing') {
    out.scroll_fraction = Math.round(Math.min(1, Math.max(0, Number(scroll.fraction) || 0)) * 10000) / 10000;
    const anchor = clean(scroll.anchor, ID_RE);
    if (anchor) out.scroll_anchor = anchor;
  }
  return out;
}

// ── Browser side ──────────────────────────────────────────────────────────
const state = { screen: '', view: {}, timer: null, restoring: false, last: '', pending: null };

function signedInAccount() {
  if (BB_API.isStudentLaunch()) return null;   // a launch link has no account
  if (BB_API.isStudentAccount()) return 'student';
  return BB_API.isAuthed() ? 'staff' : null;
}

// The first kept row (or section) still showing at the top of what scrolls.
function topAnchor(el) {
  if (typeof document === 'undefined') return '';
  const top = el === document.scrollingElement || el === document.documentElement ? 0 : el.getBoundingClientRect().top;
  for (const a of document.querySelectorAll('[data-resume-anchor]')) {
    const r = a.getBoundingClientRect();
    if (r.height > 0 && r.bottom > top + 8) return a.getAttribute('data-resume-anchor') || '';
  }
  return '';
}

// What scrolls: the workspace's own panel (data-resume-scroll) when it
// scrolls, as on a laptop, else the page itself (a phone, the student pages).
function scroller() {
  const panel = document.querySelector('[data-resume-scroll]');
  if (panel && panel.scrollHeight > panel.clientHeight + 1) return panel;
  return document.scrollingElement || document.documentElement;
}

function currentLocation() {
  const who = signedInAccount();
  if (!who) return null;
  const el = scroller();
  return locationFor(state.screen, {
    student: who === 'student', w: window, view: state.view,
    scroll: {
      fraction: scrollFraction(el.scrollTop, el.scrollHeight, el.clientHeight),
      anchor: el.scrollTop > 4 ? topAnchor(el) : '',
    },
  });
}

function save({ keepalive = false } = {}) {
  clearTimeout(state.timer); state.timer = null;
  if (state.restoring) return;
  const loc = currentLocation();
  if (!loc) return;
  const key = JSON.stringify(loc);
  if (key === state.last) return;
  state.last = key;
  BB_API.putLastLocation(loc, { keepalive });
}

export function scheduleSave() {
  if (state.restoring || typeof window === 'undefined') return;
  clearTimeout(state.timer);
  state.timer = setTimeout(save, SAVE_DELAY_MS);
}

// app.jsx calls this whenever the screen changes.
export function trackScreen(screen) {
  if (screen !== state.screen) state.view = {};
  state.screen = screen;
  scheduleSave();
}

// A screen reports what it is showing: { student } on Students, { tab }.
export function noteView(view) {
  state.view = { ...state.view, ...view };
  scheduleSave();
}

let installed = false;
export function installResumeTracking() {
  if (installed || typeof window === 'undefined') return;
  installed = true;
  // Capture: a scrolling panel's scroll events do not bubble.
  document.addEventListener('scroll', scheduleSave, { passive: true, capture: true });
  document.addEventListener('visibilitychange', () => { if (document.visibilityState === 'hidden') save({ keepalive: true }); });
  window.addEventListener('pagehide', () => save({ keepalive: true }));
}

// What a screen opens with when it is the one being resumed (taken once).
export function takeResumed(key) {
  const p = state.pending;
  if (!p || !(key in p)) return undefined;
  const v = p[key];
  delete p[key];
  return v;
}

// After the screen's data has loaded: scroll to the saved row if it is there,
// otherwise to the saved fraction of the page. Saving resumes afterwards.
function restoreScroll(anchor, fraction) {
  const start = Date.now();
  let lastHeight = -1, steady = 0;
  const done = () => { state.restoring = false; state.last = ''; scheduleSave(); };
  const tick = () => {
    const el = anchor ? document.querySelector(`[data-resume-anchor="${CSS.escape(anchor)}"]`) : null;
    if (el) { el.scrollIntoView({ block: 'start' }); done(); return; }
    const loading = [...document.querySelectorAll('[role="status"]')].some(n => /loading|opening/i.test(n.textContent || ''));
    const sc = scroller();
    const h = sc.scrollHeight;
    steady = (h === lastHeight && !loading) ? steady + 1 : 0;
    lastHeight = h;
    const waitedForAnchor = !anchor || Date.now() - start > 3000;
    if ((steady >= 3 && waitedForAnchor) || Date.now() - start > RESTORE_WAIT_MS) {
      const room = h - sc.clientHeight;
      if (fraction > 0 && room > 0) sc.scrollTop = Math.round(fraction * room);
      done();
      return;
    }
    setTimeout(tick, 100);
  };
  setTimeout(tick, 50);
}

// After a sign-in: open the saved place if the server still allows it,
// otherwise `home`. `openExam` is Account.jsx's openStudentExam (passed in to
// keep this module free of screen imports).
export async function resumeOrHome(onNavigate, home, { openExam } = {}) {
  const who = signedInAccount();
  // A link the visitor followed (#exam/<id>, #students) wins over the saved place.
  const linked = typeof window !== 'undefined' && parseDeepLink(window.location.hash);
  const loc = who && !linked ? await BB_API.getLastLocation() : null;
  const table = who === 'student' ? STUDENT_SCREENS : STAFF_SCREENS;
  if (!loc || !loc.screen || !(loc.screen in table) || loc.screen === 'exam') { onNavigate(home); return; }
  const id = loc.entity_id;
  try {
    if (who === 'staff') {
      if (loc.screen === 'manage-exam') window.BB_MANAGE_EXAM = id;
      if (loc.screen === 'proctor') window.BB_PROCTOR_EXAM = id;
      if (loc.screen === 'roster') window.BB_ROSTER_COURSE = { id, name: loc.entity && loc.entity.name, code: loc.entity && loc.entity.code };
    } else {
      if (loc.screen === 'student-submission') window.BB_VIEW_SUBMISSION = id;
      if (loc.screen === 'briefing') {
        // The exam's start screen, through the same door as "Open"/"Resume".
        if (!openExam) { onNavigate(home); return; }
        await openExam(id, onNavigate);
        return;
      }
    }
  } catch (e) { onNavigate(home); return; }
  state.pending = { student: loc.entity_kind === 'student' ? id : undefined, tab: loc.tab || undefined };
  state.restoring = true;
  onNavigate(loc.screen);
  restoreScroll(loc.scroll_anchor || '', Number(loc.scroll_fraction) || 0);
}
