import React from 'react';
import { BB_API, MockupFonts, PARCHMENT_SHADES, STOCK_CANDIDATE } from './components.jsx';

// ════════════════════════════════════════════════════════════════
//  BLUEBOOK — Examination Screens
//  Briefing · Active Examination · Submitted
// ════════════════════════════════════════════════════════════════
const { useState: useExState, useEffect: useExEffect, useRef: useExRef, useCallback: useExCB } = React;

const EXAM_META = {
  title:       'Ethics in the Modern World',
  course:      'PHIL 301A',
  courseTitle: 'Philosophy 301A',
  candidate:   STOCK_CANDIDATE,
  duration:    90 * 60, // seconds
  minWords:    600,
  maxWords:    1200,
  prompt:      'Critically examine the tension between individual autonomy and collective obligation in contemporary liberal theory. With reference to at least two philosophers examined in this course, construct and defend a coherent position on the proper limits of state authority. Your answer will be evaluated for analytical rigour, fidelity to the texts, and the quality of your independent argument.',
  // Lockdown defaults — overridden by the instructor's New Examination settings
  blockAI:   true,
  blockWeb:  true,
  blockCopy: true,
  spellChk:  false,
  phoneBlk:  true,
  aiDetect:  false,
};

// Merge any instructor-configured settings saved from the New Examination form.
function getExamConfig() {
  const cfg = window.BB_EXAM_CONFIG || {};
  return {
    ...EXAM_META,
    ...cfg,
    duration: (cfg.duration ? cfg.duration * 60 : EXAM_META.duration),
    minWords: cfg.minWords != null ? cfg.minWords : EXAM_META.minWords,
    maxWords: cfg.maxWords != null ? cfg.maxWords : EXAM_META.maxWords,
    prompt:   cfg.prompt || EXAM_META.prompt,
    title:    cfg.title || EXAM_META.title,
  };
}

// A stored exam (GET /bluebook/me/exams/{id} or the start route's `exam`)
// as the config the briefing and exam screens read. `duration` stays in
// minutes here; getExamConfig() converts it. `loaded` marks the config as
// the teacher's real exam, so the briefing never falls back to the sample.
export function examToConfig(detail, extra = {}) {
  const d = detail || {};
  return {
    ...(d.conditions || {}),
    id:          d.exam_id || d.id,
    title:       d.title,
    course:      d.course || '',
    courseTitle: d.course || '',
    duration:    d.duration || 90,
    minWords:    d.min_words != null ? d.min_words : (d.minWords != null ? d.minWords : 0),
    maxWords:    d.max_words != null ? d.max_words : (d.maxWords != null ? d.maxWords : 0),
    prompt:      d.prompt || '',
    questions:   Array.isArray(d.questions) ? d.questions : [],
    state:       d.state,
    closesAt:    d.closes_at || null,
    inProgress:  !!d.session && !d.submitted,
    loaded:      true,
    ...extra,
  };
}

// The on-device draft for one exam (see ExamScreen's draft persistence).
// It belongs to the student who wrote it: on a shared computer, an unsent
// draft left by one student must never open in another student's booklet,
// where it could be sealed as theirs. A teacher previewing an exam has no
// student id, so the exam alone names that draft.
function bbDraftOwner() {
  try {
    const launch = localStorage.getItem('bluebook_student_id');
    if (launch) return launch;
    if (localStorage.getItem('original_role') === 'student') return localStorage.getItem('original_student_id') || '';
  } catch (e) {}
  return '';
}
export function bbDraftKey(cfg) {
  const exam = (cfg && (cfg.id || cfg.title)) || 'exam';
  const owner = bbDraftOwner();
  return 'bb_draft_' + (owner ? owner + '|' : '') + exam;
}

// Drafts were once keyed by the exam alone. A sitting in progress when the
// per-student key shipped would otherwise refresh into an empty booklet, so
// a recent draft under the old key is moved to this student's key, once.
// "Recent" is an exam day (12 hours): an older one is left alone, since on a
// shared computer it may be someone else's. The student's own draft always
// wins.
const BB_LEGACY_DRAFT_MAX_AGE_MS = 12 * 3600 * 1000;
export function bbAdoptLegacyDraft(cfg, now = Date.now()) {
  try {
    const key = bbDraftKey(cfg);
    const legacy = 'bb_draft_' + ((cfg && (cfg.id || cfg.title)) || 'exam');
    if (key === legacy || localStorage.getItem(key) != null) return;
    const raw = localStorage.getItem(legacy);
    if (raw == null) return;
    const d = JSON.parse(raw);
    if (!d || typeof d.savedAt !== 'number' || now - d.savedAt > BB_LEGACY_DRAFT_MAX_AGE_MS) return;
    localStorage.setItem(key, raw);
    localStorage.removeItem(legacy);
  } catch (e) {}
}

// Whether this sitting's submission goes to Original. Original can be
// switched on or off for a workspace mid-exam, and any home-page load then
// refreshes the stored products, so the sitting decides once — when the
// student first enters the exam screen — and keeps that decision in the
// exam's draft (seal.withOriginal). The briefing and the seal both read it,
// so what the student is told is what happens to the submission. Before the
// sitting has started (no draft, or a draft from an older page without the
// decision), the workspace's current products answer.
export function bbOriginalForSitting(cfg) {
  bbAdoptLegacyDraft(cfg);
  try {
    const d = JSON.parse(localStorage.getItem(bbDraftKey(cfg)) || 'null');
    if (d && d.seal && typeof d.seal.withOriginal === 'boolean') return d.seal.withOriginal;
  } catch (e) {}
  return BB_API.hasOriginal();
}

// Lock the decision into the exam's draft when the student clicks Begin, with
// exactly the value the briefing displayed. Between the briefing's render and
// the exam screen's mount another tab can refresh the stored products, so
// leaving the decision to the mount could compare a submission the student
// was just told would not be compared. An existing boolean (a resumed
// sitting) is never overwritten; everything else in the draft is kept. The
// exam screen's own mount still decides for a sitting that skipped the
// briefing. Returns the decision the draft now holds, or null if storage
// could not be written.
export function bbLockOriginalDecision(cfg, withOriginal) {
  bbAdoptLegacyDraft(cfg);
  const key = bbDraftKey(cfg);
  try {
    let d = null;
    try { d = JSON.parse(localStorage.getItem(key) || 'null'); } catch (e) { d = null; }
    if (!d || typeof d !== 'object') {
      const questions = (cfg && cfg.questions && cfg.questions.length) ? cfg.questions : [cfg && cfg.prompt];
      d = { content: '', answers: questions.map(() => ''), seal: null, warnings: [], savedAt: Date.now() };
    }
    if (!d.seal || typeof d.seal !== 'object') {
      d.seal = { uuid: null, aiScore: undefined, baselineData: null };
    }
    if (typeof d.seal.withOriginal === 'boolean') return d.seal.withOriginal;
    d.seal.withOriginal = !!withOriginal;
    localStorage.setItem(key, JSON.stringify(d));
    return d.seal.withOriginal;
  } catch (e) { return null; }
}

// Build the enforced-conditions list from a config object. Each line says
// what this page actually does. A web page cannot block other applications
// or AI tools, so it says what is not permitted and what is recorded,
// never that something is impossible. `withOriginal` is the sitting's
// Original decision, computed once by the caller (see the briefing) so the
// list and the value saved at Begin cannot differ.
function buildConditions(cfg, withOriginal) {
  return [
    cfg.blockAI   && 'Please write on your own, without AI assistants or other writing tools.',
    cfg.blockWeb  && 'The exam opens full screen. If you leave it or switch tabs, your teacher sees a short note with the time.',
    cfg.blockCopy && 'Copy and paste are turned off in the answer box.',
    withOriginal  && 'Your teacher also sees a few session facts, such as how long you wrote and your word count, as context.',
    cfg.phoneBlk  && 'Please silence your phone and other devices.',
    withOriginal && cfg.aiDetect && 'After you submit, your writing is compared with your own past work. This is a starting point for your teacher, never proof of anything.',
    withOriginal  && 'Your teacher may choose to add this booklet to your writing profile (the past writing your new work is compared with), and can undo that.',
  ].filter(Boolean);
}

function wordCount(text) {
  return text.trim() ? text.trim().split(/\s+/).length : 0;
}

