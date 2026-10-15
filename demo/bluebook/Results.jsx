import React from 'react';
import { BB_API, ORIGINAL_TESTING_NOTICE, WorthALookNote, rowKeyDown } from './components.jsx';
import { Badge, Btn, Page, Stat } from './forms.jsx';
import { AllSubmissionsScreen, ExportByExam, openManageExam } from './Teacher.jsx';

// ════════════════════════════════════════════════════════════════
//  BLUEBOOK: Results screen (a workspace that holds Original)
//  Sealed submissions and their session facts. No score is shown
//  here, so no correction form is either: Original's analysis
//  belongs in Original, where it carries its testing-phase label.
// ════════════════════════════════════════════════════════════════
const { useState: useResState } = React;

const MOCK_RESULTS = [
  { id:'r1', student:'James Thornton',   candidateId:'00042', exam:'Ethics in the Modern World',           course:'PHIL 301A', words:847,  timeMin:72,  stylometric:94, aiScore:97, status:'SUBMITTED'  },
  { id:'r2', student:'Amelia Osei',      candidateId:'00043', exam:'Ethics in the Modern World',           course:'PHIL 301A', words:612,  timeMin:81,  stylometric:61, aiScore:43, status:'FLAGGED'    },
  { id:'r3', student:'Oliver Mackenzie', candidateId:'00044', exam:'Foundations of Political Thought',     course:'POLS 204',  words:1034, timeMin:58,  stylometric:88, aiScore:91, status:'SUBMITTED', graded_at:'2026-01-12T10:00:00Z' },
  { id:'r4', student:'Priya Nair',       candidateId:'00045', exam:'Foundations of Political Thought',     course:'POLS 204',  words:923,  timeMin:55,  stylometric:91, aiScore:89, status:'SUBMITTED', graded_at:'2026-01-12T11:30:00Z' },
  { id:'r5', student:'Samuel Adeyemi',   candidateId:'00046', exam:'Constitutional Principles',            course:'LAW 101',   words:788,  timeMin:88,  stylometric:69, aiScore:41, status:'FLAGGED'    },
  { id:'r6', student:'Catherine Wolff',  candidateId:'00047', exam:'Metaphysics and Epistemology',         course:'PHIL 590',  words:1156, timeMin:114, stylometric:96, aiScore:98, status:'SUBMITTED'  },
  { id:'r7', student:'Hiroshi Tanaka',   candidateId:'00048', exam:'History of Economic Thought',          course:'ECON 203',  words:702,  timeMin:71,  stylometric:85, aiScore:82, status:'SUBMITTED'  },
  { id:'r8', student:'Sofia Lindqvist',  candidateId:'00049', exam:'Ethics in the Modern World',           course:'PHIL 301A', words:941,  timeMin:68,  stylometric:92, aiScore:95, status:'SUBMITTED'  },
];

// The stored status words, said the way the Bluebook Sessions page says them.
const STATUS_LABEL = { SUBMITTED: 'submitted', FLAGGED: 'worth a look', INCONCLUSIVE: 'inconclusive', REVIEWED: 'reviewed' };
const STATUS_TONE  = { SUBMITTED: 'ok', FLAGGED: 'warn', INCONCLUSIVE: '', REVIEWED: 'ok' };

// "Reviewed" means the teacher has graded the exam (graded_at is set), the same
// rule the Original suite uses for "awaiting review". The stored status never
// becomes REVIEWED (the server stores SUBMITTED, FLAGGED or INCONCLUSIVE), so it is
// not what the count, the filter or the pill reads. Stored values are unchanged.
const isReviewed = r => !!r.graded_at;
const stored = r => String(r.status || '').toUpperCase();
// Original's mark stays visible on a graded exam; anything else graded reads "reviewed".
const shownStatus = r => (stored(r) !== 'FLAGGED' && isReviewed(r) ? 'REVIEWED' : stored(r));

function StatusPill({ result }) {
  const status = shownStatus(result);
  return <Badge tone={STATUS_TONE[status] || ''}>{STATUS_LABEL[status] || status.toLowerCase()}</Badge>;
}

// The rows each filter shows, and the counts above it, by one rule.
const FILTERS = {
  all:       () => true,
  // An INCONCLUSIVE exam is a submitted one Original could not read.
  SUBMITTED: r => (stored(r) === 'SUBMITTED' || stored(r) === 'INCONCLUSIVE') && !isReviewed(r),
  FLAGGED:   r => stored(r) === 'FLAGGED',
  REVIEWED:  isReviewed,
};

// The Examiner's Correction form asks whether Original's verdict on a sealed exam
// was right. This screen no longer shows that verdict (Original's reading belongs in
// Original, where it carries the testing-phase label), so there is nothing here to
// mark correct or incorrect and the form is not rendered. Corrections are still filed
// from the classic Analysis page. Bring the form back when stored results return
// (docs/adr/012-ui-design-port.md, open item 4); BB_API.fileCorrection and
// BB_API.listCorrections are kept for it.
function CorrectionNote() {
  return <p className="bb-hint">Corrections to Original's reading are not available on this screen for now.</p>;
}

