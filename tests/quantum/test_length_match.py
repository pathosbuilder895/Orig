"""Tests for LENGTH_MATCHED_BASELINE: compare a short paper with short pieces.

The fault being repaired: past papers are measured whole, so a 300-word paper
is compared with the mean and spread of 1,200-word papers and reads as a
change of writer. The length-matched state re-measures long past papers in
pieces of the new paper's length and overrides only the comparison reference.

Asserted before anything about whether it helps:

  1. off is byte-identical, whatever state the caller passes;
  2. shadow is byte-identical to off except for the added report-only fields;
  3. the shadow preview equals exactly what "on" produces;
  4. cutting papers never changes what the student's history is counted as.
"""

from __future__ import annotations

import dataclasses

import numpy as np
import pytest

from original.constants import ALL_FEATURE_CODES, FEATURE_DIM, RECENCY_DECAY
from original.quantum.length_match import (
    LENGTH_MATCH_MAX_PIECES,
    LENGTH_MATCH_MIN_WORDS,
    LengthMatchedState,
    build_length_matched_state,
    paper_pieces,
    split_into_pieces,
)
from original.quantum.scoring import (
    ScoringConfig,
    _parse_length_matched_baseline_mode,
    score,
)
from original.quantum.state import BaselineSample, StudentState

_REPORT_FIELDS = {
    "length_match_applied",
    "length_match_mode",
    "length_match_pieces",
    "length_match_deviation_preview",
    "length_match_action_preview",
}


def _text(n_words: int, tag: str = "w") -> str:
    return " ".join(f"{tag}{i}" for i in range(n_words))


def _state(seed=5, n=4, words=1200, student_id="t1:len") -> StudentState:
    """Past papers of ``words`` words whose whole-paper vectors sit close
    together, as long papers' do."""
    rng = np.random.default_rng(seed)
    centre = np.clip(rng.normal(0.5, 0.1, FEATURE_DIM), 0.1, 0.9)
    state = StudentState(student_id=student_id)
    for i in range(n):
        state.add_sample(
            BaselineSample(
                text=_text(words, f"p{i}_"),
                vector=np.clip(centre + rng.normal(0, 0.02, FEATURE_DIM), 0.0, 1.0),
                provenance="proctored",
                auth_weight=1.0,
                assignment=f"a{i}",
            )
        )
    return state


def _vectoriser(seed=11, shift=0.06, noise=0.09):
    """Stands in for feature extraction on a short piece: noisier than a whole
    paper and shifted, as length-dependent measurements are. Deterministic
    per text."""
    centre = np.clip(np.random.default_rng(5).normal(0.5, 0.1, FEATURE_DIM), 0.1, 0.9)
    calls = []

    def vectorise(text: str) -> np.ndarray:
        calls.append(text)
        rng = np.random.default_rng(abs(hash(text)) % (2**32) + seed)
        return np.clip(centre + shift + rng.normal(0, noise, FEATURE_DIM), 0.0, 1.0)

    vectorise.calls = calls
    return vectorise


def _matched(state, n_words=300, **kw):
    return build_length_matched_state(state, n_words, _vectoriser(), **kw)


def _submission(seed=99):
    centre = np.clip(np.random.default_rng(5).normal(0.5, 0.1, FEATURE_DIM), 0.1, 0.9)
    rng = np.random.default_rng(seed)
    return np.clip(centre + 0.06 + rng.normal(0, 0.09, FEATURE_DIM), 0.0, 1.0)


def _fd(sub):
    return {c: float(sub[i]) for i, c in enumerate(ALL_FEATURE_CODES)}


def _score(state, sub, mode="off", matched=None, **kw):
    cfg = kw.pop("config", None) or ScoringConfig(length_matched_baseline=mode)
    return score(state, sub, _fd(sub), scoring_config=cfg, length_matched_state=matched, **kw)


def _strip(result):
    d = dataclasses.asdict(result)
    for f in _REPORT_FIELDS:
        d.pop(f)
    return d


def _same(a, b):
    np.testing.assert_equal(a, b)


# ── Cutting ──────────────────────────────────────────────────────────────────


def test_pieces_cover_the_text_and_are_never_shorter_than_the_paper():
    text = _text(1250)
    pieces = split_into_pieces(text, 300)
    assert len(pieces) == 4
    assert " ".join(pieces) == text
    assert all(len(p.split()) >= 300 for p in pieces)


