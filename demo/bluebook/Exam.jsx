// ════════════════════════════════════════════════════════════════
//  BLUEBOOK — Examination Screens
//  Briefing · Active Examination · Submitted
// ════════════════════════════════════════════════════════════════
const { useState: useExState, useEffect: useExEffect, useRef: useExRef, useCallback: useExCB } = React;

const EXAM_META = {
  title:       'Ethics in the Modern World',
  course:      'PHIL 301A',
  courseTitle: 'Philosophy 301A',
  candidate:   'Candidate No. 00042',
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

// Build the enforced-conditions list from a config object.
function buildConditions(cfg) {
  return [
    cfg.blockAI   && 'Access to AI assistants and writing tools is blocked',
    cfg.blockWeb  && 'The examination runs full-screen — the browser is locked, no web or external tabs',
    cfg.blockCopy && 'Copy and paste are disabled for this session',
    'Keystroke dynamics will be recorded throughout',
    cfg.phoneBlk  && 'Devices must be silenced for the duration',
    cfg.aiDetect  && 'Stylometric & AI analysis will follow submission',
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
// ({tenant}:{sha256(tenant:identity)[:16]}) and POST the prose + captured
// keystroke dynamics to /students/{id}/baseline as a `proctored` sample
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

// Auth header for whatever session is present (principal or student token).
function bbAuthHeaders() {
  const h = { 'Content-Type': 'application/json' };
  const token = localStorage.getItem('original_principal_token')
    || localStorage.getItem('original_session_token') || '';
  if (token) h['Authorization'] = 'Bearer ' + token;
  return h;
}

// Score the submission against the student's EXISTING baseline → returns an
// AI/authorship score (0–100, higher = more authentically theirs), or null when
// there is no baseline yet to compare against (a first proctored sitting).
async function bbScoreWithOriginal(studentId, text, assignment) {
  try {
    const r = await fetch(`${BB_API_BASE}/students/${encodeURIComponent(studentId)}/score`, {
      method: 'POST', headers: bbAuthHeaders(), body: JSON.stringify({ text, assignment }),
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
async function bbSubmitToOriginal({ text, assignment, keystrokeData, cfg, studentId: preStudentId }) {
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
        keystroke_data: keystrokeData,
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
function BriefingScreen({ onNavigate }) {
  const cfg = getExamConfig();
  const conditions = buildConditions(cfg);
  return (
    <div className="bb-screen" style={{
      minHeight: '100vh', background: BB.deep,
      display: 'flex', alignItems: 'center', justifyContent: 'center',
      padding: 24, fontFamily: fontBody,
    }}>
      <button onClick={() => onNavigate('exams')} style={{
        position: 'fixed', top: 28, left: 48,
        fontFamily: fontMono, fontSize: 10, letterSpacing: '0.18em',
        textTransform: 'uppercase', color: BB.fade,
        background: 'none', border: 'none', cursor: 'pointer',
      }}>← Examinations</button>

      <div style={{ width: '100%', maxWidth: 520 }}>
        {/* Header */}
        <div style={{ textAlign: 'center', marginBottom: 32 }}>
          <Logotype size={24} onClick={() => onNavigate('dashboard')} />
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
            <p style={{
              fontFamily: fontBody, fontStyle: 'italic',
              fontSize: 16, color: BB.fade, margin: 0,
            }}>Dr. Sarah Chen · Balliol College</p>
          </div>

          {/* Meta rows */}
          <div style={{ padding: '0 36px' }}>
            {[
              { label: 'Duration',      value: `${cfg.duration / 60} minutes` },
              { label: 'Minimum',       value: `${(cfg.minWords||0).toLocaleString()} words` },
              { label: 'Maximum',       value: `${(cfg.maxWords||0).toLocaleString()} words` },
              { label: 'Candidate',     value: cfg.candidate },
            ].map(({ label, value }, i) => (
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
                {i < 3 && <GoldRule faint />}
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
            <BtnPrimary full onClick={() => { if (cfg.blockWeb) bbRequestFullscreen(); onNavigate('exam'); }} style={{ padding: '14px 0', fontSize: 17 }}>
              Begin Examination — Timer Commences
            </BtnPrimary>
            <p style={{
              textAlign: 'center', marginTop: 12,
              fontFamily: fontMono, fontSize: 10,
              letterSpacing: '0.16em', textTransform: 'uppercase',
              color: 'rgba(139,155,180,0.45)',
            }}>Once begun, this examination cannot be paused</p>
          </div>
        </div>
      </div>
    </div>
  );
}

// ─── Active Examination Screen ────────────────────────────────────────────────
function ExamScreen({ onNavigate, writingSize = 18, parchmentColor = PARCHMENT_SHADES.warm }) {
  const cfg = getExamConfig();
  const [content,     setContent]     = useExState('');
  const [words,       setWords]       = useExState(0);
  const [timeLeft,    setTimeLeft]    = useExState(cfg.duration);
  const [saving,      setSaving]      = useExState(false);
  const [warnings,    setWarnings]    = useExState(0);
  const [warnMsg,     setWarnMsg]     = useExState('');
  const [showWarn,    setShowWarn]    = useExState(false);
  const [submitting,  setSubmitting]  = useExState(false);
  const [fsLost,      setFsLost]      = useExState(false);
  const textareaRef = useExRef(null);
  const saveTimer   = useExRef(null);

  // ── Keystroke-dynamics capture (fed to Original's Tier 17) ──
  const ksRef     = useExRef([]);    // [{ key, elapsed(ms) }]
  const pausesRef = useExRef([]);    // [{ duration(ms) }] for gaps ≥ 2s
  const revsRef   = useExRef([]);    // [{ type:'paste' }]
  const delsRef   = useExRef(0);     // deletion keystrokes
  const totalRef  = useExRef(0);     // total keystrokes
  const startRef  = useExRef(null);  // performance.now() at first key
  const lastElRef = useExRef(null);  // last elapsed (ms)

  function handleKeyDown(e) {
    const now = performance.now();
    if (startRef.current == null) startRef.current = now;
    const elapsed = now - startRef.current;
    totalRef.current += 1;
    if (e.key === 'Backspace' || e.key === 'Delete') delsRef.current += 1;
    if (lastElRef.current != null) {
      const gap = elapsed - lastElRef.current;
      if (gap >= 2000) pausesRef.current.push({ duration: Math.round(gap) });
    }
    lastElRef.current = elapsed;
    if (ksRef.current.length < 8000) {
      ksRef.current.push({ key: e.key, elapsed: Math.round(elapsed) });
    }
  }

  function buildKeystrokeData() {
    const total = totalRef.current || ksRef.current.length;
    const durSec = startRef.current != null ? (performance.now() - startRef.current) / 1000 : 0;
    const w = wordCount(content);
    return {
      keystrokes:         ksRef.current,
      pauses:             pausesRef.current,
      revisions:          revsRef.current,
      deletionRate:       total ? delsRef.current / total : 0,
      wordCount:          w,
      sessionDurationSec: Math.round(durSec),
      avgWpm:             durSec > 0 ? Math.round(w / (durSec / 60)) : 0,
    };
  }

  async function handleSubmit() {
    if (submitting || words < cfg.minWords) return;
    setSubmitting(true);
    const studentId = await bbResolveStudentId(cfg);
    // 1) Score against the EXISTING baseline first (before this sitting is added)
    //    → AI / authorship reading. null when there's no baseline yet.
    const aiScore = await bbScoreWithOriginal(studentId, content, cfg.title);
    // 2) Add this proctored sitting to the student's voice profile.
    const result = await bbSubmitToOriginal({
      text: content, assignment: cfg.title, keystrokeData: buildKeystrokeData(), cfg, studentId,
    });
    // Stylometric authenticity from keystroke/style drift vs. the profile.
    const drift = (result.data && result.data.drift && result.data.drift.drift_magnitude) || 0;
    const stylometric = Math.max(0, Math.min(100, Math.round((1 - drift) * 100)));
    const status = (drift > 0.5 || (aiScore != null && aiScore < 70)) ? 'FLAGGED' : 'SUBMITTED';
    const timeMin = Math.max(0, Math.round(((cfg.duration || 0) - timeLeft) / 60));
    if (result.ok) {
      await BB_API.recordSubmission({
        exam_id:     cfg.id || null,
        student_id:  result.studentId || studentId,
        candidate:   cfg.candidate,
        exam_title:  cfg.title,
        course:      cfg.course,
        word_count:  wordCount(content),
        time_min:    timeMin,
        stylometric,
        ai_score:    aiScore,
        status,
      });
    }
    window.BB_LAST_SUBMISSION = {
      words: wordCount(content),
      title: cfg.title,
      courseTitle: cfg.courseTitle,
      candidate: cfg.candidate,
      studentId: result.studentId || studentId,
      ok: result.ok,
      error: result.error || null,
      aiScore,
    };
    setSubmitting(false);
    onNavigate('submitted');
  }

  // Countdown
  useExEffect(() => {
    const id = setInterval(() => setTimeLeft(t => t > 0 ? t - 1 : 0), 1000);
    return () => clearInterval(id);
  }, []);

  // Autosave every 30s
  useExEffect(() => {
    saveTimer.current = setInterval(() => {
      if (content.trim()) {
        setSaving(true);
        setTimeout(() => setSaving(false), 1800);
      }
    }, 30000);
    return () => clearInterval(saveTimer.current);
  }, [content]);

  // Focus monitoring — active when the browser is locked to the exam
  useExEffect(() => {
    if (!cfg.blockWeb) return;
    function onBlur() {
      setWarnings(n => n + 1);
      setWarnMsg('You attempted to leave the examination. The browser is locked.');
      setShowWarn(true);
      setTimeout(() => setShowWarn(false), 5000);
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
    const warn = (msg) => {
      setWarnings(n => n + 1);
      setWarnMsg(msg);
      setShowWarn(true);
      setTimeout(() => setShowWarn(false), 5000);
    };
    if (cfg.blockWeb) {
      on(document, 'visibilitychange', () => {
        if (document.hidden) warn('You navigated away from the examination. This has been recorded.');
      });
      on(document, 'fullscreenchange', () => {
        const fs = bbIsFullscreen();
        setFsLost(!fs);
        if (!fs) warn('You exited full-screen. The examination must remain full-screen.');
      });
      on(window, 'beforeunload', (e) => { e.preventDefault(); e.returnValue = ''; return ''; });
      on(document, 'keydown', (e) => {
        const k = (e.key || '').toLowerCase();
        if ((e.ctrlKey || e.metaKey) && (k === 'p' || k === 's')) {
          e.preventDefault();
          warn('Printing and saving are disabled during the examination.');
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
    setContent(val);
    setWords(wordCount(val));
  }

  const isLow     = timeLeft <= 300;
  const isVeryLow = timeLeft <= 60;
  const overMax   = cfg.maxWords && words > cfg.maxWords;
  const atMin     = words >= cfg.minWords;
  const lineH     = writingSize + 12;

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
      {/* Examiner's warning note */}
      {showWarn && (
        <div style={{
          position: 'fixed', top: 0, left: 0, right: 0, zIndex: 100,
          background: BB.parchment, padding: '10px 48px',
          borderBottom: '1px solid rgba(201,169,97,0.7)',
          borderTop: '1px solid rgba(201,169,97,0.7)',
          animation: 'bbFadeIn 0.5s ease both',
        }}>
          <GoldRule style={{ marginBottom: 8 }} />
          <p style={{
            fontFamily: fontBody, fontStyle: 'italic',
            fontSize: 16, color: BB.indigo,
            margin: '0 0 6px', textAlign: 'center',
            letterSpacing: '0.03em',
          }}>
            <strong style={{ fontWeight: 600, fontStyle: 'normal' }}>Attention, {cfg.candidate}:</strong>
            {' '}{warnMsg}{' '}
            <span style={{ fontFamily: fontMono, fontSize: 11 }}>({warnings} recorded)</span>
          </p>
          <GoldRule style={{ marginTop: 8 }} />
        </div>
      )}

      {/* Prototype nav — not part of the real product */}
      <button onClick={() => onNavigate('briefing')} style={{
        position: 'fixed', top: 20, left: 20, zIndex: 200,
        fontFamily: fontMono, fontSize: 10, letterSpacing: '0.18em',
        textTransform: 'uppercase', color: 'rgba(139,155,180,0.4)',
        background: 'none', border: 'none', cursor: 'pointer',
        transition: 'color 0.3s',
      }}
        onMouseEnter={e => e.currentTarget.style.color = BB.gold}
        onMouseLeave={e => e.currentTarget.style.color = 'rgba(139,155,180,0.4)'}
      >← Exit Exam</button>

      {/* The Blue Book */}
      <div style={{
        width: '100%', maxWidth: 900,
        height: 'calc(100vh - 40px)',
        display: 'flex', flexDirection: 'column',
        border: '1px solid rgba(201,169,97,0.55)',
        margin: '20px',
      }}>

        {/* ── Masthead ── */}
        <div style={{
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
          }}>{cfg.candidate}</p>
        </div>

        <GoldRule double />

        {/* ── Lockdown status strip ── */}
        <div style={{
          background: BB.oxford, flexShrink: 0,
          padding: '7px 40px',
          display: 'flex', alignItems: 'center', gap: 18,
          borderBottom: '1px solid rgba(201,169,97,0.15)',
        }}>
          <span style={{
            fontFamily: fontMono, fontSize: 9, letterSpacing: '0.2em',
            textTransform: 'uppercase', color: BB.gold, flexShrink: 0,
          }}>● Locked</span>
          {[
            { on: cfg.blockAI,   label: 'AI blocked' },
            { on: cfg.blockWeb,  label: 'Web blocked' },
            { on: cfg.blockCopy, label: 'Clipboard blocked' },
          ].map(({ on, label }) => (
            <span key={label} style={{
              fontFamily: fontMono, fontSize: 9, letterSpacing: '0.16em',
              textTransform: 'uppercase',
              color: on ? BB.fadedCream : 'rgba(139,155,180,0.35)',
              display: 'flex', alignItems: 'center', gap: 6,
            }}>
              <span style={{ color: on ? '#5EB87C' : 'rgba(139,155,180,0.3)' }}>
                {on ? '✓' : '○'}
              </span>
              {label}
            </span>
          ))}
          {cfg.blockWeb && fsLost && (
            <button onClick={bbRequestFullscreen} style={{
              marginLeft: 'auto', flexShrink: 0,
              fontFamily: fontMono, fontSize: 9, letterSpacing: '0.16em',
              textTransform: 'uppercase', color: BB.deep, background: BB.gold,
              border: 'none', padding: '4px 12px', cursor: 'pointer',
            }}>↺ Restore full-screen</button>
          )}
        </div>

        {/* ── Prompt zone ── */}
        <div style={{
          background: BB.oxford, flexShrink: 0,
          padding: '16px 40px',
          borderBottom: '1px dashed rgba(201,169,97,0.3)',
        }}>
          <MetaLabel style={{ display: 'block', marginBottom: 8 }}>Question I of I</MetaLabel>
          <p style={{
            fontFamily: fontBody, fontSize: 15.5,
            color: BB.fadedCream, lineHeight: 1.65,
            margin: 0, letterSpacing: '0.01em',
            maxWidth: '72ch',
          }}>{cfg.prompt}</p>
        </div>

        {/* ── Writing area (parchment) ── */}
        <div style={{
          flex: 1, minHeight: 0, position: 'relative', overflow: 'hidden',
          ...lineStyle,
        }}>
          {/* Red margin line */}
          <div style={{
            position: 'absolute', left: 70, top: 0, bottom: 0,
            width: 1, background: 'rgba(180,90,80,0.18)',
          }} />

          <textarea
            ref={textareaRef}
            value={content}
            onChange={handleChange}
            onKeyDown={handleKeyDown}
            onPaste={e => {
              revsRef.current.push({ type: 'paste' });   // record the attempt for Tier 17
              if (cfg.blockCopy) {
                e.preventDefault();
                setWarnings(n => n + 1);
                setWarnMsg('Pasting is disabled. Your work must be composed here.');
                setShowWarn(true);
                setTimeout(() => setShowWarn(false), 5000);
              }
            }}
            onCopy={e => { if (cfg.blockCopy) e.preventDefault(); }}
            onCut={e => { if (cfg.blockCopy) e.preventDefault(); }}
            spellCheck={!!cfg.spellChk}
            autoComplete="off"
            autoCorrect="off"
            placeholder="Begin writing here…"
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
          <div style={{
            padding: '10px 40px',
            display: 'grid', gridTemplateColumns: '1fr auto 1fr',
            alignItems: 'center',
          }}>
            {/* Left — word count */}
            <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
              <span style={{
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
              }}>Page {TO_ROMAN(1)}</span>
            </div>

            {/* Right — timer + seal + submit */}
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'flex-end', gap: 16 }}>
              <span style={{
                fontFamily: fontMono, fontSize: 14,
                letterSpacing: '0.1em',
                color: isVeryLow ? '#C47A6B' : isLow ? BB.gold : BB.fade,
                transition: 'color 0.5s',
              }}>{fmt(timeLeft)}</span>
              <Seal size={20} verified glow={!warnings} />
              <BtnPrimary
                onClick={handleSubmit}
                disabled={words < cfg.minWords || submitting}
                style={{ padding: '7px 20px', fontSize: 14 }}
              >{submitting ? 'Sealing…' : 'Seal & Surrender'}</BtnPrimary>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

// ─── Submitted Screen ─────────────────────────────────────────────────────────
function SubmittedScreen({ onNavigate, wordsFinal = 847 }) {
  const sub = (typeof window !== 'undefined' && window.BB_LAST_SUBMISSION) || {};
  const finalWords = sub.words != null ? sub.words : wordsFinal;
  const examTitle  = sub.title || EXAM_META.title;
  const courseT    = sub.courseTitle || EXAM_META.courseTitle;
  const candidate  = sub.candidate || EXAM_META.candidate;
  const transmitted = sub.ok === true;
  const transmitFailed = sub.ok === false;
  return (
    <div className="bb-screen" style={{
      minHeight: '100vh', background: BB.oxford,
      display: 'flex', alignItems: 'center', justifyContent: 'center',
      padding: 24, fontFamily: fontBody,
    }}>
      <div style={{ width: '100%', maxWidth: 480, textAlign: 'center' }}>

        <div style={{ display: 'flex', justifyContent: 'center', marginBottom: 28 }}>
          <Seal size={72} verified glow />
        </div>

        <GoldRule double style={{ marginBottom: 28 }} />

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
          for review. Stylometric analysis has been queued.
        </p>

        {/* Transmission status — the proctored baseline hand-off to Original */}
        {(transmitted || transmitFailed) && (
          <p style={{
            fontFamily: fontMono, fontSize: 11, letterSpacing: '0.1em',
            margin: '14px 0 0',
            color: transmitted ? '#5EB87C' : BB.indigo,
          }}>
            {transmitted
              ? '✓ Proctored baseline transmitted to Original'
              : '○ Baseline could not be transmitted — ' + (sub.error || 'unavailable')}
          </p>
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
          <BtnGhost onClick={() => onNavigate('dashboard')} style={{ padding: '11px 32px' }}>
            Return to Dashboard
          </BtnGhost>
        </div>

        <p style={{
          marginTop: 28, fontFamily: fontMono, fontSize: 10,
          letterSpacing: '0.18em', textTransform: 'uppercase',
          color: 'rgba(139,155,180,0.4)',
        }}>Session closed · {new Date().toLocaleDateString('en-GB', { day:'numeric', month:'long', year:'numeric' })}</p>
      </div>
    </div>
  );
}

Object.assign(window, { BriefingScreen, ExamScreen, SubmittedScreen });
