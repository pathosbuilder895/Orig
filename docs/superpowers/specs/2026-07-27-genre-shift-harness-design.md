# Genre-Shift Validation Harness — Design

**Date:** 2026-07-27
**Status:** Approved, not yet implemented
**Owner:** validation

---

## Problem

`validation/public_authors/` tests attribution *across authors* while holding
genre roughly constant. Nothing measures the opposite case: **one author writing
across sharply different genres.**

That gap matters because it is the false-accusation case. A student who writes
three research papers and then a sermon must not be flagged. Original already
carries machinery that claims to handle this — the 8-class genre resolver
(`original/context/resolvers.py:147`), genre-family partial-credit baseline
matching (`GENRE_FAMILIES`, `original/constants.py:895`), and genre-conditional
manifest rules (`original/context/manifest.py:22`, which mutes T16 for
`creative_fiction` and anchors T8/T13 for sermon and academic genres). None of
it is measured.

C. S. Lewis is an unusually clean probe: one author, four radically different
modes, all within a twenty-year span, so era and language drift are controlled.
He also supplies a second axis for free — *The Screwtape Letters* and *Till We
Have Faces* are written in assumed voices, which is a different kind of shift
from genre and deserves separate treatment.

## Goal

A diagnostic harness that hardens the genre machinery. The outputs are numbers
that tell you which feature tiers move under genre shift, so `GENRE_FAMILIES`
and the manifest rules can be tuned against evidence.

This is **not** a marketing artifact and **not** a literary study. It is an
engineering instrument.

## Non-goals

- No changes to anything under `original/`. The harness is read-only with
  respect to product code.
- No new API endpoints.
- No CI job in run one.
- No charts or visualization.
- No fair-use claim about redistributing Lewis. See "Copyright posture".

---

## Copyright posture

Lewis's works are in copyright in the US (*Screwtape* 1942, *Abolition of Man*
1943, *Mere Christianity* 1952, *English Literature in the Sixteenth Century*
1954, *Till We Have Faces* 1956). None enter the public domain before the
2030s. The existing `public_authors` corpus is deliberately public-domain with
committed source URLs so anyone can rebuild it byte-for-byte; a Lewis corpus
cannot work the same way.

**Resolution: commit the derived feature vectors, not the text.**

The 103-dimensional feature vectors are derived measurements, not expressive
content. They are committed. The Lewis excerpt text is supplied locally by the
operator and is gitignored. The manifest records a bibliographic citation
(edition, chapter) for each Lewis sample so the extraction is documented and
repeatable by anyone holding a copy of the book, but no Lewis text and no Lewis
source URLs enter the repository.

This is also better engineering. A regression test that pins numbers is more
useful than one that re-derives them from a network fetch on every run.

---

## Corpus and artifact model

### Two tiers

| tier | path | committed? | contents |
|---|---|---|---|
| text | `validation/genre_shift/corpus/` | no (gitignored) | Lewis excerpts, supplied locally |
| vectors | `validation/genre_shift/vectors/` | yes | `features.npz`, `vectors_manifest.json` |

Public-domain contrast text is **referenced in place** under
`validation/public_authors/corpus/`, not copied.

### Extraction is separate from scoring

`extract.py` requires text. `matrix.py`, `stats.py`, and `report.py` do not.
For each sample, extraction persists:

- the 103-dim normalized feature vector
- the adaptive-weight vector produced by the context pipeline for that text
- the context manifest dict produced for that text
- a sha256 of the source text

Persisting the adaptive weights and manifest at extraction time is what makes
the flags-off / flags-on ablation reproducible from vectors alone. Those two
artifacts are the only things in the scoring path that need text, and capturing
them once removes the dependency permanently.

### Manifest schema

One entry per sample in `validation/genre_shift/manifest.json`:

| field | type | notes |
|---|---|---|
| `sample_id` | str | stable, unique |
| `author_id` | str | `lewis`, `chesterton`, … |
| `work_id` | str | `ohel`, `abolition`, `mere_christianity`, … |
| `genre` | str | a `GENRE_LABELS` value — what `resolve_genre` ideally returns |
| `genre_coarse` | str | the study label; see below |
| `persona` | str | `own` or `assumed` |
| `word_count` | int | |
| `sha256` | str | of the local source text |
| `source` | obj | PD: `{url, chunk_index}`. Lewis: `{citation, chapter}` — no URL |

### Two genre fields, deliberately

The 8-label `GENRE_LABELS` taxonomy has no clean slot for a lecture series or a
literary history, and Screwtape is genuinely both `correspondence` and
`creative_fiction`. Forcing a single label would either distort the study or
silently pick a side.

