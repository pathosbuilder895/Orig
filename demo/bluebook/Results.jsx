import React from 'react';
import { BB_API, rowKeyDown } from './components.jsx';
import { Badge, Btn, Page, Stat } from './forms.jsx';
import { AllSubmissionsScreen } from './Teacher.jsx';

// ════════════════════════════════════════════════════════════════
//  BLUEBOOK: Results screen (a workspace that holds Original)
//  Sealed submissions, their session facts, and the examiner's
//  correction form. No score is shown here: Original's analysis
//  belongs in Original, where it carries its testing-phase label.
// ════════════════════════════════════════════════════════════════
const { useState: useResState } = React;

const MOCK_RESULTS = [
  { id:'r1', student:'James Thornton',   candidateId:'00042', exam:'Ethics in the Modern World',           course:'PHIL 301A', words:847,  timeMin:72,  stylometric:94, aiScore:97, status:'SUBMITTED'  },
  { id:'r2', student:'Amelia Osei',      candidateId:'00043', exam:'Ethics in the Modern World',           course:'PHIL 301A', words:612,  timeMin:81,  stylometric:61, aiScore:43, status:'FLAGGED'    },
  { id:'r3', student:'Oliver Mackenzie', candidateId:'00044', exam:'Foundations of Political Thought',     course:'POLS 204',  words:1034, timeMin:58,  stylometric:88, aiScore:91, status:'REVIEWED'   },
  { id:'r4', student:'Priya Nair',       candidateId:'00045', exam:'Foundations of Political Thought',     course:'POLS 204',  words:923,  timeMin:55,  stylometric:91, aiScore:89, status:'REVIEWED'   },
  { id:'r5', student:'Samuel Adeyemi',   candidateId:'00046', exam:'Constitutional Principles',            course:'LAW 101',   words:788,  timeMin:88,  stylometric:69, aiScore:41, status:'FLAGGED'    },
  { id:'r6', student:'Catherine Wolff',  candidateId:'00047', exam:'Metaphysics and Epistemology',         course:'PHIL 590',  words:1156, timeMin:114, stylometric:96, aiScore:98, status:'SUBMITTED'  },
  { id:'r7', student:'Hiroshi Tanaka',   candidateId:'00048', exam:'History of Economic Thought',          course:'ECON 203',  words:702,  timeMin:71,  stylometric:85, aiScore:82, status:'SUBMITTED'  },
  { id:'r8', student:'Sofia Lindqvist',  candidateId:'00049', exam:'Ethics in the Modern World',           course:'PHIL 301A', words:941,  timeMin:68,  stylometric:92, aiScore:95, status:'SUBMITTED'  },
];

// The stored status words, said the way the Bluebook Sessions page says them.
const STATUS_LABEL = { SUBMITTED: 'submitted', FLAGGED: 'worth a look', REVIEWED: 'reviewed' };
const STATUS_TONE  = { SUBMITTED: 'ok', FLAGGED: 'warn', REVIEWED: 'ok' };
function StatusPill({ status }) {
  return <Badge tone={STATUS_TONE[status] || ''}>{STATUS_LABEL[status] || String(status || '').toLowerCase()}</Badge>;
}

const { useState: useCPState, useEffect: useCPEffect } = React;

const VERDICT_OPTIONS = ['authentic', 'uncertain', 'anomalous'];
const ACTION_OPTIONS = ['no_action', 'monitor', 'schedule_conversation', 'escalate'];

function relativeTime(iso) {
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return iso;
  const diffMin = Math.round((Date.now() - then) / 60000);
  if (diffMin < 1) return 'just now';
  if (diffMin < 60) return `${diffMin}m ago`;
  const diffH = Math.round(diffMin / 60);
  if (diffH < 24) return `${diffH}h ago`;
  return `${Math.round(diffH / 24)}d ago`;
}

function CorrectionHistoryItem({ c }) {
  return (
    <div className="bb-corr-item">
      <div className="bb-corr-line">
        <span className={c.is_correct ? 'ok' : 'bad'}>
          {c.is_correct ? '✓ Verdict correct' : '✗ Verdict overridden'}
        </span>
        <span className="who">
          {c.reviewer || 'Unknown reviewer'} · {relativeTime(c.created_at)}
        </span>
      </div>
      {!c.is_correct && (c.corrected_verdict || c.corrected_action) && (
        <p className="moved">
          {c.corrected_verdict && `→ ${c.corrected_verdict}`}
          {c.corrected_verdict && c.corrected_action && ' · '}
          {c.corrected_action && `→ ${c.corrected_action}`}
        </p>
      )}
      {c.notes && <p>{c.notes}</p>}
    </div>
  );
}

