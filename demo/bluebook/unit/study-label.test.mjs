import { test } from 'node:test';
import assert from 'node:assert/strict';
import { build } from 'esbuild';

// The staff-only study label panel (StudyLabelPanel.jsx): who sees it, what it
// sends to POST /bluebook/submissions/{id}/study-label, and what it says when
// the server refuses or lacks that route. The panel itself is rendered for
// real with react-dom/server, to check it is absent (not merely disabled)
// wherever it must not show.
const built = await build({
  stdin: {
    contents: `
      import React from 'react';
      import { renderToStaticMarkup } from 'react-dom/server';
      import { StudyLabelPanel } from './StudyLabelPanel.jsx';
      export * from './StudyLabelPanel.jsx';
      export const renderPanel = props => renderToStaticMarkup(React.createElement(StudyLabelPanel, props));
    `,
    resolveDir: new URL('..', import.meta.url).pathname,
    loader: 'jsx',
  },
  bundle: true, platform: 'node', format: 'esm', write: false, jsx: 'automatic', logLevel: 'silent',
  loader: { '.css': 'empty' },  // forms.jsx imports its stylesheet; node has no use for it
  // react-dom/server is CommonJS and reads node's own modules; a data: URL has no file to resolve them from.
  banner: { js: "import { createRequire as __createRequire } from 'node:module'; const require = __createRequire(process.cwd() + '/');" },
});
globalThis.window = { BB_API_BASE: '' };
globalThis.localStorage = { getItem: () => null, setItem: () => {}, removeItem: () => {}, key: () => null, length: 0 };
const {
  STUDY_PANEL_TITLE, STUDY_ROUTE_MISSING, detailText, examHasOriginal, imitationChoices, initialStudyLabel,
  isRouteMissing, renderPanel, saveStudyLabel, studyLabelBody, studyLabelProblem, studyPanelVisible,
} = await import('data:text/javascript;base64,' + Buffer.from(built.outputFiles[0].text).toString('base64'));

const ORIGINAL_EXAM = { id: 'e1', conditions: { aiDetect: true } };
const api = (over = {}) => ({
  base: '', _headers: () => ({ 'Content-Type': 'application/json', Authorization: 'Bearer t' }),
  isAuthed: () => true, isStudentAccount: () => false, isStudentLaunch: () => false, hasOriginal: () => true,
  ...over,
});
let sent;
const respond = (body, status = 200) => {
  globalThis.fetch = async (url, init) => {
    sent = { url, init };
    return new Response(JSON.stringify(body), { status });
  };
};

test('the panel is labelled as research and staff only', () => {
  assert.equal(STUDY_PANEL_TITLE, 'Study label (research, staff only)');
});

test('only signed-in staff in a workspace with Original see it', () => {
  assert.equal(studyPanelVisible(ORIGINAL_EXAM, api()), true);
  assert.equal(studyPanelVisible(ORIGINAL_EXAM, api({ isAuthed: () => false })), false);
  assert.equal(studyPanelVisible(ORIGINAL_EXAM, api({ isStudentAccount: () => true })), false);
  assert.equal(studyPanelVisible(ORIGINAL_EXAM, api({ isStudentLaunch: () => true })), false);
  assert.equal(studyPanelVisible(ORIGINAL_EXAM, api({ hasOriginal: () => false })), false);
});

test('only on an exam that runs Original: aiDetect strictly true, as the server checks it', () => {
  assert.equal(examHasOriginal(ORIGINAL_EXAM), true);
  for (const exam of [
    null, undefined, {}, { conditions: null }, { conditions: {} }, { conditions: { aiDetect: false } },
    { conditions: { aiDetect: 'true' } }, { conditions: { aiDetect: 1 } },
  ]) {
    assert.equal(examHasOriginal(exam), false, JSON.stringify(exam));
    assert.equal(studyPanelVisible(exam, api()), false, JSON.stringify(exam));
  }
});

test('where it may not show, the panel is not rendered at all', () => {
  const subs = [{ id: 'a', student_id: 's1', student: 'Ann', words: 300 }];
  assert.match(renderPanel({ exam: ORIGINAL_EXAM, subs, api: api() }), /Study label \(research, staff only\)/);
  for (const [exam, who] of [
    [{ conditions: { aiDetect: false } }, api()],  // the exam does not run Original
    [null, api()],  // the exam has not loaded yet
    [ORIGINAL_EXAM, api({ isStudentAccount: () => true })],
    [ORIGINAL_EXAM, api({ isStudentLaunch: () => true })],
    [ORIGINAL_EXAM, api({ isAuthed: () => false })],
    [ORIGINAL_EXAM, api({ hasOriginal: () => false })],
  ]) {
    assert.equal(renderPanel({ exam, subs, api: who }), '');
  }
});

test('the imitated-student picker offers each other student once, by name', () => {
  const subs = [
    { student_id: 's2', student: 'Zoe' }, { student_id: 's1', student: 'Ann' },
    { student_id: 's3', student: 'Ben' }, { student_id: 's3', student: 'Ben' }, { student: 'no id' },
  ];
  assert.deepEqual(imitationChoices(subs, 's1'), [{ id: 's3', name: 'Ben' }, { id: 's2', name: 'Zoe' }]);
});

