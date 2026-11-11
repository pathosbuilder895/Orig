# Scholarly same-author corpus

Many papers by the same author, so Original can be tested the way it is used:
an author's **past papers** against a **new paper** by the same writer (honest)
or by a different writer (other-writer probe). Two collections, never mixed in
one evaluation:

| collection | OpenAlex fields |
|---|---|
| `humanities` | Arts and Humanities (12) |
| `science` | natural and formal sciences (11, 13, 15, 16, 17, 19, 21-26, 28, 30, 31); no medicine, no social science |

**The repository stores a manifest, a screened candidate list and code. It never
stores paper text.** Texts are fetched into `validation/scholarly/cache/`
(git-ignored; override with `SCHOLARLY_CACHE`).

Sources, licences and rate limits, with the date each was checked:
`docs/research/2026-11-11-scholarly-corpus-sources.md`.

## The rule: screen first, fetch second

An author is **usable** only with **at least 6 usable papers** (4 past + 2
held-out new). A **usable paper** is single-author, English, openly fetchable
under a licence that permits local research use, and has **at least 1,500
words of prose** after removing formulas, tables, references, footnotes and
block quotations. No author is downloaded unless the metadata says they can
plausibly supply a complete test.

1. `screen.py` (metadata only, no full text) keeps authors with **at least 8**
   candidate papers (margin of two over the floor, because some fail cleaning)
   and ranks them by candidate count. Output: `candidates/<collection>.json`,
   committed, so the screen is reviewable before anything is fetched.
2. `fetch.py` walks the ranking from the top. Per author it stops early in both
   directions: **done** once 12 usable papers are in hand, **abandon** the
   moment usable-so-far plus untried candidates cannot reach 6. An abandoned
   author is removed from the manifest entirely and listed, with counts, in
   `manifest/<collection>_dropped.json`. Never counted.
3. `manifest/<collection>.json` holds only usable papers of usable authors.
   `schema.py` refuses a manifest with any author under 6 papers, any paper under
   1,500 words, a licence outside policy, or a partition that is not the hash of
   the author id.
4. `loader.py` turns the manifest plus cache into trials and **refuses an author
   with fewer than 6 usable papers** (`ThinAuthorError`), so a thin author can
   never enter a test silently. Authors that cannot supply the requested cut
   lengths are reported in `TrialSet.skipped`, never dropped quietly.

## Rebuild

```bash
sudo apt-get install poppler-utils            # pdftotext, used by clean.py
export OPENALEX_API_KEY=...                   # free key; needed for cursor paging
.venv/bin/python -m validation.scholarly.screen --collection humanities
.venv/bin/python -m validation.scholarly.screen --collection science
.venv/bin/python -m validation.scholarly.fetch --collection humanities --limit-authors 50   # smoke run
.venv/bin/python -m validation.scholarly.fetch --collection humanities --limit-authors 2000 # scale (resumable)
```

`fetch.py` is resumable (per-paper outcomes in `cache/<collection>/state.jsonl`),
rate limited per host (arXiv: one request per 3 seconds, single connection, per its
API terms), and sends the generic User-Agent `scholarly-corpus-builder/0.1` with no
contact details. Re-running continues where it stopped and rebuilds the manifest.

## Using the corpus

```python
from validation.scholarly.loader import load_trials
ts = load_trials("humanities", "development", n_past=4, n_new=2, past_words=1200, new_words=300)
for t in ts.trials:
    t.baseline   # past papers, cut to past_words      (shape of short_regime Trial)
    t.honest     # held-out new papers by the same author
    t.probes     # other authors' new papers, same length
```

No document is on both sides of a trial: each paper is a past paper or a new
paper, and probes are other authors' papers. Selection and cut points are seeded.

## Partitions

Author-disjoint, fixed at build time by `sha256("scholarly-v1:" + author_id)`:
`development` 40%, `calibration` 30%, `locked_test` 30% (`policy.partition_of`).
A paper's partition is its author's. The hash does not depend on paper counts, so
re-screening cannot move an author.

**The `locked_test` partition is opened once per pre-registered study.**
`load_trials(..., "locked_test")` raises unless `allow_locked_for="<study id>"`
is given, and each opening is appended to `LOCKED_OPENINGS.tsv` (a tracked file,
so it shows up in review). Nothing in this task reads it. `baseline.py` loads
`development` only.

## Licences

Permitted: CC BY, BY-SA, BY-NC, BY-NC-SA, BY-ND, BY-NC-ND, CC0, public domain
(read from OpenAlex's per-location licence), and arXiv items under arXiv's API
terms (stored content may be used "for research purposes"). Papers with no
stated licence, including most author-posted repository copies, are **excluded**,
which costs yield and is deliberate. Only text derived for local research use
is cached; nothing is redistributed.

## Caveats

* Author identity rests on OpenAlex ids with exactly one observed ORCID; this is
  strong but not proof. Authors whose id carries two ORCIDs, whose papers span
  more than 40 years, or whose papers do not share a dominant subfield are
  rejected at screen time.
* Cleaning is geometric and heuristic (`clean.py`): body-size text only, with
  formulas, tables, references, footnotes, headings and block quotes removed.
  It will leave some residue and occasionally drop prose. Sample before trusting.
* Academics are not students; formal academic prose is the register where
  published stylometric methods are weakest. Results here describe the scorer on
  scholarly writing, not on student writing.

## Tests

`tests/test_scholarly_corpus.py` runs without the cache or a network: schema,
partition determinism, the 6-paper floor, early-stop and abandon logic, loader
behaviour on a synthetic fixture.