function CorrectionPanel({ result }) {
  const [history,       setHistory]       = useCPState(null);
  const [isCorrect,     setIsCorrect]     = useCPState(null); // null = unset, true/false once chosen
  const [correctedVerdict, setCorrectedVerdict] = useCPState('');
  const [correctedAction,  setCorrectedAction]  = useCPState('');
  const [notes,          setNotes]         = useCPState('');
  const [submitting,     setSubmitting]    = useCPState(false);
  const [error,          setError]         = useCPState(null);

  const submissionId = result.submission_uuid;
  // Disabled ("cold-start") state is keyed on whether a score was ever
  // computed, not on uuid presence: a real sealed exam always carries a
  // submission_uuid (threaded into the score call too), so uuid presence
  // alone can't distinguish a cold-start 422 from a genuinely scored
  // submission. aiScore is null exactly when no score was recorded. The
  // score itself is not displayed; it only decides whether there is a
  // verdict to correct.
  const hasScore = result.aiScore != null;

  useCPEffect(() => {
    if (!hasScore) return;
    let live = true;
    BB_API.listCorrections(submissionId).then(items => { if (live) setHistory(items || []); });
    return () => { live = false; };
  }, [hasScore, submissionId]);

  function resetForm() {
    setIsCorrect(null);
    setCorrectedVerdict('');
    setCorrectedAction('');
    setNotes('');
  }

  async function handleFile() {
    if (isCorrect === null || !submissionId) return;
    setSubmitting(true);
    setError(null);
    try {
      const identity = BB_API.identity();
      const created = await BB_API.fileCorrection(submissionId, {
        isCorrect,
        correctedVerdict: isCorrect ? null : (correctedVerdict || null),
        correctedAction: isCorrect ? null : (correctedAction || null),
        reviewer: identity.name || null,
        notes: notes || null,
      });
      setHistory(h => [created, ...(h || [])]);
      resetForm();
    } catch (e) {
      setError(String(e && e.message || e));
    } finally {
      setSubmitting(false);
    }
  }

  if (!hasScore) {
    return (
      <div>
        <span className="bb-label">Examiner's Correction</span>
        <p className="bb-corr-empty">
          This submission wasn't scored — no verdict to correct.
        </p>
      </div>
    );
  }

  return (
    <div>
      <span className="bb-label">Examiner's Correction</span>

      {history === null ? (
        <p className="bb-hint">Loading history…</p>
      ) : history.length > 0 ? (
        <div className="bb-corr-history">
          {history.map(c => <CorrectionHistoryItem key={c.id} c={c} />)}
        </div>
      ) : null}

      <div className="bb-toggle-row">
        <button type="button" className="bb-toggle ok" aria-pressed={isCorrect === true} onClick={() => setIsCorrect(true)}>Correct</button>
        <button type="button" className="bb-toggle bad" aria-pressed={isCorrect === false} onClick={() => setIsCorrect(false)}>Incorrect</button>
      </div>

      {isCorrect === false && (
        <div className="bb-toggle-row">
          <select className="bb-input" aria-label="Corrected verdict" value={correctedVerdict} onChange={e => setCorrectedVerdict(e.target.value)}>
            <option value="">No verdict change</option>
            {VERDICT_OPTIONS.map(v => <option key={v} value={v}>{v}</option>)}
          </select>
          <select className="bb-input" aria-label="Corrected action" value={correctedAction} onChange={e => setCorrectedAction(e.target.value)}>
            <option value="">No action change</option>
            {ACTION_OPTIONS.map(a => <option key={a} value={a}>{a}</option>)}
          </select>
        </div>
      )}

      <textarea
        className="bb-input"
        value={notes}
        onChange={e => setNotes(e.target.value)}
        placeholder="Record observations, decision rationale, or marginal notes…"
        rows={4}
        aria-label="Notes for this correction"
      />

      {error && <p className="bb-error" role="alert" style={{ marginTop: '.6rem' }}>{error}</p>}

      <Btn primary onClick={handleFile} disabled={isCorrect === null || submitting} style={{ marginTop: '.8rem', width: '100%', justifyContent: 'center' }}>
        {submitting ? 'Filing…' : 'File Correction'}
      </Btn>
    </div>
  );
}

