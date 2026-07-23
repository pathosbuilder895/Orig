// Settings.jsx — unlike every other page in this app, most of the Settings
// mockup (Security, Notifications, Detection, an editable Profile form) has
// NO backing endpoint anywhere in original/api.py: no password-change route,
// no per-user notification-preference storage, no per-user detection-toggle
// storage. Rather than wire a dozen toggles that silently do nothing on
// click, this page keeps the design's navigational shape but is honest
// section-by-section about what's real:
//
//   Profile      — real, auth-aware (GET /auth/me; 401s for the demo principal)
//   Display      — real: score-format is an actual saved preference (see
//                  util.js fmtScore) that changes every score in the app,
//                  not a decorative toggle
//   Institution  — real: GET /tenants (a genuine registry endpoint the design
//                  didn't even surface here — a bonus, not a mockup translation)
//   Privacy      — static, accurate text (no fake toggles)
//   Danger Zone  — shown but disabled; wiring live destructive actions from a
//                  settings mockup isn't something to do casually
//   Security / Notifications / Detection — honest "not yet available" stubs,
//                  same treatment as the Dashboard's Courses panel

import { useEffect, useState } from 'react';
import { getJSON, getJSONSafe } from './api.js';
import { Sidebar, Topbar, Icon } from './components.jsx';
import { fmtDate, fmtScore, SCORE_FORMAT_KEY } from './util.js';

const SECTIONS = [
  { id: 'profile', label: 'Profile', group: 'Account' },
  { id: 'display', label: 'Display', group: 'Preferences' },
  { id: 'institution', label: 'Institution', group: 'Institution' },
  { id: 'privacy', label: 'Privacy & Data', group: 'Detection' },
  { id: 'unavailable', label: 'Security & Notifications', group: 'Detection' },
  { id: 'danger', label: 'Danger Zone', group: 'Danger Zone' },
];

