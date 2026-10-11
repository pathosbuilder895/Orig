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
  aiDetect:  true,
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
function bbDraftKey(cfg) {
  return 'bb_draft_' + ((cfg && (cfg.id || cfg.title)) || 'exam');
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
    cfg.blockAI   && 'AI assistants and other writing tools are not permitted',
    cfg.blockWeb  && 'The examination runs full-screen; leaving it or switching tabs is recorded for your teacher',
    cfg.blockCopy && 'Copy and paste are disabled in the answer box',
    withOriginal  && 'Session duration and coarse writing information are noted as context for your teacher',
    cfg.phoneBlk  && 'Devices must be silenced for the duration',
    withOriginal && cfg.aiDetect && 'After you submit, your writing is compared with your own past work',
    withOriginal  && 'Your teacher may choose to add your sealed booklet to your writing profile, and can undo that',
  ].filter(Boolean);
}

function fmt(s) {
  return `${String(Math.floor(s / 60)).padStart(2, '0')}:${String(s % 60).padStart(2, '0')}`;
}

function wordCount(text) {
  return text.trim() ? text.trim().split(/\s+/).length : 0;
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
    } catch (e) { return null; }
  }
  try {
    const r = await fetch(`${BB_API_BASE}/bluebook/exams/${encodeURIComponent(cfg.id)}/session`, {
      method: 'POST', headers: bbAuthHeaders(),
      body: JSON.stringify({
        student_id: studentId || '',
        candidate: cfg.candidateEmail || cfg.candidate || '',
      }),
    });
    if (!r.ok) return null;
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
      .catch(err => { if (live) { setLoadError(err.message || 'This examination could not be loaded.'); setLoadState('error'); } });
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
              <h1>Blue Book</h1>
              <p role={loadState === 'error' ? 'alert' : 'status'} className="bk-cover-note state">
                {loadState === 'error' ? loadError : 'Loading your examination…'}
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
            <span className="bk-exam-lbl">Preliminary Instructions</span>
            <h1>Blue Book</h1>
            <div className="bk-rule" />

            <div className="bk-fields">
              <div className="bk-field"><b>Name</b><span className="fill hand">{bbCandidateLabel(cfg)}</span></div>
              {cfg.courseTitle && <div className="bk-field"><b>Course</b><span className="fill">{cfg.courseTitle}</span></div>}
              <div className="bk-field"><b>Exam</b><span className="fill">{cfg.title}</span></div>
              <div className="bk-field"><b>Date</b><span className="fill">{today}</span></div>
            </div>

            <p className="bk-meta">
              <b>{questionCount} question{questionCount === 1 ? '' : 's'} · {cfg.duration / 60} minutes.</b>
              {limits && ` ${limits}`} Your work saves itself as you write. When you open this booklet, the clock starts, and everything you write here is yours, in your own hand.
            </p>
            {cfg.closesAt && (
              <p className="bk-closes">Closes {new Date(cfg.closesAt).toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' })}</p>
            )}

            <div className="bk-conditions">
              <h2>Enforced Conditions</h2>
              <ul>
                {conditions.map(rule => <li key={rule}>{rule}</li>)}
              </ul>
            </div>

            {cannotBegin ? (
              <p role="status" className="bk-cover-note state">
                {cfg.state === 'upcoming' ? 'This examination has not opened yet.' : 'This examination is closed.'}
              </p>
            ) : (
              <button type="button" className="bk-begin" onClick={() => { if (cfg.blockWeb) bbRequestFullscreen(); bbLockOriginalDecision(cfg, withOriginal); onNavigate('exam'); }}>
                {cfg.inProgress ? 'Resume Examination' : 'Begin Examination'}
              </button>
            )}
            <p className="bk-cover-note">Once begun, this examination cannot be paused</p>
            <p className="bk-cover-note">{withOriginal ? 'Original · Bluebook · quiet by design' : 'Bluebook · quiet by design'}</p>
          </div>
        </div>
      </div>
    </div>
  );
}

