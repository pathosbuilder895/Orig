"""LambdaG signals for the pan_stack / gutenberg_verify fusion ablations,
computed per partition -- mirrors delta_signals.py's structure and role.

Tags every document in a partition with POSNoise ONCE and reuses the
result for every candidate's reference pool (see
lambdag.build_candidate_grammar_from_sentences's docstring for why: without
this, an n-author partition would re-tag the same ~(n-1) reference
documents once per candidate, an O(n^2) tagging cost for no benefit).
Builds one CandidateGrammar per author (the expensive step: ~19s/candidate
at production settings on 2500-word documents) and reuses it to score every
probe from every source author in the partition -- the full target x
source x probe cross-product, matching pan_stack.py's own trial
construction, not the leaner 1:1 matched-pair design delta_signals.py and
gutenberg_verify_delta.py use, because LambdaG's dominant cost is per
CANDIDATE, not per trial, so the fuller cross-product costs barely more
than the matched design once the grammars are built.
"""

from __future__ import annotations

import random
import sys
import time
from typing import Sequence

from validation.attribution.lambdag import (
    build_candidate_grammar_from_sentences,
    lambda_g_score,
    posnoise_sentences,
)


def lambdag_trial_signals(
    partitions: dict[str, Sequence],
    *,
    order: int = 10,
    repetitions: int = 30,
    seed: int = 20260805,
) -> dict[str, dict[str, dict[str, float]]]:
    """Per-partition LambdaG signals, keyed like
    ``pan_stack.original_trial_signals`` / ``delta_signals.delta_trial_signals``
    so ``combine_trials``-style merges can pick them up.

    Returns ``{partition_name: {trial_id: {"lambdag_score": float}}}``.
    Raw, uncalibrated lambda_G (see lambdag.py's module docstring) -- the
    fusion layer this feeds does the calibration, matching how the other
    raw signals (LUAR cosine, Delta distance) are handled.
    """
    from validation.verify.pan_stack import trial_id

    rng = random.Random(seed)
    output: dict[str, dict[str, dict[str, float]]] = {}
    for partition_name, authors in partitions.items():
        print(f"[lambdag] {partition_name}: tagging {len(authors)} authors' documents...", file=sys.stderr)
        tagged_baselines = {
            author.author_id: [posnoise_sentences(t) for t in author.baselines]
            for author in authors
        }
        tagged_probes = {
            author.author_id: [posnoise_sentences(t) for t in author.probes]
            for author in authors
        }

        rows: dict[str, dict[str, float]] = {}
        for i, target in enumerate(authors):
            candidate_sentences = [s for doc in tagged_baselines[target.author_id] for s in doc]
            reference_sentences = [
                s
                for other in authors
                if other.author_id != target.author_id
                for doc in tagged_baselines[other.author_id]
                for s in doc
            ]
            # Per-candidate cost varies a lot with a real author's actual
            # sentence count/length (not just word count -- an author who
            # writes long, low-punctuation sentences produces far more
            # n-gram instances per sentence than a choppy, short-sentence
            # writer at the same word count), so a fixed-time estimate
            # from one measured candidate does not reliably predict the
            # next one. Timing every candidate makes that variance visible
            # instead of leaving progress a silent black box.
            candidate_start = time.perf_counter()
            grammar = build_candidate_grammar_from_sentences(
                candidate_sentences,
                reference_sentences,
                order=order,
                repetitions=repetitions,
                rng=random.Random(rng.random()),
            )
            build_seconds = time.perf_counter() - candidate_start
            for source in authors:
                for probe_index, probe_sentences in enumerate(tagged_probes[source.author_id]):
                    result = lambda_g_score(probe_sentences, grammar.candidate, grammar.reference)
                    identifier = trial_id(target.author_id, source.author_id, probe_index)
                    rows[identifier] = {"lambdag_score": result.lambda_g}
            print(
                f"[lambdag] {partition_name}: {i + 1}/{len(authors)} candidate grammars built "
                f"({target.author_id}: {build_seconds:.1f}s, "
                f"{len(candidate_sentences)} candidate / {len(reference_sentences)} reference sentences)",
                file=sys.stderr,
            )
        output[partition_name] = rows
    return output
