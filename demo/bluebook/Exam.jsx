import React from 'react';
import { BB, BB_API, BtnGhost, BtnPrimary, GoldRule, Logotype, MetaLabel, Ornament, PARCHMENT_SHADES, STOCK_CANDIDATE, Seal, fontBody, fontDisplay, fontMono } from './components.jsx';

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
    loaded:      true,
    ...extra,
  };
}

// Build the enforced-conditions list from a config object. Each line says
// what this page actually does. A web page cannot block other applications
// or AI tools, so it says what is not permitted and what is recorded,
// never that something is impossible.
function buildConditions(cfg) {
  const withOriginal = BB_API.hasOriginal();
  return [
    cfg.blockAI   && 'AI assistants and other writing tools are not permitted',
    cfg.blockWeb  && 'The examination runs full-screen; leaving it or switching tabs is recorded for your teacher',
    cfg.blockCopy && 'Copy and paste are disabled in the answer box',
    withOriginal  && 'Session duration and coarse writing information are noted as context, not proof of authorship',
    cfg.phoneBlk  && 'Devices must be silenced for the duration',
    withOriginal && cfg.aiDetect && 'After you submit, your writing is compared with your own past work',
  ].filter(Boolean);
}

const TO_ROMAN = n => {
  const vals  = [1000,900,500,400,100,90,50,40,10,9,5,4,1];
  const syms  = ['M','CM','D','CD','C','XC','L','XL','X','IX','V','IV','I'];
  let result  = '';
  vals.forEach((v, i) => { while (n >= v) { result += syms[i]; n -= v; } });
  return result;
};

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
// Bluebook is the proctored baseline-capture layer for Original. On submit we
// derive the same institution-scoped, FERPA-friendly student id Original uses
// ({tenant}:{sha256(tenant:identity)[:16]}) and POST the prose + a macro
// composition_summary (session timing, paste/revision counts — no per-key
// data, ADR-010) to /students/{id}/baseline as a `proctored` sample
// (auth_weight 2.0 — the highest-trust ground truth for the voice profile).
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
// (see original/api.py:bluebook_magic_launch) — without it, a proctored
// baseline write is silently downgraded to 'unverified' (_authorize_provenance).
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

// Score the submission against the student's EXISTING baseline → returns an
// AI/authorship score (0–100, higher = more authentically theirs), or null when
// there is no baseline yet to compare against (a first proctored sitting).
async function bbScoreWithOriginal(studentId, text, assignment, submissionId, compositionSummary) {
  try {
    const r = await fetch(`${BB_API_BASE}/students/${encodeURIComponent(studentId)}/score`, {
      method: 'POST', headers: bbAuthHeaders(),
      body: JSON.stringify({
        text, assignment, submission_id: submissionId || undefined,
        composition_summary: compositionSummary,
      }),
    });
    if (!r.ok) return null;
    const data = await r.json();
    const a = data && data.authorship;
    if (!a) return null;
    // Prefer Born-rule authorship probability; fall back to (1 − deviation).
    const prob = a.authorship_probability != null
      ? a.authorship_probability
      : (a.deviation_score != null ? 1 - a.deviation_score : null);
    if (prob == null) return null;
    return Math.max(0, Math.min(100, Math.round(prob * 100)));
  } catch (e) { return null; }
}

