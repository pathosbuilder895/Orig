import { test } from 'node:test';
import assert from 'node:assert/strict';
import { build } from 'esbuild';

// NORTH_STAR rule 3 at the seal: a thin baseline (fewer than 3 approved
// samples) makes the exam INCONCLUSIVE, never "worth a look".
const built = await build({
  entryPoints: [new URL('../Exam.jsx', import.meta.url).pathname],
  bundle: true, platform: 'node', format: 'esm', write: false, jsx: 'automatic', logLevel: 'silent',
});
globalThis.window = { BB_API_BASE: '' };
globalThis.localStorage = { getItem: () => null, setItem: () => {}, removeItem: () => {} };
const { bbScoreWithOriginal, bbSealStatus, BB_NOT_ENOUGH_REFERENCE } = await import(
  'data:text/javascript;base64,' + Buffer.from(built.outputFiles[0].text).toString('base64')
);

const respond = (body, status = 200) => {
  globalThis.fetch = async () => new Response(JSON.stringify(body), { status });
};
const score = () => bbScoreWithOriginal('s1', 'Some text.', 'Essay', 'uuid-1', {});
const reading = { authorship: { authorship_probability: 0.42 } };

test('a ready baseline returns the score', async () => {
  respond({ ...reading, baseline_integrity: { readiness: 'ready' } });
  assert.equal(await score(), 42);
});
test('a thin baseline returns not-enough-reference, not a score', async () => {
  respond({ ...reading, baseline_integrity: { readiness: 'thin' } });
  assert.equal(await score(), BB_NOT_ENOUGH_REFERENCE);
});
test('a response without a readiness report is treated as thin', async () => {
  respond(reading);
  assert.equal(await score(), BB_NOT_ENOUGH_REFERENCE);
});
test('no baseline at all (422) still returns null, as before', async () => {
  respond({ detail: 'No baseline' }, 422);
  assert.equal(await score(), null);
});

test('only a ready, low reading marks an exam worth a look', () => {
  assert.equal(bbSealStatus(true, { aiScore: 42 }), 'FLAGGED');
  assert.equal(bbSealStatus(true, { aiScore: 85 }), 'SUBMITTED');
  assert.equal(bbSealStatus(true, { aiScore: null }), 'SUBMITTED');
});
test('a thin reading is INCONCLUSIVE whatever the score field holds', () => {
  assert.equal(bbSealStatus(true, { aiScore: null, inconclusive: true }), 'INCONCLUSIVE');
  assert.equal(bbSealStatus(true, { aiScore: 10, inconclusive: true }), 'INCONCLUSIVE');
});
test('a Bluebook-only exam is always SUBMITTED', () => {
  assert.equal(bbSealStatus(false, { aiScore: 10 }), 'SUBMITTED');
  assert.equal(bbSealStatus(false, { aiScore: null, inconclusive: true }), 'SUBMITTED');
});
