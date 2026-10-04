"""
tests/adversarial/test_generators_mechanical.py — MechanicalObfuscation
(Task 14).

Covers `validation.adversarial.generators.MechanicalObfuscation`, the
deterministic, non-LLM "dumbing down" text transform approximating the
manual-obfuscation findings of Brennan/Afroz/Greenstadt (2012) §4.5:
shorter sentences, fewer syllables/shorter words, thinner adjectives and
adverbs, lower readability.

FIXTURE_PARAGRAPH is real multi-sentence prose (5 sentences) with several
coordinating conjunctions joining independent clauses ("and", "but") and
a generous supply of adjectives/adverbs and known-simplifiable connector
words ("however", "therefore", "furthermore", "utilized", ...), so the
transform has real material to exercise all three mechanical steps
(sentence splitting, adjective/adverb thinning, word swapping).
"""

from __future__ import annotations

import re

from validation.adversarial.generators import MechanicalObfuscation, _load_nlp

FIXTURE_PARAGRAPH = (
    "The professor carefully reviewed the lengthy dissertation, and he "
    "noted several significant inconsistencies throughout the argument. "
    "The student had worked diligently on the project, but the results "
    "were ultimately disappointing and frustrating. Furthermore, the "
    "committee raised numerous concerns regarding the methodology, and "
    "they requested substantial revisions before the next submission. "
    "The advisor therefore recommended additional research, and she "
    "suggested consulting several authoritative sources. Consequently, "
    "the student utilized a more rigorous approach, and the final draft "
    "demonstrated considerably improved clarity."
)


def _sentences(text: str) -> list[str]:
    # Simple splitter for measurement purposes only (not the transform's
    # own spaCy-based splitting) — good enough for periods followed by
    # whitespace in this fixture's plain prose.
    parts = re.split(r"(?<=[.!?])\s+", text.strip())
    return [p for p in parts if p]


def _words(text: str) -> list[str]:
    return re.findall(r"[A-Za-z']+", text)


def _mean_words_per_sentence(text: str) -> float:
    sents = _sentences(text)
    counts = [len(_words(s)) for s in sents]
    return sum(counts) / len(counts)


def _mean_word_length(text: str) -> float:
    words = _words(text)
    return sum(len(w) for w in words) / len(words)


def test_output_has_lower_mean_sentence_length():
    obf = MechanicalObfuscation(seed=42)
    out = obf.transform(FIXTURE_PARAGRAPH)
    assert _mean_words_per_sentence(out) < _mean_words_per_sentence(FIXTURE_PARAGRAPH)


def test_output_has_lower_mean_word_length():
    obf = MechanicalObfuscation(seed=42)
    out = obf.transform(FIXTURE_PARAGRAPH)
    assert _mean_word_length(out) < _mean_word_length(FIXTURE_PARAGRAPH)


def test_deterministic_for_fixed_seed():
    a = MechanicalObfuscation(seed=42).transform(FIXTURE_PARAGRAPH)
    b = MechanicalObfuscation(seed=42).transform(FIXTURE_PARAGRAPH)
    assert a == b


def test_different_seeds_can_differ():
    # The seed controls exactly one arbitrary tie-break in this
    # implementation: whether adjective/adverb thinning drops every 2nd
    # or every 3rd token (in length-sorted order) from each clause — see
    # generators.py's module docstring ("Seed usage"). That choice does
    # vary output on a fixture with this many adjectives/adverbs, so this
    # test is meaningful rather than vacuous; it is not a general claim
    # that every seed pair differs.
    a = MechanicalObfuscation(seed=0).transform(FIXTURE_PARAGRAPH)
    b = MechanicalObfuscation(seed=1).transform(FIXTURE_PARAGRAPH)
    assert a != b


def test_output_is_nonempty_and_has_multiple_sentences():
    # Sanity: the splitting step should actually produce more, shorter
    # sentences on a fixture built with several clause-joining
    # conjunctions, not just thin words in place.
    obf = MechanicalObfuscation(seed=42)
    out = obf.transform(FIXTURE_PARAGRAPH)
    assert out
    assert len(_sentences(out)) > len(_sentences(FIXTURE_PARAGRAPH))


# -- Regression: Finding 1 (multi-conjunct sentence-split misselection) ----

# Reproduction from the code review: a 3-way coordination under ONE shared
# head ("seemed" governs both "and"s — "composed" and "looked" are both
# `conj` children of "seemed"), where only the SECOND "and" actually
# introduces a genuine second independent clause ("the jury looked...",
# which has its own subject "jury"). The FIRST "and" pairs with "composed",
# which has no subject of its own and is not an independent clause. Before
# the fix, `_find_split_index` accepted the first "and" as a valid split
# point because it only checked whether the shared head had *any* `conj`
# child with a subject (true, via "looked"), not the SPECIFIC conjunct
# paired with the `cc` token being evaluated — producing the garbled
# "The lawyer seemed. Composed, and the jury looked attentive and."
MULTI_CONJUNCT_SENTENCE = (
    "The lawyer seemed calm and composed, and the jury looked attentive "
    "and interested."
)


def _has_verb(sentence: str) -> bool:
    doc = _load_nlp()(sentence)
    return any(tok.pos_ in ("VERB", "AUX") for tok in doc)


def test_multi_conjunct_split_does_not_produce_garbled_fragment():
    # The specific garbled output the review reproduced must not recur,
    # for any seed (the seed only controls adjective/adverb thinning, not
    # the split point, so this must hold across the board).
    for seed in range(6):
        out = MechanicalObfuscation(seed=seed).transform(MULTI_CONJUNCT_SENTENCE)
        assert "seemed. Composed" not in out, f"seed={seed}: {out!r}"
        assert "and." not in out, f"seed={seed}: {out!r}"


