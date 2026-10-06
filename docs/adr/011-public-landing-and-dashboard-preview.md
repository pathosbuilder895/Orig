# ADR-011: Restore the public landing page and preview the dashboard inside it

**Status:** Proposed
**Date:** 2026-10-05
**Deciders:** founder (product, copy, imagery, and where the landing is hosted)
**Supersedes:** the WS-7 step 5 retirement of `demo/landing.html` (AUDIT_2026-07-06 R4, ADR-008 R3 note)

## Context

### Where Original stands (verified on main `b29ae2a3`, 2026-10-05)

PR #227 merged into main after this review (`c962a9177`). Rows marked "#227" are its claimed fixes; they were not re-verified here.

| # | Problem | Status | Evidence |
|---|---|---|---|
| 1 | A student session can upload its own baseline as `proctored`; the launch link is reusable for 14 days, and each use mints a 6-hour attestation tied to no sitting or document | Fixed by #227 (T-67/T-69) | `students_baseline.py:358-362`, `student_auth.py:115,133-151`, `bluebook.py:49-90`; reproduced by probe |
| 2 | Genuine students are flagged at small baselines: the certification test is red at N=3 and N=5 (10 of 11 genuine authors at `schedule_conversation`/`escalate` at N=5) | Open (T-01) | sigma floor `state.py:271`, thresholds `constants.py:706-713` |
| 3 | Readiness (ready at 5 or more authenticated samples) is advisory: scoring never withholds an action; the only cap is client-side in `professor.html`; Bluebook ignores readiness | Open | `students.py:110-140`, `scoring.py:1951-1961`, `professor.html:2904-2916` |
| 4 | Bluebook's integrity readings (`stylometric`, `ai_score`, `status`) are computed in the student's browser and stored as sent | Open | `Exam.jsx:506-524`, `bluebook.py:236-237`; a posted `stylometric=100` returned 201 |
| 5 | Students can read classmates' Bluebook readings, and `/students/{own}/score` returns the full professor output (a scoring oracle that contradicts ADR-005) | Open | `bluebook.py:301-310`, `students_scoring.py:36-48` |
| 6 | The pilot has never been deployed; there is no staging environment | Open | `original-pilot.onrender.com/health` is a Render 404; `render.yaml` has two services |
| 7 | Public over-claims: "FERPA Compliant", "stored encrypted", "Secure · Encrypted · Monitored"; the DPA promises automatic deletion that no sweeper performs | Pages fixed by #227; DPA text unchanged | `index.html:750,893`, `explainer.html:221`, `Landing.jsx:280`, `dpa_template.md:170-171` |
| 8 | A score cannot be reproduced later: no text, baseline snapshot, flag set or SHA is stored | Open | `store.py:203-210,298-304` |

Items closed since the September notes: the `/baseline-requests/pending` leak, Turnitin flat ids, `/seed.db` on real deploys, unauthenticated `POST /bluebook/submissions`, and `delete_student` completeness. Canvas SSRF and event-loop CPU work are partial.

### How Bluebook and Original fit together

```
Student ── LTI /lti/launch  or  GET /bluebook/launch?t=  (reusable 14 days)
   │  POST /bluebook/exams/{id}/session          server-pinned deadline
   │  SEAL (Exam.jsx:488-524)
   │    1  POST /students/{sid}/score            full professor output, to the student
   │    2  POST /students/{sid}/baseline         provenance=proctored + X-Proctor-Attestation
   │                                             → features → drift gate → student_profiles
   │    3  POST /bluebook/submissions            readings computed in the browser
Staff ── /auth/login → same token as professor.html → /bluebook/*, /proctor/park/*
One FastAPI process · one database · one SECRET_KEY
```

Coupling problems: every sitting feeds Original's profiling with no professor approval and no Bluebook-only tenant before #227 added the product gate; Bluebook cannot run without Original's backend, and step 3 only runs if step 2 succeeds, so a drift 409 means the exam is never recorded; trust is inverted (items 1 and 4); keystrokes are captured and stored while Tier 17 is disabled.

### What is usable today

| Use | Readiness | Smallest next step |
|---|---|---|
| Bluebook as a standalone exam tool | Invitation-only and Bluebook-only by default since #227 | Deploy `original-pilot` on Postgres |
| Bluebook as the proctored-baseline collector | Wired end to end; `proctored` was forgeable before #227 | Run physically proctored sittings to reach 5+ samples per student |
| Original verification for a seminary pilot | Not ready: T-01 red, readiness advisory, no reproducibility | Withhold actions server-side under 5 authenticated samples; run report-only while baselines accumulate |
| Original as a sales demo | Usable now | This ADR |

### The design import

Two Claude Design pages, received as published artifacts (DesignSync needed `/design-login`, which a headless session cannot run) and unpacked from their bundles:

