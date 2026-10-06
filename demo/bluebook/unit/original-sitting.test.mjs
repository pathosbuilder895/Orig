import { test } from 'node:test';
import assert from 'node:assert/strict';
import { build } from 'esbuild';

// bbOriginalForSitting: what the briefing tells the student must be what the
// seal does. Once a sitting has started, its draft holds the decision; before
// that, the workspace's current products answer.
const built = await build({
  entryPoints: [new URL('../Exam.jsx', import.meta.url).pathname],
  bundle: true, platform: 'node', format: 'esm', write: false, jsx: 'automatic', logLevel: 'silent',
});
const store = new Map();
globalThis.window = { BB_API_BASE: '' };
globalThis.localStorage = {
  getItem: k => (store.has(k) ? store.get(k) : null),
  setItem: (k, v) => { store.set(k, String(v)); },
  removeItem: k => { store.delete(k); },
};
const { bbOriginalForSitting, bbLockOriginalDecision } = await import('data:text/javascript;base64,' + Buffer.from(built.outputFiles[0].text).toString('base64'));

const cfg = { id: 'exam-1', title: 'Switch exam' };
const products = list => store.set('original_products', JSON.stringify(list));
const draft = seal => store.set('bb_draft_exam-1', JSON.stringify({ content: '', answers: [''], seal }));

test('a sitting that started with Original keeps it after Original is switched off', () => {
  store.clear();
  draft({ uuid: null, withOriginal: true });
  products(['bluebook']);
  assert.equal(bbOriginalForSitting(cfg), true);
});
test('a sitting that started without Original keeps that after Original is switched on', () => {
  store.clear();
  draft({ uuid: null, withOriginal: false });
  products(['bluebook', 'original']);
  assert.equal(bbOriginalForSitting(cfg), false);
});
test('with no draft the workspace products answer', () => {
  store.clear();
  products(['bluebook', 'original']);
  assert.equal(bbOriginalForSitting(cfg), true);
  products(['bluebook']);
  assert.equal(bbOriginalForSitting(cfg), false);
});
test('a draft without a boolean decision (an older page) falls back to the products', () => {
  store.clear();
  draft({ uuid: 'u1', aiScore: null, baselineData: null });
  products(['bluebook']);
  assert.equal(bbOriginalForSitting(cfg), false);
  draft({ uuid: 'u1', withOriginal: 'yes' });
  products(['bluebook', 'original']);
  assert.equal(bbOriginalForSitting(cfg), true);
  store.set('bb_draft_exam-1', '{not json');
  assert.equal(bbOriginalForSitting(cfg), true);
});
test('another exam\'s draft does not decide this one', () => {
  store.clear();
  store.set('bb_draft_exam-2', JSON.stringify({ seal: { withOriginal: true } }));
  products(['bluebook']);
  assert.equal(bbOriginalForSitting(cfg), false);
});

// bbLockOriginalDecision: the briefing writes its displayed decision into the
// draft when the student clicks Begin, so another tab refreshing the stored
// products before the exam screen mounts cannot change what the sitting does.
const read = () => JSON.parse(store.get('bb_draft_exam-1'));

test('Begin writes the displayed decision when the draft has none', () => {
  store.clear();
  assert.equal(bbLockOriginalDecision(cfg, false), false);
  const d = read();
  assert.equal(d.seal.withOriginal, false);
  assert.equal(d.seal.uuid, null);
  assert.equal(d.seal.baselineData, null);
  assert.deepEqual(d.answers, ['']);
  assert.equal(d.content, '');
  assert.deepEqual(d.warnings, []);
  assert.equal(typeof d.savedAt, 'number');
  // Products change before the exam screen mounts: the sitting still says false.
  products(['bluebook', 'original']);
  assert.equal(bbOriginalForSitting(cfg), false);
  store.clear();
  assert.equal(bbLockOriginalDecision(cfg, true), true);
  assert.equal(read().seal.withOriginal, true);
});
test('Begin writes one empty answer per question for a multi-question exam', () => {
  store.clear();
  bbLockOriginalDecision({ ...cfg, questions: ['a', 'b', 'c'] }, true);
  assert.deepEqual(read().answers, ['', '', '']);
});
test('Begin never overwrites an existing boolean decision', () => {
  for (const [stored, shown] of [[true, false], [false, true]]) {
    store.clear();
    draft({ uuid: 'u1', withOriginal: stored });
    const before = store.get('bb_draft_exam-1');
    assert.equal(bbLockOriginalDecision(cfg, shown), stored);
    assert.equal(store.get('bb_draft_exam-1'), before);
  }
});
test('Begin keeps every other draft field when it adds the decision', () => {
  store.clear();
  const existing = {
    content: 'Question 1.\nWords already written.', answers: ['Words already written.'],
    seal: { uuid: 'u9', aiScore: 88, baselineData: { ok: true } },
    warnings: [{ id: 'tab_hidden' }], savedAt: 12345,
  };
  store.set('bb_draft_exam-1', JSON.stringify(existing));
  assert.equal(bbLockOriginalDecision(cfg, true), true);
  assert.deepEqual(read(), { ...existing, seal: { ...existing.seal, withOriginal: true } });
});
test('Begin adds a seal to a draft that has none, and replaces an unreadable draft', () => {
  store.clear();
  store.set('bb_draft_exam-1', JSON.stringify({ content: 'x', answers: ['x'], savedAt: 1 }));
  bbLockOriginalDecision(cfg, false);
  assert.deepEqual(read().answers, ['x']);
  assert.equal(read().seal.withOriginal, false);
  store.set('bb_draft_exam-1', '{not json');
  bbLockOriginalDecision(cfg, true);
  assert.equal(read().seal.withOriginal, true);
});
test('Begin does not throw when storage cannot be written', () => {
  store.clear();
  const set = globalThis.localStorage.setItem;
  globalThis.localStorage.setItem = () => { throw new Error('quota'); };
  try { assert.equal(bbLockOriginalDecision(cfg, true), null); }
  finally { globalThis.localStorage.setItem = set; }
});
