"""The ``para`` measurement (PARAGRAPH_BREAKS_ENABLED; features/paragraphs.py).

A Word-style paste (one newline between paragraph-length lines, no blank
line) is measured as the same text pasted with blank lines; anything else,
and every existing measurement id, is measured exactly as before.
"""

from __future__ import annotations

import numpy as np
import pytest

from original import evidence
from original import measurement as m
from original.features import feature_flags as ff
from original.features import paragraphs as para
from original.features import part_overrides, pdf_reflow
from original.features import preprocess as pp
from original.features.pipeline import feature_vector
from original.quantum import length_match

PARAS = [
    "The question of how a community remembers its founders is never only a question "
    "about the past. It is also a question about what the present wants to be, and about "
    "which of its habits it would rather not examine too closely.",
    "When the town council voted to rename the square, the debate that followed showed how "
    "little agreement there was about what the old name had meant. Some speakers treated "
    "it as a matter of courtesy, others as a matter of justice.",
    "A historian might say that both sides were partly right. The founder had given land for "
    "the school and the chapel, but he had also fenced the common pasture and taken the "
    "best fields for himself, as the parish records plainly show.",
    "What strikes me most is how rarely anyone in the debate quoted those records. People "
    "argued from memory, from family stories and from what they had been told at school, "
    "and the documents themselves stayed in their boxes in the archive.",
    "Perhaps that is the real lesson of the episode. A name on a square is a small thing, "
    "yet it can carry the weight of a whole argument about belonging, provided nobody "
    "looks too hard at the evidence on which the argument rests.",
    "In the end the council kept the old name and added a plaque beside it. The plaque "
    "tells the story of the pasture in two careful sentences, and most people who cross the "
    "square on their way to the market never stop to read it at all.",
]


def blank(paras: list[str]) -> str:
    return "\n\n".join(paras)


def word(paras: list[str]) -> str:
    return "\n".join(paras)


@pytest.fixture
def clean_flags(monkeypatch):
    for name in (
        "FEATURE_SET",
        "MATTER_SPLITTER_ENABLED",
        "PARAGRAPH_BREAKS_ENABLED",
        "UPLOAD_ALSO_MEASURE",
    ):
        monkeypatch.delenv(name, raising=False)
    return monkeypatch


# ── The rule ─────────────────────────────────────────────────────────────────


def test_a_word_paste_becomes_the_blank_line_paste():
    body = word(PARAS)
    assert para.is_word_paste(body)
    assert pdf_reflow.apply_ops(body, para.paragraph_ops(body)) == blank(PARAS)


def test_short_lines_among_paragraphs_become_their_own_paragraphs():
    head = ["Hannah Price", "Dr. Vance", "HIST 210", "14 March 2026", "Names on a Square"]
    body = word(head + PARAS)
    assert pdf_reflow.apply_ops(body, para.paragraph_ops(body)) == blank(head + PARAS)


@pytest.mark.parametrize(
    "ending",
    [".", "?", "!", ".”", ".)", ".”(138)", ".[12]", ".2", ":", ":" + chr(0x2014), "…"],
)
def test_sentence_endings_that_count(ending):
    lines = [p[:-1] + ending for p in PARAS[:3]]
    assert para.is_word_paste(word(lines))


def _wrap(text: str, width: int) -> str:
    out, line = [], ""
    for w in text.split():
        if line and len(line) + 1 + len(w) > width:
            out.append(line)
            line = w
        else:
            line = f"{line} {w}".strip()
    return "\n".join([*out, line])


POEM = """The pasture lay beneath the frost,
The fences ran from hedge to hedge,
And what the common folk had lost
Was written at the record's edge.
No name was carved upon the stone,
No plaque was raised beside the well;
The fields the founder called his own
Were all the story left to tell."""

LIST = """1. Visit the parish archive and request the enclosure records for 1790 to 1810.
2. Compare the names on the award with the names in the baptism register.
3. Note every field that changed hands, with its acreage.
4. Ask the council clerk for the minutes of the renaming debate.
5. Write up the findings in no more than two pages."""


@pytest.mark.parametrize(
    "body",
    [
        pytest.param(blank(PARAS), id="blank-lines"),
        pytest.param(blank(PARAS[:2]) + "\n" + word(PARAS[2:]), id="one-blank-line-anywhere"),
        pytest.param(word(PARAS).replace("\n", "\n \t\n", 1), id="whitespace-only-line"),
        pytest.param(POEM, id="poetry"),
        pytest.param(LIST, id="short-list"),
        pytest.param(_wrap(" ".join(PARAS), 72), id="hard-wrapped-72"),
        pytest.param(_wrap(" ".join(PARAS), 160), id="hard-wrapped-160"),
        pytest.param(" ".join(PARAS), id="one-line"),
        pytest.param(PARAS[0], id="single-paragraph"),
        pytest.param(PARAS[0] + "\n" + LIST + "\n" + POEM, id="mostly-short-lines"),
        pytest.param(word([p.rstrip(".") for p in PARAS]), id="no-sentence-ends"),
        pytest.param(PARAS[0] + "\n" + PARAS[1][:60], id="one-paragraph-line"),
        pytest.param("", id="empty"),
    ],
)
def test_texts_that_are_not_split(body):
    assert not para.is_word_paste(body)
    assert para.paragraph_ops(body) == []


