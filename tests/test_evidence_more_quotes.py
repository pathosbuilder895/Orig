"""The habits quoted since 2026-11-26, and the per-part breakdowns.

Each new LOCATABLE habit re-runs its extractor's own rule (the extractor's
own helper function or compiled pattern) on the offset-keeping engine view.
These tests pin, for each one: the located count rebuilds the extractor's
value exactly, every located span is a verbatim slice of the stored text that
the rule itself matches, and a broken count fails closed. The breakdowns
(arc_resolution_score's quarters, vocabulary_introduction_rate's tenths) use
the extractor's own arithmetic and say "too short" below its minimum.
"""

from __future__ import annotations

import re

import pytest

from original import evidence as ev
from original.features import preprocess as pp
from original.features import prosodic, tier2, tier3, tier6
from original.features.tier1 import TextDoc
from original.features.tier7 import vocabulary_introduction_rate

NEW = (
    "paragraph_topic_position",
    "epistemic_certainty_ratio",
    "source_integration_style",
    "counter_argument_ratio",
    "imperative_density",
    "that_which_ratio",
    "abbreviation_tendency",
    "pronoun_ambiguity_rate",
    "comma_splice_rate",
    "polysyndeton_ratio",
    "latinate_ratio",
    "nominalization_density",
)

TEXT = """Consider the parable of the sower. Calvin argues that the seed is the word of God. \
This reading places the emphasis on the hearer's preparation and patient reception.

However, the soil matters too, and the farmer and the seed and the weather all play a part. \
The NT writers, cf. Rom 10, saw the matter differently, though the New Testament itself is plain. \
Remember the rocks, which had no depth. The interpretation which follows is mine.

He was certain, it was clearly a careful argument. Perhaps the scholars and the critics and the \
students disagree. Clearly the explanation that is offered here certainly has limitations. \
The church, the school, the household, each received the message with appreciation.

Although the farmer sowed widely, the harvest was uneven. Note the abundance of the good soil. \
The disciples asked Jesus about it, and he explained the meaning to them in private."""

PAST = """The sermon began quietly. The preacher spoke of mercy and of judgment. \
According to Barth, grace precedes the law. This shows the movement of the whole argument well.

It is a simple story. They listened, and they went home. The meaning which the story carries \
is plain enough for anyone to grasp in a single hearing."""


@pytest.mark.parametrize("code", NEW)
@pytest.mark.parametrize("text", [TEXT, PAST], ids=["paper", "past"])
def test_new_habit_counts_rebuild_the_extractor_value_and_slices_are_exact(code, text):
    spec = ev.LOCATABLE[code]
    doc = TextDoc(pp.preprocess(text)[0])
    reading = ev.read_paper(text, code)
    assert reading.value == spec.value(doc)
    assert reading.places is not None, code
    assert spec.formula(len(reading.places), doc) == pytest.approx(reading.value, abs=1e-12)
    for place in reading.places:
        assert 0 <= place.sentence_start <= place.start < place.end <= len(text)
        assert text[place.start : place.end].strip()


def test_the_fixture_exercises_every_new_habit():
    """Each new habit finds at least one place in the paper, so the slice
    checks below are not vacuous."""
    for code in NEW:
        assert ev.read_paper(TEXT, code).places, code


def _slices(code, text=TEXT):
    return [text[p.start : p.end] for p in ev.read_paper(text, code).places]


def test_each_located_slice_is_what_the_rule_counted():
    doc = TextDoc(pp.preprocess(TEXT)[0])
    # Sentence-level rules: every quoted sentence passes the extractor's own predicate.
    for code, rule in (
        ("imperative_density", tier3._is_imperative),
        ("counter_argument_ratio", tier3._opens_with_contrast),
        ("comma_splice_rate", prosodic._is_comma_splice),
    ):
        got = _slices(code)
        assert got == [s for s in doc.sentences if rule(s)], code
    # Pattern rules: every slice is a full match of the extractor's own pattern.
    for code, pattern, flags in (
        ("that_which_ratio", tier6.THAT_REL_RE, re.IGNORECASE),
        ("polysyndeton_ratio", prosodic._POLY_RE, 0),
        ("nominalization_density", prosodic._NOMINALIZATION_RE, 0),
    ):
        for s in _slices(code):
            assert re.fullmatch(pattern.pattern, s, pattern.flags | flags), (code, s)
    assert all(prosodic._LATINATE_SUFFIXES.search(w.lower()) for w in _slices("latinate_ratio"))
    assert set(_slices("abbreviation_tendency")) <= {"NT", "cf", "Rom"}
    assert [w.lower() for w in _slices("epistemic_certainty_ratio")] == [
        "clearly",
        "clearly",
        "certainly",
    ]
    # Paragraph openers: the first sentence of each paragraph the rule counts.
    firsts = [p[0] for p in doc.paragraphs if tier2._paragraph_fronted(p)]
    assert _slices("paragraph_topic_position") == firsts
    # Citing sentences followed by the writer's own comment.
    citing, commented = tier3._source_integration_parts(doc)
    assert citing and _slices("source_integration_style") == [doc.sentences[i] for i in commented]
    # Flagged pronoun sentences.
    flagged = [doc.sentences[i] for i, f in prosodic._pronoun_ambiguity_flags(doc) if f]
    assert _slices("pronoun_ambiguity_rate") == flagged


