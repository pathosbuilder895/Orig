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
import { mkdir, readFile, writeFile, copyFile } from 'node:fs/promises';

const here = (f) => fileURLToPath(new URL(f, import.meta.url));

await build({
  entryPoints: [here('app.jsx')],
  bundle: true,
  external: ['../assets/*'],
  jsx: 'automatic',
  format: 'iife',
  target: ['es2019'],
  minify: true,
  legalComments: 'none',
  sourcemap: 'linked',
  outfile: here('bluebook.bundle.js'),
});

console.log('✓ Built bluebook.bundle.js');

await build({ entryPoints: [here('teacher-demo.jsx')], bundle: true, jsx: 'automatic', format: 'iife', target: ['es2019'], minify: true, legalComments: 'none', external: ['../assets/*'], outfile: here('teacher-demo.bundle.js') });
console.log('✓ Built isolated teacher demo');

// Serve the same scholarly typography without contacting Google from class.
const fontDir = here('../assets/fonts/');
await mkdir(fontDir, { recursive: true });
let fontCss = '';
for (const [family, weights, styles] of [
  ['eb-garamond', [400, 500, 600], ['normal', 'italic']],
  ['cormorant-garamond', [300, 400, 500, 600], ['normal', 'italic']],
  ['playfair-display', [400, 500, 600], ['normal']],
  ['ibm-plex-mono', [300, 400, 500], ['normal']],
]) {
  const pkg = here(`node_modules/@fontsource/${family}/`);
  await copyFile(pkg + 'LICENSE', fontDir + family + '-LICENSE.txt');
  for (const weight of weights) for (const style of styles) {
    let css = await readFile(pkg + `${weight}${style === 'italic' ? '-italic' : ''}.css`, 'utf8');
    css = css.replace(/,\s*url\([^)]*\.woff\) format\('woff'\)/g, '');
    for (const match of css.matchAll(/url\(\.\/files\/([^)]*\.woff2)\)/g)) {
      await copyFile(pkg + 'files/' + match[1], fontDir + match[1]);
    }
    fontCss += css.replaceAll('./files/', '../assets/fonts/') + '\n';
  }
}
await writeFile(here('fonts.css'), fontCss);
console.log('✓ Copied licensed local fonts');