// ─── Timer, word count and seal helpers ───────────────────────────────────────
// Pure, so unit/exam-access.test.mjs can pin exactly what is shown and said.

// The visible clock: mm:ss, with hours once a sitting is an hour or longer.
export function bbClock(sec) {
  const s = Math.max(0, Math.floor(sec || 0));
  const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), r = s % 60;
  const two = n => String(n).padStart(2, '0');
  return h ? `${h}:${two(m)}:${two(r)}` : `${two(m)}:${two(r)}`;
}

const bbPlural = (n, word) => `${n} ${word}${n === 1 ? '' : 's'}`;

// The same time as words a screen reader can say. Seconds only count in
// the last five minutes.
export function bbSpokenTime(sec) {
  const s = Math.max(0, Math.floor(sec || 0));
  const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), r = s % 60;
  const parts = [];
  if (h) parts.push(bbPlural(h, 'hour'));
  if (m) parts.push(bbPlural(m, 'minute'));
  if (s < 300 && r) parts.push(bbPlural(r, 'second'));
  return parts.length ? parts.join(' ') : '0 seconds';
}

// Announced once each, politely, as the clock crosses them.
const BB_TIME_MILESTONES = [1800, 900, 600, 300, 60];

// The announcement for a tick that took the clock from prevLeft to left, or
// null. A clock that skipped several milestones at once (a throttled
// background tab) announces the time actually left, not a stale milestone.
export function bbTimeMilestone(prevLeft, left) {
  const crossed = BB_TIME_MILESTONES.filter(t => prevLeft > t && left <= t);
  if (!crossed.length) return null;
  const t = crossed[crossed.length - 1];
  return `${bbSpokenTime(t - left < 5 ? t : left)} remaining.`;
}

const bbN = n => Number(n).toLocaleString('en-US');

// The answer box's description: where the student stands on length.
export function bbWordSummary(words, min, max) {
  const parts = [`${bbN(words)} word${words === 1 ? '' : 's'} written.`];
  if (max && words > max) {
    parts.push(`You are over the ${bbN(max)}-word limit.`);
    return parts.join(' ');
  }
  if (min) parts.push(words >= min ? `You have reached the ${bbN(min)}-word minimum.` : `Write at least ${bbN(min)} words to submit.`);
  if (max) parts.push(`The limit is ${bbN(max)} words.`);
  return parts.join(' ');
}

// Announced politely when the count crosses the minimum or the limit
// upwards; never on every word.
export function bbWordMilestone(prev, words, min, max) {
  if (max && prev <= max && words > max) return `You are now over the ${bbN(max)}-word limit.`;
  if (min && prev < min && words >= min) return `You have reached the ${bbN(min)}-word minimum.`;
  return null;
}

// Why the seal button is not available yet, or null when it is.
export function bbSealHint(words, min) {
  if (min && words < min) {
    const left = min - words;
    return `Write ${bbN(left)} more word${left === 1 ? '' : 's'} to submit.`;
  }
  return words ? null : 'Write your answer to submit.';
}

// Waits between seal attempts: about 37 seconds in all, long enough to ride
// out a brief outage or a redeploy before the student is told.
export const BB_SEAL_BACKOFF = [2000, 5000, 10000, 20000];

// Whether a failed seal attempt is worth repeating. Network failures carry
// no status and are retried, as are server errors and "slow down". A
// refusal (any other 4xx) will not change on retry, so the seal stops and
// the student is told at once; the draft stays on the device either way.
export function bbSealRetryable(err) {
  const s = err && err.status;
  if (!s) return true;
  if (s === 408 || s === 425 || s === 429) return true;
  return !(s >= 400 && s < 500);
}

// ─── Lockdown helpers (browser-level enforcement) ─────────────────────────────
function bbRequestFullscreen() {
  try {
    const el = document.documentElement;
    const req = el.requestFullscreen || el.webkitRequestFullscreen;
    if (req) { const p = req.call(el); if (p && p.catch) p.catch(() => {}); }
  } catch (e) {}
}
function bbIsFullscreen() {
  return !!(document.fullscreenElement || document.webkitFullscreenElement);
}

// ─── Original integration ───────────────────────────────────────────────────
// Bluebook is the proctored writing source for Original. On submit we derive
// the same institution-scoped, FERPA-friendly student id Original uses
// ({tenant}:{sha256(tenant:identity)[:16]}) and POST the prose + a macro
// composition_summary (session timing, paste counts — no per-key data,
// ADR-010) to /students/{id}/score for a report-only comparison with the
// student's existing baseline. Sealing never adds to that baseline: a
// professor approves which sealed exams become baseline samples.
const BB_API_BASE = window.BB_API_BASE || '';   // same origin by default

function bbSlugify(s) {
  return (s || '').trim().toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '') || 'default';
}

async function bbDeriveStudentId(institution, identity) {
  const tenant = bbSlugify(institution);
  const payload = `${tenant}:${(identity || '').trim().toLowerCase()}`;
  const buf = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(payload));
  const hex = [...new Uint8Array(buf)].map(b => b.toString(16).padStart(2, '0')).join('');
  return `${tenant}:${hex.slice(0, 16)}`;
}

// Resolve the canonical Original student id this exam binds to, preferring a
// real verified identity over the demo candidate label:
//   1. an id passed by an LTI / magic-link launch (window.BB_STUDENT_ID or
//      ?sid= → localStorage.bluebook_student_id) — already canonical, used as-is
//   2. an authenticated student session (student.html login)
//   3. a verified candidate email (exam config / launch) → derived via the bridge
//   4. demo fallback — derived from the candidate label
async function bbResolveStudentId(cfg) {
  const explicit = window.BB_STUDENT_ID || localStorage.getItem('bluebook_student_id');
  if (explicit) return explicit;
  const sessionId = localStorage.getItem('original_student_id');
  if (sessionId && sessionId !== 'demo_student') return sessionId;
  const tenant = localStorage.getItem('original_tenant') || 'demo';
  const email = (cfg && cfg.candidateEmail) || window.BB_CANDIDATE_EMAIL
    || localStorage.getItem('bluebook_candidate_email');
  if (email) return bbDeriveStudentId(tenant, email);
  return bbDeriveStudentId(tenant, (cfg && cfg.candidate) || 'candidate');
}

// The bound student id, if this sitting was launched with one. Same first
// step as bbResolveStudentId's, but synchronous — an id that is already
// canonical needs no derivation, and rendering can't await.
function bbBoundStudentId() {
  try {
    return window.BB_STUDENT_ID || localStorage.getItem('bluebook_student_id') || '';
  } catch (e) { return ''; }
}

// Short form of a canonical Original student id ("{tenant}:{sha256hex[:16]}"):
// the leading 8 characters of the hash half. Opaque by construction — it
// names nobody — but long enough to match against the {sid, name} roster
// `roster_links.py --expected-out` leaves with the invigilator.
function bbShortStudentId(sid) {
  const s = String(sid || '');
  const i = s.indexOf(':');
  return (i === -1 ? s : s.slice(i + 1)).slice(0, 8);
}

// Who the sitting says it belongs to. The identity a launch BOUND must be
// the identity the screens SHOW: /bluebook/launch stores the canonical
// student id, but its links are name-free by default (FERPA), so most bound
// sittings have no name to display and used to fall through to the demo's
// stock candidate number over a perfectly good binding. Precedence:
//   1. a real name — the operator opted into it (roster_links --include-name
//      → ?candidate= → cfg.candidate, index.html's launch bootstrap)
//   2. the bound student's opaque short id — the name-free default
//   3. the stock demo label, when nothing at all is bound
function bbCandidateLabel(cfg) {
  const named = cfg && cfg.candidate;
  if (named && named !== STOCK_CANDIDATE) return named;
  const short = bbShortStudentId(bbBoundStudentId());
  return short ? `Candidate ${short}` : STOCK_CANDIDATE;
}

// Auth header for whatever session is present (principal or student token),
// plus the proctor attestation a magic-link/LTI launch stores in localStorage
// (see original/api.py:bluebook_magic_launch). The seal's score call sends
// both.
function bbAuthHeaders() {
  const h = { 'Content-Type': 'application/json' };
  const token = localStorage.getItem('original_principal_token')
    || localStorage.getItem('original_session_token') || '';
  if (token) h['Authorization'] = 'Bearer ' + token;
  const attestation = localStorage.getItem('bluebook_proctor_token');
  if (attestation) h['X-Proctor-Attestation'] = attestation;
  return h;
}

