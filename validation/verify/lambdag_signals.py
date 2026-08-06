"""LambdaG signals for the pan_stack / gutenberg_verify fusion ablations,
computed per partition -- mirrors delta_signals.py's structure and role.

Tags every document in a partition with POSNoise ONCE and reuses the
result for every candidate's reference pool (see
lambdag.build_candidate_grammar_from_sentences's docstring for why: without
this, an n-author partition would re-tag the same ~(n-1) reference
documents once per candidate, an O(n^2) tagging cost for no benefit).
Builds one CandidateGrammar per author -- the expensive, independent step
(seconds to tens of seconds per candidate depending on that author's actual
sentence count, at production settings) -- in a process pool, mirroring
feature_cache.py's ProcessPoolExecutor pattern for the same reason: building
N candidates is embarrassingly parallel, and this codebase already proved
that pattern gives a real wall-clock win (2.8x on 12 cores) without
touching the computation. Reuses each built grammar to score every probe
from every source author -- the full target x source x probe cross-product
pan_stack.py itself uses, not the leaner 1:1 matched-pair design
delta_signals.py/gutenberg_verify_delta.py use, because LambdaG's dominant
cost is per CANDIDATE, not per trial, so the fuller cross-product costs
barely more than the matched design once the grammars exist.

Each candidate's reference pool is capped (``reference_pool_cap``) before
it's handed to a worker. Measured live at n=100 (2026-08-06): with the
uncapped pool, a partition's reference set is the union of the other ~99
authors' baselines (tens of thousands of sentences), rebuilt near-identically
for all 100 tasks and pickled across the process-pool boundary every time --
O(n) payload x n tasks = O(n^2) data movement for the partition, serialized
through the pool's single submission channel. That dominated wall-clock
completely: per-candidate compute stayed in the same few-seconds-to-tens-of-
seconds range measured at n=8, but only ~10 of 100 candidates landed in the
first 10 minutes, on pace for multiple hours. `build_candidate_grammar_from_
sentences` only ever draws `len(candidate_sentences)`-sized random samples
from this pool, `repetitions` times -- it never needs the full union, so
capping it before pickling loses no signal the algorithm was using anyway.
The default (20,000 sentences) is a no-op at every scale validated so far
(observed natural pool sizes at n=8 were ~4,000-5,600), so this is a pure
scalability fix, not a behavior change at previously-measured scales.
"""

from __future__ import annotations

import random
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from typing import Sequence

from validation.attribution.lambdag import (
    build_candidate_grammar_from_sentences,
    lambda_g_score,
    posnoise_sentences,
)


def _build_one(args: tuple) -> tuple[str, object, float]:
    """Top-level (picklable) worker: build one candidate's grammar."""
    target_id, candidate_sentences, reference_sentences, order, repetitions, seed = args
    start = time.perf_counter()
    grammar = build_candidate_grammar_from_sentences(
        candidate_sentences, reference_sentences,
        order=order, repetitions=repetitions, rng=random.Random(seed),
    )
    return target_id, grammar, time.perf_counter() - start


def lambdag_trial_signals(
    partitions: dict[str, Sequence],
    *,
    order: int = 10,
    repetitions: int = 30,
    seed: int = 20260805,
    max_workers: int | None = None,
    reference_pool_cap: int = 20_000,
) -> dict[str, dict[str, dict[str, float]]]:
    """Per-partition LambdaG signals, keyed like
    ``pan_stack.original_trial_signals`` / ``delta_signals.delta_trial_signals``
    so ``combine_trials``-style merges can pick them up.

    Returns ``{partition_name: {trial_id: {"lambdag_score": float}}}``.
    Raw, uncalibrated lambda_G (see lambdag.py's module docstring) -- the
    fusion layer this feeds does the calibration, matching how the other
    raw signals (LUAR cosine, Delta distance) are handled.

    ``reference_pool_cap`` bounds each candidate's reference-sentence pool
    before it's pickled to a worker -- see the module docstring for why this
    is load-bearing at partition sizes beyond the ~10-author scale this was
    first validated at.
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

        # Seeds are drawn sequentially from `rng` BEFORE dispatch, not inside
        # worker processes, so results stay deterministic regardless of which
        # worker finishes which candidate first.
        tasks = []
        for target in authors:
            candidate_sentences = [s for doc in tagged_baselines[target.author_id] for s in doc]
            reference_sentences = [
                s
                for other in authors
                if other.author_id != target.author_id
                for doc in tagged_baselines[other.author_id]
                for s in doc
            ]
            if len(reference_sentences) > reference_pool_cap:
                reference_sentences = rng.sample(reference_sentences, reference_pool_cap)
            tasks.append(
                (target.author_id, candidate_sentences, reference_sentences, order, repetitions, rng.random())
            )

        grammars: dict[str, object] = {}
        completed = 0
        with ProcessPoolExecutor(max_workers=max_workers) as pool:
            futures = {pool.submit(_build_one, task): task[0] for task in tasks}
            for future in as_completed(futures):
                target_id, grammar, build_seconds = future.result()
                grammars[target_id] = grammar
                completed += 1
                print(
                    f"[lambdag] {partition_name}: {completed}/{len(authors)} candidate grammars "
                    f"built ({target_id}: {build_seconds:.1f}s)",
                    file=sys.stderr,
                )

        # Scoring is cheap (no new grammars built) -- stays serial.
        rows: dict[str, dict[str, float]] = {}
        for target in authors:
            grammar = grammars[target.author_id]
            for source in authors:
                for probe_index, probe_sentences in enumerate(tagged_probes[source.author_id]):
                    result = lambda_g_score(probe_sentences, grammar.candidate, grammar.reference)
                    identifier = trial_id(target.author_id, source.author_id, probe_index)
                    rows[identifier] = {"lambdag_score": result.lambda_g}
        output[partition_name] = rows
    return output