def test_word_share_threshold():
    # Two paragraph-length lines, then enough short lines to hold over a quarter of the words.
    shorts = ["Notes on the square, page one."] * 12
    assert not para.is_word_paste(word(PARAS[:2] + shorts))
    assert para.is_word_paste(word(PARAS[:2] + shorts[:3]))


def test_only_line_breaks_between_two_lines_with_words_are_replaced():
    body = "\n" + word(PARAS[:3]) + "\n"
    ops = para.paragraph_ops(body)
    assert len(ops) == 2 and all(body[a:b] == "\n" and r == "\n\n" for a, b, r in ops)


# ── Measuring ────────────────────────────────────────────────────────────────


def test_para_measures_a_word_paste_as_the_blank_line_paste(clean_flags):
    with ff.measuring("v1"):
        blank_v1 = feature_vector(blank(PARAS))
        word_v1 = feature_vector(word(PARAS))
    with ff.measuring("para"):
        assert np.array_equal(feature_vector(word(PARAS)), blank_v1)
        assert np.array_equal(feature_vector(blank(PARAS)), blank_v1)  # unchanged
    assert not np.array_equal(word_v1, blank_v1)  # the skew this measurement removes
    with ff.measuring("matter+para"):
        para_matter = pp.preprocess(word(PARAS))[0]
    with ff.measuring("matter"):
        assert para_matter == pp.preprocess(blank(PARAS))[0]


@pytest.mark.parametrize("mid", ["v1", "fs2", "matter", "fs2+matter"])
def test_existing_measurements_never_run_the_rule(clean_flags, monkeypatch, mid):
    def boom(_body):
        raise AssertionError("paragraph_ops ran under an existing measurement")

    monkeypatch.setattr(para, "paragraph_ops", boom)
    with ff.measuring(mid):
        assert not ff.paragraph_breaks_enabled()
        for text in (word(PARAS), blank(PARAS), POEM):
            pp.preprocess(text)
            assert evidence.engine_view(text) is not None
            length_match.body_word_count(text)


def test_existing_measurements_measure_a_word_paste_as_before(clean_flags):
    # The default measures the single-newline paste as one paragraph, as it always has.
    with ff.measuring("v1"):
        prose, _ = pp.preprocess(word(PARAS))
    assert prose == word(PARAS)
    with ff.measuring("para"):
        assert pp.preprocess(word(PARAS))[0] == blank(PARAS)


def test_evidence_view_follows_the_measured_text(clean_flags):
    text = word(PARAS)
    with ff.measuring("para"):
        view = evidence.engine_view(text)
    assert view is not None and view.prose.text == blank(PARAS)
    # every character of the measured text maps back into the stored text
    assert all(-1 <= i < len(text) for i in view.prose.origin)
    first_break = view.prose.text.index("\n\n")
    assert text[view.prose.origin[first_break]] == "\n"


def test_length_match_cuts_the_measured_body(clean_flags):
    with ff.measuring("para"):
        assert length_match._body(word(PARAS)) == blank(PARAS)
    with ff.measuring("v1"):
        assert length_match._body(word(PARAS)) == word(PARAS)


# ── Measurement ids ──────────────────────────────────────────────────────────


NEW_IDS = {"para": (1, False), "fs2+para": (2, False), "matter+para": (1, True)}


def test_measurement_table():
    assert ff.MEASUREMENTS == {
        "v1": (1, False, False),
        "fs2": (2, False, False),
        "matter": (1, True, False),
        "fs2+matter": (2, True, False),
        "para": (1, False, True),
        "fs2+para": (2, False, True),
        "matter+para": (1, True, True),
        "fs2+matter+para": (2, True, True),
    }


@pytest.mark.parametrize(
    ("fs", "matter", "para", "expected"),
    [
        ("1", "0", "0", "v1"),
        ("2", "0", "0", "fs2"),
        ("1", "1", "0", "matter"),
        ("2", "1", "0", "fs2+matter"),
        ("1", "0", "1", "para"),
        ("2", "0", "on", "fs2+para"),
        ("1", "1", "true", "matter+para"),
        ("2", "yes", "1", "fs2+matter+para"),
    ],
)
def test_requested_measurement_from_the_three_switches(clean_flags, fs, matter, para, expected):
    clean_flags.setenv("FEATURE_SET", fs)
    clean_flags.setenv("MATTER_SPLITTER_ENABLED", matter)
    clean_flags.setenv("PARAGRAPH_BREAKS_ENABLED", para)
    assert ff.requested_measurement() == expected == ff.current_measurement()
    fs_n, matter_on, para_on = ff.MEASUREMENTS[expected]
    assert ff.feature_set() == fs_n
    assert ff.matter_splitter_enabled() is matter_on
    assert ff.paragraph_breaks_enabled() is para_on