// Pin the sitting's deadline server-side (robustness spec §1). Returns
// { deadlineMs, offsetMs } (offset = serverNow - clientNow, so deadline math
// runs on server time), or null when the backend is unreachable — the caller
// then degrades open to the local countdown rather than stranding a student.
// The server's answer when this student has already submitted this exam
// (routers/bluebook.py _ALREADY_SUBMITTED, and the dashboard start route):
// from another tab or device, or earlier. A 409 with those words.
export function bbAlreadySubmitted(status, detail) {
  return status === 409 && /already submitted/i.test(String(detail || ''));
}

async function bbStartSession(cfg, studentId) {
  if (!cfg.id) return null;
  // A student loaded this exam through /bluebook/me: start there, so the
  // deadline is clipped to the exam's closing time and the server checks
  // enrolment and the open window. A Bluebook-only workspace gets no
  // proctor token (it never profiles); clear any stale one.
  if (cfg.viaDashboard) {
    try {
      const d = await BB_API.startMyExam(cfg.id);
      try {
        if (d.proctor_token) localStorage.setItem('bluebook_proctor_token', d.proctor_token);
        else localStorage.removeItem('bluebook_proctor_token');
      } catch (e) {}
      const deadlineMs = Date.parse(d.deadline_at);
      if (!deadlineMs) return null;
      return { deadlineMs, offsetMs: Date.parse(d.server_now) - Date.now() };
    } catch (e) { return bbAlreadySubmitted(e && e.status, e && e.message) ? { alreadySubmitted: true } : null; }
  }
  try {
    const r = await fetch(`${BB_API_BASE}/bluebook/exams/${encodeURIComponent(cfg.id)}/session`, {
      method: 'POST', headers: bbAuthHeaders(),
      body: JSON.stringify({
        student_id: studentId || '',
        candidate: cfg.candidateEmail || cfg.candidate || '',
      }),
    });
    if (!r.ok) {
      let detail = '';
      try { detail = (await r.json()).detail || ''; } catch (e) {}
      return bbAlreadySubmitted(r.status, detail) ? { alreadySubmitted: true } : null;
    }
    const d = await r.json();
    const deadlineMs = Date.parse(d.deadline_at);
    if (!deadlineMs) return null;
    return { deadlineMs, offsetMs: Date.parse(d.server_now) - Date.now() };
  } catch (e) { return null; }
}

// Returned by bbScoreWithOriginal when Original refused the call (403): the
// workspace no longer holds it, so the seal proceeds as a Bluebook-only one.
const BB_ORIGINAL_OFF = 'original-off';
// Returned by bbScoreWithOriginal when the student has fewer than 3 approved
// reference samples (baseline_integrity.readiness is not "ready"), or the
// response does not say. NORTH_STAR rule 3: with a thin baseline Original
// cannot tell, so the exam is recorded as INCONCLUSIVE, never marked.
export const BB_NOT_ENOUGH_REFERENCE = 'not-enough-reference';

// Score the submission against the student's EXISTING baseline → returns an
// AI/authorship score (0–100, higher = more authentically theirs), or null when
// there is no baseline yet to compare against (a first proctored sitting), or
// BB_NOT_ENOUGH_REFERENCE when there is one but it is too thin to read, or
// BB_ORIGINAL_OFF when the workspace no longer holds Original. The seal only
// compares; it never writes a baseline (a professor approves those).
export async function bbScoreWithOriginal(studentId, text, assignment, submissionId, compositionSummary) {
  try {
    const r = await fetch(`${BB_API_BASE}/students/${encodeURIComponent(studentId)}/score`, {
      method: 'POST', headers: bbAuthHeaders(),
      body: JSON.stringify({
        text, assignment, submission_id: submissionId || undefined,
        composition_summary: compositionSummary,
      }),
    });
    if (r.status === 403) return BB_ORIGINAL_OFF;
    if (!r.ok) return null;
    const data = await r.json();
    const a = data && data.authorship;
    if (!a) return null;
    const bi = data.baseline_integrity;
    if (!bi || bi.readiness !== 'ready') return BB_NOT_ENOUGH_REFERENCE;
    // Prefer Born-rule authorship probability; fall back to (1 − deviation).
    const prob = a.authorship_probability != null
      ? a.authorship_probability
      : (a.deviation_score != null ? 1 - a.deviation_score : null);
    if (prob == null) return null;
    return Math.max(0, Math.min(100, Math.round(prob * 100)));
  } catch (e) { return null; }
}

// The status a sealed exam is recorded with. Only an Original reading on a
// ready baseline can mark an exam FLAGGED; a thin one is
// INCONCLUSIVE; everything else, including every Bluebook-only exam, is
// SUBMITTED.
export function bbSealStatus(withOriginal, seal) {
  if (!withOriginal) return 'SUBMITTED';
  if (seal.inconclusive) return 'INCONCLUSIVE';
  return seal.aiScore != null && seal.aiScore < 70 ? 'FLAGGED' : 'SUBMITTED';
}

// ─── Briefing Screen ──────────────────────────────────────────────────────────
// Whether this browser belongs to a student (launch link or account).
function bbIsStudent() {
  return BB_API.isStudentLaunch() || BB_API.isStudentAccount();
}

