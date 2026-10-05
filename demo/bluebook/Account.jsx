import React from 'react';
import { BB, BB_API, fontBody } from './components.jsx';
import {
  AuthShell, Badge, Btn, ErrorText, Field, LinkBtn, Notice, Page, Panel, Section, SubmitButton, Table, when,
} from './forms.jsx';
import { examToConfig } from './Exam.jsx';

// ════════════════════════════════════════════════════════════════
//  BLUEBOOK — Self-serve accounts
//  Teacher sign-up · Invite (set password) · Forgot password ·
//  Student home · Student submission · Account
// ════════════════════════════════════════════════════════════════
const { useState, useEffect } = React;

const MIN_PASSWORD = 8;
// Bumped whenever demo/legal/terms.html or privacy.html change materially;
// the server records the version a teacher accepted at signup or invitation.
export const TERMS_VERSION = '2026-10-01-draft';
// The server's refusal when an invited professor has not accepted the terms
// (original/routers/auth.py, _TERMS_REQUIRED).
const TERMS_REFUSAL = 'Please accept the terms of service and privacy policy.';

function passwordProblem(pw, confirm) {
  if (pw.length < MIN_PASSWORD) return `Use at least ${MIN_PASSWORD} characters.`;
  if (confirm !== undefined && pw !== confirm) return 'The two passwords do not match.';
  return '';
}

// Where a freshly signed-in account belongs.
export function homeFor(data) {
  return data && data.role === 'student' ? 'student-home' : 'dashboard';
}

const legalLink = { color: BB.gold };

export function LegalLinks() {
  return (
    <p style={{ textAlign: 'center', marginTop: 18, fontFamily: fontBody, fontSize: 15, color: BB.fade }}>
      <a href="../legal/terms.html" target="_blank" rel="noopener" style={legalLink}>Terms</a>
      {' · '}
      <a href="../legal/privacy.html" target="_blank" rel="noopener" style={legalLink}>Privacy</a>
      {' · '}
      <a href="../legal/student-notice.html" target="_blank" rel="noopener" style={legalLink}>Student notice</a>
    </p>
  );
}

// The terms checkbox a teacher ticks at signup, and an invited professor
// ticks when setting their first password.
function TermsCheckbox({ id, checked, onChange }) {
  return (
    <label className="bb-check" style={{ marginBottom: 16 }}>
      <input id={id} type="checkbox" checked={checked} onChange={e => onChange(e.target.checked)} />
      <span>I agree to the <a href="../legal/terms.html" target="_blank" rel="noopener" style={legalLink}>terms of service</a> and
        {' '}<a href="../legal/privacy.html" target="_blank" rel="noopener" style={legalLink}>privacy policy</a>.</span>
    </label>
  );
}

// ─── Teacher sign-up ─────────────────────────────────────────────────────────
export function SignupScreen({ onNavigate }) {
  const [name, setName] = useState('');
  const [email, setEmail] = useState('');
  const [pw, setPw] = useState('');
  const [agree, setAgree] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  async function submit(e) {
    e.preventDefault();
    if (busy) return;
    const problem = passwordProblem(pw);
    if (problem) { setError(problem); return; }
    if (!agree) { setError('Please accept the terms and privacy policy to create a workspace.'); return; }
    setError('');
    setBusy(true);
    try {
      const data = await BB_API.signup(name.trim(), email.trim(), pw, true);
      onNavigate(homeFor(data));
    } catch (err) {
      setError(err.message || 'Could not create the workspace.');
      setBusy(false);
    }
  }

  return (
    <AuthShell title="Create a free workspace" onBack={() => onNavigate('landing')}
      footer={<>
        <p style={{ textAlign: 'center', marginTop: 20, fontFamily: fontBody, fontSize: 16, color: BB.fade }}>
          Already have an account? <LinkBtn onClick={() => onNavigate('login')}>Sign in</LinkBtn>
        </p>
        <LegalLinks />
      </>}>
      <form onSubmit={submit}>
        <Field id="bbSignupName" label="Your name" value={name} onChange={setName}
          placeholder="Dr. Ada Lovelace" autoComplete="name" required={false} />
        <Field id="bbSignupEmail" label="Email" type="email" value={email} onChange={setEmail}
          placeholder="you@school.edu" autoComplete="email" />
        <Field id="bbSignupPass" label="Password" type="password" value={pw} onChange={setPw}
          autoComplete="new-password" hint={`At least ${MIN_PASSWORD} characters.`} />
        <TermsCheckbox id="bbSignupTerms" checked={agree} onChange={setAgree} />
        <ErrorText>{error}</ErrorText>
        <SubmitButton busy={busy} busyLabel="Creating…">Create workspace</SubmitButton>
      </form>
      <p className="bb-hint" style={{ marginTop: 18 }}>
        Your workspace is private to you. You add your own students, and only you see their work.
      </p>
    </AuthShell>
  );
}

