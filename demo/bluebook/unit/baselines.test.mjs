import { test } from 'node:test';
import assert from 'node:assert/strict';
import { build } from 'esbuild';

const bundle = async (file) => {
  const built = await build({
    entryPoints: [new URL(file, import.meta.url).pathname],
    bundle: true, platform: 'node', format: 'esm', write: false, jsx: 'automatic', logLevel: 'silent',
    loader: { '.css': 'empty' },  // forms.jsx imports its stylesheet; node has no use for it
  });
  return import('data:text/javascript;base64,' + Buffer.from(built.outputFiles[0].text).toString('base64'));
};

globalThis.window = { BB_API_BASE: '' };
globalThis.localStorage = { getItem: () => 'test-session', setItem() {}, removeItem() {} };
const { BB_API } = await bundle('../components.jsx');
const { baselineSummary } = await bundle('../Teacher.jsx');

test('baseline API methods call the approval routes', async () => {
  const calls = [];
  globalThis.fetch = async (url, init) => { calls.push([init.method, url]); return new Response('{}'); };
  await BB_API.addToBaseline('s 1');
  await BB_API.removeFromBaseline('s 1');
  await BB_API.examBaselineStatus('e/1');
  await BB_API.addExamToBaselines('e/1');
  assert.deepEqual(calls, [
    ['POST', '/bluebook/submissions/s%201/baseline'],
    ['DELETE', '/bluebook/submissions/s%201/baseline'],
    ['GET', '/bluebook/exams/e%2F1/baseline'],
    ['POST', '/bluebook/exams/e%2F1/baseline'],
  ]);
});

test('the bulk summary counts every outcome and names held students', () => {
  assert.equal(
    baselineSummary({ added: 2, already_in_baseline: 1, held: 1, nothing_written: 0, errors: 0,
      results: [{ status: 'held', student: 'Ana' }, { status: 'added', student: 'Ben' }] }),
    '2 added · 1 already in baseline · 1 held for review. Held: Ana.',
  );
  assert.equal(
    baselineSummary({ added: 0, already_in_baseline: 0, held: 0, nothing_written: 1, errors: 1, results: [] }),
    '0 added · 0 already in baseline · 0 held for review · 1 with nothing written · 1 could not be added.',
  );
});
