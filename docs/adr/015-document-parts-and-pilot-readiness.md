# ADR-015: Judge a paper's parts separately, and what the pilot needs next

**Status:** Proposed
**Date:** 2026-11-18
**Deciders:** Andrew
**Numbering:** ADR-014 is taken by PR #312 (classroom verification target).
**Relates to:** `docs/NORTH_STAR.md` rules 2, 3, 4 and 7; the approved measurement stack PR #353 → #352 → #354 → #355; ADR-012 (navy suite); ADR-013 (located evidence, preliminary score); PR #326 (Writing State essentials); PR #334 (length-matched baseline); PR #353 (memory); PR #325 (invite and reset fixes)
**Evidence:** `validation/diagnostics/document_parts_2026-11-18/`; the visual audit page (annotated screenshots and the experiment chart), https://claude.ai/artifact/Usn2sFBH5J27fuPcD3fSPA (private to the owner; share it from its Share menu)

## Context

Andrew, 2026-11-18: bring the pilot up to speed, bugs fixed, UI and UX
"unabashedly sleek"; find the problems with visuals; fix the aspects of
stylometry that are not accurately spotted; and judge a cover letter and a
bibliography differently from the prose of the paper instead of making them
part of it.

An audit on 2026-11-18 (main `374b83f` plus PR #326) walked every teacher and
student screen on a pilot-mode server at laptop and phone width, traced the
feature code, and ran an experiment on genuine papers. What it found:

**1. Parts of a document are measured as the student's prose.**
`original/features/preprocess.py` has one way to set anything aside: a
back-matter heading that must stand alone on its line in about a dozen exact
forms (lines 42 to 65), after which everything is cut. Nothing detects a cover
letter, title block, abstract, contents, URL, table or list. Consequences:

- "Works Cited:", "Reference List", "Literature Cited", "## References",
  "7. References" and "Appendix A: …" are measured as prose.
- A lone "Notes" or "Appendix" line early in the paper (a contents entry) cuts
  off everything after it.
- `tier1.py:70-87` joins lines before splitting sentences, so a title block
  becomes one 35-word sentence and "Sincerely, Jordan Reyes" runs into the
  first real sentence. `tier3.py:271` reads the last 20% as the conclusion, so
  a letter or list placed last replaces the conclusion.

Measured (9 writers, every paper genuine, pilot flags; full table in the
evidence folder):

| Paper scored | Mean deviation | Mean rise | Band went up | At "worth a conversation" or higher |
|---|---|---|---|---|
| Plain, ~1,500 words | 0.475 | | | 0 of 9 |
| + "Works Cited" (heading recognised) | 0.475 | +0.000 | 0 of 9 | 0 of 9 |
| + cover letter | 0.473 | -0.002 | 0 of 9 | 0 of 9 |
| + "Works Cited:" (not recognised) | 0.582 | +0.106 | 3 of 9 | 2 of 9 |
| + "## References" (not recognised) | 0.570 | +0.095 | 3 of 9 | 2 of 9 |
| Short plain, ~430 words | 0.626 | | | 8 of 9 |
| Short + title + "Works Cited:" | 0.726 | +0.099 | 3 of 9 | 9 of 9 |

A bibliography the stripper misses raises an honest paper's deviation by about
0.10 for every writer. A cover letter barely moves the total at these lengths,
but it changes which habits the teacher is shown ("furthest from usual" gains
metric flatness or source integration for 3 of 9 writers), so the explanation
is wrong even when the band is right. Independently, a genuine 430-word paper
against 1,500-word past papers is flagged for 8 of 9 writers with no added
parts at all: the length mismatch PR #334 describes is the largest false-alarm
source in this audit.

**2. Several measurements do not measure what their name says.** Traced in
code, with probes on the real extractors:

- Citations are counted twice (`preprocess.py:335-337`); the author-date
  pattern misses "et al.", "McGrath", "O'Brien" and "2001a"; the scripture
  pattern also takes "(Chapter 3)", "(Table 1)" and MLA "(Smith 45)".
- The footnote-marker pattern takes verse numbers and decimals and deletes
  their digits from the prose ("As John 3: says", "1. million").
- The tokenizer knows only the straight apostrophe, so "don’t" is two words;
  contraction rate counts possessives and misses curly apostrophes.
- docx import drops footnotes, headers and tables; pdf import keeps running
  heads and page numbers, and a "paragraph" becomes a whole page.
- `appeal_to_authority_density` counts any "states", "notes" or "claims",
  cannot match "cf.", and misses "argued"; the hedge list includes "about",
  "around", "would" and "could"; the that/which ratio counts "argues that the";
  abbreviation tendency counts "universe" as "verse".
- Without spaCy, Tier 5 returns 0.0, not a neutral value.
- Validation finds no between-author signal at any length for
  catastrophe_index, metric_flatness_score, transition_predictability and the
  three Tier 16 citation-spread features, yet catastrophe_index was the top
  "difference" in this audit's analysis and the narrative calls metric
  flatness "a common pattern in AI-generated text".
- Teacher card text describes arc_resolution_score, vowel_sonority_ratio,
  pronoun_ambiguity_rate, chiasmus_rate, perplexity_proxy and the discourse
  marker ratios as things the code does not compute.

**3. The pilot's remaining blockers are mostly owner work.** Live pilot on main
`0ceaaec7`: Postgres, signup closed, Original on in the alpha workspace. Open:
hosting sign-off, email, off-box backups (the cron cannot succeed), legal pages
still drafts, the deployed acceptance run never done, no teacher named, the
repository still public. Engineering that is live-relevant: memory headroom
(PR #353), the length mismatch (PR #334), invite and reset fixes (PR #325),
the seal trusting the browser's integrity reading (T-77), and alpha-only
settings that need a decision before real teachers (`DRIFT_GATE=advisory`,
`INVITE_NO_EXPIRY`, the hard-coded alpha guide).

**4. The interface is not yet one product.** Three type systems in one suite;
two palettes in Collections; four button systems; New Collection and the
teacher sign-in each in a design of their own; the same nav labels going to
different places in the two apps; no automated accessibility check on any
Original page; dim body text below AA contrast; a fixed 900px frame with hidden
scrollbars that turns Writing State into two invisible scroll panes on a phone;
no loading or retry states; a decorative animation that runs two loops of
about 1,700 particles each, never pauses and ignores reduced motion. Bugs seen
on screen: Writing State scrolls past its own heading on load and overlaps its
form on a phone; the overview greets "Good afternoon," with no name; a
student's My Voice page says Original is off for the class when the route is
off only for students; the "Aa Text" button covers content on phones.

## Decision

**Judge a paper's parts separately by finishing the approved measurement stack,
not by building a second one.** The stack is #353 (spaCy loaded once) → #352
(teacher-only paper profile) → #354 (reworked word lists and the
front/back-matter splitter, `MATTER_SPLITTER_ENABLED`) → #355 (versioned
measurements, so a paper is only ever compared with past papers measured the
same way). It already does most of what this audit asks for:

- #354's `original/features/matter.py` sets aside the heading block, section
  headings, running heads and page numbers, citation-shaped footnote lines and a
  verified list of sources, reads the sources heading tolerantly, trusts it
  only after the first 40% of the paper, and never lets an early "Notes" or
  "Appendix" line cut the paper. When unsure it keeps the text as prose.
- #352's paper profile is the "judge it on its own terms" view for the
  bibliography: count of sources, a best-guess citation style, years, kinds,
  in-text citations and footnote markers, shown to staff beside the comparison
  and never part of it.

The same experiment, run against #354 with `MATTER_SPLITTER_ENABLED=1`
(`summary_splitter_pr354.json`), measures what it fixes and what it leaves:

| Paper scored | Rise on main | Rise with #354's splitter | Band went up (main → #354) |
|---|---|---|---|
| + "Works Cited:" (colon) | +0.106 | **+0.000** | 3 → 0 of 9 |
| Short + title + "Works Cited:" | +0.099 | **+0.002** | 3 → 0 of 9 |
| + "## References" (APA, markdown heading) | +0.095 | **+0.090** | 3 → 3 of 9 |
| + cover letter | −0.002 | +0.005 | 0 → 0 of 9 |
| + everything | +0.007 | +0.012 | 0 → 1 of 9 |

Plain papers moved by +0.003 on average on that branch; it sits on an older
base than this audit, so that shift is not attributed to the splitter here.

So this ADR decides to adopt the stack and close its measured gaps:

1. **Headings in markdown or numbered form** ("## References", "7. References",
   "References:" after a numbered section list) are recognised by the
   splitter's tolerant heading rule. Today they still raise an honest paper by
   about 0.09.
2. **Cover letters become a matter kind.** A salutation ("Dear …", "To …,")
   and a closing ("Sincerely", "Respectfully", "Best", a name alone) at the
   start or the end of the paper set the letter aside, under the same
   keep-as-prose-when-unsure guard. The letter is shown with its word count and
   never scored: there is no record of a student's letters to compare it with,
   so there is no number to give (NORTH_STAR rule 3).
3. **The experiment becomes the stack's regression test**: with the splitter
   on, every "+part" variant must stay within 0.01 of the plain paper for every
   writer (`validation/diagnostics/document_parts_2026-11-18/`).
4. **The teacher sees what was set aside**: the paper profile lists each
   set-aside part with its kind and word count, and a part can be counted as
   prose for that analysis.
