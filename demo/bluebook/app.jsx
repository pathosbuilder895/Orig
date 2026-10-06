import React from 'react';
import ReactDOM from 'react-dom/client';
import { BB_API, devToolsEnabled } from './components.jsx';
import { LandingScreen, LoginScreen } from './Landing.jsx';
import { DashboardLayout } from './Dashboard.jsx';
import { BriefingScreen, ExamScreen, SubmittedScreen } from './Exam.jsx';
import { ResultsScreen } from './Results.jsx';
import { NewExamScreen } from './NewExam.jsx';
import {
  AccountScreen, InviteScreen, SignupScreen, StudentAccountScreen,
  StudentHomeScreen, StudentSubmissionScreen, ForgotPasswordScreen,
} from './Account.jsx';
import {
  CoursesListScreen, ExamsListScreen, ManageExamScreen, ProctorLiveScreen, RosterScreen, StudentsScreen,
} from './Teacher.jsx';
import { openExam } from './Dashboard.jsx';
import { LiveTeacherSessions } from './TeacherWorkspace.jsx';
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

function App() {
  const [t, setTweak] = useTweaks(TWEAK_DEFAULTS);
  const navigate = (screen) => setTweak('currentScreen', screen);
  // Auth-gated entry, in priority order: an invite link → set password; a
  // bound student launch → briefing; a student account → their exams; a
  // signed-in teacher → dashboard; otherwise the public landing.
  const [autoScreen] = useState(() => {
    let invite = false;
    try {
      const q = new URLSearchParams(window.location.search);
      invite = q.has('invite') || q.has('reset');
    } catch (e) {}
    if (invite) return 'invite';
    if (BB_API.isStudentLaunch()) return 'briefing';
    if (BB_API.isStudentAccount()) return 'student-home';
    if (BB_API.isAuthed()) return 'dashboard';
    return 'landing';
  });
  const screen = t.currentScreen || autoScreen;
  // A Bluebook-only workspace (and its students) never sees Original's name.
  React.useEffect(() => {
    document.title = (BB_API.isAuthed() && BB_API.hasOriginal()) ? 'Original · Bluebook' : 'Bluebook';
  }, [screen]);
  // Read once at mount, alongside autoScreen and for the same reason: the
  // answer belongs to the launch, and a panel that could appear part-way
  // through a sitting would defeat the point of gating it. See
  // devToolsEnabled() in components.jsx for what arms it and what refuses it.
  const [devTools] = useState(devToolsEnabled);

  let content;
  switch (screen) {
    case 'login':
      content = <LoginScreen onNavigate={navigate} />;
      break;
    case 'sessions':
    case 'dashboard':
      content = (
        <DashboardLayout activeScreen={screen} onNavigate={navigate}>
          <LiveTeacherSessions onNavigate={navigate} overview={screen === 'dashboard'} />
        </DashboardLayout>
      );
      break;
    case 'exams':
      content = (
        <DashboardLayout activeScreen="exams" onNavigate={navigate}>
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
        <DashboardLayout activeScreen="exams" onNavigate={navigate}>
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

  return (
    <>
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
            { label: '④ Examinations',          value: 'exams'     },
            { label: '④b Courses',              value: 'courses'   },
            { label: '④c Students',             value: 'students'  },
            { label: '④d Results',              value: 'results'   },
            { label: '④e Proctor',              value: 'proctor'   },
            { label: '⑤ Exam Briefing',         value: 'briefing'  },
            { label: '⑥ New Examination',        value: 'new-exam'  },
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
