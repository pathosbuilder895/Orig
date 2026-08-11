"""validation/verify/dependency_signals.py -- candidate dependency-parse /
morphosyntactic features for the Phase 5A probe.

No corpus dependency: real spaCy parses of short fixture prose, plus manually
constructed ``Doc`` objects for the degenerate cases (same convention as
test_compression_signals.py, which uses synthetic fixtures only).

These tests are about the EXTRACTOR contract -- determinism, finite values in
declared ranges, and graceful degradation. They deliberately do not assert
anything about how well the features discriminate authors; that is the probe's
job and it has its own pre-registered gate.
"""

from __future__ import annotations

import math

import pytest

spacy = pytest.importorskip("spacy")

from validation.verify.dependency_signals import (  # noqa: E402
    CANDIDATE_CODES,
    CANDIDATE_RANGES,
    dependency_features,
    dependency_features_from_text,
    get_nlp,
)


FIXTURE = (
    "When the council finally met, the chair announced that the proposal, "
    "which had been drafted in haste, would be withdrawn. Several members "
    "objected, and a long argument followed. The secretary, who kept careful "
    "minutes, recorded that nobody had expected such a reversal, although the "
    "warning signs were plain enough. Afterwards they walked home in silence."
)

SECOND_FIXTURE = (
    "He went out. It rained. He came back. Nobody spoke. The fire had gone "
    "cold and the dog slept. He sat down and waited for the noise to stop."
)


@pytest.fixture(scope="module")
def nlp():
    return get_nlp()


def _assert_in_declared_range(values: dict) -> None:
    assert set(values) == set(CANDIDATE_CODES)
    for code in CANDIDATE_CODES:
        value = values[code]
        low, high = CANDIDATE_RANGES[code]
        assert isinstance(value, float), f"{code} is {type(value)}, not float"
        assert math.isfinite(value), f"{code} is not finite: {value}"
        assert low <= value <= high, f"{code}={value} outside declared [{low}, {high}]"


# ── Determinism ──────────────────────────────────────────────────────────────


def test_extraction_is_deterministic_across_repeat_calls(nlp):
    first = dependency_features_from_text(FIXTURE, nlp)
    second = dependency_features_from_text(FIXTURE, nlp)
    assert first == second


def test_extraction_is_deterministic_across_fresh_parses(nlp):
    """A second, independently produced Doc of the same text must agree
    bit-for-bit -- otherwise cached and uncached probe rows would differ."""
    a = dependency_features(nlp(FIXTURE))
    b = dependency_features(nlp(FIXTURE))
    assert a == b


def test_candidate_codes_are_ordered_and_unique():
    assert isinstance(CANDIDATE_CODES, tuple)
    assert len(set(CANDIDATE_CODES)) == len(CANDIDATE_CODES)
    assert set(CANDIDATE_RANGES) == set(CANDIDATE_CODES)


# ── Value ranges on real prose ───────────────────────────────────────────────


def test_all_features_finite_and_in_range_on_fixture(nlp):
    _assert_in_declared_range(dependency_features_from_text(FIXTURE, nlp))


def test_features_differ_between_two_unlike_texts(nlp):
    """Not a discrimination claim -- only that the extractor is not emitting a
    constant, which would make every downstream AUC exactly 0.5 for a reason
    that has nothing to do with authorship."""
    long_clauses = dependency_features_from_text(FIXTURE, nlp)
    short_clauses = dependency_features_from_text(SECOND_FIXTURE, nlp)
    differing = [c for c in CANDIDATE_CODES if long_clauses[c] != short_clauses[c]]
    assert len(differing) >= len(CANDIDATE_CODES) - 2, differing


def test_left_branching_ratio_moves_the_expected_way(nlp):
    """Sanity anchor with a known answer: pre-modified nominals put children
    before their head, a trailing relative clause puts them after."""
    left = dependency_features_from_text(
        "The small bright careful quiet child slept. The large old grey stone wall fell.",
        nlp,
    )["dep_left_branching_ratio"]
    right = dependency_features_from_text(
        "The child slept in a bed that was made of wood that came from a tree "
        "that grew in a field that belonged to a man that nobody knew.",
        nlp,
    )["dep_left_branching_ratio"]
    assert left > right, f"left={left} right={right}"


def test_dependency_distance_mean_is_larger_for_a_long_dependency(nlp):
    near = dependency_features_from_text("The dog barked. The cat slept.", nlp)[
        "dep_distance_mean"
    ]
    far = dependency_features_from_text(
        "The dog that had been sleeping under the broken porch all afternoon "
        "barked.",
        nlp,
    )["dep_distance_mean"]
    assert far > near, f"near={near} far={far}"


