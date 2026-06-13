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

// ─── Expanded row detail ──────────────────────────────────────────────────────
function ExpandedRow({ result, onClose }) {
  const [notes, setNotes] = useResState('');
  const [marked, setMarked] = useResState(result.status === 'REVIEWED');

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
              { label:'Stylometric Authenticity', score:result.stylometric, note:'Keystroke dynamics vs. baseline' },
              { label:'AI-Authorship Detection',  score:result.aiScore,     note:'Scored via Original platform' },
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

        {/* Right: review notes */}
        <div>
          <MetaLabel style={{ display:'block', marginBottom:14 }}>Examiner's Notes</MetaLabel>
          <textarea
            value={notes}
            onChange={e => setNotes(e.target.value)}
            placeholder="Record observations, decision rationale, or marginal notes…"
            rows={5}
            style={{
              width:'100%', boxSizing:'border-box',
              background:'rgba(0,0,0,0.25)',
              border:'1px solid rgba(201,169,97,0.22)',
              padding:'12px 14px',
              fontFamily:fontBody, fontStyle:'italic', fontSize:15,
              color:BB.cream, outline:'none', resize:'vertical',
              lineHeight:1.65, letterSpacing:'0.01em',
            }}
          />
          <div style={{ display:'flex', gap:10, marginTop:12 }}>
            <BtnGhost onClick={onClose} style={{ padding:'8px 20px', fontSize:14, flex:1 }}>
              Close
            </BtnGhost>
            {!marked ? (
              <BtnPrimary onClick={() => setMarked(true)} style={{ padding:'8px 20px', fontSize:14, flex:1 }}>
                Mark Reviewed
              </BtnPrimary>
            ) : (
              <div style={{
                flex:1, display:'flex', alignItems:'center', justifyContent:'center', gap:8,
                fontFamily:fontMono, fontSize:10, letterSpacing:'0.15em',
                textTransform:'uppercase', color:'#5EB87C',
              }}>
                <Seal size={14} verified /> Reviewed
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

// ─── Results Screen ───────────────────────────────────────────────────────────
function ResultsScreen({ onNavigate }) {
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
          { label:'Avg Stylometric', value:`${avgStylo}%`, color:BB.gold },
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
          {['Candidate', 'Examination', 'Words', 'Time', 'Stylometric', 'AI Score', 'Status'].map(h => (
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
              onMouseEnter={e => { if(expanded !== result.id) e.currentTarget.style.background='rgba(201,169,97,0.03)'; }}
              onMouseLeave={e => { if(expanded !== result.id) e.currentTarget.style.background='transparent'; }}
              onClick={() => setExpanded(expanded === result.id ? null : result.id)}
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

Object.assign(window, { ResultsScreen });
