import React from 'react';

// ════════════════════════════════════════════════════════════════
//  BLUEBOOK — Design System Components
//  Oxford Blue · Antique Gold · Parchment · EB Garamond
// ════════════════════════════════════════════════════════════════

// Keydown handler for div-as-button rows: Enter/Space activates like a
// click (WS-4). Shared across every screen that renders a click-only row.
export function rowKeyDown(fn) {
  return (e) => {
    if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); fn(); }
  };
}

// Faces the navy-design screens use beyond fonts.css: IBM Plex Mono 700 and the
// Caveat hand. The Original suite self-hosts both (OFL licences sit beside the
// files in demo/original/fonts). A face whose file is missing just falls back
// to the next family, so it can never block a screen, and nothing is requested
// from a third party. Rendered only by the live screens that use them.
const LATIN = 'U+0000-00FF,U+0131,U+0152-0153,U+02BB-02BC,U+02C6,U+02DA,U+02DC,U+0304,U+0308,U+0329,U+2000-206F,U+20AC,U+2122,U+2191,U+2193,U+2212,U+2215,U+FEFF,U+FFFD';
const LATIN_EXT = 'U+0100-02BA,U+02BD-02C5,U+02C7-02CC,U+02CE-02D7,U+02DD-02FF,U+0304,U+0308,U+0329,U+1D00-1DBF,U+1E00-1E9F,U+1EF2-1EFF,U+2020,U+20A0-20AB,U+20AD-20C0,U+2113,U+2C60-2C7F,U+A720-A7FF';
const face = (family, weight, file, range) => `@font-face{font-family:'${family}';font-style:normal;font-display:swap;font-weight:${weight};src:url(/original/fonts/${file}.woff2) format('woff2');unicode-range:${range}}`;
const MOCKUP_MONO_CSS = face('IBM Plex Mono', 700, 'ibm-plex-mono-latin-ext-700-normal', LATIN_EXT) + face('IBM Plex Mono', 700, 'ibm-plex-mono-latin-700-normal', LATIN);
const MOCKUP_HAND_CSS = face('Caveat', 500, 'caveat-latin-ext-500-normal', LATIN_EXT) + face('Caveat', 500, 'caveat-latin-500-normal', LATIN);
export function MockupFonts({ hand = false }) {
  return <style>{MOCKUP_MONO_CSS + (hand ? MOCKUP_HAND_CSS : '')}</style>;
}

export const BB = {
  oxford:      '#002147',
  deep:        '#001020',
  oxfordLight: '#0A2D5E',
  gold:        '#C9A961',
  goldDark:    '#B8860B',
  parchment:   '#F4EFE6',
  parchmentDk: '#EDE5D8',
  ink:         '#1A1A1A',
  inkMid:      '#2C2C2C',
  indigo:      '#3B4A6B',
  fade:        '#8B9BB4',
  cream:       '#F0EDE4',
  fadedCream:  '#B8B4AC',
};

export const fontDisplay = "'Cormorant Garamond', serif";
export const fontBody    = "'EB Garamond', serif";
export const fontMono    = "'IBM Plex Mono', monospace";

export const PARCHMENT_SHADES = {
  warm:  '#F4EFE6',
  ivory: '#F8F5EE',
  cool:  '#EEF2EC',
};

// The demo's stock candidate label. Shared because Exam.jsx's
// bbCandidateLabel() recognises it as "nothing real is bound here" — if
// Dashboard.jsx were to carry its own copy and the two drifted, a bound
// student who stepped back through the Examinations list would be handed a
// literal bbCandidateLabel() reads as somebody's actual name.
export const STOCK_CANDIDATE = 'Candidate No. 00042';

// ─── Logotype ────────────────────────────────────────────────────────────────
export function Logotype({ size = 22, onClick, light = false }) {
  const Tag = onClick ? 'button' : 'span';
  const interactiveProps = onClick ? {
    onClick,
    type: 'button',
    'aria-label': 'Collections home',
  } : {};
  return (
    <Tag
      {...interactiveProps}
      style={{
        fontFamily: fontDisplay,
        fontSize: size,
        color: BB.gold,
        fontWeight: 600,
        letterSpacing: '0.06em',
        cursor: onClick ? 'pointer' : 'default',
        userSelect: 'none',
        whiteSpace: 'nowrap',
        background: 'none',
        border: 'none',
        padding: 0,
      }}
    >
      C<span style={{
        fontVariant: 'small-caps',
        letterSpacing: '0.15em',
        fontSize: size * 0.88,
        color: light ? BB.fadedCream : BB.gold,
      }}>ollections</span>
    </Tag>
  );
}