// ─── Expanded row detail ──────────────────────────────────────────────────────
function ExpandedRow({ result, onClose, onNavigate }) {
  return (
    <div className="bb-rdetail">
      <div className="bb-rdetail-grid">
        {/* Left: the session's own facts */}
        <div>
          <span className="bb-label">Session details</span>
          {result.status === 'FLAGGED' && (
            <p className="bb-hint" style={{ margin: '0 0 .8rem' }}>Marked by Original's comparison with the writing in this student's baseline. {ORIGINAL_TESTING_NOTICE}</p>
          )}
          {result.status === 'INCONCLUSIVE' && (
            <p className="bb-hint" style={{ margin: '0 0 .8rem' }}>Not enough reference writing yet: Original needs at least 3 approved samples from this student before it can compare a new piece, so it makes no observation about this exam. {ORIGINAL_TESTING_NOTICE}</p>
          )}
          <div className="bb-facts">
            {[
              { label:'Word count',  value:`${result.words.toLocaleString()} words` },
              { label:'Time spent',  value:`${result.timeMin} minutes` },
              { label:'Student no.', value:`No. ${result.candidateId}` },
            ].map(({ label, value }) => (
              <div key={label}>
                <span className="bb-label">{label}</span>
                <span className="bb-fact">{value}</span>
              </div>
            ))}
          </div>
        </div>

        {/* Right: where corrections are made, and Close */}
        <div>
          <CorrectionNote />
          {/* The writing itself, with marking and feedback, is read in its examination. */}
          {result.exam_id && onNavigate && (
            <div style={{ marginTop: '.8rem' }}>
              <Btn primary onClick={() => openManageExam(result.exam_id, onNavigate)} style={{ width: '100%', justifyContent: 'center' }}>Read and mark in the examination →</Btn>
            </div>
          )}
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

  const filtered = results.filter(FILTERS[statusFilter] || FILTERS.all);

  // Original's mark (Worth a look / inconclusive) only exists on exams where
  // the teacher switched writing consistency on; hide its count, filter and
  // note when nothing here carries one.
  const showMark = results.some(r => stored(r) === 'FLAGGED' || stored(r) === 'INCONCLUSIVE');

  const counts = {
    total:     results.length,
    submitted: results.filter(FILTERS.SUBMITTED).length,
    flagged:   results.filter(FILTERS.FLAGGED).length,
    reviewed:  results.filter(FILTERS.REVIEWED).length,
  };

  const nSubs = `${counts.total} submission${counts.total === 1 ? '' : 's'}`;
  if (loadError) return <Page eyebrow="Your workspace" title="Submissions"><div role="alert" className="bb-error">{loadError}</div></Page>;
  return (
    <Page
      eyebrow="Your workspace"
      title="Submissions"
      meta={serverResults === null && BB_API.isAuthed() ? 'Loading…' : showMark
        ? `${nSubs} · ${counts.flagged} worth a look · ${counts.reviewed} reviewed`
        : `${nSubs} · ${counts.reviewed} reviewed`}
    >
      <div className={showMark ? 'bb-grid cols-3' : 'bb-grid cols-2'} style={{ marginBottom: '1.5rem' }}>
        <Stat value={counts.submitted} label="Submitted" />
        {showMark && <Stat value={counts.flagged} label="Worth a look" />}
        <Stat value={counts.reviewed} label="Reviewed" />
      </div>

      {BB_API.isAuthed() && <ExportByExam />}

      {/* This screen shows Original's mark (a count, a filter, a status), so it
          always says what the mark is and that Original is in testing. */}
      {showMark && <WorthALookNote />}

      <div className="bb-filter" role="group" aria-label="Show submissions">
        {[['all','All'],['SUBMITTED','Submitted'],...(showMark ? [['FLAGGED','Worth a look']] : []),['REVIEWED','Reviewed']].map(([val,label]) => (
          <button key={val} type="button" aria-pressed={statusFilter === val} onClick={() => setFilter(val)}>{label}</button>
        ))}
      </div>

      <div className="bb-results">
        <div className="bb-rgrid bb-rhead">
          {['Student', 'Examination', 'Words', 'Time', 'Status'].map(h => (
            <span key={h}>{h}</span>
          ))}
        </div>

        {filtered.length === 0 && (
          <p role="status" className="bb-empty" style={{ padding: '1rem' }}>
            {serverResults === null && BB_API.isAuthed() ? 'Loading submissions…'
              : results.length ? 'Nothing matches this filter.' : 'No sealed exams yet. They appear here as students submit them.'}
          </p>
        )}
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
              <span><StatusPill result={result} /></span>
            </div>
            {expanded === result.id && (
              <ExpandedRow result={result} onClose={() => setExpanded(null)} onNavigate={onNavigate} />
            )}
          </div>
        ))}
      </div>
    </Page>
  );
}
