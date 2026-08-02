import React from 'react';
import { BB, BB_API, BtnGhost, BtnPrimary, GoldRule, MetaLabel, StatusBadge, fontBody, fontDisplay, fontMono, rowKeyDown } from './components.jsx';

// ════════════════════════════════════════════════════════════════
//  BLUEBOOK — Results Screen
//  Submission review with stylometric & AI integrity scores
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

// ─── Score display ────────────────────────────────────────────────────────────
function ScoreBar({ score }) {
  if (score == null) return (
    <span style={{ fontFamily:fontMono, fontSize:11, color:'rgba(139,155,180,0.5)', letterSpacing:'0.06em' }}>—</span>
  );
  const color = score >= 85 ? '#5EB87C' : score >= 70 ? BB.gold : '#C47A6B';
  return (
    <div style={{ display:'flex', alignItems:'center', gap:8 }}>
      <div style={{ width:44, height:3, background:'rgba(139,155,180,0.18)', position:'relative', flexShrink:0 }}>
        <div style={{ position:'absolute', left:0, top:0, bottom:0, width:`${score}%`, background:color }} />
      </div>
      <span style={{ fontFamily:fontMono, fontSize:11, color, letterSpacing:'0.06em', minWidth:32 }}>
        {score}%
      </span>
    </div>
  );
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
    <div style={{
      padding:'10px 0', borderBottom:'1px solid rgba(201,169,97,0.12)',
      fontFamily:fontBody, fontSize:13, color:BB.fade,
    }}>
      <div style={{ display:'flex', justifyContent:'space-between', marginBottom:4 }}>
        <span style={{ color: c.is_correct ? '#5EB87C' : '#C47A6B', fontFamily:fontMono, fontSize:11, letterSpacing:'0.08em' }}>
          {c.is_correct ? '✓ Verdict correct' : '✗ Verdict overridden'}
        </span>
        <span style={{ fontFamily:fontMono, fontSize:10, color:'rgba(139,155,180,0.6)' }}>
          {c.reviewer || 'Unknown reviewer'} · {relativeTime(c.created_at)}
        </span>
      </div>
      {!c.is_correct && (c.corrected_verdict || c.corrected_action) && (
        <p style={{ margin:'0 0 4px', fontStyle:'italic' }}>
          {c.corrected_verdict && `→ ${c.corrected_verdict}`}
          {c.corrected_verdict && c.corrected_action && ' · '}
          {c.corrected_action && `→ ${c.corrected_action}`}
        </p>
      )}
      {c.notes && <p style={{ margin:0 }}>{c.notes}</p>}
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
  // Disabled ("cold-start") state is keyed on whether an AI score was ever
  // computed, not on uuid presence — a real sealed exam always carries a
  // submission_uuid (threaded into the score call too), so uuid presence
  // alone can't distinguish a cold-start 422 from a genuinely scored
  // submission. aiScore is null exactly when no score was recorded.
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
        <MetaLabel style={{ display:'block', marginBottom:14 }}>Examiner's Correction</MetaLabel>
        <p style={{
          fontFamily:fontBody, fontStyle:'italic', fontSize:14, color:BB.fade,
          padding:'12px 14px', border:'1px solid rgba(201,169,97,0.15)', margin:0,
        }}>
          This submission wasn't scored — no verdict to correct.
        </p>
      </div>
    );
  }

  return (
    <div>
      <MetaLabel style={{ display:'block', marginBottom:14 }}>Examiner's Correction</MetaLabel>

      {history === null ? (
        <p style={{ fontFamily:fontBody, fontStyle:'italic', fontSize:13, color:BB.fade }}>Loading history…</p>
      ) : history.length > 0 ? (
        <div style={{ marginBottom:16, maxHeight:180, overflowY:'auto' }}>
          {history.map(c => <CorrectionHistoryItem key={c.id} c={c} />)}
        </div>
      ) : null}

      <div style={{ display:'flex', gap:10, marginBottom:10 }}>
        <button
          onClick={() => setIsCorrect(true)}
          style={{
            flex:1, padding:'8px 14px', fontFamily:fontMono, fontSize:11, letterSpacing:'0.08em',
            textTransform:'uppercase', cursor:'pointer',
            background: isCorrect === true ? '#5EB87C' : 'transparent',
            color: isCorrect === true ? BB.deep : '#5EB87C',
            border:'1px solid #5EB87C',
          }}
        >Correct</button>
        <button
          onClick={() => setIsCorrect(false)}
          style={{
            flex:1, padding:'8px 14px', fontFamily:fontMono, fontSize:11, letterSpacing:'0.08em',
            textTransform:'uppercase', cursor:'pointer',
            background: isCorrect === false ? '#C47A6B' : 'transparent',
            color: isCorrect === false ? BB.deep : '#C47A6B',
            border:'1px solid #C47A6B',
          }}
        >Incorrect</button>
      </div>

      {isCorrect === false && (
        <div style={{ display:'flex', gap:10, marginBottom:10 }}>
          <select
            value={correctedVerdict}
            onChange={e => setCorrectedVerdict(e.target.value)}
            style={{
              flex:1, padding:'8px 10px', background:'rgba(0,0,0,0.25)',
              border:'1px solid rgba(201,169,97,0.22)', color:BB.cream,
              fontFamily:fontMono, fontSize:12,
            }}
          >
            <option value="">No verdict change</option>
            {VERDICT_OPTIONS.map(v => <option key={v} value={v}>{v}</option>)}
          </select>
          <select
            value={correctedAction}
            onChange={e => setCorrectedAction(e.target.value)}
            style={{
              flex:1, padding:'8px 10px', background:'rgba(0,0,0,0.25)',
              border:'1px solid rgba(201,169,97,0.22)', color:BB.cream,
              fontFamily:fontMono, fontSize:12,
            }}
          >
            <option value="">No action change</option>
            {ACTION_OPTIONS.map(a => <option key={a} value={a}>{a}</option>)}
          </select>
        </div>
      )}

      <textarea
        value={notes}
        onChange={e => setNotes(e.target.value)}
        placeholder="Record observations, decision rationale, or marginal notes…"
        rows={4}
        style={{
          width:'100%', boxSizing:'border-box',
          background:'rgba(0,0,0,0.25)',
          border:'1px solid rgba(201,169,97,0.22)',
          padding:'12px 14px',
          fontFamily:fontBody, fontStyle:'italic', fontSize:15,
          color:BB.cream, outline:'none', resize:'vertical',
          lineHeight:1.65, letterSpacing:'0.01em', marginBottom:10,
        }}
      />

      {error && (
        <p style={{ color:'#C47A6B', fontFamily:fontMono, fontSize:12, margin:'0 0 10px' }}>{error}</p>
      )}

      <BtnPrimary
        onClick={handleFile}
        disabled={isCorrect === null || submitting}
        style={{ padding:'8px 20px', fontSize:14, width:'100%', opacity: (isCorrect === null || submitting) ? 0.5 : 1 }}
      >
        {submitting ? 'Filing…' : 'File Correction'}
      </BtnPrimary>
    </div>
  );
}

