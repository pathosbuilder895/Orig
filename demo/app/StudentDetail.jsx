// StudentDetail.jsx — per-student drill-down, full original-student.html port:
// student header with latest deviation, the designed Stylometric Fingerprint
// card (procedural canvas + readout + headline feature rows), Baseline
// Profile, Deviation History sparkline, Pipeline shortcuts into the Research
// pages, baseline confidence + samples (lazy text), and submission history.
//
// Data sources (all real):
//   GET /students/{id}                      → StudentStateResponse (+ entropy)
//   GET /students/{id}/readiness            → verdict + recommendations
//   GET /students/{id}/samples/{i}/text     → lazy, on row expand
//   GET /admin/manifests?student_id={id}    → history + deviation sparkline
//   GET /admin/tuned-thresholds             → flag-threshold line (else default)
//   sessionStorage last-score (Submissions) → fingerprint compare overlay
//
// The particle canvas is labeled a procedural illustration — it does not plot
// the vector; the numbers beside it are the real baseline values (normalized
// 0–1 pipeline units, labeled as such — raw units aren't exposed by the API).

import { useEffect, useRef, useState } from 'react';
import { getJSON, getJSONSafe } from './api.js';
import { Sidebar, Topbar, Icon } from './components.jsx';
import { shortLabel, initials, fmtScore, fmtDate, humanize, loadLastScore } from './util.js';
import { FEATURES } from './feature-names.js';

const FLAG_ACTIONS = new Set(['escalate', 'schedule_conversation']);

// Headline features shown on the fingerprint card + baseline profile —
// the design's Lexical/Syntactic/Grammatical trio, mapped to real codes.
const HEADLINE_GROUPS = [
  { name: 'Lexical', codes: ['type_token_ratio', 'hapax_legomena_rate', 'avg_word_length'] },
  { name: 'Syntactic', codes: ['mean_sentence_length', 'sentence_length_variance'] },
  { name: 'Grammatical', codes: ['function_word_ratio', 'passive_voice_ratio', 'modal_verb_ratio'] },
];

function qs(name) {
  return new URLSearchParams(window.location.search).get(name);
}

