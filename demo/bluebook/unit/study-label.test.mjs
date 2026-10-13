import { test } from 'node:test';
import assert from 'node:assert/strict';
import { build } from 'esbuild';

// The staff-only study label panel (StudyLabelPanel.jsx): who sees it, what it
// sends to POST /bluebook/submissions/{id}/study-label, and what it says when
// the backend does not have that route yet.
const built = await build({
  entryPoints: [new URL('../StudyLabelPanel.jsx', import.meta.url).pathname],
  bundle: true, platform: 'node', format: 'esm', write: false, jsx: 'automatic', logLevel: 'silent',
  loader: { '.css': 'empty' },  // forms.jsx imports its stylesheet; node has no use for it
});
globalThis.window = { BB_API_BASE: '' };
globalThis.localStorage = { getItem: () => null, setItem: () => {}, removeItem: () => {}, key: () => null, length: 0 };
const {
  STUDY_PANEL_TITLE, STUDY_ROUTE_MISSING, imitationChoices, isRouteMissing, saveStudyLabel,
  studyLabelBody, studyLabelProblem, studyPanelVisible,
} = await import('data:text/javascript;base64,' + Buffer.from(built.outputFiles[0].text).toString('base64'));

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
  assert.equal(studyPanelVisible(api()), true);
  assert.equal(studyPanelVisible(api({ isAuthed: () => false })), false);
  assert.equal(studyPanelVisible(api({ isStudentAccount: () => true })), false);
  assert.equal(studyPanelVisible(api({ isStudentLaunch: () => true })), false);
  assert.equal(studyPanelVisible(api({ hasOriginal: () => false })), false);
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
  respond({ detail: 'imitated_student_id is not in this workspace' }, 422);
  assert.equal((await saveStudyLabel('sub1', 'shadow', 'x', api())).message, 'imitated_student_id is not in this workspace');
  globalThis.fetch = async () => { throw new TypeError('offline'); };
  assert.match((await saveStudyLabel('sub1', 'natural', '', api())).message, /Could not reach the server/);
});
