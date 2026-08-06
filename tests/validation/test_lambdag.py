"""validation/attribution/lambdag.py -- grammar-based likelihood-ratio
verification (Nini et al. 2026). Requires spaCy (already a hard dependency
elsewhere in this codebase, e.g. original/features/tier5.py)."""

from __future__ import annotations

import random

import pytest

from validation.attribution.lambdag import (
    NGramLM,
    build_candidate_grammar,
    compute_lambda_g,
    lambda_g_score,
    posnoise_sentences,
)


def test_posnoise_matches_the_papers_own_worked_example():
    """Nini et al. 2026's own POSNoise example:
    "If they actually censor anything is another question." ->
    "If they [ADV] [VERB] anything is another [NOUN]."
    Every one of the 7 non-punctuation tokens should get the same
    keep-literal-vs-mask-to-POS decision under this module's spaCy-POS
    approximation, including "anything," which POSNoise's own published
    whitelist (Table 6) explicitly lists as a retained pronoun."""
    sentences = posnoise_sentences("If they actually censor anything is another question.")
    assert len(sentences) == 1
    tokens = sentences[0]

    assert tokens[0] == "if"        # SCONJ -- kept literal
    assert tokens[1] == "they"      # PRON -- kept literal
    assert tokens[2] == "ADV"       # "actually" -- masked to POS
    assert tokens[3] == "VERB"      # "censor" -- masked to POS
    assert tokens[4] == "anything"  # PRON -- kept literal (POSNoise's own whitelist agrees)
    assert tokens[5] == "is"        # AUX -- kept literal
    assert tokens[6] == "another"   # DET -- kept literal
    assert tokens[7] == "NOUN"      # "question" -- masked to POS
    assert tokens[8] == "."         # PUNCT -- kept literal


def _repeat_sentences(pattern: tuple[str, ...], n: int) -> list[tuple[str, ...]]:
    return [pattern for _ in range(n)]


def test_ngram_lm_never_returns_zero_probability_for_an_unseen_token():
    """The k=0 uniform-interpolation term (Eq. 16) exists specifically so a
    token never seen anywhere in training still gets a defined, nonzero
    probability -- infinite perplexity would otherwise poison any document
    containing a single novel token."""
    sentences = _repeat_sentences(("a", "b", "a", "b"), 20)
    model = NGramLM(sentences, order=2)
    logprob = model.token_logprob("totally-unseen-token", context=("a",))
    assert logprob > float("-inf")
    assert logprob < 0  # a valid log-probability: P < 1


def test_ngram_lm_prefers_a_seen_pattern_over_an_unseen_one():
    sentences = _repeat_sentences(("a", "b", "a", "b", "a", "b"), 30)
    model = NGramLM(sentences, order=2)
    seen = model.token_logprob("b", context=("a",))
    unseen = model.token_logprob("z", context=("a",))
    assert seen > unseen


def test_ngram_lm_rejects_empty_training_data():
    with pytest.raises(ValueError, match="at least one sentence"):
        NGramLM([], order=2)


def test_lambda_g_score_requires_at_least_one_reference_model():
    sentences = _repeat_sentences(("a", "b"), 5)
    model = NGramLM(sentences, order=2)
    with pytest.raises(ValueError, match="at least one reference model"):
        lambda_g_score(sentences, model, [])