// ─── Invite / reset: set a password ──────────────────────────────────────────
function inviteTokenFromUrl() {
  try {
    const q = new URLSearchParams(window.location.search);
    return q.get('invite') || q.get('reset') || '';
  } catch (e) { return ''; }
}

// A professor's invitation link ends in &terms=1 (original/onboarding.py).
function inviteNeedsTermsFromUrl() {
  try { return new URLSearchParams(window.location.search).get('terms') === '1'; } catch (e) { return false; }
}

function clearInviteFromUrl() {
  try {
    const url = new URL(window.location.href);
    url.searchParams.delete('invite');
    url.searchParams.delete('reset');
    url.searchParams.delete('terms');
    window.history.replaceState(null, '', url.pathname + (url.search || '') + url.hash);
  } catch (e) {}
}

export function InviteScreen({ onNavigate }) {
  const [token] = useState(inviteTokenFromUrl);
  const [pw, setPw] = useState('');
  const [confirm, setConfirm] = useState('');
  // Shown for a professor's invitation, or once the server asks for it (a
  // link that lost its terms=1, or a reset link before the first password).
  const [needTerms, setNeedTerms] = useState(inviteNeedsTermsFromUrl);
  const [agree, setAgree] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(token ? '' : 'This link is missing its code. Ask your teacher for a new one, or use “Forgot password”.');

  async function submit(e) {
    e.preventDefault();
    if (busy || !token) return;
    const problem = passwordProblem(pw, confirm);
    if (problem) { setError(problem); return; }
    if (needTerms && !agree) { setError('Please accept the terms and privacy policy to continue.'); return; }
    setError('');
    setBusy(true);
    try {
      const data = await BB_API.redeemInvite(token, pw, needTerms && agree);
      clearInviteFromUrl();
      onNavigate(homeFor(data));
    } catch (err) {
      if (err.message === TERMS_REFUSAL) setNeedTerms(true);
      setError(err.message || 'This link could not be used.');
      setBusy(false);
    }
  }

  return (
    <AuthShell title="Set your password" footer={<LegalLinks />}>
      <p style={{ fontFamily: fontBody, fontSize: 16, color: BB.fade, margin: '0 0 20px', lineHeight: 1.55 }}>
        Choose a password for your Bluebook account. You will use it with your
        email address to sign in from now on.
      </p>
      <form onSubmit={submit}>
        <Field id="bbInvitePass" label="New password" type="password" value={pw} onChange={setPw}
          autoComplete="new-password" hint={`At least ${MIN_PASSWORD} characters.`} />
        <Field id="bbInviteConfirm" label="Confirm password" type="password" value={confirm}
          onChange={setConfirm} autoComplete="new-password" />
        {needTerms && <TermsCheckbox id="bbInviteTerms" checked={agree} onChange={setAgree} />}
        <ErrorText>{error}</ErrorText>
        <SubmitButton busy={busy} busyLabel="Saving…">Save and continue</SubmitButton>
      </form>
    </AuthShell>
  );
}

// ─── Forgot password ─────────────────────────────────────────────────────────
export function ForgotPasswordScreen({ onNavigate }) {
  const [email, setEmail] = useState('');
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState('');
  const [error, setError] = useState('');

  async function submit(e) {
    e.preventDefault();
    if (busy) return;
    setBusy(true); setError('');
    try {
      const r = await BB_API.requestPasswordReset(email.trim());
      setDone(r && r.mail === false
        ? 'Email is not set up on this site yet. Students: ask your teacher for a new link. Teachers: contact support.'
        : 'If that address has a Bluebook account, a reset link is on its way. Check your inbox and spam folder.');
    } catch (err) { setError(err.message || 'Could not send the reset email.'); }
    setBusy(false);
  }

  return (
    <AuthShell title="Reset your password" onBack={() => onNavigate('login')} footer={<LegalLinks />}>
      {done ? <Notice>{done}</Notice> : (
        <form onSubmit={submit}>
          <Field id="bbForgotEmail" label="Email" type="email" value={email} onChange={setEmail}
            placeholder="you@school.edu" autoComplete="email" />
          <ErrorText>{error}</ErrorText>
          <SubmitButton busy={busy} busyLabel="Sending…">Email me a reset link</SubmitButton>
        </form>
      )}
      <p className="bb-hint" style={{ marginTop: 16 }}>Students can also ask their teacher for a new link.</p>
    </AuthShell>
  );
}