- **Original Landing.html**: the cinematic Oxford long-scroll (cold open, flattening, ruin, fingerprint, method, Bluebook, tension arc, baseline, demo, what it is not, closing).
- **original-quantum.html**: a professor "Integrity Operations Center" mock (term stats, flag table, per-student tier inspector) over the fingerprint canvas.

`landing.html` was deleted in WS-7 step 5 because nothing linked to it, yet `docs/OWNERS_MANUAL.md:32` still lists `/landing.html` as the marketing page. The whole `demo/` directory is static-mounted behind a denylist (`api.py:308-337`), so new pages are served on demo and pilot with no allowlist entry. #227 changed hosting: `/` now redirects to `/bluebook/` on real deploys (`/professor.html` on the demo), the `original-demo` Render service is gone, and the new `bluebook-teacher-demo` static origin publishes only an explicit allowlist (`scripts/build_teacher_demo_site.sh`). So `original-pilot` is the only deploy that serves `demo/`.

## Decision

1. Restore `demo/landing.html` from the design, served at `/landing.html` (on `original-pilot`, and locally). It does not become the front door in this change.
2. Add `demo/original-quantum.html` as a standalone design-preview page with an `?embed=1` mode that drops the outer padding and chrome.
3. Preview the dashboard inside the landing in a new section, **V·b The dashboard**, between the baseline act and the photo break: a same-origin iframe rendered at its native 1360 × 860 and scaled to the column with one CSS variable.
4. Reconcile every claim on both pages with the shipped system, and say so on the page where the data is illustrative.

## Options considered (for the preview)

### Option A: Same-origin iframe, scaled (chosen)
| Dimension | Assessment |
|-----------|------------|
| Complexity | Low: ~25 lines of CSS, 10 of JS, 2 of embed CSS |
| Cost | One extra document load, lazy (`loading="lazy"`) |
| Scalability | The preview is the real page, so it cannot drift from it |
| Team familiarity | Plain HTML; `X-Frame-Options: SAMEORIGIN` already allows it |

