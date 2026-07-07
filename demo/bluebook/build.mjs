// build.mjs — bundle Bluebook's ESM React app into a single browser bundle.
//
//   npm install && npm run build   →   bluebook.bundle.js
//
// The .jsx files are real ES modules (import/export) rooted at app.jsx.
// esbuild resolves the module graph itself — no manual concatenation, no
// fixed load-order array to keep in sync. React/ReactDOM are bundled in as
// real dependencies (not left external), so the emitted IIFE is fully
// self-contained: no CDN, no vendored global <script> tags, same bundle in
// dev and prod.

import { build } from 'esbuild';
import { fileURLToPath } from 'node:url';

const here = (f) => fileURLToPath(new URL(f, import.meta.url));

await build({
  entryPoints: [here('app.jsx')],
  bundle: true,
  jsx: 'automatic',
  format: 'iife',
  target: ['es2019'],
  minify: true,
  legalComments: 'none',
  sourcemap: 'linked',
  outfile: here('bluebook.bundle.js'),
});

console.log('✓ Built bluebook.bundle.js');
