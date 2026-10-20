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
const SCREEN_LINK = /^#(students|courses|collections|exams|sessions)$/;
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

// Drops a deep-link hash from the address bar, keeping the path and query,
// so a reload after the teacher has moved on opens the dashboard rather
// than the exam the link named. Does not fire hashchange.
export function clearDeepLink() {
  try {
    if (!parseDeepLink(window.location.hash) && window.location.hash !== FORGOT_HASH) return;
    window.history.replaceState(window.history.state, '', window.location.pathname + window.location.search);
  } catch (e) { /* history unavailable: the hash stays, which is harmless */ }
}