@pytest.mark.parametrize("n_words", [300, 599])
def test_a_paper_under_twice_the_length_stays_whole(n_words):
    text = _text(n_words)
    assert split_into_pieces(text, 300) == [text]


def test_nothing_long_enough_to_cut_abstains():
    assert _matched(_state(words=500)) is None


def test_a_very_short_paper_abstains():
    assert _matched(_state(), n_words=LENGTH_MATCH_MIN_WORDS - 1) is None
    assert _matched(_state(), n_words=LENGTH_MATCH_MIN_WORDS) is not None


def test_no_contributing_paper_abstains():
    state = _state()
    for s in state.samples:
        s.auth_weight = 0.0
    assert _matched(state) is None


@pytest.mark.parametrize("blank", [[0, 1, 2, 3], [2], [0, 3]])
def test_any_missing_text_abstains(blank):
    """A past paper with no retained text may be a long one; left whole it is
    the reference this exists to replace."""
    state = _state()
    for i in blank:
        state.samples[i].text = "  " if i % 2 else ""
    assert _matched(state) is None


def test_pieces_keep_line_and_paragraph_breaks():
    paragraph = " ".join(f"w{i}" for i in range(100))
    text = "\n\n".join([paragraph] * 12)
    pieces = split_into_pieces(text, 300)
    assert len(pieces) == 4
    assert all(p.count("\n\n") >= 2 for p in pieces)
    assert all(p in text for p in pieces)
    assert sum(len(p.split()) for p in pieces) == 1200


def test_back_matter_is_never_cut_into_pieces():
    body = _text(900)
    references = "\n".join(f"Author{i}, A. Title of work {i}. Press, 19{i:02d}." for i in range(40))
    pieces = paper_pieces(f"{body}\n\nBibliography\n{references}\n", 300)
    assert len(pieces) == 3  # counted over the body, not body + references
    assert " ".join(pieces) == body
    assert not any("Press" in p for p in pieces)


def test_a_wrong_shaped_piece_vector_abstains():
    assert build_length_matched_state(_state(), 300, lambda _t: np.zeros(3)) is None


@pytest.mark.parametrize("n", [6, 13, 20, LENGTH_MATCH_MAX_PIECES])
def test_extraction_is_capped(n):
    state = _state(n=n, words=6000)  # 20 pieces a paper uncapped
    vectorise = _vectoriser()
    matched = build_length_matched_state(state, 300, vectorise)
    assert n <= len(vectorise.calls) <= LENGTH_MATCH_MAX_PIECES
    assert len(matched.piece_vectors) == len(vectorise.calls)
    assert all(len(t.split()) == 300 for t in vectorise.calls)
    assert matched.papers_cut == n


def test_more_long_papers_than_the_cap_abstains():
    state = _state(n=LENGTH_MATCH_MAX_PIECES + 1, words=700)
    vectorise = _vectoriser()
    assert build_length_matched_state(state, 300, vectorise) is None
    assert vectorise.calls == []


def test_the_original_state_is_not_modified():
    state = _state()
    before = (state.baseline_mean.copy(), state.baseline_std.copy(), len(state.samples))
    matched = _matched(state)
    matched.samples.append(state.samples[0])
    _same(before, (state.baseline_mean, state.baseline_std, len(state.samples)))


# ── The matched reference ────────────────────────────────────────────────────


def test_history_is_still_counted_in_papers():
    state = _state()
    matched = _matched(state)
    assert isinstance(matched, LengthMatchedState)
    assert len(matched.piece_vectors) == 16
    assert matched.papers_cut == 4
    assert matched.sample_count == state.sample_count == 4
    assert matched.authenticated_count == state.authenticated_count
    assert matched.effective_sample_count == state.effective_sample_count
    _same(matched.density_matrix, state.density_matrix)
    _same(matched.trajectory.vector, state.trajectory.vector)
    assert matched.loo_distances == state.loo_distances


def test_each_paper_keeps_its_weight_however_many_pieces_it_gives():
    state = _state(n=3, words=1200)
    state.samples[0].text = _text(400, "short_")  # stays whole
    matched = _matched(state)
    assert len(matched.piece_vectors) == 1 + 4 + 4
    per_paper = [
        matched.piece_weights[:1].sum(),
        matched.piece_weights[1:5].sum(),
        matched.piece_weights[5:].sum(),
    ]
    np.testing.assert_allclose(per_paper, [RECENCY_DECAY**2, RECENCY_DECAY, 1.0])
    # The uncut paper contributes its stored vector unchanged.
    _same(matched.piece_vectors[0], state.samples[0].vector)


