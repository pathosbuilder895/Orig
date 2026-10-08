# ADR-011: Restore the public landing page (without a dashboard preview)

**Status:** Proposed
**Date:** 2026-10-05, revised 2026-10-07 for `docs/NORTH_STAR.md` v0.2 (STATUS.md task B)
**Deciders:** Andrew (product, copy, imagery, and where the landing is hosted)
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

### What NORTH_STAR v0.2 changed (2026-10-07)

The first version of this ADR reconciled the design with the code. NORTH_STAR then set the rules the page must meet, and the 2026-10-07 revision applies them:

- **Audience:** this phase is an invitation-only Bluebook pilot for independent teachers, not institutions or professors.
- **Baselines:** sealing never adds work to a profile; only teacher-approved writing becomes a baseline, and approvals can be undone (rule 8). The page said sealed, proctored exams were "banked as baseline".
- **Honest claims (rule 2):** no AI-authorship claims, no unsupported precision, and every fictional number or name is labelled fictional.
- **No keystroke data (rule 6):** the page said keystroke features "stay off until they pass validation", which implies they could be switched on.
- **Testing-phase label (rule 10):** Original is labelled as unvalidated wherever it appears.
- **Port the dashboard's look, not its invented data (rule 9):** the dashboard mock was an invented term of flagged students.
- **Student writing stays inside the deployment (rule 7):** the demo textarea sat on a page that loaded Google Fonts.
- **Images (AGENTS.md, Claude Design):** no AI-generated images credited as historical art, and no unlicensed photographs.

## Decision

1. Restore `demo/landing.html` from the design, served at `/landing.html` (on `original-pilot`, and locally). It does not become the front door in this change.
2. **Do not ship the dashboard mock.** `demo/original-quantum.html` and the landing's "V·b The dashboard" iframe preview are removed. A real teacher dashboard is NORTH_STAR milestone 3 and belongs in the Bluebook teacher workspace, with real API data and the rule-10 label.
3. Reconcile every claim on the page with the shipped system and NORTH_STAR (tables below).
4. Show a testing-phase notice directly after the cold open, using the shared label text from STATUS.md, and label every illustrative number, name and drawing as fictional or illustrative.
5. Self-host the fonts from `demo/assets/fonts` (the files Bluebook already serves), so the page makes no third-party request.
6. Ship no image whose licence or provenance is in doubt (see Imagery).

## Options considered (for the dashboard preview)

*Kept for the record. The 2026-10-07 revision removed the preview altogether (Decision 2), so none of these ships.*

- **A. Same-origin iframe, scaled** (originally chosen): low complexity and no drift from the page it shows, but the page it showed was a mock with invented data.
- **B. Inline the markup re-scoped under `.ops-preview`:** about 160 rules rewritten; two copies that drift.
- **C. Shadow DOM web component:** unfamiliar in `demo/`; fonts still load at document level.
- **D. Static screenshot plus link:** simplest, but goes stale.

## What changed against the design, and why

### 2026-10-05: claims reconciled with the code

| Where | Design said | The code says | Page now says |
|---|---|---|---|
| Method | 103 features, "seven tiers", depth tier 1 → 12 | `FEATURE_DIM` 109 over 18 tiers; 97 active (T17 keystroke, T18 uniformity disabled) | 109 features defined across 18 tiers; seven *families*; 97 in use |
| Method cards | Counts 12/14/11/16/18/14/18 (sum 103) | Real tiers grouped into the seven families | 11/17/25/14/7/12/11 (sum 97); mapping in an HTML comment above the section |
| Card VII | "Voice authenticity: aggregate match against baseline" (that is the score, not a feature family) | T8 prosody, T12 κ, T13 clausulae | "Cadence & tension" |
| Bluebook | Paper booklets scanned and transcribed | Bluebook is an in-browser locked exam; no scanning or OCR exists | A locked, in-browser writing window |
| Demo | "Original will extract its surface features"; VOICE, κ and "103 / 103" | `live-demo.js` drew VOICE from a hash (`0.78 + rand × 0.20`), κ from sentence-length variance, and three more strip lines from the seed | Only what the browser measures (see the 2026-10-07 table) |
| Promise | −30% grading time "beside the scan", "5 min", "0 honest students flagged" | Unmeasured; scanning not built; T-01 red | Replaced (see the 2026-10-07 table) |

### 2026-10-07: NORTH_STAR v0.2