**Pros:** total style and script isolation (the dashboard's global `nav`, `table`, `.card`, `.bar`, `*{margin:0}` rules and its `window.$`/`__inspect` globals would collide with the landing); stays interactive; one source of truth.
**Cons:** scaled to ~0.25 on phones (made look-only there, with "Open full screen" to the responsive page); the custom cursor cannot follow into the frame (hidden while inside).

### Option B: Inline the markup with every rule re-scoped under `.ops-preview`
| Dimension | Assessment |
|-----------|------------|
| Complexity | High: ~160 rules and the JS rewritten |
| Cost | No extra request |
| Scalability | Two copies of the dashboard that drift apart |
| Team familiarity | Familiar, but tedious and fragile |

**Pros:** one document, crisp text at any width. **Cons:** maintenance burden and collision risk for no user-visible gain.

### Option C: Shadow DOM web component
| Dimension | Assessment |
|-----------|------------|
| Complexity | Medium: every `getElementById` becomes a shadow-root query; fonts still load at document level |
| Cost | No extra request |
| Scalability | Single copy if the standalone page also uses the component |
| Team familiarity | Low; nothing else in `demo/` uses it |

### Option D: Static screenshot plus link
| Dimension | Assessment |
|-----------|------------|
| Complexity | Lowest |
| Cost | One image |
| Scalability | Goes stale on every design change |
| Team familiarity | Trivial |

**Cons:** not a preview: loses the live fingerprint, the inspector and the honesty of showing the real page.

## Trade-off analysis

The deciding forces were CLAUDE.md's "prefer simple over elaborate" and drift. A and D are the simple ones; only A keeps the preview identical to the page it advertises. B and C buy crisp phone rendering at the cost of a second copy or an unfamiliar mechanism, and the phone case is already served by the standalone page's own responsive layout.

## What changed against the design, and why

### Claims reconciled with the code

| Where | Design said | The code says | Page now says |
|---|---|---|---|
| Method | 103 features, "seven tiers", depth tier 1 → 12 | `FEATURE_DIM` 109 over 18 tiers; 97 active (T17 keystroke, T18 uniformity disabled) | 109 features across 18 tiers; seven *families*; 97 active, 12 off until validated |
| Method cards | Counts 12/14/11/16/18/14/18 (sum 103) | Real tiers grouped into the seven families | 11/17/25/14/7/12/11 (sum 97); mapping in an HTML comment above the section |
| Card VII | "Voice authenticity: aggregate match against baseline" (that is the score, not a feature family) | T8 prosody, T12 κ, T13 clausulae | "Cadence & tension" |
| Bluebook | Paper booklets scanned and transcribed; "two or three booklets in, the profile can vouch" | Bluebook is an in-browser locked exam; no scanning or OCR exists; T-01 is red at N=3 and N=5; readiness wants 5 | Locked exam window, sealed exams; "about five sealed exams in"; Original says when a baseline is thin |
| Baseline | "three to five" samples; "projected onto that matrix" | Readiness at 5; actions come from `deviation_score`, not the ρ projection | "five or more"; "measured against that baseline" |
| Demo | "Original will extract its surface features"; VOICE, κ and "103 / 103" | `live-demo.js` drew VOICE from a hash (`0.78 + rand × 0.20`), κ from sentence-length variance, and three more strip lines from the seed | Seven real in-browser measures; cells show mean sentence, vocabulary, 7 / 109; "nothing is sent anywhere" |
| Promise | −30% grading time "beside the scan", "5 min", "0 honest students flagged" | Unmeasured; scanning not built; T-01 red | Typed, Midterm, Plain, Open |
| Dashboard | 17 tiers, 103 measured; 59% and 52% labelled Flagged, 34% and 29% Needs review; flag rate 59% beside "121 of 128 in their own voice" | 18 tiers (16 active), 97 active; monitor 0.40-0.60, schedule_conversation 0.60-0.75; 7 of 128 is about 5% | 16 active, 97 measured; 66/62 and 47/43; 5%; an "Illustrative data · fictional names" chip |
| Footer | Pilot brief, FERPA & GDPR, Canvas, documentation, terms, help | None of these pages exist in `demo/` | Sign in, Bluebook exams, The dashboard, and in-page anchors |

### Imagery
- The dashboard hero was a watermarked third-party photograph ("Sarah Savic Kallesøe | Oxford by Night"). It is replaced by the public-domain 1822 Storer engraving, inverted into a night plate.
- `st-andrews-ruins.webp` is a modern photograph with an identifiable passer-by and no licence on file. It ships as designed, but needs a licence or a replacement before public launch.
- `all-souls-engraving` and `radcliffe-engraving` are byte-identical to "ChatGPT Image Jul 6, 2026" uploads in the Jul 11 export, while their captions credit Mackenzie & Le Keux (1834) and J. & H. S. Storer (1822). If they are AI renderings rather than restorations of the plates, the captions misattribute.
- Engravings were converted from PNG to WebP (5.3 MB to 0.7 MB).

### Design-tool scaffolding dropped
React, ReactDOM and Babel standalone (about 4.3 MB, used only by the Tweaks panel), `image-slot.js`, the Claude Design badge, and the export's global scrollbar hiding. The Tweaks defaults are baked in as body attributes (Bodleian palette, full motion, epigraph hero, Playfair with EB Garamond). The repo's July `tension-arc.js` and `live-demo.js` were kept over the design's: they add the real tension series and a hidden-iframe failsafe. `fingerprint.js` and `scenes.js` are byte-identical to the design.

## Consequences

- **Easier:** one URL to send a prospect (`/landing.html`), with the product visible in it; the dashboard design lives in the repo next to the code it describes.
- **Harder:** marketing copy now has an owner in the repo. Any change to `FEATURE_DIM`, `DISABLED_FEATURE_GROUPS` or `ACTION_THRESHOLDS` should be checked against both pages.
- **Revisit:** the landing still describes the product as it should be. Problems 2, 3 and 4 above keep "honest students are not flagged by a black box" untrue until T-01 is fixed and actions are withheld under five samples.

## Action items

1. [ ] Founder: review the reconciliation table; revert any line that reflects a deliberate product direction (for example, paper-booklet scanning).
2. [ ] Licence or replace `st-andrews-ruins.webp`; confirm the provenance of both engravings and their captions.
3. [ ] Decide where the landing lives. With `original-demo` gone it is reachable only at `original-pilot/landing.html`, whose root opens Bluebook; it is unlinked there.
4. [ ] If it should live on the static `bluebook-teacher-demo` origin instead, add `landing.html`, `original-quantum.html`, `styles/original-landing.css`, `js/{cursor,fingerprint,tension-arc,live-demo,scenes}.js` and the three assets to `scripts/build_teacher_demo_site.sh`, and check that origin's `X-Frame-Options` still allows a same-origin frame.
5. [ ] Give Original its own privacy and terms pages and link them from the footer. `demo/legal/` (from #227) is Bluebook's draft policy and does not describe Original's profiling.
6. [ ] Keep `original-quantum.html` a mock, or wire it to a real overview endpoint (the design expects `GET /api/v1/overview`, which the live stack lacks; the loader now runs only when `window.ORIGINAL_API` is set). Never show real student data in the public preview.
7. [ ] Before the landing's promises are true: withhold actions server-side under 5 authenticated samples (T-01); keep Bluebook's readings server-computed; store what is needed to reproduce a score.
