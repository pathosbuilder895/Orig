import { test } from 'node:test';
import assert from 'node:assert/strict';
import { build } from 'esbuild';

// The plain-text copy of one sealed submission that a teacher can download
// from the reader. It must carry exactly what the reader shows, from the
// stored record only: nothing invented, nothing from Original.
const built = await build({
  entryPoints: [new URL('../Teacher.jsx', import.meta.url).pathname],
  bundle: true, platform: 'node', format: 'esm', write: false, jsx: 'automatic', logLevel: 'silent',
  external: ['../assets/*'], loader: { '.css': 'empty' },
});
globalThis.window = { BB_API_BASE: '' };
globalThis.localStorage = { getItem: () => null, setItem() {}, removeItem() {} };
const { submissionAsText, submissionFilename } = await import('data:text/javascript;base64,' + Buffer.from(built.outputFiles[0].text).toString('base64'));

const SUB = {
  exam: 'Ethics: Midterm', student: 'Ada Lovelace', course: 'PHIL 220',
  created_at: '2026-10-13T09:30:00Z', words: 412, timeMin: 47, late: 1,
  warnings: [{ type: 'focus_lost' }, { type: 'focus_lost' }, { type: 'paste_blocked' }],
  questions: ['First question?', 'Second question?'],
  answers: ['First answer.', ''],
  mark: 'B+', feedback: 'Clear argument.',
  ai_score: 12, stylometric: 40,
};

test('the text copy carries the record, every question and answer, and the session notes', () => {
  const text = submissionAsText(SUB);
  assert.match(text, /^Ethics: Midterm\n/);
  assert.match(text, /^Student: Ada Lovelace$/m);
  assert.match(text, /^Course: PHIL 220$/m);
  assert.match(text, /^Submitted: .+ · 412 words · 47 min · after the deadline$/m);
  assert.match(text, /^Session notes: Left the window × 2 · Tried to paste × 1$/m);
  assert.match(text, /^Mark: B\+$/m);
  assert.match(text, /^Feedback: Clear argument\.$/m);
  assert.match(text, /Question 1: First question\?\nFirst answer\./);
  assert.match(text, /Question 2: Second question\?\n\(No answer\.\)/);
});

test('it never carries a score', () => {
  const text = submissionAsText(SUB);
  assert.doesNotMatch(text, /\b12\b|\b40\b|score/i);
});

test('a single-answer submission and an empty record read sensibly', () => {
  const one = submissionAsText({ exam: 'Essay', student: 'Sam', words: 3, timeMin: 2, warnings: [], text: 'Three words here.' });
  assert.match(one, /^Session notes: none$/m);
  assert.match(one, /\n\nThree words here\.\n?$/);
  assert.doesNotMatch(one, /^Mark:|^Feedback:|^Course:/m);
  const none = submissionAsText({ exam: 'Essay', student: 'Sam', warnings: [] });
  assert.match(none, /The text of this submission is not available\./);
});

test('the file is named after the exam and the student, safely', () => {
  assert.equal(submissionFilename(SUB), 'Ethics-Midterm-Ada-Lovelace.txt');
  assert.equal(submissionFilename({ exam: '../../etc', student: '' }), 'etc-submission.txt');
  assert.equal(submissionFilename({}), 'submission.txt');
});
