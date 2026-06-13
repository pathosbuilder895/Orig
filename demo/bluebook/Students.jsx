// ════════════════════════════════════════════════════════════════
//  BLUEBOOK — Students Screen
// ════════════════════════════════════════════════════════════════
const { useState: useStuState } = React;

const MOCK_STUDENTS = [
  { id:'s1', name:'James Thornton',   candidateId:'00042', course:'PHIL 301A', submissions:3, lastActive:'2 hours ago',  flagged:false },
  { id:'s2', name:'Amelia Osei',      candidateId:'00043', course:'PHIL 301A', submissions:2, lastActive:'1 day ago',    flagged:true  },
  { id:'s3', name:'Oliver Mackenzie', candidateId:'00044', course:'POLS 204',  submissions:4, lastActive:'3 hours ago',  flagged:false },
  { id:'s4', name:'Priya Nair',       candidateId:'00045', course:'POLS 204',  submissions:3, lastActive:'5 hours ago',  flagged:false },
  { id:'s5', name:'Samuel Adeyemi',   candidateId:'00046', course:'LAW 101',   submissions:2, lastActive:'1 day ago',    flagged:true  },
  { id:'s6', name:'Catherine Wolff',  candidateId:'00047', course:'PHIL 590',  submissions:1, lastActive:'2 days ago',   flagged:false },
  { id:'s7', name:'Hiroshi Tanaka',   candidateId:'00048', course:'ECON 203',  submissions:2, lastActive:'6 hours ago',  flagged:false },
  { id:'s8', name:'Sofia Lindqvist',  candidateId:'00049', course:'PHIL 301A', submissions:3, lastActive:'4 hours ago',  flagged:false },
  { id:'s9', name:'Marcus Petrov',    candidateId:'00050', course:'POLS 204',  submissions:2, lastActive:'12 hours ago', flagged:false },
  { id:'s10',name:'Zara Okafor',      candidateId:'00051', course:'LAW 101',   submissions:1, lastActive:'3 days ago',   flagged:false },
];

function relTime(iso) {
  if (!iso) return '—';
  const t = Date.parse(iso);
  if (isNaN(t)) return '—';
  const mins = Math.max(0, Math.round((Date.now() - t) / 60000));
  if (mins < 60) return mins <= 1 ? 'just now' : mins + ' minutes ago';
  const hrs = Math.round(mins / 60);
  if (hrs < 24) return hrs + (hrs === 1 ? ' hour ago' : ' hours ago');
  const days = Math.round(hrs / 24);
  return days + (days === 1 ? ' day ago' : ' days ago');
}

