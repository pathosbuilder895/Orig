// ════════════════════════════════════════════════════════════════
//  BLUEBOOK — Courses Screen
// ════════════════════════════════════════════════════════════════
const { useState: useCState } = React;

const MOCK_COURSES_DATA = [
  { id:'c1', code:'PHIL 301A', name:'Ethics in the Modern World',           term:'Michaelmas 2026', students:23, exams:3, active:true  },
  { id:'c2', code:'POLS 204',  name:'Foundations of Political Thought',     term:'Michaelmas 2026', students:31, exams:2, active:true  },
  { id:'c3', code:'PHIL 590',  name:'Metaphysics and Epistemology',         term:'Michaelmas 2026', students:12, exams:1, active:true  },
  { id:'c4', code:'LAW 101',   name:'Constitutional Principles',            term:'Michaelmas 2026', students:45, exams:2, active:false },
  { id:'c5', code:'ECON 203',  name:'History of Economic Thought',          term:'Michaelmas 2026', students:18, exams:1, active:false },
];

function CoursesScreen({ onNavigate }) {
  const [showNew, setShowNew] = useCState(false);
  const [newCode, setNewCode] = useCState('');
  const [newName, setNewName] = useCState('');
  const [serverCourses, setServerCourses] = useCState(null);
  const [creating, setCreating] = useCState(false);

  const reload = () => BB_API.listCourses().then(l => setServerCourses(l || []));
  React.useEffect(() => {
    let live = true;
    BB_API.listCourses().then(l => { if (live) setServerCourses(l || []); });
    return () => { live = false; };
  }, []);
  const courses = (serverCourses && serverCourses.length)
    ? serverCourses : (BB_API.isAuthed() ? [] : MOCK_COURSES_DATA);

  async function handleCreate() {
    if (!newCode.trim() || !newName.trim() || creating) return;
    setCreating(true);
    try {
      await BB_API.createCourse({
        code: newCode.trim(), name: newName.trim(),
        term: 'Michaelmas Term 2026', status: 'ACTIVE',
      });
      await reload();
      setNewCode(''); setNewName(''); setShowNew(false);
    } catch (e) { console.warn('course create failed', e && e.message); }
    setCreating(false);
  }

  return (
    <div style={{ flex:1, overflowY:'auto', padding:'44px 48px', background:BB.deep }}>
      <div style={{ display:'flex', justifyContent:'space-between', alignItems:'flex-end', marginBottom:10 }}>
        <div>
          <h1 style={{ fontFamily:fontDisplay, fontSize:34, color:BB.cream, fontWeight:400, letterSpacing:'0.01em', margin:'0 0 6px' }}>
            Courses
          </h1>
          <MetaLabel>{courses.length} courses · Michaelmas Term 2026</MetaLabel>
        </div>
        <BtnPrimary onClick={() => setShowNew(v => !v)} style={{ padding:'10px 28px', fontSize:16 }}>
          + New Course
        </BtnPrimary>
      </div>
      <GoldRule double style={{ margin:'20px 0 36px' }} />

      {/* Inline new-course form */}
      {showNew && (
        <div style={{
          border:'1px solid rgba(201,169,97,0.35)', padding:'24px 28px',
          marginBottom:28, background:BB.oxford,
          animation:'bbFadeIn 0.4s ease both',
        }}>
          <MetaLabel style={{ display:'block', marginBottom:18 }}>New Course</MetaLabel>
          <div style={{ display:'grid', gridTemplateColumns:'140px 1fr', gap:24, marginBottom:22 }}>
            <div>
              <MetaLabel style={{ display:'block', marginBottom:8 }}>Course Code</MetaLabel>
              <input value={newCode} onChange={e => setNewCode(e.target.value)}
                placeholder="PHIL 401"
                style={{
                  width:'100%', background:'transparent', border:'none',
                  borderBottom:'1px solid rgba(201,169,97,0.4)', padding:'8px 2px',
                  fontFamily:fontBody, fontSize:16, color:BB.cream, outline:'none',
                }} />
            </div>
            <div>
              <MetaLabel style={{ display:'block', marginBottom:8 }}>Course Name</MetaLabel>
              <input value={newName} onChange={e => setNewName(e.target.value)}
                placeholder="e.g. Philosophy of Language"
                style={{
                  width:'100%', background:'transparent', border:'none',
                  borderBottom:'1px solid rgba(201,169,97,0.4)', padding:'8px 2px',
                  fontFamily:fontBody, fontSize:16, color:BB.cream, outline:'none',
                }} />
            </div>
          </div>
          <div style={{ display:'flex', gap:12, justifyContent:'flex-end' }}>
            <BtnGhost onClick={() => setShowNew(false)} style={{ padding:'8px 24px', fontSize:15 }}>
              Cancel
            </BtnGhost>
            <BtnPrimary
              disabled={!newCode.trim() || !newName.trim() || creating}
              onClick={handleCreate}
              style={{ padding:'8px 28px', fontSize:15 }}
            >{creating ? 'Creating…' : 'Create Course'}</BtnPrimary>
          </div>
        </div>
      )}

      <div style={{ border:'1px solid rgba(201,169,97,0.2)' }}>
        <div style={{ display:'grid', gridTemplateColumns:'100px 1fr 140px 80px 60px 80px 80px', padding:'10px 20px', borderBottom:'1px solid rgba(201,169,97,0.35)' }}>
          {['Code', 'Course Name', 'Term', 'Students', 'Exams', 'Status', ''].map(h => (
            <MetaLabel key={h}>{h}</MetaLabel>
          ))}
        </div>
        {courses.map((course, i) => (
          <div key={course.id}>
            <div
              style={{ display:'grid', gridTemplateColumns:'100px 1fr 140px 80px 60px 80px 80px', padding:'14px 20px', alignItems:'center', cursor:'pointer', transition:'background 0.2s' }}
              onMouseEnter={e => e.currentTarget.style.background='rgba(201,169,97,0.04)'}
              onMouseLeave={e => e.currentTarget.style.background='transparent'}
            >
              <MetaLabel style={{ color:BB.gold }}>{course.code}</MetaLabel>
              <p style={{ fontFamily:fontBody, fontSize:16, color:BB.cream, margin:0 }}>{course.name}</p>
              <MetaLabel>{course.term}</MetaLabel>
              <MetaLabel>{course.students}</MetaLabel>
              <MetaLabel>{course.exams}</MetaLabel>
              <div>
                <StatusBadge status={course.active ? 'ACTIVE' : 'COMPLETED'} pulse={course.active} />
              </div>
              <button style={{ fontFamily:fontMono, fontSize:10, letterSpacing:'0.15em', textTransform:'uppercase', color:BB.gold, background:'none', border:'none', cursor:'pointer' }}>
                Manage →
              </button>
            </div>
            {i < courses.length - 1 && <GoldRule faint />}
          </div>
        ))}
      </div>
    </div>
  );
}

Object.assign(window, { CoursesScreen });
