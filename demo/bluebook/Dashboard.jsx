// ════════════════════════════════════════════════════════════════
//  BLUEBOOK — Dashboard Screens
//  Instructor Overview · Examinations List
// ════════════════════════════════════════════════════════════════

const MOCK_EXAMS = [
  { id:'1', title:'Ethics in the Modern World',         course:'PHIL 301A', duration:90,  submissions:23, status:'ACTIVE'    },
  { id:'2', title:'Foundations of Political Thought',   course:'POLS 204',  duration:60,  submissions:31, status:'COMPLETED' },
  { id:'3', title:'Metaphysics and Epistemology',       course:'PHIL 590',  duration:120, submissions:0,  status:'SCHEDULED' },
  { id:'4', title:'Constitutional Principles',          course:'LAW 101',   duration:90,  submissions:0,  status:'DRAFT'     },
  { id:'5', title:'History of Economic Thought',        course:'ECON 203',  duration:75,  submissions:18, status:'COMPLETED' },
];

const NAV_ITEMS = [
  { label: 'Overview',      screen: 'dashboard' },
  { label: 'Examinations',  screen: 'exams'     },
  { label: 'Courses',       screen: 'courses'   },
  { label: 'Students',      screen: 'students'  },
  { label: 'Results',       screen: 'results'   },
];

// ─── Sidebar ─────────────────────────────────────────────────────────────────
function Sidebar({ activeScreen, onNavigate }) {
  const [hovered, setHovered] = React.useState(null);
  const id = BB_API.identity();
  const displayName = id.authed ? (id.name || 'Signed in') : 'Demo Session';
  const displayRole = id.authed
    ? `${id.role || 'instructor'}${id.tenant ? ' · ' + id.tenant : ''}`
    : 'Bluebook · demo';

  return (
    <aside style={{
      width: 232, flexShrink: 0,
      background: BB.oxford,
      borderRight: '1px solid rgba(201,169,97,0.22)',
      display: 'flex', flexDirection: 'column',
      height: '100vh', position: 'sticky', top: 0,
    }}>
      {/* Brand */}
      <div style={{ padding: '22px 24px 20px' }}>
        <Logotype size={21} onClick={() => onNavigate('dashboard')} />
      </div>
      <GoldRule />

      {/* Nav */}
      <nav style={{ flex: 1, padding: '14px 12px', display: 'flex', flexDirection: 'column', gap: 2 }}>
        {NAV_ITEMS.map(({ label, screen }) => {
          const isActive = activeScreen === screen;
          const isHov    = hovered === label;
          return (
            <button
              key={label}
              onClick={() => screen && onNavigate(screen)}
              onMouseEnter={() => setHovered(label)}
              onMouseLeave={() => setHovered(null)}
              style={{
                display: 'flex', alignItems: 'center', gap: 0,
                padding: '9px 12px',
                background: 'none', border: 'none',
                borderLeft: isActive ? `2px solid ${BB.gold}` : '2px solid transparent',
                fontFamily: fontBody, fontSize: 16,
                color: isActive ? BB.cream : isHov ? BB.gold : BB.fade,
                cursor: screen ? 'pointer' : 'default',
                letterSpacing: '0.02em',
                transition: 'color 0.25s, border-color 0.25s',
                textAlign: 'left',
                opacity: screen ? 1 : 0.45,
              }}
            >{label}</button>
          );
        })}

        <div style={{ margin: '10px 0', borderTop: '1px solid rgba(201,169,97,0.18)' }} />

        {/* Original Analysis — cross-link back to the Original dashboard */}
        <button
          onClick={() => { window.location.href = '../professor.html'; }}
          onMouseEnter={() => setHovered('original')}
          onMouseLeave={() => setHovered(null)}
          style={{
            display: 'flex', alignItems: 'center', justifyContent: 'space-between',
            padding: '9px 12px',
            background: 'none', border: 'none',
            borderLeft: '2px solid transparent',
            fontFamily: fontBody, fontSize: 16,
            color: hovered === 'original' ? BB.gold : BB.fade,
            cursor: 'pointer', letterSpacing: '0.02em',
            opacity: 0.7, transition: 'color 0.25s',
            textAlign: 'left',
          }}
        >
          <span>Original Analysis</span>
          <span style={{ fontSize: 11, opacity: 0.6 }}>↗</span>
        </button>
      </nav>

      {/* User block */}
      <div>
        <GoldRule />
        <div style={{ padding: '16px 24px' }}>
          <p style={{
            fontFamily: fontBody, fontSize: 16,
            color: BB.cream, margin: '0 0 3px',
            letterSpacing: '0.02em',
          }}>{displayName}</p>
          <MetaLabel>{displayRole}</MetaLabel>
        </div>
        <div style={{ padding: '0 12px 16px' }}>
          <button
            onClick={() => { BB_API.logout(); onNavigate('landing'); }}
            style={{
              display: 'block', width: '100%', padding: '8px 12px',
              background: 'none', border: 'none', borderLeft: '2px solid transparent',
              fontFamily: fontBody, fontSize: 15,
              color: 'rgba(139,155,180,0.55)',
              cursor: 'pointer', textAlign: 'left', letterSpacing: '0.02em',
              transition: 'color 0.25s',
            }}
          >Sign Out</button>
        </div>
      </div>
    </aside>
  );
}