def test_mean_is_the_weighted_mean_of_the_pieces():
    matched = _matched(_state())
    w = matched.piece_weights
    np.testing.assert_allclose(
        matched.baseline_mean, (w[:, None] * matched.piece_vectors).sum(axis=0) / w.sum()
    )


def test_spread_floor_keeps_the_paper_count():
    """Sixteen pieces must not earn the tighter floor sixteen papers would."""
    state = _state()
    matched = build_length_matched_state(state, 300, lambda _t: np.full(FEATURE_DIM, 0.4))
    np.testing.assert_allclose(matched.baseline_std, 0.15 / np.sqrt(4))


def test_unverified_papers_are_never_cut_or_counted():
    state = _state()
    state.samples[1].auth_weight = 0.0
    vectorise = _vectoriser()
    matched = build_length_matched_state(state, 300, vectorise)
    assert len(matched.piece_vectors) == 12
    assert not any(t.startswith("p1_") for t in vectorise.calls)


# ── 1. off is byte-identical ─────────────────────────────────────────────────


def test_off_ignores_the_state_entirely():
    state = _state()
    sub = _submission()
    _same(
        dataclasses.asdict(_score(state, sub)),
        dataclasses.asdict(_score(state, sub, matched=_matched(state))),
    )


def test_default_config_is_off():
    assert ScoringConfig().length_matched_baseline == "off"
    r = _score(_state(), _submission())
    assert r.length_match_applied is False
    assert r.length_match_mode is None
    assert r.length_match_pieces is None
    assert r.length_match_deviation_preview is None


@pytest.mark.parametrize(
    "raw,expected",
    [("0", "off"), ("", "off"), ("1", "on"), ("on", "on"), ("Shadow", "shadow"), ("yes", "off")],
)
def test_mode_parsing_fails_closed(raw, expected):
    assert _parse_length_matched_baseline_mode(raw) == expected


def test_from_env_reads_the_flag(monkeypatch):
    monkeypatch.setenv("LENGTH_MATCHED_BASELINE", "shadow")
    assert ScoringConfig.from_env().length_matched_baseline == "shadow"
    monkeypatch.delenv("LENGTH_MATCHED_BASELINE")
    assert ScoringConfig.from_env().length_matched_baseline == "off"


@pytest.mark.parametrize("mode", ["shadow", "on"])
@pytest.mark.parametrize("bad", ["none", "plain", "other_student"])
def test_no_usable_state_is_exactly_off(mode, bad):
    state = _state()
    sub = _submission()
    handed = {
        "none": None,
        "plain": _state(seed=8),  # a StudentState, not a length-matched one
        "other_student": _matched(_state(student_id="t1:someone_else")),
    }[bad]
    _same(
        dataclasses.asdict(_score(state, sub)),
        dataclasses.asdict(_score(state, sub, mode, handed)),
    )


# ── 2. shadow is inert ───────────────────────────────────────────────────────


def test_shadow_changes_nothing_but_the_report_fields():
    state = _state()
    sub = _submission()
    off = _score(state, sub)
    shadow = _score(state, sub, "shadow", _matched(state))
    _same(_strip(off), _strip(shadow))
    assert shadow.length_match_applied is False
    assert shadow.length_match_mode == "shadow"
    assert shadow.length_match_pieces == 16
    assert shadow.length_match_deviation_preview is not None


def test_shadow_keeps_the_typicality_band_and_the_conformal_pvalue():
    state = _state(n=6)
    sub = _submission()
    cfg = ScoringConfig(
        typicality_scoring_enabled=True,
        amplitude_scoring_enabled=True,
        authentic_fidelities=[0.5, 0.6, 0.7, 0.8, 0.9],
    )
    off = _score(state, sub, config=cfg)
    shadow = _score(
        state,
        sub,
        matched=_matched(state),
        config=dataclasses.replace(cfg, length_matched_baseline="shadow"),
    )
    assert off.typicality_band is not None
    assert shadow.typicality_band == off.typicality_band
    assert off.authorship.fidelity_conformal_pvalue is not None
    assert shadow.authorship.fidelity_conformal_pvalue == off.authorship.fidelity_conformal_pvalue


