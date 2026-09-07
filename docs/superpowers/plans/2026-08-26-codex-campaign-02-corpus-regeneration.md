# Plan 02 — Corpora: regenerate what's missing, deepen what's thin, close corpus-shaped debt

> **For agentic workers (Codex):** Goal-oriented brief. Goals C1–C3 are strictly ordered
> (each needs the previous); C4–C11 are independent of each other and can run in
> parallel worktrees. Prerequisite from Plan 01: the `.gitignore` rules for
> `validation/genre_crossgenre_2026-08/` artifacts (commit `88de2d93`) must be in your
> branch before C1, or you risk committing copyrighted text.

**Goal:** Every gate that is currently `uninformative` for *corpus* reasons (G7, G-P3,
genre-invariant criterion 3, G3's Wilson straddle) gets the data it needs and returns a
real verdict, and the corpus layer's known blind spots (sermons, 2-works-per-author
topic estimation, nondeterminism) are closed or explicitly measured.

**Why now:** Three shipped-but-dark mechanisms (`TOPIC_VARIANCE_INFLATION`,
`CHARACTERISTIC_WEIGHTS`, `GENRE_INVARIANT_WEIGHTS_ENABLED`) are all blocked on the
same uncommitted corpus. It is regenerable in ~15 minutes of compute from committed
scripts. Nothing else in the campaign produces more verdicts per unit work.

**Architecture:** All work in `validation/` + `docs/`. The corpus itself is never
committed (copyright); the *scripts, manifests, reports, and verdicts* are. Where a
goal produces numbers destined for MODEL_CARD.md or a CLAUDE.md flag row, updating
those docs is part of the goal.

## Global constraints

Same as Plan 01 (venv absolute path; 11–12 min full suite; postgres marker suite if
persistence is touched; coverage margin ~1.6 pt; failure witness for every new gate;
`--strict` before quoting; `git rm` not `rm`; no pushes to main). Plus, specific to
this plan:

- **NEVER commit** `validation/genre_crossgenre_2026-08/{raw,clean}/`, `chunks.json`,
  `vectors.npy`, `vectors_meta.json`. The Lewis/Chesterton editions are in copyright in
  US/UK (Lewis is Canadian-PD only). Verify `.gitignore` covers them before generating.
- **Benchmark trap:** `score()` no longer reads `os.environ`. Any harness you write or
  reuse must build a `ScoringConfig` explicitly (`ScoringConfig.from_env()` or
  constructed) — `validation/calibration.py::run_calibration()` calls `score()` with no
  config and will silently measure flag-off behavior for any env flag.
- **Determinism:** run every measurement with `PYTHONHASHSEED=0` exported (see C9) and
  record the seed in the report JSON.
- Public-domain sourcing only for anything you *do* commit (Gutenberg / CCEL / archive.org
  scans of pre-1929 US editions), with a per-document provenance row in the corpus
  manifest, matching the pattern in `validation/genre_2026-08/corpus_manifest.json`.

---

## C1. Regenerate the cross-genre corpus locally

Directory `validation/genre_crossgenre_2026-08/` holds 12 scripts and no data. The
regeneration path documented in `validation/README.md:118-129`:

1. `clean_corpus.py` fetches the MANIFEST URLs → `raw/`, `clean/`.
2. `extract_vectors.py` → `chunks.json`, `vectors.npy`, `vectors_meta.json`
   (~10 min, 560 chunks).

Hard requirements the gate itself enforces (do not work around them):
- **`chunks.json` must survive** the regeneration — G7's topic distance is computed
  from TEXT; `vectors_meta.json` carries none. The cached `vectors.npy` alone cannot
  make the inflation mechanism fire.
- Chunk coverage must span the genuine and impostor sides **equally**, or G7 refuses
  the run (partial coverage widens only one side's sigma and biases both action legs
  toward a pass).

**Acceptance:** both files exist locally; `git status` shows **no** corpus artifacts as
untracked-and-committable (ignore rules working);
`.venv/bin/python -m validation.calibration_gate` now reports G7 as something other
than "corpus missing".

## C2. Run G7 to real verdicts, both hold-out directions

G7 (`validation/calibration_gate.py:1015`; bars `_G7_FP_BAR=0.25`,
`_G7_CATCH_BAR=0.29`, `_G7_AUC_BAR=0.60`) has **never returned a verdict**. Run it with
`TOPIC_VARIANCE_INFLATION=on` (shadow structurally cannot produce a G7 pass — the gate
downgrades a shadow "pass" to uninformative by design), in **both** leave-one-genre-out
hold-out directions.

