import { test } from 'node:test';
import assert from 'node:assert/strict';
import { build } from 'esbuild';

// The alpha journey's rough edges (2026-10-15), pinned without a browser:
// the set-password screen for each kind of link, the student's exam order and
// the way back after a refresh, the teacher's copied invite links, the live
// view's choice of exam, the teacher frame's labels, and what the sealed
// screen does (and does not) say about comparison. Screens are rendered for
// real with react-dom/server.
const built = await build({
  stdin: {
    contents: `
      import React from 'react';
      import { renderToStaticMarkup } from 'react-dom/server';
      import { InviteScreen, inviteKind, inviteErrorText, INVITE_LINK_USED, INVITE_LINK_USED_STAFF, INVITE_LINK_MISSING, sortStudentExams } from './Account.jsx';
      import { SubmittedScreen, rememberSitting, takeSittingToResume, REFERENCE_WRITING_LINE } from './Exam.jsx';
      import { linksAsText, linksAsCsv, chooseLiveExam } from './Teacher.jsx';
      import { avatarInitials, ORIGINAL_NAV_LABEL } from './TeacherWorkspace.jsx';
      export {
        inviteKind, inviteErrorText, INVITE_LINK_USED, INVITE_LINK_USED_STAFF, INVITE_LINK_MISSING, sortStudentExams,
        rememberSitting, takeSittingToResume, REFERENCE_WRITING_LINE,
        linksAsText, linksAsCsv, chooseLiveExam, avatarInitials, ORIGINAL_NAV_LABEL,
      };
      export const invite = () => renderToStaticMarkup(React.createElement(InviteScreen, { onNavigate() {} }));
      export const sealed = () => renderToStaticMarkup(React.createElement(SubmittedScreen, { onNavigate() {} }));
    `,
    resolveDir: new URL('..', import.meta.url).pathname,
    loader: 'jsx',
  },
  bundle: true, platform: 'node', format: 'esm', write: false, jsx: 'automatic', logLevel: 'silent',
  loader: { '.css': 'empty' },
  banner: { js: "import { createRequire as __createRequire } from 'node:module'; const require = __createRequire(process.cwd() + '/');" },
});
const storage = () => {
  const m = new Map();
  return {
    getItem: k => (m.has(k) ? m.get(k) : null),
    setItem: (k, v) => { m.set(k, String(v)); },
    removeItem: k => { m.delete(k); },
    clear: () => m.clear(),
  };
};
globalThis.window = { BB_API_BASE: '', location: { search: '', origin: 'https://collections.example', href: 'https://collections.example/bluebook/' } };
globalThis.localStorage = storage();
globalThis.sessionStorage = storage();
const m = await import('data:text/javascript;base64,' + Buffer.from(built.outputFiles[0].text).toString('base64'));
const text = html => html.replace(/<[^>]+>/g, ' ').replace(/\s+/g, ' ');

// ── The set-password screen ──────────────────────────────────────────────────
test('the kind of link is read from its address', () => {
  assert.equal(m.inviteKind('?invite=abc&terms=1'), 'teacher');
  assert.equal(m.inviteKind('?reset=abc'), 'reset');
  assert.equal(m.inviteKind('?invite=abc'), 'student');
  assert.equal(m.inviteKind(''), 'student');
});

test('a used or expired link is explained with what to do next', () => {
  const said = m.inviteErrorText('This invite link is invalid, expired, or already used.');
  assert.equal(said, m.INVITE_LINK_USED);
  assert.match(said, /already been used, or it has expired/);
  assert.match(said, /sign in with your email and password/);
  assert.match(said, /ask your teacher for a new link/);
  // A teacher's (or a reset) link was not sent by a teacher.
  for (const kind of ['teacher', 'reset']) {
    const staff = m.inviteErrorText('This invite link is invalid, expired, or already used.', kind);
    assert.equal(staff, m.INVITE_LINK_USED_STAFF);
    assert.doesNotMatch(staff, /your teacher/);
  }
  // Anything else the server says is passed on as it is.
  assert.equal(m.inviteErrorText('Password must be at least 8 characters.'), 'Password must be at least 8 characters.');
});

