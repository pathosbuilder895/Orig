"""features/lexicon_v2.py and features/feature_flags.py (FEATURE_SET=2).

The reworked word-list habits, sentence by sentence: what counts as a hedge,
a modal verb, a confident-statement word and a linking word. Each case names
a mistake the old lists made (``tests/test_lexicon_v2.py::OLD_MISTAKES``) or a
hedge they missed, and the tier functions are checked to switch only when
FEATURE_SET=2.
"""

from __future__ import annotations

import pytest

from original.features import feature_flags as ff
from original.features import lexicon_v2 as lx
from original.features import tier1, tier2, tier3, tier7
from original.features.tier1 import TextDoc

HAS_SPACY = TextDoc("You may go.").spacy_doc is not None
needs_spacy = pytest.mark.skipif(not HAS_SPACY, reason="en_core_web_sm not installed")


def _found(fn, text: str) -> list[str]:
    doc = TextDoc(text)
    return [doc.clean[a:b] for a, b in fn(doc)]


@pytest.fixture
def no_spacy(monkeypatch):
    """The fallback rules, as on a machine without en_core_web_sm."""
    monkeypatch.setattr(TextDoc, "spacy_doc", property(lambda self: None))


# ── Hedges ───────────────────────────────────────────────────────────────────

#: (sentence, hedges counted). The same answer with and without spaCy.
HEDGES = [
    # The month and other false hits of the old list.
    ("The essay was submitted in May 2026.", []),
    ("The novel is about grief.", []),
    ("She is about to leave.", []),
    ("They walked around the lake.", []),
    ("Attention rather than ambition matters.", []),
    ("I would rather stay home.", []),
    ("He would walk to school every day.", []),
    ("May I ask a question?", []),
    ("There is no doubt that he lied.", []),
    ("The ghost appeared on stage.", []),
    ("Students tend toward silence.", []),
    ("They think it is wrong.", []),
    # Real hedges, including ones the old list missed.
    ("You may go now.", ["may"]),
    ("This could be read two ways.", ["could"]),
    ("Perhaps the argument fails.", ["Perhaps"]),
    ("It seems likely that he was wrong.", ["It seems", "likely"]),
    ("To some extent, this is true.", ["To some extent"]),
    ("It is possible that the author erred.", ["It is possible that"]),
    ("I think the claim is weak.", ["think"]),
    ("We suspect the data are noisy.", ["suspect"]),
    ("The data would seem to help.", ["would", "seem"]),
    ("About forty people came.", ["About"]),
    ("It costs around $40.", ["around"]),
    ("About a dozen came.", ["About"]),
    ("It is rather good.", ["rather"]),
    ("Students tend to agree.", ["tend"]),
    ("It appears that the ghost was real.", ["It appears"]),
    ("The ghost appeared to smile.", ["appeared"]),
    ("Arguably, Lewis was right.", ["Arguably"]),
    ("Critics have often described Berry.", ["often"]),
    ("In most cases the rule holds.", ["In most cases"]),
    ("I doubt it.", ["doubt"]),
    ("The results suggest a link.", ["suggest"]),
]


@needs_spacy
@pytest.mark.parametrize(("text", "expected"), HEDGES, ids=[t for t, _ in HEDGES])
def test_hedges_with_spacy(text, expected):
    assert _found(lx.hedge_spans, text) == expected


@pytest.mark.parametrize(("text", "expected"), HEDGES, ids=[t for t, _ in HEDGES])
def test_hedges_without_spacy(no_spacy, text, expected):
    assert _found(lx.hedge_spans, text) == expected


def test_month_in_a_heading_block_is_never_a_hedge():
    """The case that started this: an MLA date merged into sentence one."""
    text = "Jane Doe\nProfessor Hall\nENGL 1101\n17 May 2026\nThe essay begins here."
    assert _found(lx.hedge_spans, text) == []
    assert _found(lx.modal_spans, text) == []


def test_a_word_inside_a_counted_phrase_is_not_counted_again():
    assert _found(lx.hedge_spans, "It is likely that we lose.") == ["It is likely that"]


