"""How each habit's number is shown to a teacher (display only).

``original/evidence_features.py`` ``display_info`` tells the one shared
formatter (``demo/original/js/evidence-view.js`` ``readable``) whether a
habit's number is a true percentage, a plain unit, a kind, or only a plain
comparison with the past papers. These tests pin the rules that keep that
honest: a percent only for a true proportion, never a percent read from an
engine value that is a calibration position, and no "0 to 1" in any
teacher-facing words. Nothing here touches a measured value.
"""

from __future__ import annotations

import re
from pathlib import Path

from original import evidence as ev
from original.constants import ALL_FEATURE_CODES, NORM_BOUNDS
from original.evidence_features import HIDDEN_CODES, WHOLE_PAPER, display_info, feature_info

ROOT = Path(__file__).resolve().parents[1]

#: The proportions whose NORM_BOUNDS are exactly (0, 1), so the engine's value
#: IS the share (the plan's list, re-derived from the extractors).
TRUE_SHARES_ON_ENGINE = {
    "paragraph_topic_position",
    "adversative_ratio",
    "temporal_ratio",
    "epistemic_certainty_ratio",
    "source_integration_style",
    "counter_argument_ratio",
    "first_person_ratio",
    "that_which_ratio",
    "abbreviation_tendency",
    "latinate_ratio",
    "vowel_sonority_ratio",
    "pronoun_ambiguity_rate",
    "polysyndeton_ratio",
    "source_loyalty_index",
}
_SHARE_UNIT = re.compile(r"share of|per word$|average overlap")


def _measured():
    return [c for c in ALL_FEATURE_CODES if feature_info()[c]["kind"] == "measured"]


def test_every_measured_habit_has_one_display_style():
    styles = {c: display_info(c)["style"] for c in _measured()}
    assert set(styles.values()) <= {"percent", "unit", "category", "compare", "hidden"}
    assert (
        {c for c, s in styles.items() if s == "hidden"}
        == set(HIDDEN_CODES)
        == {"conclusion_strategy_score"}
    )


def test_percent_only_for_a_true_proportion():
    for code in _measured():
        d = display_info(code)
        if d["style"] != "percent":
            continue
        unit = feature_info()[code]["unit"]
        located = ev.LOCATABLE.get(code)
        shares_in_plain = bool(
            (unit and _SHARE_UNIT.search(unit)) or (located and _SHARE_UNIT.search(located.unit))
        )
        # Either the plain value is a share, or the engine value is the share itself.
        assert shares_in_plain or d["engine_is_raw"], code
        if not unit and not located:
            assert d["engine_is_raw"] and NORM_BOUNDS[code] == (0.0, 1.0), code
    for code in TRUE_SHARES_ON_ENGINE:
        assert display_info(code)["style"] == "percent", code
        assert display_info(code)["engine_is_raw"] is True, code


def test_engine_is_raw_exactly_where_the_bounds_are_zero_and_one():
    for code in _measured():
        assert display_info(code)["engine_is_raw"] == (tuple(NORM_BOUNDS[code]) == (0.0, 1.0)), code


def test_count_rates_keep_a_plain_unit_and_scaled_ones_undo_their_own_scaling():
    for code in ("comma_rate", "hedging_density", "mean_sentence_length", "imperative_density"):
        d = display_info(code)
        assert d["style"] == "unit" and d["unit"], code
    # comma splices: per 100 sentences ÷ 30, capped at 1 (features/prosodic.py).
    splice = display_info("comma_splice_rate")
    assert (splice["scale"], splice["cap"], splice["engine_is_raw"]) == (30.0, 1.0, True)
    assert display_info("nominalization_density")["scale"] == 15.0
    assert display_info("chiasmus_rate")["scale"] == 5.0
    # theological register: term rate ÷ 0.15, so per 100 words is × 15 (read from the plain value).
    assert display_info("theological_register_score")["scale"] == 15.0


def test_no_everyday_unit_means_a_plain_comparison():
    for code in (
        "burstiness",
        "char_trigram_entropy",
        "catastrophe_index",
        "article_omission_rate",
    ):
        assert display_info(code)["style"] == "compare", code


def test_whole_paper_habits_say_so_in_plain_words():
    for code, words in WHOLE_PAPER.items():
        assert code not in ev.LOCATABLE, code
        assert words.startswith("This is ") and words.endswith("No single sentence shows it."), code
        assert ev.whole_text_note(code) == words
    assert ev.whole_text_note("imperative_density") == ev.NOT_POINTED_NOTE


def test_no_teacher_facing_string_says_zero_to_one():
    pages = [
        ROOT / "demo" / "original" / name
        for name in ("evidence.html", "packet.html", "writing-state.html")
    ] + [
        ROOT / "demo" / "original" / "js" / n
        for n in ("evidence-view.js", "evidence-cards.js", "feature-data.js")
    ]
    for path in pages:
        text = path.read_text(encoding="utf-8")
        assert not re.search(r"\b0 to 1\b|from 0 to 1", text), path.name
    for words in (
        ev.ENGINE_SCALE_NOTE,
        ev.PLAIN_UNREADABLE_NOTE,
        ev.OWN_SCORE_NOTE,
        ev.ALL_FEATURES_ORDERING,
        ev.PRELIMINARY_NOTE,
        *(feature_info()[c]["unit"] or "" for c in ALL_FEATURE_CODES),
    ):
        assert "0 to 1" not in words, words


def test_the_page_hidden_list_matches_the_server():
    js = (ROOT / "demo" / "original" / "js" / "evidence-view.js").read_text(encoding="utf-8")
    listed = re.search(r"var HIDDEN_CODES = \[([^\]]*)\]", js).group(1)
    assert set(re.findall(r"'([a-z0-9_]+)'", listed)) == set(HIDDEN_CODES)


def test_every_evidence_entry_carries_its_display():
    text = "It rains; we stay. However, the roof leaks. Perhaps it will stop."
    past = [("past paper 1", "The sun shines, and we walk. Then we rest; it is warm.")]
    full = ev.build_all_features(text, past)
    assert len(full) == len(ALL_FEATURE_CODES)
    for entry in full:
        assert entry["display"] == display_info(entry["code"])
    one = ev.build_feature_evidence(
        {"code": "comma_rate", "submission_value": 0.2, "baseline_value": 0.4, "delta": -0.2},
        text,
        past,
        rank=1,
    )
    assert one["display"]["style"] == "unit"
    examples = ev.build_past_paper_examples("comma_rate", past)
    assert all(f["display"] == display_info(f["code"]) for f in examples["features"])
