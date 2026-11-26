// ════════════════════════════════════════════════════════════════
//  BLUEBOOK: deep links into one examination (2026-10-11)
// ════════════════════════════════════════════════════════════════
// A link from outside the app can open one exam for a signed-in teacher:
//
//   /bluebook/#exam/<id>   Manage examination (submissions, Read & mark,
//                          baseline approval)
//   /bluebook/#live/<id>   the live (proctor) view of that exam
//   /bluebook/#students    the teacher's Students screen (the roster)
//   /bluebook/#courses     the teacher's Courses screen
//   /bluebook/#collection/<id>      same as #exam/<id>
//   /bluebook/#collections, #exams, #sessions   the Collections list
//   /bluebook/#dashboard   the Collections dashboard (a teacher whose
//                          workspace has Original otherwise opens Original:
//                          see staffOriginalHome below)
//
// The Original suite links here: its Bluebook Sessions page (demo/original/
// bluebook.html), the Submissions rows (#exam), Add student and Voice Baseline
// (#students, or the student's own exam), and the course links (#courses). Screens stay in memory (app.jsx); the hash only picks the first
// one. app.jsx checks the exam with GET /bluebook/exams/{id} before opening
// it, so an unknown id or another workspace's id lands on the normal
// dashboard with no error page. #students and #courses name no exam, so
// nothing is checked: they open that screen. Nothing here runs for a student:
// app.jsx resolves a link only on a signed-in teacher's dashboard, and a
// visitor who is not signed in gets the landing page and, after signing in,
// the screen the link named.

// Exam ids are short hex strings today (uuid4().hex[:16] in
// original/routers/bluebook.py); seeded demo ids use letters, digits and
// dashes. Anything else is not a deep link and is ignored.
const DEEP_LINK = /^#(exam|collection|live)\/([A-Za-z0-9_-]{1,64})$/;
// A link to a whole screen: no id, nothing to check on the server.
const SCREEN_LINK = /^#(students|courses|results|collections|exams|sessions|dashboard)$/;
// The old Examinations and Sessions links open the one Collections list
// (screen 'sessions'), so links saved before the merge keep working.
const SCREEN_ALIAS = { collections: 'sessions', exams: 'sessions', sessions: 'sessions' };

// The screen each kind of link opens, and the global that screen reads its
// exam id from (Teacher.jsx: ManageExamScreen, ProctorLiveScreen).
export const DEEP_LINK_SCREEN = { exam: 'manage-exam', collection: 'manage-exam', live: 'proctor' };
const DEEP_LINK_GLOBAL = { exam: 'BB_MANAGE_EXAM', collection: 'BB_MANAGE_EXAM', live: 'BB_PROCTOR_EXAM' };

// '#exam/<id>' or '#live/<id>' -> {kind, id}; '#students' or '#courses' ->
// {kind: 'screen', screen}; anything else -> null.
export function parseDeepLink(hash) {
  const h = typeof hash === 'string' ? hash : '';
  const m = DEEP_LINK.exec(h);
  if (m) return { kind: m[1], id: m[2] };
  const s = SCREEN_LINK.exec(h);
  return s ? { kind: 'screen', screen: SCREEN_ALIAS[s[1]] || s[1] } : null;
}

// Points the target screen at the exam and returns the screen to show.
export function deepLinkScreen(link, exam) {
  window[DEEP_LINK_GLOBAL[link.kind]] = exam.id;
  return DEEP_LINK_SCREEN[link.kind];
}

// '#forgot' opens the existing "Reset your password" screen for a visitor who is not signed in
// (the sign-in page's "Forgot your password?" link). It is not a deep link into a signed-in
// workspace: app.jsx reads it only to pick the first screen.
export const FORGOT_HASH = '#forgot';

// Teacher screens that keep their place across a reload: navigating to one
// writes its hash, so a refresh reopens it instead of the dashboard (alpha
// bug 2026-10-20: a refresh on Students dropped the teacher elsewhere).
export const RELOADABLE_SCREENS = ['students', 'courses', 'sessions', 'collections', 'exams', 'results'];
// The one Collections list (screen 'sessions', and its old names) is kept as #collections.
const SCREEN_HASH = { sessions: 'collections', exams: 'collections', collections: 'collections' };
export function rememberScreen(screen) {
  if (!RELOADABLE_SCREENS.includes(screen)) return;
  const hash = SCREEN_HASH[screen] || screen;
  try { window.history.replaceState(window.history.state, '', window.location.pathname + window.location.search + '#' + hash); } catch (e) {}
}

