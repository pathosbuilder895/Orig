// Fingerprint.jsx — Research: the stylometric fingerprint, two ways.
//
//  1. The designed visual: the procedural particle fingerprint canvas
//     (demo/js/fingerprint.js, shared with the marketing landing page).
//     Honesty rule: it is labeled a procedural illustration — it does NOT
//     plot the vector below.
//  2. The plain-English breakdown: all 103 real baseline_vector values from
//     GET /students/{id}, grouped by tier with professor-facing feature names
//     (feature-names.js, generated from constants.py + explainer.py).
//
// If a last-analysis stash exists for the student (saveLastScore from the
// Submissions page), a Compare toggle overlays that submission's
// feature_vector against the baseline — the original-features.html design.

import { useEffect, useRef, useState } from 'react';
import { getJSON } from './api.js';
import { Sidebar, Topbar, useStudentSelection, StudentPicker } from './components.jsx';
import { shortLabel, fmtScore, loadLastScore } from './util.js';
import { groupByTier } from './feature-names.js';

export function Fingerprint() {
  const { students, studentId, setStudentId } = useStudentSelection();
  const [state, setState] = useState(null);
  const [error, setError] = useState(null);
  const [view, setView] = useState('baseline'); // baseline | compare
  const [openTiers, setOpenTiers] = useState(() => new Set([1]));

  const canvasRef = useRef(null);
  const fpCtrlRef = useRef(null);

  useEffect(() => {
    if (!studentId) return;
    let alive = true;
    setState(null);
    setError(null);
    getJSON(`/students/${encodeURIComponent(studentId)}`)
      .then((r) => alive && setState(r))
      .catch((e) => alive && setError(String(e.message || e)));
    return () => { alive = false; };
  }, [studentId]);

  // Mount the particle fingerprint once; reseed per student for a fresh pattern.
  useEffect(() => {
    if (canvasRef.current && window.Fingerprint && !fpCtrlRef.current) {
      fpCtrlRef.current = window.Fingerprint(canvasRef.current, {
        // Light cream background — the library defaults target dark pages.
        lineColor: 'rgba(26,19,10,0.45)',
        goldColor: 'rgba(155,100,32,0.9)',
      });
    } else if (fpCtrlRef.current) {
      fpCtrlRef.current.reseed();
    }
  }, [studentId]);

  const stash = studentId ? loadLastScore(studentId) : null;
  const comparing = view === 'compare' && stash;
  const submissionVec = comparing ? stash.result.feature_vector : null;
  const groups = state ? groupByTier(state.baseline_vector) : [];

  function toggleTier(t) {
    setOpenTiers((prev) => {
      const next = new Set(prev);
      if (next.has(t)) next.delete(t); else next.add(t);
      return next;
    });
  }

  return (
    <>
      <Sidebar active="fingerprint" />
      <div className="main">
        <Topbar crumb="Fingerprint" semester="Live demo" />
        <div className="page-body">
          <div className="page-header">
            <div>
              <h1 className="page-title">Stylometric Fingerprint</h1>
              <p className="page-subtitle">All 103 features of the baseline mean vector, in plain English</p>
            </div>
            <div className="page-actions">
              <StudentPicker students={students} studentId={studentId} onChange={setStudentId} shortLabelFn={shortLabel} />
            </div>
          </div>

          {error && <div className="dash-error">Couldn't load {studentId}: {error}</div>}

          <div className="fp-layout">
            {/* The designed visual */}
            <div className="section-card">
              <div className="section-head">
                <span className="section-title">The fingerprint</span>
                <span className="section-title-meta">procedural illustration — not a plot of the vector</span>
              </div>
              <div className="fp-canvas-panel">
                <canvas ref={canvasRef} />
                {state && (
                  <div className="fp-readout">
                    <span className="fp-readout-name" style={{ textTransform: 'capitalize' }}>{shortLabel(studentId)}</span>
                    <span>DIMENSIONS · 103</span>
                    <span>BASELINE · {state.sample_count} sample{state.sample_count === 1 ? '' : 's'}</span>
                    <span>PURITY · {fmtScore(state.purity)}</span>
                  </div>
                )}
              </div>
            </div>

            {/* The real numbers */}
            <div className="section-card">
              <div className="section-head">
                <span className="section-title">Feature profile <span className="section-title-meta">baseline mean, normalized 0–1</span></span>
                <div className="mode-toggle">
                  <button className={'mode-btn' + (view === 'baseline' ? ' active' : '')} onClick={() => setView('baseline')}>Baseline only</button>
                  <button className={'mode-btn' + (view === 'compare' ? ' active' : '')} onClick={() => setView('compare')} disabled={!stash}
                          title={stash ? '' : 'Run an analysis in Submissions first'}>
                    Compare last analysis
                  </button>
                </div>
              </div>

              {!state && !error && <div className="empty-state"><p>Loading…</p></div>}

              {view === 'compare' && !stash && (
                <div className="empty-state"><p>No analysis stashed for this student in this tab — run one in <a href={`submissions.html?student=${encodeURIComponent(studentId)}`}>Submissions</a> and come back.</p></div>
              )}

              {comparing && (
                <div className="fp-compare-note">
                  Comparing against "{stash.assignment || 'last analysis'}" from {new Date(stash.saved_at).toLocaleTimeString()} ·
                  <span className="fp-legend"><i className="sw sw-base" /> baseline</span>
                  <span className="fp-legend"><i className="sw sw-sub" /> submission</span>
                </div>
              )}

              {state && groups.map((g) => {
                const open = openTiers.has(g.tier);
                return (
                  <div className="fp-tier" key={g.tier}>
                    <button className="fp-tier-head" onClick={() => toggleTier(g.tier)}>
                      <span className={'fp-tier-chevron' + (open ? ' open' : '')}>›</span>
                      <span className="fp-tier-name">{g.name}</span>
                      <span className="fp-tier-count">{g.features.length}</span>
                    </button>
                    {open && (
                      <div className="fp-tier-body">
                        {g.features.map((f) => {
                          const base = f.value;
                          const sub = submissionVec ? submissionVec[f.code] : null;
                          const delta = comparing && typeof sub === 'number' && typeof base === 'number' ? sub - base : null;
                          return (
                            <div className="fp-feature" key={f.code}>
                              <div className="fp-feature-label">
                                <span className="fp-feature-plain">{f.plain}</span>
                                <span className="fp-feature-code">{f.code}</span>
                              </div>
                              <div className="fp-feature-bars">
                                <div className="fp-bar"><div className="fp-bar-fill base" style={{ width: `${Math.round((base || 0) * 100)}%` }} /></div>
                                {comparing && (
                                  <div className="fp-bar"><div className={'fp-bar-fill sub' + (delta != null && Math.abs(delta) > 0.15 ? ' flagged' : '')} style={{ width: `${Math.round((sub || 0) * 100)}%` }} /></div>
                                )}
                              </div>
                              <div className="fp-feature-val">
                                {base == null ? '—' : base.toFixed(2)}
                                {comparing && delta != null && (
                                  <span className={'fp-delta' + (Math.abs(delta) > 0.15 ? ' big' : '')}>
                                    {delta >= 0 ? '+' : ''}{delta.toFixed(2)}
                                  </span>
                                )}
                              </div>
                            </div>
                          );
                        })}
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          </div>
        </div>
      </div>
    </>
  );
}