// ─── Wax Seal SVG ────────────────────────────────────────────────────────────
export function Seal({ size = 22, verified = true, glow = false }) {
  const a = verified ? 1 : 0.3;
  const ticks = [0, 45, 90, 135, 180, 225, 270, 315];
  return (
    <svg
      width={size} height={size} viewBox="0 0 32 32"
      style={{ display: 'block', flexShrink: 0 }}
    >
      {glow && (
        <circle cx="16" cy="16" r="14"
          fill="rgba(201,169,97,0.12)" />
      )}
      <circle cx="16" cy="16" r="14"
        fill="none" stroke={BB.gold} strokeWidth="1" opacity={a} />
      <circle cx="16" cy="16" r="9.5"
        fill="none" stroke={BB.gold} strokeWidth="0.5" opacity={a * 0.6} />
      {ticks.map(angle => {
        const rad = angle * Math.PI / 180;
        return (
          <line key={angle}
            x1={16 + 11 * Math.cos(rad)} y1={16 + 11 * Math.sin(rad)}
            x2={16 + 14 * Math.cos(rad)} y2={16 + 14 * Math.sin(rad)}
            stroke={BB.gold} strokeWidth="0.75" opacity={a * 0.55}
          />
        );
      })}
      <text x="16" y="20.5"
        textAnchor="middle"
        fontFamily={fontDisplay}
        fontSize="10"
        fill={BB.gold}
        fontStyle="italic"
        opacity={a}
      >C</text>
    </svg>
  );
}

// ─── Gold Rule ───────────────────────────────────────────────────────────────
export function GoldRule({ double = false, faint = false, style: s = {} }) {
  const alpha = faint ? 0.22 : 0.72;
  const color = `rgba(201,169,97,${alpha})`;
  return (
    <div style={s}>
      <div style={{ borderTop: `1px solid ${color}` }} />
      {double && <div style={{ borderTop: `1px solid ${color}`, marginTop: '3px' }} />}
    </div>
  );
}

// ─── Printer's Ornament ──────────────────────────────────────────────────────
export function Ornament({ char = '❦', py = 20 }) {
  return (
    <div style={{
      display: 'flex', alignItems: 'center', gap: 16,
      padding: `${py}px 0`,
    }}>
      <div style={{ flex: 1, borderTop: '1px solid rgba(201,169,97,0.22)' }} />
      <span style={{
        color: BB.gold, fontSize: 18, opacity: 0.65, lineHeight: 1,
        userSelect: 'none',
      }}>{char}</span>
      <div style={{ flex: 1, borderTop: '1px solid rgba(201,169,97,0.22)' }} />
    </div>
  );
}

// ─── Meta Label ──────────────────────────────────────────────────────────────
// 12.5px = the product-wide 0.78rem readability floor (docs and dashboards
// share it) — metadata still reads as metadata, but a 65-year-old can read it.
export function MetaLabel({ children, style: s = {}, htmlFor, className }) {
  const Tag = htmlFor ? 'label' : 'span';
  const forProp = htmlFor ? { htmlFor } : {};
  return (
    <Tag {...forProp} className={className} style={{
      fontFamily: fontMono,
      fontSize: 12.5,
      letterSpacing: '0.14em',
      textTransform: 'uppercase',
      color: BB.fade,
      ...s,
    }}>{children}</Tag>
  );
}

// ─── Primary Button ──────────────────────────────────────────────────────────
export function BtnPrimary({ children, onClick, disabled = false, style: s = {}, full = false }) {
  const [hover, setHover] = React.useState(false);
  return (
    <button
      onClick={onClick}
      disabled={disabled}
      onMouseEnter={() => setHover(true)}
      onMouseLeave={() => setHover(false)}
      style={{
        fontFamily: fontBody,
        fontVariant: 'small-caps',
        letterSpacing: '0.14em',
        background: disabled ? BB.gold : hover ? BB.goldDark : BB.gold,
        color: BB.deep,
        border: 'none',
        padding: '12px 40px',
        fontSize: 17,
        fontWeight: 500,
        cursor: disabled ? 'not-allowed' : 'pointer',
        opacity: disabled ? 0.4 : 1,
        transition: 'background 0.35s ease',
        width: full ? '100%' : 'auto',
        display: full ? 'block' : 'inline-block',
        textAlign: 'center',
        ...s,
      }}
    >{children}</button>
  );
}