# ── Degenerate input ─────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "text",
    ["", "   ", "word", "Hello.", "the the the the the", "!!! ??? ...", "123 456"],
)
def test_degenerate_text_returns_finite_in_range_values(nlp, text):
    _assert_in_declared_range(dependency_features_from_text(text, nlp))


def test_text_with_no_verbs_does_not_crash(nlp):
    values = dependency_features_from_text(
        "A table. A chair. Two lamps and a rug. Red, blue, green.", nlp
    )
    _assert_in_declared_range(values)


def test_empty_text_yields_the_documented_neutral_vector(nlp):
    values = dependency_features_from_text("", nlp)
    for code in CANDIDATE_CODES:
        if code == "dep_subord_coord_ratio":
            assert values[code] == 0.5, "documented neutral for an undefined ratio"
        else:
            assert values[code] == 0.0, f"{code}={values[code]}"


# ── Malformed parses ─────────────────────────────────────────────────────────


def test_parse_with_no_root_does_not_crash_or_hang(nlp):
    """A head structure with no self-heading token (a cycle) is accepted by
    spaCy's Doc constructor. tier5's ``_get_dep_depths`` guards this with a
    ``seen`` set; the candidate extractor must not regress that -- an
    unguarded depth walk recurses forever here."""
    doc = spacy.tokens.Doc(
        nlp.vocab,
        words=["alpha", "beta", "gamma", "delta"],
        heads=[1, 2, 3, 0],
        deps=["nsubj", "dobj", "conj", "amod"],
        pos=["NOUN", "NOUN", "NOUN", "ADJ"],
    )
    assert not any(token.head.i == token.i for token in doc), "fixture must be rootless"
    _assert_in_declared_range(dependency_features(doc))


def test_unparsed_doc_without_sentence_boundaries_does_not_crash(nlp):
    """``Doc.sents`` raises E030 when no component set sentence boundaries.
    The extractor must fall back rather than propagate."""
    doc = spacy.tokens.Doc(nlp.vocab, words=["alpha", "beta", "gamma"])
    with pytest.raises(ValueError):
        list(doc.sents)  # documents why the fallback exists
    _assert_in_declared_range(dependency_features(doc))


def test_single_token_doc(nlp):
    doc = spacy.tokens.Doc(
        nlp.vocab, words=["alpha"], heads=[0], deps=["ROOT"], pos=["NOUN"]
    )
    _assert_in_declared_range(dependency_features(doc))


# ── Specific feature semantics ───────────────────────────────────────────────


def test_entropies_are_zero_when_there_is_only_one_distinct_event(nlp):
    doc = spacy.tokens.Doc(
        nlp.vocab,
        words=["cats", "dogs", "eat"],
        heads=[2, 2, 2],
        deps=["nsubj", "nsubj", "ROOT"],
        pos=["NOUN", "NOUN", "VERB"],
    )
    values = dependency_features(doc)
    assert values["dep_pos_pair_entropy"] == 0.0
    assert values["dep_morph_entropy"] == 0.0


def test_relation_rates_are_per_hundred_word_tokens(nlp):
    """Two nsubj arcs among three word tokens = 66.67 per 100."""
    doc = spacy.tokens.Doc(
        nlp.vocab,
        words=["cats", "dogs", "eat"],
        heads=[2, 2, 2],
        deps=["nsubj", "nsubj", "ROOT"],
        pos=["NOUN", "NOUN", "VERB"],
    )
    assert dependency_features(doc)["dep_nsubj_rate"] == pytest.approx(200 / 3)


def test_punctuation_is_excluded_from_the_rate_denominator(nlp):
    """Punctuation habits are already measured by tier 4; a dependency rate
    whose denominator counts commas would partly re-measure them."""
    doc = spacy.tokens.Doc(
        nlp.vocab,
        words=["cats", ",", "dogs", ",", "eat"],
        heads=[4, 0, 4, 2, 4],
        deps=["nsubj", "punct", "nsubj", "punct", "ROOT"],
        pos=["NOUN", "PUNCT", "NOUN", "PUNCT", "VERB"],
    )
    assert dependency_features(doc)["dep_nsubj_rate"] == pytest.approx(200 / 3)


# ── Probe statistics ─────────────────────────────────────────────────────────
#
# The probe's own helpers, tested here rather than in a second file because
# they exist only to serve this extractor.


def test_ranked_auc_matches_the_repo_reference_implementation():
    """``dependency_probe.ranked_auc`` replaces ``binary_auc.auc`` only because
    the latter materialises a P x N matrix that is 280 MB at probe scale. If
    the two ever disagree the probe's headline number is wrong."""
    import numpy as np

    from validation.verify.binary_auc import auc as reference_auc
    from validation.verify.dependency_probe import ranked_auc

    rng = np.random.default_rng(1729)
    for _ in range(5):
        labels = rng.integers(0, 2, size=400)
        scores = rng.normal(size=400) + labels * 0.4
        assert ranked_auc(labels, scores) == pytest.approx(
            reference_auc(labels, scores), abs=1e-12
        )