| Where | Page said | Why it changed | Page now says |
|---|---|---|---|
| Throughout | "professor", "proctor", "committee", "For Institutions", "THEO 301 · Dr. Hendricks" unlabelled | Audience is independent teachers; fictional names must be labelled (rule 2) | "teacher"; footer "For Teachers"; the booklet carries a "Fictional example" tag |
| New | No notice | Rule 10 | A testing-phase band after the cold open: "Original is not yet validated on real student writing. Treat any result as a reason for a conversation, never as evidence." Repeated in the fictional result card and the footer |
| Act I | "Plagiarism detectors" ask human or computer; Original "will show whether it is the same writer" | AI detectors ask that, not plagiarism detectors; Original supports judgement and gives no verdict (rule 1) | AI detectors ask the wrong question; Original "shows the teacher what moved, so the next step is a conversation, never a verdict" |
| Fingerprint | "Measurable to a thousandth of a unit"; readout "A. Webb · 0x7C3", "STATE · resolved" | Unsupported precision; a fictional writer presented as real | "Original uses ninety-seven of them... A sketch, not proof"; readout "Fictional writer", "FEATURES · 109 defined", "IN USE · 97", "DRAWING · illustrative" |
| Method | Twelve keystroke and uniformity features "stay off until they pass validation" | Rule 6: keystroke data is never collected, so T17 is never coming on | "Six keystroke-timing features, because Original collects no keystroke data, and six uniformity measures that have not passed validation"; the big count reads 97 |
| Bluebook | Baseline built "only from proctored writing"; "each sealed exam becomes an authenticated sample"; "about five sealed exams in, the profile is ready" and Original "tells the professor while a baseline is still thin" | Rule 8: sealing adds nothing, only teacher-approved writing counts, approvals can be undone. T-01 is red at N=5 and no Bluebook screen shows readiness | Sealing adds nothing on its own; only work the teacher approves becomes reference writing; with few pieces it is not reliable, and testing found too many false alarms on small baselines, which is why Original is off by default |
| Tension arc | "AI text, even when fluent, tends to flatten the arc"; "Models trained to be helpful resolve too eagerly"; "averaged over three authenticated samples"; "one orthogonal input" | No AI-authorship claims; three contradicted five; "orthogonal" is unmeasured | "One feature among ninety-seven, and not a test for machine writing"; "what it cannot do: it is not a lie detector"; an "Illustrative curve" tag (the landing draws synthetic data) |
| Baseline cards | Phrase highlights for "matches voice baseline" and "stylometric anomaly"; "voice match 0.71 · flagged for human review"; "measured against this student's baseline fingerprint ρ" | Phrase-level highlighting is not a shipped feature; "voice match" is not an output; actions come from `deviation_score`, not a ρ projection | Plain fictional essay; "What the teacher sees · fictional example"; "reads differently · worth a conversation"; "97 features compared with this student's own usual range" |
| Baseline copy | "Three papers"; the baseline is "a quantum density matrix ρ"; "the math is fair... not penalised for being unusual, only for being suddenly someone else" | Five, not three; the ρ framing implies it drives the comparison; fairness parity (G6) is unvalidated and rule 4 lists legitimate reasons writing changes | "Their own pages. Their own voice."; the baseline is "the usual value and the usual spread of each feature"; a different piece may reflect learning, genre, revision, permitted help or accommodations; "A difference starts a conversation; it never ends one" |
| What it is not | "The student always sees their own report"; "no retroactive sweeps" | Neither is verified | Not an AI detector; not surveillance (no camera, screen recording or keystroke biometrics); not a verdict; **not a corrector** (rule 5) |
| Promise | "A verified writing profile"; "language a committee can defend"; "every report is visible to the student" | Over-claims and misconduct framing | "What a teacher gets": Typed, Optional (Bluebook works without Original), Approved (only approved writing counts, approvals can be undone), Honest (no "AI-written" label, no probability of cheating) |
| Demo | "Try Original on your own writing"; "7 / 109"; "provisional fingerprint"; "live extraction" | The browser's seven measures are not seven of the 109 features, and the drawing is seeded from a hash | "See what gets measured in your own writing"; "7 simple habits, in your browser"; "drawing is decorative"; "nothing you paste leaves this page" |
| Closing | "If you tell the truth, you will become original..." credited to C. S. Lewis | A paraphrase presented as a quotation | Same paraphrase, credited "After C. S. Lewis, *Mere Christianity*" |
| Footer | "© Original Stylometrics"; "The dashboard" link; "Sign in" to `index.html` | No such entity on file (legal pages still read `[ENTITY]`); the dashboard is gone; teachers sign in to Bluebook | "Original · MMXXVI · Testing phase..."; "Sign in to Bluebook" (`bluebook/`) |
| Fonts | Google Fonts (Cormorant, EB Garamond, JetBrains Mono, Playfair Display) | Rule 7: the page has a writing textarea | Self-hosted from `demo/assets/fonts`; JetBrains Mono is replaced by IBM Plex Mono (the mono Bluebook ships); Playfair Display has no italic file there, so its italics are synthesised by the browser |