test("a student's invitation asks them to read the student notice and accept the terms", () => {
  window.location.search = '?invite=abc';
  const html = m.invite();
  assert.match(text(html), /I have read the student notice and agree to the terms of service and privacy policy/);
  assert.match(html, /href="\.\.\/legal\/student-notice\.html"/);
  assert.match(text(html), /Already set your password\? Sign in/);
});

test("a teacher's invitation keeps the teacher's terms; a reset asks for none", () => {
  window.location.search = '?invite=abc&terms=1';
  let t = text(m.invite());
  assert.match(t, /I agree to the terms of service and privacy policy/);
  assert.doesNotMatch(t, /student notice and agree/);
  window.location.search = '?reset=abc';
  t = text(m.invite());
  assert.match(t, /Choose a new password/);
  assert.doesNotMatch(t, /I agree|I have read/);
});

test('a link with no code shows no form, only the way to sign in', () => {
  window.location.search = '?invite=';
  const html = m.invite();
  assert.match(text(html), new RegExp(m.INVITE_LINK_MISSING.slice(0, 40)));
  assert.match(text(html), /Go to sign in/);
  assert.doesNotMatch(html, /New password/);
});

// ── The student's exams ──────────────────────────────────────────────────────
test("a student's exams: in progress first, then open, upcoming, closed, submitted; oldest first inside each", () => {
  // The server lists exams newest first.
  const exams = [
    { exam_id: 'b2', state: 'open' },
    { exam_id: 'done', state: 'open', submitted: true },
    { exam_id: 'b1', state: 'open' },
    { exam_id: 'soon', state: 'upcoming' },
    { exam_id: 'going', state: 'open', session: { started_at: 'x' } },
    { exam_id: 'old', state: 'closed' },
  ];
  assert.deepEqual(m.sortStudentExams(exams).map(e => e.exam_id), ['going', 'b1', 'b2', 'soon', 'old', 'done']);
  assert.deepEqual(m.sortStudentExams(null), []);
});

test('a refresh mid-sitting goes back to that exam, once', () => {
  sessionStorage.clear();
  const exams = [{ exam_id: 'a', session: { x: 1 }, submitted: false }, { exam_id: 'b' }];
  m.rememberSitting('a');
  assert.equal(m.takeSittingToResume(exams).exam_id, 'a');
  // Used once: choosing "My exams" from the briefing then stays on the list.
  assert.equal(m.takeSittingToResume(exams), null);
  // Nothing to go back to: submitted, never started, or forgotten after the seal.
  m.rememberSitting('a');
  assert.equal(m.takeSittingToResume([{ exam_id: 'a', session: { x: 1 }, submitted: true }]), null);
  m.rememberSitting('b');
  assert.equal(m.takeSittingToResume(exams), null);
  m.rememberSitting('a'); m.rememberSitting(null);
  assert.equal(m.takeSittingToResume(exams), null);
});

// ── Invite links for the teacher ─────────────────────────────────────────────
test('"Copy all invite links" gives name, email and link, one per line, sorted by name', () => {
  const rows = [
    { name: 'Volunteer 10', email: 'v10@x.test', invite_path: '/bluebook/?invite=t10' },
    { name: 'Volunteer 2', email: 'v2@x.test', invite_path: '/bluebook/?invite=t2' },
    { name: 'No link', email: 'n@x.test' },
    { name: 'Volunteer 1', email: 'v1@x.test', invite_path: '/bluebook/?invite=t1' },
  ];
  assert.equal(m.linksAsText(rows), [
    'Volunteer 1\tv1@x.test\thttps://collections.example/bluebook/?invite=t1',
    'Volunteer 2\tv2@x.test\thttps://collections.example/bluebook/?invite=t2',
    'Volunteer 10\tv10@x.test\thttps://collections.example/bluebook/?invite=t10',
  ].join('\n'));
  const csv = m.linksAsCsv(rows).trim().split('\n');
  assert.equal(csv[0], 'name,email,invite_link,expires');
  assert.equal(csv.length, 4);
  assert.match(csv[1], /^Volunteer 1,v1@x\.test,https:\/\/collections\.example\/bluebook\/\?invite=t1,$/);
});

