// Portal.jsx — the student-facing surface, standalone (no staff sidebar).
//
// ADR-005 boundary: everything rendered here comes from the redacted
// VoiceView read-model (/me/voice) — fingerprint dimensions, the term arc,
// milestones, notes, review invitations, formation. Never scores, flags,
// feature codes, or action enums; the server strips them (tests/test_voice_leak.py)
// and this page renders only the allow-listed fields. The language stays
// pastoral for the same reason the classic student.html's does.
//
// Modes: gate (login) → live (/me/* with a real student session), or guest —
// a clearly-bannered client-side showcase that makes ZERO /me/* calls,
// mirroring the classic page's guest pattern.

import { useEffect, useState } from 'react';
import {
  getSession, storeSession, clearSession,
  login, validateSession, fetchVoice, submitWork, advanceFormation,
} from './portal-api.js';

const GUEST_ID = 'demo_student';

// Guest showcase — VoiceView-shaped sample data, labeled as such on screen.
const GUEST_VOICE = {
  name: 'Andrew Whitfield',
  headline: 'Your voice is taking shape.',
  subhead: 'Michaelmas Term · Wycliffe College',
  fingerprint: [
    { name: 'Rhythm', value: 0.72 }, { name: 'Vocabulary', value: 0.64 },
    { name: 'Hedging', value: 0.55 }, { name: 'Transitions', value: 0.68 },
    { name: 'Assertion', value: 0.49 }, { name: 'First person', value: 0.61 },
    { name: 'Word length', value: 0.58 }, { name: 'Register', value: 0.75 },
  ],
  arc: [
    { period: 'Week 1', fidelity: 78, attention: false },
    { period: 'Week 3', fidelity: 84, attention: false },
    { period: 'Week 5', fidelity: 81, attention: false },
    { period: 'Week 7', fidelity: 90, attention: false },
    { period: 'Week 9', fidelity: 74, attention: true },
    { period: 'Week 11', fidelity: 88, attention: false },
  ],
  milestones: [
    { label: 'Voice Sampled', state: 'reached', blurb: 'Your writing enters your record.' },
    { label: 'Voice Established', state: 'reached', blurb: 'Enough on file to recognise your voice.' },
    { label: 'Voice Affirmed', state: 'upcoming', blurb: 'A verified piece confirms it is yours.' },
  ],
  voice_notes: [
    { note: 'The Week 7 reflection has a lovely patience to it — you let the argument breathe before resolving it.', reviewer: 'Dr. Hendricks', date: 'Week 8' },
  ],
  review_opportunities: [],
  formation: { active: true, status: 'in_progress', current_step: 2, total_steps: 3, step_label: 'Begin formation', supportive_copy: 'Two sittings down — one verified piece to go.' },
};