function StudentsScreen({ onNavigate }) {
  const [filter, setFilter] = useStuState('all');
  const [subs, setSubs] = useStuState(null);
  React.useEffect(() => {
    let live = true;
    BB_API.listSubmissions().then(l => { if (live) setSubs(l || []); });
    return () => { live = false; };
  }, []);

  // The roster IS the set of students who have sat examinations in this tenant.
  const roster = React.useMemo(() => {
    if (!subs) return null;
    const by = {};
    subs.forEach(s => {
      const key = s.student_id || s.candidate || s.candidateId;
      if (!key) return;
      if (!by[key]) {
        by[key] = {
          id: key, name: s.student || s.candidate || 'Candidate',
          candidateId: s.candidateId || '—', course: s.course || '—',
          submissions: 0, _last: '', flagged: false,
        };
      }
      const r = by[key];
      r.submissions += 1;
      if ((s.status || '').toUpperCase() === 'FLAGGED') r.flagged = true;
      if (s.created_at && s.created_at > r._last) { r._last = s.created_at; r.course = s.course || r.course; }
    });
    return Object.values(by).map(r => ({ ...r, lastActive: relTime(r._last) }));
  }, [subs]);

  const students = (roster && roster.length) ? roster : (BB_API.isAuthed() ? [] : MOCK_STUDENTS);
  const filtered = filter === 'flagged' ? students.filter(s => s.flagged) : students;

  return (
    <div style={{ flex:1, overflowY:'auto', padding:'44px 48px', background:BB.deep }}>
      <div style={{ display:'flex', justifyContent:'space-between', alignItems:'flex-end', marginBottom:10 }}>
        <div>
          <h1 style={{ fontFamily:fontDisplay, fontSize:34, color:BB.cream, fontWeight:400, letterSpacing:'0.01em', margin:'0 0 6px' }}>
            Students
          </h1>
          <MetaLabel>
            {students.length} enrolled ·{' '}
            <span style={{ color:students.filter(s=>s.flagged).length > 0 ? '#C47A6B' : BB.fade }}>
              {students.filter(s=>s.flagged).length} flagged
            </span>
          </MetaLabel>
        </div>
        {/* Filter pills */}
        <div style={{ display:'flex', gap:2, border:'1px solid rgba(201,169,97,0.22)' }}>
          {[['all','All Students'],['flagged','Flagged Only']].map(([val, label]) => (
            <button key={val} onClick={() => setFilter(val)} style={{
              fontFamily:fontMono, fontSize:10, letterSpacing:'0.15em',
              textTransform:'uppercase', padding:'8px 18px',
              background: filter === val ? BB.gold : 'transparent',
              color: filter === val ? BB.deep : BB.fade,
              border:'none', cursor:'pointer',
              transition:'all 0.25s',
            }}>{label}</button>
          ))}
        </div>
      </div>
      <GoldRule double style={{ margin:'20px 0 36px' }} />

      <div style={{ border:'1px solid rgba(201,169,97,0.2)' }}>
        <div style={{ display:'grid', gridTemplateColumns:'1fr 100px 120px 80px 120px 80px', padding:'10px 20px', borderBottom:'1px solid rgba(201,169,97,0.35)' }}>
          {['Name', 'Candidate', 'Course', 'Submissions', 'Last Active', 'Status'].map(h => (
            <MetaLabel key={h}>{h}</MetaLabel>
          ))}
        </div>
        {filtered.map((s, i) => (
          <div key={s.id}>
            <div
              style={{ display:'grid', gridTemplateColumns:'1fr 100px 120px 80px 120px 80px', padding:'13px 20px', alignItems:'center', cursor:'pointer', transition:'background 0.2s' }}
              onMouseEnter={e => e.currentTarget.style.background='rgba(201,169,97,0.04)'}
              onMouseLeave={e => e.currentTarget.style.background='transparent'}
              onClick={() => onNavigate('results')}
            >
              <div style={{ display:'flex', alignItems:'center', gap:10 }}>
                {/* Avatar initials */}
                <div style={{
                  width:28, height:28, border:'1px solid rgba(201,169,97,0.3)',
                  display:'flex', alignItems:'center', justifyContent:'center', flexShrink:0,
                }}>
                  <span style={{ fontFamily:fontMono, fontSize:9, color:BB.gold, letterSpacing:'0.05em' }}>
                    {s.name.split(' ').map(n=>n[0]).join('')}
                  </span>
                </div>
                <span style={{ fontFamily:fontBody, fontSize:16, color:BB.cream }}>{s.name}</span>
              </div>
              <MetaLabel>No. {s.candidateId}</MetaLabel>
              <MetaLabel style={{ color:BB.gold }}>{s.course}</MetaLabel>
              <MetaLabel>{s.submissions}</MetaLabel>
              <MetaLabel>{s.lastActive}</MetaLabel>
              <div>
                {s.flagged
                  ? <StatusBadge status="FLAGGED" />
                  : <StatusBadge status="COMPLETED" />
                }
              </div>
            </div>
            {i < filtered.length - 1 && <GoldRule faint />}
          </div>
        ))}
        {filtered.length === 0 && (
          <div style={{ padding:'40px 20px', textAlign:'center' }}>
            <MetaLabel>No flagged submissions</MetaLabel>
          </div>
        )}
      </div>
    </div>
  );
}

Object.assign(window, { StudentsScreen });
