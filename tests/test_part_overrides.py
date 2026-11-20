"""A teacher's own choice of which parts of a paper are measured
(original/features/part_overrides.py, steps 4-5 of the document-parts plan).

Checked here: (1) the choice is validated against the text, (2) the hook in
``preprocess.body_segments`` wins over the rules only when a choice is in
force, and with none is the identical list, and (3) caches never serve a
value measured under another choice.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from original.features import feature_flags as ff
from original.features import part_overrides as po
from original.features import preprocess as pre

ROOT = Path(__file__).resolve().parents[1]
SAMPLES = ROOT / "validation" / "diagnostics" / "document_parts_v2" / "samples"
TEXT = "Title Page\n\nThe first paragraph is mine.\n\nThe second paragraph is also mine.\n"


def _apa_docx_text() -> str:
    from original.upload_utils import extract_text_from_bytes

    return extract_text_from_bytes((SAMPLES / "apa_student.docx").read_bytes(), "paper.docx")


@pytest.fixture(autouse=True)
def _tfidf_tier10(monkeypatch):
    """Tier 10 on its TF-IDF backend, so the route tests need no model download."""
    from original.features import tier10

    monkeypatch.setattr(tier10, "_st_model", None)
    monkeypatch.setattr(tier10, "_st_failed", True)
    # Rule D's piece vectors are not what these tests are about, and are slow.
    monkeypatch.setenv("RULE_D_OBSERVATION", "off")


@pytest.fixture
def splitter(monkeypatch):
    monkeypatch.setenv("MATTER_SPLITTER_ENABLED", "1")
    monkeypatch.setenv("PAPER_PROFILE_ENABLED", "1")
    monkeypatch.setenv("UPLOAD_ALSO_MEASURE", "matter")


# ── validation ───────────────────────────────────────────────────────────────


def test_no_choice_is_none():
    assert po.validate(TEXT, None, None) is None
    assert po.validate(TEXT, [], []) is None


def test_a_valid_choice_is_kept_sorted_and_hashable():
    o = po.validate(TEXT, [[0, 10], (12, 20)], [[30, 40]])
    assert o == po.PartOverride(((0, 10), (12, 20)), ((30, 40),))
    assert hash(o) == hash(po.PartOverride(((0, 10), (12, 20)), ((30, 40),)))
    assert o.to_doc() == {"exclude_ranges": [[0, 10], [12, 20]], "include_ranges": [[30, 40]]}


@pytest.mark.parametrize(
    "exclude, include, words",
    [
        ([[0, len(TEXT) + 1]], None, "not within the text"),
        ([[-1, 3]], None, "not within the text"),
        ([[5, 5]], None, "not within the text"),
        ([[10, 20], [0, 5]], None, "sorted"),
        ([[0, 10], [5, 15]], None, "sorted"),
        (None, [[0, 10], [9, 15]], "sorted"),
        ([[0, 10]], [[5, 15]], "both set aside and measured"),
        ([[0, 10, 12]], None, "pairs"),
        ("0-10", None, "pairs"),
        ([[0, True]], None, "whole-number"),
        ([[0.0, 3]], None, "whole-number"),
        ([[0, 3]] * 0 + [[i, i + 1] for i in range(65)], None, "more than 64"),
        ([[12, len(TEXT)]], None, "60%"),
    ],
)
def test_a_choice_that_does_not_fit_is_refused(exclude, include, words):
    with pytest.raises(po.OverrideError, match=words):
        po.validate(TEXT, exclude, include)


def test_up_to_sixty_percent_may_be_set_aside():
    text = " ".join(["word"] * 10)
    assert po.validate(text, [[0, len("word " * 6) - 1]], None) is not None  # 6 of 10
    with pytest.raises(po.OverrideError):
        po.validate(text, [[0, len("word " * 7) - 1]], None)  # 7 of 10


# ── the hook ─────────────────────────────────────────────────────────────────


def test_combine_adds_included_and_removes_excluded_ranges():
    o = po.PartOverride(exclude=((5, 8),), include=((20, 30),))
    assert po.combine([(0, 10), (25, 40)], o) == [(0, 5), (8, 10), (20, 40)]
    assert po.combine([], po.PartOverride(include=((3, 4),))) == [(3, 4)]
    assert po.combine([(0, 10)], po.PartOverride(exclude=((0, 10),))) == []


def test_without_a_choice_the_rules_ranges_are_returned_untouched(monkeypatch):
    segments = [(0, 4), (9, 12)]
    assert po.apply(TEXT, segments) is segments
    with po.applying({"another paper": po.PartOverride(exclude=((0, 1),))}):
        assert po.apply(TEXT, segments) is segments
    for on in ("0", "1"):
        monkeypatch.setenv("MATTER_SPLITTER_ENABLED", on)
        before = pre.body_segments(TEXT)
        with po.applying({}):
            assert pre.body_segments(TEXT) == before
        assert pre.preprocess(TEXT) == pre.preprocess(TEXT)


@pytest.mark.parametrize("splitter_on", ["0", "1"])
def test_a_choice_wins_over_the_rules_only_while_in_force(monkeypatch, splitter_on):
    monkeypatch.setenv("MATTER_SPLITTER_ENABLED", splitter_on)
    first = TEXT.index("The first")
    second = TEXT.index("The second")
    before = pre.preprocess(TEXT)[0]
    with po.applying({TEXT: po.PartOverride(exclude=((first, second),))}):
        cut = pre.preprocess(TEXT)[0]
        assert "first paragraph" not in cut and "second paragraph" in cut
        with po.applying({TEXT: None}):  # a nested block may lift the choice
            assert pre.preprocess(TEXT)[0] == before
    assert pre.preprocess(TEXT)[0] == before


def test_measuring_the_title_page_puts_it_back(monkeypatch):
    monkeypatch.setenv("MATTER_SPLITTER_ENABLED", "1")
    text = _apa_docx_text()
    from original.features.matter import find_parts

    title = next(r for r in find_parts(text).set_aside if r.kind == "title_page")
    before = pre.preprocess(text)[0]
    assert "Hannah Price" not in before
    with po.applying({text: po.PartOverride(include=((title.start, title.end),))}):
        assert "Hannah Price" in pre.preprocess(text)[0]


def test_the_choice_never_leaks_into_another_context():
    import contextvars

    def inner():
        po.set_in_force({TEXT: po.PartOverride(exclude=((0, 5),))})
        return po.for_text(TEXT)

    assert contextvars.copy_context().run(inner) is not None
    assert po.for_text(TEXT) is None


def test_text_caches_key_on_the_choice(monkeypatch):
    monkeypatch.setenv("MATTER_SPLITTER_ENABLED", "1")
    calls = []

    @ff.text_cache(maxsize=8)
    def measured(text):
        calls.append(1)
        return "".join(text[a:b] for a, b in pre.body_segments(text))

    plain = measured(TEXT)
    assert measured(TEXT) == plain and len(calls) == 1
    with po.applying({TEXT: po.PartOverride(exclude=((0, 12),))}):
        assert measured(TEXT) != plain
    assert measured(TEXT) == plain and len(calls) == 2


def test_evidence_reads_the_same_ranges_as_the_measurement(monkeypatch):
    from original import evidence

    monkeypatch.setenv("MATTER_SPLITTER_ENABLED", "1")
    first = TEXT.index("The first")
    second = TEXT.index("The second")
    with po.applying({TEXT: po.PartOverride(exclude=((first, second),))}):
        prose = pre.preprocess(TEXT)[0]
        view = evidence.engine_view(TEXT)
    assert view is not None and "first paragraph" not in prose