// ─── Change password (any signed-in account) ─────────────────────────────────
export function PasswordForm() {
  const [current, setCurrent] = useState('');
  const [pw, setPw] = useState('');
  const [confirm, setConfirm] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [done, setDone] = useState('');

  async function submit(e) {
    e.preventDefault();
    if (busy) return;
    const problem = passwordProblem(pw, confirm);
    if (problem) { setError(problem); return; }
    setError(''); setDone(''); setBusy(true);
    try {
      await BB_API.changePassword(current, pw);
      setCurrent(''); setPw(''); setConfirm('');
      setDone('Password changed.');
    } catch (err) {
      setError(err.message || 'Could not change the password.');
    }
    setBusy(false);
  }

  return (
    <form onSubmit={submit} style={{ maxWidth: 420 }}>
      <Field id="bbPwCurrent" label="Current password" type="password" value={current}
        onChange={setCurrent} autoComplete="current-password" />
      <Field id="bbPwNew" label="New password" type="password" value={pw} onChange={setPw}
        autoComplete="new-password" hint={`At least ${MIN_PASSWORD} characters.`} />
      <Field id="bbPwConfirm" label="Confirm new password" type="password" value={confirm}
        onChange={setConfirm} autoComplete="new-password" />
      <ErrorText>{error}</ErrorText>
      <Notice>{done}</Notice>
      <Btn primary type="submit" disabled={busy}>{busy ? 'Saving…' : 'Change password'}</Btn>
    </form>
  );
}

export function AccountScreen() {
  const id = BB_API.identity();
  return (
    <Page eyebrow="Account" title={id.name || 'Your account'} meta={id.email}>
      <Panel><h2>Change password</h2><PasswordForm /></Panel>
    </Page>
  );
}

// ─── Student shell ───────────────────────────────────────────────────────────
export function StudentShell({ onNavigate, active, children }) {
  const id = BB_API.identity();
  const tab = (key, label) => (
    <button key={key} onClick={() => onNavigate(key)} aria-current={active === key ? 'page' : undefined}>{label}</button>
  );
  return (
    <div className="bb-student">
      <nav className="bb-student-nav" aria-label="Student navigation">
        <button className="brand" onClick={() => onNavigate('student-home')}>Bluebook</button>
        <div className="tabs">
          {tab('student-home', 'My exams')}
          {tab('student-account', 'Account')}
          <button onClick={() => { BB_API.logout(); onNavigate('landing'); }}>Sign out</button>
        </div>
      </nav>
      <main className="bb-student-body">
        {id.name && <p className="sr-only" style={{ position: 'absolute', left: -9999 }}>Signed in as {id.name}</p>}
        {children}
      </main>
    </div>
  );
}

function examWindowText(e) {
  if (e.submitted) return e.results_released ? 'Results released' : 'Submitted';
  if (e.state === 'upcoming') return `Opens ${when(e.opens_at)}`;
  if (e.state === 'open' && e.closes_at) return `Closes ${when(e.closes_at)}`;
  if (e.state === 'closed' && e.closes_at) return `Closed ${when(e.closes_at)}`;
  return e.state === 'open' ? 'Open now' : '';
}

// Load the stored exam (questions, timing, conditions) into the shared slot
// the briefing and exam screens read, then enter the briefing.
export async function openStudentExam(examId, onNavigate) {
  const detail = await BB_API.myExam(examId);
  const id = BB_API.identity();
  // The signed-in student's own name and email label the sitting, so the
  // teacher sees who submitted it rather than "Candidate".
  window.BB_EXAM_CONFIG = examToConfig(detail, {
    viaDashboard: true,
    candidate: id.name || id.email || '',
    candidateEmail: id.email || '',
  });
  onNavigate('briefing');
}