// Drops a deep-link hash from the address bar, keeping the path and query,
// so a reload after the teacher has moved on opens the dashboard rather
// than the exam the link named. Does not fire hashchange.
// `signingIn`: the move starts on a screen a visitor sees before signing in.
// A deep link then stays, because resumeOrHome (resume-location.jsx) reads it
// after sign-in so the followed link wins over the place saved on another
// device. '#forgot' is not a deep link and still goes.
export function clearDeepLink({ signingIn = false } = {}) {
  try {
    if (signingIn && parseDeepLink(window.location.hash)) return;
    if (!parseDeepLink(window.location.hash) && window.location.hash !== FORGOT_HASH) return;
    window.history.replaceState(window.history.state, '', window.location.pathname + window.location.search);
  } catch (e) { /* history unavailable: the hash stays, which is harmless */ }
}

// Where a signed-in staff member whose workspace has Original starts, the same
// places the main sign-in page (demo/index.html) sends them: Original for a
// teacher, the admin and operator pages for those roles.
const STAFF_HOME = {
  professor: '/original/', super_admin: '/original/', admin: '/admin.html', operator: '/operator.html',
};
// The bare app entry. /collections/ serves the same app but names Collections
// on purpose, so it never sends anyone away.
const SPA_ENTRY = /^\/bluebook(\/(index\.html)?)?$/;

// This browser tab has already shown a signed-in teacher Collections. Most
// Collections screens do not keep their place in the address (only
// RELOADABLE_SCREENS do), so a reload of the Proctor screen or the dashboard
// is the bare /bluebook/ address again: without this a teacher working in
// Collections would be sent to Original by a reload. Per tab (sessionStorage),
// so a new tab or a new visit still starts in Original (a duplicated tab copies
// sessionStorage, so it stays in Collections too). Signing out clears it
// (BB_API.logout in components.jsx, Live.signOut in demo/original/live.js).
export const COLLECTIONS_TAB_KEY = 'bluebook_collections_tab';
export function markCollectionsTab() {
  try { sessionStorage.setItem(COLLECTIONS_TAB_KEY, '1'); } catch (e) {}
}
export function inCollectionsTab() {
  try { return sessionStorage.getItem(COLLECTIONS_TAB_KEY) === '1'; } catch (e) { return false; }
}
export function clearCollectionsTab() {
  try { sessionStorage.removeItem(COLLECTIONS_TAB_KEY); } catch (e) {}
}

// Whether this visit should leave Collections for the staff member's home, and
// where: a URL, or null to stay. It leaves only when every one holds: signed in
// as staff (not a student account, not a student launch), the workspace has
// Original, the role has a home above, the address is the bare /bluebook/
// entry, there is no hash (no deep link, no remembered screen, no #dashboard),
// no join, invite or reset link is being followed, and this tab is not already
// working in Collections (inCollections). Anything else stays, so students,
// course links and Collections-only workspaces are unchanged.
export function staffOriginalHome({
  authed, studentAccount, studentLaunch, hasOriginal, role, pathname, search, hash, inCollections,
} = {}) {
  if (!authed || studentAccount || studentLaunch || !hasOriginal || inCollections) return null;
  const home = Object.prototype.hasOwnProperty.call(STAFF_HOME, role) ? STAFF_HOME[role] : null;
  if (!home) return null;
  if (hash && hash !== '#') return null;
  if (!SPA_ENTRY.test(typeof pathname === 'string' ? pathname : '')) return null;
  let q;
  try { q = new URLSearchParams(search || ''); } catch (e) { return null; }
  if (q.has('join') || q.has('invite') || q.has('reset')) return null;
  return home;
}

// staffOriginalHome for this browser's sign-in and address. `api` is BB_API
// (components.jsx), passed in so this file stays free of it.
export function staffHomeRedirect(api, loc) {
  const here = loc || (typeof window !== 'undefined' ? window.location : {});
  const role = (api.identity() || {}).role || '';
  return staffOriginalHome({
    authed: api.isAuthed(), studentAccount: api.isStudentAccount(), studentLaunch: api.isStudentLaunch(),
    hasOriginal: api.hasOriginal(), role,
    pathname: here.pathname, search: here.search, hash: here.hash, inCollections: inCollectionsTab(),
  });
}
