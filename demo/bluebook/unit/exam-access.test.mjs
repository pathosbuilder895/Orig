import { test } from 'node:test';
import assert from 'node:assert/strict';
import { build } from 'esbuild';

// The exam screen's timer, word count and seal-retry rules, as pure helpers.
// The screen renders and announces whatever these return, so a wrong answer
// here is a wrong announcement to a student using a screen reader, or a seal
// that gives up (or keeps hammering) when it should not.
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
const {
  bbClock, bbSpokenTime, bbTimeMilestone, bbWordSummary, bbWordMilestone,
  bbSealHint, bbSealRetryable, BB_SEAL_BACKOFF, bbDraftKey,
} = await import('data:text/javascript;base64,' + Buffer.from(built.outputFiles[0].text).toString('base64'));

test('the visible clock shows hours once a sitting is an hour or longer', () => {
  assert.equal(bbClock(7199), '1:59:59');
  assert.equal(bbClock(3600), '1:00:00');
  assert.equal(bbClock(3599), '59:59');
  assert.equal(bbClock(300), '05:00');
  assert.equal(bbClock(0), '00:00');
  assert.equal(bbClock(-4), '00:00');
});

test('the spoken time is words a screen reader can say, not a clock face', () => {
  assert.equal(bbSpokenTime(7199), '1 hour 59 minutes');
  assert.equal(bbSpokenTime(7260), '2 hours 1 minute');
  assert.equal(bbSpokenTime(3600), '1 hour');
  assert.equal(bbSpokenTime(1800), '30 minutes');
  // Under five minutes the seconds matter.
  assert.equal(bbSpokenTime(299), '4 minutes 59 seconds');
  assert.equal(bbSpokenTime(60), '1 minute');
  assert.equal(bbSpokenTime(61), '1 minute 1 second');
  assert.equal(bbSpokenTime(45), '45 seconds');
  assert.equal(bbSpokenTime(0), '0 seconds');
});

test('a time milestone is announced once, when the clock crosses it', () => {
  assert.equal(bbTimeMilestone(1801, 1800), '30 minutes remaining.');
  assert.equal(bbTimeMilestone(1800, 1799), null);   // already announced at 1800
  assert.equal(bbTimeMilestone(901, 899), '15 minutes remaining.');
  assert.equal(bbTimeMilestone(601, 600), '10 minutes remaining.');
  assert.equal(bbTimeMilestone(301, 300), '5 minutes remaining.');
  assert.equal(bbTimeMilestone(61, 60), '1 minute remaining.');
  assert.equal(bbTimeMilestone(1000, 999), null);
  assert.equal(bbTimeMilestone(59, 58), null);
});

test('a clock that jumps past several milestones announces the time actually left', () => {
  // A throttled background tab can skip many ticks at once.
  assert.equal(bbTimeMilestone(1000, 250), '4 minutes 10 seconds remaining.');
});

test('the word summary tells the student where they stand', () => {
  assert.equal(bbWordSummary(0, 600, 1200), '0 words written. Write at least 600 words to submit. The limit is 1,200 words.');
  assert.equal(bbWordSummary(1, 0, 0), '1 word written.');
  assert.equal(bbWordSummary(650, 600, 1200), '650 words written. You have reached the 600-word minimum. The limit is 1,200 words.');
  assert.equal(bbWordSummary(1250, 600, 1200), '1,250 words written. You are over the 1,200-word limit.');
  assert.equal(bbWordSummary(30, 0, 1200), '30 words written. The limit is 1,200 words.');
});

test('word-count milestones are announced only when crossed upwards', () => {
  assert.equal(bbWordMilestone(599, 600, 600, 1200), 'You have reached the 600-word minimum.');
  assert.equal(bbWordMilestone(600, 601, 600, 1200), null);
  assert.equal(bbWordMilestone(601, 599, 600, 1200), null);
  assert.equal(bbWordMilestone(1200, 1201, 600, 1200), 'You are now over the 1,200-word limit.');
  assert.equal(bbWordMilestone(0, 5, 0, 0), null);
});

test('the seal button explains why it cannot be pressed yet', () => {
  assert.equal(bbSealHint(588, 600), 'Write 12 more words to submit.');
  assert.equal(bbSealHint(599, 600), 'Write 1 more word to submit.');
  assert.equal(bbSealHint(600, 600), null);
  assert.equal(bbSealHint(0, 0), null);
});

test('a seal retries network trouble and server hiccups, never a refusal', () => {
  const err = status => Object.assign(new Error('x'), status ? { status } : {});
  assert.equal(bbSealRetryable(err()), true);            // fetch threw: offline, DNS, reset
  assert.equal(bbSealRetryable(new TypeError('Failed to fetch')), true);
  for (const s of [500, 502, 503, 504, 408, 425, 429]) assert.equal(bbSealRetryable(err(s)), true, String(s));
  for (const s of [400, 401, 403, 404, 413, 422]) assert.equal(bbSealRetryable(err(s)), false, String(s));
});

test('the seal keeps trying for long enough to ride out a redeploy', () => {
  const total = BB_SEAL_BACKOFF.reduce((a, b) => a + b, 0);
  assert.ok(BB_SEAL_BACKOFF.length >= 4, 'at least five attempts');
  assert.ok(total >= 30_000 && total <= 60_000, `waits ${total}ms in all`);
  assert.deepEqual([...BB_SEAL_BACKOFF].sort((a, b) => a - b), BB_SEAL_BACKOFF, 'waits never shrink');
});

test('a draft belongs to the student who wrote it', () => {
  store.clear();
  const cfg = { id: 'exam-9', title: 'Essay' };
  // Nobody bound (a teacher previewing): the exam alone names the draft.
  assert.equal(bbDraftKey(cfg), 'bb_draft_exam-9');
  // A launch-link student.
  store.set('bluebook_student_id', 'tenant:aaaa');
  assert.equal(bbDraftKey(cfg), 'bb_draft_tenant:aaaa|exam-9');
  // A student who signed in with an account.
  store.clear();
  store.set('original_role', 'student');
  store.set('original_student_id', 'tenant:bbbb');
  assert.equal(bbDraftKey(cfg), 'bb_draft_tenant:bbbb|exam-9');
  // A teacher's own sign-in carries no student id.
  store.clear();
  store.set('original_role', 'professor');
  store.set('original_student_id', 'tenant:stale');
  assert.equal(bbDraftKey(cfg), 'bb_draft_exam-9');
});