def test_a_failing_shadow_preview_never_fails_the_request(caplog):
    state = _state()
    sub = _submission()
    broken = _matched(state)
    broken.piece_weights = None  # the "on" pass will raise
    off = _score(state, sub)
    shadow = _score(state, sub, "shadow", broken)
    assert shadow.length_match_deviation_preview is None
    assert "length-match shadow preview failed" in caplog.text
    stripped = _strip(shadow)
    _same(_strip(off), stripped)


# ── 3. on ────────────────────────────────────────────────────────────────────


def test_on_scores_a_short_paper_as_closer_to_the_student():
    """The fixture is the fault in miniature: whole papers agree tightly, a
    short paper by the same writer is noisier and shifted."""
    state = _state()
    sub = _submission()
    off = _score(state, sub)
    on = _score(state, sub, "on", _matched(state))
    assert on.length_match_applied is True
    assert on.length_match_mode == "on"
    assert on.length_match_deviation_preview is None
    assert on.authorship.deviation_score < off.authorship.deviation_score


def test_on_still_separates_a_different_writer():
    state = _state()
    matched = _matched(state)
    own = _score(state, _submission(), "on", matched).authorship.deviation_score
    rng = np.random.default_rng(404)
    stranger = np.clip(rng.normal(0.5, 0.2, FEATURE_DIM), 0.0, 1.0)
    assert _score(state, stranger, "on", matched).authorship.deviation_score > own


def test_on_reports_the_paper_count_not_the_piece_count():
    state = _state()
    on = _score(state, _submission(), "on", _matched(state))
    off = _score(state, _submission())
    assert on.baseline_confidence.sample_count == off.baseline_confidence.sample_count
    assert on.baseline_confidence.authenticated_count == off.baseline_confidence.authenticated_count
    assert on.length_match_pieces == 16


def test_on_withholds_the_typicality_band():
    """loo_distances are distances between whole past papers."""
    state = _state(n=6)
    cfg = ScoringConfig(typicality_scoring_enabled=True, length_matched_baseline="on")
    sub = _submission()
    assert _score(state, sub, matched=_matched(state), config=cfg).typicality_band is None
    assert _score(state, sub, matched=None, config=cfg).typicality_band is not None


def test_on_withholds_the_conformal_pvalue():
    state = _state(n=6)
    cfg = ScoringConfig(
        amplitude_scoring_enabled=True,
        authentic_fidelities=[0.5, 0.6, 0.7, 0.8, 0.9],
        length_matched_baseline="on",
    )
    sub = _submission()
    assert _score(state, sub, config=cfg).authorship.fidelity_conformal_pvalue is not None
    on = _score(state, sub, matched=_matched(state), config=cfg)
    assert on.authorship.fidelity_conformal_pvalue is None


# ── 4. shadow preview equals on ──────────────────────────────────────────────


def _impostor_stats(seed=21):
    rng = np.random.default_rng(seed)
    return (
        np.clip(rng.normal(0.5, 0.05, FEATURE_DIM), 0.0, 1.0),
        np.clip(rng.normal(0.12, 0.03, FEATURE_DIM), 0.02, None),
    )


@pytest.mark.parametrize(
    "extra,kwargs",
    [
        ({}, {}),
        ({"length_adaptive_weights": True}, {"n_tokens": 350}),
        ({"characteristic_weights": "on"}, {"impostor_stats": "pool"}),
        ({"null_model": "impostor"}, {"impostor_stats": "pool"}),
        ({"identity_axis_enabled": True}, {}),
        ({"opportunity_mask": "on"}, {"unmeasured_mask": "mask"}),
        ({"opportunity_mask": "shadow"}, {"unmeasured_mask": "mask"}),
        ({"amplitude_scoring_enabled": True, "typicality_scoring_enabled": True}, {}),
    ],
)
@pytest.mark.parametrize("n", [4, 9])
def test_shadow_preview_equals_on(extra, kwargs, n):
    state = _state(n=n)
    matched = _matched(state)
    sub = _submission()
    kw = dict(kwargs)
    if kw.get("impostor_stats") == "pool":
        kw["impostor_stats"] = _impostor_stats()
    if kw.get("unmeasured_mask") == "mask":
        mask = np.zeros(FEATURE_DIM, dtype=bool)
        mask[np.flatnonzero(matched.active_feature_mask)[:3]] = True
        kw["unmeasured_mask"] = mask
    shadow = _score(
        state,
        sub,
        matched=matched,
        config=ScoringConfig(length_matched_baseline="shadow", **extra),
        **kw,
    )
    on = _score(
        state,
        sub,
        matched=matched,
        config=ScoringConfig(length_matched_baseline="on", **extra),
        **kw,
    )
    assert shadow.length_match_deviation_preview == on.authorship.deviation_score
    assert shadow.length_match_action_preview == on.recommendation.action
    assert on.authorship.deviation_score != shadow.authorship.deviation_score


