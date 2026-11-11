import { test } from 'node:test';
import assert from 'node:assert/strict';
import { build } from 'esbuild';

// Phone parking (2026-10): the briefing's Begin waits for this to be true.
const built = await build({
  entryPoints: [new URL('../Exam.jsx', import.meta.url).pathname],
  bundle: true, platform: 'node', format: 'esm', write: false, jsx: 'automatic', logLevel: 'silent',
});
globalThis.window = { BB_API_BASE: '' };
globalThis.localStorage = { getItem: () => null, setItem() {}, removeItem() {} };
const { bbPhoneParkCleared, examToConfig } = await import('data:text/javascript;base64,' + Buffer.from(built.outputFiles[0].text).toString('base64'));

test('off: nothing to wait for', () => {
  assert.equal(bbPhoneParkCleared({ required: false }), true);
});
test('on: waits until the phone is parked or the teacher lets the student begin', () => {
  assert.equal(bbPhoneParkCleared(null), false);
  assert.equal(bbPhoneParkCleared({ required: true, parked: false, overridden: false }), false);
  assert.equal(bbPhoneParkCleared({ required: true, parked: true, overridden: false }), true);
  assert.equal(bbPhoneParkCleared({ required: true, parked: false, overridden: true }), true);
});
test('the option reaches the briefing from the collection', () => {
  assert.equal(examToConfig({ id: 'e1', conditions: { phonePark: true } }).phonePark, true);
  assert.equal(examToConfig({ id: 'e1', conditions: {} }).phonePark, undefined);
});
