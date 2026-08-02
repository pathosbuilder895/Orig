# Provenance — 2026-08-01 length-stability run (committed clean caches)

Re-run of the length-stability study against the **committed** clean
`_full_work_cache.txt` files (this branch, after "Truncate back-matter
before writing the full-work cache"), replacing the reader-side
workaround documented in the earlier 2026-08-01 run
(see `COMPARISON_vs_2026-06-30.md` in this directory, imported to main
from `claude/elated-ptolemy-338039`).

Invocation (same pool and defaults as that run):

    python -m validation.stability.run \
        --only augustine,boethius,chesterton,edwards,james,kempis,mill,newman

## Reproduction check vs the workaround run

The two runs' inputs are word-identical, and the outputs match exactly
for every feature except one:

- `length_stability.csv`: identical apart from the
  `thematic_progression_score` row.
- `per_tier_summary.csv`: identical apart from tier 2's means
  (1.8235 → 1.7831 stability ratio; flag unchanged, HOLDS).
- All conclusions in the elated-ptolemy `COMPARISON_vs_2026-06-30.md`
  stand unchanged for this report.

The single differing feature is **not** a corpus effect:
`thematic_progression_score` (`original/features/tier2.py`) slices
`list(set(...))` positionally into theme/rheme halves, so its value
depends on `PYTHONHASHSEED` and varies between interpreter runs on
identical text (verified: 0.045 / 0.038 / 0.068 on the same input under
seeds 1/2/3). Treat that feature's Fisher values as jitter in both
reports until the feature is made order-deterministic.