# ── Cut points for the matched reference ─────────────────────────────────────


def test_the_cut_points_are_the_ones_the_study_derived():
    """The constant must stay the study's output, not a hand-tuned copy."""
    import json
    from pathlib import Path

    from original.quantum.length_match import LENGTH_MATCHED_ACTION_THRESHOLDS

    derived = json.loads(
        (
            Path(__file__).resolve().parents[2]
            / "validation"
            / "length_match_thresholds"
            / "derived_cut_points.json"
        ).read_text()
    )["cut_points"]
    assert LENGTH_MATCHED_ACTION_THRESHOLDS == {
        "no_action": derived["monitor"],
        "monitor": derived["schedule_conversation"],
        "escalate": derived["escalate"],
    }


_EVERYTHING_ESCALATES = {"no_action": 0.0, "monitor": 0.0, "escalate": 0.0}


def test_on_reads_the_action_against_the_matched_cut_points(monkeypatch):
    from original.quantum import scoring

    state = _state()
    matched = _matched(state)
    sub = _submission()
    before = _score(state, sub, "on", matched)
    monkeypatch.setattr(scoring, "LENGTH_MATCHED_ACTION_THRESHOLDS", _EVERYTHING_ESCALATES)
    after = _score(state, sub, "on", matched)
    assert after.authorship.deviation_score == before.authorship.deviation_score
    assert after.recommendation.action == "escalate"


def test_off_and_an_abstained_match_keep_the_product_cut_points(monkeypatch):
    from original.quantum import scoring

    state = _state()
    sub = _submission()
    off = _score(state, sub, "off", _matched(state))
    abstained = _score(state, sub, "on", None)  # nothing to cut: the route passes None
    monkeypatch.setattr(scoring, "LENGTH_MATCHED_ACTION_THRESHOLDS", _EVERYTHING_ESCALATES)
    _same(dataclasses.asdict(_score(state, sub, "off", _matched(state))), dataclasses.asdict(off))
    _same(dataclasses.asdict(_score(state, sub, "on", None)), dataclasses.asdict(abstained))
    assert off.recommendation.action != "escalate"


def test_the_matched_cut_points_take_precedence_over_an_admin_tuned_set(monkeypatch):
    """An admin-tuned set was made for whole-paper references too, so it
    applies only when the match did not."""
    from original.quantum import scoring

    state = _state()
    matched = _matched(state)
    sub = _submission()
    tuned = {"no_action": 0.99, "monitor": 0.995, "escalate": 0.999}  # all no_action
    monkeypatch.setattr(scoring, "LENGTH_MATCHED_ACTION_THRESHOLDS", _EVERYTHING_ESCALATES)
    on = _score(
        state,
        sub,
        matched=matched,
        config=ScoringConfig(length_matched_baseline="on", tuned_action_thresholds=tuned),
    )
    off = _score(
        state,
        sub,
        matched=matched,
        config=ScoringConfig(length_matched_baseline="off", tuned_action_thresholds=tuned),
    )
    assert on.recommendation.action == "escalate"
    assert off.recommendation.action == "no_action"


def test_shadow_previews_the_matched_action_without_using_it(monkeypatch):
    from original.quantum import scoring

    state = _state()
    matched = _matched(state)
    sub = _submission()
    off = _score(state, sub, "off", matched)
    monkeypatch.setattr(scoring, "LENGTH_MATCHED_ACTION_THRESHOLDS", _EVERYTHING_ESCALATES)
    shadow = _score(state, sub, "shadow", matched)
    assert shadow.length_match_action_preview == "escalate"
    assert shadow.recommendation.action == off.recommendation.action
    assert _strip(shadow) == _strip(off)


def test_a_failing_preview_reports_neither_number():
    from original.quantum.scoring import _length_match_preview

    def boom():
        raise RuntimeError("preview")

    assert _length_match_preview(boom) == (None, None)
