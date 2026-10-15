import React from 'react';
import { BB, BB_API, BtnPrimary, fontBody } from './components.jsx';
import {
  AuthShell, Badge, Btn, ErrorText, Field, LinkBtn, Notice, Page, Panel, Section, SubmitButton, Table, when,
} from './forms.jsx';
import { examToConfig, takeSittingToResume } from './Exam.jsx';

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
// ticks when setting their first password. A student's invitation asks them
// to read the student notice as well (`student`).
function TermsCheckbox({ id, checked, onChange, student = false }) {
  return (
    <label className="bb-check" style={{ marginBottom: 16 }}>
      <input id={id} type="checkbox" checked={checked} onChange={e => onChange(e.target.checked)} />
      {student ? (
        <span>I have read the <a href="../legal/student-notice.html" target="_blank" rel="noopener" style={legalLink}>student notice</a> and
          agree to the <a href="../legal/terms.html" target="_blank" rel="noopener" style={legalLink}>terms of service</a> and
          {' '}<a href="../legal/privacy.html" target="_blank" rel="noopener" style={legalLink}>privacy policy</a>.</span>
      ) : (
        <span>I agree to the <a href="../legal/terms.html" target="_blank" rel="noopener" style={legalLink}>terms of service</a> and
          {' '}<a href="../legal/privacy.html" target="_blank" rel="noopener" style={legalLink}>privacy policy</a>.</span>
      )}
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

// What kind of link opened the set-password screen: a professor's invitation
// ('teacher', it ends in &terms=1), a password reset from the reset email
// ('reset', ?reset=), or a student's invitation from a course roster
// ('student', every other ?invite= link).
export function inviteKind(search) {
  try {
    const q = new URLSearchParams(search || '');
    if (q.get('terms') === '1') return 'teacher';
    if (q.has('reset') && !q.has('invite')) return 'reset';
    return 'student';
  } catch (e) { return 'student'; }
}

// The server gives one answer for every link it will not take (unknown,
// expired, voided or already used), so the route cannot be used to probe
// tokens (original/routers/auth.py). The screen says what to do next instead.
const LINK_REFUSED = /invalid, expired, or already used/i;
export const INVITE_LINK_USED = 'This link has already been used, or it has expired. Each link works once and lasts 14 days. '
  + 'If you have already set your password, sign in with your email and password. If not, ask your teacher for a new link.';
// A teacher's own invitation or reset link was not sent by a teacher.
export const INVITE_LINK_USED_STAFF = 'This link has already been used, or it has expired. Each link works once and lasts 14 days. '
  + 'If you have already set your password, sign in with your email and password. If not, use “Forgot your password?” on the sign-in page, '
  + 'or ask the person who invited you for a new link.';
export const INVITE_LINK_MISSING = 'This link is incomplete, so it cannot be used. Please open the whole link from your invitation, '
  + 'or ask your teacher for a new one. If you have already set your password, sign in instead.';

// What the set-password screen says when the server refuses a link of this kind.
export function inviteErrorText(message, kind = 'student') {
  if (LINK_REFUSED.test(String(message || ''))) return kind === 'student' ? INVITE_LINK_USED : INVITE_LINK_USED_STAFF;
  return message || 'This link could not be used. Ask your teacher for a new one, or use “Forgot password”.';
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

// Leave the set-password screen for the sign-in page, dropping the link's
// code from the address bar so the sign-in page does not reopen this one.
function toSignIn(onNavigate) {
  clearInviteFromUrl();
  onNavigate('login');
}

export function InviteScreen({ onNavigate }) {
  const [token] = useState(inviteTokenFromUrl);
  const [kind] = useState(() => inviteKind(window.location.search));
  const [pw, setPw] = useState('');
  const [confirm, setConfirm] = useState('');
  // Shown for a professor's invitation, or once the server asks for it (a
  // link that lost its terms=1, or a reset link before the first password).
  const [needTerms, setNeedTerms] = useState(inviteNeedsTermsFromUrl);
  // A student's invitation asks them to read the student notice and accept
  // the terms before their first sign-in. The server records a teacher's
  // acceptance (original/routers/auth.py); for a student this step is the
  // screen's own, and the request carries accept_terms like a teacher's.
  const studentTerms = kind === 'student' && !needTerms;
  const [agree, setAgree] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  // The link itself cannot be used (no code, or the server refused it): the
  // form gives way to what to do next.
  const [linkDead, setLinkDead] = useState(!token);

  async function submit(e) {
    e.preventDefault();
    if (busy || !token) return;
    const problem = passwordProblem(pw, confirm);
    if (problem) { setError(problem); return; }
    if ((needTerms || studentTerms) && !agree) {
      setError(studentTerms
        ? 'Please tick the box to say you have read the student notice and accept the terms.'
        : 'Please accept the terms and privacy policy to continue.');
      return;
    }
    setError('');
    setBusy(true);
    try {
      const data = await BB_API.redeemInvite(token, pw, (needTerms || studentTerms) && agree);
      clearInviteFromUrl();
      onNavigate(homeFor(data));
    } catch (err) {
      if (err.message === TERMS_REFUSAL) setNeedTerms(true);
      if (LINK_REFUSED.test(err.message || '')) setLinkDead(true);
      setError(inviteErrorText(err.message, kind));
      setBusy(false);
    }
  }

  const title = kind === 'reset' ? 'Choose a new password' : 'Set your password';
  const signInLine = (
    <p style={{ textAlign: 'center', marginTop: 20, fontFamily: fontBody, fontSize: 16, color: BB.fade }}>
      Already set your password? <LinkBtn onClick={() => toSignIn(onNavigate)}>Sign in</LinkBtn>
    </p>
  );

  if (linkDead) {
    return (
      <AuthShell title={title} footer={<LegalLinks />}>
        <p role="alert" className="bb-error" style={{ marginTop: 0 }}>{token ? (error || INVITE_LINK_USED) : INVITE_LINK_MISSING}</p>
        <BtnPrimary full onClick={() => toSignIn(onNavigate)} style={{ padding: '14px 0', fontSize: 17 }}>Go to sign in</BtnPrimary>
        <p className="bb-hint" style={{ marginTop: 16 }}>
          {kind === 'student'
            ? 'Forgot your password? Use “Forgot your password?” on the sign-in page, or ask your teacher for a new link.'
            : 'Forgot your password? Use “Forgot your password?” on the sign-in page.'}
        </p>
      </AuthShell>
    );
  }

  return (
    <AuthShell title={title} footer={<>{signInLine}<LegalLinks /></>}>
      <p style={{ fontFamily: fontBody, fontSize: 16, color: BB.fade, margin: '0 0 20px', lineHeight: 1.55 }}>
        {kind === 'reset'
          ? 'Choose a new password for your Collections account. Your old password stops working once you save.'
          : 'Choose a password for your Collections account. You will use it with your email address to sign in from now on.'}
      </p>
      <form onSubmit={submit}>
        <Field id="bbInvitePass" label="New password" type="password" value={pw} onChange={setPw}
          autoComplete="new-password" hint={`At least ${MIN_PASSWORD} characters.`} />
        <Field id="bbInviteConfirm" label="Confirm password" type="password" value={confirm}
          onChange={setConfirm} autoComplete="new-password" />
        {(needTerms || studentTerms) && (
          <TermsCheckbox id="bbInviteTerms" checked={agree} onChange={setAgree} student={studentTerms} />
        )}
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
        ? 'Password reset emails are not available here yet. Students: please ask your teacher for a new link. Teachers: please contact support.'
        : 'If that address has a Collections account, a reset link is on its way. Check your inbox and spam folder.');
    } catch (err) { setError(err.message || 'We could not send the reset email just now. Please try again in a few minutes.'); }
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
      setError(err.message || 'Your password was not changed. Please try again.');
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
// The two Original pages a student can open: their own voice and a piece of
// their writing compared with it. They are offered only when the student's
// workspace holds Original (BB_API.hasOriginal: the products sign-in stored,
// refreshed by every student-home load), and a Bluebook-only workspace sees
// the shell it always had. The pages check the session themselves.
export const STUDENT_ORIGINAL_LINKS = [['../original/voice.html', 'My voice'], ['../original/my-work.html', 'My work']];
// Not offered to students in this pilot phase, even where the workspace holds
// Original: "My work" shows Original's reading of a pasted piece, and during
// the pilot a student never sees a comparison of their writing (NORTH_STAR
// "Not doing now" defers the "My Voice" pages). The pages themselves are
// unchanged; set this to true to offer them again.
export const SHOW_STUDENT_ORIGINAL_PAGES = false;

export function StudentShell({ onNavigate, active, children }) {
  const id = BB_API.identity();
  const studentOriginalLinks = SHOW_STUDENT_ORIGINAL_PAGES && BB_API.hasOriginal() ? STUDENT_ORIGINAL_LINKS : [];
  const tab = (key, label) => (
    <button key={key} onClick={() => onNavigate(key)} aria-current={active === key ? 'page' : undefined}>{label}</button>
  );
  return (
    <div className="bb-student">
      <nav className="bb-student-nav" aria-label="Student navigation">
        <button className="brand" onClick={() => onNavigate('student-home')}>Collections</button>
        <div className="tabs">
          {tab('student-home', 'My exams')}
          {studentOriginalLinks.map(([href, label]) => <a key={href} href={href}>{label}</a>)}
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

// The order a student's exams are listed in: a sitting in progress first,
// then open, upcoming and closed exams, then what they have submitted. The
// server lists exams newest first; inside each group the oldest comes first,
// so the first exam a teacher set ("Practice prompt 1") sits above the next.
const EXAM_STATE_ORDER = { open: 0, upcoming: 1, closed: 2 };
export function sortStudentExams(exams) {
  const rank = e => [
    e.submitted ? 1 : 0,
    e.session && !e.submitted ? 0 : 1,
    EXAM_STATE_ORDER[e.state] ?? 3,
  ];
  return (exams || []).map((e, i) => ({ e, i })).sort((a, b) => {
    const ra = rank(a.e), rb = rank(b.e);
    for (let k = 0; k < ra.length; k++) if (ra[k] !== rb[k]) return ra[k] - rb[k];
    return b.i - a.i;
  }).map(x => x.e);
}

// What a student is told when one of their own requests fails: plain words
// for "not there" and "not yours", the fallback for anything the server did
// not explain, and never a bare "exam not found".
function bbStudentError(err, fallback) {
  const s = err && err.status;
  if (s === 404) return 'That is no longer available. Please check with your teacher.';
  if (s === 403) return 'That is not available to your account. Please check with your teacher.';
  if (s && s >= 500) return fallback;
  return (err && err.message) || fallback;
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
      .then(([m, e, s]) => {
        if (!live) return;
        setMe(m); setExams(e); setSubs(s);
        const resume = takeSittingToResume(e);
        if (resume) open(resume);
      })
      .catch(err => {
        if (!live) return;
        if (err.status === 401 || /sign in|not authenticated/i.test(err.message || '')) {
          BB_API.logout(); onNavigate('login'); return;
        }
        setError(bbStudentError(err, 'We could not load your exams just now. Please refresh the page to try again.'));
        setExams([]);
      });
    return () => { live = false; };
  }, []);

  async function open(e) {
    setOpening(e.exam_id); setError('');
    try { await openStudentExam(e.exam_id, onNavigate); }
    catch (err) { setError(bbStudentError(err, 'We could not open that exam just now. Please try again.')); setOpening(''); }
  }

  const courses = (me && me.courses) || [];
  const loading = exams === null;
  const sorted = sortStudentExams(exams);

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
      <Page eyebrow="Collections"
        title={me ? (me.name ? `Welcome, ${me.name}.` : 'Welcome.') : 'My exams'}
        meta={courses.length ? courses.map(c => c.code || c.name).join(' · ') : (loading ? 'Loading…' : 'You are not in a course yet. Your teacher will add you.')}>
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
    BB_API.mySubmission(id).then(setSub).catch(err => setError(bbStudentError(err, 'We could not load this submission just now. Please try again.')));
  }, []);
  const answers = sub && sub.answers && sub.answers.length ? sub.answers : null;
  return (
    <StudentShell onNavigate={onNavigate} active="student-home">
      <Page eyebrow="Your submission"
        title={sub ? (sub.exam || 'Submission') : 'Submission'}
        meta={sub ? `${when(sub.created_at)} · ${sub.words} words${sub.late ? ' · after the deadline' : ''}` : ''}
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
              )) : (sub.text || 'The text of this submission is not available here.')}
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
