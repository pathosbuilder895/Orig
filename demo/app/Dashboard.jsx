// Dashboard.jsx — the overview page, wired to the live Original API.
//
// Data sources (all real endpoints, verified against original/api.py + schemas.py):
//   GET /admin/health                     → student_count, total_submissions, flagged_count, avg_latency_ms
//   GET /students                         → { students: [ids] }
//   GET /students/{id}/readiness          → { verdict: "ready"|"developing"|"insufficient" }  (baseline coverage)
//   GET /admin/manifests?limit=6          → { items: [{student_id, divergence_score, action, created_at, flags[]}] }
//
// The Courses table is intentionally stubbed: the professor-facing app is
// student-centric today; there is no course-roster endpoint yet (see the note
// rendered in that panel). Everything else is live.

import { useEffect, useState } from 'react';
import { getJSONSafe } from './api.js';
import { Sidebar, Topbar, StatCard, SectionCard, Icon } from './components.jsx';

const FLAG_ACTIONS = new Set(['escalate', 'schedule_conversation']);

function fmtScore(v) {
  return v == null ? '—' : Number(v).toFixed(2);
}
function fmtDate(iso) {
  if (!iso) return '';
  const d = new Date(iso);
  if (isNaN(d)) return String(iso).slice(0, 10);
  return d.toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
}
function humanizeFlags(item) {
  const fs = (item.flags || []).map((f) => f.replace(/_/g, ' '));
  if (fs.length) return fs.join(' · ');
  if (item.length_regime) return `length: ${item.length_regime}`;
  return 'within baseline range';
}

// Bounded-concurrency map — avoids firing N simultaneous requests on load.
async function mapPool(items, fn, poolSize = 8) {
  const out = new Array(items.length);
  let i = 0;
  await Promise.all(
    Array.from({ length: Math.min(poolSize, items.length) }, async () => {
      while (i < items.length) { const idx = i++; out[idx] = await fn(items[idx]); }
    })
  );
  return out;
}