So the manifest carries both. **`genre_coarse` drives all study math.**
`genre` exists only so the harness can additionally report how often
`resolve_genre` agrees with the hand label — a free secondary diagnostic of the
classifier itself.

`genre_coarse` values: `history`, `lecture`, `talk`, `epistolary_fiction`,
`novel`, `essay`, `apologetics`, `sermon`.

### Lewis corpus shape

| work | `genre` | `genre_coarse` | `persona` |
|---|---|---|---|
| *English Literature in the 16th Century* | `scholarly_essay` | `history` | own |
| *The Abolition of Man* | `scholarly_essay` | `lecture` | own |
| *Mere Christianity* | `sermon` | `talk` | own |
| *The Screwtape Letters* | `correspondence` | `epistolary_fiction` | assumed |
| *Till We Have Faces* | `creative_fiction` | `novel` | assumed |

Chapter-sized excerpts of 2,000–5,000 words, at least 4 per work so every cell
supports a ≥3-sample baseline with one held out. `_chunk_text`
(`validation/public_authors/build_corpus.py:452`) already splits on chapter
headers and is reused directly.

The existing corpus chunks whole works into 11,000–15,000-word parts, so
chapter-sized samples sit comfortably inside what the pipeline handles. The
only hard floors in the pipeline are small — tier10 needs ≥3 usable sentences
for `semantic_field_dispersion` and ≥2 for `semantic_centroid_proximity`.

### Contrast pool

Eight authors from the existing corpus: `chesterton`, `douglass`, `edwards`,
`emerson`, `james`, `mill`, `newman`, `thoreau`.

`augustine`, `boethius`, and `kempis` are **excluded**: those texts are
translations, so their measured style is substantially the translator's.
Including them would inflate the cross-author spread with an artifact.

Contrast samples need `genre_coarse` labels too. Those labels live in
genre_shift's own manifest. `validation/public_authors/manifest.json` is not
edited, so the existing green gate is untouched.

---

## Measurement

### One matrix, three slices

Build a baseline for every `(author_id, genre_coarse)` cell with ≥3 samples.
Score every held-out sample against every baseline. This single pass produces
one deviation matrix; every statistic is a slice of it.

A cell needs ≥3 samples to form a baseline at all, and ≥4 to contribute to
**W**, since leave-one-out must still leave 3 behind.

| slice | definition | meaning |
|---|---|---|
| **W** | same author, same genre (leave-one-out) | noise floor |
| **G** | same author, different genre | genre shift |
| **X** | different author | impostor |

`G` is split into `G_own` (both cells `persona == own`) and `G_persona` (the
cells differ in persona). The two are never pooled.

### Headline statistic

**AUC(G_own vs X)** — how well `deviation_score` alone separates "Lewis in
another genre" from "a different author." Threshold-free, so it does not
inherit whatever the action thresholds are currently tuned to. 1.0 means genre
shift never resembles a different person; 0.5 means the score cannot tell them
apart.

### Binary gates

- **Genre gate:** `p95(G_own) < p05(X)` — the worst own-voice genre shift stays
  below the mildest impostor.
- **Persona gate:** the same comparison with `G_persona` in place of `G_own`.
  Separate statistic, separate threshold, separate pass/fail, so a hard persona
  result neither masks nor blocks the genre finding.

Pooled `X` is the headline. Genre-matched `X` (contrast samples restricted to
the same `genre_coarse`) is reported as a secondary.

For genre-matching only, `talk` and `sermon` count as the same family — Lewis's
broadcast talks and Edwards's sermons are the same coarse mode, and treating
them as distinct would shrink the genre-matched `X` pool to nothing. This
family mapping is local to the harness and does not touch `GENRE_FAMILIES` in
`original/constants.py`.

### Thresholds are calibrated, not guessed

The true values of these statistics are unknown. The harness therefore ships
with both gates defined but in state `calibrating` — computed and printed every
run, never enforced.

Run one is an exploratory run. Gate constants are committed as a **separate,
second change** once real output has been inspected. No threshold constant is
invented in advance.

### Ablation

Every scoring pass runs twice: once with `CONTEXT_MANIFEST_ENABLED=0` and
`ADAPTIVE_WEIGHTS_ENABLED=0`, once with both at `1`. Both arms report their AUC
and separation. Whether the genre machinery earns its complexity is a reported
delta, not a gate.

### Per-tier attribution

For each cross-genre pair, report mean |Δ| per feature tier, ranked descending.

