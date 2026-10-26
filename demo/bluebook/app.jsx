import React from 'react';
import ReactDOM from 'react-dom/client';
import { BB_API, BB_SIGNED_OUT_EVENT, devToolsEnabled } from './components.jsx';
import { expiryWarnDelay, tokenExpiryMs } from './form-drafts.jsx';
import { LandingScreen, LoginScreen } from './Landing.jsx';
import { DashboardLayout } from './Dashboard.jsx';
import { BriefingScreen, ExamScreen, SubmittedScreen } from './Exam.jsx';
import './booklet.css';
import { ResultsScreen } from './Results.jsx';
import { NewExamScreen } from './NewExam.jsx';
import {
  AccountScreen, InviteScreen, JoinScreen, SignupScreen, StudentAccountScreen,
  StudentHomeScreen, StudentSubmissionScreen, ForgotPasswordScreen,
} from './Account.jsx';
import {
  CoursesListScreen, ExamsListScreen, ManageExamScreen, ProctorLiveScreen, RosterScreen, StudentsScreen,
} from './Teacher.jsx';
import { openExam } from './Dashboard.jsx';
import { LiveTeacherSessions } from './TeacherWorkspace.jsx';
import { installResumeTracking, trackScreen } from './resume-location.jsx';
import { DEEP_LINK_SCREEN, FORGOT_HASH, clearDeepLink, deepLinkScreen, parseDeepLink, rememberScreen } from './deep-link.jsx';
import {
  useTweaks, TweaksPanel, TweakSection, TweakSelect, TweakSlider, TweakColor,
} from './tweaks-panel.jsx';

// ════════════════════════════════════════════════════════════════
//  BLUEBOOK — App root (router + dev-gated Tweaks panel)
// ════════════════════════════════════════════════════════════════
const { useState } = React;

const TWEAK_DEFAULTS = /*EDITMODE-BEGIN*/{
  "currentScreen": "",
  "writingSize": 18,
  "parchmentColor": "#F4EFE6"
}/*EDITMODE-END*/;

// The screens a visitor sees before they have signed in (or while they are signing in or up).
const PRE_AUTH_SCREENS = ['landing', 'login', 'signup', 'invite', 'forgot', 'join'];
const BB_SESSION_WATCH = ['original_principal_token', 'original_session_token', 'original_role'];

