import { test } from 'node:test';
import assert from 'node:assert/strict';
import { build } from 'esbuild';

// The student screens' navigation (Account.jsx StudentShell): "My voice" and
// "My work" open the Original student pages, and only when the student's
// workspace holds Original (the products sign-in stored, BB_API.hasOriginal).
// Rendered for real with react-dom/server; no browser needed.
const built = await build({
  stdin: {
    contents: `
      import React from 'react';
      import { renderToStaticMarkup } from 'react-dom/server';
      import { StudentShell } from './Account.jsx';
      export const nav = () => renderToStaticMarkup(React.createElement(StudentShell, { onNavigate() {}, active: 'student-home' }, null));
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
const { nav } = await import('data:text/javascript;base64,' + Buffer.from(built.outputFiles[0].text).toString('base64'));

const labels = html => [...html.matchAll(/<(?:button|a)[^>]*>([^<]*)<\/(?:button|a)>/g)].map(m => m[1]);
const links = html => [...html.matchAll(/<a href="([^"]*)"[^>]*>([^<]*)<\/a>/g)].map(m => [m[1], m[2]]);
const products = list => store.set('original_products', JSON.stringify(list));

test('a student whose workspace holds Original can reach My voice and My work', () => {
  products(['bluebook', 'original']);
  const html = nav();
  assert.deepEqual(labels(html), ['Bluebook', 'My exams', 'My voice', 'My work', 'Account', 'Sign out']);
  assert.deepEqual(links(html), [['../original/voice.html', 'My voice'], ['../original/my-work.html', 'My work']]);
});

test('a Bluebook-only workspace keeps the shell it always had', () => {
  products(['bluebook']);
  const html = nav();
  assert.deepEqual(labels(html), ['Bluebook', 'My exams', 'Account', 'Sign out']);
  assert.deepEqual(links(html), []);
});

test('the links are real links, so they can be opened in a new tab', () => {
  products(['original', 'bluebook']);
  assert.match(nav(), /<a href="\.\.\/original\/voice\.html">My voice<\/a>/);
});
