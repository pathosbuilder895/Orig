// ════════════════════════════════════════════════════════════════
//  BLUEBOOK — App root (router + Tweaks panel)
//  Loaded last; all screen components are already on window.
// ════════════════════════════════════════════════════════════════
const { useState, useEffect } = React;

const TWEAK_DEFAULTS = /*EDITMODE-BEGIN*/{
  "currentScreen": "",
  "writingSize": 18,
  "parchmentColor": "#F4EFE6"
}/*EDITMODE-END*/;

function App() {
  const [t, setTweak] = useTweaks(TWEAK_DEFAULTS);
  const navigate = (screen) => setTweak('currentScreen', screen);
  // Auth-gated entry: a bound student launch → briefing; a signed-in
  // instructor → dashboard; otherwise the public landing/login.
  const [autoScreen] = useState(() =>
    BB_API.isStudentLaunch() ? 'briefing' : BB_API.isAuthed() ? 'dashboard' : 'landing');
  const screen = t.currentScreen || autoScreen;

  let content;
  switch (screen) {
    case 'login':
      content = <LoginScreen onNavigate={navigate} />;
      break;
    case 'dashboard':
      content = (
        <DashboardLayout activeScreen="dashboard" onNavigate={navigate}>
          <DashboardScreen onNavigate={navigate} />
        </DashboardLayout>
      );
      break;
    case 'exams':
      content = (
        <DashboardLayout activeScreen="exams" onNavigate={navigate}>
          <ExamsScreen onNavigate={navigate} />
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
          <CoursesScreen onNavigate={navigate} />
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
    case 'new-exam':
      content = <NewExamScreen onNavigate={navigate} />;
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
    </>
  );
}

ReactDOM.createRoot(document.getElementById('root')).render(<App />);
