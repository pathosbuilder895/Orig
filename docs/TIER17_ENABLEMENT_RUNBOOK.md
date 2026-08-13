# Tier 17 (behavioral biometrics) — Enablement Runbook

**Standing rule (pilot master plan):** collect and report keystroke data,
but do NOT enable the `behavioral` feature group until the readiness gate
passes on real pilot data **and** a human approves the flip. This runbook
exists so that when both happen, enabling is a rehearsed ~30-minute act,
not a research project. The rehearsal itself is
`tests/test_tier17_rehearsal.py` — it enables the group inside a
restore-guaranteed fixture and proves the full extract → mask → score
path with the six behavioral dimensions live.

## 1. Go / no-go preconditions

All four, in order:

1. **Readiness gate is READY on real data.**
   `python -m scripts.tier17_report --db "$DATABASE_URL"` (the pilot
   Postgres; the script opens the session read-only). READY means
   >= 20 proctored samples with keystroke data, across >= 5 distinct
   students, with non-degenerate (p10 != p90) distributions on >= 4 of
   the 6 features. Never enable on synthetic or demo data — local SQLite
   files are all fixtures.
2. **The rehearsal suite is green:**
   `.venv/bin/python -m pytest tests/test_tier17_rehearsal.py -q`.
3. **The full suite is green** (0 failed) at the commit you'll flip on.
4. **A human has approved**, with the report's markdown attached to the
   approval. Changing `original/constants.py` requires explicit
   permission per CLAUDE.md — that applies here even though the flip
   touches set membership, not feature ordering.

## 2. The flip

One line in `original/constants.py` (search `DISABLED_FEATURE_GROUPS`):
remove `"behavioral"` from the set. Do not touch `"uniformity"` — Tier 18
has its own gates (G2b, G6) and is not covered by this runbook.

## 3. Everything that must move with it

- **The active-dimension story: 97 → 103.** Update, in the same PR:
  - `CLAUDE.md` — the "Feature dimensionality" section (97 active count,
    Tier 17 wording).
  - `MODEL_CARD.md` — the feature-count table (~line 82) and any
    fairness/validation caveats that assumed behavioral off.
  - `README.md` — feature tables mentioning 97/disabled tiers.
- **Retire the rehearsal tripwire.** `tests/test_tier17_rehearsal.py`'s
  fixture asserts `"behavioral" in DISABLED_FEATURE_GROUPS` as a
  precondition; after a deliberate flip, retire the file (its job is
  done) or invert the default-off tests. Grep the suite for other
  assumptions: `grep -rn "behavioral" tests/ | grep -i disabled`.
- **Re-derive calibration.** Action thresholds and measured weights were
  derived with 97 active dimensions.
  `scripts/derive_measured_weights.py` reads `DISABLED_FEATURE_GROUPS`;
  re-run it and `python -m validation.calibration_gate --strict` before
  quoting any post-flip number. Treat pre/post scores as different
  instruments in any longitudinal comparison.
- **Old baselines need no backfill.** Samples stored without keystroke
  data carry 0.5 placeholders at the six positions; the per-profile
  `active_feature_mask` (variance-derived) keeps those dimensions out of
  ρ until a student accumulates real keystroke-bearing sittings. Mixed
  baselines degrade gracefully — that's by design, verified in the
  rehearsal tests.

## 4. Verify after the flip

1. Rehearsal-equivalent smoke on staging: sit one proctored exam, check
   the six features leave 0.5 in the stored vector and the score is sane.
2. Full suite green; calibration gate `--strict` passes.
3. `scripts/tier17_report.py` re-run a week later: distributions should
   remain non-degenerate as volume grows (a collapse back toward
   degenerate suggests capture drift in the exam room — investigate
   before trusting the six features).

## 5. Rollback

Re-add `"behavioral"` to `DISABLED_FEATURE_GROUPS` and redeploy. The six
features return to 0.5/masked immediately; no data migration in either
direction (the raw blobs persist regardless of the flag).

## 6. Known caveats (accepted, documented)

- **Pause threshold:** our `pause_density` counts pauses >= 3 s
  (`original/features/tier17.py`); the writing-process literature's
  standard is 2 s (see
  `docs/research/2026-08-13-typing-biometrics-ranges-brief.md`).
  Changing the threshold changes the feature — do it, if ever, as its own
  validated change, never silently alongside the flip.
- **No published ranges** exist for our exact `burst_ratio`,
  `paste_event_rate`, or `revision_depth` definitions; the readiness
  gate's non-degeneracy rule is the operative check, with the brief's
  numbers as loose sanity bounds only.
- **The readiness report is not per-tenant.** If the pilot ever spans
  tenants with very different exam conditions (e.g., typed vs. dictated
  accommodations), read the per-student counts in the report before
  concluding readiness.
