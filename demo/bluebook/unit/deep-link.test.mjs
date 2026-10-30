import { test } from 'node:test';
import assert from 'node:assert/strict';
import { build } from 'esbuild';

// Deep links into one exam (deep-link.jsx): #exam/<id> opens Manage
// examination, #live/<id> the live view. The behaviour in the app (signed-in
// teacher only, unknown ids fall back to the dashboard) is covered by
// e2e/deep-link.spec.mjs; this pins the parsing and the screen each link picks.
const built = await build({
  entryPoints: [new URL('../deep-link.jsx', import.meta.url).pathname],
  bundle: true, platform: 'node', format: 'esm', write: false, jsx: 'automatic', logLevel: 'silent',
});

function fakeWindow(href) {
  const url = new URL(href);
  const calls = [];
  return {
    calls,
    location: {
      get hash() { return url.hash; },
      get pathname() { return url.pathname; },
      get search() { return url.search; },
    },
    history: {
      state: { kept: true },
      replaceState(state, _title, next) { calls.push({ state, next }); url.href = new URL(next, url).href; },
    },
  };
}

globalThis.window = fakeWindow('https://example.test/bluebook/');
const { parseDeepLink, deepLinkScreen, clearDeepLink, DEEP_LINK_SCREEN, FORGOT_HASH } = await import(
  'data:text/javascript;base64,' + Buffer.from(built.outputFiles[0].text).toString('base64'));

test('#exam/<id> and #live/<id> are deep links', () => {
  assert.deepEqual(parseDeepLink('#exam/3f2a9c01d4e5b6a7'), { kind: 'exam', id: '3f2a9c01d4e5b6a7' });
  assert.deepEqual(parseDeepLink('#live/demo-exam_1'), { kind: 'live', id: 'demo-exam_1' });
});

test('#students and #courses are links to a whole screen, with no id', () => {
  assert.deepEqual(parseDeepLink('#students'), { kind: 'screen', screen: 'students' });
  assert.deepEqual(parseDeepLink('#courses'), { kind: 'screen', screen: 'courses' });
  for (const hash of ['#students/', '#students/abc', '#student', '#courses?x=1', '#Courses', '#STUDENTS', '#courses ', ' #courses', 'students']) {
    assert.equal(parseDeepLink(hash), null, hash);
  }
});

test('anything else is not a deep link', () => {
  for (const hash of [
    '', '#', '#exam', '#exam/', '#live/', '#results/abc', '#EXAM/abc', 'exam/abc',
    '#exam/abc/def', '#exam/abc?x=1', '#exam/a%2Fb', '#exam/<script>', '#exam/ abc',
    '#exam/' + 'a'.repeat(65), null, undefined, 42,
  ]) {
    assert.equal(parseDeepLink(hash), null, String(hash));
  }
});

test('each link opens its own screen and points it at the exam', () => {
  assert.deepEqual(DEEP_LINK_SCREEN, { exam: 'manage-exam', collection: 'manage-exam', live: 'proctor' });
  assert.equal(deepLinkScreen({ kind: 'exam', id: 'e1' }, { id: 'e1' }), 'manage-exam');
  assert.equal(globalThis.window.BB_MANAGE_EXAM, 'e1');
  assert.equal(deepLinkScreen({ kind: 'live', id: 'e2' }, { id: 'e2' }), 'proctor');
  assert.equal(globalThis.window.BB_PROCTOR_EXAM, 'e2');
});

test('#collection/<id> is the same deep link as #exam/<id>', () => {
  assert.deepEqual(parseDeepLink('#collection/3f2a9c01d4e5b6a7'), { kind: 'collection', id: '3f2a9c01d4e5b6a7' });
  assert.equal(deepLinkScreen({ kind: 'collection', id: 'c1' }, { id: 'c1' }), 'manage-exam');
  assert.equal(globalThis.window.BB_MANAGE_EXAM, 'c1');
});

test('#collections, and the old #exams and #sessions links, open the one Collections list', () => {
  for (const h of ['#collections', '#exams', '#sessions']) {
    assert.deepEqual(parseDeepLink(h), { kind: 'screen', screen: 'sessions' }, h);
  }
  assert.equal(parseDeepLink('#collection'), null);
});

test('clearing drops only a deep-link hash and keeps the path and query', () => {
  globalThis.window = fakeWindow('https://example.test/bluebook/?dev=0#exam/abc');
  clearDeepLink();
  assert.deepEqual(globalThis.window.calls, [{ state: { kept: true }, next: '/bluebook/?dev=0' }]);

  globalThis.window = fakeWindow('https://example.test/bluebook/#somewhere-else');
  clearDeepLink();
  assert.deepEqual(globalThis.window.calls, []);
});

test('#forgot is not a deep link, and moving on drops it like one', () => {
  assert.equal(FORGOT_HASH, '#forgot');
  assert.equal(parseDeepLink('#forgot'), null);
  globalThis.window = fakeWindow('https://example.test/bluebook/?x=1#forgot');
  clearDeepLink();
  assert.deepEqual(globalThis.window.calls, [{ state: { kept: true }, next: '/bluebook/?x=1' }]);
});

test('a visitor still signing in keeps a deep link, so signing in can open it', () => {
  for (const hash of ['#exam/abc', '#live/abc', '#students']) {
    globalThis.window = fakeWindow(`https://example.test/bluebook/${hash}`);
    clearDeepLink({ signingIn: true });
    assert.deepEqual(globalThis.window.calls, [], hash);
  }
  // '#forgot' is not a deep link: leaving the reset form still drops it.
  globalThis.window = fakeWindow('https://example.test/bluebook/?x=1#forgot');
  clearDeepLink({ signingIn: true });
  assert.deepEqual(globalThis.window.calls, [{ state: { kept: true }, next: '/bluebook/?x=1' }]);
});

test('clearing never throws when history is unavailable', () => {
  globalThis.window = { location: { hash: '#exam/abc', pathname: '/bluebook/', search: '' } };
  assert.doesNotThrow(() => clearDeepLink());
});
