// Interference.jsx — Research: decompose the last analysis into per-feature
// constructive/destructive contributions (the original-decomposition.html
// design). Per-feature contributions are NOT stored server-side — the only
// honest source is the last score run in this browser tab, stashed by the
// Submissions page (saveLastScore). Without one: an empty state, not fakery.

import { useMemo, useState } from 'react';
import { Sidebar, Topbar, useStudentSelection, StudentPicker, SectionCard } from './components.jsx';
import { shortLabel, fmtScore, actionMeta, loadLastScore } from './util.js';
import { FEATURES, TIER_META } from './feature-names.js';

// Mirrors original/explainer.py's _delta_intensity so the prose here matches
// the language professors see elsewhere in the product.
function deltaPhrase(delta) {
  const a = Math.abs(delta);
  const intensity = a > 0.3 ? 'dramatically' : a > 0.15 ? 'notably' : a > 0.05 ? 'slightly' : 'marginally';
  return `${intensity} ${delta > 0 ? 'higher' : 'lower'} than this student's baseline`;
}

export function Interference() {
  const { students, studentId, setStudentId } = useStudentSelection();
  const [filter, setFilter] = useState('all');   // all | destr | constr
  const [tierFilter, setTierFilter] = useState('all');

  const stash = studentId ? loadLastScore(studentId) : null;
  const result = stash ? stash.result : null;

  const signals = useMemo(() => {
    if (!result) return [];
    const inter = result.interference || {};
    const all = [
      ...(inter.destructive_features || []),
      ...(inter.constructive_features || []),
    ];
    return all
      .map((f) => ({
        ...f,
        plain: (FEATURES[f.code] && FEATURES[f.code].plain) || f.name || f.code,
      }))
      .sort((a, b) => Math.abs(b.contribution) - Math.abs(a.contribution));
  }, [result]);

  const tiersPresent = useMemo(() => [...new Set(signals.map((s) => s.tier))].sort((a, b) => a - b), [signals]);

  const visible = signals.filter((s) => {
    if (filter === 'destr' && s.direction !== 'destructive') return false;
    if (filter === 'constr' && s.direction === 'destructive') return false;
    if (tierFilter !== 'all' && String(s.tier) !== tierFilter) return false;
    return true;
  });

  const maxAbs = Math.max(0.0001, ...signals.map((s) => Math.abs(s.contribution)));
  const nDestr = signals.filter((s) => s.direction === 'destructive').length;
  const nConstr = signals.length - nDestr;
  const cards = signals.filter((s) => s.direction === 'destructive').slice(0, 6);
  const am = result ? actionMeta(result.recommendation.action) : null;

  return (
    <>
      <Sidebar active="interference" />
      <div className="main">
        <Topbar crumb="Interference" semester="Live demo" />
        <div className="page-body">
          <div className="page-header">
            <div>
              <h1 className="page-title">Interference Analysis</h1>
              <p className="page-subtitle">
                {stash
                  ? `"${stash.assignment || 'Untitled analysis'}" · stashed ${new Date(stash.saved_at).toLocaleString()}`
                  : 'Per-feature decomposition of the most recent analysis in this tab'}
              </p>
            </div>
            <div className="page-actions">
              <StudentPicker students={students} studentId={studentId} onChange={setStudentId} shortLabelFn={shortLabel} />
            </div>
          </div>

          {!result && (
            <div className="section-card">
              <div className="empty-state">
                <h3>No analysis to decompose</h3>
                <p>
                  Per-feature contributions only exist for a scored submission and aren't stored
                  server-side. Run one in{' '}
                  <a href={`submissions.html?student=${encodeURIComponent(studentId)}`}>Submissions</a>{' '}
                  and come back — the tornado chart lights up from that result.
                </p>
              </div>
            </div>
          )}

          {result && (
            <>
              <div className="score-strip">
                <div className="score-metric">
                  <div className="sm-label">Deviation score</div>
                  <div className="sm-value">{fmtScore(result.authorship.deviation_score)}</div>
                </div>
                <div className="score-metric">
                  <div className="sm-label">Recommended action</div>
                  <div className={'sm-value sm-action ' + am.cls}>{am.label}</div>
                </div>
                <div className="score-metric">
                  <div className="sm-label">Authorship prob.</div>
                  <div className="sm-value">{fmtScore(result.authorship.authorship_probability)}</div>
                </div>
                <div className="score-metric">
                  <div className="sm-label">Destructive features</div>
                  <div className="sm-value" style={{ color: 'var(--flag-red)' }}>{nDestr}</div>
                </div>
                <div className="score-metric">
                  <div className="sm-label">Constructive features</div>
                  <div className="sm-value" style={{ color: 'var(--flag-green)' }}>{nConstr}</div>
                </div>
              </div>

              <SectionCard
                title="Feature interference decomposition"
                titleMeta={`${visible.length} of ${signals.length} shown`}
                action={
                  <div className="int-filters">
                    {[['all', `All ${signals.length}`], ['destr', 'Destructive'], ['constr', 'Constructive']].map(([k, label]) => (
                      <button key={k} className={'src-tab' + (filter === k ? ' active' : '')} onClick={() => setFilter(k)}>{label}</button>
                    ))}
                    <select className="select-compact" value={tierFilter} onChange={(e) => setTierFilter(e.target.value)}>
                      <option value="all">All tiers</option>
                      {tiersPresent.map((t) => <option key={t} value={String(t)}>T{t} · {TIER_META[String(t)]}</option>)}
                    </select>
                  </div>
                }
              >
                <div className="tornado">
                  {visible.map((s) => {
                    const destr = s.direction === 'destructive';
                    const frac = Math.abs(s.contribution) / maxAbs;
                    return (
                      <div className="tornado-row" key={s.code}>
                        <div className="tornado-label" title={s.plain}>
                          {s.name || s.code} <span className="tornado-tier">T{s.tier}</span>
                        </div>
                        <div className="tornado-track">
                          <div className="tornado-half left">
                            {destr && <div className="tornado-fill destr" style={{ width: `${Math.max(2, frac * 100)}%` }} />}
                          </div>
                          <div className="tornado-half right">
                            {!destr && <div className="tornado-fill constr" style={{ width: `${Math.max(2, frac * 100)}%` }} />}
                          </div>
                        </div>
                        <div className={'tornado-val ' + (destr ? 'destr' : 'constr')}>
                          {s.contribution >= 0 ? '+' : ''}{s.contribution.toFixed(4)}
                        </div>
                      </div>
                    );
                  })}
                  {visible.length === 0 && <div className="empty-state"><p>Nothing matches this filter.</p></div>}
                </div>
              </SectionCard>

              {cards.length > 0 && (
                <SectionCard title="Primary signals" titleMeta="most destructive features, in plain English">
                  <div className="signal-cards">
                    {cards.map((s) => (
                      <div className="signal-card" key={s.code}>
                        <div className="signal-card-name">{s.plain}</div>
                        <div className="signal-card-rows">
                          <div><span className="sc-lbl">Baseline</span><span className="sc-val">{s.baseline_value.toFixed(3)}</span></div>
                          <div><span className="sc-lbl">Submission</span><span className="sc-val">{s.submission_value.toFixed(3)}</span></div>
                          <div><span className="sc-lbl">Contribution</span><span className="sc-val" style={{ color: 'var(--flag-red)' }}>{s.contribution.toFixed(4)}</span></div>
                        </div>
                        <div className="signal-card-interp">{deltaPhrase(s.delta)}</div>
                      </div>
                    ))}
                  </div>
                </SectionCard>
              )}
            </>
          )}
        </div>
      </div>
    </>
  );
}