// ─── Ghost Button ────────────────────────────────────────────────────────────
export function BtnGhost({ children, onClick, disabled = false, style: s = {}, full = false }) {
  const [hover, setHover] = React.useState(false);
  return (
    <button
      onClick={onClick}
      disabled={disabled}
      onMouseEnter={() => setHover(true)}
      onMouseLeave={() => setHover(false)}
      style={{
        fontFamily: fontBody,
        fontVariant: 'small-caps',
        letterSpacing: '0.14em',
        background: hover ? 'rgba(201,169,97,0.07)' : 'transparent',
        color: BB.gold,
        border: `1px solid rgba(201,169,97,${hover ? 0.6 : 0.32})`,
        padding: '12px 40px',
        fontSize: 17,
        fontWeight: 500,
        cursor: disabled ? 'not-allowed' : 'pointer',
        opacity: disabled ? 0.4 : 1,
        transition: 'all 0.35s ease',
        width: full ? '100%' : 'auto',
        display: full ? 'block' : 'inline-block',
        textAlign: 'center',
        ...s,
      }}
    >{children}</button>
  );
}

// ─── Status Badge ────────────────────────────────────────────────────────────
const STATUS_MAP = {
  ACTIVE:      { color: '#5EB87C', border: 'rgba(94,184,124,0.28)' },
  DRAFT:       { color: BB.fade,   border: 'rgba(139,155,180,0.25)' },
  COMPLETED:   { color: BB.fade,   border: 'rgba(139,155,180,0.25)' },
  SCHEDULED:   { color: BB.gold,   border: 'rgba(201,169,97,0.28)' },
  FLAGGED:     { color: '#C47A6B', border: 'rgba(196,122,107,0.28)' },
  ARCHIVED:    { color: '#4A4A4A', border: 'rgba(74,74,74,0.28)' },
  IN_PROGRESS: { color: BB.gold,   border: 'rgba(201,169,97,0.28)' },
  OPEN:        { color: '#5EB87C', border: 'rgba(94,184,124,0.28)' },
  CLOSED:      { color: BB.fade,   border: 'rgba(139,155,180,0.25)' },
  SUBMITTED:   { color: BB.cream,  border: 'rgba(240,237,228,0.28)' },
  INVITED:     { color: BB.gold,   border: 'rgba(201,169,97,0.28)' },
  LINK:        { color: BB.fade,   border: 'rgba(139,155,180,0.25)' },
};

// ─── The "worth a look" mark and Original's testing-phase label ─────────────
// "Worth a look" is an Original result (a sealed exam compared with the writing
// in the student's baseline), so wherever a teacher can see it the screen must
// say plainly that Original is in its testing phase (NORTH_STAR rule 10). The
// sentence is the one the Original suite shows (demo/original/live.js, NOTICE);
// a test pins the two together. A tooltip is not enough: a screen that shows the
// mark (this badge, a count, a filter, a row) renders <WorthALookNote /> once.
export const ORIGINAL_TESTING_NOTICE = 'Testing phase: Original is not yet validated on real student writing. Treat any result as a reason for a conversation, never as evidence.';
export const WORTH_A_LOOK_SOURCE = "Worth a look: marked by Original's comparison with the writing in each student's baseline.";
// Styled by `.bb-hint` (inside a .bb-page screen); a screen laid out in inline
// styles passes `style`.
export function WorthALookNote({ style }) {
  return (
    <p className="bb-hint" style={{ margin: '0 0 .8rem', ...style }}>{WORTH_A_LOOK_SOURCE} {ORIGINAL_TESTING_NOTICE}</p>
  );
}

export function StatusBadge({ status, pulse = false }) {
  const s = STATUS_MAP[(status || '').toUpperCase()] || STATUS_MAP.DRAFT;
  const flagged = (status || '').toUpperCase() === 'FLAGGED';
  return (
    <span title={flagged ? `${WORTH_A_LOOK_SOURCE} ${ORIGINAL_TESTING_NOTICE}` : undefined} style={{
      fontFamily: fontMono,
      fontSize: 9,
      letterSpacing: '0.18em',
      textTransform: 'uppercase',
      color: s.color,
      border: `1px solid ${s.border}`,
      padding: '3px 9px',
      display: 'inline-flex',
      alignItems: 'center',
      gap: 6,
      whiteSpace: 'nowrap',
    }}>
      {pulse && status === 'ACTIVE' && (
        <span style={{
          width: 5, height: 5, borderRadius: '50%',
          background: '#5EB87C',
          animation: 'bbPulse 2s ease-in-out infinite',
          flexShrink: 0,
        }} />
      )}
      {flagged ? 'worth a look' : (status || '').toLowerCase().replace(/_/g, ' ')}
    </span>
  );
}

// ─── Original API client (exam persistence) ──────────────────────────────────
// Same-origin by default (Bluebook is served by the Original demo server).
// Attaches whatever session token is present so writes are tenant-scoped.