def test_multi_conjunct_split_points_are_genuine_clause_boundaries():
    # Every output sentence must be a genuine clause: it must contain a
    # verb (no mid-word/mid-clause fragment lacking a predicate), and no
    # sentence may end with a bare coordinating conjunction ("and"/"or"/
    # "but" with nothing after it).
    for seed in range(6):
        out = MechanicalObfuscation(seed=seed).transform(MULTI_CONJUNCT_SENTENCE)
        sents = _sentences(out)
        assert len(sents) >= 2, f"seed={seed}: expected a split, got {out!r}"
        for sent in sents:
            assert _has_verb(sent), f"seed={seed}: fragment lacks a verb: {sent!r}"
            stripped = sent.rstrip(".!? ").lower()
            assert not stripped.endswith((" and", " or", " but")), (
                f"seed={seed}: sentence ends with a bare conjunction: {sent!r}"
            )


# -- Regression: Finding 2 (thinning strands a bare coordinating conj) -----

# Reproduction from the code review: "unconvinced" (the second of an
# ADJ-and-ADJ pair, "skeptical and unconvinced") is the longest ADJ token
# in its clause, so it is the first one thinning drops — before the fix,
# that left "and" dangling at the end of the clause: "...remained
# skeptical and."
DANGLING_CONJUNCTION_SENTENCE = "The board remained skeptical and unconvinced."


def test_thinning_does_not_strand_bare_conjunction():
    for seed in range(6):
        out = MechanicalObfuscation(seed=seed).transform(DANGLING_CONJUNCTION_SENTENCE)
        assert "and." not in out, f"seed={seed}: {out!r}"


def test_no_output_sentence_ends_with_a_coordinating_conjunction():
    # Broader sweep across every fixture this module already exercises,
    # not just the minimal reproduction — a thinning-stranded "and"/"or"
    # must never survive to the rendered output regardless of seed.
    for text in (FIXTURE_PARAGRAPH, MULTI_CONJUNCT_SENTENCE, DANGLING_CONJUNCTION_SENTENCE):
        for seed in range(6):
            out = MechanicalObfuscation(seed=seed).transform(text)
            for sent in _sentences(out):
                stripped = sent.rstrip(".!? ").lower()
                assert not stripped.endswith((" and", " or", " but")), (
                    f"seed={seed}: sentence ends with a bare conjunction: {sent!r}"
                )


# -- Regression: Finding 3 (thinning strands a conjunction on its LEADING
#    side — the mirror of Finding 2) -----------------------------------

# Reproduction from the independent re-verification after the Finding-2
# fix landed (commit fb613238): this is the SAME sentence as
# MULTI_CONJUNCT_SENTENCE above, re-used here because it is exactly what
# exposes the leading-conjunct case. "calm" (the only ADJ/ADV token in
# the clause "The lawyer seemed calm and composed") is the sole thinning
# candidate and gets dropped unconditionally (it's the only entry in the
# length-ordered list, so it always lands at ordered-position 0, which is
# always in the drop set) — before the fix, that left "and" stranded
# with nothing meaningful *before* it: "The lawyer seemed and composed."
# Note spaCy tags "composed" here as VERB (a `conj` sibling of "calm"
# under the head "seemed"), not ADJ — the second clause's own pair
# ("attentive and interested") IS a plain ADJ-ADJ coordination, so this
# fixture exercises both shapes at once. Any fix that only recognizes
# ADJ/ADV on both sides of the conjunction would miss the first clause.
LEADING_CONJUNCT_SENTENCE = MULTI_CONJUNCT_SENTENCE


def test_thinning_does_not_strand_leading_conjunction():
    # The exact garbled fragment the re-verification reproduced must not
    # recur: a coordinating conjunction with nothing meaningful before
    # it (a verb immediately followed by "and", with the word that used
    # to sit between them thinned away).
    for seed in range(6):
        out = MechanicalObfuscation(seed=seed).transform(LEADING_CONJUNCT_SENTENCE)
        assert "seemed and composed" not in out, f"seed={seed}: {out!r}"
        assert " and composed" not in out or "calm and composed" in out, (
            f"seed={seed}: 'composed' survived with its coordinate partner "
            f"thinned away: {out!r}"
        )


def test_no_sentence_has_a_conjunction_with_an_empty_slot():
    # General enough to have caught Finding 3 on its own: no rendered
    # sentence may contain a coordinating conjunction ("and"/"or")
    # immediately preceded by a bare verb/aux with nothing coordinate-
    # shaped before the conjunction (i.e. the conjunction's leading slot
    # was emptied by thinning), and every sentence must still have a
    # full predicate (a verb), never a fragment.
    for text in (FIXTURE_PARAGRAPH, MULTI_CONJUNCT_SENTENCE, DANGLING_CONJUNCTION_SENTENCE):
        for seed in range(6):
            out = MechanicalObfuscation(seed=seed).transform(text)
            for sent in _sentences(out):
                assert _has_verb(sent), f"seed={seed}: fragment lacks a verb: {sent!r}"
                doc = _load_nlp()(sent)
                for tok in doc:
                    if tok.pos_ != "CCONJ" or tok.dep_ != "cc":
                        continue
                    # The token immediately before a `cc` conjunction
                    # must not itself be a verb/aux directly abutting it
                    # with nothing coordinate in between — that shape
                    # ("<verb> and <word>") is exactly what Finding 3
                    # produced when the leading conjunct was thinned away.
                    if tok.i == 0:
                        continue
                    prev = doc[tok.i - 1]
                    assert prev.pos_ not in ("VERB", "AUX"), (
                        f"seed={seed}: conjunction directly follows a verb "
                        f"with no coordinate between them: {sent!r}"
                    )