export function BriefingScreen({ onNavigate }) {
  // A launch link that named a stored exam (?exam_id=) arrives with only its
  // id and title: fetch the teacher's real exam before showing anything, so
  // the student is never briefed on the built-in sample question.
  const pending = !!(window.BB_EXAM_CONFIG && window.BB_EXAM_CONFIG.fromLaunch
    && window.BB_EXAM_CONFIG.id && !window.BB_EXAM_CONFIG.loaded && bbIsStudent());
  const [loadState, setLoadState] = useExState(pending ? 'loading' : 'ready');
  const [loadError, setLoadError] = useExState('');
  useExEffect(() => {
    if (!pending) return;
    let live = true;
    BB_API.myExam(window.BB_EXAM_CONFIG.id)
      .then(d => {
        if (!live) return;
        window.BB_EXAM_CONFIG = examToConfig(d, {
          viaDashboard: true,
          candidate: window.BB_EXAM_CONFIG.candidate,
          candidateEmail: window.BB_EXAM_CONFIG.candidateEmail,
        });
        setLoadState('ready');
      })
      .catch(err => {
        if (!live) return;
        setLoadError(err && err.status === 401
          ? 'Your sign-in has expired. Please sign in again to open this exam.'
          : 'We could not open this exam just now. Please refresh the page, or ask your teacher for a new link.');
        setLoadState('error');
      });
    return () => { live = false; };
  }, []);

  const cfg = getExamConfig();
  // Computed once per render: the conditions list below and the decision
  // saved at Begin both use this value.
  const withOriginal = bbOriginalForSitting(cfg);
  const conditions = buildConditions(cfg, withOriginal);
  const studentAccount = BB_API.isStudentAccount();
  const cannotBegin = cfg.loaded && cfg.state && cfg.state !== 'open';
  if (loadState !== 'ready') {
    return (
      <div className="bk-stage bb-screen">
        <MockupFonts hand />
        <div className="bk-booklet compact">
          <div className="bk-cover">
            <div className="bk-cover-inner">
              <span className="bk-exam-lbl">Examination Booklet</span>
              <h1>Collections</h1>
              <p role={loadState === 'error' ? 'alert' : 'status'} className="bk-cover-note state">
                {loadState === 'error' ? loadError : 'Opening your exam…'}
              </p>
            </div>
          </div>
        </div>
      </div>
    );
  }
  const questionCount = (cfg.questions || []).length || 1;
  const limits = [
    cfg.minWords ? `At least ${cfg.minWords.toLocaleString()} words.` : null,
    cfg.maxWords ? `No more than ${cfg.maxWords.toLocaleString()} words.` : null,
  ].filter(Boolean).join(' ');
  const today = new Date().toLocaleDateString(undefined, { day: 'numeric', month: 'long', year: 'numeric' });
  return (
    <div className="bk-stage bb-screen">
      <MockupFonts hand />
      <div className="bk-booklet">
        <div className="bk-cover">
          {/* A launch-link student has nowhere else to go; an account student
              goes back to their exams; staff previewing go back to the list. */}
          {(!BB_API.isStudentLaunch()) && (
            <button type="button" className="bk-leave" onClick={() => onNavigate(studentAccount ? 'student-home' : 'exams')}>
              <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M15 6l-6 6 6 6"/></svg>
              {studentAccount ? 'My exams' : 'Examinations'}
            </button>
          )}

          <div className="bk-cover-inner">
            <span className="bk-exam-lbl">Before you begin</span>
            <h1>Collections</h1>
            <div className="bk-rule" />

            <div className="bk-fields">
              <div className="bk-field"><b>Name</b><span className="fill hand">{bbCandidateLabel(cfg)}</span></div>
              {cfg.courseTitle && <div className="bk-field"><b>Course</b><span className="fill">{cfg.courseTitle}</span></div>}
              <div className="bk-field"><b>Exam</b><span className="fill">{cfg.title}</span></div>
              <div className="bk-field"><b>Date</b><span className="fill">{today}</span></div>
            </div>

            <p className="bk-meta">
              <b>{questionCount} question{questionCount === 1 ? '' : 's'} · {cfg.duration / 60} minutes.</b>
              {limits && ` ${limits}`} Your work saves itself on this device as you write. The clock starts when you open the booklet.
            </p>
            {cfg.closesAt && (
              <p className="bk-closes">Closes {new Date(cfg.closesAt).toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' })}</p>
            )}

            <div className="bk-conditions">
              <h2>How this exam works</h2>
              <ul>
                {conditions.map(rule => <li key={rule}>{rule}</li>)}
              </ul>
              {(cfg.blockWeb || cfg.blockCopy) && (
                <p className="bk-conditions-note">These notes help your teacher understand the session. Short moments away are normal.</p>
              )}
              {/* Before the clock starts, so reading it costs no exam time. */}
              <p className="bk-conditions-note">
                <a href="../legal/student-notice.html" target="_blank" rel="noopener">What Collections keeps, and what it does not</a>
              </p>
            </div>

            {cannotBegin ? (
              <p role="status" className="bk-cover-note state">
                {cfg.state === 'upcoming'
                  ? 'This exam is not open yet. Please come back at the time your teacher gave you.'
                  : 'This exam has closed. If you think that is a mistake, please talk to your teacher.'}
              </p>
            ) : (
              <button type="button" className="bk-begin" onClick={() => { if (cfg.blockWeb) bbRequestFullscreen(); bbLockOriginalDecision(cfg, withOriginal); onNavigate('exam'); }}>
                {cfg.inProgress ? 'Resume Examination' : 'Begin Examination'}
              </button>
            )}
            <p className="bk-cover-note">Once you begin, the clock keeps running, even if you close this page</p>
            <p className="bk-cover-note">{withOriginal ? 'Original · Collections · quiet by design' : 'Collections · quiet by design'}</p>
          </div>
        </div>
      </div>
    </div>
  );
}

// ─── Active Examination Screen ────────────────────────────────────────────────
// The answers joined as the teacher reads them. A single-question (or legacy
// prompt-only) exam is a list of one, so everything downstream reads the
// joined text exactly as it read the single answer before.
function bbJoinAnswers(answers, multi) {
  return multi ? answers.map((a, i) => `Question ${i + 1}.\n${a}`).join('\n\n') : answers[0];
}

function bbNewSealId() {
  return (window.crypto && crypto.randomUUID)
    ? crypto.randomUUID()
    : 'uu-' + Date.now() + '-' + Math.random().toString(16).slice(2);
}

// What the student is shown when the page notes something for the teacher.
// Plain statements of what happened: never a warning, a rule restated as a
// threat, or a guess about why. Only the event's type and time go to the
// teacher (see recordWarning), never these words.
export const BB_NOTICE = {
  focus_lost:      'You moved away from the exam window.',
  tab_hidden:      'The exam tab was in the background for a moment.',
  fullscreen_exit: 'Full screen was turned off. You can turn it back on with the button at the top.',
  print_or_save:   'Printing and saving are turned off during this exam.',
  paste_blocked:   'Pasting is turned off for this exam, so nothing was added.',
};

export function ExamScreen({ onNavigate, writingSize = 18, parchmentColor = PARCHMENT_SHADES.warm }) {
  const cfg = getExamConfig();
  const candidateLabel = bbCandidateLabel(cfg);
  // Draft persistence: a sitting must survive a crash, a refresh, a dropped
  // connection or an accidental exit. The draft is keyed per exam and per
  // student (bbDraftKey), written as the student types, restored on mount,
  // and removed only once the seal has been delivered.
  const draftKey = bbDraftKey(cfg);
  bbAdoptLegacyDraft(cfg);
  const restored = (() => {
    try { return JSON.parse(localStorage.getItem(draftKey) || 'null'); }
    catch (e) { return null; }
  })();
  const questions = (cfg.questions && cfg.questions.length) ? cfg.questions : [cfg.prompt];
  const multi = questions.length > 1;
  const [answers,     setAnswers]     = useExState(() => {
    const saved = restored && Array.isArray(restored.answers) ? restored.answers
      : [(restored && restored.content) || ''];
    return questions.map((_, i) => saved[i] || '');
  });
  const [qIndex,      setQIndex]      = useExState(0);
  const [promptOpen,  setPromptOpen]  = useExState(true);
  const content = bbJoinAnswers(answers, multi);
  const words = answers.reduce((n, a) => n + wordCount(a), 0);
  // timeLeft is display state DERIVED from the server deadline each tick
  // (see the countdown effect). It is deliberately not restored from the
  // draft: persisting a countdown remainder let closing the tab pause the
  // clock. With no session (degrade-open) the local countdown restarts.
  const [timeLeft,    setTimeLeft]    = useExState(cfg.duration);
  const [saving,      setSaving]      = useExState(false);
  const [warnLog,     setWarnLog]     = useExState([]); // [{ id, msg }] for this page; never auto-dismissed
  const [warnLogOpen, setWarnLogOpen] = useExState(true);
  const [submitting,  setSubmitting]  = useExState(false);
  const [sealNote,    setSealNote]    = useExState('');   // visible progress while sealing
  const [fsLost,      setFsLost]      = useExState(false);
  const [liveMsg,     setLiveMsg]     = useExState('');   // the one polite live region
  const [storageOk,   setStorageOk]   = useExState(true);
  const textareaRef = useExRef(null);
  const saveTimer   = useExRef(null);
  const deadlineRef = useExRef(null);   // { deadlineMs, offsetMs } once the session lands
  // Seal progress survives refreshes so a retried seal is idempotent end to
  // end: the same uuid, and completed steps never re-run.
  const sealRef     = useExRef((restored && restored.seal) || { uuid: null, aiScore: undefined, baselineData: null });
  // Whether this sitting goes to Original is decided here, once, on first
  // entry, and kept in the draft (see bbOriginalForSitting). A restored
  // decision stands even if the workspace's products have changed since.
  const decidedNowRef = useExRef(false);
  if (typeof sealRef.current.withOriginal !== 'boolean') {
    sealRef.current.withOriginal = BB_API.hasOriginal();
    decidedNowRef.current = true;
  }
  const [offline, setOffline] = useExState(typeof navigator !== 'undefined' && navigator.onLine === false);
  // Live refs so event, interval and retry callbacks always see current values.
  const contentRef  = useExRef(content);
  contentRef.current  = content;
  const answersRef  = useExRef(answers);
  answersRef.current  = answers;
  // "Anything written at all": the joined content always contains the
  // question headers for a multi-question exam, so test the answers.
  const hasWriting = () => answersRef.current.some(a => a.trim());
  // Once the student confirms the seal (or time runs out) the answers are
  // final. A draft that was already final when this screen mounted (a
  // refresh mid-seal, or "Try again" after a failed one) is not reopened
  // for editing: the same seal is finished instead. Editing it would be
  // lost anyway if the first attempt had in fact reached the server, which
  // keeps the first copy of a submission id.
  const resumeRef   = useExRef(!!sealRef.current.confirmedAt && answers.some(a => a.trim()));
  const [locked, setLocked] = useExState(resumeRef.current);
  const lockedRef   = useExRef(resumeRef.current);
  // One seal at a time. State updates land a render late, so a synchronous
  // ref (not `submitting`) stops a double press, or time expiry racing a
  // press, from starting two seal loops.
  const sealingRef  = useExRef(false);
  // This student has already submitted this exam (another tab or device, or
  // earlier): the booklet stays closed and nothing is sent.
  const [alreadySubmitted, setAlreadySubmitted] = useExState(false);
  const alreadySubmittedRef = useExRef(false);
  const announcedSaveRef = useExRef(false);
  // Session facts carried across a refresh: when writing started, and how
  // many pastes were attempted. No per-key data is kept (NORTH_STAR rule 6).
  const startedAtRef = useExRef((restored && restored.startedAt) || null);
  const pastesRef    = useExRef((restored && restored.pastes) || 0);
  // Every notice also goes to the teacher with the seal: its type and time
  // only, never the message text or anything about the page.
  const warnEventsRef = useExRef((restored && restored.warnings) || []);

  function writeDraftNow() {
    try {
      localStorage.setItem(draftKey, JSON.stringify({
        content: contentRef.current,
        answers: answersRef.current,
        seal: sealRef.current,
        warnings: warnEventsRef.current,
        startedAt: startedAtRef.current,
        pastes: pastesRef.current,
        savedAt: Date.now(),
      }));
      setStorageOk(true);
      return true;
    } catch (e) {
      // Private browsing, a full disk or blocked storage. Say so (see the
      // banner) rather than let the student believe a copy is being kept.
      setStorageOk(false);
      return false;
    }
  }

  // One notice per real event: blur and visibilitychange fire together for
  // a single tab switch, so repeats inside 1.5s collapse into one.
  const lastWarnRef = useExRef(0);
  // True only while the seal confirmation is open. The browser may blur the
  // window for its own dialog; that is not the student leaving the exam, so
  // nothing is recorded (or sent to the teacher) while it is up.
  const sealPromptRef = useExRef(false);
  function recordWarning(msg, type = 'other') {
    // Nothing is noted once the answers are final: what a student does while
    // the seal is on its way is not part of the sitting, and the notes sent
    // with every retry stay exactly those of the sitting.
    if (sealPromptRef.current || lockedRef.current) return;
    const now = Date.now();
    if (now - lastWarnRef.current < 1500) return;
    lastWarnRef.current = now;
    warnEventsRef.current = [...warnEventsRef.current, { type, at: new Date(now).toISOString() }].slice(-500);
    writeDraftNow();
    setWarnLog(log => [...log, { id: now, msg }]);
    setWarnLogOpen(true);
    // Polite: a notice is information for later, not an interruption.
    setLiveMsg(`Noted for your teacher. ${msg}`);
  }

  function buildCompositionSummary() {
    const started = startedAtRef.current;
    return {
      session_seconds: started ? Math.max(0, Math.round((Date.now() - started) / 1000)) : 0,
      word_count:      wordCount(contentRef.current),
      paste_attempts:  pastesRef.current,
      focus_losses:    warnEventsRef.current.length,
      started_at:      started ? new Date(started).toISOString() : '',
      ended_at:        new Date().toISOString(),
      exam_config: {
        block_copy:   !!cfg.blockCopy,
        min_words:    cfg.minWords,
        duration_min: Math.round(cfg.duration / 60),
      },
    };
  }

  async function handleSubmit(opts = {}) {
    // opts.force: time expiry (or finishing a seal already confirmed) seals
    // whatever exists, bypassing the word minimum. A student must never be
    // stranded at a dead 00:00.
    if (sealingRef.current || alreadySubmittedRef.current) return;
    if (!opts.force && (words < cfg.minWords || !hasWriting())) return;
    if (opts.force && !hasWriting()) {
      // Nothing written when time ran out: don't record an empty submission.
      // The draft holds only this sitting's Original decision (no writing),
      // so clear it: the next person to sit this exam on this browser must
      // decide afresh, not inherit it. Nothing below reads the draft.
      try { localStorage.removeItem(draftKey); } catch (e) {}
      window.BB_LAST_SUBMISSION = {
        words: 0, title: cfg.title, courseTitle: cfg.courseTitle,
        candidate: candidateLabel, studentId: null,
        ok: false, error: 'No text was written before time expired',
        expired: true, empty: true,
      };
      onNavigate('submitted');
      return;
    }
    sealingRef.current = true;
    lockedRef.current = true;
    setLocked(true);
    setSubmitting(true);
    // Idempotent, retryable sealing (robustness spec §2): one uuid per seal,
    // persisted in the draft with per-step results, so a refresh-and-reseal
    // or network retry never repeats a completed step. Everything a retry
    // sends is fixed at the moment the answers became final.
    const seal = sealRef.current;
    if (!seal.uuid) seal.uuid = bbNewSealId();
    if (!seal.confirmedAt) {
      seal.confirmedAt = new Date().toISOString();
      seal.expired = !!opts.expired;
      seal.timeMin = Math.max(0, Math.round(((cfg.duration || 0) - timeLeft) / 60));
      seal.summary = buildCompositionSummary();
    }
    writeDraftNow();   // the draft (answers + seal state) survives a failed seal
    const finalText = contentRef.current;
    const finalAnswers = answersRef.current;

    const waitOnline = () => new Promise((res) => {
      if (navigator.onLine !== false) return res();
      const h = () => { window.removeEventListener('online', h); res(); };
      window.addEventListener('online', h);
    });

    const studentId = await bbResolveStudentId(cfg);
    // A Bluebook-only workspace never calls Original: the server 403s those
    // routes for it anyway, and its students are not profiled. The sitting's
    // own decision, not the products stored now: switching Original on
    // mid-exam must not compare a submission the student was told would not
    // be. `let`: an operator can switch Original off while this sitting
    // still holds it.
    let withOriginal = typeof seal.withOriginal === 'boolean' ? seal.withOriginal : BB_API.hasOriginal();
    let result = null;
    let lastError = null;
    const attempts = BB_SEAL_BACKOFF.length + 1;
    for (let attempt = 0; attempt < attempts; attempt++) {
      try {
        if (navigator.onLine === false) {
          setSealNote('Waiting for the connection. Your answers will be submitted when the connection returns.');
          await waitOnline();
        }
        setSealNote(attempt ? `Still submitting (try ${attempt + 1} of ${attempts}). Your answers are saved on this device.` : 'Submitting your answers…');
        // 1) Score against the EXISTING baseline (skipped on retry once known).
<<<<<<< HEAD
        // Only when the teacher switched writing consistency on for this exam
        // (conditions.aiDetect, off by default).
        if (withOriginal && cfg.aiDetect && seal.aiScore === undefined) {
          const scored = await bbScoreWithOriginal(studentId, content, cfg.title, seal.uuid, buildCompositionSummary());
=======
        if (withOriginal && seal.aiScore === undefined) {
          const scored = await bbScoreWithOriginal(studentId, finalText, cfg.title, seal.uuid, seal.summary);
>>>>>>> origin/main
          if (scored === BB_ORIGINAL_OFF) {
            // The workspace no longer holds Original (switched off since this
            // page loaded). A 403 will not change on retry, so seal exactly as
            // a Bluebook-only workspace does instead of stranding the exam.
            withOriginal = false;
            seal.withOriginal = false;
            seal.aiScore = null;
            BB_API.dropOriginal();
          } else if (scored === BB_NOT_ENOUGH_REFERENCE) {
            seal.aiScore = null;
            seal.inconclusive = true;
          } else {
            seal.aiScore = scored;
          }
          writeDraftNow();
        }
        // 2) Record the sealed submission (the server dedupes by
        // submission_uuid). Compare-only (plan Phase 7): the seal never adds
        // to the student's baseline; a professor approves which sealed exams
        // become baseline samples.
        const status = bbSealStatus(withOriginal, seal);
        // Throws on failure, so a lost submission row retries like any other
        // step instead of reporting "sealed" and deleting the draft.
        await BB_API.recordSubmission({
          exam_id:     cfg.id || null,
          student_id:  studentId,
          candidate:   cfg.candidateEmail || cfg.candidate,
          exam_title:  cfg.title,
          course:      cfg.course,
          word_count:  wordCount(finalText),
          time_min:    seal.timeMin,
          stylometric: null,
          ai_score:    withOriginal ? seal.aiScore : null,
          status,
          submission_uuid: seal.uuid,
          text:        finalText,
          answers:     finalAnswers,
          warnings:    warnEventsRef.current,
        });
        result = { ok: true, studentId };
        break;
      } catch (e) {
        lastError = e;
        if (!bbSealRetryable(e) || attempt === attempts - 1) break;
        const wait = BB_SEAL_BACKOFF[attempt];
        const msg = `The server did not answer. Trying again in ${Math.round(wait / 1000)} seconds. Your answers are saved on this device.`;
        setSealNote(msg);
        setLiveMsg(msg);
        await new Promise(res => setTimeout(res, wait));
      }
    }

    if (result && result.ok) {
      // Sealed and delivered: the on-device draft has served its purpose.
      try { localStorage.removeItem(draftKey); } catch (e) {}
    }
    window.BB_LAST_SUBMISSION = {
      words: wordCount(finalText),
      title: cfg.title,
      courseTitle: cfg.courseTitle,
      candidate: candidateLabel,
      studentId: (result && result.studentId) || studentId,
      ok: !!(result && result.ok),
      error: (result && result.ok) ? null : String((lastError && lastError.message) || lastError || 'seal failed'),
      aiScore: seal.aiScore,
      withOriginal,
      expired: !!seal.expired,
      alreadySubmitted: !(result && result.ok) && bbAlreadySubmitted(lastError && lastError.status, lastError && lastError.message),
      draftKey,
    };
    sealingRef.current = false;
    setSubmitting(false);
    onNavigate('submitted');
  }

  // Server-pinned deadline (robustness spec §1): first call pins it, later
  // calls (any refresh) get the same one back. clockReady marks the moment
  // the clock is worth announcing: the server answered, or it could not.
  const clockReadyRef = useExRef(false);
  useExEffect(() => {
    let cancelled = false;
    (async () => {
      const sid = await bbResolveStudentId(cfg);
      const sess = await bbStartSession(cfg, sid);
      if (cancelled) return;
      if (sess && sess.alreadySubmitted) {
        // A seal this tab is finishing may be the very submission the server
        // already holds (its reply was lost): let it finish, and the server
        // returns that row. Otherwise the booklet stays closed.
        if (!resumeRef.current) {
          alreadySubmittedRef.current = true;
          lockedRef.current = true;
          setLocked(true);
          setAlreadySubmitted(true);   // the banner is a status: it is announced
        }
      } else if (sess) {
        deadlineRef.current = sess;
      }
      clockReadyRef.current = true;
    })();
    return () => { cancelled = true; };
  }, []);

  // Countdown: derived from the server deadline when there is one, so a
  // reload can't pause the clock; a plain local countdown otherwise.
  useExEffect(() => {
    const id = setInterval(() => {
      const sess = deadlineRef.current;
      if (sess) {
        setTimeLeft(Math.max(0, Math.round((sess.deadlineMs - (Date.now() + sess.offsetMs)) / 1000)));
      } else {
        setTimeLeft(t => t > 0 ? t - 1 : 0);
      }
    }, 1000);
    return () => clearInterval(id);
  }, []);

  // Polite time announcements: the time left once the clock is known, then
  // each milestone as it is crossed. Never every tick.
  const prevLeftRef = useExRef(null);
  const announcedStartRef = useExRef(false);
  useExEffect(() => {
    const prev = prevLeftRef.current;
    prevLeftRef.current = timeLeft;
    if (!cfg.duration || prev == null || !clockReadyRef.current || timeLeft <= 0) return;
    if (!announcedStartRef.current) {
      announcedStartRef.current = true;
      setLiveMsg(`${bbSpokenTime(timeLeft)} remaining.`);
      return;
    }
    const msg = bbTimeMilestone(prev, timeLeft);
    if (msg) setLiveMsg(msg);
  }, [timeLeft]);

  // Offline awareness (robustness spec §3): a persistent banner; the seal
  // retry loop parks on the matching 'online' event.
  useExEffect(() => {
    const goOff = () => { setOffline(true);  setLiveMsg('Connection lost. Your writing is still saved on this device.'); };
    const goOn  = () => { setOffline(false); setLiveMsg('Connection restored.'); };
    window.addEventListener('offline', goOff);
    window.addEventListener('online', goOn);
    return () => { window.removeEventListener('offline', goOff); window.removeEventListener('online', goOn); };
  }, []);

  // Time expiry: seal whatever is written. Without this the countdown died
  // silently at 00:00 with the seal button still disabled below the word
  // minimum, and the student was stranded.
  useExEffect(() => {
    if (timeLeft > 0 || !cfg.duration) return;
    handleSubmit({ force: true, expired: true });
  }, [timeLeft]);

  // Persist a sitting decision taken on this mount at once, so a reload keeps
  // it before the student has written anything. Silent: with no writing
  // there is nothing to announce.
  useExEffect(() => {
    if (decidedNowRef.current) writeDraftNow();
  }, []);

  // On entry: finish a seal that was already final, or put the student in
  // the answer box so they can start writing straight away.
  useExEffect(() => {
    if (resumeRef.current) {
      setLiveMsg('Your answers were already final. Finishing your submission now.');
      handleSubmit({ force: true });
    } else if (textareaRef.current) {
      textareaRef.current.focus();
    }
  }, []);

  // The "saved" mark appears after a pause in typing. The draft itself is
  // written on every change (handleChange); the 30s interval keeps the
  // saved time fresh while idle, and pagehide/hidden flush it once more.
  useExEffect(() => {
    if (!hasWriting()) return;
    const deb = setTimeout(() => {
      if (writeDraftNow()) {
        setSaving(true);
        setTimeout(() => setSaving(false), 1800);
      }
    }, 1500);
    return () => clearTimeout(deb);
  }, [content]);
  useExEffect(() => {
    saveTimer.current = setInterval(() => {
      if (hasWriting()) writeDraftNow();
    }, 30000);
    const flush = () => { if (hasWriting()) writeDraftNow(); };
    const onHidden = () => { if (document.hidden) flush(); };
    window.addEventListener('pagehide', flush);
    document.addEventListener('visibilitychange', onHidden);
    return () => {
      clearInterval(saveTimer.current);
      window.removeEventListener('pagehide', flush);
      document.removeEventListener('visibilitychange', onHidden);
    };
  }, []);

  // Polite word-count milestones: the minimum reached, the limit passed.
  const prevWordsRef = useExRef(words);
  useExEffect(() => {
    const msg = bbWordMilestone(prevWordsRef.current, words, cfg.minWords, cfg.maxWords);
    prevWordsRef.current = words;
    if (msg) setLiveMsg(msg);
  }, [words]);

  // Focus monitoring: active when the browser is locked to the exam.
  useExEffect(() => {
    if (!cfg.blockWeb) return;
    function onBlur() {
      recordWarning(BB_NOTICE.focus_lost, 'focus_lost');
    }
    window.addEventListener('blur', onBlur);
    return () => window.removeEventListener('blur', onBlur);
  }, []);

  // Browser-level lockdown: full screen, tab visibility, right-click, an
  // unload guard and the print/save keys. A web page can enforce these
  // in-page; a hard "no AI / no web" guarantee would need a native lockdown
  // browser.
  useExEffect(() => {
    const off = [];
    const on = (target, type, fn, opts) => { target.addEventListener(type, fn, opts); off.push([target, type, fn, opts]); };
    const warn = recordWarning;
    if (cfg.blockWeb) {
      on(document, 'visibilitychange', () => {
        if (document.hidden) warn(BB_NOTICE.tab_hidden, 'tab_hidden');
      });
      on(document, 'fullscreenchange', () => {
        const fs = bbIsFullscreen();
        setFsLost(!fs);
        if (!fs) warn(BB_NOTICE.fullscreen_exit, 'fullscreen_exit');
      });
      on(window, 'beforeunload', (e) => { writeDraftNow(); e.preventDefault(); e.returnValue = ''; return ''; });
      on(document, 'keydown', (e) => {
        const k = (e.key || '').toLowerCase();
        if ((e.ctrlKey || e.metaKey) && (k === 'p' || k === 's')) {
          e.preventDefault();
          warn(BB_NOTICE.print_or_save, 'print_or_save');
        }
      });
    }
    if (cfg.blockCopy) {
      on(document, 'contextmenu', (e) => e.preventDefault());
      on(document, 'keydown', (e) => {
        const k = (e.key || '').toLowerCase();
        if ((e.ctrlKey || e.metaKey) && (k === 'c' || k === 'x' || k === 'v')) e.preventDefault();
      });
    }
    return () => off.forEach(([t, ty, fn, o]) => t.removeEventListener(ty, fn, o));
  }, []);

  function handleChange(e) {
    if (lockedRef.current) return;
    const val = e.target.value;
    if (startedAtRef.current == null) startedAtRef.current = Date.now();
    const next = answersRef.current.map((a, i) => (i === qIndex ? val : a));
    answersRef.current = next;
    contentRef.current = bbJoinAnswers(next, multi);
    setAnswers(next);
    // Written now, not after a pause: a refresh one keystroke later keeps it.
    if (writeDraftNow() && !announcedSaveRef.current) {
      announcedSaveRef.current = true;
      setLiveMsg('Your writing is saved on this device as you type.');
    }
  }
  function goToQuestion(i) {
    setQIndex(i);
    setLiveMsg(`Question ${i + 1} of ${questions.length}.`);
    setTimeout(() => textareaRef.current && textareaRef.current.focus(), 0);
  }

  const isLow     = timeLeft <= 300;
  const isVeryLow = timeLeft <= 60;
  const overMax   = cfg.maxWords && words > cfg.maxWords;
  const atMin     = words >= cfg.minWords;
  const sealHint  = submitting || locked ? null : bbSealHint(words, cfg.minWords);

  // The paper keeps the design's cream unless a shade other than the old
  // default was picked in the dev-only Tweaks panel.
  const paper = parchmentColor && parchmentColor !== PARCHMENT_SHADES.warm ? parchmentColor : undefined;
  const crsLabel = [cfg.course, cfg.title].filter(Boolean).join(' · ');
  const wantsMin = cfg.minWords > 0;
  const fillPct = wantsMin ? Math.min(100, (words / cfg.minWords) * 100) : 0;

  return (
    <main className="bk-stage">
      <MockupFonts hand />
      <h1 className="bk-sr">{cfg.title || 'Examination'}</h1>
      {/* The one polite live region: time and word-count milestones, saving,
          connection and notices. Never interrupts the student. */}
      <div role="status" aria-live="polite" className="bk-sr">{liveMsg}</div>

      {/* The Blue Book */}
      <div className="bk-booklet">
        <div className="bk-page" style={paper ? { '--bk-paper': paper } : undefined}>

          {/* ── Bar: course, question tabs, saved, timer ── */}
          <div className="bk-bar">
            <span className="bk-crs">{crsLabel}</span>
            {/* Instructor-preview exit. Hidden for real student launches: one
                stray click must never cost a student their essay. The draft
                is kept on this device, so re-entry restores it. */}
            {!bbIsStudent() && (
              <button type="button" className="bk-exit" onClick={() => {
                writeDraftNow();
                if (confirm('Leave the preview? Your draft is saved on this device and will be restored when you come back.')) {
                  onNavigate('briefing');
                }
              }}>
                <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M15 6l-6 6 6 6"/></svg>
                Exit Exam
              </button>
            )}
            {multi && (
              <div className="bk-qtabs" role="group" aria-label="Questions">
                {questions.map((_, i) => (
                  <button key={i} type="button" onClick={() => goToQuestion(i)}
                    aria-current={i === qIndex ? 'step' : undefined}
                    aria-label={`Question ${i + 1}${answers[i].trim() ? ', answered' : ''}`}
                    className="bk-qtab">
                    {`Q${i + 1}`}
                    {answers[i].trim() && <span aria-hidden="true"> ✓</span>}
                  </button>
                ))}
              </div>
            )}
            <div className="bk-bar-right">
              <span className="bk-cand">{candidateLabel}</span>
              {cfg.blockWeb && fsLost && (
                <button type="button" className="bk-restore" onClick={bbRequestFullscreen}>
                  <span aria-hidden="true">↺ </span>Restore full-screen
                </button>
              )}
              <span className={'bk-saved' + (saving ? ' show' : '')} aria-hidden="true">
                <svg viewBox="0 0 24 24"><path d="M20 6L9 17l-5-5"/></svg>saved
              </span>
              <span className={'bk-timer' + (isVeryLow ? ' vlow' : isLow ? ' low' : '')}>
                <svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="13" r="8"/><path d="M12 9v4l2.5 2.5"/><path d="M9 2h6"/></svg>
                <span className="bk-timer-lbl" aria-hidden="true">Time left</span>
                <span role="timer" aria-label={`Time remaining: ${bbSpokenTime(timeLeft)}`}>{bbClock(timeLeft)}</span>
              </span>
            </div>
          </div>

          {/* Connection and storage state (robustness spec §3): persistent
              while they last, in flow, so they never cover the seal button. */}
          {offline && (
            <div role="status" className="bk-offline">
              {submitting
                ? 'You are offline. Your answers are saved on this device.'
                : 'You are offline. Your writing is saved on this device, and you can keep writing.'}
            </div>
          )}
          {alreadySubmitted && (
            <div role="status" className="bk-offline">
              You have already submitted this exam, so this booklet cannot be sent again. Your teacher has the work you submitted. If you need to change something, please talk to your teacher.
            </div>
          )}
          {!storageOk && (
            <div role="status" className="bk-offline">
              This browser cannot keep a copy of your writing on this device. Please keep this window open until you have submitted.
            </div>
          )}

          {/* Notes for the teacher: what the page recorded (leaving the
              window, a blocked paste). In flow under the bar, so the timer,
              question tabs and full-screen button are never covered.
              Announced politely through the live region above. */}
          {warnLog.length > 0 && (
            <section className="bk-notices" aria-labelledby="bbNoticesHead">
              <div className="bk-notices-head">
                <h2 id="bbNoticesHead">Notes for your teacher ({warnLog.length})</h2>
                <button type="button" aria-expanded={warnLogOpen} aria-controls="bbNoticesList"
                  onClick={() => setWarnLogOpen(o => !o)}>{warnLogOpen ? 'Hide' : 'Show'}</button>
              </div>
              <div id="bbNoticesList" hidden={!warnLogOpen}>
                <p className="bk-notices-note">Your teacher sees these with the time, as context. They are not a judgement about you or your work.</p>
                <ul>
                  {warnLog.map(w => (
                    <li key={w.id}>
                      <span className="bk-notices-time">{new Date(w.id).toLocaleTimeString(undefined, { hour: 'numeric', minute: '2-digit' })}</span>{' '}
                      <span>{w.msg}</span>
                    </li>
                  ))}
                </ul>
              </div>
            </section>
          )}

          {/* ── Sheet: the current question and the ruled writing area ── */}
          <div className="bk-sheet">
            <div className="bk-sheet-inner">
              <section className="bk-qhead" aria-labelledby="bbQn">
                <div className="bk-qtop">
                  <h2 className="bk-qn" id="bbQn">{multi ? `Question ${qIndex + 1} of ${questions.length}` : 'Examination prompt'}</h2>
                  <button type="button" className="bk-qlink" onClick={() => setPromptOpen(o => !o)}
                    aria-expanded={promptOpen} aria-controls="bbQuestionText">
                    {promptOpen ? 'Hide question' : 'Show question'}
                  </button>
                </div>
                <p className="bk-qtext" id="bbQuestionText" hidden={!promptOpen}>{questions[qIndex]}</p>
                {multi && (
                  <div className="bk-qnav">
                    <button type="button" className="bk-qlink" disabled={qIndex === 0} onClick={() => goToQuestion(qIndex - 1)}>
                      <span aria-hidden="true">← </span>Previous
                    </button>
                    <button type="button" className="bk-qlink" disabled={qIndex === questions.length - 1} onClick={() => goToQuestion(qIndex + 1)}>
                      Next<span aria-hidden="true"> →</span>
                    </button>
                  </div>
                )}
              </section>

              <div className="bk-writing" style={{ '--bk-fs': `${writingSize}px`, '--bk-lh': `${writingSize + 16}px` }}>
                <textarea
                  key={qIndex}
                  ref={textareaRef}
                  value={answers[qIndex]}
                  onChange={handleChange}
                  readOnly={locked}
                  onPaste={e => {
                    if (locked) return;
                    pastesRef.current += 1;   // the attempt is a session fact
                    if (cfg.blockCopy) {
                      e.preventDefault();
                      recordWarning(BB_NOTICE.paste_blocked, 'paste_blocked');
                    } else {
                      writeDraftNow();
                    }
                  }}
                  onCopy={e => { if (cfg.blockCopy) e.preventDefault(); }}
                  onCut={e => { if (cfg.blockCopy) e.preventDefault(); }}
                  spellCheck={!!cfg.spellChk}
                  autoComplete="off"
                  autoCorrect="off"
                  placeholder="Begin writing here…"
                  aria-label={multi ? `Your answer to question ${qIndex + 1}` : 'Your examination answer'}
                  aria-describedby="bbQuestionText bbWordSummary"
                />
              </div>
            </div>
          </div>

          {/* ── Foot: word count, what is kept, seal ── */}
          <div className="bk-foot">
            <div className="bk-wc">
              {wantsMin && (
                <div className="bk-wc-track" aria-hidden="true"><div className={'bk-wc-fill' + (atMin ? ' met' : '')} style={{ width: `${fillPct}%` }} /></div>
              )}
              <span className={'bk-wc-n' + (overMax ? ' over' : '')} aria-hidden="true">
                <b>{words.toLocaleString()}</b>
                {wantsMin ? ` of ${cfg.minWords.toLocaleString()} words` : ` word${words === 1 ? '' : 's'}`}
                {overMax ? ' · over the limit' : ''}
              </span>
              <span id="bbWordSummary" className="bk-sr">{bbWordSummary(words, cfg.minWords, cfg.maxWords)}</span>
            </div>
            <span className="bk-capture">
              <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 3l8 4v6c0 5-3.5 7.5-8 8-4.5-.5-8-3-8-8V7z"/><path d="M9 12l2 2 4-4"/></svg>
              Collections saves your words and a few session facts (time, word count, pastes, print or save attempts, leaving the window). Your screen is never watched.
            </span>
            <div className="bk-seal">
              <button
                type="button"
                className="bk-finish"
                onClick={() => {
                  // A stray tap must not end the exam. Time expiry seals via
                  // handleSubmit({ force: true }) and never reaches this.
                  sealPromptRef.current = true;
                  let ok = false;
                  try { ok = window.confirm('Ready to submit? Once your booklet is sealed, your answers cannot be changed.'); }
                  finally {
                    sealPromptRef.current = false;
                    // A blur or visibility event can arrive just after the
                    // dialog closes: let the 1.5s dedupe window absorb it.
                    lastWarnRef.current = Date.now();
                  }
                  if (ok) handleSubmit();
                }}
                disabled={words < cfg.minWords || !words || submitting || locked}
                aria-describedby={sealHint ? 'bbSealHint' : (sealNote ? 'bbSealNote' : undefined)}
              >{alreadySubmitted ? 'Already submitted' : (submitting || locked ? 'Submitting…' : 'Seal & Submit')}</button>
              {sealHint && <span id="bbSealHint" className="bk-seal-hint">{sealHint}</span>}
              {(submitting || locked) && sealNote && <span id="bbSealNote" className="bk-seal-hint">{sealNote}</span>}
            </div>
          </div>
        </div>

        {/* The cover swings open over the page as the booklet is entered. */}
        <div className="bk-cover bk-cover-open" aria-hidden="true" />
      </div>
    </main>
  );
}

// ─── Submitted Screen ─────────────────────────────────────────────────────────
export function SubmittedScreen({ onNavigate, wordsFinal = 847 }) {
  const sub = (typeof window !== 'undefined' && window.BB_LAST_SUBMISSION) || {};
  const finalWords = sub.words != null ? sub.words : wordsFinal;
  const examTitle  = sub.title || EXAM_META.title;
  // Sample values only when there is no real submission to describe: a real
  // exam with a blank course label must not borrow the sample's course.
  const courseT    = sub.title ? (sub.courseTitle || '') : EXAM_META.courseTitle;
  const candidate  = sub.candidate || bbCandidateLabel(null);
  const transmitted = sub.ok === true;
  const transmitFailed = sub.ok === false;
  const isStudent = bbIsStudent();
  const studentAccount = BB_API.isStudentAccount();
  const compared = sub.withOriginal !== undefined ? sub.withOriginal : BB_API.hasOriginal();
  // Focus the result, so a keyboard or screen-reader user arriving from the
  // seal button (now gone) starts here rather than at the top of the page.
  const headRef = useExRef(null);
  useExEffect(() => { if (headRef.current) headRef.current.focus(); }, []);
  return (
    <main className="bk-stage bb-screen">
      <div className="bk-booklet compact">
        <div className="bk-page">
          <div className="bk-done">
            <div className={'big' + (transmitFailed ? ' failed' : '')}>
              {transmitFailed
                ? <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 8v5"/><path d="M12 17h.01"/><path d="M10.3 3.9L2.4 18a2 2 0 001.7 3h15.8a2 2 0 001.7-3L13.7 3.9a2 2 0 00-3.4 0z"/></svg>
                : <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M20 6L9 17l-5-5"/></svg>}
            </div>

            {transmitFailed ? (
              <React.Fragment>
                <h1 ref={headRef} tabIndex={-1}>{sub.empty ? 'Time is up' : sub.alreadySubmitted ? 'This exam was already submitted' : 'Your exam has not been submitted yet'}</h1>
                {sub.alreadySubmitted ? (
                  <p>
                    Your account already has a submission for this exam, perhaps
                    from another tab or device, so this copy was not sent. Your
                    writing is still saved on this device. If you meant to change
                    your answers, please talk to your teacher.
                  </p>
                ) : sub.empty ? (
                  <p>
                    Nothing was written in this booklet, so there was nothing to
                    submit. If that is not right, please talk to your teacher.
                  </p>
                ) : (
                  <React.Fragment>
                    <p>
                      Your writing is saved on this device, so nothing is lost.
                      Please try again. If it still does not go through, let your
                      teacher know before you close this window.
                    </p>
                    {/* The server's own words, kept for the teacher rather than put in the student's way. */}
                    <details className="state-details">
                      <summary>Details for your teacher</summary>
                      <p className="state err">{sub.error || 'The server could not be reached.'}</p>
                    </details>
                  </React.Fragment>
                )}
              </React.Fragment>
            ) : (
              <React.Fragment>
                <h1 ref={headRef} tabIndex={-1}>Examination Sealed</h1>
                <p>
                  Your examination has been received, sealed, and submitted
                  for your teacher to read.{compared && ' Your writing will be compared with your own past work. Your teacher may choose to add this booklet to your writing profile (the past writing your new work is compared with), and can undo that.'}
                </p>
                {sub.expired && (
                  <p>Time ran out, so your booklet was sealed with everything you had written.</p>
                )}
                {transmitted && (
                  <p className="state ok">✓ Delivered to your teacher</p>
                )}
              </React.Fragment>
            )}

            <div className="gist">
              {[
                { label: 'Exam',         value: examTitle             },
                { label: 'Course',       value: courseT               },
                { label: 'Name',         value: candidate             },
                { label: 'Words',        value: `${finalWords} words` },
              ].filter(({ value }) => value).map(({ label, value }) => (
                <div key={label}>
                  <b>{label}</b>
                  <span>{value}</span>
                </div>
              ))}
            </div>

            <div className="acts">
              {transmitFailed && !sub.empty && !sub.alreadySubmitted && (
                <button type="button" className="go" onClick={() => onNavigate('exam')}>Try again</button>
              )}
              {!isStudent && (
                <button type="button" className="back" onClick={() => onNavigate('dashboard')}>Return to Dashboard</button>
              )}
              {studentAccount && (
                <button type="button" className="back" onClick={() => onNavigate('student-home')}>Back to my exams</button>
              )}
            </div>

            {isStudent && !transmitFailed && (
              <p>
                Your teacher can now read it.
                {!studentAccount && ' You may close this window.'}
              </p>
            )}

            {!transmitFailed && (
              <p className="closed-on">Sealed on {new Date().toLocaleDateString('en-GB', { day:'numeric', month:'long', year:'numeric' })}</p>
            )}
          </div>
        </div>
      </div>
    </main>
  );
}
