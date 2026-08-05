// Reports.jsx — term-level analytics, wired to the live Original API.
//
// Data sources:
//   GET /admin/manifests/stats?since=&until=   → { total, by_action, by_flag, mean_divergence }
//   GET /admin/manifests?since=&until=&limit=  → raw items, bucketed client-side into
//                                                 the weekly trend + score-distribution charts
//                                                 (the API has no time-series or histogram
//                                                 endpoint, so this is the honest way to get
//                                                 both from real data without a new endpoint)
//
// "Baseline Coverage by Course" is omitted — same reason as the Dashboard's
// Courses panel: no course-roster concept exists in the API yet. "Email
// Summary" is omitted too (no backend for it). "Export PDF" is real: the
// browser's native print-to-PDF, which needs no backend at all.

import { useEffect, useMemo, useState } from 'react';
import { getJSONSafe } from './api.js';
import { Sidebar, Topbar, Icon } from './components.jsx';
import { fmtScore, fmtDate, shortLabel, humanize } from './util.js';

const RANGES = [
  { key: '7d', label: '7d', days: 7 },
  { key: '30d', label: '30d', days: 30 },
  { key: 'all', label: 'All time', days: null },
];

function isoDaysAgo(days) {
  const d = new Date(Date.now() - days * 86400000);
  return d.toISOString().slice(0, 10);
}

function weekKey(iso) {
  const d = new Date(iso);
  if (isNaN(d)) return 'unknown';
  const onejan = new Date(d.getFullYear(), 0, 1);
  const week = Math.ceil(((d - onejan) / 86400000 + onejan.getDay() + 1) / 7);
  return `${d.getFullYear()}-W${week}`;
}

const SCORE_BUCKETS = [
  { key: '0.0–0.2', min: 0, max: 0.2, color: 'var(--flag-green)' },
  { key: '0.2–0.4', min: 0.2, max: 0.4, color: 'var(--flag-green)' },
  { key: '0.4–0.6', min: 0.4, max: 0.6, color: 'var(--amber)' },
  { key: '0.6–0.8', min: 0.6, max: 0.8, color: 'var(--amber)' },
  { key: '0.8–1.0', min: 0.8, max: 1.01, color: 'var(--flag-red)' },
];