export function Dashboard() {
  const [state, setState] = useState({ loading: true, error: null, health: null, coverage: null, flags: [] });

  useEffect(() => {
    let alive = true;
    (async () => {
      // Fast path — stat totals + recent flags render as soon as they land.
      const [health, studentsResp, manifests] = await Promise.all([
        getJSONSafe('/admin/health'),
        getJSONSafe('/students'),
        getJSONSafe('/admin/manifests?limit=6'),
      ]);
      if (!alive) return;
      const flags = ((manifests && manifests.items) || [])
        .slice()
        .sort((a, b) => (b.divergence_score || 0) - (a.divergence_score || 0));
      setState((s) => ({ ...s, loading: false, health, flags }));

      // Baseline coverage — bounded fan-out over readiness. A backend aggregate
      // endpoint should replace this per-student walk at real class scale.
      const ids = (studentsResp && studentsResp.students) || [];
      if (ids.length) {
        const readi = await mapPool(ids, (id) => getJSONSafe(`/students/${encodeURIComponent(id)}/readiness`), 8);
        if (!alive) return;
        const ready = readi.filter((r) => r && r.verdict === 'ready').length;
        setState((s) => ({ ...s, coverage: { ready, total: ids.length, pct: Math.round((100 * ready) / ids.length) } }));
      }
    })().catch((e) => { if (alive) setState((s) => ({ ...s, loading: false, error: String(e) })); });
    return () => { alive = false; };
  }, []);

  const { loading, error, health, coverage, flags } = state;
  const flaggedCount = health ? health.flagged_count : undefined;

  const covClass = !coverage ? '' : coverage.pct >= 75 ? '' : coverage.pct >= 50 ? 'partial' : 'low';

  return (
    <>
      <Sidebar school="Pilot Institution" flaggedCount={flaggedCount} />

      <div className="main">
        <Topbar crumb="Dashboard" semester="Live demo" />

        <div className="page-body">
          <div className="page-header">
            <div>
              <h1 className="page-title">Dashboard</h1>
              <p className="page-subtitle">
                {loading ? 'Loading live data…' : error ? 'Live data unavailable' : 'Wired to the Original API'}
              </p>
            </div>
            <div className="page-actions">
              <a className="btn btn-ghost" href="/professor.html"><Icon name="upload" />Classic view</a>
              <button className="btn btn-primary"><Icon name="plus" />New Course</button>
            </div>
          </div>

          {error && (
            <div className="dash-error">
              Couldn’t reach the API: <code>{error}</code>. The dev server may be down, or these
              endpoints need a signed-in principal.
            </div>
          )}

          {/* Stat cards — live */}
          <div className="stats-row">
            <StatCard
              variant="default"
              label="Total Students"
              value={loading ? '…' : health ? health.student_count : '—'}
              meta={<>in the <strong>live store</strong></>}
            />
            <StatCard
              variant="flagged"
              label="Flagged"
              value={loading ? '…' : health ? health.flagged_count : '—'}
              meta={<><strong>escalate</strong> + schedule-conversation</>}
            />
            <StatCard
              variant="clear"
              label="Baseline Coverage"
              value={loading ? '…' : coverage ? coverage.pct : '—'}
              unit={coverage ? '%' : null}
              meta={coverage ? <><strong>{coverage.ready} of {coverage.total}</strong> ready to score</> : 'no roster'}
            />
            <StatCard
              variant="pending"
              label="Submissions"
              value={loading ? '…' : health ? health.total_submissions : '—'}
              meta={health && health.avg_latency_ms != null ? <>avg <strong>{health.avg_latency_ms} ms</strong> / score</> : 'scored to date'}
            />
          </div>

          {/* Import — the "Integrations" surface lives here + in Submissions,
              not as its own nav item. All three link into the wired flows. */}
          <SectionCard title="Import" titleMeta="bring work in from outside">
            <div className="import-row">
              <a className="import-card" href="submissions.html#import">
                <Icon name="upload" />
                <div>
                  <div className="sd-pipe-name">Upload files</div>
                  <div className="sd-pipe-meta">.txt / .docx / .pdf — analyze or batch into baselines</div>
                </div>
              </a>
              <a className="import-card" href="submissions.html?source=canvas">
                <Icon name="book" />
                <div>
                  <div className="sd-pipe-name">Canvas</div>
                  <div className="sd-pipe-meta">list a student's submissions, analyze or import</div>
                </div>
              </a>
              <a className="import-card" href="submissions.html#import">
                <Icon name="inbox" />
                <div>
                  <div className="sd-pipe-name">Turnitin CSV</div>
                  <div className="sd-pipe-meta">roster import — creates student records</div>
                </div>
              </a>
            </div>
          </SectionCard>

          <div className="main-grid">
            {/* Courses — the registry is real (bluebook_courses); it just isn't
                linked to students/submissions yet. See courses.html for the
                live list and the honest note on what's missing. */}
            <SectionCard title="Courses" action={<a className="section-action" href="courses.html">View registry →</a>}>
              <div className="empty-state">
                <p>
                  Course <em>rosters</em> (who's enrolled, who's flagged) aren't wired yet —
                  <span style={{ fontStyle: 'normal', color: 'var(--amber)' }}> bluebook_courses </span>
                  has no link to student/submission data in the schema today. The course
                  registry itself is real — see the full list.
                </p>
              </div>
            </SectionCard>

            {/* Recent Flags — live from the manifest audit log */}
            <SectionCard title="Recent Flags" action={<a className="section-action" href="flagged.html">Review all →</a>}>
              <div className="flag-panel">
                {loading && <div className="empty-state"><p>Loading recent submissions…</p></div>}
                {!loading && flags.length === 0 && (
                  <div className="empty-state"><p>No submissions recorded yet — score a paper in the classic view to populate this.</p></div>
                )}
                {!loading && flags.map((f, i) => {
                  const high = (f.divergence_score || 0) >= 0.85 || FLAG_ACTIONS.has(f.action);
                  return (
                    <a className="flag-item" href={`student.html?id=${encodeURIComponent(f.student_id)}`} key={f.submission_id || i}>
                      <div className="flag-item-top">
                        <span className="flag-student">{f.student_id || 'unknown'}</span>
                        <span className={'flag-score' + (high ? ' high' : '')}>{fmtScore(f.divergence_score)}</span>
                      </div>
                      <div className="flag-detail">{humanizeFlags(f)}</div>
                      <div className="flag-meta">
                        {f.action && <span className="flag-course-tag">{f.action.replace(/_/g, ' ')}</span>}
                        <span className="flag-date">{fmtDate(f.created_at)}</span>
                      </div>
                    </a>
                  );
                })}
              </div>
            </SectionCard>
          </div>
        </div>
      </div>
    </>
  );
}
