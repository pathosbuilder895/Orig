import { test } from 'node:test';
import assert from 'node:assert/strict';
import { build } from 'esbuild';

// Where a signed-in staff member lands when they open the bare Collections
// address (staffOriginalHome in deep-link.jsx): a teacher whose workspace has
// Original opens Original, everyone and everything else stays in Collections.
// app.jsx applies it at page load and Landing.jsx after a sign-in.
const built = await build({
  entryPoints: [new URL('../deep-link.jsx', import.meta.url).pathname],
  bundle: true, platform: 'node', format: 'esm', write: false, jsx: 'automatic', logLevel: 'silent',
});
globalThis.window = { location: { hash: '', pathname: '/bluebook/', search: '' } };
const {
  staffOriginalHome, staffHomeRedirect, parseDeepLink, markCollectionsTab, inCollectionsTab, clearCollectionsTab,
  COLLECTIONS_TAB_KEY,
} = await import(
  'data:text/javascript;base64,' + Buffer.from(built.outputFiles[0].text).toString('base64'));

const TEACHER = {
  authed: true, studentAccount: false, studentLaunch: false, hasOriginal: true,
  role: 'professor', pathname: '/bluebook/', search: '', hash: '',
};
const at = (over) => staffOriginalHome({ ...TEACHER, ...over });

test('a signed-in teacher with Original at the bare address opens Original', () => {
  assert.equal(at({}), '/original/');
  assert.equal(at({ pathname: '/bluebook' }), '/original/');
  assert.equal(at({ pathname: '/bluebook/index.html' }), '/original/');
  assert.equal(at({ hash: '#' }), '/original/');
  assert.equal(at({ role: 'super_admin' }), '/original/');
});

test('admin and operator go where the main sign-in page sends them', () => {
  assert.equal(at({ role: 'admin' }), '/admin.html');
  assert.equal(at({ role: 'operator' }), '/operator.html');
});

test('a workspace without Original stays in Collections', () => {
  assert.equal(at({ hasOriginal: false }), null);
  assert.equal(at({ hasOriginal: false, role: 'admin' }), null);
});

test('students, student launches and signed-out visitors stay', () => {
  assert.equal(at({ authed: false }), null);
  assert.equal(at({ studentAccount: true }), null);
  assert.equal(at({ studentLaunch: true }), null);
  assert.equal(at({ role: 'student' }), null);
  assert.equal(at({ role: '' }), null);
  assert.equal(at({ role: 'toString' }), null);
});

test('any hash stays: a deep link, a remembered screen, #dashboard, #forgot', () => {
  for (const hash of ['#exam/abc123', '#live/abc123', '#students', '#courses', '#collections',
    '#results', '#sessions', '#exams', '#dashboard', '#forgot', '#anything']) {
    assert.equal(at({ hash }), null, hash);
  }
});

test('#dashboard is a link to the Collections dashboard', () => {
  assert.deepEqual(parseDeepLink('#dashboard'), { kind: 'screen', screen: 'dashboard' });
});

test('join, invite and reset links stay; other queries do not block', () => {
  assert.equal(at({ search: '?join=abc' }), null);
  assert.equal(at({ search: '?invite=abc' }), null);
  assert.equal(at({ search: '?reset=abc' }), null);
  assert.equal(at({ search: '?x=1&join=abc' }), null);
  assert.equal(at({ search: '?x=1' }), '/original/');
});

test('/collections/ names Collections on purpose and never leaves', () => {
  assert.equal(at({ pathname: '/collections/' }), null);
  assert.equal(at({ pathname: '/collections' }), null);
  assert.equal(at({ pathname: '/bluebook/parked.html' }), null);
  assert.equal(at({ pathname: '/bluebookx/' }), null);
  assert.equal(at({ pathname: undefined }), null);
});

test('a tab already working in Collections stays, so a reload of an unnamed screen stays', () => {
  assert.equal(at({ inCollections: true }), null);
  assert.equal(at({ inCollections: false }), '/original/');
});

test('the Collections tab mark lives in sessionStorage and is cleared on request', () => {
  // No sessionStorage at all (a locked-down browser): never marked, never throws.
  assert.equal(inCollectionsTab(), false);
  markCollectionsTab();
  clearCollectionsTab();
  const store = new Map();
  globalThis.sessionStorage = {
    getItem: k => (store.has(k) ? store.get(k) : null),
    setItem: (k, v) => { store.set(k, String(v)); },
    removeItem: k => { store.delete(k); },
  };
  try {
    assert.equal(inCollectionsTab(), false);
    markCollectionsTab();
    assert.equal(store.get(COLLECTIONS_TAB_KEY), '1');
    assert.equal(inCollectionsTab(), true);
    clearCollectionsTab();
    assert.equal(inCollectionsTab(), false);
  } finally {
    delete globalThis.sessionStorage;
  }
});

test('no arguments at all stays', () => {
  assert.equal(staffOriginalHome(), null);
});

test('staffHomeRedirect reads the sign-in from the api and the address', () => {
  const api = (over = {}) => ({
    isAuthed: () => true, isStudentAccount: () => false, isStudentLaunch: () => false,
    hasOriginal: () => true, identity: () => ({ role: 'professor' }), ...over,
  });
  assert.equal(staffHomeRedirect(api(), { pathname: '/bluebook/', search: '', hash: '' }), '/original/');
  assert.equal(staffHomeRedirect(api(), { pathname: '/bluebook/', search: '', hash: '#students' }), null);
  assert.equal(staffHomeRedirect(api({ hasOriginal: () => false }), { pathname: '/bluebook/', search: '', hash: '' }), null);
  assert.equal(staffHomeRedirect(api({ identity: () => ({ role: 'student' }) }), { pathname: '/bluebook/' }), null);
  // Without an address given it reads window.location.
  assert.equal(staffHomeRedirect(api()), '/original/');
  // A tab marked as working in Collections stays.
  globalThis.sessionStorage = { getItem: () => '1', setItem() {}, removeItem() {} };
  try {
    assert.equal(staffHomeRedirect(api()), null);
  } finally {
    delete globalThis.sessionStorage;
  }
});
