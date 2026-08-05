// Students.jsx — full roster, wired to the live Original API.
//
// Data sources:
//   GET /students                    → { students: [ids], roster: [...] | null }
//     roster is populated server-side only for a tenant-scoped, non-demo
//     principal (see original/api.py list_students). The zero-login demo
//     gets ids only, so this page falls back to a bounded per-student walk.
//   GET /students/{id}                → sample_count, authenticated_count, effective_sample_count
//   GET /admin/manifests?limit=300    → recent submissions, used to derive each
//                                        student's latest score + activity date
//
// Course and email columns from the mockup are omitted — the API has no
// course-roster or contact-info concept yet (same honesty rule as the
// Dashboard's Courses panel, not silently faked).

import { useEffect, useMemo, useState } from 'react';
import { getJSONSafe } from './api.js';
import { Sidebar, Topbar, Icon } from './components.jsx';
import { mapPool, fmtScore, fmtDate, verdictFor, shortLabel, initials } from './util.js';

const VERDICT_LABEL = { ready: 'Strong', developing: 'Building', insufficient: 'Not set' };
const VERDICT_CLASS = { ready: 'strong', developing: 'building', insufficient: 'none' };

function devClass(v) {
  if (v == null) return 'none';
  if (v >= 0.7) return 'high';
  if (v >= 0.4) return 'mid';
  return 'low';
}

