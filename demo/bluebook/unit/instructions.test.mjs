import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { build } from 'esbuild';

// The Instructions guide (instructions.jsx) opened from the teacher and
// student navigation bars. Rendered for real with react-dom/server; no
// browser needed. The guide names buttons by their on-screen labels, so the
// last test fails if one of those labels is renamed without the guide.
const built = await build({
  stdin: {
    contents: `
      import React from 'react';
      import { renderToStaticMarkup } from 'react-dom/server';
      import { ALPHA_STEPS, InstructionsButton, SHOW_ALPHA_GUIDE, STUDENT_STEPS, TEACHER_ORIGINAL_NOTE, TEACHER_STEPS, instructionsFor } from './instructions.jsx';
      import { REFERENCE_WRITING_LINE } from './Exam.jsx';
      export { ALPHA_STEPS, SHOW_ALPHA_GUIDE, STUDENT_STEPS, TEACHER_ORIGINAL_NOTE, TEACHER_STEPS, REFERENCE_WRITING_LINE, instructionsFor };
      export const guide = who => renderToStaticMarkup(React.createElement(InstructionsButton, { who }));
    `,
    resolveDir: new URL('..', import.meta.url).pathname,
    loader: 'jsx',
  },
  bundle: true, platform: 'node', format: 'esm', write: false, jsx: 'automatic', logLevel: 'silent',
  loader: { '.css': 'empty' },
  // react-dom/server is CommonJS and reads node's own modules; a data: URL has no file to resolve them from.
  banner: { js: "import { createRequire as __createRequire } from 'node:module'; const require = __createRequire(process.cwd() + '/');" },
});
const store = new Map();
globalThis.window = { BB_API_BASE: '' };
globalThis.localStorage = {
  getItem: k => (store.has(k) ? store.get(k) : null),
  setItem: (k, v) => { store.set(k, String(v)); },
  removeItem: k => { store.delete(k); },
};
const { guide, ALPHA_STEPS, SHOW_ALPHA_GUIDE, STUDENT_STEPS, TEACHER_ORIGINAL_NOTE, TEACHER_STEPS, REFERENCE_WRITING_LINE, instructionsFor } = await import('data:text/javascript;base64,' + Buffer.from(built.outputFiles[0].text).toString('base64'));

const products = list => store.set('original_products', JSON.stringify(list));
const decode = html => html.replace(/&#x27;/g, "'").replace(/&amp;/g, '&').replace(/&quot;/g, '"');

test('the button opens a closed, labelled dialog that holds the whole guide', () => {
  products(['bluebook']);
  const html = guide('teacher');
  assert.match(html, /<button type="button" aria-haspopup="dialog">Instructions<\/button>/);
  assert.match(html, /<dialog class="bb-howto" aria-labelledby="([^"]+)"><div class="bb-howto-card"><div class="bb-howto-head"><h2 id="\1">Using Collections<\/h2>/);
  assert.doesNotMatch(html, /<dialog[^>]* open/);
  assert.equal((html.match(/<li>/g) || []).length, TEACHER_STEPS.length + 2);
});

test('during the alpha, students in a workspace that holds Original get the alpha test steps', () => {
  assert.equal(SHOW_ALPHA_GUIDE, true);
  products(['bluebook', 'original']);
  const html = decode(guide('student'));
  assert.match(html, />Alpha test: what to do</);
  for (const [step] of ALPHA_STEPS) assert.ok(html.includes(`<strong>${step}.</strong>`), step);
  assert.match(html, /three papers you wrote yourself/);
  assert.match(html, /question 1 \(Q1\).*question 2 \(Q2\)/);
  assert.match(html, /Give it the topic only, not your writing/);
  // The batch scorer needs the tool's name (generator_tool), and only the feedback form records it.
  assert.match(html, /Note which AI tool you used\. The feedback form asks for its name\./);
  assert.doesNotMatch(html, /Courses|Publish Collection|reference writing/);
  assert.match(guide('teacher'), />Using Collections</);
});

// Step 1 points to Share a past paper, which a Bluebook-only workspace does not show.
test('a Bluebook-only workspace keeps the general student guide', () => {
  products(['bluebook']);
  const html = decode(guide('student'));
  assert.match(html, />Taking an exam</);
  assert.doesNotMatch(html, /Alpha test|past paper|AI tool/);
});

test('after the alpha, students get the general guide back', () => {
  const plain = instructionsFor('student', false, false);
  assert.equal(plain.title, 'Taking an exam');
  assert.deepEqual(plain.steps, STUDENT_STEPS);
  assert.ok(!plain.notes.includes(REFERENCE_WRITING_LINE));
  // NORTH_STAR rule 10: with Original on, students are told their booklet may become reference writing.
  assert.ok(instructionsFor('student', true, false).notes.includes(REFERENCE_WRITING_LINE));
});

test('Original is mentioned to teachers only where the workspace holds it, and labelled as in testing', () => {
  products(['bluebook']);
  assert.doesNotMatch(guide('teacher'), /Original|reference writing/);
  products(['bluebook', 'original']);
  assert.ok(decode(guide('teacher')).includes(TEACHER_ORIGINAL_NOTE));
  assert.match(TEACHER_ORIGINAL_NOTE, /testing phase/);
});

test('every button the guide names is labelled that way in the app', () => {
  const src = f => readFileSync(new URL(`../${f}`, import.meta.url), 'utf8');
  const labels = {
    'Teacher.jsx': ['+ New collection', 'Release results', 'Export CSV', 'Turn on sign-up link'],
    'NewExam.jsx': ['Publish Collection'],
    'Exam.jsx': ['Begin Examination', 'Resume Examination', 'Seal & Submit', '`Q${i + 1}`'],
    'Account.jsx': ['My exams', 'Share a past paper', 'title="Examinations"', "'Open'"],
  };
  for (const [file, names] of Object.entries(labels)) {
    for (const name of names) assert.ok(src(file).includes(name), `${name} in ${file}`);
  }
});