test('a label must be natural, or shadow with someone else named', () => {
  const sub = { student_id: 's1' };
  assert.equal(studyLabelProblem(sub, 'natural', ''), '');
  assert.equal(studyLabelProblem(sub, 'shadow', 's2'), '');
  assert.match(studyLabelProblem(sub, '', ''), /natural or shadow/);
  assert.match(studyLabelProblem(sub, 'shadow', ''), /Choose the classmate/);
  assert.match(studyLabelProblem(sub, 'shadow', 's1'), /someone else/);
});

test('the body is the contract: study_label and imitated_student_id', () => {
  assert.deepEqual(studyLabelBody('shadow', 's2'), { study_label: 'shadow', imitated_student_id: 's2' });
  // A natural label never carries a stale imitated student.
  assert.deepEqual(studyLabelBody('natural', 's2'), { study_label: 'natural', imitated_student_id: null });
});

test('saving posts to the study-label route', async () => {
  respond({ ok: true });
  assert.deepEqual(await saveStudyLabel('sub 1', 'shadow', 's2', api()), { ok: true });
  assert.equal(sent.url, '/bluebook/submissions/sub%201/study-label');
  assert.equal(sent.init.method, 'POST');
  assert.deepEqual(JSON.parse(sent.init.body), { study_label: 'shadow', imitated_student_id: 's2' });
  assert.equal(sent.init.headers.Authorization, 'Bearer t');
});

test('a natural label is posted with imitated_student_id null, even after a shadow choice', async () => {
  respond({ ok: true });
  await saveStudyLabel('sub1', 'natural', 's2', api());
  const body = JSON.parse(sent.init.body);
  assert.deepEqual(body, { study_label: 'natural', imitated_student_id: null });
  assert.ok('imitated_student_id' in body);  // sent as null, not left out
});

test("a 422 shows the server's reason", async () => {
  respond({ detail: 'imitated_student_id must belong to this workspace' }, 422);
  assert.equal((await saveStudyLabel('sub1', 'shadow', 'x', api())).message,
    'Not saved: imitated_student_id must belong to this workspace');
  // FastAPI's own request validation: a list of {loc, msg}.
  respond({ detail: [
    { loc: ['body', 'study_label'], msg: "Input should be 'natural' or 'shadow'", type: 'literal_error' },
    { loc: ['body', 'imitated_student_id'], msg: 'Field required', type: 'missing' },
  ] }, 422);
  assert.equal((await saveStudyLabel('sub1', 'shadow', 'x', api())).message,
    "Not saved: study_label: Input should be 'natural' or 'shadow'; imitated_student_id: Field required");
  respond({}, 422);
  assert.match((await saveStudyLabel('sub1', 'shadow', 'x', api())).message, /Not saved: .*HTTP 422/);
});

test('detail text reads strings, validation lists and single objects', () => {
  assert.equal(detailText('nope'), 'nope');
  assert.equal(detailText([{ loc: ['body'], msg: 'bad body' }, 'plain', null, {}]), 'bad body; plain');
  assert.equal(detailText({ msg: 'one' }), 'one');
  assert.equal(detailText(undefined), '');
  assert.equal(detailText(42), '');
});

test('a server without the route says so, and nothing reads as saved', async () => {
  respond({ detail: 'Not Found' }, 404);
  const r = await saveStudyLabel('sub1', 'natural', '', api());
  assert.equal(r.ok, false);
  assert.equal(r.missing, true);
  assert.equal(r.message, STUDY_ROUTE_MISSING);
  respond({ detail: 'Method Not Allowed' }, 405);
  assert.equal((await saveStudyLabel('sub1', 'natural', '', api())).missing, true);
});

test('a missing submission is not mistaken for a missing route', async () => {
  respond({ detail: 'submission not found' }, 404);
  const r = await saveStudyLabel('sub1', 'natural', '', api());
  assert.equal(r.missing, undefined);
  assert.equal(r.message, 'submission not found');
  assert.equal(isRouteMissing(404, 'submission not found'), false);
  assert.equal(isRouteMissing(404, ''), true);
});

test('refusals and network failures are reported, not swallowed', async () => {
  respond({ detail: 'Staff only' }, 403);
  assert.match((await saveStudyLabel('sub1', 'natural', '', api())).message, /Only staff/);
  globalThis.fetch = async () => { throw new TypeError('offline'); };
  assert.match((await saveStudyLabel('sub1', 'natural', '', api())).message, /Could not reach the server/);
});

test('a label saved this visit wins over the stale list, so it survives Hide and Show', () => {
  const sub = { id: 'a', study_label: null, imitated_student_id: null };
  assert.deepEqual(initialStudyLabel(sub, undefined), { label: '', imitated: '' });
  assert.deepEqual(initialStudyLabel(sub, { label: 'shadow', imitated: 's2' }), { label: 'shadow', imitated: 's2' });
  // A server that already returns labels prefills them.
  assert.deepEqual(initialStudyLabel({ study_label: 'natural', imitated_student_id: null }, undefined),
    { label: 'natural', imitated: '' });
});