export function Reports() {
  const [range, setRange] = useState('30d');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [stats, setStats] = useState(null);
  const [items, setItems] = useState([]);

  useEffect(() => {
    let alive = true;
    setLoading(true);
    const r = RANGES.find((x) => x.key === range);
    const since = r.days ? isoDaysAgo(r.days) : '';
    const qs = since ? `?since=${since}` : '';
    const qs2 = since ? `since=${since}&` : '';
    Promise.all([
      getJSONSafe(`/admin/manifests/stats${qs}`),
      getJSONSafe(`/admin/manifests?${qs2}limit=1000`),
    ]).then(([s, m]) => {
      if (!alive) return;
      setStats(s);
      setItems((m && m.items) || []);
      setLoading(false);
      if (!s && !m) setError('Live data unavailable');
    });
    return () => { alive = false; };
  }, [range]);

  const weekly = useMemo(() => {
    const buckets = new Map();
    for (const m of items) {
      const wk = weekKey(m.created_at);
      const b = buckets.get(wk) || { week: wk, total: 0, flagged: 0 };
      b.total++;
      if (m.action === 'escalate' || m.action === 'schedule_conversation') b.flagged++;
      buckets.set(wk, b);
    }
    return [...buckets.values()].sort((a, b) => a.week.localeCompare(b.week)).slice(-10);
  }, [items]);

  const distribution = useMemo(() => {
    return SCORE_BUCKETS.map((b) => ({
      ...b,
      count: items.filter((m) => (m.divergence_score || 0) >= b.min && (m.divergence_score || 0) < b.max).length,
    }));
  }, [items]);

  const flagCounts = useMemo(() => {
    const by = (stats && stats.by_flag) || {};
    return Object.entries(by).sort((a, b) => b[1] - a[1]).slice(0, 8);
  }, [stats]);

  const outcomes = useMemo(() => items.slice().sort((a, b) => (b.created_at || '').localeCompare(a.created_at || '')).slice(0, 15), [items]);

  const total = stats ? stats.total : items.length;
  const flaggedTotal = (stats && stats.by_action && ((stats.by_action.escalate || 0) + (stats.by_action.schedule_conversation || 0))) || 0;
  const flagRate = total ? Math.round((1000 * flaggedTotal) / total) / 10 : 0;
  const clearCount = (stats && stats.by_action && stats.by_action.no_action) || 0;
  const clearRate = total ? Math.round((1000 * clearCount) / total) / 10 : 0;
  const escalated = (stats && stats.by_action && stats.by_action.escalate) || 0;
  const maxWeekly = Math.max(1, ...weekly.map((w) => w.total));
  const maxDist = Math.max(1, ...distribution.map((d) => d.count));
  const maxFlag = Math.max(1, ...flagCounts.map(([, c]) => c));

  return (
    <>
      <Sidebar active="reports" />
      <div className="main">
        <Topbar crumb="Reports" semester="Live demo" />
        <div className="page-body">
          <div className="page-header">
            <div>
              <h1 className="page-title">Reports</h1>
              <p className="page-subtitle">{loading ? 'Loading…' : error || `${total} submissions in range`}</p>
            </div>
            <div className="page-actions">
              <div className="range-tabs">
                {RANGES.map((r) => (
                  <button key={r.key} className={'range-tab' + (range === r.key ? ' active' : '')} onClick={() => setRange(r.key)}>{r.label}</button>
                ))}
              </div>
              <button className="btn btn-ghost" onClick={() => window.print()}><Icon name="upload" />Export PDF</button>
            </div>
          </div>

          <div className="stats-row">
            <StatMini variant="default" label="Submissions Analyzed" value={loading ? '…' : total} />
            <StatMini variant="flagged" label="Flag Rate" value={loading ? '…' : `${flagRate}%`} meta={`${flaggedTotal} of ${total}`} />
            <StatMini variant="clear" label="Clear Rate" value={loading ? '…' : `${clearRate}%`} meta={`${clearCount} no-action`} />
            <StatMini variant="pending" label="Escalated" value={loading ? '…' : escalated} meta={stats && stats.mean_divergence != null ? `mean deviation ${fmtScore(stats.mean_divergence)}` : ''} />
          </div>

          <div className="chart-grid">
            <div className="chart-card">
              <div className="chart-head"><span className="chart-title">Deviation Flags Over Time</span><span className="chart-meta">weekly · {weekly.length} weeks</span></div>
              <div className="chart-body">
                {weekly.length === 0 && <p style={{ fontStyle: 'italic', color: 'var(--text-muted)', fontSize: '0.85rem' }}>No submissions in this range yet.</p>}
                {weekly.length > 0 && (
                  <div className="bar-chart">
                    {weekly.map((w) => (
                      <div className="bar-col" key={w.week} title={`${w.week}: ${w.total} submissions, ${w.flagged} flagged`}>
                        <div className="bar-col-track">
                          <div className="bar-col-fill" style={{ height: `${Math.round((100 * w.total) / maxWeekly)}%`, background: w.flagged > 0 ? 'var(--flag-red)' : 'var(--flag-green)', opacity: w.flagged > 0 ? 0.55 + 0.45 * (w.flagged / w.total) : 0.55 }} />
                        </div>
                        <div className="bar-col-label">{w.week.replace(/^\d+-W/, 'W')}</div>
                      </div>
                    ))}
                  </div>
                )}
                <div style={{ fontFamily: "'EB Garamond',serif", fontSize: '0.78rem', fontStyle: 'italic', color: 'var(--text-muted)', marginTop: '0.5rem' }}>
                  Bar height = submissions that week; red tint = share flagged.
                </div>
              </div>
            </div>

            <div className="chart-card">
              <div className="chart-head"><span className="chart-title">Score Distribution</span><span className="chart-meta">all {total} submissions</span></div>
              <div className="chart-body">
                <div className="bar-chart">
                  {distribution.map((d) => (
                    <div className="bar-col" key={d.key} title={`${d.key}: ${d.count} submissions`}>
                      <div className="bar-col-track">
                        <div className="bar-col-fill" style={{ height: `${Math.round((100 * d.count) / maxDist)}%`, background: d.color }} />
                      </div>
                      <div className="bar-col-label">{d.key}</div>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          </div>

          <div className="chart-grid">
            <div className="chart-card">
              <div className="chart-head"><span className="chart-title">Baseline Coverage by Course</span></div>
              <div className="empty-state">
                <p>Course rosters aren't a first-class entity in the API yet — see the Dashboard's Courses panel for the same note. This chart lights up once that backend piece exists.</p>
              </div>
            </div>

            <div className="chart-card">
              <div className="chart-head"><span className="chart-title">Most-Triggered Flags</span><span className="chart-meta">from /admin/manifests/stats</span></div>
              <div className="tier-bars" style={{ padding: '0.6rem 1.4rem 1rem' }}>
                {flagCounts.length === 0 && <p style={{ fontStyle: 'italic', color: 'var(--text-muted)', fontSize: '0.85rem' }}>No flags recorded in this range.</p>}
                {flagCounts.map(([flag, count]) => (
                  <div className="tier-bar-row" key={flag}>
                    <div className="tier-bar-label">{humanize(flag)}</div>
                    <div className="tier-bar-track"><div className="tier-bar-fill" style={{ width: `${Math.round((100 * count) / maxFlag)}%` }} /></div>
                    <div className="tier-bar-val">{count}</div>
                  </div>
                ))}
              </div>
            </div>
          </div>

          <div className="chart-card-full">
            <div className="chart-head"><span className="chart-title">Decision Outcomes</span><span className="chart-meta">{outcomes.length} most recent</span></div>
            <div className="outcomes-table">
              <div className="outcomes-head">
                <div className="th">Student</div>
                <div className="th">Submission</div>
                <div className="th center">Score</div>
                <div className="th center">Outcome</div>
                <div className="th right">Date</div>
              </div>
              {!loading && outcomes.length === 0 && <div className="empty-state"><p>No submissions in this range.</p></div>}
              {outcomes.map((m) => (
                <a className="outcomes-row" href={`student.html?id=${encodeURIComponent(m.student_id)}`} key={m.submission_id}>
                  <div className="td" style={{ fontWeight: 500, color: 'var(--text-primary)', textTransform: 'capitalize' }}>{shortLabel(m.student_id)}</div>
                  <div className="td">{m.submission_id || '—'}</div>
                  <div className="td center" style={{ fontWeight: 600, color: (m.divergence_score || 0) >= 0.7 ? 'var(--flag-red)' : 'var(--text-secondary)' }}>{fmtScore(m.divergence_score)}</div>
                  <div className="td center"><OutcomePill action={m.action} /></div>
                  <div className="td right">{fmtDate(m.created_at)}</div>
                </a>
              ))}
            </div>
          </div>
        </div>
      </div>
    </>
  );
}

function StatMini({ variant, label, value, meta }) {
  return (
    <div className={'stat-card stat-' + variant}>
      <div className="stat-label">{label}</div>
      <div className="stat-value">{value}</div>
      {meta && <div className="stat-meta">{meta}</div>}
    </div>
  );
}

const OUTCOME_LABEL = {
  escalate: { label: 'Escalated', cls: 'escalated' },
  schedule_conversation: { label: 'Monitoring', cls: 'monitoring' },
  monitor: { label: 'Monitoring', cls: 'monitoring' },
  no_action: { label: 'Cleared', cls: 'cleared' },
};
function OutcomePill({ action }) {
  const o = OUTCOME_LABEL[action] || { label: humanize(action) || 'Pending', cls: 'pending' };
  return <span className={'outcome-pill ' + o.cls}>{o.label}</span>;
}
