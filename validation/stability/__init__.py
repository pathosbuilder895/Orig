"""
validation/stability/ — length-stability study for Original's 103 features.

For each feature i ∈ ALL_FEATURE_CODES and each length L ∈ {250, 500,
1000, 2000, 5000}, compute the Fisher discriminant ratio across the
public-author corpus:

    F(i, L) = var(per-author means) / mean(per-author variances) + ε

A feature whose F(500) / F(5000) stays close to 1 keeps its
discriminating power on short inputs. A feature whose ratio collapses
toward zero needs thousands of words to settle.

The study is the measurement layer that informs Phase 2's
LENGTH_WEIGHT_SCHEDULE in original/constants.py — once we know which
features survive at 500 words, we can scale tier weights at inference
time so short submissions lean on stable features.

Math is unchanged. The study only reads feature vectors from
``original.features.pipeline.feature_vector`` — Born-rule scoring, the
density matrix, and the per-tier weights are untouched in this PR.
"""
