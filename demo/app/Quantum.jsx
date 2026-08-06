// Quantum.jsx — Research: the student's quantum baseline state, all real:
//   purity Tr(ρ²) and normalized von Neumann entropy S = −Tr(ρ log ρ)/log(D)
//   from GET /students/{id} (entropy exposure added alongside this page),
//   readiness verdict from /readiness, the 103-dim baseline mean vector as a
//   state heatmap (with the last-analysis submission vector overlaid when
//   stashed), client-computed tier averages as a radar, and the real sample
//   timeline with per-sample trust weights.
//
// Honesty note rendered on-page: the heatmap shows the baseline MEAN vector
// (what the API exposes), not ρ itself — ρ never leaves the server.

import { useEffect, useState } from 'react';
import { getJSON, getJSONSafe } from './api.js';
import { Sidebar, Topbar, useStudentSelection, StudentPicker, SectionCard } from './components.jsx';
import { shortLabel, fmtScore, fmtDate, humanize, loadLastScore } from './util.js';
import { FEATURES, CODES, tierAverages } from './feature-names.js';

function PurityRing({ purity }) {
  const R = 52, C = 2 * Math.PI * R;
  const frac = Math.max(0, Math.min(1, purity || 0));
  return (
    <svg viewBox="0 0 140 140" className="purity-ring">
      <circle cx="70" cy="70" r={R} fill="none" stroke="var(--cream-border)" strokeWidth="10" />
      <circle cx="70" cy="70" r={R} fill="none" stroke="var(--gold)" strokeWidth="10" strokeLinecap="round"
              strokeDasharray={`${C * frac} ${C}`} transform="rotate(-90 70 70)" />
      <text x="70" y="66" textAnchor="middle" className="purity-ring-num">{fmtScore(purity)}</text>
      <text x="70" y="86" textAnchor="middle" className="purity-ring-lbl">Tr(ρ²)</text>
    </svg>
  );
}

function TierRadar({ averages }) {
  // 17 spokes (tiers 1-17); comparison meta-features (tier 0) excluded.
  const spokes = averages.filter((a) => a.tier !== 0);
  const N = spokes.length;
  const CX = 130, CY = 120, R = 92;
  const pt = (i, frac) => {
    const ang = (i / N) * 2 * Math.PI - Math.PI / 2;
    return [CX + Math.cos(ang) * R * frac, CY + Math.sin(ang) * R * frac];
  };
  const poly = spokes.map((s, i) => pt(i, Math.max(0.04, s.avg ?? 0)).join(',')).join(' ');
  return (
    <svg viewBox="0 0 260 240" className="tier-radar">
      {[0.25, 0.5, 0.75, 1].map((f) => (
        <polygon key={f} points={spokes.map((_, i) => pt(i, f).join(',')).join(' ')}
                 fill="none" stroke="var(--cream-border)" strokeWidth="1" />
      ))}
      {spokes.map((s, i) => {
        const [x, y] = pt(i, 1.08);
        return <text key={s.tier} x={x} y={y} textAnchor="middle" className="tier-radar-lbl">T{s.tier}</text>;
      })}
      <polygon points={poly} fill="rgba(201,160,40,0.18)" stroke="var(--gold)" strokeWidth="1.5" />
    </svg>
  );
}