export function StudentDetail() {
  const id = qs('id') || '';
  const [state, setState] = useState(null);
  const [readiness, setReadiness] = useState(null);
  const [history, setHistory] = useState(null);
  const [thresholds, setThresholds] = useState(undefined);
  const [error, setError] = useState(null);
  const [openIndex, setOpenIndex] = useState(null);
  const [sampleText, setSampleText] = useState({}); // index -> {loading, data}

  const fpCanvasRef = useRef(null);
  const fpCtrlRef = useRef(null);

  useEffect(() => {
    if (!id) return;
    let alive = true;
    getJSON(`/students/${encodeURIComponent(id)}`).then((r) => alive && setState(r))
      .catch((e) => alive && setError(String(e.message || e)));
    getJSONSafe(`/students/${encodeURIComponent(id)}/readiness`).then((r) => alive && setReadiness(r));
    getJSONSafe(`/admin/manifests?student_id=${encodeURIComponent(id)}&limit=100`).then((r) => alive && setHistory(r));
    getJSONSafe('/admin/tuned-thresholds').then((r) => alive && setThresholds(r));
    return () => { alive = false; };
  }, [id]);

  // Procedural fingerprint canvas (decorative-but-labeled), light-bg palette.
  useEffect(() => {
    if (!state) return;
    if (fpCanvasRef.current && window.Fingerprint && !fpCtrlRef.current) {
      fpCtrlRef.current = window.Fingerprint(fpCanvasRef.current, {
        lineColor: 'rgba(26,19,10,0.45)',
        goldColor: 'rgba(155,100,32,0.9)',
        rings: 13,
        particlesPerRing: 80,
      });
    }
  }, [state]);

  function toggleSample(index) {
    if (openIndex === index) { setOpenIndex(null); return; }
    setOpenIndex(index);
    if (!sampleText[index]) {
      setSampleText((s) => ({ ...s, [index]: { loading: true } }));
      getJSONSafe(`/students/${encodeURIComponent(id)}/samples/${index}/text`).then((r) => {
        setSampleText((s) => ({ ...s, [index]: { loading: false, data: r } }));
      });
    }
  }

  if (!id) {
    return (
      <>
        <Sidebar active="students" />
        <div className="main">
          <Topbar crumb="Student" />
          <div className="page-body"><div className="empty-state"><h3>No student selected</h3><p>Open this page from the Students or Flagged list.</p></div></div>
        </div>
      </>
    );
  }

  // Derived, all from real data.
  const items = (history && history.items) || [];
  const chrono = items.slice().sort((a, b) => (a.created_at || '').localeCompare(b.created_at || ''));
  const latest = chrono.length ? chrono[chrono.length - 1] : null;
  const isFlagged = latest && FLAG_ACTIONS.has(latest.action);
  const fpState = latest ? (isFlagged ? 'deviating' : 'steady') : '—';
  const stash = loadLastScore(id);
  const submissionVec = stash ? stash.result.feature_vector : null;
  const flagLine = thresholds && thresholds.escalate != null
    ? { value: thresholds.escalate, label: 'escalate threshold (tuned)' }
    : { value: 0.65, label: 'default flag threshold' };

  return (
    <>
      <Sidebar active="students" />
      <div className="main">
        <Topbar crumb={state ? shortLabel(id) : 'Student'} semester="Live demo" />
        <div className="page-body">

          {error && <div className="dash-error">Couldn't load {id}: {error}</div>}
          {!state && !error && <div className="empty-state"><p>Loading…</p></div>}

          {state && (
            <>
              {/* ── Student header (design: student-header + deviation display) ── */}
              <div className="student-header">
                <div className="student-avatar-lg">{initials(id)}</div>
                <div className="student-header-info">
                  <h1 className="student-header-name" style={{ textTransform: 'capitalize' }}>{shortLabel(id)}</h1>
                  <div className="student-header-meta">
                    <span className="student-meta-item">{id}</span>
                    <span className="student-meta-item">{state.sample_count} sample{state.sample_count === 1 ? '' : 's'} · {state.authenticated_count} authenticated</span>
                    {readiness && <span className={'student-meta-item verdict-' + readiness.verdict}>baseline: {readiness.verdict}</span>}
                    {isFlagged && <span className="alert-badge"><Icon name="alert" />High deviation flagged</span>}
                  </div>
                </div>
                <div className="student-header-right">
                  {latest && (
                    <div className="deviation-display">
                      <div className="deviation-label">Latest deviation</div>
                      <div className={'deviation-number' + ((latest.divergence_score || 0) >= flagLine.value ? ' hot' : '')}>{fmtScore(latest.divergence_score)}</div>
                      <div className="deviation-sub">{latest.submission_id || 'submission'} · {fmtDate(latest.created_at)}</div>
                    </div>
                  )}
                  <div className="sd-header-btns">
                    <a className="btn btn-primary" href={`submissions.html?student=${encodeURIComponent(id)}`}><Icon name="upload" />Submit</a>
                    <a className="btn btn-ghost" href={`submissions.html?student=${encodeURIComponent(id)}#import`}>Baseline</a>
                    <a className="btn btn-ghost" href={`submissions.html?student=${encodeURIComponent(id)}&source=canvas`}>Canvas import</a>
                  </div>
                </div>
              </div>

              <div className="profile-grid">
                {/* ── LEFT column ── */}
                <div style={{ display: 'flex', flexDirection: 'column', gap: '1.25rem' }}>

                  {/* Stylometric Fingerprint — designed visual + real numbers */}
                  <div className="section-card">
                    <div className="section-head">
                      <span className="section-title">Stylometric Fingerprint</span>
                      <span className="section-title-meta">
                        {submissionVec ? 'baseline vs. last analysis' : 'baseline values (normalized 0–1)'}
                      </span>
                    </div>
                    <div className="sd-fp-visual">
                      <canvas ref={fpCanvasRef} />
                      <div className="fp-readout">
                        <span className="fp-readout-name" style={{ textTransform: 'capitalize' }}>{shortLabel(id)}</span>
                        <span>DIMENSIONS · 103</span>
                        <span>BASELINE · {state.sample_count} sample{state.sample_count === 1 ? '' : 's'}</span>
                        <span>STATE · <em>{fpState}</em></span>
                      </div>
                      <div className="sd-fp-caption">procedural illustration — the numbers below are the real vector</div>
                    </div>
                    <div className="sd-fp-features">
                      {HEADLINE_GROUPS.map((g) => (
                        <div key={g.name}>
                          <div className="sd-fp-group">{g.name}</div>
                          {g.codes.map((code) => {
                            const meta = FEATURES[code];
                            const base = state.baseline_vector[code];
                            const sub = submissionVec ? submissionVec[code] : null;
                            const delta = sub != null && base != null ? sub - base : null;
                            return (
                              <div className="fp-feature" key={code}>
                                <div className="fp-feature-label">
                                  <span className="fp-feature-plain">{meta ? meta.plain : code}</span>
                                  <span className="fp-feature-code">{code}</span>
                                </div>
                                <div className="fp-feature-bars">
                                  <div className="fp-bar"><div className="fp-bar-fill base" style={{ width: `${Math.round((base || 0) * 100)}%` }} /></div>
                                  {submissionVec && (
                                    <div className="fp-bar"><div className={'fp-bar-fill sub' + (delta != null && Math.abs(delta) > 0.15 ? ' flagged' : '')} style={{ width: `${Math.round((sub || 0) * 100)}%` }} /></div>
                                  )}
                                </div>
                                <div className="fp-feature-val">
                                  {base == null ? '—' : base.toFixed(2)}
                                  {delta != null && (
                                    <span className={'fp-delta' + (Math.abs(delta) > 0.15 ? ' big' : '')}>{delta >= 0 ? '+' : ''}{delta.toFixed(2)}</span>
                                  )}
                                </div>
                              </div>
                            );
                          })}
                        </div>
                      ))}
                      {!submissionVec && (
                        <div className="extract-meta" style={{ marginTop: '0.5rem' }}>
                          Run an analysis in <a href={`submissions.html?student=${encodeURIComponent(id)}`}>Submissions</a> to compare a submission against these — full 103-feature view on the <a href={`fingerprint.html?student=${encodeURIComponent(id)}`}>Fingerprint</a> page.
                        </div>
                      )}
                    </div>
                  </div>

                  {/* Deviation history — real sparkline from manifests */}
                  <div className="section-card">
                    <div className="section-head">
                      <span className="section-title">Deviation History</span>
                      <span className="section-title-meta">{chrono.length} scored submission{chrono.length === 1 ? '' : 's'}</span>
                    </div>
                    {chrono.length === 0 && <div className="empty-state"><p>No scored submissions yet — the chart appears after the first analysis.</p></div>}
                    {chrono.length > 0 && <DeviationChart points={chrono} flagLine={flagLine} />}
                  </div>

                  {/* Baseline confidence (kept) */}
                  <div className="section-card">
                    <div className="section-head"><span className="section-title">Baseline confidence</span></div>
                    <div className="confidence-grid">
                      <ConfidenceStat label="Purity" value={fmtScore(state.purity)} />
                      <ConfidenceStat label="Entropy" value={fmtScore(state.von_neumann_entropy)} />
                      <ConfidenceStat label="Effective samples" value={state.effective_sample_count.toFixed(1)} />
                      <ConfidenceStat label="Trajectory" value={humanize(state.trajectory_direction)} />
                    </div>
                    {readiness && readiness.recommendations && readiness.recommendations.length > 0 && (
                      <div className="readiness-notes">
                        {readiness.recommendations.map((r, i) => <div key={i} className="readiness-note">{r}</div>)}
                      </div>
                    )}
                  </div>

                  {/* Baseline samples (kept) */}
                  <div className="section-card">
                    <div className="section-head"><span className="section-title">Baseline samples</span><span className="section-title-meta">{state.samples.length}</span></div>
                    {state.samples.length === 0 && <div className="empty-state"><p>No baseline samples yet.</p></div>}
                    {state.samples.map((s) => (
                      <div key={s.index} className="sample-row-wrap">
                        <div className="sample-row" onClick={() => toggleSample(s.index)}>
                          <div>
                            <div className="sample-assignment">{s.assignment || `Sample ${s.index + 1}`}</div>
                            <div className="sample-sub">{humanize(s.provenance)} · weight {s.auth_weight.toFixed(2)}</div>
                          </div>
                          <div className="sample-date">{fmtDate(s.submitted_at)}</div>
                        </div>
                        {openIndex === s.index && (
                          <div className="sample-text-panel">
                            {(!sampleText[s.index] || sampleText[s.index].loading) && <p style={{ fontStyle: 'italic', color: 'var(--text-muted)' }}>Loading…</p>}
                            {sampleText[s.index] && sampleText[s.index].data && (
                              <>
                                <div className="sample-text-meta">{sampleText[s.index].data.word_count} words</div>
                                <p className="sample-text-body">{sampleText[s.index].data.text}</p>
                              </>
                            )}
                          </div>
                        )}
                      </div>
                    ))}
                  </div>
                </div>

                {/* ── RIGHT rail ── */}
                <div style={{ display: 'flex', flexDirection: 'column', gap: '1.25rem' }}>

                  {/* Baseline Profile (design right-rail card) */}
                  <div className="section-card">
                    <div className="section-head">
                      <span className="section-title">Baseline Profile</span>
                      {readiness && (
                        <span className={'baseline-pill ' + (readiness.verdict === 'ready' ? 'strong' : readiness.verdict === 'developing' ? 'building' : 'none')}>
                          <span className="bp-dot" />{readiness.verdict === 'ready' ? 'Strong' : readiness.verdict === 'developing' ? 'Building' : 'Not set'}
                        </span>
                      )}
                    </div>
                    <div className="sd-profile-list">
                      <div><span className="th-lbl">Samples on file</span><span className="th-val">{state.sample_count}</span></div>
                      {HEADLINE_GROUPS.flatMap((g) => g.codes).slice(0, 5).map((code) => (
                        <div key={code}>
                          <span className="th-lbl">{FEATURES[code] ? FEATURES[code].plain : code}</span>
                          <span className="th-val">{state.baseline_vector[code] == null ? '—' : state.baseline_vector[code].toFixed(2)}</span>
                        </div>
                      ))}
                      <div className="th-meta">normalized 0–1 pipeline values — raw units aren't exposed by the API</div>
                    </div>
                  </div>

                  {/* Pipeline shortcuts (design right-rail card) */}
                  <div className="section-card">
                    <div className="section-head"><span className="section-title">Pipeline Analysis</span></div>
                    <div className="sd-pipeline">
                      <a className="sd-pipe-card" href={`fingerprint.html?student=${encodeURIComponent(id)}`}>
                        <Icon name="sliders" />
                        <div>
                          <div className="sd-pipe-name">Feature Profile</div>
                          <div className="sd-pipe-meta">103 features · plain English</div>
                        </div>
                      </a>
                      <a className="sd-pipe-card" href={`quantum.html?student=${encodeURIComponent(id)}`}>
                        <Icon name="atom" />
                        <div>
                          <div className="sd-pipe-name">Quantum State</div>
                          <div className="sd-pipe-meta">purity {fmtScore(state.purity)} · entropy {fmtScore(state.von_neumann_entropy)}</div>
                        </div>
                      </a>
                      <a className="sd-pipe-card" href={`interference.html?student=${encodeURIComponent(id)}`}>
                        <Icon name="activity" />
                        <div>
                          <div className="sd-pipe-name">Interference</div>
                          <div className="sd-pipe-meta">
                            {stash
                              ? `last analysis · deviation ${fmtScore(stash.result.authorship.deviation_score)}`
                              : 'run an analysis to decompose it'}
                          </div>
                        </div>
                      </a>
                    </div>
                  </div>

                  {/* Submission history (kept, design-styled rows) */}
                  <div className="section-card">
                    <div className="section-head">
                      <span className="section-title">Submission history</span>
                      {history && <span className="section-title-meta">{history.total} total</span>}
                    </div>
                    {history === null && <div className="empty-state"><p>Loading…</p></div>}
                    {history && items.length === 0 && <div className="empty-state"><h3>No submissions yet</h3><p>Once this student is scored, submissions appear here.</p></div>}
                    {items.map((m) => (
                      <div className="flag-item" key={m.submission_id} style={{ cursor: 'default' }}>
                        <div className="flag-item-top">
                          <span className="flag-student">{m.submission_id || 'submission'}</span>
                          <span className={'flag-score' + ((m.divergence_score || 0) >= 0.7 ? ' high' : '')}>{fmtScore(m.divergence_score)}</span>
                        </div>
                        <div className="flag-detail">{(m.flags || []).map(humanize).join(' · ') || 'no flags'} · {m.length_regime}</div>
                        <div className="flag-meta">
                          {m.action && <span className="flag-course-tag" style={{ textTransform: 'capitalize' }}>{humanize(m.action)}</span>}
                          <span className="flag-date">{fmtDate(m.created_at)}</span>
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              </div>
            </>
          )}
        </div>
      </div>
    </>
  );
}

// Real deviation-over-time sparkline: divergence_score per scored submission,
// with the flag-threshold reference line (tuned when available, else default).
function DeviationChart({ points, flagLine }) {
  const W = 560, H = 150, PAD = 22;
  const n = points.length;
  const x = (i) => PAD + (n === 1 ? (W - PAD * 2) / 2 : (i / (n - 1)) * (W - PAD * 2));
  const y = (v) => PAD + (1 - Math.max(0, Math.min(1, v))) * (H - PAD * 2);
  const line = points.map((p, i) => `${x(i)},${y(p.divergence_score || 0)}`).join(' ');
  return (
    <div className="sd-devchart-wrap">
      <svg viewBox={`0 0 ${W} ${H + 16}`} className="sd-devchart">
        <line x1={PAD} y1={y(flagLine.value)} x2={W - PAD} y2={y(flagLine.value)}
              stroke="var(--amber)" strokeWidth="1" strokeDasharray="5,4" />
        <text x={W - PAD} y={y(flagLine.value) - 5} textAnchor="end" className="sd-devchart-lbl">
          {flagLine.value.toFixed(2)} · {flagLine.label}
        </text>
        {n > 1 && <polyline points={line} fill="none" stroke="var(--green-deep)" strokeWidth="2" strokeLinejoin="round" strokeLinecap="round" />}
        {points.map((p, i) => (
          <circle key={i} cx={x(i)} cy={y(p.divergence_score || 0)} r="3.5"
                  fill={(p.divergence_score || 0) >= flagLine.value ? 'var(--flag-red)' : 'var(--flag-green)'}>
            <title>{`${p.submission_id || 'submission'} · ${(p.divergence_score || 0).toFixed(2)} · ${p.created_at ? p.created_at.slice(0, 10) : ''}`}</title>
          </circle>
        ))}
        {points.map((p, i) => (
          (n <= 8 || i === 0 || i === n - 1) && (
            <text key={'t' + i} x={x(i)} y={H + 10} textAnchor="middle" className="sd-devchart-lbl">{fmtDate(p.created_at)}</text>
          )
        ))}
      </svg>
    </div>
  );
}

function ConfidenceStat({ label, value }) {
  return (
    <div className="confidence-stat">
      <div className="confidence-label">{label}</div>
      <div className="confidence-value" style={{ textTransform: 'capitalize' }}>{value}</div>
    </div>
  );
}
