import { test } from 'node:test';
import assert from 'node:assert/strict';
import { build } from 'esbuild';

// The Collections list (Teacher.jsx): what each card says, the order cards
// come in, and the filters and search. Pure helpers; no browser needed.
const built = await build({
  stdin: {
    contents: `
      export { collectionFacts, collectionType, filterCollections, orderCollections, NO_FILTERS } from './Teacher.jsx';
    `,
    resolveDir: new URL('..', import.meta.url).pathname,
    loader: 'jsx',
  },
  bundle: true, platform: 'node', format: 'esm', write: false, jsx: 'automatic', logLevel: 'silent',
  loader: { '.css': 'empty' },
  banner: { js: "import { createRequire as __createRequire } from 'node:module'; const require = __createRequire(process.cwd() + '/');" },
});
const store = new Map();
globalThis.window = { BB_API_BASE: '', location: { origin: 'https://collections.example' } };
globalThis.localStorage = { getItem: k => (store.has(k) ? store.get(k) : null), setItem: (k, v) => store.set(k, String(v)), removeItem: k => store.delete(k) };
const m = await import('data:text/javascript;base64,' + Buffer.from(built.outputFiles[0].text).toString('base64'));

const lock = { blockAI: true, blockWeb: true, blockCopy: true };
const day = 86400000;
const iso = ms => new Date(Date.now() + ms).toISOString();
// Server order: newest first.
const exams = [
  { id: 'd', title: 'Diagnostic', course: 'WRT 210', status: 'DRAFT', duration: 30, conditions: lock },
  { id: 'c', title: 'In-class essay', course: 'WRT 210', status: 'ACTIVE', duration: 50, conditions: { ...lock, size: 'great' }, minWords: 1001, opens_at: iso(-3 * day), closes_at: iso(-day) },
  { id: 'u', title: 'Term paper draft', course: 'WRT 210', status: 'ACTIVE', duration: 90, conditions: { ...lock, blockWeb: false, timed: false, setting: 'take_home', size: 'great' }, opens_at: iso(2 * day) },
  { id: 'r', title: 'Reading response', course: 'WRT 210', status: 'ACTIVE', duration: 40, conditions: { blockCopy: false, timed: false, setting: 'take_home', size: 'small' } },
  { id: 'p2', title: 'Practice prompt 2', course: 'ALPHA1', status: 'ACTIVE', duration: 25, conditions: lock },
  // The alpha's shape: an older row, timed, locked, no size or setting.
  { id: 'p1', title: 'Practice prompt 1', course: 'ALPHA1', status: 'ACTIVE', duration: 25, minWords: 0, maxWords: 0, conditions: lock },
];
const ids = list => list.map(e => e.id);

test('a card reads the options: size, timed, locked, setting and state', () => {
  assert.deepEqual(m.collectionFacts(exams[5]), { size: '', timed: true, locked: true, setting: 'in_class', state: 'open' });
  assert.deepEqual(m.collectionFacts(exams[3]), { size: 'small', timed: false, locked: false, setting: 'take_home', state: 'open' });
  assert.equal(m.collectionFacts(exams[2]).state, 'upcoming');
  assert.equal(m.collectionFacts(exams[1]).state, 'closed');
  assert.equal(m.collectionFacts(exams[0]).state, 'draft');
  // A row with no conditions at all reads as timed, open, in class.
  assert.deepEqual(m.collectionFacts({ status: 'ACTIVE', duration: 90 }), { size: '', timed: true, locked: false, setting: 'in_class', state: 'open' });
  assert.equal(m.collectionType(exams[2]), 'Take-home · Great');
  assert.equal(m.collectionType(exams[5]), 'In class');
});

test('cards come open first, then upcoming, drafts and closed, newest first inside each', () => {
  assert.deepEqual(ids(m.orderCollections(exams)), ['r', 'p2', 'p1', 'u', 'd', 'c']);
});

test('each filter narrows the list, and they combine', () => {
  const f = filters => ids(m.filterCollections(exams, filters));
  assert.deepEqual(f(m.NO_FILTERS), ids(exams));
  assert.deepEqual(f({ status: 'open' }), ['r', 'p2', 'p1']);
  assert.deepEqual(f({ size: 'great' }), ['c', 'u']);
  assert.deepEqual(f({ size: 'small' }), ['r']);
  assert.deepEqual(f({ timing: 'untimed' }), ['u', 'r']);
  assert.deepEqual(f({ timing: 'timed' }), ['d', 'c', 'p2', 'p1']);
  assert.deepEqual(f({ paste: 'open' }), ['r']);
  assert.deepEqual(f({ paste: 'locked' }), ['d', 'c', 'u', 'p2', 'p1']);
  assert.deepEqual(f({ setting: 'take_home' }), ['u', 'r']);
  assert.deepEqual(f({ size: 'great', timing: 'untimed' }), ['u']);
});

test('search matches the title or the course, ignoring case and spaces', () => {
  const f = q => ids(m.filterCollections(exams, { q }));
  assert.deepEqual(f('practice'), ['p2', 'p1']);
  assert.deepEqual(f('  ALPHA1 '), ['p2', 'p1']);
  assert.deepEqual(f('wrt'), ['d', 'c', 'u', 'r']);
  assert.deepEqual(f('nothing like this'), []);
});
