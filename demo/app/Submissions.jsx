// Submissions.jsx — score or ingest student writing from any source:
// paste, file upload (.txt/.docx/.pdf), Canvas, Blackboard (via file export),
// or a Turnitin roster CSV. Renamed from Analyze.jsx ("Submit Writing").
//
// Two modes ride over the sources:
//   Analyze         → POST /students/{id}/score (the single scoring entrypoint;
//                      files go through the dry-run extractor POST /students/{id}/upload,
//                      Canvas through fetch-submission-text — text in, score out)
//   Add to baseline → POST /students/{id}/baseline (paste) or
//                      /students/{id}/baseline/upload-batch (files) or
//                      /canvas/baseline/{id}/import-baseline (Canvas rows)
//
// Every successful score is stashed via saveLastScore() — the Research pages
// (Interference entirely; Fingerprint/Quantum compare overlays) read it.

import { useEffect, useRef, useState } from 'react';
import { getJSON, getJSONSafe, postJSON, postForm } from './api.js';
import { Sidebar, Topbar, Icon } from './components.jsx';
import { shortLabel, fmtScore, actionMeta, saveLastScore } from './util.js';
import { TIER_META } from './feature-names.js';

const TIERS = Array.from({ length: 17 }, (_, i) => ({
  key: `T${i + 1}`,
  name: TIER_META[String(i + 1)] || `Tier ${i + 1}`,
}));

const ARC_FLAG_LABEL = {
  authentic: 'Authentic human arc', ai_typical: 'AI-typical arc',
  review: 'Review — inconclusive', insufficient_length: 'Too short to analyze',
};

const SOURCES = [
  ['paste', 'Paste text'],
  ['file', 'Upload file'],
  ['canvas', 'Canvas'],
  ['blackboard', 'Blackboard'],
  ['turnitin', 'Turnitin CSV'],
];