### Imagery

All three photographic or engraved images are removed from the branch:

- `st-andrews-ruins.webp`: a modern photograph with an identifiable passer-by and no licence on file. The ruin section now stands on a plain night gradient.
- `radcliffe-engraving-navy.webp` and `all-souls-engraving.webp`: byte-identical to "ChatGPT Image Jul 6, 2026" uploads in the Jul 11 export, **and each prints a historical credit inside the image**: "Drawn & Eng.d by J. & H. S. Storer... London: Pub.d June 1. 1822 by Sherwood, Neely, & Jones", and "F. Mackenzie / J. Le Keux... Published Nov.r 1st 1834 by J. H. Parker". A corrected caption cannot fix a credit drawn into the picture. The cold open falls back to the design's dark hero (the `engraved` class is off; its CSS is kept), and the photo break before the demo is removed.
- The design's original dashboard hero was a watermarked third-party photograph and was already replaced on 2026-10-05; it left with the dashboard.

To bring the plates back, use genuine public-domain scans of the same plates (both were published in 1822 and 1834), credit them as what they are, re-add the `engraved` class and an `.hero-bg` image to the cold open, and restore the photo-break section from this PR's history.

### Design-tool scaffolding dropped

React, ReactDOM and Babel standalone (about 4.3 MB, used only by the Tweaks panel), `image-slot.js`, the Claude Design badge, and the export's global scrollbar hiding. The Tweaks defaults are baked in as body attributes (Bodleian palette, full motion, epigraph hero, Playfair with EB Garamond). The repo's July `tension-arc.js` and `live-demo.js` were kept over the design's: they add the real tension series and a hidden-iframe failsafe. `fingerprint.js` and `scenes.js` are byte-identical to the design.

## Consequences

- **Easier:** one URL to send a prospective teacher (`/landing.html`) that says plainly what Original is, what it is not, and that it is in testing. The page makes no third-party requests.
- **Harder:** marketing copy now has an owner in the repo. Any change to `FEATURE_DIM`, `DISABLED_FEATURE_GROUPS`, `ACTION_THRESHOLDS` or the baseline-approval flow should be checked against the page.
- **Visual cost:** without the plates, the cold open and the ruin section are typographic only, and there is no product screenshot on the page.
- **Revisit:** problems 2, 3 and 4 above still stand. The page no longer promises otherwise, but they decide when Original can leave its testing phase.

## Action items

1. [ ] Andrew: review both reconciliation tables; revert any line that reflects a deliberate product direction.
2. [ ] Andrew: choose final images. Genuine public-domain scans of the two plates, licensed photographs, or none (today's state).
3. [ ] Andrew: decide where the landing lives. With `original-demo` gone it is reachable only at `original-pilot/landing.html`, whose root opens Bluebook; it is unlinked there.
4. [ ] If it should live on the static `bluebook-teacher-demo` origin instead, add `landing.html`, `styles/original-landing.css`, `js/{cursor,fingerprint,tension-arc,live-demo,scenes}.js` and the `assets/fonts/` files the page uses to `scripts/build_teacher_demo_site.sh` (owned outside task B).
5. [ ] Give Original its own privacy and terms pages and link them from the footer. `demo/legal/` (from #227) is Bluebook's draft policy, awaits counsel, and does not yet describe Original.
6. [ ] Build the teacher-facing Original view as milestone 3 asks: real data, inside the teacher workspace, with the rule-10 label. Never show real student data on the public page.
7. [ ] Before Original leaves its testing phase: withhold actions server-side under 5 approved samples (T-01); keep Bluebook's readings server-computed; store what is needed to reproduce a score.
