// build.mjs — compile Bluebook's JSX into a single browser bundle.
//
//   npm install && npm run build   →   bluebook.bundle.js
//
// The .jsx files are classic global-scope scripts (they attach to `window` and
// reference each other as globals, in a fixed load order) — NOT ES modules.
// So we concatenate them in order into one virtual file, then let esbuild
// transform the JSX and emit a single minified IIFE. React / ReactDOM stay as
// externals (loaded from the CDN by index.prod.html before this bundle).
//
// Result: production drops in-browser Babel (~the slowest part of first paint)
// and the per-file ?v= cache-buster — one hashed bundle instead.

import { build } from 'esbuild';
import { readFileSync, writeFileSync, rmSync } from 'node:fs';
import { fileURLToPath } from 'node:url';

const here = (f) => fileURLToPath(new URL(f, import.meta.url));

// Load order MUST match index.html (components → screens → tweaks → app).
const ORDER = [
  'components.jsx', 'Landing.jsx', 'Dashboard.jsx', 'Exam.jsx', 'Courses.jsx',
  'Students.jsx', 'Results.jsx', 'NewExam.jsx', 'tweaks-panel.jsx', 'app.jsx',
];

const combined = ORDER
  .map((f) => `// ─────────── ${f} ───────────\n` + readFileSync(here(f), 'utf8'))
  .join('\n\n');

const tmp = here('._bluebook_combined.jsx');
writeFileSync(tmp, combined);

try {
  await build({
    entryPoints: [tmp],
    bundle: true,                 // single file; React/ReactDOM remain globals
    loader: { '.jsx': 'jsx' },
    jsx: 'transform',
    format: 'iife',
    target: ['es2019'],
    minify: true,
    legalComments: 'none',
    outfile: here('bluebook.bundle.js'),
  });
  console.log('✓ Built bluebook.bundle.js');
} finally {
  rmSync(tmp, { force: true });
}