Traps the gate already catches (expect them, don't fight them): under `on`, a run where
`inflation_fire_rate == 0` is `uninformative`, not a pass; typicality withholds its band
while inflation is active.

Record: verdicts + all three legs' numbers in the committed battery report and in the
`TOPIC_VARIANCE_INFLATION` row of CLAUDE.md. **Do not change the flag default.** A G7
pass here is necessary but not sufficient for `on` — the pilot shadow soak (Plan 03)
still owns the "does `d` ever exceed 0.25 on real submissions" question.

**Acceptance:** committed report with G7 verdicts for both directions; flag row updated;
default untouched.

## C3. Run G-P3 for `CHARACTERISTIC_WEIGHTS`

`original/quantum/scoring.py:594` records: "Not validated: gate G-P3 requires the
leave-one-genre-out corpus … and has not been run." With C1's corpus in place, run
G-P3. Compare `on` vs `off` on the corpus's genuine-cross-genre and impostor legs at
the same matched-severity bars G7 uses. Register/confirm the failure witness in
`gate_contracts.py` if G-P3 is being added to the battery rather than run ad hoc.

Record the verdict in MODEL_CARD.md and the `CHARACTERISTIC_WEIGHTS` CLAUDE.md row.
Flag default stays `off` regardless of outcome (the dispersion soak on real traffic —
Plan 03 — is the other necessary leg).

**Acceptance:** committed G-P3 result; docs updated; default untouched.

## C4. Measure the genre-invariant tier set (criterion 3) — the last blocker on `GENRE_INVARIANT_WEIGHTS_ENABLED`

The classifier blocker is resolved (G8 passes); the remaining blocker is that the
attenuated tier set `{2, 3, 9, 10}` (`context/weighting.py:105`,
`ATTENUATE_FACTOR=0.6`) **has never been measured by anything**. The pre-registered
bar is criterion 3 of `docs/research/2026-08-13-genre-resolver-fix-scoping.md`: the
gate fires in a **majority of leave-one-genre-out folds** and, where it fires, improves
the genuine-vs-impostor separation rather than degrading it.

Also measure the specific suspicion recorded in `weighting.py:94-104`: tier 2 contains
`lexical_chain_density`, one of the most topic-*invariant* features available —
attenuating tier 2 wholesale may discard signal. Report per-feature topic-invariance
rankings alongside the tier-level result so a follow-up can propose a feature-level
(not tier-level) attenuation set if the tier set fails.

A negative result here is a *valid, publishable outcome*: it would retire the flag's
"blocked" status into "measured and rejected," which is strictly better than dark code.

**Acceptance:** committed study report under `validation/genre_crossgenre_2026-08/`
(scripts + JSON results only, no corpus text); criterion-3 verdict recorded in the
research doc's addendum and in the CLAUDE.md flag row.

## C5. Build the public-domain analogue corpus (Chesterton + Newman)

Follow-up named in `docs/superpowers/specs/2026-07-27-genre-shift-harness-design.md`:
the cross-genre study is not externally reproducible because Lewis can't be committed.
Build a same-shape corpus from fully-PD authors — Chesterton (pre-1929 works) as the
style-varied anchor and Newman as the impostor pool is the spec's suggestion; verify
publication dates per edition. Same chunking and manifest format as
`validation/genre_2026-08/`. **This one IS committed.** Re-run C2/C4's harnesses on it
and report whether conclusions transfer (they may not — that divergence is itself a
finding about the Lewis corpus's idiosyncrasy).

**Acceptance:** committed corpus + manifest + provenance; harness runs green on a fresh
checkout with no network; transfer report committed.

## C6. Sermon corpus + the taxonomy gap

Seminary traffic will contain sermons; the v2 resolver carries no `sermon` label and
does not reliably abstain on them (7 of 11 out-of-taxonomy docs; 3 Edwards sermons
labeled `scholarly_essay`, 1 Kempis devotional `narrative_prose`). This is flagged as
"the first thing to look for in the shadow soak" — give the soak something to compare
against:

1. Build a committed PD sermon corpus: Edwards, Whitefield, Wesley, Spurgeon, Moody
   are all safely PD; aim for ≥6 authors × ≥5 sermons so leave-one-author-out is
   possible (the original reason `sermon` was dropped was a single-author class).
2. Measure v2's behavior on it: abstention rate, label distribution, and — critically —
   what the **downstream consumers do** with the labels it does emit (tier-16 muting,
   T8/T13 anchors fire on `sermon`∈ the anchor set via `state.py:435-436`; a sermon
   labeled `scholarly_essay` gets anchors anyway, which may be why the mislabel is
   score-benign — measure, don't assume).
3. Decide and document one of: (a) train a `sermon` class into a
   `genre_model_v2.json` via the existing `validation/genre_2026-08/` training path,
   with G8 re-run including the new class; (b) abstention-hardening (threshold change)
   so sermons reliably read `unknown`; or (c) measured do-nothing, if step 2 shows
   mislabels are score-neutral. Any model artifact change re-runs G8 and updates the
   loader's fail-closed expectations.

**Acceptance:** committed corpus; committed measurement report; a written decision in
the genre spec's addendum; if (a), new artifact + G8 re-run committed.

## C7. Deepen `public_authors` so G3 and the floors stop biting

Current state: 11 authors, only 9 eligible — `douglass` and `thoreau` carry 1 baseline
doc each against the 3-doc attribution floor — and G3's top-1 attribution (0.727 raw,
bar 0.70) is **uninformative at n=22** because the Wilson interval straddles the bar.

Add PD baseline documents for douglass and thoreau (both have ample PD corpora) to
clear the 3-doc floor, and add held-out essays across authors until the Wilson lower
bound at the observed rate clears 0.70 (at ~0.73 observed you need n≳150 for a
0.70 lower bound — check the exact interval math in the gate; if that n is
impractical, grow what's practical and let the report show the shrinking interval
honestly). Respect `ATTRIBUTION_MIN_WORDS=300` — do **not** raise it to 500; that
decision is already made (it would drop all of kempis's 393–499-word docs).

This also serves G1/G6's per-entity depth problem (conformal floor needs N≥33 / N≥49
per entity) — add depth where PD sources allow, and note per-entity N in the manifest.

**Acceptance:** all 11 authors eligible; G3 informative (or interval visibly narrowed
with the arithmetic shown); corpus manifest provenance complete; battery re-run
committed.

## C8. Restore the PAN benchmark cache and re-pre-register the NCD arm

`.benchmark_cache/pan/2020` is absent (G-P1, G-P2-secondary, G-P5a all need it).
Restore via `scripts/fetch_benchmark_data.py --pan`.

Then the delicate one: the compression-channel study
(`docs/research/COMPRESSION_CHANNEL_FINDINGS_2026-08-10.md`) found the **registered**
arm failed (1 of 3 bars) while an **unregistered** NCD variant cleared all three — and
correctly refused to cite it. If the NCD arm is worth pursuing, write a fresh
pre-registration (bars, corpus split, locked hold-out that nobody has read) as a doc
in `docs/research/`, get human sign-off on the registration **before** running, then
run once and commit whatever comes out. Do not touch the locked split while writing
the registration.

**Acceptance:** cache restored + reproduction of the committed G-P1 numbers; a
pre-registration doc exists with an explicit "awaiting human sign-off" or, post
sign-off, a single committed run.

## C9. Kill the pipeline nondeterminism (PYTHONHASHSEED)

The committed short-regime report cannot be reproduced: two identical runs differ on
120/122 honest scores (max |Δ| 0.119, AUC 0.862 vs 0.866) unless `PYTHONHASHSEED=0`.
The fix was declared "tracked separately" and **no tracking artifact exists**. Close it:

1. Find the hash-order dependence. Prime suspects: `set`/`dict` iteration feeding
   feature extraction or corpus assembly ordering. Bisect by fixing the seed at
   different pipeline stages until the diff disappears; the diff surface (120/122 docs,
   small deltas) smells like ordering in TF-IDF vocabulary or chunk assembly.
2. Fix it at the source (sort before iterate) so results are seed-independent, or —
   if the source is a third-party structure — export `PYTHONHASHSEED=0` inside every
   validation entrypoint (`calibration_gate`, benchmark runners) and assert it at
   startup so a bare run fails loud rather than differs silently.
3. Re-run the short-regime report once deterministic and commit alongside the old one
   with a note; do not overwrite history.

**Acceptance:** two back-to-back full runs of the affected harness are byte-identical;
a test guards the entrypoint assertion or the sorted iteration.

## C10. Exercise `distort_corpus.py`

`validation/genre_crossgenre_2026-08/distort_corpus.py` is committed and has never run
against the real corpus. After C1, run it; verify chunk counts, genre balance, and that
extraction over distorted prose behaves (no NaN vectors, no measurability violations).
Commit a short run-report (numbers only). This also produces the mechanical-paraphrase
material Plan 04's HYBRID scenario reuses — coordinate the output location with that
plan (`.benchmark_cache/` is the right home; it is not committed).

**Acceptance:** committed run-report; any crashes/pathologies filed as fixes or issues.

## C11. Merge the topic-sensitivity corpus expansion; re-attempt the derivation honestly

Branch `claude/topic-sensitivity-derivation` (2 commits) carries the
`validation/topic_sensitivity_2026-08/` harness and the cross-work manifest expansion
2→4 works × 8 chunks per author — the exact corpus work `TOPIC_SENSITIVITY` (ships
empty) is blocked on. Its own conclusion was "negative result, do not ship a vector."
Land the branch (the corpus expansion has standalone value for C4/C7), then re-run the
derivation at 4 works. If the estimate still cannot support a 109-dim constant, commit
the negative result and record in the CLAUDE.md `TOPIC_VARIANCE_INFLATION` row that
per-feature sensitivity remains uniform **by measurement, not neglect**. If it can,
propose the vector in a doc — populating `constants.py` needs explicit human approval
(NORM_BOUNDS/constants rule).

**Acceptance:** branch content landed; derivation re-run committed either way; flag row
updated to cite the measurement.

---

## Out of scope

- Any live-traffic measurement (abstention rates, topic-distance distributions) → Plan 03.
- The term-simulator's use of these corpora → Plan 04 (it consumes what this plan builds).
