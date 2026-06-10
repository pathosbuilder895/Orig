// ════════════════════════════════════════════════════════════════
//  BLUEBOOK — Design System Components
//  Oxford Blue · Antique Gold · Parchment · EB Garamond
// ════════════════════════════════════════════════════════════════

const BB = {
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

const fontDisplay = "'Cormorant Garamond', serif";
const fontBody    = "'EB Garamond', serif";
const fontMono    = "'IBM Plex Mono', monospace";

const PARCHMENT_SHADES = {
  warm:  '#F4EFE6',
  ivory: '#F8F5EE',
  cool:  '#EEF2EC',
};

// ─── Logotype ────────────────────────────────────────────────────────────────
function Logotype({ size = 22, onClick, light = false }) {
  return (
    <span
      onClick={onClick}
      style={{
        fontFamily: fontDisplay,
        fontSize: size,
        color: BB.gold,
        fontWeight: 600,
        letterSpacing: '0.06em',
        cursor: onClick ? 'pointer' : 'default',
        userSelect: 'none',
        whiteSpace: 'nowrap',
      }}
    >
      B<span style={{
        fontVariant: 'small-caps',
        letterSpacing: '0.15em',
        fontSize: size * 0.88,
        color: light ? BB.fadedCream : BB.gold,
      }}>luebook</span>
    </span>
  );
}

// ─── Wax Seal SVG ────────────────────────────────────────────────────────────
function Seal({ size = 22, verified = true, glow = false }) {
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
      >B</text>
    </svg>
  );
}

// ─── Gold Rule ───────────────────────────────────────────────────────────────
function GoldRule({ double = false, faint = false, style: s = {} }) {
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
function Ornament({ char = '❦', py = 20 }) {
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
function MetaLabel({ children, style: s = {} }) {
  return (
    <span style={{
      fontFamily: fontMono,
      fontSize: 10,
      letterSpacing: '0.2em',
      textTransform: 'uppercase',
      color: BB.fade,
      ...s,
    }}>{children}</span>
  );
}

// ─── Primary Button ──────────────────────────────────────────────────────────
function BtnPrimary({ children, onClick, disabled = false, style: s = {}, full = false }) {
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
function BtnGhost({ children, onClick, disabled = false, style: s = {}, full = false }) {
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
};

function StatusBadge({ status, pulse = false }) {
  const s = STATUS_MAP[status] || STATUS_MAP.DRAFT;
  return (
    <span style={{
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
      {status.toLowerCase().replace(/_/g, ' ')}
    </span>
  );
}

// ─── Original API client (exam persistence) ──────────────────────────────────
// Same-origin by default (Bluebook is served by the Original demo server).
// Attaches whatever session token is present so writes are tenant-scoped.
const BB_API = {
  base: window.BB_API_BASE || '',
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
  async recordSubmission(payload) {
    try {
      const r = await fetch(this.base + '/bluebook/submissions', {
        method: 'POST', headers: this._headers(), body: JSON.stringify(payload),
      });
      return r.ok;
    } catch (e) { return false; }
  },
  async listSubmissions() {
    try {
      const r = await fetch(this.base + '/bluebook/submissions', { headers: this._headers() });
      if (!r.ok) return null;
      return (await r.json()).submissions || [];
    } catch (e) { return null; }
  },
  async listCourses() {
    try {
      const r = await fetch(this.base + '/bluebook/courses', { headers: this._headers() });
      if (!r.ok) return null;
      return (await r.json()).courses || [];
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
  // ── Auth / session ──
  async login(email, password) {
    const r = await fetch(this.base + '/auth/login', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email, password }),
    });
    if (!r.ok) {
      let detail = 'Invalid email or passphrase';
      try { detail = (await r.json()).detail || detail; } catch (e) {}
      throw new Error(detail);
    }
    const data = await r.json();
    localStorage.setItem('original_principal_token', data.token);
    localStorage.setItem('original_role', data.role || 'professor');
    localStorage.setItem('original_tenant', data.tenant_id || '');
    localStorage.setItem('original_name', data.name || '');
    return data;
  },
  logout() {
    ['original_principal_token', 'original_session_token', 'original_role',
     'original_tenant', 'original_name', 'bluebook_student_id', 'bluebook_candidate_email']
      .forEach(k => { try { localStorage.removeItem(k); } catch (e) {} });
  },
  isAuthed()        { try { return !!localStorage.getItem('original_principal_token'); } catch (e) { return false; } },
  isStudentLaunch() { try { return !!localStorage.getItem('bluebook_student_id'); }      catch (e) { return false; } },
  identity() {
    try {
      return {
        name:   localStorage.getItem('original_name') || '',
        role:   localStorage.getItem('original_role') || '',
        tenant: localStorage.getItem('original_tenant') || '',
        authed: !!localStorage.getItem('original_principal_token'),
      };
    } catch (e) { return { name: '', role: '', tenant: '', authed: false }; }
  },
};

// Export everything to window for cross-script access
Object.assign(window, {
  BB, fontDisplay, fontBody, fontMono, PARCHMENT_SHADES,
  Logotype, Seal, GoldRule, Ornament, MetaLabel,
  BtnPrimary, BtnGhost, StatusBadge, BB_API,
});
