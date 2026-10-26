import { test } from 'node:test';
import assert from 'node:assert/strict';
import { build } from 'esbuild';

// Course join links (Account.jsx JoinScreen, Teacher.jsx JoinLinkPanel and
// ClassListImport): what the student and the teacher are told. The flow
// itself (code, approval, domain limit) is pinned server-side in
// tests/test_course_join.py; this pins the words, rendered for real with
// react-dom/server. Student-facing text names Original Collections and says
// nothing about scores or the consistency engine.
const built = await build({
  stdin: {
    contents: `
      import React from 'react';
      import { renderToStaticMarkup } from 'react-dom/server';
      import { JoinScreen, joinCodeFromUrl, joinIntro, JOIN_APPROVAL_NOTE, pendingNotice } from './Account.jsx';
      import { ClassListImport, JoinLinkPanel, JOIN_PANEL_INTRO } from './Teacher.jsx';
      export { joinCodeFromUrl, joinIntro, JOIN_APPROVAL_NOTE, pendingNotice, JOIN_PANEL_INTRO };
      export const join = () => renderToStaticMarkup(React.createElement(JoinScreen, { onNavigate() {} }));
      export const panel = () => renderToStaticMarkup(React.createElement(JoinLinkPanel, { courseId: 'c1', onError() {} }));
      export const upload = () => renderToStaticMarkup(React.createElement(ClassListImport, {
        courseId: 'c1', rosterEmails: [], sendEmail: false, onDone() {}, onCancel() {},
      }));
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
const ENGINE_WORDS = /score|consisten|stylometr|deviation|baseline|\bOriginal\b(?! Collections)/i;

test('the join code is read from the link', () => {
  assert.equal(m.joinCodeFromUrl('?join=K7QW3X'), 'K7QW3X');
  assert.equal(m.joinCodeFromUrl('?invite=abc'), '');
  assert.equal(m.joinCodeFromUrl(''), '');
});

test('without a code, the screen asks for one', () => {
  window.location.search = '';
  const t = text(m.join());
  assert.match(t, /Join a course/);
  assert.match(t, /Enter the class code your teacher gave you/);
  assert.match(t, /Class code/);
  assert.match(t, /Already joined\? Sign in/);
  assert.doesNotMatch(t, ENGINE_WORDS);
});

test('the course and the approval rule are said in plain words, with the product name', () => {
  const course = { code: 'K7QW3X', course_name: 'Ethics 101', course_code: 'ETH101', require_approval: true, allowed_domain: '' };
  const intro = m.joinIntro(course);
  assert.match(intro, /^Create your Original Collections account to join Ethics 101 \(ETH101\)\./);
  assert.match(intro, /Use the same email and the password you already have\./);
  assert.equal(m.joinIntro({ ...course, course_code: '' }).includes('Ethics 101.'), true);
  for (const words of [intro, m.JOIN_APPROVAL_NOTE]) assert.doesNotMatch(words, ENGINE_WORDS);
});

test('a waiting student is told which courses wait on their teacher', () => {
  assert.equal(m.pendingNotice([]), '');
  assert.equal(m.pendingNotice(undefined), '');
  assert.equal(m.pendingNotice([{ name: 'Ethics 101' }]),
    'Waiting for your teacher to approve you for Ethics 101. Its collections appear here once you are approved.');
  assert.equal(m.pendingNotice([{ name: 'Ethics 101' }, { code: 'LOG1' }, { name: 'Greek' }]),
    'Waiting for your teacher to approve you for Ethics 101, LOG1 and Greek. Their collections appear here once you are approved.');
  assert.doesNotMatch(m.pendingNotice([{ name: 'X' }]), ENGINE_WORDS);
});

test('the teacher panels render before their data arrives', () => {
  assert.match(text(m.panel()), /Join link Loading/);
  assert.match(m.JOIN_PANEL_INTRO, /type the code on the sign-in page/);
  const up = text(m.upload());
  assert.match(up, /Upload class list/);
  assert.match(up, /The file stays on this computer/);
  assert.match(up, /Choose a CSV file/);
});