def test_a_count_that_disagrees_fails_closed(monkeypatch):
    spec = ev.LOCATABLE["imperative_density"]
    broken = ev.Locatable(
        spec.code, spec.what, spec.unit, lambda view: ("clean", []), spec.formula, spec.value
    )
    monkeypatch.setitem(ev.LOCATABLE, "imperative_density", broken)
    assert ev.read_paper(TEXT, "imperative_density").places is None


def test_no_citations_means_numbers_only_for_source_integration():
    text = "The day was long. We walked home slowly in the rain. Nobody said anything at all."
    reading = ev.read_paper(text, "source_integration_style")
    assert reading.places is None and reading.unplaced == "no_citations"
    one = ev.build_feature_evidence(
        {
            "code": "source_integration_style",
            "submission_value": 0.5,
            "baseline_value": 0.4,
            "delta": 0.1,
        },
        text,
        [("past paper 1", TEXT)],
        rank=1,
    )
    assert one["locatable"] is False and one["note"] == ev.UNPLACED_NOTES["no_citations"]
    # A count that disagrees still gets the mismatch note, never the by-design one.
    assert ev.read_paper(TEXT, "source_integration_style").unplaced is None


def test_new_habits_sit_in_one_family_each():
    codes = [c for group in ev.FAMILIES.values() for c in group]
    assert len(codes) == len(set(codes)) and set(NEW) <= set(codes)


def test_spacy_habits_are_not_quoted():
    # Re-parsing every past paper with spaCy took the pilot past its memory (2026-11-17).
    for code in (
        "adjective_rate",
        "adverb_rate",
        "clause_depth_mean",
        "article_omission_rate",
        "chiasmus_rate",
    ):
        assert code not in ev.LOCATABLE


# ── breakdowns ───────────────────────────────────────────────────────────────


def test_arc_quarters_are_the_extractor_own_split():
    doc = TextDoc(pp.preprocess(TEXT)[0])
    quarters = ev._arc_quarters(doc)
    assert len(quarters) == 4
    # The extractor's score, rebuilt from the same quarters (prosodic._arc_resolution_score).
    lengths = [len(re.findall(r"\b\w+(?:'\w+)?\b", s)) for s in doc.sentences]
    q = len(lengths) // 4
    exact = [lengths[:q], lengths[q : 2 * q], lengths[2 * q : 3 * q], lengths[3 * q :]]
    assert quarters == [round(sum(x) / len(x), 1) for x in exact]
    middle = max(*(sum(x) / len(x) for x in exact[:3]), 1.0)
    rebuilt = 1.0 - min(max(sum(exact[3]) / len(exact[3]) / middle, 0.0), 1.5) / 1.5
    assert prosodic._arc_resolution_score(doc) == pytest.approx(min(max(rebuilt, 0.0), 1.0))


def test_arc_under_eight_sentences_is_too_short_not_a_number():
    short = "One. Two words. Three words here. Four words are here."
    out = ev.build_breakdown("arc_resolution_score", short, [("past paper 1", TEXT)])
    assert out["this_paper"] is None and out["too_short"].startswith("Too short to measure")
    assert out["past_papers"][0]["values"] is not None
    assert prosodic._arc_resolution_score(TextDoc(pp.preprocess(short)[0])) == 0.5


def test_arc_closing_sentences_are_verbatim_and_last():
    out = ev.build_breakdown("arc_resolution_score", TEXT, [("past paper 1", PAST)])
    closing = out["closing"]["this_paper"]
    assert 1 <= len(closing) <= 3
    for q in closing:
        assert q["passage"] == TEXT[q["passage_start"] : q["passage_end"]]
    assert TEXT.rstrip().endswith(closing[-1]["passage"])
    for q in out["closing"]["past_papers"]:
        assert (
            q["paper"] == "past paper 1"
            and q["passage"] == PAST[q["passage_start"] : q["passage_end"]]
        )


def test_vocab_tenths_end_at_all_words_and_rebuild_the_score():
    doc = TextDoc(pp.preprocess(TEXT)[0])
    tenths = ev._vocab_tenths(doc)
    assert len(tenths) == 10 and tenths[-1] == 1.0 and tenths == sorted(tenths)
    assert ev._vocab_tenths(TextDoc("too few words here")) is None
    assert vocabulary_introduction_rate(doc) != 0.5


def test_breakdowns_ride_on_the_full_list_only_for_their_habits():
    full = ev.build_all_features(TEXT, [("past paper 1", PAST)])
    with_breakdown = sorted(f["code"] for f in full if "breakdown" in f)
    assert with_breakdown == ["arc_resolution_score", "vocabulary_introduction_rate"]