// Kept by the Original pages (demo/original/writing-state.html, demo/professor.html).
const BB_PORTFOLIO_PREFIX = 'original_portfolio_';
const BB_LAST_RESULT_KEY = 'original_last_result';
function bbClearKeptPapers() {
  try {
    // Collect first, remove after: removing while counting skips entries.
    const found = [];
    for (let i = 0; i < localStorage.length; i++) {
      const k = localStorage.key(i);
      if (k && k.indexOf(BB_PORTFOLIO_PREFIX) === 0) found.push(k);
    }
    found.forEach(k => { try { localStorage.removeItem(k); } catch (e) {} });
  } catch (e) {}
  try { sessionStorage.removeItem(BB_LAST_RESULT_KEY); } catch (e) {}
}

// Every localStorage key a sign-in (or a launch) can leave behind. Signing
// in as one kind of account clears the others, so a shared machine never
// carries a stale student binding into a teacher session or vice versa.
const BB_SESSION_KEYS = [
  'original_principal_token', 'original_session_token', 'original_role',
  'original_tenant', 'original_name', 'original_email', 'original_products',
  'original_student_id', 'bluebook_student_id', 'bluebook_candidate_email',
  'bluebook_proctor_token',
];

// What a person is shown when a request fails: the server's own sentence when
// it sent one, otherwise a plain sentence for that kind of failure. Never a
// bare status line such as "Unprocessable Entity" or "Internal Server Error".
async function bbDetail(r, fallback) {
  let detail = null;
  try { detail = (await r.json()).detail; } catch (e) {}
  if (typeof detail === 'string' && detail.trim()) return detail;
  if (fallback) return fallback;
  if (r.status === 429) return 'Too many tries in a short time. Please wait a minute and try again.';
  if (r.status >= 500) return 'Something went wrong on our side. Please try again in a moment.';
  return 'That did not go through. Please check what you entered and try again.';
}

// A 401 that only means "no valid sign-in" is said in plain words. A 401 that
// says something specific (a wrong current password, a removed account) is
// passed on as the server wrote it.
const BB_SIGNED_OUT = 'Your sign-in has expired. Please sign in again.';
// What the server says for a missing or lapsed staff token (original/api.py).
const BB_STAFF_401 = /^(authentication required|this account no longer exists)/i;
const BB_GENERIC_401 = /^(not authenticated|not signed in\.?|expired|invalid token)$/i;

// A teacher's sign-in lasts 8 hours (original/principal.py). When it has
// lapsed, every teacher list answers 401; those screens used to show that as
// "No examinations yet". Announce it once so the app can send the teacher to
// sign in instead (alpha bug 2026-10-20). Students are not affected.
export const BB_SIGNED_OUT_EVENT = 'bb-staff-signed-out';
function bbStaffSignedOut() {
  try {
    if (!localStorage.getItem('original_principal_token')) return;
    window.dispatchEvent(new Event(BB_SIGNED_OUT_EVENT));
  } catch (e) {}
}

