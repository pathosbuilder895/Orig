# Document parts experiment (2026-11-18)

Evidence for ADR-015 (`docs/adr/015-document-parts-and-pilot-readiness.md`).

**Question.** When a student's paper arrives with a cover letter, a title
block, notes or a bibliography attached, how much does that move the score of a
paper the student really wrote?

**Design.** Every paper is genuine, so any rise is a false alarm.

- Writers: the 9 authors in `validation/public_authors/corpus/` with at least 5
  `*part_0*.txt` files (augustine, boethius, chesterton, douglass, edwards,
  james, kempis, mill, newman).
- Past papers: parts 1 to 4, each cut to its first 9,000 characters (about
  1,500 words), uploaded as `verified`.
- New paper: part 5, cut the same way, scored once per variant. A fresh student
  per variant, so variants never see each other.
- Front and back matter: one fixed cover letter, title block, notes list, and an
  MLA and an APA bibliography (in `run_experiment.py`).
- Path: the live `/students/{id}/baseline` and `/students/{id}/score` routes
  through an in-process `TestClient`, with the pilot's flags:
  `CONTEXT_MANIFEST_ENABLED=0`, `ADAPTIVE_WEIGHTS_ENABLED=0`, `NULL_MODEL=none`,
  `DRIFT_GATE=advisory`, and no `sentence-transformers` (the pilot lockfile
  leaves it out, so Tier 10 and the tension arc use their fallbacks as live).

**Results** (`summary.json`; raw rows with every feature vector in
`rows_A.json`, `rows_B.json`):

| Paper scored | Mean deviation | Mean rise | Largest rise | Band went up | At "worth a conversation" or higher |
|---|---|---|---|---|---|
| Plain, ~1,500 words | 0.475 | | | | 0 of 9 |
| + "Works Cited" (heading the stripper knows) | 0.475 | +0.000 | +0.000 | 0 of 9 | 0 of 9 |
| + title block | 0.481 | +0.006 | +0.041 | 0 of 9 | 0 of 9 |
| + cover letter | 0.473 | -0.002 | +0.083 | 0 of 9 | 0 of 9 |
| + "Works Cited:" (colon, not stripped) | 0.582 | +0.106 | +0.179 | 3 of 9 | 2 of 9 |
| + "## References" (APA, not stripped) | 0.570 | +0.095 | +0.215 | 3 of 9 | 2 of 9 |
| Short plain, ~430 words | 0.626 | | | | 8 of 9 |
| Short + cover letter | 0.616 | -0.011 | +0.016 | 0 of 9 | 7 of 9 |
| Short + title + "Works Cited:" | 0.726 | +0.099 | +0.168 | 3 of 9 | 9 of 9 (2 escalate) |

The short variants are compared with "short plain", not with "plain".

**What it does not show.** This is published 19th-century prose, not student
writing, and n = 9. The rows say which direction and roughly how large; they
are not false-alarm rates to quote. The short-paper rows mix two effects: the
length mismatch against 1,500-word past papers (PR #334) and the added parts.

**Rerun.** From the repository root, about 10 minutes per set on 3 workers:

```bash
for w in 0 1 2; do FB_SET=A FB_WORKER=$w FB_WORKERS=3 .venv/bin/python -I validation/diagnostics/document_parts_2026-11-18/run_experiment.py & done; wait
```

`FB_SET=B` runs the unmatched-heading and short-paper variants. Each worker
writes `rows_<set>_<worker>.json` next to the script.

## The same experiment against PR #354's splitter

Run on PR #354's branch (`feat/measures-v2`, `2cf45136`) with
`MATTER_SPLITTER_ENABLED=1` and `FEATURE_SET=1` (raw rows
`rows_splitter_pr354.json`, summary `summary_splitter_pr354.json`):

| Paper scored | Rise on main | Rise with the splitter | Band went up (main → splitter) |
|---|---|---|---|
| + "Works Cited:" (colon) | +0.106 | +0.000 | 3 → 0 of 9 |
| Short + title + "Works Cited:" | +0.099 | +0.002 | 3 → 0 of 9 |
| + "## References" (APA, markdown heading) | +0.095 | +0.090 | 3 → 3 of 9 |
| + cover letter | -0.002 | +0.005 | 0 → 0 of 9 |
| + everything | +0.007 | +0.012 | 0 → 1 of 9 |

The splitter removes the colon-heading and short-paper harm. A markdown
"## References" heading and a cover letter are still measured as prose; ADR-015
names both as the gaps to close. Plain papers moved +0.003 on average on that
branch, which sits on an older base, so the shift is not attributed here.

## Against PR #359 (the gaps ADR-015 named)

A diagnostic run, not a validation: the same 9 published 19th-century authors
(public-domain books, not student writing), one genuine paper each, scored plain
and with parts added, on PR #359 (`claude/matter-gaps`) with the splitter on
(pilot flags, `MATTER_SPLITTER_ENABLED=1`, `FEATURE_SET=1`). n = 9 per row; the
rules were developed against this experiment, so it is not an independent test.
The figures show direction and rough size; they are not false-alarm rates for
students. Raw rows `rows_splitter_pr359.json`, summary `summary_splitter_pr359.json`.

For scale: under these flags, 8 of the 9 plain papers already read "monitor",
and 7 of 9 short plain papers read "schedule a conversation".

- Under each of the three headings tried ("Works Cited", "Works Cited:",
  "## References"), the same fixed list of sources moved the reading by 0.000 on
  all 9 papers. That is the only change from #354 on this experiment, where
  "## References" had raised the reading by +0.090 on average and moved 3 of 9 up
  a band. Other headings and other kinds of list were not tested.
- A cover letter is still measured as prose (#359 tried a rule for it and
  dropped it after three reviews found student writing it set aside). It moved
  full-length readings both ways, +0.005 on average, between -0.032 and +0.076,
  2 of 9 within 0.01, no band change.
- Notes without years are also measured as prose. Notes plus a bibliography moved
  the reading by -0.002 on average, between -0.022 and +0.045, 4 of 9 within
  0.01, no band change.
- All the parts together raised the reading by +0.012 on average, at most
  +0.078; 2 of 9 stayed within 0.01, and one paper went up a band (Edwards,
  "monitor" to "schedule a conversation", +0.071).
- On a ~430-word paper against ~1,500-word past papers, a cover letter moved
  readings between -0.054 and +0.022 and took one paper up a band (Newman,
  +0.022). The short rows mix this with the length mismatch.
- A title block left 8 of 9 readings exactly unchanged. The exception is
  Douglass (+0.056, no band change), and the cause is the splitter, not the title
  block: his excerpt opens with an all-caps chapter summary from the Gutenberg
  edition, and with a dated heading block above it the splitter took six of its
  seven lines (48 of his own words) as part of the heading block. A student's own
  capitalised lines under a heading block could be taken the same way; that has
  not been tested.
