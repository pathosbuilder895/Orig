import { test } from 'node:test';
import assert from 'node:assert/strict';
import { build } from 'esbuild';

const built = await build({
  entryPoints: [new URL('../form-drafts.jsx', import.meta.url).pathname],
  bundle: true, platform: 'node', format: 'esm', write: false, jsx: 'automatic', logLevel: 'silent',
});
const m = await import('data:text/javascript;base64,' + Buffer.from(built.outputFiles[0].text).toString('base64'));

function mem(init = {}) {
  const d = { ...init };
  return { getItem: k => (k in d ? d[k] : null), setItem: (k, v) => { d[k] = String(v); }, removeItem: k => { delete d[k]; }, d };
}

test('a teacher draft round-trips and belongs to that teacher only', () => {
  const ls = mem({ original_role: 'professor', original_email: 'A@x.edu', original_tenant: 't1' });
  assert.equal(m.saveFormDraft('new-collection', { title: 'Essay' }, false, ls), true);
  assert.deepEqual(m.loadFormDraft('new-collection', ls), { title: 'Essay' });
  ls.setItem('original_email', 'b@x.edu');
  assert.equal(m.loadFormDraft('new-collection', ls), null);
});

test('a student draft is keyed by student id', () => {
  const ls = mem({ original_role: 'student', original_student_id: 's1' });
  m.saveFormDraft('past-paper', { text: 'hello' }, false, ls);
  ls.setItem('original_student_id', 's2');
  assert.equal(m.loadFormDraft('past-paper', ls), null);
  ls.setItem('original_student_id', 's1');
  assert.deepEqual(m.loadFormDraft('past-paper', ls), { text: 'hello' });
});

test('an empty form or clear removes the draft', () => {
  const ls = mem({ original_role: 'student', original_student_id: 's1' });
  m.saveFormDraft('past-paper', { text: 'x' }, false, ls);
  m.saveFormDraft('past-paper', { text: '' }, true, ls);
  assert.equal(m.loadFormDraft('past-paper', ls), null);
  m.saveFormDraft('past-paper', { text: 'x' }, false, ls);
  m.clearFormDraft('past-paper', ls);
  assert.equal(m.loadFormDraft('past-paper', ls), null);
});

test('a draft survives sign-out: session keys are separate', () => {
  const ls = mem({ original_role: 'professor', original_email: 'a@x.edu', original_tenant: 't' });
  m.saveFormDraft('new-collection', { title: 'T' }, false, ls);
  for (const k of ['original_role', 'original_email', 'original_tenant']) ls.removeItem(k);
  Object.assign(ls.d, { original_role: 'professor', original_email: 'a@x.edu', original_tenant: 't' });
  assert.deepEqual(m.loadFormDraft('new-collection', ls), { title: 'T' });
});

test('token expiry is read and the warning lands 10 minutes before', () => {
  const exp = 2_000_000_000;
  const tok = Buffer.from(JSON.stringify({ sub: 'u', tid: 't', exp })).toString('base64url') + '.sig';
  assert.equal(m.tokenExpiryMs(tok), exp * 1000);
  assert.equal(m.expiryWarnDelay(exp * 1000, exp * 1000 - 60 * 60 * 1000), 50 * 60 * 1000);
  assert.equal(m.expiryWarnDelay(exp * 1000, exp * 1000 - 60 * 1000), 0);
  assert.equal(m.tokenExpiryMs('garbage'), null);
  assert.equal(m.expiryWarnDelay(null, 0), null);
});
