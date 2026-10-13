import { test } from 'node:test';
import assert from 'node:assert/strict';
import { build } from 'esbuild';

// Exercise the shipped API adapter without a browser or a live server.
const built = await build({ entryPoints: [new URL('../components.jsx', import.meta.url).pathname], bundle: true, platform: 'node', format: 'esm', write: false });
globalThis.window = { BB_API_BASE: '' };
globalThis.localStorage = { getItem: () => 'test-session' };
const { BB_API } = await import('data:text/javascript;base64,' + Buffer.from(built.outputFiles[0].text).toString('base64'));

test('an expired sign-in is not reported as an empty submission list', async () => {
  globalThis.fetch = async () => new Response('{"detail":"Expired"}', { status: 401 });
  await assert.rejects(BB_API.listSubmissions(), /Your sign-in has expired\. Please sign in again\./);
});
test('a 401 that says something specific is passed on, not replaced', async () => {
  globalThis.fetch = async () => new Response('{"detail":"Current password is incorrect."}', { status: 401 });
  await assert.rejects(BB_API.changePassword('old-password', 'new-password-1'), /^Error: Current password is incorrect\.$/);
});
test('a failure the server did not explain is said in plain words, not as a status line', async () => {
  globalThis.fetch = async () => new Response('Internal Server Error', { status: 500, statusText: 'Internal Server Error' });
  await assert.rejects(BB_API.listSubmissions(), /Something went wrong on our side/);
  globalThis.fetch = async () => new Response('{"detail":[{"msg":"Field required"}]}', { status: 422, statusText: 'Unprocessable Entity' });
  await assert.rejects(BB_API.listSubmissions(), /That did not go through/);
});
test('a failed request carries its HTTP status', async () => {
  globalThis.fetch = async () => new Response('{"detail":"Not accepted."}', { status: 422 });
  await assert.rejects(BB_API.recordSubmission({}), err => err.status === 422 && err.message === 'Not accepted.');
});
test('a server failure is not reported as an empty submission list', async () => {
  globalThis.fetch = async () => new Response('{"detail":"Temporarily unavailable"}', { status: 503 });
  await assert.rejects(BB_API.listSubmissions(), /Temporarily unavailable/);
});
test('network failures propagate and successful empty lists remain empty', async () => {
  globalThis.fetch = async () => { throw new TypeError('Network unavailable'); };
  await assert.rejects(BB_API.listSubmissions(), /Network unavailable/);
  globalThis.fetch = async () => new Response('{"submissions":[]}');
  assert.deepEqual(await BB_API.listSubmissions(), []);
});
test('signupOpen follows /health and fails closed', async () => {
  const health = (body, status = 200) => async () => new Response(JSON.stringify(body), { status });
  delete BB_API._healthP;
  globalThis.fetch = health({ environment: 'pilot', signup_open: false });
  assert.equal(await BB_API.signupOpen(), false);
  assert.equal(await BB_API.environment(), 'pilot');

  delete BB_API._healthP;
  globalThis.fetch = health({ environment: 'pilot' });
  assert.equal(await BB_API.signupOpen(), true);

  delete BB_API._healthP;
  globalThis.fetch = async () => { throw new TypeError('offline'); };
  assert.equal(await BB_API.signupOpen(), false);
  assert.equal(await BB_API.environment(), null);
});
test('redeemInvite sends accept_terms and surfaces the terms refusal', async () => {
  const bodies = [];
  globalThis.fetch = async (url, init) => {
    bodies.push(JSON.parse(init.body));
    return new Response('{"detail":"Please accept the terms of service and privacy policy."}', { status: 422 });
  };
  await assert.rejects(BB_API.redeemInvite('tok', 'pw-123456'), /^Error: Please accept the terms of service and privacy policy\.$/);
  await assert.rejects(BB_API.redeemInvite('tok', 'pw-123456', true), /accept the terms/);
  assert.deepEqual(bodies, [
    { token: 'tok', password: 'pw-123456', accept_terms: false },
    { token: 'tok', password: 'pw-123456', accept_terms: true },
  ]);
});
test('the home-page calls keep the stored products in step with the server', async () => {
  // Original can be switched on or off for a workspace while a page is open;
  // /bluebook/me (student home) and /auth/me (teacher workspace) carry the
  // current products and must replace what sign-in stored.
  const store = new Map([['original_products', '["bluebook","original"]'], ['original_session_token', 't']]);
  const saved = globalThis.localStorage;
  globalThis.localStorage = {
    getItem: k => (store.has(k) ? store.get(k) : null),
    setItem: (k, v) => { store.set(k, String(v)); },
    removeItem: k => { store.delete(k); },
  };
  try {
    globalThis.fetch = async () => new Response(JSON.stringify({ student_id: 't:s', products: ['bluebook'], courses: [] }));
    assert.deepEqual((await BB_API.me()).products, ['bluebook']);
    assert.equal(store.get('original_products'), '["bluebook"]');
    assert.equal(BB_API.hasOriginal(), false);

    globalThis.fetch = async () => new Response(JSON.stringify({ role: 'professor', products: ['bluebook', 'original'], mail: false }));
    await BB_API.authMe();
    assert.equal(store.get('original_products'), '["bluebook","original"]');
    assert.equal(BB_API.hasOriginal(), true);

    // A failed call leaves the stored products alone.
    globalThis.fetch = async () => new Response('{"detail":"Temporarily unavailable"}', { status: 503 });
    await assert.rejects(BB_API.me(), /Temporarily unavailable/);
    assert.equal(store.get('original_products'), '["bluebook","original"]');

    // A seal that finds Original switched off drops it from this page.
    BB_API.dropOriginal();
    assert.equal(store.get('original_products'), '["bluebook"]');
    assert.equal(BB_API.hasOriginal(), false);
  } finally {
    globalThis.localStorage = saved;
  }
});