// ─── Expanded row detail ──────────────────────────────────────────────────────
function ExpandedRow({ result, onClose }) {
  return (
    <div className="bb-rdetail">
      <div className="bb-rdetail-grid">
        {/* Left: the session's own facts */}
        <div>
          <span className="bb-label">Session details</span>
          {result.status === 'FLAGGED' && (
            <p className="bb-hint" style={{ margin: '0 0 .8rem' }}>Marked by Original's comparison with this student's approved writing.</p>
          )}
          <div className="bb-facts">
            {[
              { label:'Word count',  value:`${result.words.toLocaleString()} words` },
              { label:'Time spent',  value:`${result.timeMin} minutes` },
              { label:'Candidate',   value:`No. ${result.candidateId}` },
            ].map(({ label, value }) => (
              <div key={label}>
                <span className="bb-label">{label}</span>
                <span className="bb-fact">{value}</span>
              </div>
            ))}
          </div>
        </div>

        {/* Right: correction form + history */}
        <div>
          <CorrectionPanel result={result} />
          <div style={{ marginTop: '.8rem' }}>
            <Btn onClick={onClose} style={{ width: '100%', justifyContent: 'center' }}>Close</Btn>
          </div>
        </div>
      </div>
    </div>
  );
}

// ─── Results Screen ───────────────────────────────────────────────────────────
export function ResultsScreen({ onNavigate }) {
  // A workspace without Original has no scores: show its submissions and
  // their text instead of an empty score dashboard.
  if (BB_API.isAuthed() && !BB_API.hasOriginal()) return <AllSubmissionsScreen />;
  return <ScoredResultsScreen onNavigate={onNavigate} />;
}

function ScoredResultsScreen({ onNavigate }) {
  const [expanded,  setExpanded]  = useResState(null);
  const [statusFilter, setFilter] = useResState('all');
  const [serverResults, setServerResults] = useResState(null);

  const [loadError, setLoadError] = useResState('');
  React.useEffect(() => {
    let live = true;
    BB_API.listSubmissions().then(list => { if (live) setServerResults(list || []); }).catch(err => { if (live) setLoadError(err.message); });
    return () => { live = false; };
  }, []);

  // Live submissions from Original, falling back to the demo set when empty.
  const results = (serverResults && serverResults.length) ? serverResults : (BB_API.isAuthed() ? [] : MOCK_RESULTS);

  const filtered = statusFilter === 'all'
    ? results
    : results.filter(r => r.status === statusFilter);

  const counts = {
    total:    results.length,
    flagged:  results.filter(r => r.status === 'FLAGGED').length,
    reviewed: results.filter(r => r.status === 'REVIEWED').length,
  };

  if (loadError) return <div role="alert" className="bb-error">{loadError}</div>;
  return (
    <Page
      eyebrow="Your workspace"
      title="Results"
      meta={`${counts.total} submissions · ${counts.flagged} worth a look · ${counts.reviewed} reviewed`}
    >
      <div className="bb-grid cols-3" style={{ marginBottom: '1.5rem' }}>
        <Stat value={results.filter(r => r.status === 'SUBMITTED').length} label="Submitted" />
        <Stat value={counts.flagged} label="Worth a look" />
        <Stat value={counts.reviewed} label="Reviewed" />
      </div>

      {counts.flagged > 0 && (
        <p className="bb-hint" style={{ margin: '0 0 .8rem' }}>Worth a look: marked by Original's comparison with this student's approved writing.</p>
      )}

      <div className="bb-filter" role="group" aria-label="Show submissions">
        {[['all','All'],['SUBMITTED','Submitted'],['FLAGGED','Worth a look'],['REVIEWED','Reviewed']].map(([val,label]) => (
          <button key={val} type="button" aria-pressed={statusFilter === val} onClick={() => setFilter(val)}>{label}</button>
        ))}
      </div>

      <div className="bb-results">
        <div className="bb-rgrid bb-rhead">
          {['Candidate', 'Examination', 'Words', 'Time', 'Status'].map(h => (
            <span key={h}>{h}</span>
          ))}
        </div>

        {filtered.map(result => (
          <div key={result.id}>
            <div
              className="bb-rgrid bb-rrow"
              role="button" tabIndex={0}
              aria-expanded={expanded === result.id}
              aria-label={`${result.student}, ${expanded === result.id ? 'hide' : 'show'} session details`}
              onClick={() => setExpanded(expanded === result.id ? null : result.id)}
              onKeyDown={rowKeyDown(() => setExpanded(expanded === result.id ? null : result.id))}
            >
              <div>
                <p className="bb-rname">{result.student}</p>
                <span className="bb-rsub">No. {result.candidateId} · {result.course}</span>
              </div>
              <p className="bb-rexam">
                {result.exam.length > 28 ? result.exam.slice(0,26)+'…' : result.exam}
              </p>
              <span className="bb-rnum">{result.words.toLocaleString()}</span>
              <span className="bb-rnum">{result.timeMin}m</span>
              <span><StatusPill status={result.status} /></span>
            </div>
            {expanded === result.id && (
              <ExpandedRow result={result} onClose={() => setExpanded(null)} />
            )}
          </div>
        ))}
      </div>
    </Page>
  );
}