function App() {
  const [t, setTweak] = useTweaks(TWEAK_DEFAULTS);
  // Moving to another screen drops a deep-link hash (deep-link.jsx), so the
  // address bar never names an exam the teacher has left.
  // A signed-in teacher who moves on also drops a link still being checked, or it would open
  // that exam the next time they land on the dashboard. A visitor who is not signed in yet keeps
  // it: the sign-in flow carries it to the exam. That includes the navigation right after sign-in
  // or sign-up, which happens with the session already stored, so it is the screen the move starts
  // from that tells the two apart, not the session alone.
  const navigate = (next) => {
    clearDeepLink();
    if (BB_API.isAuthed() && !PRE_AUTH_SCREENS.includes(screen)) setDeepLink(null);
    if (BB_API.isAuthed() && !BB_API.isStudentAccount() && !BB_API.isStudentLaunch()) rememberScreen(next);
    setTweak('currentScreen', next);
  };
  // One browser holds one sign-in (localStorage is shared by every tab). If
  // another tab signs in as someone else (typically the teacher testing a
  // student invite), this tab's token is gone and every request would come
  // back empty or refused. Say so plainly instead of showing empty pages.
  // The account this tab last rendered with (its own sign-ins do not fire
  // storage events, so this follows them; another tab's change does not).
  const shownSession = React.useRef(BB_API.sessionSignature());
  const [switched, setSwitched] = useState(false);
  React.useEffect(() => {
    const onStorage = (e) => {
      if (e.key !== null && !BB_SESSION_WATCH.includes(e.key)) return;
      if (shownSession.current && BB_API.sessionSignature() !== shownSession.current) setSwitched(true);
    };
    window.addEventListener('storage', onStorage);
    return () => window.removeEventListener('storage', onStorage);
  }, []);
  // A lapsed teacher sign-in (401) goes to the sign-in page with a reason,
  // never to empty lists. The current screen is kept in the hash, so signing
  // back in returns there.
  const [expired, setExpired] = useState(false);
  const [expiredStudent, setExpiredStudent] = useState(false);
  React.useEffect(() => {
    const onExpired = (e) => {
      setExpiredStudent(!!(e && e.detail && e.detail.student));
      BB_API._clearSession();
      setExpired(true);
      setTweak('currentScreen', 'login');
    };
    window.addEventListener(BB_SIGNED_OUT_EVENT, onExpired);
    return () => window.removeEventListener(BB_SIGNED_OUT_EVENT, onExpired);
  }, []);
  // A teacher's sign-in lasts 8 hours. About 10 minutes before it ends, say
  // so, so nothing is typed into a form that will be refused. Form drafts
  // (form-drafts.jsx) are kept on this computer either way.
  const [expirySoon, setExpirySoon] = useState(false);
  React.useEffect(() => {
    let tok = '';
    try { tok = localStorage.getItem('original_principal_token') || ''; } catch (e) {}
    const delay = expiryWarnDelay(tokenExpiryMs(tok), Date.now());
    if (delay === null) { setExpirySoon(false); return; }
    const id = setTimeout(() => setExpirySoon(true), delay);
    return () => clearTimeout(id);
  }, [t.currentScreen]);

  // A deep link (#exam/<id>, #live/<id>) waiting to be opened. It opens only
  // on a signed-in teacher's dashboard: straight away for a teacher who is
  // already signed in, after sign-in for one who is not, and never for a
  // student, whose screens ignore it.
  const [deepLink, setDeepLink] = useState(() => parseDeepLink(window.location.hash));
  // Auth-gated entry, in priority order: an invite link → set password; a
  // course join link → join; a bound student launch → briefing; a student
  // account → their exams; a signed-in teacher → dashboard; otherwise the
  // public landing.
  const [autoScreen] = useState(() => {
    let invite = false;
    let join = false;
    try {
      const q = new URLSearchParams(window.location.search);
      invite = q.has('invite') || q.has('reset');
      join = q.has('join');
    } catch (e) {}
    if (invite) return 'invite';
    if (join) return 'join';
    if (BB_API.isStudentLaunch()) return 'briefing';
    if (BB_API.isStudentAccount()) return 'student-home';
    if (BB_API.isAuthed()) return 'dashboard';
    // The sign-in page's "Forgot your password?" link opens the reset form.
    if (window.location.hash === FORGOT_HASH) return 'forgot';
    return 'landing';
  });
  const screen = t.currentScreen || autoScreen;
  const teacherHome = screen === 'dashboard' && BB_API.isAuthed()
    && !BB_API.isStudentLaunch() && !BB_API.isStudentAccount();
  // A link followed while the app is already open (same page, new hash).
  React.useEffect(() => {
    const onHash = () => {
      const link = parseDeepLink(window.location.hash);
      if (!link) return;
      setDeepLink(link);
      if (BB_API.isAuthed() && !BB_API.isStudentLaunch() && !BB_API.isStudentAccount()) {
        setTweak('currentScreen', 'dashboard');
      }
    };
    window.addEventListener('hashchange', onHash);
    return () => window.removeEventListener('hashchange', onHash);
  }, []);
  // Open the linked exam only once the server says this teacher may see it.
  // A 404 (unknown id) or 403 (another workspace's) leaves the dashboard as
  // it is, with no error, and drops the hash. A link to a whole screen
  // (#students, #courses) has nothing to check and opens it at once.
  React.useEffect(() => {
    if (!deepLink || !teacherHome) return undefined;
    if (deepLink.kind === 'screen') {
      setDeepLink(null);
      setTweak('currentScreen', deepLink.screen);
      return undefined;
    }
    let live = true;
    BB_API.getExam(deepLink.id).then(exam => {
      if (!live) return;
      setDeepLink(null);
      if (exam && exam.id === deepLink.id) setTweak('currentScreen', deepLinkScreen(deepLink, exam));
      else clearDeepLink();
    }).catch(() => {
      if (!live) return;
      setDeepLink(null);
      clearDeepLink();
    });
    return () => { live = false; };
  }, [deepLink, teacherHome]);
  // Where this account is, saved for resuming on another device
  // (resume-location.jsx). Only kept screens are saved; the rest are ignored.
  React.useEffect(() => { installResumeTracking(); }, []);
  React.useEffect(() => { trackScreen(screen); }, [screen]);
  // A Bluebook-only workspace (and its students) never sees Original's name.
  React.useEffect(() => {
    document.title = (BB_API.isAuthed() && BB_API.hasOriginal()) ? 'Original · Collections' : 'Collections';
  }, [screen]);
  // Read once at mount, alongside autoScreen and for the same reason: the
  // answer belongs to the launch, and a panel that could appear part-way
  // through a sitting would defeat the point of gating it. See
  // devToolsEnabled() in components.jsx for what arms it and what refuses it.
  const [devTools] = useState(devToolsEnabled);

  let content;
  switch (screen) {
    case 'login':
      content = <>
        {expired && <p role="alert" data-testid="signin-expired" style={{ textAlign: 'center', margin: '1.5rem auto 0', maxWidth: 520, color: '#C47A6B' }}>{expiredStudent ? 'Your sign-in has expired. Please sign in again to finish submitting your exam. Your answers are kept on this computer.' : 'Your sign-in has expired. Please sign in again. Nothing was lost.'}</p>}
        <LoginScreen onNavigate={(n) => { setExpired(false); navigate(n); }} />
      </>;
      break;
    case 'dashboard':
      // While a deep link is being checked, say so instead of flashing the
      // dashboard first.
      if (deepLink && teacherHome) {
        const toScreen = deepLink.kind === 'screen';
        content = (
          <DashboardLayout activeScreen={toScreen ? deepLink.screen : (DEEP_LINK_SCREEN[deepLink.kind] === 'proctor' ? 'proctor' : 'sessions')} onNavigate={navigate}>
            <div className="bb-page"><p role="status" className="bb-meta">{toScreen ? 'Opening…' : 'Opening the collection…'}</p></div>
          </DashboardLayout>
        );
        break;
      }
      content = (
        <DashboardLayout activeScreen={screen} onNavigate={navigate}>
          <LiveTeacherSessions onNavigate={navigate} overview />
        </DashboardLayout>
      );
      break;
    // One Collections area: the old Sessions and Examinations screens (and
    // the 'collections' alias) all open the same list.
    case 'sessions':
    case 'collections':
    case 'exams':
      content = (
        <DashboardLayout activeScreen="sessions" onNavigate={navigate}>
          <ExamsListScreen onNavigate={navigate} />
        </DashboardLayout>
      );
      break;
    case 'briefing':
      content = <BriefingScreen onNavigate={navigate} />;
      break;
    case 'exam':
      content = (
        <ExamScreen
          onNavigate={navigate}
          writingSize={Number(t.writingSize) || 18}
          parchmentColor={t.parchmentColor || '#F4EFE6'}
        />
      );
      break;
    case 'courses':
      content = (
        <DashboardLayout activeScreen="courses" onNavigate={navigate}>
          <CoursesListScreen onNavigate={navigate} />
        </DashboardLayout>
      );
      break;
    case 'students':
      content = (
        <DashboardLayout activeScreen="students" onNavigate={navigate}>
          <StudentsScreen onNavigate={navigate} />
        </DashboardLayout>
      );
      break;
    case 'results':
      content = (
        <DashboardLayout activeScreen="results" onNavigate={navigate}>
          <ResultsScreen onNavigate={navigate} />
        </DashboardLayout>
      );
      break;
    case 'proctor':
      content = (
        <DashboardLayout activeScreen="proctor" onNavigate={navigate}>
          <ProctorLiveScreen />
        </DashboardLayout>
      );
      break;
    case 'new-exam':
      content = <NewExamScreen onNavigate={navigate} />;
      break;
    case 'manage-exam':
      content = (
        <DashboardLayout activeScreen="sessions" onNavigate={navigate}>
          <ManageExamScreen onNavigate={navigate} onPreview={exam => openExam(exam, navigate)} />
        </DashboardLayout>
      );
      break;
    case 'roster':
      content = (
        <DashboardLayout activeScreen="courses" onNavigate={navigate}>
          <RosterScreen onNavigate={navigate} />
        </DashboardLayout>
      );
      break;
    case 'account':
      content = (
        <DashboardLayout activeScreen="account" onNavigate={navigate}>
          <AccountScreen />
        </DashboardLayout>
      );
      break;
    case 'signup':
      content = <SignupScreen onNavigate={navigate} />;
      break;
    case 'invite':
      content = <InviteScreen onNavigate={navigate} />;
      break;
    case 'forgot':
      content = <ForgotPasswordScreen onNavigate={navigate} />;
      break;
    case 'join':
      content = <JoinScreen onNavigate={navigate} />;
      break;
    case 'student-home':
      content = <StudentHomeScreen onNavigate={navigate} />;
      break;
    case 'student-submission':
      content = <StudentSubmissionScreen onNavigate={navigate} />;
      break;
    case 'student-account':
      content = <StudentAccountScreen onNavigate={navigate} />;
      break;
    case 'submitted':
      content = <SubmittedScreen onNavigate={navigate} />;
      break;
    default:
      content = <LandingScreen onNavigate={navigate} />;
  }

  if (!switched) shownSession.current = BB_API.sessionSignature();
  if (switched) {
    const who = BB_API.identity();
    return (
      <div role="alert" data-testid="session-switched" style={{ maxWidth: 560, margin: '15vh auto', padding: '0 1.5rem', fontFamily: 'Georgia, serif', lineHeight: 1.55 }}>
        <h1 style={{ fontWeight: 400 }}>You were signed out in this tab</h1>
        <p>Another tab in this browser signed in{who.email ? <> as <strong>{who.email}</strong></> : null}{who.role ? ` (${who.role})` : ''}. A browser holds one sign-in at a time, so this tab's account was signed out. Nothing you or your students submitted was lost.</p>
        <p>To use a teacher and a student account at the same time, open the student's link in a private (incognito) window or a different browser.</p>
        <button onClick={() => window.location.reload()}>Reload this tab</button>
      </div>
    );
  }

  return (
    <>
      {expirySoon && screen !== 'login' && BB_API.isAuthed() && !BB_API.isStudentAccount() && (
        <div role="status" data-testid="signin-expiring" style={{ position: 'fixed', top: 0, left: 0, right: 0, zIndex: 1000, background: '#1b2347', color: '#F3EBD8', borderBottom: '1px solid #C9A028', padding: '0.6rem 1rem', textAlign: 'center', fontFamily: 'Georgia, serif' }}>
          Your sign-in ends in about 10 minutes. Anything typed in the New collection form is kept on this computer.{' '}
          <button onClick={() => { BB_API._clearSession(); setExpirySoon(false); setTweak('currentScreen', 'login'); }} style={{ marginLeft: 8 }}>Sign in again now</button>
        </div>
      )}
      <div key={screen} style={{ animation: 'bbFadeIn 0.65s ease both' }}>
        {content}
      </div>

      {devTools && (
      <TweaksPanel>
        <TweakSection label="Navigation" />
        <TweakSelect
          label="Jump to screen"
          value={screen}
          options={[
            { label: '① Landing',              value: 'landing'   },
            { label: '② Sign In',               value: 'login'     },
            { label: '③ Dashboard',             value: 'dashboard' },
            { label: '④ Collections',           value: 'sessions'  },
            { label: '④b Courses',              value: 'courses'   },
            { label: '④c Students',             value: 'students'  },
            { label: '④d Results',              value: 'results'   },
            { label: '④e Proctor',              value: 'proctor'   },
            { label: '⑤ Exam Briefing',         value: 'briefing'  },
            { label: '⑥ New Collection',         value: 'new-exam'  },
            { label: '⑦ Active Examination',    value: 'exam'      },
            { label: '⑧ Submitted',             value: 'submitted' },
          ]}
          onChange={(v) => navigate(v)}
        />

        <TweakSection label="Writing Surface" />
        <TweakSlider
          label="Font size"
          value={Number(t.writingSize) || 18}
          min={14} max={22} step={1} unit="px"
          onChange={(v) => setTweak('writingSize', v)}
        />
        <TweakColor
          label="Parchment shade"
          value={t.parchmentColor || '#F4EFE6'}
          options={['#F4EFE6', '#F8F5EE', '#EEF2EC']}
          onChange={(v) => setTweak('parchmentColor', v)}
        />
      </TweaksPanel>
      )}
    </>
  );
}

ReactDOM.createRoot(document.getElementById('root')).render(<App />);
