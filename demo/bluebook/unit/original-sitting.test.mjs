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
const { bbOriginalForSitting } = await import('data:text/javascript;base64,' + Buffer.from(built.outputFiles[0].text).toString('base64'));

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
