import { test } from 'node:test';
import assert from 'node:assert/strict';
import { build } from 'esbuild';

// Signing out must also forget the papers the Original pages keep on this computer
// (original_portfolio_<student id> in localStorage, original_last_result in
// sessionStorage), the same keys demo/original/live.js and demo/professor.html clear.
const built = await build({ entryPoints: [new URL('../components.jsx', import.meta.url).pathname], bundle: true, platform: 'node', format: 'esm', write: false });

function store(initial = {}) {
  const m = new Map(Object.entries(initial));
  return {
    getItem: k => (m.has(k) ? m.get(k) : null),
    setItem: (k, v) => { m.set(k, String(v)); },
    removeItem: k => { m.delete(k); },
    key: i => Array.from(m.keys())[i] ?? null,
    get length() { return m.size; },
    keys: () => Array.from(m.keys()).sort(),
  };
}
const blocked = new Proxy({}, { get() { throw new Error('storage is blocked'); } });

globalThis.window = { BB_API_BASE: '' };
globalThis.localStorage = store();
globalThis.sessionStorage = store();
const { BB_API } = await import('data:text/javascript;base64,' + Buffer.from(built.outputFiles[0].text).toString('base64'));

function signedIn() {
  const papers = {};
  for (let i = 0; i < 9; i++) papers[`original_portfolio_tenant:s${i}`] = '[{"text":"a whole paper"}]';
  globalThis.localStorage = store({
    original_principal_token: 'tok', original_role: 'professor', original_name: 'Pat', original_email: 'pat@example.org',
    original_portfolio_: 'a prefix with no student id still goes',
    ...papers,
    original_portfolio: 'not a kept paper: no trailing underscore',
    another_site_key: 'left alone',
  });
  globalThis.sessionStorage = store({ original_last_result: '{"result":{}}', unrelated: 'left alone' });
}

test('logout removes the session keys, every kept paper and the last result, and nothing else', () => {
  signedIn();
  BB_API.logout();
  assert.deepEqual(localStorage.keys(), ['another_site_key', 'original_portfolio']);
  assert.deepEqual(sessionStorage.keys(), ['unrelated']);
});

test('signing in again keeps the papers (only signing out forgets them)', () => {
  signedIn();
  BB_API._storeSession({ token: 'new', role: 'professor', tenant_id: 't', name: 'Pat', email: 'pat@example.org' });
  assert.equal(localStorage.getItem('original_principal_token'), 'new');
  assert.equal(localStorage.keys().filter(k => k.startsWith('original_portfolio_')).length, 10);
  assert.equal(sessionStorage.getItem('original_last_result'), '{"result":{}}');
});

test('logout still signs out when the browser blocks storage', () => {
  globalThis.localStorage = blocked;
  globalThis.sessionStorage = blocked;
  assert.doesNotThrow(() => BB_API.logout());
});