def test_word_class_vetoes_a_noun(no_spacy):
    class _Tok:
        def __init__(self, idx, tag, pos):
            self.idx, self.tag_, self.pos_ = idx, tag, pos

    text = "The estimate was high, and it was quite low."
    tags = {4: ("NN", "NOUN"), 34: ("RB", "ADV")}
    assert lx._is_hedge(text, 4, 12, "estimate", tags) is False
    assert lx._is_hedge(text, 34, 39, "quite", tags) is True
    assert lx._is_hedge(text, 4, 12, "estimate", None) is True  # untagged fallback
    assert lx._is_hedge(text, 0, 3, "The", tags) is False


def test_untagged_offset_counts_as_not_a_modal():
    assert lx._is_hedge("You may go.", 4, 7, "may", {}) is False


# ── Helpers ──────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("text", "i", "expected"),
    [
        ("Perhaps.", 0, True),
        ('He left." Then we ate.', 10, True),
        ("He left.\u201d Then we ate.", 10, True),
        ("(He left.) Then", 11, True),
        ('"Perhaps," he said.', 1, True),
        ("He left. Then", 9, True),
        ("He left, then", 9, False),
    ],
)
def test_sentence_start(text, i, expected):
    assert lx._at_sentence_start(text, i) is expected


def test_next_and_previous_word_at_the_edges():
    assert lx._next_word("about", 5) == ""
    assert lx._prev_word("about", 0) == ""
    assert lx._next_is_number("about", 5) is False
    assert lx._next_is_number("about a book", 5) is False


def test_month_fallback_rules():
    assert lx._month_like("In May, we met.", 3, 6) is True
    assert lx._month_like("May 2026 was wet.", 0, 3) is True
    assert lx._month_like("May we go?", 0, 3) is False
    assert lx._month_like("It might rain.", 3, 8) is False


# ── Modal verbs ──────────────────────────────────────────────────────────────

MODALS = [
    ("In May, the team met.", []),
    ("The can was empty.", []),
    ("Her will was read aloud.", []),
    ("You can see it.", ["can"]),
    ("They should leave, and they must.", ["should", "must"]),
]


@needs_spacy
@pytest.mark.parametrize(("text", "expected"), MODALS, ids=[t for t, _ in MODALS])
def test_modals_with_spacy(text, expected):
    assert _found(lx.modal_spans, text) == expected


@needs_spacy
def test_a_name_is_not_a_modal_with_spacy():
    assert _found(lx.modal_spans, "Will Smith wrote it.") == []


@pytest.mark.parametrize(("text", "expected"), MODALS, ids=[t for t, _ in MODALS])
def test_modals_without_spacy(no_spacy, text, expected):
    assert _found(lx.modal_spans, text) == expected


def test_modal_fallback_month_and_name(no_spacy):
    assert _found(lx.modal_spans, "May 2026 was wet. We met with Will Smith.") == []
    assert _found(lx.modal_spans, "Can we go? We can't.") == ["Can"]


# ── Confident statements and linking words ───────────────────────────────────


def test_assertions_are_whole_words_counted_once_and_drop_must():
    assert _found(lx.assertion_spans, "It is clearly wrong.") == ["clearly"]
    assert _found(lx.assertion_spans, "We must act; it is unclearly put.") == []
    assert "must" not in lx.ASSERTION_WORDS_V2


TRANSITIONS = [
    ("The second chapter is so long.", []),
    ("Second, the claim fails.", ["Second"]),
    ("He was tired, so he left.", ["so"]),
    ("He was tired, so much so that he left.", []),
    ("So we left.", ["So"]),
    ("The thing that is wrong is obvious.", []),
    ("There is one reason, that is, money.", ["that is"]),
    ("That is, money matters.", ["That is"]),
    ("We ate; then we slept.", ["then"]),
    ("We ate and then slept.", []),
    ("However, we stayed.", ["However"]),
]


@pytest.mark.parametrize(("text", "expected"), TRANSITIONS, ids=[t for t, _ in TRANSITIONS])
def test_transitions(text, expected):
    assert _found(lx.transition_spans, text) == expected


def test_discourse_markers_count_each_marker_once_where_it_links():
    text = "First, we ate. The first course was soup. However, we left; however, late."
    markers = lx.discourse_markers(text)
    assert ("first", "temporal") in markers
    assert sum(1 for m, _ in markers if m == "however") == 1
    spans = lx.first_marker_spans(text, "temporal")
    assert [text[a:b] for a, b in spans] == ["First"]
    assert len(lx.first_marker_spans(text, None)) == len(markers)
    assert lx.discourse_markers("The second chapter is long.") == []