export function StudentHomeScreen({ onNavigate }) {
  const [me, setMe] = useState(null);
  const [exams, setExams] = useState(null);
  const [subs, setSubs] = useState([]);
  const [error, setError] = useState('');
  const [opening, setOpening] = useState('');

  useEffect(() => {
    let live = true;
    Promise.all([BB_API.me(), BB_API.myExams(), BB_API.mySubmissions()])
      .then(([m, e, s]) => { if (live) { setMe(m); setExams(e); setSubs(s); } })
      .catch(err => {
        if (!live) return;
        if (/sign in|not authenticated/i.test(err.message || '')) {
          BB_API.logout(); onNavigate('login'); return;
        }
        setError(err.message || 'Could not load your exams.');
        setExams([]);
      });
    return () => { live = false; };
  }, []);

  async function open(e) {
    setOpening(e.exam_id); setError('');
    try { await openStudentExam(e.exam_id, onNavigate); }
    catch (err) { setError(err.message || 'Could not open that exam.'); setOpening(''); }
  }

  const courses = (me && me.courses) || [];
  const loading = exams === null;
  const order = { open: 0, upcoming: 1, closed: 2 };
  const sorted = (exams || []).slice().sort((a, b) =>
    (a.submitted - b.submitted) || (order[a.state] - order[b.state]));

  const examColumns = [
    { key: 'title', label: 'Examination', lead: true, render: e => <>{e.title}<span className="sub">{[e.course, e.duration ? `${e.duration} min` : null, e.questions_count > 1 ? `${e.questions_count} questions` : null].filter(Boolean).join(' · ')}</span></> },
    { key: 'state', label: 'Status', render: e => <Badge>{e.submitted ? 'submitted' : e.state}</Badge> },
    { key: 'when', label: 'When', render: e => examWindowText(e) || '—' },
    { key: 'go', label: 'Action', actions: true, render: e => {
      const canOpen = !e.submitted && (e.state === 'open' || e.session);
      return canOpen ? <Btn primary onClick={() => open(e)}>{opening === e.exam_id ? 'Opening…' : (e.session ? 'Resume' : 'Open')}</Btn> : null;
    } },
  ];
  const subColumns = [
    { key: 'exam', label: 'Examination', lead: true, render: s => s.exam || 'Examination' },
    { key: 'created_at', label: 'Submitted', render: s => when(s.created_at) },
    { key: 'words', label: 'Words', num: true },
    { key: 'mark', label: 'Mark', render: s => s.results_released ? (s.mark || 'Released') : 'Not yet released' },
    { key: 'read', label: 'Read', actions: true, render: s => <LinkBtn onClick={() => { window.BB_VIEW_SUBMISSION = s.id; onNavigate('student-submission'); }}>Read →</LinkBtn> },
  ];

  return (
    <StudentShell onNavigate={onNavigate} active="student-home">
      <Page eyebrow="Bluebook"
        title={me ? `Welcome, ${me.name || 'student'}.` : 'My exams'}
        meta={courses.length ? courses.map(c => c.code || c.name).join(' · ') : (loading ? 'Loading…' : 'Not enrolled in any course yet')}>
        <ErrorText>{error}</ErrorText>
        <Section title="Examinations">
          <Table columns={examColumns} rows={sorted} rowKey={e => e.exam_id} caption="Your examinations"
            empty={loading ? 'Loading…' : 'No examinations yet. Your teacher will add them to your course.'} />
        </Section>
        <Section title="My submissions">
          <Table columns={subColumns} rows={subs} rowKey={s => s.id} caption="Your submissions" empty="Nothing submitted yet." />
        </Section>
      </Page>
    </StudentShell>
  );
}

export function StudentSubmissionScreen({ onNavigate }) {
  const [sub, setSub] = useState(null);
  const [error, setError] = useState('');
  useEffect(() => {
    const id = window.BB_VIEW_SUBMISSION;
    if (!id) { onNavigate('student-home'); return; }
    BB_API.mySubmission(id).then(setSub).catch(err => setError(err.message || 'Could not load it.'));
  }, []);
  const answers = sub && sub.answers && sub.answers.length ? sub.answers : null;
  return (
    <StudentShell onNavigate={onNavigate} active="student-home">
      <Page eyebrow="Your submission"
        title={sub ? (sub.exam || 'Submission') : 'Submission'}
        meta={sub ? `${when(sub.created_at)} · ${sub.words} words${sub.late ? ' · late' : ''}` : ''}
        actions={<Btn onClick={() => onNavigate('student-home')}>← My exams</Btn>}>
        <ErrorText>{error}</ErrorText>
        {sub && (
          <>
            <Panel style={{ marginBottom: '1.5rem' }}>
              <h2>Result</h2>
              {sub.results_released ? (
                <>
                  <p style={{ fontSize: '1.4rem', margin: '0 0 .5rem' }}>{sub.mark || 'No mark given'}</p>
                  {sub.feedback
                    ? <p style={{ whiteSpace: 'pre-wrap', margin: 0 }}>{sub.feedback}</p>
                    : <p className="bb-meta">No written feedback.</p>}
                </>
              ) : <p className="bb-meta">Your teacher has not released results for this exam yet.</p>}
            </Panel>
            <div className="bb-paper">
              {answers ? answers.map((a, i) => (
                <div key={i} className="bb-answer">
                  <h3>Question {i + 1}</h3>
                  <div>{a || <em>No answer.</em>}</div>
                </div>
              )) : (sub.text || 'The text of this submission was not stored.')}
            </div>
          </>
        )}
      </Page>
    </StudentShell>
  );
}

export function StudentAccountScreen({ onNavigate }) {
  const id = BB_API.identity();
  return (
    <StudentShell onNavigate={onNavigate} active="student-account">
      <Page eyebrow="Account" title={id.name || 'Your account'} meta={id.email}>
        <Panel><h2>Change password</h2><PasswordForm /></Panel>
        <p className="bb-hint" style={{ marginTop: 20 }}>Forgot your password? Sign out and use “Forgot password”, or ask your teacher for a new link.</p>
      </Page>
    </StudentShell>
  );
}