// ─── Stat Card ────────────────────────────────────────────────────────────────
function StatCard({ label, value, note }) {
  return (
    <div style={{
      background: BB.oxford,
      border: '1px solid rgba(201,169,97,0.2)',
      padding: '24px 28px 20px',
      flex: 1,
    }}>
      <GoldRule style={{ marginBottom: 20 }} />
      <p style={{
        fontFamily: fontDisplay, fontSize: 52,
        color: BB.cream, margin: '0 0 6px',
        fontWeight: 400, lineHeight: 1,
        letterSpacing: '-0.01em',
      }}>{value}</p>
      <MetaLabel>{label}</MetaLabel>
      {note && <p style={{
        fontFamily: fontMono, fontSize: 10,
        color: BB.gold, letterSpacing: '0.12em',
        marginTop: 6, textTransform: 'uppercase',
      }}>{note}</p>}
    </div>
  );
}

// ─── Dashboard Overview ───────────────────────────────────────────────────────
function DashboardScreen({ onNavigate }) {
  const [serverExams, setServerExams] = React.useState(null);
  const [subs, setSubs] = React.useState([]);
  React.useEffect(() => {
    let live = true;
    BB_API.listExams().then(l => { if (live) setServerExams(l || []); });
    BB_API.listSubmissions().then(l => { if (live) setSubs(l || []); });
    return () => { live = false; };
  }, []);
  const exams = (serverExams && serverExams.length) ? serverExams : (BB_API.isAuthed() ? [] : MOCK_EXAMS);
  const id = BB_API.identity();
  const greetName = id.authed ? (id.name || 'Instructor') : 'Dr. Chen';
  const up = s => (s || '').toUpperCase();
  const nActive    = exams.filter(e => up(e.status) === 'ACTIVE').length;
  const nCompleted = exams.filter(e => up(e.status) === 'COMPLETED').length;
  const nFlagged   = subs.filter(s => up(s.status) === 'FLAGGED').length;

  return (
    <div style={{
      flex: 1, overflowY: 'auto',
      padding: '44px 48px',
      background: BB.deep,
    }}>
      {/* Header */}
      <div style={{ marginBottom: 10 }}>
        <h1 style={{
          fontFamily: fontDisplay, fontSize: 34,
          color: BB.cream, fontWeight: 400,
          letterSpacing: '0.01em', margin: '0 0 6px',
        }}>Good morning, {greetName}.</h1>
        <MetaLabel>Saturday, 17 May · Michaelmas Term</MetaLabel>
      </div>
      <GoldRule double style={{ margin: '20px 0 36px' }} />

      {/* Stat cards */}
      <div style={{ display: 'flex', gap: 16, marginBottom: 44 }}>
        <StatCard label="Examinations"  value={exams.length} />
        <StatCard label="Active"        value={nActive}    note={nActive ? 'live now' : undefined} />
        <StatCard label="Completed"     value={nCompleted} />
        <StatCard label="Flagged"       value={nFlagged}   note={nFlagged ? 'review required' : undefined} />
      </div>

      <Ornament py={0} />

      {/* Recent exams */}
      <div style={{ marginTop: 32 }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: 16 }}>
          <h2 style={{
            fontFamily: fontDisplay, fontSize: 22,
            color: BB.cream, fontWeight: 500,
            letterSpacing: '0.02em', margin: 0,
          }}>Recent Examinations</h2>
          <button onClick={() => onNavigate('exams')} style={{
            fontFamily: fontMono, fontSize: 10,
            letterSpacing: '0.18em', textTransform: 'uppercase',
            color: BB.gold, background: 'none', border: 'none',
            cursor: 'pointer',
          }}>View All →</button>
        </div>

        <div style={{ border: '1px solid rgba(201,169,97,0.2)' }}>
          <div style={{
            display: 'grid',
            gridTemplateColumns: '1fr 100px 110px 80px 80px',
            padding: '10px 20px',
            borderBottom: '1px solid rgba(201,169,97,0.35)',
          }}>
            {['Examination', 'Course', 'Status', 'Duration', 'Submitted'].map(h => (
              <MetaLabel key={h}>{h}</MetaLabel>
            ))}
          </div>
          {exams.slice(0, 4).map((exam, i) => (
            <div key={exam.id}>
              <div style={{
                display: 'grid',
                gridTemplateColumns: '1fr 100px 110px 80px 80px',
                padding: '14px 20px',
                alignItems: 'center',
                cursor: 'pointer',
                transition: 'background 0.2s',
              }}
                onMouseEnter={e => e.currentTarget.style.background = 'rgba(201,169,97,0.04)'}
                onMouseLeave={e => e.currentTarget.style.background = 'transparent'}
                onClick={() => openExam(exam, onNavigate)}
              >
                <div>
                  <p style={{
                    fontFamily: fontBody, fontSize: 16,
                    color: BB.cream, margin: 0, letterSpacing: '0.01em',
                  }}>{exam.title}</p>
                </div>
                <MetaLabel>{exam.course}</MetaLabel>
                <div><StatusBadge status={exam.status} pulse /></div>
                <MetaLabel>{exam.duration}m</MetaLabel>
                <MetaLabel>{exam.submissions || '—'}</MetaLabel>
              </div>
              {i < 3 && <GoldRule faint />}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

// Load an exam's config into the shared slot, then enter its briefing.
function openExam(exam, onNavigate) {
  window.BB_EXAM_CONFIG = {
    id:          exam.id,
    title:       exam.title,
    course:      exam.course,
    courseTitle: exam.course,
    duration:    exam.duration || 90,
    minWords:    exam.minWords != null ? exam.minWords : 600,
    maxWords:    exam.maxWords != null ? exam.maxWords : 1200,
    prompt:      exam.prompt || '',
    candidate:   (window.BB_EXAM_CONFIG && window.BB_EXAM_CONFIG.candidate) || 'Candidate No. 00042',
    ...(exam.conditions || {}),
  };
  onNavigate('briefing');
}

// ─── Exams List Screen ────────────────────────────────────────────────────────
function ExamsScreen({ onNavigate }) {
  // null = loading; real exams from the server, falling back to the demo set.
  const [serverExams, setServerExams] = React.useState(null);
  React.useEffect(() => {
    let live = true;
    BB_API.listExams().then(list => { if (live) setServerExams(list || []); });
    return () => { live = false; };
  }, []);
  const exams = (serverExams && serverExams.length) ? serverExams : (BB_API.isAuthed() ? [] : MOCK_EXAMS);
  const loading = serverExams === null;

  return (
    <div style={{
      flex: 1, overflowY: 'auto',
      padding: '44px 48px',
      background: BB.deep,
    }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-end', marginBottom: 10 }}>
        <div>
          <h1 style={{
            fontFamily: fontDisplay, fontSize: 34,
            color: BB.cream, fontWeight: 400,
            letterSpacing: '0.01em', margin: '0 0 6px',
          }}>Examinations</h1>
          <MetaLabel>{loading ? 'Loading…' : `${exams.length} examination${exams.length === 1 ? '' : 's'} on record`}</MetaLabel>
        </div>
        <BtnPrimary onClick={() => onNavigate('new-exam')} style={{ padding: '10px 28px', fontSize: 16 }}>
          + New Examination
        </BtnPrimary>
      </div>
      <GoldRule double style={{ margin: '20px 0 36px' }} />

      <div style={{ border: '1px solid rgba(201,169,97,0.2)' }}>
        <div style={{
          display: 'grid',
          gridTemplateColumns: '1fr 100px 120px 80px 80px 80px',
          padding: '10px 20px',
          borderBottom: '1px solid rgba(201,169,97,0.35)',
        }}>
          {['Examination', 'Course', 'Status', 'Duration', 'Submitted', ''].map(h => (
            <MetaLabel key={h}>{h}</MetaLabel>
          ))}
        </div>
        {exams.map((exam, i) => (
          <div key={exam.id}>
            <div style={{
              display: 'grid',
              gridTemplateColumns: '1fr 100px 120px 80px 80px 80px',
              padding: '14px 20px',
              alignItems: 'center',
              cursor: 'pointer',
              transition: 'background 0.2s',
            }}
              onMouseEnter={e => e.currentTarget.style.background = 'rgba(201,169,97,0.04)'}
              onMouseLeave={e => e.currentTarget.style.background = 'transparent'}
              onClick={() => openExam(exam, onNavigate)}
            >
              <div>
                <p style={{ fontFamily: fontBody, fontSize: 16, color: BB.cream, margin: 0 }}>
                  {exam.title}
                </p>
              </div>
              <MetaLabel>{exam.course}</MetaLabel>
              <div><StatusBadge status={exam.status} pulse /></div>
              <MetaLabel>{exam.duration}m</MetaLabel>
              <MetaLabel>{exam.submissions || '—'}</MetaLabel>
              <button onClick={e => { e.stopPropagation(); openExam(exam, onNavigate); }} style={{
                fontFamily: fontMono, fontSize: 10,
                letterSpacing: '0.15em', textTransform: 'uppercase',
                color: BB.gold, background: 'none', border: 'none',
                cursor: 'pointer',
              }}>Manage →</button>
            </div>
            {i < exams.length - 1 && <GoldRule faint />}
          </div>
        ))}
      </div>
    </div>
  );
}

// ─── Dashboard Layout (sidebar + content) ────────────────────────────────────
function DashboardLayout({ activeScreen, onNavigate, children }) {
  return (
    <div style={{ display: 'flex', height: '100vh', overflow: 'hidden' }}>
      <Sidebar activeScreen={activeScreen} onNavigate={onNavigate} />
      {children}
    </div>
  );
}

Object.assign(window, { DashboardLayout, DashboardScreen, ExamsScreen });