export function Portal() {
  const [phase, setPhase] = useState('loading'); // loading | gate | guest | live
  const [voice, setVoice] = useState(null);
  const [error, setError] = useState(null);

  // Login form
  const [email, setEmail] = useState('');
  const [institution, setInstitution] = useState('');
  const [name, setName] = useState('');
  const [busy, setBusy] = useState(false);

  // Submit work
  const [workTitle, setWorkTitle] = useState('');
  const [workText, setWorkText] = useState('');
  const [workResult, setWorkResult] = useState(null);

  useEffect(() => {
    const s = getSession();
    if (s.token) {
      validateSession()
        .then(() => loadVoice())
        .catch(() => { clearSession(); setPhase('gate'); });
    } else if (s.studentId === GUEST_ID) {
      setVoice(GUEST_VOICE);
      setPhase('guest');
    } else {
      setPhase('gate');
    }
  }, []);

  async function loadVoice() {
    try {
      const v = await fetchVoice();
      setVoice(v);
      setPhase('live');
    } catch (e) {
      setError(String(e.message || e));
      setPhase('gate');
    }
  }

  async function doLogin(ev) {
    ev.preventDefault();
    if (!email.trim() || !institution.trim() || busy) return;
    setBusy(true);
    setError(null);
    try {
      const resp = await login(email.trim(), institution.trim(), name.trim());
      storeSession(resp);
      await loadVoice();
    } catch (e) {
      setError(String(e.message || e));
    } finally {
      setBusy(false);
    }
  }

  function enterGuest() {
    clearSession();
    try { localStorage.setItem('original_student_id', GUEST_ID); } catch (e) { /* ignore */ }
    setVoice(GUEST_VOICE);
    setPhase('guest');
  }

  function signOut() {
    clearSession();
    setVoice(null);
    setWorkResult(null);
    setPhase('gate');
  }

  async function doSubmitWork(ev) {
    ev.preventDefault();
    const wc = workText.trim().split(/\s+/).filter(Boolean).length;
    if (wc < 20 || busy) return;
    setBusy(true);
    setError(null);
    if (phase === 'guest') {
      // Guest showcase: no /me/* calls — a gentle, clearly-local response.
      setWorkResult({
        headline: 'Received — in demo mode.',
        summary: 'This showcase does not send your writing anywhere. Sign in and your submissions join your own record.',
        steady: [], review_opportunity: false,
      });
      setBusy(false);
      return;
    }
    try {
      const r = await submitWork(workText, workTitle);
      setWorkResult(r);
      setWorkText('');
      const v = await fetchVoice();
      setVoice(v);
    } catch (e) {
      setError(String(e.message || e));
    } finally {
      setBusy(false);
    }
  }

  async function doAdvance() {
    if (phase !== 'live' || busy) return;
    setBusy(true);
    try {
      const v = await advanceFormation();
      setVoice(v);
    } catch (e) {
      setError(String(e.message || e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="portal-shell">
      <header className="portal-top">
        <div className="portal-brand"><span className="portal-mark" />ORIGINAL</div>
        {(phase === 'live' || phase === 'guest') && (
          <button className="portal-signout" onClick={signOut}>{phase === 'guest' ? 'Leave demo' : 'Sign out'}</button>
        )}
      </header>

      {phase === 'loading' && <div className="portal-card portal-center"><p className="portal-quiet">One moment…</p></div>}

      {phase === 'gate' && (
        <div className="portal-card portal-gate">
          <h1 className="portal-h1">Your writing, in formation.</h1>
          <p className="portal-lede">
            Original keeps a record of your voice as it grows across the term —
            so your work is recognised as unmistakably yours.
          </p>
          <form onSubmit={doLogin} className="portal-form">
            <label className="a-label">Email</label>
            <input className="a-input" type="email" value={email} onChange={(e) => setEmail(e.target.value)} placeholder="you@school.edu" />
            <label className="a-label" style={{ marginTop: '0.8rem' }}>Institution</label>
            <input className="a-input" value={institution} onChange={(e) => setInstitution(e.target.value)} placeholder="e.g. Wycliffe College" />
            <label className="a-label" style={{ marginTop: '0.8rem' }}>Name (optional)</label>
            <input className="a-input" value={name} onChange={(e) => setName(e.target.value)} placeholder="how your tutors know you" />
            {error && <div className="dash-error" style={{ marginTop: '0.8rem' }}>{error}</div>}
            <button className="btn btn-primary a-cta" disabled={!email.trim() || !institution.trim() || busy} type="submit">
              {busy ? 'Signing in…' : 'Continue'}
            </button>
          </form>
          <button className="portal-guest-link" onClick={enterGuest}>Explore the demo instead →</button>
        </div>
      )}

      {(phase === 'live' || phase === 'guest') && voice && (
        <main className="portal-main">
          {phase === 'guest' && (
            <div className="portal-demo-banner">Demo data — sign in to see your own voice.</div>
          )}

          <section className="portal-hero">
            <h1 className="portal-h1">{voice.headline || 'Your voice.'}</h1>
            <p className="portal-lede">{voice.subhead || ''}</p>
          </section>

          <div className="portal-grid">
            <div className="portal-card">
              <h2 className="portal-h2">Voice fingerprint</h2>
              <p className="portal-quiet">The dimensions of how you write — not a grade, a portrait.</p>
              <VoiceRadar dims={voice.fingerprint || []} />
            </div>

            <div className="portal-card">
              <h2 className="portal-h2">The arc of your term</h2>
              <TermArc arc={voice.arc || []} />
              {(voice.arc || []).length === 0 && <p className="portal-quiet">Submit your first piece to reveal your arc.</p>}
            </div>
          </div>

          <div className="portal-card">
            <h2 className="portal-h2">Milestones</h2>
            <div className="portal-milestones">
              {(voice.milestones || []).map((m) => (
                <div className={'portal-milestone ' + m.state} key={m.label}>
                  <div className="pm-dot" />
                  <div>
                    <div className="pm-label">{m.label}</div>
                    <div className="pm-blurb">{m.blurb}</div>
                  </div>
                </div>
              ))}
            </div>
          </div>

          {voice.formation && voice.formation.active && (
            <div className="portal-card">
              <h2 className="portal-h2">Formation track</h2>
              <p className="portal-quiet">{voice.formation.supportive_copy || voice.formation.step_label}</p>
              <div className="portal-steps">
                {Array.from({ length: voice.formation.total_steps || 3 }, (_, i) => (
                  <div key={i} className={'portal-step' + (i < (voice.formation.current_step || 0) ? ' done' : '')} />
                ))}
              </div>
              {phase === 'live' && (
                <button className="btn btn-ghost" onClick={doAdvance} disabled={busy}>Mark next step complete</button>
              )}
            </div>
          )}

          {(voice.review_opportunities || []).length > 0 && (
            <div className="portal-card portal-invite">
              <h2 className="portal-h2">An invitation</h2>
              <p className="portal-lede">{voice.review_opportunities[0].invitation_prose}</p>
            </div>
          )}

          {(voice.voice_notes || []).length > 0 && (
            <div className="portal-card">
              <h2 className="portal-h2">Notes from your tutors</h2>
              {(voice.voice_notes || []).map((n, i) => (
                <blockquote className="portal-note" key={i}>
                  <p>{n.note}</p>
                  <footer>— {n.reviewer}{n.date ? `, ${n.date}` : ''}</footer>
                </blockquote>
              ))}
            </div>
          )}

          <div className="portal-card">
            <h2 className="portal-h2">Submit work</h2>
            <form onSubmit={doSubmitWork} className="portal-form">
              <label className="a-label">Title</label>
              <input className="a-input" value={workTitle} onChange={(e) => setWorkTitle(e.target.value)} placeholder="e.g. Week 9 Reflection" />
              <label className="a-label" style={{ marginTop: '0.8rem' }}>Your writing</label>
              <textarea className="a-textarea" value={workText} onChange={(e) => setWorkText(e.target.value)} placeholder="Paste or write here…" />
              <button className="btn btn-primary a-cta" disabled={busy || workText.trim().split(/\s+/).filter(Boolean).length < 20} type="submit">
                {busy ? 'Sending…' : 'Add to my record'}
              </button>
            </form>
            {workResult && (
              <div className="portal-work-result">
                <div className="pm-label">{workResult.headline}</div>
                <p className="portal-quiet">{workResult.summary}</p>
                {(workResult.steady || []).length > 0 && (
                  <ul className="portal-steady">
                    {workResult.steady.map((s, i) => <li key={i}>{s}</li>)}
                  </ul>
                )}
              </div>
            )}
          </div>

          {error && <div className="dash-error">{error}</div>}
        </main>
      )}
    </div>
  );
}

function VoiceRadar({ dims }) {
  const N = Math.max(dims.length, 3);
  const CX = 150, CY = 130, R = 92;
  const pt = (i, frac) => {
    const ang = (i / N) * 2 * Math.PI - Math.PI / 2;
    return [CX + Math.cos(ang) * R * frac, CY + Math.sin(ang) * R * frac];
  };
  if (!dims.length) return <p className="portal-quiet">Your fingerprint appears after your first submissions.</p>;
  const poly = dims.map((d, i) => pt(i, Math.max(0.05, d.value)).join(',')).join(' ');
  return (
    <svg viewBox="0 0 300 260" className="portal-radar">
      {[0.33, 0.66, 1].map((f) => (
        <polygon key={f} points={dims.map((_, i) => pt(i, f).join(',')).join(' ')} fill="none" stroke="var(--cream-border)" strokeWidth="1" />
      ))}
      {dims.map((d, i) => {
        const [x, y] = pt(i, 1.16);
        return <text key={d.name} x={x} y={y} textAnchor="middle" className="portal-radar-lbl">{d.name}</text>;
      })}
      <polygon points={poly} fill="rgba(201,160,40,0.16)" stroke="var(--gold)" strokeWidth="1.5" />
    </svg>
  );
}

function TermArc({ arc }) {
  if (!arc.length) return null;
  const W = 460, H = 130, PAD = 18;
  const x = (i) => PAD + (i / Math.max(1, arc.length - 1)) * (W - PAD * 2);
  const y = (f) => PAD + (1 - f / 100) * (H - PAD * 2);
  const line = arc.map((p, i) => `${x(i)},${y(p.fidelity)}`).join(' ');
  return (
    <svg viewBox={`0 0 ${W} ${H + 20}`} className="portal-arc">
      <polyline points={line} fill="none" stroke="var(--gold)" strokeWidth="2" strokeLinejoin="round" strokeLinecap="round" />
      {arc.map((p, i) => (
        <circle key={i} cx={x(i)} cy={y(p.fidelity)} r={p.attention ? 4.5 : 3}
                fill={p.attention ? 'var(--amber)' : 'var(--flag-green)'} />
      ))}
      {arc.map((p, i) => (
        <text key={'l' + i} x={x(i)} y={H + 12} textAnchor="middle" className="portal-radar-lbl">{p.period}</text>
      ))}
    </svg>
  );
}