// POST the proctored baseline to Original. Returns { ok, studentId, status, data }.
async function bbSubmitToOriginal({ text, assignment, compositionSummary, cfg, studentId: preStudentId, submissionUuid }) {
  try {
    const studentId = preStudentId || await bbResolveStudentId(cfg);
    const headers = bbAuthHeaders();
    const r = await fetch(`${BB_API_BASE}/students/${encodeURIComponent(studentId)}/baseline`, {
      method: 'POST',
      headers,
      body: JSON.stringify({
        text,
        assignment,
        provenance: 'proctored',
        composition_summary: compositionSummary,
        submission_uuid: submissionUuid || undefined,
      }),
    });
    let data = null;
    try { data = await r.json(); } catch (e) {}
    if (!r.ok) {
      return { ok: false, studentId, status: r.status, error: (data && data.detail) || r.statusText };
    }
    return { ok: true, studentId, status: r.status, data };
  } catch (e) {
    return { ok: false, error: String(e && e.message || e) };
  }
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
  const conditions = buildConditions(cfg);
  const studentAccount = BB_API.isStudentAccount();
  const cannotBegin = cfg.loaded && cfg.state && cfg.state !== 'open';
  if (loadState !== 'ready') {
    return (
      <div className="bb-screen" style={{ minHeight: '100vh', background: BB.deep, display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 24 }}>
        <div style={{ maxWidth: 440, textAlign: 'center' }}>
          <Logotype size={24} />
          <GoldRule double style={{ margin: '16px 0 18px' }} />
          <p role={loadState === 'error' ? 'alert' : 'status'} style={{ fontFamily: fontBody, fontSize: 17, color: BB.fade, lineHeight: 1.6 }}>
            {loadState === 'error' ? loadError : 'Loading your examination…'}
          </p>
        </div>
      </div>
    );
  }
  return (
    <div className="bb-screen" style={{
      minHeight: '100vh', background: BB.deep,
      display: 'flex', alignItems: 'center', justifyContent: 'center',
      padding: 24, fontFamily: fontBody,
    }}>
      {/* A launch-link student has nowhere else to go; an account student
          goes back to their exams; staff previewing go back to the list. */}
      {(!BB_API.isStudentLaunch()) && (
        <button className="bb-brief-back" onClick={() => onNavigate(studentAccount ? 'student-home' : 'exams')} style={{
          position: 'fixed', top: 28, left: 48,
          fontFamily: fontMono, fontSize: 10, letterSpacing: '0.18em',
          textTransform: 'uppercase', color: BB.fade,
          background: 'none', border: 'none', cursor: 'pointer',
        }}>{studentAccount ? '← My exams' : '← Examinations'}</button>
      )}

      <div style={{ width: '100%', maxWidth: 520 }}>
        {/* Header */}
        <div style={{ textAlign: 'center', marginBottom: 32 }}>
          <Logotype size={24} />
          <GoldRule double style={{ margin: '16px 0 12px' }} />
          <MetaLabel>Preliminary Instructions</MetaLabel>
        </div>

        {/* Card */}
        <div style={{
          border: '1px solid rgba(201,169,97,0.35)',
          background: BB.oxford,
        }}>
          {/* Title band */}
          <div style={{ padding: '28px 36px 22px', borderBottom: '1px solid rgba(201,169,97,0.2)' }}>
            <MetaLabel style={{ display: 'block', marginBottom: 10 }}>{cfg.courseTitle}</MetaLabel>
            <h1 style={{
              fontFamily: fontDisplay, fontSize: 26,
              color: BB.cream, fontWeight: 500,
              margin: '0 0 6px', letterSpacing: '0.01em',
            }}>{cfg.title}</h1>
            {cfg.closesAt && (
              <p style={{
                fontFamily: fontBody, fontStyle: 'italic',
                fontSize: 16, color: BB.fade, margin: 0,
              }}>Closes {new Date(cfg.closesAt).toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' })}</p>
            )}
          </div>

          {/* Meta rows */}
          <div style={{ padding: '0 36px' }}>
            {[
              { label: 'Duration',      value: `${cfg.duration / 60} minutes` },
              ...((cfg.questions || []).length > 1 ? [{ label: 'Questions', value: `${cfg.questions.length}, answered separately` }] : []),
              { label: 'Minimum',       value: cfg.minWords ? `${cfg.minWords.toLocaleString()} words` : 'None' },
              { label: 'Maximum',       value: cfg.maxWords ? `${cfg.maxWords.toLocaleString()} words` : 'None' },
              { label: 'Candidate',     value: bbCandidateLabel(cfg) },
            ].map(({ label, value }, i, rows) => (
              <div key={label}>
                <div style={{
                  display: 'flex', justifyContent: 'space-between',
                  alignItems: 'baseline', padding: '13px 0',
                }}>
                  <MetaLabel>{label}</MetaLabel>
                  <span style={{
                    fontFamily: fontBody, fontSize: 16,
                    color: BB.cream, letterSpacing: '0.02em',
                  }}>{value}</span>
                </div>
                {i < rows.length - 1 && <GoldRule faint />}
              </div>
            ))}
          </div>

          {/* Security rules */}
          <div style={{
            margin: '4px 36px 28px',
            border: '1px solid rgba(201,169,97,0.18)',
            padding: '16px 20px',
          }}>
            <MetaLabel style={{ display: 'block', marginBottom: 12 }}>Enforced Conditions</MetaLabel>
            {conditions.map(rule => (
              <div key={rule} style={{
                display: 'flex', alignItems: 'flex-start', gap: 10,
                marginBottom: 8,
              }}>
                <div style={{
                  width: 4, height: 4, borderRadius: '50%',
                  background: BB.gold, flexShrink: 0, marginTop: 8,
                }} />
                <span style={{
                  fontFamily: fontBody, fontSize: 15,
                  color: BB.fade, lineHeight: 1.55,
                }}>{rule}</span>
              </div>
            ))}
          </div>

          {/* CTA */}
          <div style={{ padding: '0 36px 32px' }}>
            <GoldRule style={{ marginBottom: 24 }} />
            {cannotBegin ? (
              <p role="status" style={{ textAlign: 'center', fontFamily: fontBody, fontSize: 17, color: BB.fade, margin: 0 }}>
                {cfg.state === 'upcoming' ? 'This examination has not opened yet.' : 'This examination is closed.'}
              </p>
            ) : (
              <BtnPrimary full onClick={() => { if (cfg.blockWeb) bbRequestFullscreen(); onNavigate('exam'); }} style={{ padding: '14px 0', fontSize: 17 }}>
                Begin Examination — Timer Commences
              </BtnPrimary>
            )}
            <p style={{
              textAlign: 'center', marginTop: 12,
              fontFamily: fontMono, fontSize: 13,
              letterSpacing: '0.12em', textTransform: 'uppercase',
              color: BB.fadedCream,
            }}>Once begun, this examination cannot be paused</p>
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
  const draftKey = 'bb_draft_' + (cfg.id || cfg.title || 'exam');
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
  // Every warning also goes to the teacher with the seal: its type and time
  // only, never the message text or anything about the page.
  const warnEventsRef = useExRef((restored && restored.warnings) || []);
  function recordWarning(msg, type = 'other') {
    const now = Date.now();
    if (now - lastWarnRef.current < 1500) return;
    lastWarnRef.current = now;
    warnEventsRef.current = [...warnEventsRef.current, { type, at: new Date(now).toISOString() }].slice(-500);
    setWarnings(n => n + 1);
    setWarnLog(log => [...log, { id: now, msg }]);
    setWarnLogOpen(true);
  }

  // ── Composition-timing capture (macro-only, ADR-010 — fed to Original's
  // Tier 17 via composition_summary; no per-key array is built client-side) ──
  const revsRef     = useExRef([]);    // [{ type:'paste' }]
  const delsRef     = useExRef(0);     // deletion keystrokes
  const startRef    = useExRef(null);  // performance.now() at first key
  const startWallRef = useExRef(null); // Date.now() wall-clock at first key

  function handleKeyDown(e) {
    if (startRef.current == null) {
      startRef.current = performance.now();
      startWallRef.current = Date.now();
    }
    if (e.key === 'Backspace' || e.key === 'Delete') delsRef.current += 1;
  }

  function buildCompositionSummary() {
    const durSec = startRef.current != null ? (performance.now() - startRef.current) / 1000 : 0;
    return {
      session_seconds: Math.round(durSec),
      word_count:      wordCount(content),
      paste_attempts:  revsRef.current.filter(r => r.type === 'paste').length,
      focus_losses:    warnings,
      revision_count:  delsRef.current,
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
      // Nothing written when time ran out — don't post an empty baseline.
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
    // routes for it anyway, and its students are not profiled.
    const withOriginal = BB_API.hasOriginal();
    let result = null;
    let lastError = null;
    const BACKOFF = [2000, 5000, 10000];
    for (let attempt = 0; attempt < 3; attempt++) {
      try {
        await waitOnline();
        // 1) Score against the EXISTING baseline (skipped on retry once known).
        if (withOriginal && seal.aiScore === undefined) {
          seal.aiScore = await bbScoreWithOriginal(studentId, content, cfg.title, seal.uuid, buildCompositionSummary());
          writeDraftNow();
        }
        // 2) Add this proctored sitting (server skips identical text on replay).
        if (withOriginal && !seal.baselineData) {
          const r = await bbSubmitToOriginal({
            text: content, assignment: cfg.title,
            compositionSummary: buildCompositionSummary(), cfg, studentId,
            submissionUuid: seal.uuid,
          });
          if (!r.ok) throw new Error(r.error || 'baseline write failed');
          seal.baselineData = r;
          writeDraftNow();
        }
        // 3) Record the sealed submission (server dedupes by submission_uuid).
        const baseline = seal.baselineData || {};
        const drift = (baseline.data && baseline.data.drift
          && baseline.data.drift.drift_magnitude) || 0;
        const stylometric = withOriginal ? Math.max(0, Math.min(100, Math.round((1 - drift) * 100))) : null;
        const status = withOriginal && (drift > 0.5 || (seal.aiScore != null && seal.aiScore < 70))
          ? 'FLAGGED' : 'SUBMITTED';
        const timeMin = Math.max(0, Math.round(((cfg.duration || 0) - timeLeft) / 60));
        // Throws on failure, so a lost submission row retries like any other
        // step instead of reporting "sealed" and deleting the draft.
        await BB_API.recordSubmission({
          exam_id:     cfg.id || null,
          student_id:  baseline.studentId || studentId,
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
        result = { ok: true, studentId: baseline.studentId || studentId };
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
  const lineH     = writingSize + 12;

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

  const lineStyle = {
    background: parchmentColor,
    backgroundImage: `repeating-linear-gradient(
      ${parchmentColor} 0px,
      ${parchmentColor} ${lineH - 1}px,
      rgba(196,152,80,0.18) ${lineH - 1}px,
      rgba(196,152,80,0.18) ${lineH}px
    )`,
  };

  return (
    <div style={{
      height: '100vh', background: BB.deep,
      display: 'flex', alignItems: 'center', justifyContent: 'center',
      overflow: 'hidden',
    }}>
      {/* Polite live region: autosave + timer milestones — never interrupts */}
      <div role="status" aria-live="polite" style={{
        position: 'absolute', width: 1, height: 1, padding: 0, margin: -1,
        overflow: 'hidden', clip: 'rect(0,0,0,0)', whiteSpace: 'nowrap', border: 0,
      }}>{liveMsg}</div>

      {/* Offline banner (robustness spec §3) — persistent while disconnected;
          the seal retry loop parks until the matching 'online' event. */}
      {offline && (
        <div role="status" style={{
          position: 'fixed', bottom: 0, left: 0, right: 0, zIndex: 100,
          background: BB.parchment, borderTop: '1px solid rgba(201,169,97,0.7)',
          padding: '8px 48px', fontFamily: fontMono, fontSize: 12,
          letterSpacing: '0.08em', color: BB.indigo,
        }}>
          Connection lost — your writing is safe on this device.
          {submitting ? ' Your seal will submit when reconnected.' : ''}
        </div>
      )}

      {/* Examiner's warning notices — recorded proctoring events. Assertive
          and persistent: a candidate must hear every one, and it must not
          vanish before they can review it. */}
      {warnLog.length > 0 && (
        <div role="alert" style={{
          position: 'fixed', top: 0, left: 0, right: 0, zIndex: 100,
          background: BB.parchment,
          borderBottom: '1px solid rgba(201,169,97,0.7)',
          borderTop: '1px solid rgba(201,169,97,0.7)',
          animation: 'bbFadeIn 0.5s ease both',
        }}>
          <GoldRule style={{ marginBottom: 8 }} />
          <div style={{ padding: '0 48px 10px', display: 'flex', alignItems: 'baseline', justifyContent: 'space-between' }}>
            <MetaLabel style={{ color: BB.indigo }}>Recorded Notices ({warnLog.length})</MetaLabel>
            <button
              onClick={() => setWarnLogOpen(o => !o)}
              style={{
                fontFamily: fontMono, fontSize: 11, letterSpacing: '0.1em',
                textTransform: 'uppercase', color: BB.indigo,
                background: 'none', border: 'none', cursor: 'pointer',
              }}
            >{warnLogOpen ? 'Hide' : 'Show'}</button>
          </div>
          {warnLogOpen && (
            <ul style={{
              listStyle: 'none', margin: 0, padding: '0 48px 10px',
              maxHeight: 140, overflowY: 'auto',
            }}>
              {warnLog.map(w => (
                <li key={w.id} style={{
                  fontFamily: fontBody, fontStyle: 'italic',
                  fontSize: 16, color: BB.indigo,
                  margin: '0 0 6px', textAlign: 'center',
                  letterSpacing: '0.03em',
                }}>{w.msg}</li>
              ))}
            </ul>
          )}
          <GoldRule style={{ marginTop: 8 }} />
        </div>
      )}

      {/* Instructor-preview nav. Hidden for real student launches — one
          stray click must never cost a student their essay. The draft +
          remaining time are persisted, so re-entry restores both. */}
      {!bbIsStudent() && (
        <button onClick={() => {
          writeDraftNow();
          if (confirm('Leave the exam? Your draft and remaining time are saved on this device and will be restored when you re-enter.')) {
            onNavigate('briefing');
          }
        }} style={{
          position: 'fixed', top: 20, left: 20, zIndex: 200,
          fontFamily: fontMono, fontSize: 12.5, letterSpacing: '0.14em',
          textTransform: 'uppercase', color: 'rgba(139,155,180,0.55)',
          background: 'none', border: 'none', cursor: 'pointer',
          transition: 'color 0.3s',
        }}
          onMouseEnter={e => e.currentTarget.style.color = BB.gold}
          onMouseLeave={e => e.currentTarget.style.color = 'rgba(139,155,180,0.55)'}
        >← Exit Exam</button>
      )}

      {/* The Blue Book */}
      <div className="bb-exam-book" style={{
        width: '100%', maxWidth: 900,
        height: 'calc(100vh - 40px)',
        display: 'flex', flexDirection: 'column',
        border: '1px solid rgba(201,169,97,0.55)',
        margin: '20px',
      }}>

        {/* ── Masthead ── */}
        <div className="bb-exam-mast" style={{
          background: BB.oxford, flexShrink: 0,
          padding: '14px 40px',
          display: 'grid', gridTemplateColumns: '1fr auto 1fr',
          alignItems: 'center', gap: 16,
        }}>
          <Logotype size={18} />
          <div style={{ textAlign: 'center' }}>
            <p style={{
              fontFamily: fontBody, fontVariant: 'small-caps',
              fontSize: 14, letterSpacing: '0.2em',
              color: BB.cream, margin: 0,
            }}>{cfg.courseTitle}: {cfg.title}</p>
          </div>
          <p style={{
            fontFamily: fontMono, fontSize: 10,
            letterSpacing: '0.18em', textTransform: 'uppercase',
            color: BB.fade, textAlign: 'right', margin: 0,
          }}>{candidateLabel}</p>
        </div>

        <GoldRule double />

        {/* ── Lockdown status strip ── */}
        <div className="bb-exam-strip" style={{
          background: BB.oxford, flexShrink: 0,
          padding: '7px 40px',
          display: 'flex', alignItems: 'center', gap: 18,
          borderBottom: '1px solid rgba(201,169,97,0.15)',
        }}>
          <span style={{
            fontFamily: fontMono, fontSize: 12, letterSpacing: '0.16em',
            textTransform: 'uppercase', color: BB.gold, flexShrink: 0,
          }}>● Exam mode</span>
          {/* What this page actually does, not what it cannot do: it cannot
              block other apps or AI tools, only record leaving the window. */}
          {[
            { on: cfg.blockAI,   label: 'No AI tools' },
            { on: cfg.blockWeb,  label: 'Full-screen, leaving is recorded' },
            { on: cfg.blockCopy, label: 'Copy & paste off' },
          ].map(({ on, label }) => (
            <span key={label} style={{
              fontFamily: fontMono, fontSize: 12, letterSpacing: '0.12em',
              textTransform: 'uppercase',
              color: on ? BB.fadedCream : 'rgba(139,155,180,0.5)',
              display: 'flex', alignItems: 'center', gap: 6,
            }}>
              <span style={{ color: on ? '#5EB87C' : 'rgba(139,155,180,0.45)' }}>
                {on ? '✓' : '○'}
              </span>
              {label}
            </span>
          ))}
          {cfg.blockWeb && fsLost && (
            <button onClick={bbRequestFullscreen} style={{
              marginLeft: 'auto', flexShrink: 0,
              fontFamily: fontMono, fontSize: 13, letterSpacing: '0.12em',
              textTransform: 'uppercase', color: BB.deep, background: BB.gold,
              border: 'none', padding: '11px 20px', cursor: 'pointer',
              minHeight: 40,
            }}>↺ Restore full-screen</button>
          )}
        </div>

        {/* ── Prompt zone: the current question, with navigation ── */}
        <div className="bb-exam-prompt" style={{
          background: BB.oxford, flexShrink: 0,
          padding: '14px 40px',
          borderBottom: '1px dashed rgba(201,169,97,0.3)',
        }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 12, flexWrap: 'wrap' }}>
            <MetaLabel>{multi ? `Question ${qIndex + 1} of ${questions.length}` : 'Examination prompt'}</MetaLabel>
            <div style={{ display: 'flex', alignItems: 'center', gap: 6, flexWrap: 'wrap' }}>
              {multi && questions.map((_, i) => (
                <button key={i} type="button" onClick={() => goToQuestion(i)}
                  aria-label={`Question ${i + 1}${answers[i].trim() ? ', answered' : ''}`}
                  aria-current={i === qIndex ? 'step' : undefined}
                  className="bb-qdot"
                  style={{
                    minWidth: 36, minHeight: 36, borderRadius: 18, cursor: 'pointer',
                    fontFamily: fontMono, fontSize: 12,
                    border: `1px solid ${i === qIndex ? BB.gold : 'rgba(201,169,97,0.35)'}`,
                    background: i === qIndex ? 'rgba(201,169,97,0.18)' : 'transparent',
                    color: answers[i].trim() ? BB.cream : BB.fade,
                  }}>{answers[i].trim() ? '✓' : i + 1}</button>
              ))}
              <button type="button" onClick={() => setPromptOpen(o => !o)} aria-expanded={promptOpen}
                style={{ fontFamily: fontMono, fontSize: 11, letterSpacing: '0.12em', textTransform: 'uppercase',
                  color: BB.gold, background: 'none', border: 'none', cursor: 'pointer', minHeight: 36, padding: '0 6px' }}>
                {promptOpen ? 'Hide question' : 'Show question'}
              </button>
            </div>
          </div>
          {promptOpen && (
            <p style={{
              fontFamily: fontBody, fontSize: 15.5,
              color: BB.fadedCream, lineHeight: 1.65,
              margin: '8px 0 0', letterSpacing: '0.01em',
              maxWidth: '72ch', whiteSpace: 'pre-wrap',
              maxHeight: '30vh', overflowY: 'auto',
            }}>{questions[qIndex]}</p>
          )}
          {multi && (
            <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: 8 }}>
              <button type="button" disabled={qIndex === 0} onClick={() => goToQuestion(qIndex - 1)}
                style={{ fontFamily: fontMono, fontSize: 11, color: qIndex === 0 ? BB.fade : BB.gold, background: 'none', border: 'none', cursor: qIndex === 0 ? 'default' : 'pointer', minHeight: 36 }}>← Previous</button>
              <button type="button" disabled={qIndex === questions.length - 1} onClick={() => goToQuestion(qIndex + 1)}
                style={{ fontFamily: fontMono, fontSize: 11, color: qIndex === questions.length - 1 ? BB.fade : BB.gold, background: 'none', border: 'none', cursor: qIndex === questions.length - 1 ? 'default' : 'pointer', minHeight: 36 }}>Next →</button>
            </div>
          )}
        </div>

        {/* ── Writing area (parchment) ── */}
        <div className="bb-exam-paper" style={{
          flex: 1, minHeight: 0, position: 'relative', overflow: 'hidden',
          ...lineStyle,
        }}>
          {/* Red margin line */}
          <div className="bb-exam-margin" style={{
            position: 'absolute', left: 70, top: 0, bottom: 0,
            width: 1, background: 'rgba(180,90,80,0.18)',
          }} />

          <textarea
            key={qIndex}
            className="bb-exam-textarea"
            ref={textareaRef}
            value={answers[qIndex]}
            onChange={handleChange}
            onKeyDown={handleKeyDown}
            onPaste={e => {
              revsRef.current.push({ type: 'paste' });   // record the attempt for Tier 17
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
            style={{
              position: 'absolute', inset: 0,
              width: '100%', height: '100%',
              background: 'transparent',
              border: 'none', outline: 'none', resize: 'none',
              padding: `${lineH - writingSize + 1}px 60px 60px 88px`,
              fontFamily: fontBody,
              fontSize: writingSize,
              lineHeight: `${lineH}px`,
              color: BB.ink,
              letterSpacing: '0.01em',
              overflowY: 'auto',
            }}
          />

          {/* Word limit badge */}
          {overMax && (
            <div style={{
              position: 'absolute', bottom: 14, right: 20,
              fontFamily: fontMono, fontSize: 10, letterSpacing: '0.15em',
              textTransform: 'uppercase', color: '#C47A6B',
              border: '1px solid rgba(196,122,107,0.3)',
              padding: '3px 10px', background: BB.parchment,
            }}>Word limit reached</div>
          )}
        </div>

        {/* ── Footer ── */}
        <div style={{ background: BB.oxford, flexShrink: 0 }}>
          <GoldRule />
          <div className="bb-exam-foot" style={{
            padding: '10px 40px',
            display: 'grid', gridTemplateColumns: '1fr auto 1fr',
            alignItems: 'center',
          }}>
            {/* Left — word count */}
            <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
              <span id="bbWordCount" style={{
                fontFamily: fontMono, fontSize: 12,
                letterSpacing: '0.12em',
                color: overMax ? '#C47A6B' : atMin ? BB.gold : BB.fade,
                transition: 'color 0.5s',
              }}>
                {words.toLocaleString()}
              </span>
              <MetaLabel>words</MetaLabel>
              {/* Autosave dot */}
              {saving && (
                <div style={{
                  width: 6, height: 6, borderRadius: '50%',
                  background: BB.gold,
                  animation: 'bbSaveDot 1.8s ease both',
                }} />
              )}
            </div>

            {/* Center — page */}
            <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 2 }}>
              <span style={{
                fontFamily: fontDisplay, fontStyle: 'italic',
                fontSize: 14, color: BB.fadedCream,
                letterSpacing: '0.08em',
              }}>{multi ? `Question ${TO_ROMAN(qIndex + 1)}` : `Page ${TO_ROMAN(1)}`}</span>
            </div>

            {/* Right — timer + seal + submit */}
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'flex-end', gap: 16 }}>
              <span role="timer" aria-label={'Time remaining ' + fmt(timeLeft)} style={{
                fontFamily: fontMono, fontSize: 14,
                letterSpacing: '0.1em',
                color: isVeryLow ? '#C47A6B' : isLow ? BB.gold : BB.fade,
                transition: 'color 0.5s',
              }}>{fmt(timeLeft)}</span>
              <Seal size={20} verified glow />
              {cfg.minWords > 0 && !atMin && !submitting && (
                <span style={{
                  fontFamily: fontMono, fontSize: 12.5,
                  letterSpacing: '0.06em', color: BB.fade,
                }}>{words.toLocaleString()} of {cfg.minWords.toLocaleString()} minimum words</span>
              )}
              <BtnPrimary
                onClick={handleSubmit}
                disabled={words < cfg.minWords || submitting}
                style={{ padding: '7px 20px', fontSize: 14 }}
              >{submitting ? 'Sealing…' : 'Seal & Submit'}</BtnPrimary>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

// ─── Submitted Screen ─────────────────────────────────────────────────────────
export function SubmittedScreen({ onNavigate, wordsFinal = 847 }) {
  const sub = (typeof window !== 'undefined' && window.BB_LAST_SUBMISSION) || {};
  const finalWords = sub.words != null ? sub.words : wordsFinal;
  const examTitle  = sub.title || EXAM_META.title;
  const courseT    = sub.courseTitle || EXAM_META.courseTitle;
  const candidate  = sub.candidate || bbCandidateLabel(null);
  const transmitted = sub.ok === true;
  const transmitFailed = sub.ok === false;
  const isStudent = bbIsStudent();
  const studentAccount = BB_API.isStudentAccount();
  const compared = sub.withOriginal !== undefined ? sub.withOriginal : BB_API.hasOriginal();
  return (
    <div className="bb-screen" style={{
      minHeight: '100vh', background: BB.oxford,
      display: 'flex', alignItems: 'center', justifyContent: 'center',
      padding: 24, fontFamily: fontBody,
    }}>
      <div style={{ width: '100%', maxWidth: 480, textAlign: 'center' }}>

        <div style={{ display: 'flex', justifyContent: 'center', marginBottom: 28 }}>
          <Seal size={72} verified={!transmitFailed} glow={!transmitFailed} />
        </div>

        <GoldRule double style={{ marginBottom: 28 }} />

        {transmitFailed ? (
          <React.Fragment>
            <h1 style={{
              fontFamily: fontDisplay, fontSize: 34,
              fontWeight: 400, color: BB.cream,
              letterSpacing: '0.02em', margin: '0 0 16px',
            }}>We could not deliver your examination</h1>
            <p style={{
              fontFamily: fontBody, fontSize: 17,
              color: BB.fade, lineHeight: 1.65,
              margin: '0 0 10px', letterSpacing: '0.02em',
            }}>
              Your writing is saved on this device — nothing is lost.
              Please try again, and if it still fails, tell your instructor
              before closing this window.
            </p>
            <p style={{
              fontFamily: fontMono, fontSize: 12.5, letterSpacing: '0.08em',
              margin: '14px 0 0', color: BB.indigo,
            }}>{sub.error || 'The server could not be reached.'}</p>
          </React.Fragment>
        ) : (
          <React.Fragment>
            <h1 style={{
              fontFamily: fontDisplay, fontSize: 36,
              fontWeight: 400, color: BB.cream,
              letterSpacing: '0.02em', margin: '0 0 16px',
            }}>Examination Sealed</h1>
            <p style={{
              fontFamily: fontBody, fontSize: 17,
              color: BB.fade, lineHeight: 1.65,
              margin: '0 0 10px', letterSpacing: '0.02em',
            }}>
              Your examination has been received, sealed, and submitted
              for review.{compared && ' Your writing will be compared with your own past work to confirm it as yours.'}
            </p>
            {sub.expired && (
              <p style={{
                fontFamily: fontBody, fontStyle: 'italic', fontSize: 15,
                color: BB.fadedCream, margin: '6px 0 0',
              }}>Time expired — your work was sealed as written.</p>
            )}
            {transmitted && (
              <p style={{
                fontFamily: fontMono, fontSize: 12.5, letterSpacing: '0.08em',
                margin: '14px 0 0', color: '#5EB87C',
              }}>✓ Delivered to your teacher</p>
            )}
          </React.Fragment>
        )}

        <Ornament py={24} />

        <div style={{
          border: '1px solid rgba(201,169,97,0.22)',
          padding: '20px 32px', marginBottom: 32,
        }}>
          {[
            { label: 'Examination',  value: examTitle             },
            { label: 'Course',       value: courseT               },
            { label: 'Candidate',    value: candidate             },
            { label: 'Word Count',   value: `${finalWords} words` },
          ].map(({ label, value }, i) => (
            <div key={label}>
              <div style={{
                display: 'flex', justifyContent: 'space-between',
                alignItems: 'baseline', padding: '11px 0',
              }}>
                <MetaLabel>{label}</MetaLabel>
                <span style={{ fontFamily: fontBody, fontSize: 16, color: BB.cream }}>
                  {value}
                </span>
              </div>
              {i < 3 && <GoldRule faint />}
            </div>
          ))}
        </div>

        <div style={{ display: 'flex', gap: 12, justifyContent: 'center' }}>
          {transmitFailed && (
            <BtnPrimary onClick={() => onNavigate('exam')} style={{ padding: '11px 32px' }}>
              Try Again
            </BtnPrimary>
          )}
          {!isStudent && (
            <BtnGhost onClick={() => onNavigate('dashboard')} style={{ padding: '11px 32px' }}>
              Return to Dashboard
            </BtnGhost>
          )}
          {studentAccount && !transmitFailed && (
            <BtnGhost onClick={() => onNavigate('student-home')} style={{ padding: '11px 32px' }}>
              Back to my exams
            </BtnGhost>
          )}
        </div>

        {isStudent && !transmitFailed && (
          <p style={{
            marginTop: 20, fontFamily: fontBody, fontSize: 15,
            color: BB.fade, lineHeight: 1.6,
          }}>
            Your teacher reviews the results and will follow up with you.
            {!studentAccount && ' You may close this window.'}
          </p>
        )}

        <p style={{
          marginTop: 28, fontFamily: fontMono, fontSize: 10,
          letterSpacing: '0.18em', textTransform: 'uppercase',
          color: 'rgba(139,155,180,0.4)',
        }}>Session closed · {new Date().toLocaleDateString('en-GB', { day:'numeric', month:'long', year:'numeric' })}</p>
      </div>
    </div>
  );
}
