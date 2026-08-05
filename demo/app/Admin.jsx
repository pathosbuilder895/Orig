// Admin.jsx — institution admin console, real endpoints only:
//   GET /admin/health           → system health incl. backups + latency
//   GET /admin/manifests/stats  → submission roll-ups (by_action, mean divergence)
//   GET /admin/audit            → recent audit trail (shared AuditTable)
//   GET /admin/tuned-thresholds → active calibrated thresholds (read-only)
//
// The design's Instructors / Courses / LTI-registration tables have no live
// backend behind them — omitted with a note rather than rendered as fiction.
// Destructive operations stay in the classic admin console.

import { useEffect, useState } from 'react';
import { getJSONSafe } from './api.js';
import { Sidebar, Topbar, SectionCard, AuditTable } from './components.jsx';
import { fmtScore, humanize } from './util.js';

function ago(seconds) {
  if (seconds == null) return null;
  if (seconds < 90) return `${Math.round(seconds)}s ago`;
  if (seconds < 5400) return `${Math.round(seconds / 60)}m ago`;
  return `${(seconds / 3600).toFixed(1)}h ago`;
}

export function Admin() {
  const [health, setHealth] = useState(null);
  const [stats, setStats] = useState(null);
  const [audit, setAudit] = useState(null);
  const [thresholds, setThresholds] = useState(undefined); // undefined=loading, null=none set

  useEffect(() => {
    let alive = true;
    getJSONSafe('/admin/health').then((r) => alive && setHealth(r));
    getJSONSafe('/admin/manifests/stats').then((r) => alive && setStats(r));
    getJSONSafe('/admin/audit?limit=50').then((r) => alive && setAudit(r));
    getJSONSafe('/admin/tuned-thresholds').then((r) => alive && setThresholds(r));
    return () => { alive = false; };
  }, []);

  const byAction = (stats && stats.by_action) || {};

  return (
    <>
      <Sidebar active="admin" flaggedCount={health ? health.flagged_count : undefined} />
      <div className="main">
        <Topbar crumb="Admin" semester="Live demo" />
        <div className="page-body">
          <div className="page-header">
            <div>
              <h1 className="page-title">Institution Admin</h1>
              <p className="page-subtitle">System health, submission roll-ups, thresholds, and the audit trail</p>
            </div>
            <div className="page-actions">
              <a className="btn btn-ghost" href="/admin.html">Classic admin console</a>
            </div>
          </div>

          {/* KPI row */}
          <div className="stats-row">
            <div className="stat-card stat-default">
              <div className="stat-label">Students</div>
              <div className="stat-value">{health ? health.student_count : '…'}</div>
              <div className="stat-meta">in the live store</div>
            </div>
            <div className="stat-card stat-pending">
              <div className="stat-label">Submissions Scored</div>
              <div className="stat-value">{health ? health.total_submissions : '…'}</div>
              <div className="stat-meta">{stats && stats.mean_divergence != null ? <>mean deviation <strong>{fmtScore(stats.mean_divergence)}</strong></> : 'all time'}</div>
            </div>
            <div className="stat-card stat-flagged">
              <div className="stat-label">Flagged</div>
              <div className="stat-value">{health ? health.flagged_count : '…'}</div>
              <div className="stat-meta"><strong>escalate</strong> + schedule-conversation</div>
            </div>
            <div className="stat-card stat-clear">
              <div className="stat-label">Cleared</div>
              <div className="stat-value">{byAction.no_action ?? '…'}</div>
              <div className="stat-meta">no-action outcomes</div>
            </div>
          </div>

          <div className="main-grid" style={{ gridTemplateColumns: '1fr 1fr' }}>
            {/* System health */}
            <SectionCard title="System health" titleMeta="from /admin/health">
              {!health && <div className="empty-state"><p>Loading…</p></div>}
              {health && (
                <div className="health-list">
                  <div className="health-row">
                    <span className={'health-dot ' + (health.api_status === 'operational' ? 'ok' : 'bad')} />
                    <span className="health-name">API</span>
                    <span className="health-val" style={{ textTransform: 'capitalize' }}>{health.api_status}</span>
                  </div>
                  <div className="health-row">
                    <span className={'health-dot ' + (health.avg_latency_ms == null || health.avg_latency_ms < 2000 ? 'ok' : 'warn')} />
                    <span className="health-name">Avg scoring latency</span>
                    <span className="health-val">{health.avg_latency_ms == null ? 'n/a yet' : `${health.avg_latency_ms} ms`}</span>
                  </div>
                  <div className="health-row">
                    <span className="health-dot ok" />
                    <span className="health-name">Queue depth</span>
                    <span className="health-val">{health.queue_depth} (synchronous demo server)</span>
                  </div>
                  <div className="health-row">
                    <span className={'health-dot ' + (health.backups_enabled ? 'ok' : 'warn')} />
                    <span className="health-name">Backups</span>
                    <span className="health-val">
                      {health.backups_enabled
                        ? `enabled${health.last_backup_age_seconds != null ? ` · last ${ago(health.last_backup_age_seconds)}` : ' · none yet'}`
                        : 'disabled (demo)'}
                    </span>
                  </div>
                </div>
              )}
            </SectionCard>

            {/* Outcome mix + thresholds */}
            <div style={{ display: 'flex', flexDirection: 'column', gap: '1.5rem' }}>
              <SectionCard title="Outcome mix" titleMeta="all scored submissions">
                <div className="tier-bars" style={{ padding: '0.8rem 1.4rem 1.1rem' }}>
                  {['no_action', 'monitor', 'schedule_conversation', 'escalate'].map((a) => {
                    const n = byAction[a] || 0;
                    const total = Math.max(1, stats ? stats.total : 1);
                    return (
                      <div className="tier-bar-row" key={a}>
                        <div className="tier-bar-label" style={{ textTransform: 'capitalize' }}>{humanize(a)}</div>
                        <div className="tier-bar-track"><div className="tier-bar-fill" style={{ width: `${Math.round((100 * n) / total)}%` }} /></div>
                        <div className="tier-bar-val">{n}</div>
                      </div>
                    );
                  })}
                </div>
              </SectionCard>

              <SectionCard title="Detection thresholds" titleMeta="read-only — tuned in the Calibration Lab">
                {thresholds === undefined && <div className="empty-state"><p>Loading…</p></div>}
                {thresholds === null && (
                  <div className="empty-state"><p>No tuned thresholds applied — factory defaults in effect. Run a calibration in the classic Lab to tune them.</p></div>
                )}
                {thresholds && (
                  <div className="threshold-list">
                    <div><span className="th-lbl">no action below</span><span className="th-val">{thresholds.no_action}</span></div>
                    <div><span className="th-lbl">monitor from</span><span className="th-val">{thresholds.monitor}</span></div>
                    <div><span className="th-lbl">escalate from</span><span className="th-val">{thresholds.escalate}</span></div>
                    <div className="th-meta">applied {String(thresholds.created_at).slice(0, 10)} · source: {thresholds.source}{thresholds.notes ? ` · ${thresholds.notes}` : ''}</div>
                  </div>
                )}
              </SectionCard>
            </div>
          </div>

          <SectionCard title="Recent activity" titleMeta={audit ? `${audit.total} audit entries total` : ''}>
            <AuditTable items={audit ? audit.items : null} loading={!audit} />
          </SectionCard>

          <div className="extract-meta" style={{ marginTop: '0.4rem' }}>
            Instructor accounts, course tables, and LTI registrations are managed in the classic
            console — no live endpoints exist for them here yet, so this page doesn't pretend to.
          </div>
        </div>
      </div>
    </>
  );
}