// ─── Expanded row detail ──────────────────────────────────────────────────────
function ExpandedRow({ result, onClose }) {
  return (
    <div style={{
      padding:'20px 20px 20px 48px',
      background:'rgba(0,10,28,0.55)',
      borderTop:'1px solid rgba(201,169,97,0.15)',
      animation:'bbFadeIn 0.35s ease both',
    }}>
      <div style={{ display:'grid', gridTemplateColumns:'1fr 1fr', gap:32 }}>
        {/* Left: analysis detail */}
        <div>
          <MetaLabel style={{ display:'block', marginBottom:14 }}>Integrity Analysis</MetaLabel>
          <div style={{ display:'flex', flexDirection:'column', gap:12 }}>
            {[
              { label:'Typing Consistency', score:result.stylometric, note:'Typing rhythm compared with this student’s baseline — higher is more consistent' },
              { label:'Authenticity',       score:result.aiScore,     note:'Higher = more consistent with this student’s own writing (scored via Original)' },
            ].map(({ label, score, note }) => (
              <div key={label}>
                <div style={{ display:'flex', justifyContent:'space-between', marginBottom:6 }}>
                  <span style={{ fontFamily:fontBody, fontSize:15, color:BB.cream }}>{label}</span>
                </div>
                <ScoreBar score={score} />
                <p style={{ fontFamily:fontBody, fontStyle:'italic', fontSize:13, color:BB.fade, margin:'4px 0 0' }}>{note}</p>
              </div>
            ))}
            <div style={{ marginTop:4 }}>
              <GoldRule faint />
              <div style={{ paddingTop:12, display:'flex', gap:24 }}>
                {[
                  { label:'Word Count',  value:`${result.words.toLocaleString()} words` },
                  { label:'Time Spent',  value:`${result.timeMin} minutes` },
                  { label:'Candidate',   value:`No. ${result.candidateId}` },
                ].map(({ label, value }) => (
                  <div key={label}>
                    <MetaLabel style={{ display:'block', marginBottom:4 }}>{label}</MetaLabel>
                    <span style={{ fontFamily:fontBody, fontSize:16, color:BB.cream }}>{value}</span>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </div>

        {/* Right: correction form + history */}
        <div>
          <CorrectionPanel result={result} />
          <div style={{ marginTop:12 }}>
            <BtnGhost onClick={onClose} style={{ padding:'8px 20px', fontSize:14, width:'100%' }}>
              Close
            </BtnGhost>
          </div>
        </div>
      </div>
    </div>
  );
}

// ─── Results Screen ───────────────────────────────────────────────────────────
export function ResultsScreen({ onNavigate }) {
  const [expanded,  setExpanded]  = useResState(null);
  const [statusFilter, setFilter] = useResState('all');
  const [serverResults, setServerResults] = useResState(null);

  React.useEffect(() => {
    let live = true;
    BB_API.listSubmissions().then(list => { if (live) setServerResults(list || []); });
    return () => { live = false; };
  }, []);

  // Live submissions from Original, falling back to the demo set when empty.
  const results = (serverResults && serverResults.length) ? serverResults : (BB_API.isAuthed() ? [] : MOCK_RESULTS);

  const filtered = statusFilter === 'all'
    ? results
    : results.filter(r => r.status === statusFilter);

  const styloScores = results.filter(r => r.stylometric != null);
  const avgStylo = styloScores.length
    ? Math.round(styloScores.reduce((a, r) => a + r.stylometric, 0) / styloScores.length)
    : 0;
  const counts = {
    total:    results.length,
    flagged:  results.filter(r => r.status === 'FLAGGED').length,
    reviewed: results.filter(r => r.status === 'REVIEWED').length,
  };

  return (
    <div style={{ flex:1, overflowY:'auto', padding:'44px 48px', background:BB.deep }}>
      <div style={{ marginBottom:10 }}>
        <h1 style={{ fontFamily:fontDisplay, fontSize:34, color:BB.cream, fontWeight:400, letterSpacing:'0.01em', margin:'0 0 6px' }}>
          Results
        </h1>
        <MetaLabel>
          {counts.total} submissions ·{' '}
          <span style={{ color:'#C47A6B' }}>{counts.flagged} flagged</span>
          {' '}·{' '}
          <span style={{ color:'#5EB87C' }}>{counts.reviewed} reviewed</span>
        </MetaLabel>
      </div>
      <GoldRule double style={{ margin:'20px 0 36px' }} />

      {/* Summary stat row */}
      <div style={{ display:'flex', gap:16, marginBottom:36 }}>
        {[
          { label:'Submitted',  value:results.filter(r=>r.status==='SUBMITTED').length,  color:BB.fade  },
          { label:'Flagged',    value:counts.flagged,                                    color:'#C47A6B'},
          { label:'Reviewed',   value:counts.reviewed,                                   color:'#5EB87C'},
          { label:'Avg Typing Consistency', value:`${avgStylo}%`, color:BB.gold },
        ].map(({ label, value, color }) => (
          <div key={label} style={{
            flex:1, border:'1px solid rgba(201,169,97,0.18)',
            background:BB.oxford, padding:'18px 22px',
          }}>
            <GoldRule style={{ marginBottom:14 }} />
            <p style={{ fontFamily:fontDisplay, fontSize:40, color, margin:'0 0 4px', fontWeight:400, lineHeight:1 }}>
              {value}
            </p>
            <MetaLabel>{label}</MetaLabel>
          </div>
        ))}
      </div>

      {/* Filter tabs */}
      <div style={{ display:'flex', gap:2, marginBottom:16, border:'1px solid rgba(201,169,97,0.2)', alignSelf:'flex-start', width:'fit-content' }}>
        {[['all','All'],['SUBMITTED','Submitted'],['FLAGGED','Flagged'],['REVIEWED','Reviewed']].map(([val,label]) => (
          <button key={val} onClick={() => setFilter(val)} style={{
            fontFamily:fontMono, fontSize:10, letterSpacing:'0.15em',
            textTransform:'uppercase', padding:'8px 18px',
            background: statusFilter === val ? BB.gold : 'transparent',
            color: statusFilter === val ? BB.deep : BB.fade,
            border:'none', cursor:'pointer', transition:'all 0.25s',
          }}>{label}</button>
        ))}
      </div>

      {/* Results table */}
      <div style={{ border:'1px solid rgba(201,169,97,0.2)' }}>
        <div style={{
          display:'grid',
          gridTemplateColumns:'1fr 160px 80px 55px 100px 100px 90px',
          padding:'10px 20px',
          borderBottom:'1px solid rgba(201,169,97,0.35)',
        }}>
          {['Candidate', 'Examination', 'Words', 'Time', 'Typing Consistency', 'Authenticity', 'Status'].map(h => (
            <MetaLabel key={h}>{h}</MetaLabel>
          ))}
        </div>

        {filtered.map((result, i) => (
          <div key={result.id}>
            <div
              style={{
                display:'grid',
                gridTemplateColumns:'1fr 160px 80px 55px 100px 100px 90px',
                padding:'13px 20px', alignItems:'center',
                cursor:'pointer', transition:'background 0.2s',
                background: expanded === result.id ? 'rgba(201,169,97,0.04)' : 'transparent',
                borderLeft: expanded === result.id ? `2px solid ${BB.gold}` : '2px solid transparent',
              }}
              role="button" tabIndex={0}
              aria-expanded={expanded === result.id}
              aria-label={`${result.student} — ${expanded === result.id ? 'hide' : 'view'} integrity analysis`}
              onMouseEnter={e => { if(expanded !== result.id) e.currentTarget.style.background='rgba(201,169,97,0.03)'; }}
              onMouseLeave={e => { if(expanded !== result.id) e.currentTarget.style.background='transparent'; }}
              onClick={() => setExpanded(expanded === result.id ? null : result.id)}
              onKeyDown={rowKeyDown(() => setExpanded(expanded === result.id ? null : result.id))}
            >
              <div>
                <p style={{ fontFamily:fontBody, fontSize:16, color:BB.cream, margin:'0 0 2px' }}>
                  {result.student}
                </p>
                <MetaLabel>No. {result.candidateId} · {result.course}</MetaLabel>
              </div>
              <p style={{ fontFamily:fontBody, fontSize:14, color:BB.fade, margin:0, lineHeight:1.4 }}>
                {result.exam.length > 28 ? result.exam.slice(0,26)+'…' : result.exam}
              </p>
              <MetaLabel>{result.words.toLocaleString()}</MetaLabel>
              <MetaLabel>{result.timeMin}m</MetaLabel>
              <ScoreBar score={result.stylometric} />
              <ScoreBar score={result.aiScore} />
              <StatusBadge status={result.status} />
            </div>
            {expanded === result.id && (
              <ExpandedRow result={result} onClose={() => setExpanded(null)} />
            )}
            {i < filtered.length - 1 && <GoldRule faint />}
          </div>
        ))}
      </div>
    </div>
  );
}