export function Submissions() {
  const [students, setStudents] = useState([]);
  const [studentId, setStudentId] = useState('');
  const [readiness, setReadiness] = useState(null);

  const [mode, setMode] = useState('analyze');        // analyze | baseline
  const [source, setSource] = useState('paste');      // paste | file | canvas | blackboard | turnitin
  const [assignment, setAssignment] = useState('');
  const [provenance, setProvenance] = useState('verified');
  const [text, setText] = useState('');

  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState(null);
  const [result, setResult] = useState(null);          // Layer7 score result
  const [baselineResult, setBaselineResult] = useState(null); // paste/file baseline outcome

  // File source
  const [extracted, setExtracted] = useState(null);    // {text, filename, word_count} (analyze)
  const [batchFiles, setBatchFiles] = useState([]);    // File[] (baseline)

  // Canvas source
  const [cvCourse, setCvCourse] = useState('');
  const [cvUser, setCvUser] = useState('');
  const [cvToken, setCvToken] = useState('');
  const [cvSubs, setCvSubs] = useState(null);           // null=not listed, []=empty
  const [cvBusy, setCvBusy] = useState(false);
  const [cvRowStatus, setCvRowStatus] = useState({});   // id -> status text

  // Turnitin source
  const [ttCourses, setTtCourses] = useState([]);
  const [ttCourse, setTtCourse] = useState('');
  const [ttResult, setTtResult] = useState(null);

  const canvasRef = useRef(null);
  const hoverRef = useRef(null);
  const arcCtrlRef = useRef(null);
  const fileInputRef = useRef(null);

  useEffect(() => {
    let alive = true;
    const params = new URLSearchParams(window.location.search);
    const preselect = params.get('student');
    getJSON('/students').then((r) => {
      if (!alive) return;
      const ids = (r && r.students) || [];
      setStudents(ids);
      if (preselect && ids.includes(preselect)) setStudentId(preselect);
      else if (ids.length) setStudentId(ids[0]);
    }).catch(() => {});
    getJSONSafe('/bluebook/courses').then((r) => {
      if (alive) setTtCourses((r && r.courses) || []);
    });
    // Dashboard deep-link: #import opens the ingestion-oriented state.
    if (window.location.hash === '#import') { setMode('baseline'); setSource('file'); }
    if (params.get('source') === 'canvas') setSource('canvas');
    return () => { alive = false; };
  }, []);

  useEffect(() => {
    if (!studentId) { setReadiness(null); return; }
    let alive = true;
    getJSONSafe(`/students/${encodeURIComponent(studentId)}/readiness`).then((r) => { if (alive) setReadiness(r); });
    return () => { alive = false; };
  }, [studentId]);

  // Mount the tension-arc canvas once it exists; feed it real data per result.
  useEffect(() => {
    if (canvasRef.current && window.TensionArc && !arcCtrlRef.current) {
      arcCtrlRef.current = window.TensionArc(canvasRef.current, hoverRef.current);
    }
  }, [result]);
  useEffect(() => {
    const series = result && result.tension_arc && result.tension_arc.tension_series;
    if (arcCtrlRef.current && Array.isArray(series) && series.length) {
      arcCtrlRef.current.setSeries(series);
    }
  }, [result]);

  const words = text.trim().split(/\s+/).filter(Boolean).length;

  async function scoreText(rawText, label) {
    if (!studentId || submitting) return;
    setSubmitting(true);
    setError(null);
    setBaselineResult(null);
    try {
      const resp = await postJSON(`/students/${encodeURIComponent(studentId)}/score`, {
        text: rawText, submission_id: '', assignment: label || '',
      });
      setResult(resp);
      saveLastScore(studentId, resp, label || '');
    } catch (e) {
      setError(String(e.message || e));
      setResult(null);
    } finally {
      setSubmitting(false);
    }
  }

  async function addBaselineText(rawText, label) {
    if (!studentId || submitting) return;
    setSubmitting(true);
    setError(null);
    setResult(null);
    try {
      const resp = await postJSON(`/students/${encodeURIComponent(studentId)}/baseline`, {
        text: rawText, provenance, assignment: label || '',
      });
      setBaselineResult({ kind: 'single', data: resp });
    } catch (e) {
      setError(String(e.message || e));
    } finally {
      setSubmitting(false);
    }
  }

  async function extractFile(file) {
    setSubmitting(true);
    setError(null);
    try {
      const fd = new FormData();
      fd.append('file', file);
      const resp = await postForm(`/students/${encodeURIComponent(studentId)}/upload`, fd);
      setExtracted(resp);
      if (!assignment) setAssignment(resp.filename.replace(/\.[^.]+$/, ''));
    } catch (e) {
      setError(String(e.message || e));
      setExtracted(null);
    } finally {
      setSubmitting(false);
    }
  }

  async function uploadBatch() {
    if (!studentId || !batchFiles.length || submitting) return;
    setSubmitting(true);
    setError(null);
    setResult(null);
    try {
      const fd = new FormData();
      for (const f of batchFiles) fd.append('files', f);
      fd.append('provenance', provenance);
      fd.append('assignment', assignment);
      const resp = await postForm(`/students/${encodeURIComponent(studentId)}/baseline/upload-batch`, fd);
      setBaselineResult({ kind: 'batch', data: resp });
      setBatchFiles([]);
      if (fileInputRef.current) fileInputRef.current.value = '';
    } catch (e) {
      setError(String(e.message || e));
    } finally {
      setSubmitting(false);
    }
  }

  function canvasBody(extra) {
    const body = { canvas_course_id: cvCourse.trim(), canvas_user_id: cvUser.trim(), ...extra };
    if (cvToken.trim()) body.access_token = cvToken.trim();
    return body;
  }

  async function canvasList() {
    if (!cvCourse.trim() || !cvUser.trim() || cvBusy) return;
    setCvBusy(true);
    setError(null);
    setCvSubs(null);
    setCvRowStatus({});
    try {
      const resp = await postJSON(
        `/canvas/baseline/${encodeURIComponent(studentId)}/list-canvas-submissions`, canvasBody());
      setCvSubs(resp.submissions || []);
    } catch (e) {
      setError(String(e.message || e));
    } finally {
      setCvBusy(false);
    }
  }

  async function canvasAnalyze(sub) {
    setCvRowStatus((s) => ({ ...s, [sub.canvas_submission_id]: 'fetching…' }));
    try {
      const fetched = await postJSON(
        `/canvas/baseline/${encodeURIComponent(studentId)}/fetch-submission-text`,
        canvasBody({ canvas_submission_id: sub.canvas_submission_id }));
      setCvRowStatus((s) => ({ ...s, [sub.canvas_submission_id]: 'scoring…' }));
      await scoreText(fetched.text, fetched.assignment_name);
      setCvRowStatus((s) => ({ ...s, [sub.canvas_submission_id]: 'scored ✓ (results below)' }));
    } catch (e) {
      setCvRowStatus((s) => ({ ...s, [sub.canvas_submission_id]: `error: ${e.message}` }));
    }
  }

  async function canvasImport(sub) {
    setCvRowStatus((s) => ({ ...s, [sub.canvas_submission_id]: 'importing…' }));
    try {
      const resp = await postJSON(
        `/canvas/baseline/${encodeURIComponent(studentId)}/import-baseline`,
        canvasBody({ submission_ids: [sub.canvas_submission_id] }));
      const note = resp.imported ? 'imported ✓'
        : resp.drift_holds && resp.drift_holds.length ? 'held (drift gate)'
        : 'skipped (duplicate or too short)';
      const downgrade = resp.provenance_downgraded ? ' · provenance downgraded to unverified' : '';
      setCvRowStatus((s) => ({ ...s, [sub.canvas_submission_id]: note + downgrade }));
    } catch (e) {
      setCvRowStatus((s) => ({ ...s, [sub.canvas_submission_id]: `error: ${e.message}` }));
    }
  }

  async function turnitinUpload(file) {
    const course = ttCourse.trim();
    if (!course || !file || submitting) return;
    setSubmitting(true);
    setError(null);
    setTtResult(null);
    try {
      const fd = new FormData();
      fd.append('file', file);
      const resp = await postForm(`/import/courses/${encodeURIComponent(course)}/turnitin-csv`, fd);
      setTtResult(resp);
    } catch (e) {
      setError(String(e.message || e));
    } finally {
      setSubmitting(false);
    }
  }

  const rec = result && result.recommendation;
  const auth = result && result.authorship;
  const explain = result && result.human_explanation;
  const arc = result && result.tension_arc;
  const tierBreakdown = (result && result.interference && result.interference.tier_breakdown) || {};
  const constructive = (result && result.interference && result.interference.constructive_features) || [];
  const destructive = (result && result.interference && result.interference.destructive_features) || [];
  const topFeatures = [...destructive, ...constructive].slice(0, 6);
  const am = rec ? actionMeta(rec.action) : null;
  const researchQS = `?student=${encodeURIComponent(studentId)}`;

  return (
    <>
      <Sidebar active="submissions" />
      <div className="main">
        <Topbar crumb="Submissions" semester="Live demo" />
        <div className="page-body">
          <div className="page-header">
            <div>
              <h1 className="page-title">Submissions</h1>
              <p className="page-subtitle">Score writing against a student's baseline, or add to it — paste, files, Canvas, or a Turnitin roster</p>
            </div>
          </div>

          <div className="analyze-grid">
            {/* ── Input card ── */}
            <div className="section-card analyze-form">
              <div className="section-head">
                <span className="section-title">Source</span>
                <div className="mode-toggle">
                  <button className={'mode-btn' + (mode === 'analyze' ? ' active' : '')} onClick={() => setMode('analyze')}>Analyze</button>
                  <button className={'mode-btn' + (mode === 'baseline' ? ' active' : '')} onClick={() => setMode('baseline')}>Add to baseline</button>
                </div>
              </div>
              <div className="analyze-form-body">
                <label className="a-label">Student</label>
                <select className="a-select" value={studentId} onChange={(e) => { setStudentId(e.target.value); setCvSubs(null); setCvRowStatus({}); }}>
                  {students.length === 0 && <option value="">Loading…</option>}
                  {students.map((id) => (
                    <option key={id} value={id} style={{ textTransform: 'capitalize' }}>{shortLabel(id)}</option>
                  ))}
                </select>
                {readiness && (
                  <div className={'baseline-hint ' + (readiness.verdict === 'ready' ? 'ok' : readiness.verdict === 'developing' ? 'warn' : 'bad')}>
                    Baseline: <strong>{readiness.verdict}</strong> — {readiness.authenticated_count} authenticated sample{readiness.authenticated_count === 1 ? '' : 's'}
                    {readiness.verdict === 'insufficient' && mode === 'analyze' && ' · scoring will be rejected until at least one baseline sample exists'}
                  </div>
                )}

                <div className="src-tabs">
                  {SOURCES.map(([key, label]) => (
                    <button key={key} className={'src-tab' + (source === key ? ' active' : '')} onClick={() => { setSource(key); setError(null); }}>
                      {label}
                    </button>
                  ))}
                </div>

                {/* ── Paste ── */}
                {source === 'paste' && (
                  <>
                    <label className="a-label">Assignment label (optional)</label>
                    <input className="a-input" value={assignment} onChange={(e) => setAssignment(e.target.value)} placeholder="e.g. Midterm Essay — Doctrine of God" />
                    <label className="a-label" style={{ marginTop: '1rem' }}>Submission text</label>
                    <textarea className="a-textarea" value={text} onChange={(e) => setText(e.target.value)}
                              placeholder="Paste the student's writing here…" />
                    <div className="a-wordcount">{words} word{words === 1 ? '' : 's'}{words > 0 && words < 20 ? ' — 20+ needed' : ''}</div>
                    {mode === 'baseline' && <ProvenanceSelect value={provenance} onChange={setProvenance} />}
                    <button className="btn btn-primary a-cta" disabled={!studentId || words < 20 || submitting}
                            onClick={() => (mode === 'analyze' ? scoreText(text, assignment) : addBaselineText(text, assignment))}>
                      {submitting ? 'Working…' : mode === 'analyze' ? 'Analyze submission' : 'Add to baseline'}
                    </button>
                  </>
                )}

                {/* ── Upload file ── */}
                {source === 'file' && (
                  <>
                    <label className="a-label">File{mode === 'baseline' ? 's' : ''} (.txt, .docx, .pdf)</label>
                    <input ref={fileInputRef} className="a-input" type="file" accept=".txt,.docx,.pdf"
                           multiple={mode === 'baseline'}
                           onChange={(e) => {
                             const files = [...(e.target.files || [])];
                             if (!files.length) return;
                             if (mode === 'baseline') setBatchFiles(files);
                             else extractFile(files[0]);
                           }} />
                    <label className="a-label" style={{ marginTop: '1rem' }}>Assignment label (optional)</label>
                    <input className="a-input" value={assignment} onChange={(e) => setAssignment(e.target.value)} placeholder="defaults to the filename" />

                    {mode === 'analyze' && extracted && (
                      <>
                        <div className="extract-preview">
                          <div className="extract-meta">{extracted.filename} · {extracted.word_count} words extracted (nothing stored)</div>
                          <p className="extract-text">{extracted.text.slice(0, 600)}{extracted.text.length > 600 ? '…' : ''}</p>
                        </div>
                        <button className="btn btn-primary a-cta" disabled={submitting || extracted.word_count < 20}
                                onClick={() => scoreText(extracted.text, assignment)}>
                          {submitting ? 'Analyzing…' : 'Analyze extracted text'}
                        </button>
                      </>
                    )}

                    {mode === 'baseline' && (
                      <>
                        {batchFiles.length > 0 && (
                          <div className="extract-meta" style={{ marginTop: '0.6rem' }}>
                            {batchFiles.length} file{batchFiles.length === 1 ? '' : 's'} selected: {batchFiles.map((f) => f.name).join(', ')}
                          </div>
                        )}
                        <ProvenanceSelect value={provenance} onChange={setProvenance} />
                        <button className="btn btn-primary a-cta" disabled={!batchFiles.length || submitting} onClick={uploadBatch}>
                          {submitting ? 'Uploading…' : `Add ${batchFiles.length || ''} file${batchFiles.length === 1 ? '' : 's'} to baseline`}
                        </button>
                      </>
                    )}
                  </>
                )}

                {/* ── Canvas ── */}
                {source === 'canvas' && (
                  <>
                    <label className="a-label">Canvas course ID</label>
                    <input className="a-input" value={cvCourse} onChange={(e) => setCvCourse(e.target.value)} placeholder="e.g. 4512" />
                    <label className="a-label" style={{ marginTop: '0.8rem' }}>Canvas user ID</label>
                    <input className="a-input" value={cvUser} onChange={(e) => setCvUser(e.target.value)} placeholder="the student's Canvas user id" />
                    <label className="a-label" style={{ marginTop: '0.8rem' }}>API token (blank if set server-side)</label>
                    <input className="a-input" type="password" value={cvToken} onChange={(e) => setCvToken(e.target.value)} placeholder="CANVAS_API_TOKEN env fallback" />
                    <button className="btn btn-primary a-cta" disabled={!cvCourse.trim() || !cvUser.trim() || cvBusy} onClick={canvasList}>
                      {cvBusy ? 'Listing…' : 'List submissions'}
                    </button>
                    {cvSubs && cvSubs.length === 0 && (
                      <div className="extract-meta" style={{ marginTop: '0.6rem' }}>No eligible submissions found (minimum 50 words).</div>
                    )}
                  </>
                )}

                {/* ── Blackboard ── */}
                {source === 'blackboard' && (
                  <div className="bb-note">
                    <p>
                      There's no Blackboard API integration in the backend — a form here would be
                      decoration. The working path: in Blackboard, open the assignment →
                      <em> Download submissions</em> (exports .docx/.pdf/.txt files), then bring
                      those files in through the upload tab.
                    </p>
                    <button className="btn btn-primary" onClick={() => setSource('file')}>
                      <Icon name="upload" />Go to file upload
                    </button>
                  </div>
                )}

                {/* ── Turnitin CSV ── */}
                {source === 'turnitin' && (
                  <>
                    <label className="a-label">Course ID</label>
                    {ttCourses.length > 0 ? (
                      <select className="a-select" value={ttCourse} onChange={(e) => setTtCourse(e.target.value)}>
                        <option value="">— select course —</option>
                        {ttCourses.map((c) => <option key={c.course_id} value={c.course_id}>{c.name}</option>)}
                      </select>
                    ) : (
                      <input className="a-input" value={ttCourse} onChange={(e) => setTtCourse(e.target.value)} placeholder="course id (no courses registered yet)" />
                    )}
                    <label className="a-label" style={{ marginTop: '0.8rem' }}>Turnitin roster export (.csv)</label>
                    <input className="a-input" type="file" accept=".csv" onChange={(e) => e.target.files[0] && turnitinUpload(e.target.files[0])} />
                    <div className="extract-meta" style={{ marginTop: '0.6rem' }}>
                      Creates student roster entries from the CSV metadata — it carries no paper
                      text, so no baselines and no scores come from this import.
                    </div>
                  </>
                )}

                {error && <div className="dash-error" style={{ marginTop: '0.9rem' }}>{error}</div>}
              </div>
            </div>

            {/* ── Results ── */}
            <div className="analyze-results">
              {/* Canvas listing renders in the results column — it needs the width */}
              {source === 'canvas' && cvSubs && cvSubs.length > 0 && (
                <div className="section-card">
                  <div className="section-head"><span className="section-title">Canvas submissions</span><span className="section-title-meta">{cvSubs.length}</span></div>
                  {cvSubs.map((s) => (
                    <div className="cv-row" key={s.canvas_submission_id}>
                      <div className="cv-row-main">
                        <div className="cv-row-title">
                          {s.assignment_name}
                          {s.already_imported && <span className="baseline-pill strong" style={{ marginLeft: '0.5rem' }}><span className="bp-dot" />in baseline</span>}
                        </div>
                        <div className="cv-row-meta">{s.word_count} words{s.submitted_at ? ` · ${s.submitted_at.slice(0, 10)}` : ''}</div>
                        <div className="cv-row-preview">{s.preview}</div>
                        {cvRowStatus[s.canvas_submission_id] && (
                          <div className="cv-row-status">{cvRowStatus[s.canvas_submission_id]}</div>
                        )}
                      </div>
                      <div className="cv-row-actions">
                        <button className="btn btn-primary" onClick={() => canvasAnalyze(s)}>Analyze</button>
                        <button className="btn btn-ghost" disabled={s.already_imported} onClick={() => canvasImport(s)}>Import to baseline</button>
                      </div>
                    </div>
                  ))}
                </div>
              )}

              {/* Baseline outcomes */}
              {baselineResult && baselineResult.kind === 'single' && (
                <div className="section-card explain-card no_action" style={{ padding: '1.1rem 1.4rem' }}>
                  <div className="explain-headline">Added to baseline</div>
                  <p className="explain-summary">
                    <span style={{ textTransform: 'capitalize' }}>{shortLabel(studentId)}</span> now has {baselineResult.data.sample_count} sample{baselineResult.data.sample_count === 1 ? '' : 's'}
                    {typeof baselineResult.data.purity === 'number' ? ` · purity ${fmtScore(baselineResult.data.purity)}` : ''}.
                  </p>
                </div>
              )}
              {baselineResult && baselineResult.kind === 'batch' && (
                <div className="section-card" style={{ padding: '1.1rem 1.4rem' }}>
                  <div className="explain-headline">Batch upload result</div>
                  <p className="explain-summary">
                    Imported {baselineResult.data.imported} · duplicates skipped {baselineResult.data.skipped_duplicates}
                    {baselineResult.data.drift_holds && baselineResult.data.drift_holds.length > 0 ? ` · held by drift gate ${baselineResult.data.drift_holds.length}` : ''}
                  </p>
                  {(baselineResult.data.errors || []).map((e, i) => <div className="dash-error" key={i} style={{ marginTop: '0.4rem' }}>{e}</div>)}
                  {(baselineResult.data.drift_holds || []).map((h, i) => (
                    <div className="extract-meta" key={i}>
                      {h.filename || h.canvas_submission_id}: held — deviates from this student's established baseline; review before forcing it in.
                    </div>
                  ))}
                </div>
              )}

              {/* Turnitin outcome */}
              {ttResult && (
                <div className="section-card" style={{ padding: '1.1rem 1.4rem' }}>
                  <div className="explain-headline">Turnitin roster import</div>
                  <p className="explain-summary">
                    {ttResult.total_rows} rows · {ttResult.matched_students} matched · {ttResult.created_students} students created
                    · {ttResult.unmatched_rows} unmatched — roster stubs only (the CSV carries no paper text).
                  </p>
                  {(ttResult.errors || []).map((e, i) => <div className="dash-error" key={i}>{e}</div>)}
                </div>
              )}

              {!result && !submitting && !baselineResult && !ttResult && !(source === 'canvas' && cvSubs) && (
                <div className="section-card"><div className="empty-state"><h3>No analysis yet</h3><p>Pick a source on the left — paste, a file, or Canvas — and the real scoring output appears here.</p></div></div>
              )}
              {submitting && !result && (
                <div className="section-card"><div className="empty-state"><p>Working…</p></div></div>
              )}

              {result && (
                <>
                  <div className={'rec-banner ' + (am ? am.cls : '')}>
                    <div>
                      <div className="rec-banner-label">Recommended action</div>
                      <div className="rec-banner-action">{am.label}</div>
                    </div>
                    <div className="rec-banner-rationale">{rec.rationale}</div>
                  </div>

                  <div className="stats-row" style={{ gridTemplateColumns: 'repeat(3, 1fr)' }}>
                    <StatMini label="Deviation" value={fmtScore(auth.deviation_score)} />
                    <StatMini label="Authorship probability" value={fmtScore(auth.authorship_probability)} />
                    <StatMini label="Peer-relative (LLR)" value={auth.llr_deviation_score == null ? 'n/a' : fmtScore(auth.llr_deviation_score)} />
                  </div>

                  <div className="research-links">
                    Deep-dive this analysis:&nbsp;
                    <a href={`interference.html${researchQS}`}>Interference</a> ·{' '}
                    <a href={`quantum.html${researchQS}`}>Quantum State</a> ·{' '}
                    <a href={`fingerprint.html${researchQS}`}>Fingerprint</a>
                  </div>

                  {explain && (
                    <div className={'section-card explain-card ' + (am ? am.cls : '')}>
                      <div className="explain-headline">
                        {explain.verdict}
                        {explain.ghostwriting_signal && <span className="explain-note ai">ghostwriting signal</span>}
                      </div>
                      <p className="explain-summary">{explain.summary}</p>
                      {explain.top_reasons && explain.top_reasons.length > 0 && (
                        <>
                          <div className="explain-section-title">What the system noticed</div>
                          <ul className="explain-list">{explain.top_reasons.map((o, i) => <li key={i}>{o}</li>)}</ul>
                        </>
                      )}
                      {explain.confidence_note && <div className="explain-confidence">{explain.confidence_note}</div>}
                    </div>
                  )}

                  {arc && (
                    <div className="section-card">
                      <div className="section-head">
                        <span className="section-title">Tension Arc <span className="section-title-meta">κ = {fmtScore(arc.catastrophe_index)}</span></span>
                        <span className={'arc-flag-badge ' + arc.arc_flag}>{ARC_FLAG_LABEL[arc.arc_flag] || arc.arc_flag}</span>
                      </div>
                      <div className="arc-canvas-wrap">
                        <canvas ref={canvasRef} />
                        <div className="tension-hover" ref={hoverRef} />
                      </div>
                      <div className="arc-caption">{arc.arc_flag_reason}</div>
                    </div>
                  )}

                  <div className="section-card">
                    <div className="section-head"><span className="section-title">Tier breakdown</span></div>
                    <div className="tier-bars">
                      {TIERS.map((t) => {
                        const v = tierBreakdown[t.key];
                        const pct = v == null ? 50 : Math.round(v * 100);
                        return (
                          <div className="tier-bar-row" key={t.key}>
                            <div className="tier-bar-label">{t.name}</div>
                            <div className="tier-bar-track"><div className="tier-bar-fill" style={{ width: `${pct}%` }} /></div>
                            <div className="tier-bar-val">{v == null ? '—' : v.toFixed(2)}</div>
                          </div>
                        );
                      })}
                    </div>
                  </div>

                  {topFeatures.length > 0 && (
                    <div className="section-card">
                      <div className="section-head"><span className="section-title">Contributing features</span></div>
                      <div className="signal-list" style={{ padding: '1rem 1.4rem' }}>
                        {topFeatures.map((f, i) => (
                          <div className="signal-item" key={i}>
                            <span className="signal-name">{f.name || f.code} <span style={{ color: 'var(--text-muted)', fontWeight: 400 }}>· T{f.tier}</span></span>
                            <span className={'signal-delta ' + (f.direction === 'destructive' ? 'bad' : 'warn')}>{f.direction === 'destructive' ? '↓' : '✓'} Δ{fmtScore(f.delta)}</span>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}
                </>
              )}
            </div>
          </div>
        </div>
      </div>
    </>
  );
}

function ProvenanceSelect({ value, onChange }) {
  return (
    <>
      <label className="a-label" style={{ marginTop: '1rem' }}>Provenance</label>
      <select className="a-select" value={value} onChange={(e) => onChange(e.target.value)}>
        <option value="verified">verified — instructor vouches for authorship</option>
        <option value="proctored">proctored — written under supervision</option>
        <option value="unverified">unverified — self-submitted</option>
      </select>
    </>
  );
}

function StatMini({ label, value }) {
  return (
    <div className="stat-card stat-default">
      <div className="stat-label">{label}</div>
      <div className="stat-value" style={{ fontSize: '1.5rem' }}>{value}</div>
    </div>
  );
}