# ── Flags and the tier functions ─────────────────────────────────────────────


@pytest.mark.parametrize(
    ("value", "expected"), [(None, 1), ("1", 1), ("2", 2), (" 2 ", 2), ("3", 1), ("two", 1)]
)
def test_feature_set_parsing(monkeypatch, value, expected):
    if value is None:
        monkeypatch.delenv("FEATURE_SET", raising=False)
    else:
        monkeypatch.setenv("FEATURE_SET", value)
    assert ff.feature_set() == expected
    assert ff.lexicon_v2() is (expected == 2)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (None, False),
        ("0", False),
        ("1", True),
        ("on", True),
        ("TRUE", True),
        ("yes", True),
        ("x", False),
    ],
)
def test_matter_flag_parsing(monkeypatch, value, expected):
    if value is None:
        monkeypatch.delenv("MATTER_SPLITTER_ENABLED", raising=False)
    else:
        monkeypatch.setenv("MATTER_SPLITTER_ENABLED", value)
    assert ff.matter_splitter_enabled() is expected


def test_text_cache_is_keyed_on_the_switches(monkeypatch):
    calls = []

    @ff.text_cache(maxsize=4)
    def f(text: str) -> tuple[str, int]:
        calls.append(text)
        return text, ff.feature_set()

    monkeypatch.delenv("FEATURE_SET", raising=False)
    assert f("a") == ("a", 1) and f("a") == ("a", 1)
    monkeypatch.setenv("FEATURE_SET", "2")
    assert f("a") == ("a", 2)
    assert calls == ["a", "a"]
    assert f.cache_info().misses == 2
    assert f.__wrapped__("b") == ("b", 2)
    f.cache_clear()
    assert f.cache_info().currsize == 0


PAPER = (
    "In May 2026 the committee met. The essay is about grief, rather than hope. "
    "Perhaps the author erred; it seems likely. I think the second chapter is so long. "
    "It is clearly wrong, and it is clearly argued. However, we may never know. "
    "To some extent the claim holds, and we suspect it might hold again. "
    "Maybe the reader will disagree, but the evidence could suggest otherwise."
)


def _values() -> dict[str, float]:
    doc = TextDoc(PAPER)
    return {
        "modal": tier1.modal_verb_ratio(doc),
        "hedge": tier3.hedging_density(doc),
        "assert": tier3.assertion_density(doc),
        "certainty": tier3.epistemic_certainty_ratio(doc),
        "transition": tier2.transition_density(doc),
        "markers": tier2.discourse_marker_density(doc),
        "cluster": tier7.filler_hedge_cluster_rate(doc),
    }


def test_tier_functions_switch_only_under_feature_set_2(monkeypatch):
    monkeypatch.delenv("FEATURE_SET", raising=False)
    old = _values()
    monkeypatch.setenv("FEATURE_SET", "1")
    assert _values() == old
    monkeypatch.setenv("FEATURE_SET", "2")
    new = _values()
    doc = TextDoc(PAPER)
    assert new["hedge"] == pytest.approx(len(lx.hedge_spans(doc)) / doc.word_count * 100)
    assert new["assert"] == pytest.approx(len(lx.assertion_spans(doc)) / doc.word_count * 100)
    assert new["modal"] == pytest.approx(len(lx.modal_spans(doc)) / doc.word_count)
    assert new["transition"] == pytest.approx(len(lx.transition_spans(doc)) / doc.word_count * 100)
    assert 0.0 < new["certainty"] < 1.0
    assert new["cluster"] > 0.0
    assert new["hedge"] != old["hedge"] and new["transition"] != old["transition"]


def test_empty_paper_under_feature_set_2(monkeypatch):
    monkeypatch.setenv("FEATURE_SET", "2")
    doc = TextDoc("")
    assert tier1.modal_verb_ratio(doc) == 0.0
    assert tier2.transition_density(doc) == 0.0
    assert tier3.epistemic_certainty_ratio(doc) == 0.5
    assert tier7.filler_hedge_cluster_rate(doc) == 0.0