export function Settings() {
  const [active, setActive] = useState('profile');
  const [me, setMe] = useState(undefined); // undefined = loading, null = 401, object = real
  const [tenants, setTenants] = useState(null);
  const [pctFormat, setPctFormat] = useState(() => {
    try { return localStorage.getItem(SCORE_FORMAT_KEY) === '1'; } catch (e) { return false; }
  });

  useEffect(() => {
    let alive = true;
    getJSON('/auth/me').then((r) => alive && setMe(r)).catch(() => alive && setMe(null));
    getJSONSafe('/tenants').then((r) => alive && setTenants(r));
    return () => { alive = false; };
  }, []);

  function togglePct(v) {
    setPctFormat(v);
    try { localStorage.setItem(SCORE_FORMAT_KEY, v ? '1' : '0'); } catch (e) { /* unavailable */ }
  }

  const groups = [...new Set(SECTIONS.map((s) => s.group))];

  return (
    <>
      <Sidebar active="settings" />
      <div className="main">
        <Topbar crumb="Settings" semester="Live demo" />
        <div className="settings-shell">
          <div className="settings-nav">
            {groups.map((g) => (
              <div key={g}>
                <div className="settings-nav-section">{g}</div>
                {SECTIONS.filter((s) => s.group === g).map((s) => (
                  <a key={s.id} href={`#${s.id}`} className={'settings-nav-item' + (active === s.id ? ' active' : '')}
                     style={s.id === 'danger' ? { color: 'var(--flag-red)', opacity: 0.85 } : undefined}
                     onClick={(e) => { e.preventDefault(); setActive(s.id); }}>
                    {s.label}
                  </a>
                ))}
              </div>
            ))}
          </div>

          <div className="settings-content">
            {active === 'profile' && (
              <div className="settings-section">
                <div className="settings-section-title">Profile</div>
                <div className="settings-section-desc">Your identity as the API sees it — real, not editable here (no profile-update endpoint exists yet).</div>
                {me === undefined && <p style={{ color: 'var(--text-muted)', fontStyle: 'italic' }}>Loading…</p>}
                {me === null && (
                  <div className="baseline-hint bad" style={{ maxWidth: 480 }}>
                    Signed in as the <strong>zero-login demo principal</strong> — <code>GET /auth/me</code> returns 401
                    for demo sessions by design. Sign in with a real staff account to see role, tenant, and auth
                    method here.
                  </div>
                )}
                {me && (
                  <div className="profile-card">
                    <div className="profile-av-lg">{(me.user_id || '?').slice(0, 2).toUpperCase()}</div>
                    <div className="profile-av-info">
                      <div className="profile-av-name">{me.user_id}</div>
                      <div className="profile-av-email">{me.tenant_id} · {me.auth_method}</div>
                      <div className="profile-av-role">{me.role}</div>
                    </div>
                  </div>
                )}
              </div>
            )}

            {active === 'display' && (
              <div className="settings-section">
                <div className="settings-section-title">Display</div>
                <div className="settings-section-desc">One real, saved preference — changes how every deviation score renders across the whole app.</div>
                <div className="toggle-group" style={{ maxWidth: 480 }}>
                  <div className="select-row">
                    <div className="toggle-info">
                      <div className="toggle-name">Deviation score display</div>
                      <div className="toggle-desc">Decimal (0.91) or percentage (91%) — try it, then check Reports or Students</div>
                    </div>
                    <select className="select-compact" value={pctFormat ? 'pct' : 'dec'} onChange={(e) => togglePct(e.target.value === 'pct')}>
                      <option value="dec">Decimal (0.91)</option>
                      <option value="pct">Percentage (91%)</option>
                    </select>
                  </div>
                </div>
                <p style={{ marginTop: '1rem', fontFamily: "'EB Garamond',serif", fontStyle: 'italic', color: 'var(--text-muted)', fontSize: '0.85rem' }}>
                  Live preview — a deviation score of 0.913 currently renders as <strong style={{ color: 'var(--text-primary)', fontStyle: 'normal' }}>{fmtScore(0.913)}</strong>.
                </p>
              </div>
            )}

            {active === 'institution' && (
              <div className="settings-section" style={{ maxWidth: 720 }}>
                <div className="settings-section-title">Institution registry</div>
                <div className="settings-section-desc">Real tenants from GET /tenants — not in the original mockup, added because the endpoint already exists and is staff-readable.</div>
                {tenants === null && <p style={{ color: 'var(--text-muted)', fontStyle: 'italic' }}>Loading…</p>}
                {Array.isArray(tenants) && (
                  <div className="section-card">
                    <div className="student-head" style={{ gridTemplateColumns: '2fr 1fr 1fr' }}>
                      <div className="th">Institution</div>
                      <div className="th">Environment</div>
                      <div className="th right">Registered</div>
                    </div>
                    {tenants.map((t) => (
                      <div className="student-row" key={t.tenant_id} style={{ gridTemplateColumns: '2fr 1fr 1fr', cursor: 'default' }}>
                        <div>
                          <div className="s-name">{t.name}</div>
                          <div className="s-email">{t.tenant_id}</div>
                        </div>
                        <div className="td" style={{ textTransform: 'capitalize' }}>{t.environment}</div>
                        <div className="td right">{fmtDate(t.created_at)}</div>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            )}

            {active === 'privacy' && (
              <div className="settings-section">
                <div className="settings-section-title">Privacy &amp; Data</div>
                <div className="settings-section-desc">How Original handles student data. Informational — not editable toggles, since there's no per-user data-policy storage to back them.</div>
                <div style={{ padding: '1rem', background: 'var(--flag-green-bg)', border: '1px solid rgba(42,107,69,0.2)', borderRadius: 'var(--radius)', fontFamily: "'EB Garamond',serif", fontSize: '0.9rem', fontStyle: 'italic', color: 'var(--flag-green)', lineHeight: 1.6, maxWidth: 640 }}>
                  Original does not use student writing samples to train, fine-tune, or improve any external
                  machine-learning models. Stylometric analysis runs on-infrastructure under your institution's
                  data agreement.
                </div>
              </div>
            )}

            {active === 'unavailable' && (
              <div className="settings-section">
                <div className="settings-section-title">Security &amp; Notifications</div>
                <div className="settings-section-desc">Not yet available.</div>
                <div className="empty-state">
                  <p>There's no password-change endpoint, 2FA support, or per-user notification-preference storage
                    in the API yet. Building toggles here would just be decoration — same call as the Dashboard's
                    Courses panel.</p>
                </div>
              </div>
            )}

            {active === 'danger' && (
              <div className="settings-section">
                <div className="settings-section-title" style={{ color: 'var(--flag-red)' }}>Danger Zone</div>
                <div className="settings-section-desc">Destructive actions — shown for completeness, disabled here on purpose.</div>
                <div className="danger-zone">
                  <div className="danger-row">
                    <div>
                      <div className="danger-name">Reset baselines</div>
                      <div className="danger-desc">No scoped "reset my courses' baselines" endpoint exists — the real primitive is per-student deletion.</div>
                    </div>
                    <button className="btn btn-danger" disabled style={{ opacity: 0.4, cursor: 'not-allowed' }}>Reset baselines</button>
                  </div>
                  <div className="danger-row">
                    <div>
                      <div className="danger-name">Delete flag history</div>
                      <div className="danger-desc">Affects audit trails — not something to wire behind a settings-page click.</div>
                    </div>
                    <button className="btn btn-danger" disabled style={{ opacity: 0.4, cursor: 'not-allowed' }}>Delete history</button>
                  </div>
                  <div className="danger-row">
                    <div>
                      <div className="danger-name">Deactivate account</div>
                      <div className="danger-desc">Use the classic admin tools for real account and student-data deletion (FERPA-compliant, per-student).</div>
                    </div>
                    <a className="btn btn-ghost" href="/professor.html">Open classic view</a>
                  </div>
                </div>
              </div>
            )}
          </div>
        </div>
      </div>
    </>
  );
}
