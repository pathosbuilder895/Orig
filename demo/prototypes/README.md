# Original investigation workspace prototypes

Six linked, front-end-only concepts inspired by the layered investigation
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
- **Living document intelligence** — a read-only review paper with immediate
  feature-to-passage correlation, glass evidence overlays, illustrative baseline statistics,
  a full-size switchable baseline-paper comparison, a correlation field,
  selection tools, and five reading atmospheres.

Serve the live `demo/` directory and open `/prototypes/`. No build step or
backend is required. The entire `/prototypes` subtree is intentionally returned
as `404` whenever Original detects a real deployment; it is a demonstration
surface, not a production route.

## Feature registry and evidence resolution

The prototypes carry a deploy-safe, generated copy of Original's 109-feature
contract in `feature-registry.generated.js`. It is generated directly from the
canonical code order, tier membership, and technical labels in
`original/constants.py`, plus professor-facing descriptions from
`original/explainer.py`. It does not depend on the optional `demo/app/` React
workspace, so a clean checkout can serve `/prototypes/` without missing module
imports.

After changing backend feature metadata, regenerate and verify the copy:

```bash
.venv/bin/python demo/prototypes/generate-feature-registry.py
.venv/bin/python demo/prototypes/generate-feature-registry.py --check
.venv/bin/python -m pytest tests/test_prototype_feature_registry.py -q
```

Every generated feature exposes four localization properties through
`FEATURE_BY_CODE`: `localizationKind`, `localizationLabel`,
`localizationGuidance`, and `supportsInlineHighlight`. The six allowed kinds
are `character`, `token`, `sentence`, `paragraph`, `document`, and
`behavioral`. Only the first four permit inline highlighting. Document-level
signals use summaries or distributions, and behavioral signals require a live
drafting timeline; the interface must not invent word highlights for either.

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

## Production evidence contract

The prototype deliberately does not infer evidence offsets from prose. A
production adapter should render only trusted analysis records and should keep
the backend feature code as the stable join key. Each record needs:

- document and revision identifiers, a content hash, analysis/model version,
  and generation time;
- feature code, localization kind, raw value, display unit, interpretation,
  and provenance;
- baseline cohort identifiers, sample count, range/quantiles, and enough
  dispersion data to explain a comparison honestly;
- for `character` and `token` evidence, validated block IDs and start/end
  offsets into immutable source text;
- for `sentence` and `paragraph` evidence, the complete enclosing block range
  rather than a manufactured word attribution;
- for `behavioral` evidence, drafting-session event or time ranges rather than
  document offsets.

All submitted prose must enter the DOM as text nodes. Only application-owned,
allowlisted markup may be parsed. The demonstration baseline renderer applies
an element/attribute allowlist even though its three papers are local constants.
Before integration, add explicit loading, empty, error, stale-analysis, and
insufficient-baseline states to the API adapter; never substitute the current
illustrative values when a request fails.

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

`document-intelligence.js` coordinates the read-only passage reviewer. Selecting any
feature updates the annotated passages, difference rail, baseline comparison,
feature position, related-feature field, and interpretive guidance as one
synchronized lens. Its comparison workspace preserves identical paper geometry,
fits a two-paper reading spread without horizontal panning, increases comparison
typography, and adds paired passage markers, persistent
comparison metrics, difference navigation, and cycles
among verified baseline papers without losing the active feature lens or reading
position. At desktop widths the document participates in the page scroll while
the feature library and inspector remain sticky; this removes the competing
nested document scrollbar. Hovering, focusing, or selecting a
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
The final legibility profile is sized for older readers: 16–17px document
text, enlarged navigation and inspector copy, taller controls, wider analysis
panels, and generous line spacing while retaining a zero-horizontal-overflow
two-paper comparison. Evidence occurrences use roving keyboard focus, and the
correlation animation pauses offscreen, in background tabs, and under reduced
motion. Whole-document and drafting-session features show an explicit evidence
scope instead of receiving arbitrary inline highlights.

The supplied Long Room photograph is included locally as
`assets/long-room-library.jpg` and used as a color-graded, vignetted cinematic
backdrop. The paper remains opaque while the surrounding intelligence surfaces
reveal the architecture through controlled blur and translucency.