@pytest.mark.parametrize("mid", list(ff.MEASUREMENTS))
def test_measuring_each_id(clean_flags, mid):
    fs_n, matter_on, para_on = ff.MEASUREMENTS[mid]
    with ff.measuring(mid):
        assert ff.current_measurement() == mid
        assert (ff.feature_set(), ff.matter_splitter_enabled()) == (fs_n, matter_on)
        assert ff.paragraph_breaks_enabled() is para_on
        # Existing ids keep the two-part cache key they always had.
        assert ff.cache_key() == ((fs_n, matter_on, True) if para_on else (fs_n, matter_on))
    assert ff.current_measurement() == "v1"


@pytest.mark.parametrize("value", ["0", "off", "", "no", "2"])
def test_off_values(clean_flags, value):
    clean_flags.setenv("PARAGRAPH_BREAKS_ENABLED", value)
    assert not ff.paragraph_breaks_enabled() and ff.requested_measurement() == "v1"


@pytest.mark.parametrize("mid", ["para", "fs2+para", "matter+para", "fs2+matter+para"])
def test_new_ids_are_accepted_wherever_ids_are(clean_flags, mid):
    from scripts.backfill_measurements import CHOICES

    clean_flags.setenv("UPLOAD_ALSO_MEASURE", mid)
    assert ff.upload_also_measure() == mid
    assert mid in CHOICES
    assert m.measurement_of({"measurement": {"used": mid}}) == mid
    assert part_overrides.is_splitter(mid) is ff.MEASUREMENTS[mid][1]


def test_text_cache_keeps_para_apart(clean_flags):
    calls = []

    @ff.text_cache(8)
    def measure(text: str) -> str:
        calls.append(ff.current_measurement())
        return pp.preprocess(text)[0]

    with ff.measuring("v1"):
        a = measure(word(PARAS))
    with ff.measuring("para"):
        b = measure(word(PARAS))
    assert calls == ["v1", "para"] and a != b


def test_plan_uses_para_only_when_every_past_paper_has_it(clean_flags):
    from original.constants import FEATURE_DIM
    from original.quantum.state import BaselineSample, StudentState

    def sample(extra):
        return BaselineSample(
            text="x",
            vector=np.zeros(FEATURE_DIM),
            provenance="verified",
            auth_weight=1.0,
            extra_vectors=extra,
        )

    clean_flags.setenv("PARAGRAPH_BREAKS_ENABLED", "1")
    full = StudentState("t:a", samples=[sample({"para": np.ones(FEATURE_DIM)})] * 2)
    assert m.plan_for(full).used == "para"
    mixed = StudentState("t:a", samples=[sample({"para": np.ones(FEATURE_DIM)}), sample(None)])
    plan = m.plan_for(mixed)
    assert plan.used == "v1" and plan.stamp()["requested"] == "para"


# ── Through the score route ──────────────────────────────────────────────────


def _papers() -> list[list[str]]:
    rot = [PARAS[i:] + PARAS[:i] for i in range(4)]
    return [[f"{p} Paper {k} adds this closing remark." for p in r] for k, r in enumerate(rot)]


def test_api_word_paste_reads_as_the_blank_line_paste(live_client, store_reset, clean_flags):
    clean_flags.setenv("PRELIMINARY_SCORE_ENABLED", "0")
    clean_flags.setenv("EVIDENCE_PASSAGES_ENABLED", "0")
    clean_flags.setenv("UPLOAD_ALSO_MEASURE", "para")
    papers = _papers()
    sid = "demo:para_route"
    for i, paras in enumerate(papers[:3]):
        r = live_client.post(
            f"/students/{sid}/baseline",
            json={"text": blank(paras), "provenance": "verified", "assignment": f"p{i}"},
        )
        assert r.status_code == 200, r.text[:300]
    clean_flags.delenv("UPLOAD_ALSO_MEASURE")

    def score(text: str, tag: str) -> dict:
        r = live_client.post(f"/students/{sid}/score", json={"text": text, "submission_id": tag})
        assert r.status_code == 200, r.text[:300]
        return r.json()

    new = papers[3]
    off_blank, off_word = score(blank(new), "a"), score(word(new), "b")
    assert "measurement" not in off_blank and "measurement" not in off_word
    # (On this short synthetic paper the skew happens not to move the rounded score;
    # the feature-level skew is pinned by test_para_measures_a_word_paste_...)
    clean_flags.setenv("PARAGRAPH_BREAKS_ENABLED", "1")
    on_blank, on_word = score(blank(new), "c"), score(word(new), "d")
    assert on_word["measurement"]["used"] == "para"
    assert on_word["authorship"] == on_blank["authorship"]
    # The blank-line paste's past papers carry blank lines, so para measures them as v1 did.
    assert on_blank["authorship"]["deviation_score"] == off_blank["authorship"]["deviation_score"]