export const BB_API = {
  base: window.BB_API_BASE || '',
  // JSON request that throws Error(detail) on any non-2xx. The error carries
  // the HTTP status, so a caller can tell a refusal (which will not change on
  // retry) from a server that is briefly unavailable.
  async _json(method, path, body) {
    const r = await fetch(this.base + path, {
      method, headers: this._headers(),
      body: body === undefined ? undefined : JSON.stringify(body),
    });
    if (!r.ok) {
      const said = await bbDetail(r, r.status === 401 ? BB_SIGNED_OUT : undefined);
      const lapsed = r.status === 401 && (said === BB_SIGNED_OUT || BB_GENERIC_401.test(said) || BB_STAFF_401.test(said));
      // Only a lapsed sign-in signs the teacher out; a specific 401 (a wrong
      // current password) stays on its own form.
      if (lapsed) bbStaffSignedOut();
      const err = new Error(lapsed ? BB_SIGNED_OUT : said);
      err.status = r.status;
      throw err;
    }
    return r.json();
  },
  _headers() {
    const h = { 'Content-Type': 'application/json' };
    const tok = localStorage.getItem('original_principal_token')
      || localStorage.getItem('original_session_token');
    if (tok) h['Authorization'] = 'Bearer ' + tok;
    return h;
  },
  async listExams() {
    try {
      const r = await fetch(this.base + '/bluebook/exams', { headers: this._headers() });
      if (r.status === 401) bbStaffSignedOut();
      if (!r.ok) return null;
      return (await r.json()).exams || [];
    } catch (e) { return null; }
  },
  async createExam(payload) {
    const r = await fetch(this.base + '/bluebook/exams', {
      method: 'POST', headers: this._headers(), body: JSON.stringify(payload),
    });
    if (!r.ok) {
      let detail = r.statusText;
      try { detail = (await r.json()).detail || detail; } catch (e) {}
      throw new Error(detail);
    }
    return r.json();
  },
  // Throws on failure. The seal loop retries on a throw and keeps the draft
  // on the device until this lands — a seal is only "sealed" once the
  // submission row exists, because that row is all the teacher ever sees.
  async recordSubmission(payload) {
    return this._json('POST', '/bluebook/submissions', payload);
  },
  // The signed-in student's own unsealed draft kept on the server, so a
  // sitting resumes from any browser. Never throws: a draft that cannot be
  // read or saved leaves the on-device copy in charge. keepalive lets the
  // save on page close still go out.
  async getExamDraft(examId) {
    try {
      const r = await fetch(this.base + `/bluebook/exams/${encodeURIComponent(examId)}/draft`, { headers: this._headers() });
      if (!r.ok) return null;
      return await r.json();
    } catch (e) { return null; }
  },
  async putExamDraft(examId, draft, { keepalive = false } = {}) {
    try {
      const r = await fetch(this.base + `/bluebook/exams/${encodeURIComponent(examId)}/draft`, {
        method: 'PUT', headers: this._headers(), body: JSON.stringify(draft), keepalive,
      });
      return r.status;
    } catch (e) { return 0; }
  },
  // Where this account last was (resume-location.jsx), kept on the server so
  // signing in on another device returns there. Never throws: a place that
  // cannot be read or saved just means the home screen.
  async getLastLocation() {
    try {
      const r = await fetch(this.base + '/bluebook/me/location', { headers: this._headers() });
      if (!r.ok) return null;
      return (await r.json()).location || null;
    } catch (e) { return null; }
  },
  async putLastLocation(loc, { keepalive = false } = {}) {
    try {
      const r = await fetch(this.base + '/bluebook/me/location', {
        method: 'PUT', headers: this._headers(), body: JSON.stringify(loc), keepalive,
      });
      return r.status;
    } catch (e) { return 0; }
  },
  async listSubmissions() {
    return (await this._json('GET', '/bluebook/submissions')).submissions || [];
  },
  async listCourses() {
    try {
      const r = await fetch(this.base + '/bluebook/courses', { headers: this._headers() });
      if (r.status === 401) bbStaffSignedOut();
      if (!r.ok) return null;
      return (await r.json()).courses || [];
    } catch (e) { return null; }
  },
  // File instructor feedback on a scoring verdict — persists to the
  // corrections ledger (drives future retraining; see original/schemas.py
  // CorrectionRequest). submissionId is the Original scoring-record id
  // for the submission (Exam.jsx now threads the seal's own uuid into the
  // score call, so it's the same as the row's submission_uuid) — not the
  // Bluebook exam id.
  async fileCorrection(submissionId, { isCorrect, correctedVerdict, correctedAction, reviewer, notes }) {
    const r = await fetch(this.base + `/submissions/${encodeURIComponent(submissionId)}/correct`, {
      method: 'POST', headers: this._headers(),
      body: JSON.stringify({
        is_correct: isCorrect,
        corrected_verdict: correctedVerdict || null,
        corrected_action: correctedAction || null,
        reviewer: reviewer || null,
        notes: notes || null,
      }),
    });
    if (!r.ok) {
      let detail = r.statusText;
      try { detail = (await r.json()).detail || detail; } catch (e) {}
      throw new Error(detail);
    }
    return r.json();
  },
  async listCorrections(submissionId) {
    try {
      const r = await fetch(
        this.base + `/admin/corrections?submission_id=${encodeURIComponent(submissionId)}`,
        { headers: this._headers() },
      );
      if (!r.ok) return null;
      return (await r.json()).items || [];
    } catch (e) { return null; }
  },
  async createCourse(payload) {
    const r = await fetch(this.base + '/bluebook/courses', {
      method: 'POST', headers: this._headers(), body: JSON.stringify(payload),
    });
    if (!r.ok) {
      let detail = r.statusText;
      try { detail = (await r.json()).detail || detail; } catch (e) {}
      throw new Error(detail);
    }
    return r.json();
  },
  // ── QR phone park (proctoring deterrence) ──
  // Staff-only endpoints; the phones themselves post to /proctor/park/beat
  // anonymously and never touch this client.
  async parkOpen(examSessionId) {
    const r = await fetch(this.base + '/proctor/park/open', {
      method: 'POST', headers: this._headers(),
      body: JSON.stringify({ exam_session_id: examSessionId }),
    });
    if (!r.ok) {
      let detail = r.statusText;
      try { detail = (await r.json()).detail || detail; } catch (e) {}
      throw new Error(detail);
    }
    return r.json();   // { park_token, qr_url }
  },
  // Resolves to `null` on a transient failure (keep the last tiles on screen)
  // and to `{ tiles: [], missing: true }` on 404. A 404 here is the ordinary
  // answer for "never opened, or just deleted" — the poll loop hits it every
  // time a session is closed, so it must never read as an error.
  async parkStatus(examSessionId) {
    try {
      const r = await fetch(
        this.base + '/proctor/park/status?exam_session_id=' + encodeURIComponent(examSessionId),
        { headers: this._headers() },
      );
      if (r.status === 404) return { tiles: [], missing: true };
      if (!r.ok) return null;
      const data = await r.json();
      return { tiles: data.tiles || [], missing: false };
    } catch (e) { return null; }
  },
  // 404 means it is already gone, which is the outcome the caller wanted.
  // NOTE: `deleted` counts the session row plus every beat row, so it is not
  // a phone count and must not be shown to anyone as one.
  async parkDelete(examSessionId) {
    const r = await fetch(this.base + '/proctor/park/' + encodeURIComponent(examSessionId), {
      method: 'DELETE', headers: this._headers(),
    });
    if (r.status === 404) return { deleted: 0 };
    if (!r.ok) {
      let detail = r.statusText;
      try { detail = (await r.json()).detail || detail; } catch (e) {}
      throw new Error(detail);
    }
    return r.json();
  },

  // ── Teacher: exams, courses, rosters, submissions (self-serve) ──
  getExam(id)            { return this._json('GET', `/bluebook/exams/${encodeURIComponent(id)}`); },
  updateExam(id, fields) { return this._json('PATCH', `/bluebook/exams/${encodeURIComponent(id)}`, fields); },
  deleteExam(id)         { return this._json('DELETE', `/bluebook/exams/${encodeURIComponent(id)}`); },
  updateCourse(id, f)    { return this._json('PATCH', `/bluebook/courses/${encodeURIComponent(id)}`, f); },
  deleteCourse(id)       { return this._json('DELETE', `/bluebook/courses/${encodeURIComponent(id)}`); },
  getSubmission(id)      { return this._json('GET', `/bluebook/submissions/${encodeURIComponent(id)}`); },
  async rosterList(courseId) {
    return (await this._json('GET', `/bluebook/courses/${encodeURIComponent(courseId)}/students`)).students || [];
  },
  async rosterAdd(courseId, students, sendEmail = false) {
    return (await this._json('POST', `/bluebook/courses/${encodeURIComponent(courseId)}/students`, { students, send_email: sendEmail })).students || [];
  },
  // Fresh links for every student still waiting on an invite (links are
  // stored hashed, so an old one can never be shown again — only replaced).
  async reissuePending(courseId, sendEmail = false) {
    return (await this._json('POST', `/bluebook/courses/${encodeURIComponent(courseId)}/invites/reissue-pending`, { send_email: sendEmail })).students || [];
  },
  async listStudents()  { return (await this._json('GET', '/bluebook/students')).students || []; },
  examLive(id)          { return this._json('GET', `/bluebook/exams/${encodeURIComponent(id)}/live`); },
  saveFeedback(id, { mark, feedback }) {
    return this._json('PATCH', `/bluebook/submissions/${encodeURIComponent(id)}/feedback`, { mark, feedback });
  },
  releaseResults(id)    { return this._json('POST', `/bluebook/exams/${encodeURIComponent(id)}/release`); },
  unreleaseResults(id)  { return this._json('POST', `/bluebook/exams/${encodeURIComponent(id)}/unrelease`); },
  // Professor-approved writing baselines (plan Phase 7).
  addToBaseline(id)      { return this._json('POST',   `/bluebook/submissions/${encodeURIComponent(id)}/baseline`); },
  removeFromBaseline(id) { return this._json('DELETE', `/bluebook/submissions/${encodeURIComponent(id)}/baseline`); },
  examBaselineStatus(id) { return this._json('GET',    `/bluebook/exams/${encodeURIComponent(id)}/baseline`); },
  addExamToBaselines(id) { return this._json('POST',   `/bluebook/exams/${encodeURIComponent(id)}/baseline`); },
  async authMe()        { return this._rememberProducts(await this._json('GET', '/auth/me')); },
  rosterRemove(courseId, sid) {
    return this._json('DELETE', `/bluebook/courses/${encodeURIComponent(courseId)}/students/${encodeURIComponent(sid)}`);
  },
  // Permanent FERPA erasure: the account, every sitting and submission, and
  // every roster row — not just this course.
  eraseStudent(sid) {
    return this._json('DELETE', `/bluebook/students/${encodeURIComponent(sid)}`);
  },
  rosterReissue(courseId, sid, sendEmail = false) {
    return this._json('POST', `/bluebook/courses/${encodeURIComponent(courseId)}/students/${encodeURIComponent(sid)}/invite`, { send_email: sendEmail });
  },
  // Download the CSV through fetch (it needs the Authorization header, which
  // a plain link cannot send), then hand the browser a blob to save.
  async downloadExport(examId, title) {
    const r = await fetch(this.base + `/bluebook/exams/${encodeURIComponent(examId)}/export`, { headers: this._headers() });
    if (!r.ok) throw new Error(await bbDetail(r));
    const url = URL.createObjectURL(await r.blob());
    const a = document.createElement('a');
    a.href = url;
    a.download = `${(title || 'exam').replace(/[^A-Za-z0-9]+/g, '-').slice(0, 60) || 'exam'}.csv`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  },

  // ── Student dashboard ──
  async me()             { return this._rememberProducts(await this._json('GET', '/bluebook/me')); },
  async myExams()        { return (await this._json('GET', '/bluebook/me/exams')).exams || []; },
  myExam(id)             { return this._json('GET', `/bluebook/me/exams/${encodeURIComponent(id)}`); },
  startMyExam(id)        { return this._json('POST', `/bluebook/me/exams/${encodeURIComponent(id)}/start`); },
  async mySubmissions()  { return (await this._json('GET', '/bluebook/me/submissions')).submissions || []; },
  // Past papers the student shares for their teacher to review (titles and
  // review status only; nothing here is ever scored).
  async myPapers()       { return this._json('GET', '/bluebook/me/papers'); },
  // multipart: a file and/or pasted text. No Content-Type header, so the
  // browser sets the multipart boundary itself.
  async sharePaper(form) {
    const h = this._headers(); delete h['Content-Type'];
    const r = await fetch(this.base + '/bluebook/me/papers', { method: 'POST', headers: h, body: form });
    if (!r.ok) {
      const err = new Error(await bbDetail(r, r.status === 401 ? BB_SIGNED_OUT : undefined));
      err.status = r.status;
      throw err;
    }
    return r.json();
  },
  mySubmission(id)       { return this._json('GET', `/bluebook/me/submissions/${encodeURIComponent(id)}`); },

  // ── Auth / session ──
  // Store whatever a sign-in returned. Staff get a principal token; students
  // get a session token and their student id. Everything else is cleared.
  _storeSession(data) {
    this._clearSession();
    const student = data.role === 'student';
    localStorage.setItem(student ? 'original_session_token' : 'original_principal_token', data.token);
    if (student) localStorage.setItem('original_student_id', data.student_id || '');
    localStorage.setItem('original_role', data.role || 'professor');
    localStorage.setItem('original_tenant', data.tenant_id || '');
    localStorage.setItem('original_name', data.name || '');
    localStorage.setItem('original_email', data.email || '');
    localStorage.setItem('original_products', JSON.stringify(data.products || ['original', 'bluebook']));
    return data;
  },
  // Original can be switched on or off for a workspace while a page is open
  // (scripts/set_products.py). /auth/me and /bluebook/me carry the current
  // products, so the teacher workspace and the student home refresh what
  // sign-in stored each time they load. Returns the response unchanged.
  _rememberProducts(data) {
    if (data && Array.isArray(data.products) && data.products.length) {
      try { localStorage.setItem('original_products', JSON.stringify(data.products)); } catch (e) {}
    }
    return data;
  },
  // An Original route answered 403: this workspace no longer holds Original.
  // Stop calling it from this page until the next home-page load says otherwise.
  dropOriginal() {
    this._rememberProducts({ products: this.products().filter(p => p !== 'original') });
  },
  async _auth(path, body, fallback) {
    const r = await fetch(this.base + path, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    if (!r.ok) throw new Error(await bbDetail(r, fallback));
    return this._storeSession(await r.json());
  },
  login(email, password) {
    return this._auth('/auth/login', { email, password }, 'Invalid email or password');
  },
  signup(name, email, password, acceptTerms = false) {
    return this._auth('/auth/signup', { name, email, password, accept_terms: acceptTerms }, 'Could not create the workspace');
  },
  // Always resolves the same way whether or not the address has an account,
  // so the form cannot be used to discover who is registered.
  async requestPasswordReset(email) {
    const r = await fetch(this.base + '/auth/password-reset/request', {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ email }),
    });
    if (!r.ok) throw new Error(await bbDetail(r, 'We could not send the reset email just now. Please try again in a few minutes.'));
    return r.json();
  },
  // An invited professor's first password also accepts the terms; students
  // and password resets send false and the server ignores it.
  redeemInvite(token, password, acceptTerms = false) {
    return this._auth('/auth/invite/redeem', { token, password, accept_terms: acceptTerms }, 'This link could not be used. Ask your teacher for a new one, or use “Forgot password”.');
  },
  changePassword(currentPassword, newPassword) {
    return this._json('POST', '/auth/password', { current_password: currentPassword, new_password: newPassword });
  },
  // The public health probe, fetched once per page. A failure resolves to
  // null; every reader below treats null as "not a demo, signup closed".
  _health() {
    if (this._healthP === undefined) {
      this._healthP = fetch(this.base + '/health')
        .then(r => (r.ok ? r.json() : null))
        .catch(() => null);
    }
    return this._healthP;
  },
  // The deploy's environment label. Demo-only affordances ("Explore the
  // demo") show only when this is 'demo'.
  async environment() {
    const h = await this._health();
    return (h && h.environment) || null;
  },
  // Whether teachers may create their own workspace (SELF_SERVE_SIGNUP).
  // Fails closed so an invitation-only pilot never advertises signup
  // because of a network blip; an older server without the field is open.
  async signupOpen() {
    const h = await this._health();
    return !!h && h.signup_open !== false;
  },
  // The keys a sign-in leaves behind. Signing in clears these (so one kind of
  // account never inherits another's binding) but not the papers kept below.
  _clearSession() {
    BB_SESSION_KEYS.forEach(k => { try { localStorage.removeItem(k); } catch (e) {} });
  },
  // Signing out also forgets the papers the Original Writing State page keeps on
  // this computer (the full text and the results, one key per student) and its last
  // result, so a shared computer does not hold the last teacher's students' writing.
  // The same keys Live.signOut and professor.html's signOut clear.
  logout() {
    this._clearSession();
    bbClearKeptPapers();
  },
  // Which account this browser is signed in as, for noticing a switch made
  // in another tab. Token-based, so a re-login as a different user counts.
  sessionSignature() {
    try {
      const tok = localStorage.getItem('original_principal_token') || localStorage.getItem('original_session_token') || '';
      return tok ? tok + '|' + (localStorage.getItem('original_role') || '') : '';
    } catch (e) { return ''; }
  },
  isAuthed()        { try { return !!localStorage.getItem('original_principal_token'); } catch (e) { return false; } },
  isStudentLaunch() { try { return !!localStorage.getItem('bluebook_student_id'); }      catch (e) { return false; } },
  // A student who signed in with an account (not a launch link).
  isStudentAccount() {
    try {
      return localStorage.getItem('original_role') === 'student'
        && !!localStorage.getItem('original_session_token')
        && !localStorage.getItem('bluebook_student_id');
    } catch (e) { return false; }
  },
  products() {
    try {
      const p = JSON.parse(localStorage.getItem('original_products') || 'null');
      return Array.isArray(p) && p.length ? p : ['original', 'bluebook'];
    } catch (e) { return ['original', 'bluebook']; }
  },
  // Whether this workspace bought Original. Bluebook-only workspaces never
  // call the stylometric engine and never see its scores.
  hasOriginal() { return this.products().includes('original'); },
  isDevToolsArmed() { try { return localStorage.getItem('bluebook_dev_tools') === '1'; } catch (e) { return false; } },
  identity() {
    try {
      return {
        name:   localStorage.getItem('original_name') || '',
        email:  localStorage.getItem('original_email') || '',
        role:   localStorage.getItem('original_role') || '',
        tenant: localStorage.getItem('original_tenant') || '',
        authed: !!localStorage.getItem('original_principal_token'),
      };
    } catch (e) { return { name: '', email: '', role: '', tenant: '', authed: false }; }
  },
};