// ─── Active Examination Screen ────────────────────────────────────────────────
export function ExamScreen({ onNavigate, writingSize = 18, parchmentColor = PARCHMENT_SHADES.warm }) {
  const cfg = getExamConfig();
  const candidateLabel = bbCandidateLabel(cfg);
  // Draft persistence: an exam must survive a crash, reload, or accidental
  // exit. Keyed per exam, restored on mount, cleared on successful seal.
  const draftKey = bbDraftKey(cfg);
  const restored = (() => {
    try { return JSON.parse(localStorage.getItem(draftKey) || 'null'); }
    catch (e) { return null; }
  })();
  // One answer per question. A single-question (or legacy prompt-only) exam
  // is just a list of one, so everything downstream reads `content`, the
  // answers joined, exactly as it read the single answer before.
  const questions = (cfg.questions && cfg.questions.length) ? cfg.questions : [cfg.prompt];
  const multi = questions.length > 1;
  const [answers,     setAnswers]     = useExState(() => {
    const saved = restored && Array.isArray(restored.answers) ? restored.answers
      : [(restored && restored.content) || ''];
    return questions.map((_, i) => saved[i] || '');
  });
  const [qIndex,      setQIndex]      = useExState(0);
  const [promptOpen,  setPromptOpen]  = useExState(true);
  const content = multi
    ? answers.map((a, i) => `Question ${i + 1}.\n${a}`).join('\n\n')
    : answers[0];
  const words = answers.reduce((n, a) => n + wordCount(a), 0);
  // timeLeft is display state DERIVED from the server deadline each tick
  // (see the countdown effect); it is deliberately NOT restored from the
  // draft — persisting a countdown remainder let closing the tab pause the
  // clock. Degrade-open fallback (no session) restarts the local countdown.
  const [timeLeft,    setTimeLeft]    = useExState(cfg.duration);
  const [saving,      setSaving]      = useExState(false);
  const [warnings,    setWarnings]    = useExState(0);
  const [warnLog,     setWarnLog]     = useExState([]); // [{ id, msg }] — persists for the session, never auto-dismissed
  const [warnLogOpen,  setWarnLogOpen] = useExState(true);
  const [submitting,  setSubmitting]  = useExState(false);
  const [fsLost,      setFsLost]      = useExState(false);
  const [liveMsg,     setLiveMsg]     = useExState(''); // polite announcements: autosave + timer milestones
  const textareaRef = useExRef(null);
  const saveTimer   = useExRef(null);
  const deadlineRef = useExRef(null);   // { deadlineMs, offsetMs } once the session lands
  // Seal progress survives refreshes so a retried seal is idempotent
  // end-to-end: same uuid, completed steps never re-run.
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
  // Live refs so interval/debounce callbacks always persist current values.
  const contentRef  = useExRef(content);
  contentRef.current  = content;
  const answersRef  = useExRef(answers);
  answersRef.current  = answers;
  // "Anything written at all" — the joined content always contains the
  // question headers for a multi-question exam, so test the answers.
  const hasWriting = () => answersRef.current.some(a => a.trim());

  function writeDraftNow() {
    try {
      localStorage.setItem(draftKey, JSON.stringify({
        content: contentRef.current,
        answers: answersRef.current,
        seal: sealRef.current,
        warnings: warnEventsRef.current,
        savedAt: Date.now(),
      }));
      return true;
    } catch (e) { return false; }
  }

  // One warning per real event: blur + visibilitychange fire together for a
  // single tab switch, so repeats inside 1.5s collapse into one notice.
  const lastWarnRef = useExRef(0);
  // True only while the seal confirmation is open. The browser may blur the
  // window for its own dialog; that is not the student leaving the exam, so
  // nothing is recorded (or sent to the teacher) while it is up.
  const sealPromptRef = useExRef(false);
  // Every warning also goes to the teacher with the seal: its type and time
  // only, never the message text or anything about the page.
  const warnEventsRef = useExRef((restored && restored.warnings) || []);
  function recordWarning(msg, type = 'other') {
    if (sealPromptRef.current) return;
    const now = Date.now();
    if (now - lastWarnRef.current < 1500) return;
    lastWarnRef.current = now;
    warnEventsRef.current = [...warnEventsRef.current, { type, at: new Date(now).toISOString() }].slice(-500);
    setWarnings(n => n + 1);
    setWarnLog(log => [...log, { id: now, msg }]);
    setWarnLogOpen(true);
  }

  // ── Composition-timing capture (macro-only, ADR-010 — fed to Original's
  // Tier 17 via composition_summary; no per-key counts are kept) ──
  const revsRef     = useExRef([]);    // [{ type:'paste' }]
  const startRef    = useExRef(null);  // performance.now() at first key
  const startWallRef = useExRef(null); // Date.now() wall-clock at first key

  function handleKeyDown(e) {
    if (startRef.current == null) {
      startRef.current = performance.now();
      startWallRef.current = Date.now();
    }
  }

  function buildCompositionSummary() {
    const durSec = startRef.current != null ? (performance.now() - startRef.current) / 1000 : 0;
    return {
      session_seconds: Math.round(durSec),
      word_count:      wordCount(content),
      paste_attempts:  revsRef.current.filter(r => r.type === 'paste').length,
      focus_losses:    warnings,
      started_at:      startWallRef.current != null ? new Date(startWallRef.current).toISOString() : '',
      ended_at:        new Date().toISOString(),
      exam_config: {
        block_copy:   !!cfg.blockCopy,
        min_words:    cfg.minWords,
        duration_min: Math.round(cfg.duration / 60),
      },
    };
  }

  async function handleSubmit(opts = {}) {
    // opts.force: time expiry seals whatever exists, bypassing the word
    // minimum — a student must never be stranded at a dead 00:00.
    if (submitting || (!opts.force && words < cfg.minWords)) return;
    if (opts.force && !hasWriting()) {
      // Nothing written when time ran out — don't record an empty submission.
      // The draft holds only this sitting's Original decision (no writing),
      // so clear it: the next person to sit this exam on this browser must
      // decide afresh, not inherit it. Nothing below reads the draft.
      try { localStorage.removeItem(draftKey); } catch (e) {}
      window.BB_LAST_SUBMISSION = {
        words: 0, title: cfg.title, courseTitle: cfg.courseTitle,
        candidate: candidateLabel, studentId: null,
        ok: false, error: 'No text was written before time expired',
        expired: true,
      };
      onNavigate('submitted');
      return;
    }
    setSubmitting(true);
    // Idempotent, retryable sealing (robustness spec §2): one uuid per seal,
    // persisted in the draft with per-step results, so a refresh-and-reseal
    // or network retry never repeats a completed step.
    const seal = sealRef.current;
    if (!seal.uuid) {
      seal.uuid = (window.crypto && crypto.randomUUID)
        ? crypto.randomUUID()
        : 'uu-' + Date.now() + '-' + Math.random().toString(16).slice(2);
    }
    writeDraftNow();   // draft (content + seal state) survives a failed seal

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
    const BACKOFF = [2000, 5000, 10000];
    for (let attempt = 0; attempt < 3; attempt++) {
      try {
        await waitOnline();
        // 1) Score against the EXISTING baseline (skipped on retry once known).
        if (withOriginal && seal.aiScore === undefined) {
          const scored = await bbScoreWithOriginal(studentId, content, cfg.title, seal.uuid, buildCompositionSummary());
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
        // 2) Record the sealed submission (server dedupes by submission_uuid).
        // Compare-only (plan Phase 7): the seal never adds to the student's
        // baseline; a professor approves which sealed exams become baseline
        // samples. A workspace switched off Original since this sitting began
        // answers the score call with 403 (handled in step 1), so the exam is
        // recorded exactly like a Bluebook-only one.
        const stylometric = null;
        const status = bbSealStatus(withOriginal, seal);
        const timeMin = Math.max(0, Math.round(((cfg.duration || 0) - timeLeft) / 60));
        // Throws on failure, so a lost submission row retries like any other
        // step instead of reporting "sealed" and deleting the draft.
        await BB_API.recordSubmission({
          exam_id:     cfg.id || null,
          student_id:  studentId,
          candidate:   cfg.candidateEmail || cfg.candidate,
          exam_title:  cfg.title,
          course:      cfg.course,
          word_count:  wordCount(content),
          time_min:    timeMin,
          stylometric,
          ai_score:    withOriginal ? seal.aiScore : null,
          status,
          submission_uuid: seal.uuid,
          text:        content,
          answers:     answersRef.current,
          warnings:    warnEventsRef.current,
        });
        result = { ok: true, studentId };
        break;
      } catch (e) {
        lastError = e;
        setLiveMsg(`Sealing attempt ${attempt + 1} failed — retrying.`);
        if (attempt < 2) await new Promise(res => setTimeout(res, BACKOFF[attempt]));
      }
    }

    if (result && result.ok) {
      // Sealed and delivered — the on-device draft has served its purpose.
      try { localStorage.removeItem(draftKey); } catch (e) {}
    } else {
      // Final failure: the draft stays on this device. Never strand the UI.
      setLiveMsg('Sealing failed. Your work is saved on this device — please tell your proctor.');
    }
    window.BB_LAST_SUBMISSION = {
      words: wordCount(content),
      title: cfg.title,
      courseTitle: cfg.courseTitle,
      candidate: candidateLabel,
      studentId: (result && result.studentId) || studentId,
      ok: !!(result && result.ok),
      error: (result && result.ok) ? null : String((lastError && lastError.message) || lastError || 'seal failed'),
      aiScore: seal.aiScore,
      withOriginal,
      expired: !!opts.expired,
      draftKey,
    };
    setSubmitting(false);
    onNavigate('submitted');
  }

  // Server-pinned deadline (robustness spec §1): first call pins it, later
  // calls (any refresh) get the same one back.
  useExEffect(() => {
    let cancelled = false;
    (async () => {
      const sid = await bbResolveStudentId(cfg);
      const sess = await bbStartSession(cfg, sid);
      if (!cancelled && sess) deadlineRef.current = sess;
    })();
    return () => { cancelled = true; };
  }, []);

  // Countdown — derived from the server deadline when we have one, so a
  // reload can't pause the clock; plain local countdown otherwise.
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

  // Offline awareness (robustness spec §3): a persistent, polite banner; the
  // seal retry loop parks on the matching 'online' event.
  useExEffect(() => {
    const goOff = () => { setOffline(true);  setLiveMsg('Connection lost — your writing is safe on this device.'); };
    const goOn  = () => { setOffline(false); setLiveMsg('Connection restored.'); };
    window.addEventListener('offline', goOff);
    window.addEventListener('online', goOn);
    return () => { window.removeEventListener('offline', goOff); window.removeEventListener('online', goOn); };
  }, []);

  // Time expiry: seal whatever is written. Without this the countdown died
  // silently at 00:00 with the seal button still disabled below the word
  // minimum — the student was stranded forever.
  useExEffect(() => {
    if (timeLeft > 0 || !cfg.duration || submitting) return;
    handleSubmit({ force: true, expired: true });
  }, [timeLeft]);

  // Persist a sitting decision taken on this mount at once, so a reload keeps
  // it before the student has written anything. Silent: with no writing
  // there is no "Draft saved" to announce.
  useExEffect(() => {
    if (decidedNowRef.current) writeDraftNow();
  }, []);

  // Autosave: the dot appears only after a REAL write. A 2s typing debounce
  // captures active work; the 30s interval keeps the draft fresh even
  // while idle.
  useExEffect(() => {
    if (!hasWriting()) return;
    const deb = setTimeout(() => {
      if (writeDraftNow()) {
        setSaving(true);
        setLiveMsg('Draft saved.');
        setTimeout(() => setSaving(false), 1800);
      }
    }, 2000);
    return () => clearTimeout(deb);
  }, [content]);
  useExEffect(() => {
    saveTimer.current = setInterval(() => {
      if (hasWriting()) writeDraftNow();
    }, 30000);
    return () => clearInterval(saveTimer.current);
  }, []);

  // Focus monitoring — active when the browser is locked to the exam
  useExEffect(() => {
    if (!cfg.blockWeb) return;
    function onBlur() {
      recordWarning('Focus left the exam window — please return to the exam. Brief interruptions are noted for context, not held against you.', 'focus_lost');
    }
    window.addEventListener('blur', onBlur);
    return () => window.removeEventListener('blur', onBlur);
  }, []);

  // Browser-level lockdown: full-screen + tab-visibility + right-click + unload
  // guard + print/save keys. (A web page can enforce these in-page; a hard
  // "no AI / no web" guarantee still requires a native lockdown browser.)
  useExEffect(() => {
    const off = [];
    const on = (target, type, fn, opts) => { target.addEventListener(type, fn, opts); off.push([target, type, fn, opts]); };
    const warn = recordWarning;
    if (cfg.blockWeb) {
      on(document, 'visibilitychange', () => {
        if (document.hidden) warn('The exam window was hidden — please keep this tab in front until you seal your work.', 'tab_hidden');
      });
      on(document, 'fullscreenchange', () => {
        const fs = bbIsFullscreen();
        setFsLost(!fs);
        if (!fs) warn('You left full-screen — please return to full-screen to continue.', 'fullscreen_exit');
      });
      on(window, 'beforeunload', (e) => { e.preventDefault(); e.returnValue = ''; return ''; });
      on(document, 'keydown', (e) => {
        const k = (e.key || '').toLowerCase();
        if ((e.ctrlKey || e.metaKey) && (k === 'p' || k === 's')) {
          e.preventDefault();
          warn('Printing and saving are disabled during the examination.', 'print_or_save');
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
    const val = e.target.value;
    setAnswers(prev => prev.map((a, i) => (i === qIndex ? val : a)));
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

  // Polite timer milestones — announced once per transition, not every tick.
  const lowAnnouncedRef = useExRef(false);
  const veryLowAnnouncedRef = useExRef(false);
  useExEffect(() => {
    if (isVeryLow && !veryLowAnnouncedRef.current) {
      veryLowAnnouncedRef.current = true;
      setLiveMsg('One minute remaining.');
    } else if (isLow && !lowAnnouncedRef.current) {
      lowAnnouncedRef.current = true;
      setLiveMsg('Five minutes remaining.');
    }
  }, [isLow, isVeryLow]);

  // The paper keeps the design's cream unless a shade other than the old
  // default was picked in the dev-only Tweaks panel.
  const paper = parchmentColor && parchmentColor !== PARCHMENT_SHADES.warm ? parchmentColor : undefined;
  const crsLabel = [cfg.course, cfg.title].filter(Boolean).join(' · ');
  const wantsMin = cfg.minWords > 0;
  const fillPct = wantsMin ? Math.min(100, (words / cfg.minWords) * 100) : 0;

  return (
    <div className="bk-stage">
      <MockupFonts hand />
      {/* Polite live region: autosave + timer milestones, never interrupts */}
      <div role="status" aria-live="polite" className="bk-sr">{liveMsg}</div>

      {/* The Blue Book */}
      <div className="bk-booklet">
        <div className="bk-page" style={paper ? { '--bk-paper': paper } : undefined}>

          {/* ── Bar: course, question tabs, saved, timer ── */}
          <div className="bk-bar">
            <span className="bk-crs">{crsLabel}</span>
            {/* Instructor-preview exit. Hidden for real student launches: one
                stray click must never cost a student their essay. The draft +
                remaining time are persisted, so re-entry restores both. */}
            {!bbIsStudent() && (
              <button type="button" className="bk-exit" onClick={() => {
                writeDraftNow();
                if (confirm('Leave the exam? Your draft and remaining time are saved on this device and will be restored when you re-enter.')) {
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
                    className="bk-qtab">
                    {`Q${i + 1}`}
                    {answers[i].trim() && <><span aria-hidden="true"> ✓</span><span className="bk-sr">, answered</span></>}
                  </button>
                ))}
              </div>
            )}
            <div className="bk-bar-right">
              <span className="bk-cand">{candidateLabel}</span>
              {cfg.blockWeb && fsLost && (
                <button type="button" className="bk-restore" onClick={bbRequestFullscreen}>↺ Restore full-screen</button>
              )}
              <span className={'bk-saved' + (saving ? ' show' : '')} aria-hidden="true">
                <svg viewBox="0 0 24 24"><path d="M20 6L9 17l-5-5"/></svg>saved
              </span>
              <span role="timer" aria-label={'Time remaining ' + fmt(timeLeft)} className={'bk-timer' + (isVeryLow ? ' vlow' : isLow ? ' low' : '')}>
                <svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="13" r="8"/><path d="M12 9v4l2.5 2.5"/><path d="M9 2h6"/></svg>{fmt(timeLeft)}
              </span>
            </div>
          </div>

          {/* Offline banner (robustness spec §3): persistent while disconnected;
              the seal retry loop parks until the matching 'online' event. In
              flow, so it never covers the seal button. */}
          {offline && (
            <div role="status" className="bk-offline">
              Connection lost. Your writing is safe on this device.
              {submitting ? ' Your seal will submit when reconnected.' : ''}
            </div>
          )}

          {/* Examiner's warning notices: recorded proctoring events. Assertive
              and persistent: a candidate must hear every one, and it must not
              vanish before they can review it. In flow under the bar, so the
              timer, question tabs and full-screen button are never covered. */}
          {warnLog.length > 0 && (
            <div role="alert" className="bk-notices">
              <div className="bk-notices-head">
                <span>Recorded Notices ({warnLog.length})</span>
                <button type="button" onClick={() => setWarnLogOpen(o => !o)}>{warnLogOpen ? 'Hide' : 'Show'}</button>
              </div>
              {warnLogOpen && (
                <ul>
                  {warnLog.map(w => <li key={w.id}>{w.msg}</li>)}
                </ul>
              )}
            </div>
          )}

          {/* ── Sheet: the current question and the ruled writing area ── */}
          <div className="bk-sheet">
            <div className="bk-sheet-inner">
              <div className="bk-qhead">
                <div className="bk-qtop">
                  <span className="bk-qn">{multi ? `Question ${qIndex + 1} of ${questions.length}` : 'Examination prompt'}</span>
                  <button type="button" className="bk-qlink" onClick={() => setPromptOpen(o => !o)} aria-expanded={promptOpen}>
                    {promptOpen ? 'Hide question' : 'Show question'}
                  </button>
                </div>
                {promptOpen && <p className="bk-qtext">{questions[qIndex]}</p>}
                {multi && (
                  <div className="bk-qnav">
                    <button type="button" className="bk-qlink" disabled={qIndex === 0} onClick={() => goToQuestion(qIndex - 1)}>← Previous</button>
                    <button type="button" className="bk-qlink" disabled={qIndex === questions.length - 1} onClick={() => goToQuestion(qIndex + 1)}>Next →</button>
                  </div>
                )}
              </div>

              <div className="bk-writing" style={{ '--bk-fs': `${writingSize}px`, '--bk-lh': `${writingSize + 16}px` }}>
                <textarea
                  key={qIndex}
                  ref={textareaRef}
                  value={answers[qIndex]}
                  onChange={handleChange}
                  onKeyDown={handleKeyDown}
                  onPaste={e => {
                    revsRef.current.push({ type: 'paste' });   // record the attempt as a session fact
                    if (cfg.blockCopy) {
                      e.preventDefault();
                      recordWarning('Pasting is disabled. Your work must be composed here.', 'paste_blocked');
                    }
                  }}
                  onCopy={e => { if (cfg.blockCopy) e.preventDefault(); }}
                  onCut={e => { if (cfg.blockCopy) e.preventDefault(); }}
                  spellCheck={!!cfg.spellChk}
                  autoComplete="off"
                  autoCorrect="off"
                  placeholder="Begin writing here…"
                  aria-label={multi ? `Your answer to question ${qIndex + 1}` : 'Your examination answer'}
                  aria-describedby="bbWordCount"
                />
              </div>
            </div>
          </div>

          {/* ── Foot: word count, what is kept, seal ── */}
          <div className="bk-foot">
            <div className="bk-wc">
              {wantsMin && (
                <div className="bk-wc-track"><div className={'bk-wc-fill' + (atMin ? ' met' : '')} style={{ width: `${fillPct}%` }} /></div>
              )}
              <span className={'bk-wc-n' + (overMax ? ' over' : '')}>
                <b id="bbWordCount">{words.toLocaleString()}</b>
                {wantsMin ? ` / ${cfg.minWords.toLocaleString()} words` : ' words'}
                {overMax ? ' · Word limit reached' : ''}
              </span>
            </div>
            <span className="bk-capture">
              <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 3l8 4v6c0 5-3.5 7.5-8 8-4.5-.5-8-3-8-8V7z"/><path d="M9 12l2 2 4-4"/></svg>
              Bluebook saves your words and a few session facts (time, word count, pastes, print or save attempts, leaving the window). Your screen is never watched.
            </span>
            <button
              type="button"
              className="bk-finish"
              onClick={() => {
                // A stray tap must not end the exam. Time expiry seals via
                // handleSubmit({ force: true }) and never reaches this.
                sealPromptRef.current = true;
                let ok = false;
                try { ok = window.confirm('Seal and submit now? You cannot change your answers after sealing.'); }
                finally {
                  sealPromptRef.current = false;
                  // A blur or visibility event can arrive just after the
                  // dialog closes: let the 1.5s dedupe window absorb it.
                  lastWarnRef.current = Date.now();
                }
                if (ok) handleSubmit();
              }}
              disabled={words < cfg.minWords || submitting}
            >{submitting ? 'Sealing…' : 'Seal & Submit'}</button>
          </div>
        </div>

        {/* The cover swings open over the page as the booklet is entered. */}
        <div className="bk-cover bk-cover-open" aria-hidden="true" />
      </div>
    </div>
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
  return (
    <div className="bk-stage bb-screen">
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
                <h1>We could not deliver your examination</h1>
                <p>
                  Your writing is saved on this device, so nothing is lost.
                  Please try again, and if it still fails, tell your instructor
                  before closing this window.
                </p>
                <p className="state err">{sub.error || 'The server could not be reached.'}</p>
              </React.Fragment>
            ) : (
              <React.Fragment>
                <h1>Examination Sealed</h1>
                <p>
                  Your examination has been received, sealed, and submitted
                  for your teacher to read.{compared && ' Your writing will be compared with your own past work. Your teacher may choose to add this to your writing profile, and can undo that.'}
                </p>
                {sub.expired && (
                  <p>Time expired — your work was sealed as written.</p>
                )}
                {transmitted && (
                  <p className="state ok">✓ Delivered to your teacher</p>
                )}
              </React.Fragment>
            )}

            <div className="gist">
              {[
                { label: 'Examination',  value: examTitle             },
                { label: 'Course',       value: courseT               },
                { label: 'Candidate',    value: candidate             },
                { label: 'Word Count',   value: `${finalWords} words` },
              ].filter(({ value }) => value).map(({ label, value }) => (
                <div key={label}>
                  <b>{label}</b>
                  <span>{value}</span>
                </div>
              ))}
            </div>

            <div className="acts">
              {transmitFailed && (
                <button type="button" className="go" onClick={() => onNavigate('exam')}>Try Again</button>
              )}
              {!isStudent && (
                <button type="button" className="back" onClick={() => onNavigate('dashboard')}>Return to Dashboard</button>
              )}
              {studentAccount && !transmitFailed && (
                <button type="button" className="back" onClick={() => onNavigate('student-home')}>Back to my exams</button>
              )}
            </div>

            {isStudent && !transmitFailed && (
              <p>
                Your teacher can now read it and will follow up with you.
                {!studentAccount && ' You may close this window.'}
              </p>
            )}

            <p className="closed-on">Session closed · {new Date().toLocaleDateString('en-GB', { day:'numeric', month:'long', year:'numeric' })}</p>
          </div>
        </div>
      </div>
    </div>
  );
}
