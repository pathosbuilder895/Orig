# Navy demo suite: design record

*2026-10-08. Approved in session with Andrew (parts 1-3 below).*

## Goal

Andrew handed over 13 Claude Design pages (`~/Desktop/handoff/frontend/`,
"Navy Suite") and asked to make them the UI. Decision: **both, demo first.**

1. **Now:** publish the suite as a clearly labelled fictional demonstration.
2. **Later, page by page:** port the look into the live app (`demo/bluebook/`,
   `demo/professor.html`, `demo/student.html`) with real API data. Separate
   specs; not started.

The handoff's `MANIFEST.md` targets `frontend/`, which was deleted in July
(ADR-006). NORTH_STAR rule 9 says to port the design's look, not its invented
data, which is why the suite was cleaned before it shipped rather than copied.

## Part 1: where it lives and how it ships

- `demo/prototypes/navy/`: the 13 pages, `js/fingerprint.js` (byte-identical
  to `demo/js/fingerprint.js`), `js/feature-data.js`, `fonts.css`, `demo.css`,
  `fonts/` (OFL fonts the repo lacked), `assets/CREDITS.md`, and an
  `index.html` entry page with three links: teacher view, student view, and the
  existing interactive Bluebook walkthrough.
- `/prototypes` already returns 404 on real deploys, so the suite is visible
  in `run.py --demo` and never in the pilot.
- Published by `scripts/build_teacher_demo_site.sh` to `prototypes/navy/` on
  the existing `bluebook-teacher-demo` static site, whose front page now opens
  the suite. No new hosting, no `render.yaml` change.
- Images: Andrew will supply sources and licences. Until then **no image ships**
  (including `codrington-library.jpeg`, which has no licence on file either);
  pages fall back to the design's navy gradients. `assets/CREDITS.md` lists
  each pending image and the exact CSS to restore it.
- Not touched: Task B files (`demo/landing.html`, `demo/original-quantum.html`,
  `demo/assets/`, `demo/js/`), Task C files (`demo/bluebook/*.jsx`, bundles),
  `original/**`.

## Part 2: what was cut or reworded

Rule applied: change only what breaks a NORTH_STAR rule or revives a deferred
feature; keep the rest of the design's wording.

- **Every page:** fictional-demonstration ribbon; self-hosted fonts
  (JetBrains Mono became IBM Plex Mono); deviations shown as `0.59`, not `59%`
  (a percentage beside a name reads as a probability); invented domains
  (`sbts.edu`, a real seminary, and `original.edu`) removed; links to pages not
  in the suite removed.
- **Testing-phase notice** (STATUS shared wording) on every page that shows an
  Original result. Student pages also say a teacher may approve sealed work as
  reference writing and can undo it (rule 10).
- **Rule 6:** every typing-rhythm claim removed; Tier 17 not shown. Session
  copy lists what is actually kept: text plus duration, word count, paste
  attempts, focus losses, as context rather than evidence.
- **Rule 2:** feature counts now come from the product (109 features, 97
  active; the old suite said 103). Removed: "characteristic of generated
  prose", "editing-tool polish rather than wholesale generation", "Read as
  authentic", "the two hardest things to fake", "always scores near 0.0",
  "regardless of topic", "suggestions from the pilot program". The Writing
  State math note now says what produces the number (`tanh(rms z / k)` over
  per-habit z-scores, `original/quantum/scoring.py`) and that the density
  matrix does not.
- **Rule 3 / rule 8:** "every booklet becomes an authenticated baseline",
  "three samples give a working baseline", "after two or three sessions it can
  vouch", "a fourth sample shows growth" replaced with thin-baseline wording
  and teacher approval.
- **Rule 1:** "Integrity Operations Center" became "Writing at a glance"; the
  "Escalate for review" action and the `AI-` case prefix removed.
- **Not doing now:** the My Voice term timeline and the writer-similarity
  "% alike" cards removed; Settings' Canvas "Connected" card removed; the
  "~3 / ~7 / ~14 flags per term" estimates removed.
- **Student pages:** class comparisons removed; four misattributed quotations
  in the Library corrected; the Lewis paraphrase credited "After C. S. Lewis".
- **Fictional means fictional:** the dashboard's `GET /api/v1/overview` loader
  removed. The JSON shape stays documented in a comment for the live port.
- Fixes to the design itself: Settings had no phone layout; the packet's table
  overflowed at phone width; the opened booklet cover made the page scroll.
- Em dashes in interface copy became commas, colons or parentheses. The
  fictional student essays keep theirs (as `&mdash;`), because there the dash
  is the habit being shown.

## Part 3: tests that hold it

`tests/test_teacher_demo_site.py`: exact publish allowlist; every suite link
resolves on the built site; no third-party hosts; ribbon on every page;
testing notice on every Original-result page; student reference-writing
notice; a list of removed claims (each checked to fire on the raw handoff)
including any network call; every image credited; `feature-data.js` equals
the active feature set with the product's tier names.
`tests/test_pilot_lockdown.py`: `/prototypes/navy/...` returns 404 on a real
deploy.

## Open items

- Andrew: image sources and licences (see `assets/CREDITS.md`).
- Live port: one spec per surface. Candidate order: Bluebook teacher frame
  (after Task C lands), professor Original pages, student pages.
