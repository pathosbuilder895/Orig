// build.mjs — bundle the Original React app into static browser IIFEs.
//
//   npm install && npm run build   →   one <name>.bundle.js per ENTRIES item
//
// One entry point per page (mirrors demo/'s existing multi-page structure —
// professor.html, student.html, admin.html are separate files, not a single
// SPA — so each React page gets its own small, independently-cacheable
// bundle rather than one router bundle). Each .jsx file is a real ES module;
// esbuild resolves the graph itself. React/ReactDOM are bundled in (not left
// external), so every emitted IIFE is fully self-contained — no CDN, same
// bundle in dev and prod (Render has no Node), matching demo/bluebook/build.mjs.
import { build } from 'esbuild';
import { fileURLToPath } from 'node:url';

const here = (f) => fileURLToPath(new URL(f, import.meta.url));

const ENTRIES = [
  'app.jsx',
  'students-entry.jsx',
  'flagged-entry.jsx',
  'submissions-entry.jsx',
  'student-entry.jsx',
  'reports-entry.jsx',
  'settings-entry.jsx',
  'courses-entry.jsx',
  'fingerprint-entry.jsx',
  'quantum-entry.jsx',
  'interference-entry.jsx',
  'portal-entry.jsx',
  'admin-entry.jsx',
  'operator-entry.jsx',
];

await build({
  entryPoints: ENTRIES.map(here),
  bundle: true,
  jsx: 'automatic',
  format: 'iife',
  target: ['es2019'],
  minify: true,
  legalComments: 'none',
  sourcemap: 'linked',
  outdir: here('.'),
  entryNames: '[name].bundle',
});

console.log('✓ Built ' + ENTRIES.map((e) => e.replace(/\.jsx$/, '.bundle.js')).join(', '));