export function Quantum() {
  const { students, studentId, setStudentId } = useStudentSelection();
  const [state, setState] = useState(null);
  const [readiness, setReadiness] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    if (!studentId) return;
    let alive = true;
    setState(null); setReadiness(null); setError(null);
    getJSON(`/students/${encodeURIComponent(studentId)}`)
      .then((r) => alive && setState(r))
      .catch((e) => alive && setError(String(e.message || e)));
    getJSONSafe(`/students/${encodeURIComponent(studentId)}/readiness`).then((r) => alive && setReadiness(r));
    return () => { alive = false; };
  }, [studentId]);

  const stash = studentId ? loadLastScore(studentId) : null;
  const submissionVec = stash ? stash.result.feature_vector : null;
  const averages = state ? tierAverages(state.baseline_vector) : [];

  return (
    <>
      <Sidebar active="quantum" />
      <div className="main">
        <Topbar crumb="Quantum State" semester="Live demo" />
        <div className="page-body">
          <div className="page-header">
            <div>
              <h1 className="page-title">Quantum Writing State</h1>
              <p className="page-subtitle">Density-matrix summary statistics, baseline vector, and sample evolution</p>
            </div>
            <div className="page-actions">
              <StudentPicker students={students} studentId={studentId} onChange={setStudentId} shortLabelFn={shortLabel} />
            </div>
          </div>

          {error && <div className="dash-error">Couldn't load {studentId}: {error}</div>}
          {!state && !error && <div className="empty-state"><p>Loading…</p></div>}

          {state && (
            <>
              <div className="stats-row">
                <div className="stat-card stat-default">
                  <div className="stat-label">Baseline Samples</div>
                  <div className="stat-value">{state.sample_count}</div>
                  <div className="stat-meta"><strong>{state.effective_sample_count.toFixed(1)}</strong> effective after trust weighting</div>
                </div>
                <div className="stat-card stat-flagged">
                  <div className="stat-label">Quantum Purity Tr(ρ²)</div>
                  <div className="stat-value">{fmtScore(state.purity)}</div>
                  <div className="stat-meta">{state.purity >= 0.9 ? 'near-pure state' : state.purity >= 0.5 ? 'moderately mixed state' : 'mixed-state baseline'}</div>
                </div>
                <div className="stat-card stat-clear">
                  <div className="stat-label">von Neumann Entropy</div>
                  <div className="stat-value">{fmtScore(state.von_neumann_entropy)}</div>
                  <div className="stat-meta">S = −Tr(ρ log ρ) / log(103), <strong>0 = pure</strong> · 1 = maximally mixed</div>
                </div>
                <div className="stat-card stat-pending">
                  <div className="stat-label">Baseline Confidence</div>
                  <div className="stat-value" style={{ textTransform: 'capitalize', fontSize: '1.4rem' }}>{readiness ? readiness.verdict : '—'}</div>
                  <div className="stat-meta">{readiness ? `${readiness.authenticated_count} authenticated samples` : ''}</div>
                </div>
              </div>

              <div className="quantum-grid">
                <SectionCard title="State vector" titleMeta="baseline mean ψ across all 103 features — ρ itself never leaves the server">
                  <div className="heatmap-wrap">
                    <div className="heatmap-strip">
                      {CODES.map((code) => {
                        const v = state.baseline_vector[code] ?? 0;
                        return <div key={code} className="heatmap-bar" title={`${FEATURES[code].plain} — ${v.toFixed(3)}`}
                                    style={{ height: `${Math.max(3, Math.round(v * 100))}%` }} />;
                      })}
                    </div>
                    {submissionVec && (
                      <>
                        <div className="heatmap-caption">last analyzed submission ξ ({stash.assignment || 'untitled'}):</div>
                        <div className="heatmap-strip sub">
                          {CODES.map((code) => {
                            const v = submissionVec[code] ?? 0;
                            return <div key={code} className="heatmap-bar sub" title={`${FEATURES[code].plain} — ${v.toFixed(3)}`}
                                        style={{ height: `${Math.max(3, Math.round(v * 100))}%` }} />;
                          })}
                        </div>
                      </>
                    )}
                    {!submissionVec && (
                      <div className="heatmap-caption">Run an analysis in <a href={`submissions.html?student=${encodeURIComponent(studentId)}`}>Submissions</a> to overlay a submission vector ξ.</div>
                    )}
                  </div>
                </SectionCard>

                <div className="quantum-side">
                  <SectionCard title="Purity" titleMeta="Tr(ρ²)">
                    <div className="purity-panel">
                      <PurityRing purity={state.purity} />
                      <div className="purity-legend">
                        <div><span className="pl-num">{fmtScore(state.purity)}</span> current baseline</div>
                        <div><span className="pl-num">{state.sample_count > 0 ? fmtScore(1 / Math.min(state.sample_count, 103)) : '—'}</span> floor for {state.sample_count} equal sample{state.sample_count === 1 ? '' : 's'}</div>
                        <div><span className="pl-num">1.00</span> pure state (single voice, perfectly consistent)</div>
                      </div>
                    </div>
                  </SectionCard>

                  <SectionCard title="Tier profile" titleMeta="mean of ψ per tier">
                    <TierRadar averages={averages} />
                  </SectionCard>
                </div>
              </div>

              <SectionCard title="Baseline evolution" titleMeta={`${state.samples.length} samples, trust-weighted`}>
                {state.samples.length === 0 && <div className="empty-state"><p>No baseline samples yet.</p></div>}
                <div className="q-timeline">
                  {state.samples.map((s) => (
                    <div className="q-timeline-row" key={s.index}>
                      <div className="q-timeline-dot" />
                      <div className="q-timeline-main">
                        <div className="q-timeline-title">{s.assignment || `Sample ${s.index + 1}`}</div>
                        <div className="q-timeline-meta">
                          <span className="flag-course-tag" style={{ textTransform: 'capitalize' }}>{humanize(s.provenance)}</span>
                          <span>{fmtDate(s.submitted_at)}</span>
                          <span>weight {s.auth_weight.toFixed(2)}</span>
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              </SectionCard>

              <div className="math-note">
                <strong>Mathematical note.</strong> Each authenticated sample contributes a normalized
                103-dimensional feature vector. The baseline density matrix ρ is their trust-weighted
                mixture; purity Tr(ρ²) measures how concentrated that mixture is (1 = a single
                perfectly consistent voice), and normalized von Neumann entropy S = −Tr(ρ log ρ)/log(103)
                measures its spread (0 = pure). Scoring projects a submission onto ρ via the Born rule.
                The strip above shows the baseline <em>mean</em> vector ψ — the API's view of the state;
                the full matrix stays server-side.
              </div>
            </>
          )}
        </div>
      </div>
    </>
  );
}