def test_lambda_g_favors_a_probe_matching_the_candidates_own_pattern():
    """The actual claim this module exists to test: a probe drawn from the
    SAME grammatical pattern as the candidate should score higher (more
    positive lambda_G, favoring the candidate) than a probe drawn from a
    reference-population pattern -- mirroring the discriminative-power test
    already used for Burrows' Delta (validation/verify/delta_signals.py's
    test suite)."""
    rng = random.Random(1729)
    candidate_pattern = ("the", "NOUN", "VERB", "the", "NOUN", ".")
    reference_pattern = ("a", "NOUN", "AUX", "ADJ", ".")

    candidate_sentences = _repeat_sentences(candidate_pattern, 25)
    # Reference pool must be a large, DIVERSE population, not just the
    # single reference_pattern repeated -- otherwise a candidate-matching
    # probe would trivially win against a degenerate reference and the test
    # would prove nothing about real discriminative power. Mix in the
    # reference pattern plus scrambled variants for genuine diversity.
    reference_pool = (
        _repeat_sentences(reference_pattern, 30)
        + _repeat_sentences(("a", "NOUN", "AUX", "VERB", "ADJ", "."), 30)
        + _repeat_sentences(("an", "ADJ", "NOUN", "."), 30)
    )

    candidate_model = NGramLM(candidate_sentences, order=3)
    reference_models = [
        NGramLM(rng.sample(reference_pool, len(candidate_sentences)), order=3)
        for _ in range(10)
    ]

    matching_probe = [candidate_pattern]
    mismatched_probe = [reference_pattern]

    matching_result = lambda_g_score(matching_probe, candidate_model, reference_models)
    mismatched_result = lambda_g_score(mismatched_probe, candidate_model, reference_models)

    assert matching_result.lambda_g > mismatched_result.lambda_g
    assert matching_result.lambda_g > 0
    assert mismatched_result.lambda_g < 0


def test_compute_lambda_g_end_to_end_with_real_english_text():
    """Smoke test through the full Algorithm 1 orchestration -- POSNoise,
    candidate + resampled reference Grammar Models, scoring -- on short,
    real English text. Small order/repetitions to keep this fast; the
    production defaults (order=10, repetitions=30) are exercised by the
    validation ablation, not this unit test."""
    candidate_texts = [
        "The committee reviewed the proposal carefully. "
        "Members raised several concerns about the timeline. "
        "The chair proposed a revised schedule for next month.",
        "The board discussed the annual budget in detail. "
        "Several members questioned the projected expenses. "
        "A subcommittee was formed to study the matter further.",
    ]
    reference_pool = [
        "Cats are popular pets around the world. "
        "They require regular feeding and occasional grooming. "
        "Many owners enjoy their independent nature.",
        "The weather turned cold overnight. "
        "Snow began falling across the northern region. "
        "Residents were advised to stay indoors.",
        "The recipe calls for fresh basil and garlic. "
        "Cooks should simmer the sauce for twenty minutes. "
        "Serve the dish while it is still warm.",
    ]
    probe = "The panel evaluated the submission thoroughly. Staff noted a few issues with the plan."

    result = compute_lambda_g(
        probe, candidate_texts, reference_pool, order=3, repetitions=5, rng=random.Random(42)
    )
    assert result.n_tokens > 0
    assert result.n_sentences == 2
    assert result.repetitions == 5
    assert result.order == 3


def test_build_once_score_many_matches_rebuilding_per_probe():
    """build_candidate_grammar + repeated lambda_g_score must give the
    IDENTICAL result to calling compute_lambda_g fresh per probe (same
    rng seeding) -- the whole point of splitting build from score is reuse
    without changing the answer."""
    candidate_texts = [
        "The committee reviewed the proposal carefully. "
        "Members raised several concerns about the timeline.",
    ]
    reference_pool = [
        "Cats are popular pets around the world. They require regular feeding.",
        "The weather turned cold overnight. Snow began falling across the region.",
        "The recipe calls for fresh basil and garlic. Simmer for twenty minutes.",
    ]
    probes = [
        "The panel evaluated the submission thoroughly.",
        "Staff noted a few issues with the plan.",
    ]

    grammar = build_candidate_grammar(
        candidate_texts, reference_pool, order=3, repetitions=4, rng=random.Random(7)
    )
    reused_results = [
        lambda_g_score(posnoise_sentences(p), grammar.candidate, grammar.reference)
        for p in probes
    ]
    fresh_results = [
        compute_lambda_g(p, candidate_texts, reference_pool, order=3, repetitions=4, rng=random.Random(7))
        for p in probes
    ]

    for reused, fresh in zip(reused_results, fresh_results):
        assert reused.lambda_g == pytest.approx(fresh.lambda_g)
        assert reused.n_tokens == fresh.n_tokens


def test_compute_lambda_g_rejects_a_reference_pool_smaller_than_the_candidate():
    with pytest.raises(ValueError, match="fewer than"):
        compute_lambda_g(
            "A probe sentence here.",
            ["One candidate sentence. Another candidate sentence. A third one."],
            ["Only one reference sentence."],
            order=2,
            repetitions=2,
        )