// ─── Internal dev tools gate ─────────────────────────────────────────────────
// The Tweaks panel (tweaks-panel.jsx) is an internal tuning surface, not part
// of the product: its "Jump to screen" control alone can move the app from a
// sitting straight into the professor console. It has been mounted for every
// visitor, waiting on a `__activate_edit_mode` postMessage that anything on
// the page — or any frame embedding it — can send. So the panel a candidate
// cannot see is not the same as a panel a candidate cannot reach, and this is
// what closes the second one.
//
// Runtime gate, deliberately. Render has no Node and serves the one committed
// bluebook.bundle.js (BUILD.md), so a build-time strip would mean two bundles
// and a way to ship the wrong one; the exam runs the same bytes either way.
//
// Armed the way every other Bluebook launch flag is set: index.html's
// query-param bootstrap, which already turns ?sid/?tenant/?candidate into
// localStorage. `?dev=1` stores `bluebook_dev_tools`, `?dev=0` clears it, and
// it persists in between so reloading during a tuning pass doesn't lose it.
//
// Refused outright for a bound student launch, whatever that key says. A
// candidate appending `?dev=1` mid-exam is the exact case this exists to
// answer, and answering it with "well, they'd have to set a flag" is not an
// answer. Staff have no student binding, so this costs them nothing.
export function devToolsEnabled() {
  if (BB_API.isStudentLaunch()) return false;
  return BB_API.isDevToolsArmed();
}
