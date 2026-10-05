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
  await assert.rejects(BB_API.listSubmissions(), /sign out and sign in again/);
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