// ── The live view ────────────────────────────────────────────────────────────
test('the live view opens on the exam being written, then the next to start, then the first set', () => {
  // Server order: newest first.
  assert.equal(m.chooseLiveExam([
    { id: 'B', counts: { writing: 0, not_started: 20 } },
    { id: 'A', counts: { writing: 18, not_started: 2 } },
  ]), 'A');
  // During the break: A is all submitted, B is about to start.
  assert.equal(m.chooseLiveExam([
    { id: 'B', counts: { writing: 0, not_started: 20 } },
    { id: 'A', counts: { writing: 0, not_started: 0, submitted: 20 } },
  ]), 'B');
  // Before anything: the first exam the teacher set.
  assert.equal(m.chooseLiveExam([{ id: 'B', counts: { not_started: 20 } }, { id: 'A', counts: { not_started: 20 } }]), 'A');
  // An exam whose live view could not be read counts as nothing.
  assert.equal(m.chooseLiveExam([{ id: 'B', counts: null }, { id: 'A', counts: { writing: 1 } }]), 'A');
  assert.equal(m.chooseLiveExam([]), '');
});

// ── The teacher frame ────────────────────────────────────────────────────────
test("the avatar shows letters only, and Original's link says it is in testing", () => {
  assert.equal(m.avatarInitials('Andrew (Alpha test)'), 'AA');
  assert.equal(m.avatarInitials('Dr. Ada Lovelace'), 'DA');
  assert.equal(m.avatarInitials('Zoë'), 'Z');
  assert.equal(m.avatarInitials(''), 'T');
  assert.equal(m.avatarInitials('  (  ) '), 'T');
  assert.match(m.ORIGINAL_NAV_LABEL, /in testing/);
});

// ── The sealed screen ────────────────────────────────────────────────────────
test('the sealed screen says nothing about comparison when writing consistency is off', () => {
  window.BB_LAST_SUBMISSION = { ok: true, words: 120, title: 'Practice prompt 1', courseTitle: 'ALPHA1', candidate: 'Ada', withOriginal: true, compared: false };
  const t = text(m.sealed());
  assert.match(t, /Examination Sealed/);
  assert.doesNotMatch(t, /compar|score|consisten/i);
  assert.ok(t.includes(m.REFERENCE_WRITING_LINE), 'a workspace with Original tells the student about reference writing (NORTH_STAR rule 10)');
});

test('it says the writing will be compared only when the exam had writing consistency on', () => {
  window.BB_LAST_SUBMISSION = { ok: true, words: 120, title: 'T', withOriginal: true, compared: true };
  assert.match(text(m.sealed()), /Your writing will be compared with your own past work, as a starting point for your teacher, never proof of anything\./);
  window.BB_LAST_SUBMISSION = { ok: true, words: 120, title: 'T', withOriginal: false, compared: false };
  const t = text(m.sealed());
  assert.doesNotMatch(t, /compar/i);
  assert.ok(!t.includes(m.REFERENCE_WRITING_LINE), 'a Bluebook-only workspace says nothing about reference writing');
});

test('the reference-writing line uses no scoring words', () => {
  assert.doesNotMatch(m.REFERENCE_WRITING_LINE, /compar|score|profile|consisten/i);
  assert.match(m.REFERENCE_WRITING_LINE, /reference writing/);
});
