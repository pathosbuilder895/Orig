# Original investigation workspace prototypes

Three linked, front-end-only concepts inspired by the layered investigation
model in Fuselab's Control AI case study. They are intentionally isolated from
the live professor UI and use synthetic data.

- **Command** — portfolio-level monitoring, triage, and analyst summary.
- **Constellation** — a relationship-first view of baseline, document, and
  feature evidence.
- **Case file** — evidence review and instructor-controlled next steps.
- **Network pulse** — generative interest, sentiment, engagement, and emerging
  relationship monitoring inspired by network interactivity research tools.
- **Temporal intelligence** — dimensional stacked activity, readiness,
  workflow, and evidence views with playback, comparisons, context markers,
  and analyst interpretation.
- **Living document intelligence** — an editable paper with immediate
  feature-to-passage correlation, glass evidence overlays, baseline statistics,
  a full-size switchable baseline-paper comparison, a correlation field,
  selection tools, and five reading atmospheres.

Serve the live `demo/` directory and open `/prototypes/`. No build step or
backend is required.

## Professor demonstration

The workspace now identifies itself as an interactive concept with a fictional
student, illustrative metrics, and no saved records. The rehearsed path is:

1. Command → review the fictional Morgan Lee signal.
2. Case file → explain the deviation index and aligned counterevidence.
3. Text studio → compare exact passages with one of three viewable baseline
   examples from the twelve-paper illustrative profile.
4. Constellation → show how Surface, Discourse, and Rhetoric evidence connects.

Network Pulse and Temporal are labeled as future concepts. Start the complete
demo from the repository root with:

```bash
.venv/bin/python run.py --demo --frontend-dir demo/ --port 8001
```

Then open `http://127.0.0.1:8001/prototypes/` in a fresh browser window.

## Likely production mapping

| Prototype surface | Existing Original source |
| --- | --- |
| Headline counts | `GET /admin/health` |
| Recent signals | `GET /admin/manifests` |
| Baseline readiness | `GET /students/{id}/readiness` |
| Feature constellation | fingerprint and quantum-state responses |
| Case evidence | score output, flags, and professor explanation |
| Decision trail | admin audit endpoints |

The graph uses a custom Canvas 2D projection engine. A production version can
retain the same information architecture while moving the renderer into a
React-managed canvas component.

## Dimensional engine

`constellation-engine.js` is dependency-free and renders the investigation map
to a high-DPI canvas. Every signal has an `(x, y, z, w)` position. The engine
rotates the `x/w` plane using the time-axis value, rotates the resulting 3D
field with the orbit camera, and then applies perspective projection and depth
sorting. This makes time/evidence state a genuine fourth coordinate rather
than a decorative timeline.

Implemented interactions and effects:

- drag-to-orbit camera and wheel/buttons to zoom;
- time-state interpolation and 4D reprojection;
- depth-sorted nodes, star field, orbital guides, glow, and signal trails;
- node hit-testing with synchronized evidence detail;
- motion pause/reset controls;
- device-pixel-ratio-aware rendering and `ResizeObserver` resizing;
- a 40 fps performance cap and reduced-motion support.

`network-pulse-engine.js` adds a second generative renderer. It creates four
interest clusters, sentiment-coded signals, intra-cluster relationships, and
high-relevance emergent bridges. Interest presets, sentiment filters,
notification thresholds, engagement animation, hover inspection, and a
focused “unexpected revelation” mode all alter the live field.

`temporal-chart.js` renders an accessible SVG intelligence chart. KPI cards
change its measurement model, periods support mouse and keyboard inspection,
context markers select meaningful weeks, and comparison/playback controls
support longitudinal analysis without conflating submission outcomes with
overlapping evidence signals.

`temporal-premium.css` is a swappable art-direction layer based on the supplied
Control AI reference: deep teal glass surfaces, elevated KPI tiles, narrow
metallic gradient columns, illuminated caps, a selected-period beam, and a
persistent glass tooltip. The foreground crystal is generated in SVG with
fractal turbulence, displacement mapping, and specular lighting rather than a
static raster asset.

`temporal-cinematic.css` adapts the supplied Regulatory Intelligence motion
reference into a three-panel Original cockpit: stability/signal intelligence,
the central temporal visualization, and profile/course/evidence operations.
The optional Guided View sequences those regions with CSS perspective,
Z-depth, focus attenuation, and eased camera transitions while preserving the
underlying interactive SVG and accessible DOM.

`temporal-depth.css` adds the final spatial layer: each SVG stack is rebuilt
with independently lit top and side faces, projected floor plates, a selected
column sink response, and pointer-driven perspective/parallax. It also gives
the signal dial a layered elliptical chassis and expands authorship stability
into baseline-range, movement, and confidence diagnostics.

`document-intelligence.js` coordinates the forensic editor. Selecting any
feature updates the annotated passages, difference rail, baseline comparison,
feature position, related-feature field, and interpretive guidance as one
synchronized lens. Its comparison workspace preserves identical paper geometry,
fits a two-paper reading spread without horizontal panning, increases comparison
typography, and adds paired passage markers, persistent
comparison metrics, difference navigation, working editor commands, and cycles
among verified baseline papers without losing the active feature lens or reading
position. The document viewport owns both scroll axes so long papers remain
reachable inside the fixed investigation workspace. Hovering or selecting a
colored passage replaces the crowded history plot with a focused current-versus-
baseline excerpt, live measurements, and a plain-language explanation of the
feature behavior. Selecting a feature also moves the local constellation camera
onto that node, isolates its strongest relationships, and brings the correlation
field into view; the infinity control returns to the complete authorship field.
`document-editor.css` provides
the navy, verdant, Bodleian,
forest, and parchment environments plus refractive inline evidence treatments.
`document-liquid-glass.css` is the cleaner optical layer: translucent panels,
cursor-responsive specular light, refracted edges, optically lighter button
glass, higher-contrast typography, and calmer spacing inspired by modern system
glass without sacrificing the bookish paper surface. Each visible feature family
also has a stable semantic color that follows its library control, document
highlights, inspector lens, passage comparison, and correlation constellation.
The final legibility profile is sized for older readers: 15.5–16.5px document
text, enlarged navigation and inspector copy, taller controls, wider analysis
panels, and generous line spacing while retaining a zero-horizontal-overflow
two-paper comparison.

The supplied Long Room photograph is included locally as
`assets/long-room-library.jpg` and used as a color-graded, vignetted cinematic
backdrop. The paper remains opaque while the surrounding intelligence surfaces
reveal the architecture through controlled blur and translucency.