export function Students() {
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [rows, setRows] = useState([]);
  const [loadedCount, setLoadedCount] = useState(0);
  const [totalCount, setTotalCount] = useState(0);
  const [query, setQuery] = useState('');
  const [filter, setFilter] = useState('all');
  const [sortBy, setSortBy] = useState('name');

  useEffect(() => {
    let alive = true;
    (async () => {
      const studentsResp = await getJSONSafe('/students');
      if (!alive) return;
      const ids = (studentsResp && studentsResp.students) || [];
      const roster = studentsResp && studentsResp.roster;
      setTotalCount(ids.length);

      // Latest manifest per student (score + last-activity date).
      const manifestsP = getJSONSafe('/admin/manifests?limit=300');

      let baseRows;
      if (Array.isArray(roster) && roster.length) {
        // Fast path: server already returned display-ready rows.
        baseRows = roster.map((r) => ({
          id: r.id, name: r.name || shortLabel(r.id),
          sample_count: r.sample_count, authenticated_count: r.authenticated_count,
          effective_sample_count: r.authenticated_count, // server 'status' governs display when present
        }));
        setLoadedCount(baseRows.length);
      } else {
        // Demo fallback: bounded per-student walk.
        baseRows = [];
        await mapPool(ids, async (id) => {
          const s = await getJSONSafe(`/students/${encodeURIComponent(id)}`);
          if (alive) setLoadedCount((n) => n + 1);
          if (s) baseRows.push({ id, ...s });
        }, 10);
      }

      const manifests = await manifestsP;
      const latestByStudent = new Map();
      for (const item of (manifests && manifests.items) || []) {
        const prev = latestByStudent.get(item.student_id);
        if (!prev || (item.created_at || '') > (prev.created_at || '')) latestByStudent.set(item.student_id, item);
      }

      const merged = baseRows.map((r) => {
        const latest = latestByStudent.get(r.id);
        return {
          ...r,
          verdict: verdictFor(r),
          latestScore: latest ? latest.divergence_score : null,
          latestAction: latest ? latest.action : null,
          lastActivity: latest ? latest.created_at : null,
        };
      });

      if (!alive) return;
      setRows(merged);
      setLoading(false);
    })().catch((e) => { if (alive) { setError(String(e)); setLoading(false); } });
    return () => { alive = false; };
  }, []);

  const summary = useMemo(() => {
    const s = { total: rows.length, ready: 0, developing: 0, insufficient: 0, flagged: 0 };
    for (const r of rows) {
      s[r.verdict] = (s[r.verdict] || 0) + 1;
      if (r.latestAction === 'escalate' || r.latestAction === 'schedule_conversation') s.flagged++;
    }
    return s;
  }, [rows]);

  const visible = useMemo(() => {
    let out = rows;
    if (filter === 'flagged') out = out.filter((r) => r.latestAction === 'escalate' || r.latestAction === 'schedule_conversation');
    else if (filter === 'no-baseline') out = out.filter((r) => r.verdict === 'insufficient');
    else if (filter === 'building') out = out.filter((r) => r.verdict === 'developing');
    else if (filter === 'clear') out = out.filter((r) => r.verdict === 'ready' && r.latestAction !== 'escalate' && r.latestAction !== 'schedule_conversation');

    const q = query.trim().toLowerCase();
    if (q) out = out.filter((r) => r.id.toLowerCase().includes(q) || shortLabel(r.id).toLowerCase().includes(q));

    out = out.slice().sort((a, b) => {
      if (sortBy === 'deviation') return (b.latestScore || -1) - (a.latestScore || -1);
      if (sortBy === 'samples') return (b.sample_count || 0) - (a.sample_count || 0);
      if (sortBy === 'recent') return (b.lastActivity || '').localeCompare(a.lastActivity || '');
      return shortLabel(a.id).localeCompare(shortLabel(b.id));
    });
    return out;
  }, [rows, filter, query, sortBy]);

  return (
    <>
      <Sidebar active="students" flaggedCount={summary.flagged || undefined} />
      <div className="main">
        <Topbar crumb="Students" semester="Live demo" />
        <div className="page-body" style={{ padding: 0 }}>

          <div className="sticky-head">
            <div className="page-header-row">
              <div>
                <h1 className="page-title">Students <span>{loading ? '…' : rows.length}</span></h1>
                <p className="page-subtitle">
                  {loading
                    ? `Loading roster… ${loadedCount}/${totalCount || '?'}`
                    : error ? 'Live data unavailable'
                    : rows.length < totalCount ? `Wired to the Original API · ${totalCount - rows.length} not visible to this principal`
                    : 'Wired to the Original API'}
                </p>
              </div>
              <div className="header-actions">
                <a className="btn btn-ghost" href="/professor.html"><Icon name="eye" />Classic view</a>
              </div>
            </div>

            <div className="toolbar">
              <div className="search-box">
                <Icon name="search" />
                <input placeholder="Search by student id…" value={query} onChange={(e) => setQuery(e.target.value)} />
              </div>
              <div className="filter-sep" />
              {[
                ['all', 'All'], ['flagged', '⚑ Flagged'], ['building', 'Building'],
                ['no-baseline', 'No baseline'], ['clear', 'Clear'],
              ].map(([key, label]) => (
                <div key={key} className={'filter-chip' + (filter === key ? ' active' : '') + (key === 'flagged' ? ' fc-red' : key === 'clear' ? ' fc-green' : '')}
                     onClick={() => setFilter(key)}>{label}</div>
              ))}
              <select className="sort-select" value={sortBy} onChange={(e) => setSortBy(e.target.value)}>
                <option value="name">Sort: Name A–Z</option>
                <option value="deviation">Sort: Deviation ↓</option>
                <option value="samples">Sort: Samples ↓</option>
                <option value="recent">Sort: Last active</option>
              </select>
            </div>
          </div>

          <div className="table-wrap">
            <div className="section-card">
              <div className="summary-strip">
                <div className="strip-stat"><div className="strip-label">Total</div><div className="strip-value">{summary.total}</div></div>
                <div className="strip-stat"><div className="strip-label">Baseline established</div><div className="strip-value green">{summary.ready || 0}</div></div>
                <div className="strip-stat"><div className="strip-label">Building baseline</div><div className="strip-value amber">{summary.developing || 0}</div></div>
                <div className="strip-stat"><div className="strip-label">No baseline</div><div className="strip-value red">{summary.insufficient || 0}</div></div>
                <div className="strip-stat"><div className="strip-label">Currently flagged</div><div className="strip-value amber">{summary.flagged || 0}</div></div>
              </div>

              <div className="student-head" style={{ gridTemplateColumns: '2.2fr 90px 120px 110px 90px 48px' }}>
                <div className="th sorted">Student</div>
                <div className="th center">Samples</div>
                <div className="th">Baseline</div>
                <div className="th">Latest score</div>
                <div className="th right">Last active</div>
                <div className="th" />
              </div>

              {!loading && visible.length === 0 && (
                <div className="empty-state"><h3>No students match</h3><p>Try a different search or filter.</p></div>
              )}

              {visible.map((r) => (
                <a key={r.id} className={'student-row' + (r.latestAction === 'escalate' ? ' flagged-row' : r.latestAction === 'schedule_conversation' ? ' watch-row' : '')}
                   href={`student.html?id=${encodeURIComponent(r.id)}`} style={{ gridTemplateColumns: '2.2fr 90px 120px 110px 90px 48px' }}>
                  <div className="student-ident">
                    <div className={'s-avatar' + (r.latestAction === 'escalate' ? ' av-red' : r.latestAction === 'schedule_conversation' ? ' av-amber' : '')}>{initials(r.id)}</div>
                    <div>
                      <div className="s-name" style={{ textTransform: 'capitalize' }}>{shortLabel(r.id)}</div>
                      <div className="s-email">{r.id}</div>
                    </div>
                  </div>
                  <div className="td center">{r.sample_count ?? '—'}</div>
                  <div className="td">
                    <span className={'baseline-pill ' + VERDICT_CLASS[r.verdict]}>
                      <span className="bp-dot" />{VERDICT_LABEL[r.verdict]}
                    </span>
                  </div>
                  <div className="td">
                    <div className="dev-cell">
                      <div className="dev-bar"><div className={'dev-fill ' + devClass(r.latestScore)} style={{ width: `${Math.round((r.latestScore || 0) * 100)}%` }} /></div>
                      <span className={'dev-num ' + devClass(r.latestScore)}>{fmtScore(r.latestScore)}</span>
                    </div>
                  </div>
                  <div className="td right" style={{ fontFamily: "'EB Garamond',serif", fontStyle: 'italic', color: 'var(--text-muted)', fontSize: '0.78rem' }}>
                    {fmtDate(r.lastActivity)}
                  </div>
                  <div className="td">
                    <span className="row-action"><Icon name="eye" /></span>
                  </div>
                </a>
              ))}
            </div>
          </div>
        </div>
      </div>
    </>
  );
}