This is the part that does the actual hardening. It names which tiers move
under a `history` → `talk` shift, which is the signal you act on when editing
`GENRE_FAMILIES` or the genre rules in the context manifest.

---

## Module layout

```
validation/genre_shift/
  __init__.py
  manifest.json       # committed — sample metadata, citations, no Lewis text
  corpus/             # GITIGNORED — raw text, supplied locally
  vectors/            # committed — features.npz + vectors_manifest.json
  extract.py          # corpus + manifest → vectors        (needs text)
  matrix.py           # vectors → deviation matrix         (no text)
  stats.py            # matrix → W/G/X, AUC, percentiles, tier deltas
  report.py           # stats → report.json / .md / .csv
  run.py              # CLI
```

### Unit boundaries

| module | input | output | depends on |
|---|---|---|---|
| `extract.py` | manifest + corpus text | `features.npz` | `original.features`, `original.context` |
| `matrix.py` | vectors | `DeviationMatrix` | `original.quantum` only |
| `stats.py` | `DeviationMatrix` | `Stats` | numpy only — no I/O, no `original.*` |
| `report.py` | `Stats` | files on disk | stdlib only |
| `run.py` | CLI args | exit code | the above |

`stats.py` having no I/O and no `original.*` imports is load-bearing: the AUC
and percentile logic becomes unit-testable against synthetic matrices with
known answers. That matters because the corpus is gitignored and CI will never
see it.

### CLI

```bash
python -m validation.genre_shift.extract              # requires local corpus
python -m validation.genre_shift.run                  # vectors → report
python -m validation.genre_shift.run --arm both       # flags off and on
python -m validation.genre_shift.run --report-dir DIR
```

### Deliberate deviation from `public_authors`

`public_authors/run.py` routes every score through the in-memory FastAPI client
on principle. `matrix.py` calls `StudentState` and `score()` directly instead
(`original/quantum/state.py:143`, `original/quantum/scoring.py:443` — neither
takes text).

- **Cost:** the API layer is no longer exercised by this harness.
- **Gain:** scoring needs no text, no database, and no server, which is the
  entire basis of the committed-vectors design.

The math is identical either way — same `score()`, same state builder. The
trade is right for a diagnostic, but it is a real trade and is recorded here
rather than left implicit.

---

## Reporting

Default report directory follows the existing convention:
`validation/benchmarks/<date>/genre_shift/`.

| file | contents |
|---|---|
| `report.json` | full structured result, including `environment` and `skipped_cells` |
| `report.md` | rendered summary: AUC, gate status, per-tier ranking |
| `deviation_matrix.csv` | every sample × every baseline |
| `tier_deltas.csv` | per-genre-pair mean |Δ| by tier |

---

## Error handling

| condition | behaviour |
|---|---|
| cell has <3 samples | skipped with an explicit stderr warning, recorded in `report["skipped_cells"]` — never silently dropped |
| corpus file missing at extract time | hard error naming the file |
| sha256 mismatch, local text vs manifest | hard error — the local excerpt is not what produced the committed vectors |
| scoring raises for one pair | that cell is `NaN`, recorded in `report["errors"]`, the run continues |
| fewer than 2 eligible genres for an author | that author contributes to `X` only; a warning is printed |

---

## Testing

| test | runs in CI? |
|---|---|
| `stats.py` unit tests on synthetic matrices with known AUC and percentiles | yes |
| manifest schema + consistency (every vector row has a manifest entry, and the reverse) | yes |
| smoke test: matrix → stats → report over the committed vectors | yes |
| `extract.py` tests | no — `skipif` corpus absent |

Contributors without the Lewis texts see skips, not failures.

---

## Delivery order

1. `stats.py` plus its unit tests — pure, testable, no corpus needed.
2. Manifest schema, `extract.py`, and the local Lewis corpus.
3. `matrix.py` and `report.py`; commit the extracted vectors.
4. Exploratory run; inspect output.
5. **Separate commit:** gate constants, moved from `calibrating` to enforcing.

Steps 1–4 are one implementation plan. Step 5 depends on data that does not
exist yet and is explicitly deferred.

---

## Follow-ups, not in this scope

- Extract `validation/common/` once `genre_shift` and `public_authors` have
  demonstrated concretely what they share. Building the second consumer first
  and extracting afterward is the right order.
- A CI job wiring the smoke test into the pipeline, once the gates are
  enforcing.
- A public-domain analogue corpus (Chesterton and Newman both span comparable
  modes), which would make the whole study reproducible by outsiders.
