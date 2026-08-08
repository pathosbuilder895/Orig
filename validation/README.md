# validation/ — the instrumentation & validation layer

The scoring engine answers questions; this layer makes sure the questions
and answers can't get mixed up. Background: the 2026-07-30 Instrument
Report ("The instruments were broken, not the math") and
`docs/superpowers/specs/2026-07-31-instrumentation-validation-layer-design.md`.

## The rules the layer enforces

1. **Measurability is data** (`measurability.py`). Every feature column has
   a status — `measurable`, `scoring_only` (comparison-shaped, hardwired to
   0.5 outside scoring), `structurally_blank` (constant via a fallback path
   regardless of corpus, e.g. tier 12's `catastrophe_index`), `disabled`
   (tracks `DISABLED_FEATURE_GROUPS` live), or `corpus_limited` (measurable
   in principle but known-blank on a named corpus, e.g. tier 16's citation
   fingerprint on Plato/`public_authors` prose). Precedence is
   disabled > scoring_only > structurally_blank > corpus_limited > measurable.
   `assert_aggregatable(codes, corpus)` raises `MeasurabilityError` on any
   non-measurable column instead of silently averaging it in.
2. **Power before verdicts** (`power.py`). Conformal p-values floor at
   `1/(N+1)` (`conformal_p_floor`); `band_reachable`/`min_docs_for_band` say
   whether a given threshold is arithmetically reachable at a given N, and
   `wilson_interval`/`bar_decidable` answer the same question for a binomial
   rate. Gate verdicts (`GateResult` in `calibration_gate.py`) are
   three-valued — `pass` / `fail` / `uninformative` — and the dataclass
   itself enforces that `passed=True` iff `verdict=="pass"`, so the two
   fields can't drift apart. A gate whose criterion is unreachable at the
   current corpus size downgrades a would-be pass to `uninformative`; a
   genuine failure is never downgraded. **An `uninformative` verdict must
   never be quoted as a pass** — `python -m validation.calibration_gate
   --strict` folds `uninformative` into `fail` for exactly that reason (the
   non-strict default still runs but prints which gates were uninformative,
   so a bare exit code can't hide it).
3. **Reports carry their spec** (`experiment.py`). Every runner builds an
   `ExperimentSpec` (task / git SHA / seed / env lock / corpus composition /
   windowing / features / aggregation / thresholds) and embeds it under an
   `"experiment"` key in its report JSON. `diff_specs()` explains why two
   runs disagree and raises if asked to compare runs with different `task`
   values — those answer different questions and are not comparable.
4. **Corpus floors are policy** (`corpus_policy.py`, `manifest_schema.py`).
   Only the **attribution** floor is actually enforced today, by
   `validation/public_authors/run.py` calling `check_attribution_pool()` at
   load time: **>= 300 words** (`ATTRIBUTION_MIN_WORDS`) **and** >= 3
   baseline documents per candidate (`ATTRIBUTION_MIN_BASELINE_DOCS`); short
   texts are verification-only, never attribution candidates. The
   attribution word floor is 300, matching the declared verification floor
   — not 500. That's a measured decision (2026-07-31): at 500 words, the
   real manifest loses *all three* of author `kempis`'s baseline documents
   (393–499 words each) — the same author an earlier corpus (chunker) fix
   had just repaired. The two constants are kept as separate names so
   attribution can be raised independently once the corpus carries longer
   chunks. A policy violation never aborts a run: `check_attribution_pool()`
   returns a list of `PolicyViolation`s (`short_document` / `thin_baseline`)
   and the caller **excludes** the offending document or author from the
   candidate pool, then re-checks the remaining floors — the run continues
   on whoever is left (see the real example below). The **verification**
   floor (`VERIFICATION_MIN_WORDS=300`, `check_verification_pool()`) is a
   declared constant with no production caller yet — exercised only by
   `tests/test_corpus_policy.py`, not wired into any runner.
   `genre_dominance` is a *separate*
   check on a *different* task: `check_genre_balance()` flags a
   weight-derivation corpus where one genre exceeds 60% of the words, and
   its only caller (`scripts/derive_measured_weights.py`) prints it as an
   advisory to stderr. It excludes nothing and never touches the
   attribution candidate pool. `manifest_schema.py`'s
   `CorpusEntry` carries `genre` and a `Provenance` enum
   (`real_historical` / `synthetic_ai` / `student_pilot`).
5. **Attribution is an ensemble** (`attribution/delta.py`,
   `attribution/ensemble.py`). Three independent engines score the same
   held-out essay: the existing deviation-calibrated scorer, a cosine-delta
   nearest-centroid engine, and a classic Burrows'-Delta (MFW) engine that
   reads raw text directly with no dependency on the feature pipeline. Both
   delta engines z-score against the *candidate pool's* spread, never a
   single author's own baseline spread, so a loose per-author baseline can't
   become an attribution black hole. `ensemble_vote()` attributes on 2-of-3
   agreement and naming the agreeing engines; on a 3-way split it returns
   `None` with `"engines disagree — manual review"` — it never forces a
   top-1 answer.
6. **Gates must be able to fail** (`gate_contracts.py`,
   `tests/test_gate_falsifiability.py`). `GATE_CONTRACTS` registers, per
   gate, what it claims and a concrete input (`failure_witness`) on which it
   must produce `verdict=="fail"`; several gates also register a
   `label_destruction` input that must never pass. The meta-test scans every
   `evaluate_g*` exported by `calibration_gate.py`: an entry must exist, its
   failure witness must actually fail, and any registered label-destruction
   result must not be `"pass"`. A new gate added without a registered
   failure mode fails the suite, not just a review comment.

## Real measured evidence

`validation/benchmarks/2026-07-31/public_authors/report.json` (committed;
`validation/benchmarks/*` is otherwise git-ignored and only specific runs are
added as evidence — see `validation/benchmarks/README.md`) is a real run of
`validation.public_authors.run`, not a hypothetical: 9 eligible authors, 22
held-out essays. Top-1 accuracy: deviation-calibrated 72.7%, cosine-delta
77.3%, MFW-delta 90.9%; the 2-of-3 ensemble covers 95.5% of essays at 81.0%
accuracy on the covered set (see `report.md` in the same directory for the
full per-author and confusion-matrix breakdown; every accuracy there carries
its 95% Wilson interval — at n=22 they are wide, so don't read the row order
as a ranking). Two authors (`douglass`, `thoreau`) were excluded from the
candidate pool for that run — each has only 1 baseline document against the
3-document floor — and the run completed over the remaining 9, exactly the
exclude-not-abort behavior rule 4 describes.

## Running

    # fast unit layer (part of the main suite)
    .venv/bin/python -m pytest tests/ -q

    # gate battery — G1-G7, corpus-driven via the in-process API client.
    # This is a multi-minute run (it LOO-scores whole documents across
    # seminary + public_authors + Plato, plus the G5 permutation-null
    # rerun) — don't run it casually, and use --strict before quoting
    # any number out of it, since the default treats an uninformative
    # gate as non-failing.
    .venv/bin/python -m validation.calibration_gate --strict

    # NOTE on G7 (cross-topic same-author FPR): its corpus
    # (validation/genre_crossgenre_2026-08/) is NOT committed — the Lewis
    # and Chesterton editions are still under copyright — so on a fresh
    # checkout G7 reports UNINFORMATIVE and --strict therefore exits 1.
    # That is the intended behaviour, not a bug: the suite must not read as
    # having covered topic invariance when it could not measure it. To make
    # G7 informative, fetch the texts in that directory's clean_corpus.py
    # MANIFEST and run its extract_vectors.py (~10 min). G7 additionally
    # needs the intermediate chunks.json to survive that step — topic
    # distance is computed from TEXT, and without it the topic-variance
    # inflation under test cannot fire at all, which G7 detects and reports
    # rather than scoring the un-inflated pipeline and calling it a pass.

    # attribution benchmark, three engines side by side — this is what
    # produced the committed report above.
    .venv/bin/python -m validation.public_authors.run

Weights remain HELD: nothing here writes to `original/constants.py`.
