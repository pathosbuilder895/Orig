# Stacked verification research harness

`fusion.py` combines already-produced expert trial scores without assuming
that they are independent. It uses author-grouped out-of-fold predictions,
regularized logistic calibration, explicit missing-signal indicators, `Cllr`,
and a conservative cause-label abstention rule.

This package is not a production scorer. Supply only base-expert predictions
that were themselves generated without training on the trial's author/work.
Before locked evaluation, call `assert_no_group_overlap(development, locked)`.
See `docs/research/STACKED_AUTHORSHIP_VERIFICATION_PLAN.md` for promotion gates.
