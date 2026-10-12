import React from 'react';
import { BB, BB_API, BtnPrimary, GoldRule, Logotype, MetaLabel, STOCK_CANDIDATE, StatusBadge, fontBody, fontDisplay, fontMono, rowKeyDown } from './components.jsx';
import { openManageExam } from './Teacher.jsx';
import { TeacherFrame } from './TeacherWorkspace.jsx';

// ════════════════════════════════════════════════════════════════
//  BLUEBOOK — Dashboard Screens
//  Examinations List · the teacher frame
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
  { label: 'Proctor',       screen: 'proctor'   },
];

// A signed-in teacher's own account screen; the anonymous demo has no account.
const ACCOUNT_ITEM = { label: 'Account', screen: 'account' };

// ─── Sidebar ─────────────────────────────────────────────────────────────────
function Sidebar({ activeScreen, onNavigate }) {
  const [hovered, setHovered] = React.useState(null);
  const id = BB_API.identity();
  const displayName = id.authed ? (id.name || 'Signed in') : 'Demo Session';
  const displayRole = id.authed
    ? (id.email || id.role || 'instructor')
    : 'Collections · demo';
  // Only a workspace that bought Original gets the cross-link to it.
  const showOriginal = !id.authed || BB_API.hasOriginal();

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
        {(id.authed ? [...NAV_ITEMS, ACCOUNT_ITEM] : NAV_ITEMS).map(({ label, screen }) => {
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

        {showOriginal && <div style={{ margin: '10px 0', borderTop: '1px solid rgba(201,169,97,0.18)' }} />}

        {/* Original Analysis — cross-link back to the Original dashboard.
            Sits at the sidebar's own resting colour (BB.fade, like every
            inactive nav item above it) rather than below it: an extra
            `opacity: 0.7` on top of BB.fade used to composite to #617188 and
            read 3.85:1, under WCAG AA's 4.5:1 for 16px text (e2e/a11y.spec.mjs
            measures it). The de-emphasis it bought was already carried by the
            colour and the divider above. */}
        {showOriginal && (
        <button
          onClick={() => { window.location.href = '../original/'; }}
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
            transition: 'color 0.25s',
            textAlign: 'left',
          }}
        >
          <span>Original Analysis</span>
          <span style={{ fontSize: 11, opacity: 0.6 }}>↗</span>
        </button>
        )}
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
          {/* BB.fade, not a faded BB.fade: `rgba(139,155,180,0.55)` is the same
              hue at 55%, which composites to #4c6483 and reads 2.64:1 — well
              under AA for 15px text, and this is the control a professor needs
              on a shared machine. Its smaller size and position below the rule
              already mark it as secondary. */}
          <button
            onClick={() => { BB_API.logout(); onNavigate('landing'); }}
            style={{
              display: 'block', width: '100%', padding: '8px 12px',
              background: 'none', border: 'none', borderLeft: '2px solid transparent',
              fontFamily: fontBody, fontSize: 15,
              color: BB.fade,
              cursor: 'pointer', textAlign: 'left', letterSpacing: '0.02em',
              transition: 'color 0.25s',
            }}
          >Sign Out</button>
        </div>
      </div>
    </aside>
  );
}

// A signed-in teacher manages a stored exam; the anonymous demo previews it.
function manageOrPreview(exam, onNavigate) {
  if (BB_API.isAuthed() && exam.id) openManageExam(exam.id, onNavigate);
  else openExam(exam, onNavigate);
}

// Load an exam's config into the shared slot, then enter its briefing
// (the teacher's preview of what students see).
export function openExam(exam, onNavigate) {
  window.BB_EXAM_CONFIG = {
    id:          exam.id,
    title:       exam.title,
    course:      exam.course,
    courseTitle: exam.course,
    duration:    exam.duration || 90,
    minWords:    exam.minWords != null ? exam.minWords : 600,
    maxWords:    exam.maxWords != null ? exam.maxWords : 1200,
    prompt:      exam.prompt || '',
    closesAt:    exam.closes_at || null,
    candidate:   (window.BB_EXAM_CONFIG && window.BB_EXAM_CONFIG.candidate) || STOCK_CANDIDATE,
    ...(exam.conditions || {}),
  };
  onNavigate('briefing');
}

// ─── Exams List Screen ────────────────────────────────────────────────────────
export function ExamsScreen({ onNavigate }) {
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
              role="button" tabIndex={0} aria-label={exam.title}
              onMouseEnter={e => e.currentTarget.style.background = 'rgba(201,169,97,0.04)'}
              onMouseLeave={e => e.currentTarget.style.background = 'transparent'}
              onClick={() => manageOrPreview(exam, onNavigate)}
              onKeyDown={rowKeyDown(() => manageOrPreview(exam, onNavigate))}
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
              <button onClick={e => { e.stopPropagation(); manageOrPreview(exam, onNavigate); }} style={{
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
export function DashboardLayout({ activeScreen, onNavigate, children }) {
  return <TeacherFrame active={activeScreen} onNavigate={onNavigate}>{children}</TeacherFrame>;
}
