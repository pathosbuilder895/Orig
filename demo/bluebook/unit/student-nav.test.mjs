import { test } from 'node:test';
import assert from 'node:assert/strict';
import { build } from 'esbuild';

// The student screens' navigation (Account.jsx StudentShell). "My voice" and
// "My work" (the Original student pages) are not offered during the pilot,
// even where the workspace holds Original: a student never sees a comparison
// of their writing (SHOW_STUDENT_ORIGINAL_PAGES). Rendered for real with
// react-dom/server; no browser needed.
const built = await build({
  stdin: {
    contents: `
      import React from 'react';
      import { renderToStaticMarkup } from 'react-dom/server';
      import { StudentShell, SHOW_STUDENT_ORIGINAL_PAGES, STUDENT_ORIGINAL_LINKS } from './Account.jsx';
      export { SHOW_STUDENT_ORIGINAL_PAGES, STUDENT_ORIGINAL_LINKS };
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
const { nav, SHOW_STUDENT_ORIGINAL_PAGES, STUDENT_ORIGINAL_LINKS } = await import('data:text/javascript;base64,' + Buffer.from(built.outputFiles[0].text).toString('base64'));

const labels = html => [...html.matchAll(/<(?:button|a)[^>]*>([^<]*)<\/(?:button|a)>/g)].map(m => m[1]);
const links = html => [...html.matchAll(/<a href="([^"]*)"[^>]*>([^<]*)<\/a>/g)].map(m => [m[1], m[2]]);
const products = list => store.set('original_products', JSON.stringify(list));

test('a student whose workspace holds Original is not offered My voice or My work in the pilot', () => {
  assert.equal(SHOW_STUDENT_ORIGINAL_PAGES, false);
  products(['bluebook', 'original']);
  const html = nav();
  assert.deepEqual(labels(html), ['Collections', 'My exams', 'Instructions', 'Close', 'Account', 'Sign out']);
  assert.deepEqual(links(html), []);
  assert.doesNotMatch(html, /My voice|My work|original\//);
});

test('a Bluebook-only workspace keeps the shell it always had', () => {
  products(['bluebook']);
  const html = nav();
  assert.deepEqual(labels(html), ['Collections', 'My exams', 'Instructions', 'Close', 'Account', 'Sign out']);
  assert.deepEqual(links(html), []);
});

test('the pages stay named, so offering them again is the one switch', () => {
  assert.deepEqual(STUDENT_ORIGINAL_LINKS, [['../original/voice.html', 'My voice'], ['../original/my-work.html', 'My work']]);
});
