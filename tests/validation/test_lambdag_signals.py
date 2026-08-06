"""validation/verify/lambdag_signals.py -- LambdaG as a pan_stack fusion
signal. Small order/repetitions and tiny synthetic authors to keep this
fast; production settings (order=10, repetitions=30) are exercised by the
validation ablation, not this unit test."""

from __future__ import annotations

from dataclasses import dataclass

from validation.verify.lambdag_signals import lambdag_trial_signals


@dataclass(frozen=True)
class _Author:
    author_id: str
    baselines: tuple
    probes: tuple


def _author(author_id: str, seed_sentence: str) -> _Author:
    # Real sentence-ending punctuation between repeats, so spaCy's
    # sentencizer gives a predictable, comparable sentence count across
    # authors/documents -- a run-on with no internal periods segments
    # unpredictably and can leave one author's reference pool smaller than
    # another candidate's sentence count.
    baselines = tuple(
        f"{seed_sentence}, document {i}. {seed_sentence} again. {seed_sentence} once more."
        for i in range(3)
    )
    probes = tuple(f"{seed_sentence}, probe {i}. {seed_sentence} indeed." for i in range(2))
    return _Author(author_id, baselines, probes)


def test_lambdag_trial_signals_covers_every_combine_trials_identifier():
    from validation.verify.lambdag_signals import lambdag_trial_signals as _run
    from validation.verify.pan_stack import trial_id

    authors = [
        _author("alpha", "The committee reviewed the plan carefully"),
        _author("beta", "Cats are popular household pets everywhere"),
        _author("gamma", "The engine requires regular seasonal maintenance"),
    ]
    partitions = {"locked": authors}
    signals = _run(partitions, order=3, repetitions=3)["locked"]

    expected_ids = {
        trial_id(target.author_id, source.author_id, probe_index)
        for target in authors
        for source in authors
        for probe_index in range(len(source.probes))
    }
    assert set(signals) == expected_ids
    for row in signals.values():
        assert set(row) == {"lambdag_score"}
        assert isinstance(row["lambdag_score"], float)


def test_lambdag_trial_signals_respects_a_reference_pool_cap():
    """reference_pool_cap bounds the per-task pickled payload at large
    partition sizes (see lambdag_signals.py's module docstring) -- forcing
    a cap well below the natural pool here exercises the rng.sample path
    and confirms it doesn't break coverage or crash on a tiny cap."""
    from validation.verify.pan_stack import trial_id

    authors = [
        _author("alpha", "The committee reviewed the plan carefully"),
        _author("beta", "Cats are popular household pets everywhere"),
        _author("gamma", "The engine requires regular seasonal maintenance"),
    ]
    # Each author contributes 9 candidate sentences (3 docs x 3 sentences),
    # so the natural 2-other-author reference pool is 18 sentences -- a cap
    # of 12 sits strictly between the two, forcing rng.sample to fire while
    # staying above build_candidate_grammar_from_sentences's own
    # reference->=candidate size floor.
    signals = lambdag_trial_signals(
        {"locked": authors}, order=3, repetitions=3, reference_pool_cap=12
    )["locked"]

    expected_ids = {
        trial_id(target.author_id, source.author_id, probe_index)
        for target in authors
        for source in authors
        for probe_index in range(len(source.probes))
    }
    assert set(signals) == expected_ids


def test_lambdag_favors_genuine_over_impostor_on_average():
    """The claim this signal exists to test: a probe scored against its OWN
    author's grammar should tend to read higher (more candidate-favoring)
    than the same probe scored against a different author's grammar."""
    from validation.verify.pan_stack import trial_id

    authors = [
        _author("alpha", "The committee reviewed the formal proposal thoroughly"),
        _author("beta", "Cats enjoy sunny windowsills during warm afternoons"),
        _author("gamma", "The engine requires regular maintenance every winter"),
    ]
    signals = lambdag_trial_signals({"locked": authors}, order=3, repetitions=5)["locked"]

    genuine_scores = []
    impostor_scores = []
    for author in authors:
        for probe_index in range(len(author.probes)):
            genuine_scores.append(
                signals[trial_id(author.author_id, author.author_id, probe_index)]["lambdag_score"]
            )
            for other in authors:
                if other.author_id == author.author_id:
                    continue
                impostor_scores.append(
                    signals[trial_id(other.author_id, author.author_id, probe_index)]["lambdag_score"]
                )

    assert sum(genuine_scores) / len(genuine_scores) > sum(impostor_scores) / len(impostor_scores)