def test_ranked_auc_is_half_on_fully_tied_scores():
    import numpy as np

    from validation.verify.dependency_probe import ranked_auc

    labels = np.array([1, 1, 0, 0, 0])
    assert ranked_auc(labels, np.full(5, 0.5)) == pytest.approx(0.5)


def test_icc1_is_high_for_separated_groups_and_zero_for_noise():
    import numpy as np

    from validation.verify.dependency_probe import icc1

    index = np.repeat(np.arange(20), 5)
    separated = np.repeat(np.arange(20, dtype=float), 5) + np.tile(
        [0.0, 0.01, -0.01, 0.02, -0.02], 20
    )
    assert icc1(separated, index) > 0.95

    rng = np.random.default_rng(7)
    assert icc1(rng.normal(size=100), index) < 0.30


def _gate_input(per_code: dict, mutual: dict | None = None) -> dict:
    codes = list(per_code)
    return {
        "features": {
            code: {
                "auc": values[0],
                "icc1": values[1],
                "max_abs_r_existing": values[2],
                "max_abs_r_existing_with": "adjective_rate",
            }
            for code, values in per_code.items()
        },
        "mutual_correlations": {
            a: {b: (mutual or {}).get((a, b), (mutual or {}).get((b, a), 0.0)) for b in codes}
            for a in codes
        },
    }


def test_gate_reports_uninformative_when_every_candidate_clears():
    """The result this probe actually produced. A filter that admits all 14
    candidates has shown no ability to separate them, so under
    validation/README.md's three-valued convention it is uninformative and the
    frozen list Phase 5B would consume must be empty."""
    from validation.verify.dependency_probe import apply_gate

    primary = _gate_input({code: (0.62, 0.55, 0.4) for code in CANDIDATE_CODES})
    gate = apply_gate(primary, None)
    assert gate["verdict"] == "uninformative"
    assert len(gate["gate_output"]) == len(CANDIDATE_CODES)
    assert gate["frozen_list"] == []


def test_gate_passes_and_freezes_when_it_actually_discriminates():
    from validation.verify.dependency_probe import apply_gate

    per_code = {code: (0.40, 0.05, 0.99) for code in CANDIDATE_CODES}
    per_code["dep_conj_rate"] = (0.62, 0.55, 0.40)
    gate = apply_gate(_gate_input(per_code), None)
    assert gate["verdict"] == "pass"
    assert gate["frozen_list"] == ["dep_conj_rate"]


def test_gate_fails_when_nothing_clears():
    from validation.verify.dependency_probe import apply_gate

    gate = apply_gate(_gate_input({code: (0.40, 0.05, 0.99) for code in CANDIDATE_CODES}), None)
    assert gate["verdict"] == "fail"
    assert gate["frozen_list"] == []


def test_gate_drops_the_lower_auc_member_of_a_correlated_pair():
    from validation.verify.dependency_probe import apply_gate

    per_code = {code: (0.40, 0.05, 0.99) for code in CANDIDATE_CODES}
    per_code["dep_conj_rate"] = (0.65, 0.55, 0.40)
    per_code["dep_subord_coord_ratio"] = (0.60, 0.55, 0.40)
    gate = apply_gate(
        _gate_input(per_code, {("dep_conj_rate", "dep_subord_coord_ratio"): -0.94}), None
    )
    assert gate["frozen_list"] == ["dep_conj_rate"]
    assert gate["per_feature"]["dep_subord_coord_ratio"]["dropped_for"] == "dep_conj_rate"


def test_build_pairs_excludes_same_author_same_group_pairs():
    from validation.verify.dependency_probe import ProbeDocument, build_pairs

    documents = [
        ProbeDocument("a", "g1", "0", "x"),
        ProbeDocument("a", "g1", "1", "x"),  # same author, same group -> excluded
        ProbeDocument("a", "g2", "2", "x"),
        ProbeDocument("b", "g1", "3", "x"),
    ]
    left, right, labels = build_pairs(documents)
    pairs = {(int(i), int(j)): int(k) for i, j, k in zip(left, right, labels)}
    assert (0, 1) not in pairs, "same-author same-group pair must be dropped"
    assert pairs[(0, 2)] == 1
    assert pairs[(1, 2)] == 1
    assert pairs[(0, 3)] == 0 and pairs[(1, 3)] == 0 and pairs[(2, 3)] == 0
    assert len(pairs) == 5
