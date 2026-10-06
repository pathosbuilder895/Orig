import { test } from 'node:test';
import assert from 'node:assert/strict';
import { build } from 'esbuild';

const built = await build({
  entryPoints: [new URL('../Exam.jsx', import.meta.url).pathname],
  bundle: true, platform: 'node', format: 'esm', write: false, jsx: 'automatic', logLevel: 'silent',
});
globalThis.window = { BB_API_BASE: '' };
globalThis.localStorage = { getItem: () => null, setItem() {}, removeItem() {} };
const { examToConfig } = await import('data:text/javascript;base64,' + Buffer.from(built.outputFiles[0].text).toString('base64'));

test('a running sitting is marked in progress', () => {
  assert.equal(examToConfig({ id: 'e1', session: { started_at: 't', deadline_at: 'd' } }).inProgress, true);
});
test('an unstarted exam is not in progress', () => {
  assert.equal(examToConfig({ id: 'e1', session: null }).inProgress, false);
  assert.equal(examToConfig({ id: 'e1' }).inProgress, false);
});
test('a submitted sitting is not offered as a resume', () => {
  assert.equal(examToConfig({ id: 'e1', session: { started_at: 't', deadline_at: 'd' }, submitted: true }).inProgress, false);
});
