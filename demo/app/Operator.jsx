// Operator.jsx — cross-school operator view, real endpoints only:
//   GET /tenants                 → institution registry
//   GET /tenants/{id}/stats      → per-tenant student/sample/submission counts,
//                                  last activity, action mix (bounded fan-out)
//   POST /tenants                → register a school (403/409 surfaced verbatim —
//                                  guarded on real deploys)
//   GET /admin/audit             → shared AuditTable
//
// Destructive bulk-delete stays in the classic operator console on purpose.

import { useEffect, useState } from 'react';
import { getJSONSafe, postJSON } from './api.js';
import { Sidebar, Topbar, SectionCard, AuditTable } from './components.jsx';
import { mapPool, fmtDate, humanize } from './util.js';

export function Operator() {
  const [tenants, setTenants] = useState(null);   // [{...tenant, stats}]
  const [audit, setAudit] = useState(null);
  const [regId, setRegId] = useState('');
  const [regName, setRegName] = useState('');
  const [regEnv, setRegEnv] = useState('demo');
  const [regMsg, setRegMsg] = useState(null);
  const [busy, setBusy] = useState(false);

  async function loadTenants() {
    const list = await getJSONSafe('/tenants');
    if (!Array.isArray(list)) { setTenants([]); return; }
    const stats = await mapPool(list, (t) => getJSONSafe(`/tenants/${encodeURIComponent(t.tenant_id)}/stats`), 6);
    setTenants(list.map((t, i) => ({ ...t, stats: stats[i] })));
  }

  useEffect(() => {
    let alive = true;
    loadTenants().then(() => {});
    getJSONSafe('/admin/audit?limit=50').then((r) => alive && setAudit(r));
    return () => { alive = false; };
  }, []);

  async function registerSchool(ev) {
    ev.preventDefault();
    if (!regId.trim() || !regName.trim() || busy) return;
    setBusy(true);
    setRegMsg(null);
    try {
      const r = await postJSON('/tenants', { tenant_id: regId.trim(), name: regName.trim(), environment: regEnv });
      setRegMsg({ ok: true, text: `Registered ${r.name} (${r.tenant_id}, ${r.environment}).` });
      setRegId(''); setRegName('');
      await loadTenants();
    } catch (e) {
      // 403 (guard token required) / 409 (demo-downgrade refusal) rendered verbatim
      setRegMsg({ ok: false, text: String(e.message || e) });
    } finally {
      setBusy(false);
    }
  }

  const totals = (tenants || []).reduce(
    (acc, t) => {
      const s = t.stats || {};
      acc.students += s.student_count || 0;
      acc.submissions += s.submission_count || 0;
      acc.samples += s.sample_count || 0;
      return acc;
    },
    { students: 0, submissions: 0, samples: 0 }
  );

  return (
    <>
      <Sidebar active="operator" />
      <div className="main">
        <Topbar crumb="Operator" semester="Live demo" />
        <div className="page-body">
          <div className="page-header">
            <div>
              <h1 className="page-title">Operator</h1>
              <p className="page-subtitle">Every institution at a glance — cross-tenant reads need an operator principal on real deploys</p>
            </div>
            <div className="page-actions">
              <a className="btn btn-ghost" href="/operator.html">Classic operator console</a>
            </div>
          </div>

          <div className="stats-row">
            <div className="stat-card stat-default">
              <div className="stat-label">Institutions</div>
              <div className="stat-value">{tenants ? tenants.length : '…'}</div>
              <div className="stat-meta">registered tenants</div>
            </div>
            <div className="stat-card stat-default">
              <div className="stat-label">Students</div>
              <div className="stat-value">{tenants ? totals.students : '…'}</div>
              <div className="stat-meta">summed across visible tenants</div>
            </div>
            <div className="stat-card stat-pending">
              <div className="stat-label">Submissions</div>
              <div className="stat-value">{tenants ? totals.submissions : '…'}</div>
              <div className="stat-meta">tenant-scoped manifests</div>
            </div>
            <div className="stat-card stat-clear">
              <div className="stat-label">Baseline Samples</div>
              <div className="stat-value">{tenants ? totals.samples : '…'}</div>
              <div className="stat-meta">summed across visible tenants</div>
            </div>
          </div>

          <SectionCard title="Institutions" titleMeta="per-tenant stats fetched with bounded concurrency">
            {!tenants && <div className="empty-state"><p>Loading tenants…</p></div>}
            {tenants && tenants.length === 0 && <div className="empty-state"><p>No tenants visible to this principal.</p></div>}
            <div className="tenant-grid">
              {(tenants || []).map((t) => {
                const s = t.stats;
                return (
                  <div className="tenant-card" key={t.tenant_id}>
                    <div className="tenant-head">
                      <div>
                        <div className="tenant-name">{t.name}</div>
                        <div className="tenant-id">{t.tenant_id}</div>
                      </div>
                      <span className={'baseline-pill ' + (t.environment === 'demo' ? 'building' : 'strong')}>
                        <span className="bp-dot" />{t.environment}
                      </span>
                    </div>
                    {s ? (
                      <>
                        <div className="tenant-stats">
                          <div><span className="ts-num">{s.student_count}</span><span className="ts-lbl">students</span></div>
                          <div><span className="ts-num">{s.sample_count}</span><span className="ts-lbl">samples</span></div>
                          <div><span className="ts-num">{s.submission_count}</span><span className="ts-lbl">scored</span></div>
                        </div>
                        <div className="tenant-foot">
                          <span>{s.last_active_at ? `last active ${fmtDate(s.last_active_at)}` : 'no activity yet'}</span>
                          {s.student_count > 0 && s.sample_count === 0 && (
                            <span className="tenant-warn">no baselines yet</span>
                          )}
                        </div>
                        {s.action_counts && Object.keys(s.action_counts).length > 0 && (
                          <div className="tenant-actions">
                            {Object.entries(s.action_counts).map(([a, n]) => (
                              <span key={a} className="flag-course-tag" style={{ textTransform: 'capitalize' }}>{humanize(a)} · {n}</span>
                            ))}
                          </div>
                        )}
                      </>
                    ) : (
                      <div className="tenant-foot"><span>stats unavailable to this principal</span></div>
                    )}
                  </div>
                );
              })}
            </div>
          </SectionCard>

          <div className="main-grid" style={{ gridTemplateColumns: '380px 1fr' }}>
            <SectionCard title="Register a school">
              <form onSubmit={registerSchool} className="analyze-form-body" style={{ paddingTop: '0.9rem' }}>
                <label className="a-label">Tenant slug</label>
                <input className="a-input" value={regId} onChange={(e) => setRegId(e.target.value)} placeholder="e.g. seminary-of-dallas" />
                <label className="a-label" style={{ marginTop: '0.8rem' }}>Institution name</label>
                <input className="a-input" value={regName} onChange={(e) => setRegName(e.target.value)} placeholder="Seminary of Dallas" />
                <label className="a-label" style={{ marginTop: '0.8rem' }}>Environment</label>
                <select className="a-select" value={regEnv} onChange={(e) => setRegEnv(e.target.value)}>
                  <option value="demo">demo</option>
                  <option value="pilot">pilot</option>
                  <option value="production">production</option>
                </select>
                <button className="btn btn-primary a-cta" disabled={!regId.trim() || !regName.trim() || busy} type="submit">
                  {busy ? 'Registering…' : 'Register'}
                </button>
                {regMsg && (
                  <div className={regMsg.ok ? 'baseline-hint ok' : 'dash-error'} style={{ marginTop: '0.8rem' }}>{regMsg.text}</div>
                )}
                <div className="extract-meta" style={{ marginTop: '0.8rem' }}>
                  Guarded on real deploys (X-Guard-Token) — a 403 here is the guard working.
                  Bulk data deletion lives only in the classic operator console.
                </div>
              </form>
            </SectionCard>

            <SectionCard title="Audit trail" titleMeta={audit ? `${audit.total} entries total` : ''}>
              <AuditTable items={audit ? audit.items : null} loading={!audit} />
            </SectionCard>
          </div>
        </div>
      </div>
    </>
  );
}