5. **Measurement fixes #354 does not cover** ship the same way, each behind a
   flag, byte-identical off, versioned through #355: citations counted twice,
   the footnote-marker pattern eating verse numbers and decimals, the
   straight-apostrophe tokenizer, appeal-to-authority matching, abbreviation
   substring matches, the that/which ratio, and the no-signal habits
   (catastrophe index, metric flatness, transition predictability, the Tier 16
   spread trio) kept out of the teacher's "furthest" list, with the "AI
   marker" wording removed from the narrative.

## Options considered

### A. Finish the approved stack and close its measured gaps (chosen)

| Dimension | Assessment |
|---|---|
| Complexity | Low to medium: two splitter rules, one test, one list in the profile |
| Cost | No new dependencies; reuses #354's ranges and #352's profile |
| Accuracy | Measured: fixes the colon and short-paper rows today; the two gaps are named and testable |
| Team familiarity | Same code, same flags, same versioning plan |

**Pros:** one mechanism, already reviewed in part; the experiment shows exactly
what is left. **Cons:** waits on #353 to #355 merging in order.

### B. A separate document-parts module (this audit's first draft)

**Pros:** none over A. **Cons:** a second splitter beside #354's, two sets of
ranges for evidence to agree with. Withdrawn once #354 was read.

### C. Only widen today's heading regex on main

**Pros:** small. **Cons:** still blind to letters and title blocks, still cuts
the paper on an early heading, and #354 already replaces it.

### D. A trained classifier, or asking teachers to paste only the body

**Cons:** no data to train or check a classifier (rule 2); uploads and
Collections answers bypass the paste box, and teachers paste whole documents.

## Trade-off analysis

A is cheaper than any alternative because the work is mostly done, and the
experiment turns "is it done" into a number per row. The length mismatch
(#334) is still the largest false-alarm source measured, larger than any
document part, so it comes first in the order of work.

## Consequences

- Easier: an honest student's bibliography or cover letter no longer raises a
  flag; the teacher can see and correct what was read; the citation profile is
  a new, plain fact about the paper.
- Harder: preprocessing has a second stage to test; stored baselines need a
  re-split; the evidence pages gain a part view.
- To revisit: whether a student's letters should ever be compared with their
  own earlier letters; whether part rules hold on real pilot papers (the shadow
  log decides); the measurement fixes in W2, each of which moves scores and
  needs its own TermSim and G9 diff before enablement.

## Action items (in order of measured harm)

**W0, small fixes (PR #326, done 2026-11-18):**
1. [x] Writing State: the automatic past-paper opening no longer scrolls the
   page; on phones the page flows instead of two hidden inner scroll panes.
2. [x] Overview greeting carries the first name or ends with a full stop.
3. [x] Student My Voice says the page is not open to students during the
   pilot when that is the server's reason. (Collections does not link student
   Original pages in the pilot, so there was no link to hide.)
4. [x] "Aa Text" button: a compact chip on phones, clear of the safe area,
   with room at the foot of the page.
5. [x] Writing State says when a "Ready" baseline is only the student's own
   uploads.
6. [x] My Work footer contrast (3.4:1 to above 4.5:1).
7. [x] Stale docs: STATUS header and open-PR table, ADR-013's fixed finding
   and packet note, VERIFICATION_AND_BLOCKERS' known-red lines.
   (The nav pill strip already fades at its edge on phones; not a bug.)

**W1, false alarms on honest papers:**
1. [ ] Review and merge PR #334 (length-matched baseline).
2. [ ] Merge the stack in order: #353, #352, #354, #355.
3. [ ] On top of #354: markdown and numbered source headings; cover letters as a
   matter kind; the experiment as a regression test (every "+part" variant
   within 0.01 of plain with the splitter on).
4. [ ] Paper profile lists what was set aside, with a "count as prose" control.

**W2, measurement fixes not in #354 (each flagged, byte-identical off, versioned through #355):** citation double
count; footnote-marker pattern; apostrophe-aware tokenizer; authority and hedge
lists; docx footnotes and pdf running heads; F = 0 features out of teacher-facing
lists and the "AI marker" wording out of the narrative; card text rewritten
from the code.

**W3, one product:** shared shell (top bar, brand, account menu, type, palette)
for Original and Collections; the essentials pattern on Overview, Students and
Submissions; plain habit names everywhere; decorative animation paused when
hidden and off under reduced motion; tap targets of 44px on phones; axe on
every page in CI.

**W4, pilot readiness:** PR #353 (memory) and PR #325 (invites, resets) after
review; stored analysis results (Task 12) so placeholders become data;
decisions on the alpha-only settings; owner items (hosting, email, backups,
legal pages, acceptance run, first teacher, private repository).
