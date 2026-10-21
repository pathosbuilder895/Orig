import { test } from 'node:test';
import assert from 'node:assert/strict';
import { build } from 'esbuild';

// bbPickServerDraft: a resuming page uses the server's copy of the draft only
// when it is newer than this device's copy and the local one is not final.
const built = await build({
  entryPoints: [new URL('../Exam.jsx', import.meta.url).pathname],
  bundle: true, platform: 'node', format: 'esm', write: false, jsx: 'automatic', logLevel: 'silent',
});
globalThis.window = { BB_API_BASE: '' };
globalThis.localStorage = { getItem: () => null, setItem() {}, removeItem() {} };
const { bbPickServerDraft, bbServerDraftsOn } = await import('data:text/javascript;base64,' + Buffer.from(built.outputFiles[0].text).toString('base64'));

const server = (answers, at) => ({ content: answers.join('\n'), answers, client_saved_at: at });

test('a new browser with no local draft takes the server copy', () => {
  assert.deepEqual(bbPickServerDraft(null, server(['hello'], 5)).answers, ['hello']);
  assert.deepEqual(bbPickServerDraft({ answers: [''], savedAt: 9 }, server(['hello'], 5)).answers, ['hello']);
});

test('the newer copy wins', () => {
  assert.equal(bbPickServerDraft({ answers: ['local'], savedAt: 10 }, server(['srv'], 5)), null);
  assert.equal(bbPickServerDraft({ answers: ['local'], savedAt: 10 }, server(['srv'], 10)), null);
  assert.deepEqual(bbPickServerDraft({ answers: ['local'], savedAt: 10 }, server(['srv'], 11)).answers, ['srv']);
});

test('a final local draft or an empty server draft is never replaced', () => {
  assert.equal(bbPickServerDraft({ answers: ['x'], savedAt: 1, seal: { confirmedAt: 'now' } }, server(['srv'], 99)), null);
  assert.equal(bbPickServerDraft(null, server(['  '], 99)), null);
  assert.equal(bbPickServerDraft(null, null), null);
});

test('only signed-in students on stored exams keep a server draft', () => {
  assert.equal(bbServerDraftsOn({ id: 'e1' }, true), true);
  assert.equal(bbServerDraftsOn({ id: 'e1' }, false), false);
  assert.equal(bbServerDraftsOn({ title: 'sample' }, true), false);
});
