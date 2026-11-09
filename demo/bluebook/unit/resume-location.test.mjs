import { test } from 'node:test';
import assert from 'node:assert/strict';
import { build } from 'esbuild';

// locationFor: what a screen saves for resuming on another device.
const built = await build({
  entryPoints: [new URL('../resume-location.jsx', import.meta.url).pathname],
  bundle: true, platform: 'node', format: 'esm', write: false, jsx: 'automatic', logLevel: 'silent',
});
globalThis.window = { BB_API_BASE: '' };
globalThis.localStorage = { getItem: () => null, setItem() {}, removeItem() {} };
const { locationFor, scrollFraction, SAVE_DELAY_MS, resumeOrHome } = await import('data:text/javascript;base64,' + Buffer.from(built.outputFiles[0].text).toString('base64'));

test('saves about two seconds after a change', () => { assert.equal(SAVE_DELAY_MS, 2000); });

test('teacher screens keep their item, tab and scroll', () => {
  assert.deepEqual(
    locationFor('students', { view: { student: 't:ann' }, scroll: { fraction: 0.5, anchor: 'row-t:ann' } }),
    { screen: 'students', entity_kind: 'student', entity_id: 't:ann', scroll_fraction: 0.5, scroll_anchor: 'row-t:ann' });
  assert.deepEqual(
    locationFor('proctor', { w: { BB_PROCTOR_EXAM: '' }, view: { exam: 'abc123', tab: 'phones' } }),
    { screen: 'proctor', entity_kind: 'exam', entity_id: 'abc123', tab: 'phones', scroll_fraction: 0 });
  assert.equal(locationFor('manage-exam', { w: {} }), null);   // no exam: nothing to resume
  assert.equal(locationFor('collections').screen, 'sessions');
});

test('sign-in, set-password and form screens are never saved', () => {
  for (const s of ['login', 'invite', 'forgot', 'signup', 'landing', 'new-exam', 'submitted', 'student-home'])
    assert.equal(locationFor(s), null, s);
  assert.equal(locationFor('students', { student: true }), null);
});

test('a student in a sitting saves the exam briefing, never the sitting', () => {
  const loc = locationFor('exam', { student: true, w: { BB_EXAM_CONFIG: { id: 'ex1' } }, scroll: { fraction: 0.9 } });
  assert.deepEqual(loc, { screen: 'briefing', entity_kind: 'exam', entity_id: 'ex1' });
});

test('anything that is not a short identifier is dropped', () => {
  const loc = locationFor('students', { view: { student: '?invite=secret', tab: 'Bad Tab' }, scroll: { anchor: 'x y' } });
  assert.deepEqual(loc, { screen: 'students', scroll_fraction: 0 });
  assert.equal(locationFor('student-submission', { student: true, w: { BB_VIEW_SUBMISSION: 'a=b' } }), null);
});

test('scroll fraction is clamped and survives a short page', () => {
  assert.equal(scrollFraction(500, 2000, 1000), 0.5);
  assert.equal(scrollFraction(5000, 2000, 1000), 1);
  assert.equal(scrollFraction(10, 800, 1000), 0);
});

// resumeOrHome after a sign-in: who is signed in, what the address bar holds,
// and whether the saved place was asked for.
async function signIn(session, hash) {
  globalThis.localStorage = { getItem: k => session[k] ?? null, setItem() {}, removeItem() {} };
  globalThis.window.location = { hash };
  const asked = [];
  globalThis.fetch = async (url) => { asked.push(url); return { ok: true, json: async () => ({ location: null }) }; };
  const went = [];
  await resumeOrHome(s => went.push(s), 'home');
  return { asked, went };
}
const TEACHER = { original_principal_token: 't' };
const STUDENT = { original_role: 'student', original_session_token: 's' };

test('a teacher who followed a link goes home to open it, never to the saved place', async () => {
  for (const hash of ['#exam/abc', '#live/abc', '#students']) {
    const { asked, went } = await signIn(TEACHER, hash);
    assert.deepEqual(asked, [], hash);
    assert.deepEqual(went, ['home'], hash);
  }
});

test('without a link, and for a student whatever the address, the saved place is asked for', async () => {
  for (const [who, session, hash] of [['teacher', TEACHER, ''], ['teacher', TEACHER, '#forgot'], ['student', STUDENT, '#exam/abc']]) {
    const { asked, went } = await signIn(session, hash);
    assert.deepEqual(asked, ['/bluebook/me/location'], `${who} ${hash}`);
    assert.deepEqual(went, ['home'], `${who} ${hash}`);   // nothing saved here: home
  }
});
