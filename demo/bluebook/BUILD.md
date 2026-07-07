# Bluebook — build & deploy

Bluebook is a React app written as real ES modules (`import`/`export`),
rooted at `app.jsx`. esbuild resolves the module graph itself — there's no
fixed load order to keep in sync with `index.html`.

## One index.html, dev and prod

`index.html` just loads the precompiled `bluebook.bundle.js`. React and
ReactDOM are bundled into it as real dependencies (not left external), so
there's no CDN script tag and no vendored global `<script>` — the same
bundle runs in dev and production. This is what the demo server serves at
`/bluebook/` in every `ORIGINAL_ENV`.

## Build the bundle

```bash
cd demo/bluebook
npm install        # installs esbuild + react/react-dom
npm run build      # → bluebook.bundle.js
```

`build.mjs` bundles from `app.jsx` as the esbuild entry point, transforms
JSX with the automatic runtime, and emits one minified IIFE with React
bundled in. Re-run `npm run build` after editing any `.jsx` and commit the
regenerated `bluebook.bundle.js` (Render has no Node — the committed
artifact is what production serves).

## Notes
- `app.jsx` holds the router/root and the `ReactDOM.createRoot` call.
- Cross-file references go through `import`/`export`, not `window` globals.
- For cache-busting in production, serve the bundle with a content hash in the
  filename (or an immutable `Cache-Control` + a query the deploy step rotates).
