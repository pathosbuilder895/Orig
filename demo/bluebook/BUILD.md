# Bluebook — build & deploy

Bluebook is a React app written as classic global-scope `.jsx` scripts (no
module system) that share one scope in a fixed load order.

## Two ways to run it

### Dev (`index.html`) — zero build
Loads React + **Babel-standalone** from a CDN and compiles the `.jsx` in the
browser. Convenient for iterating, but Babel-in-browser adds ~1–2s to first
paint and the `?v=N` query on each `<script src>` is a manual cache-buster.
This is what the demo server serves at `/bluebook/`.

### Production (`index.prod.html`) — precompiled bundle
Loads **minified production React** + a single precompiled `bluebook.bundle.js`.
No in-browser Babel, no per-file cache-buster. This is what you deploy.

## Build the bundle

```bash
cd demo/bluebook
npm install        # installs esbuild (devDependency)
npm run build      # → bluebook.bundle.js
```

`build.mjs` concatenates the files in load order (`components → Landing →
Dashboard → Exam → Courses → Students → Results → NewExam → tweaks-panel →
app`), transforms the JSX with esbuild, and emits one minified IIFE. React /
ReactDOM stay external (loaded by `index.prod.html` from the CDN).

Then serve `index.prod.html` (rename to `index.html` on the deploy target, or
point the route at it). Re-run `npm run build` after editing any `.jsx`.

## Notes
- `app.jsx` holds the router/root (previously inline in `index.html`).
- Keep `build.mjs`'s `ORDER` in sync with the `<script>` order in `index.html`.
- For cache-busting in production, serve the bundle with a content hash in the
  filename (or an immutable `Cache-Control` + a query the deploy step rotates).
