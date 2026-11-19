"""
LENGTH_MATCHED_BASELINE production-wiring test (students_scoring.py).

score() only uses a length-matched reference when the caller builds one, and
the route is the only place that has the past papers' text and the new
paper's length together. If that hand-off is dropped the flag goes quietly
inert with a green suite. These tests drive the real HTTP endpoint and watch
what reaches score().
"""

import logging

import numpy as np
import pytest
from fastapi.testclient import TestClient

import run  # repo-root launcher
from original import principal as pr
from original.features.pipeline import feature_vector
from original.quantum.length_match import LengthMatchedState
from original.quantum.state import BaselineSample, StudentState
from original.repository import get_repository
from original.routers import students_scoring

app = run.load_legacy_demo_app()
client = TestClient(app)

_SID = "lenw:scored_student"

_SENTENCES = [
    "The harvest came late this year, and the farmers who had waited grew uneasy.",
    "Rain fell for nine days, which nobody in the valley had expected.",
    "However, the mill kept turning because the river ran high.",
    "Prices rose in town, so the bakers closed early and went home.",
    "Children stayed indoors and read whatever books the school had lent them.",
    "The road that follows the river flooded twice before the week was out.",
    "Nobody could say whether the wheat would be worth cutting at all.",
    "Old men remembered a worse season, although they disagreed about the year.",
]


def _prose(n_words: int, offset: int) -> str:
    words: list[str] = []
    i = offset
    while len(words) < n_words:
        words += _SENTENCES[i % len(_SENTENCES)].split()
        i += 3
    return " ".join(words[:n_words])


_TEXT = _prose(150, 1)  # the new paper: a quarter the length of the past ones


def _auth(token: str):
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def lenw_tenant():
    client.post(
        "/tenants",
        json={"tenant_id": "lenw", "name": "Length Seminary", "environment": "pilot"},
    )
    state = StudentState(student_id=_SID)
    for i in range(4):
        text = _prose(620, i)
        state.add_sample(
            BaselineSample(
                text=text,
                vector=np.asarray(feature_vector(text)),
                provenance="instructor_verified",
                auth_weight=1.0,
                assignment=f"a{i}",
            )
        )
    get_repository().put(state)
    return pr.mint_principal_token("prof_lenw", "professor", "lenw")


@pytest.fixture
def spy(monkeypatch):
    """Record what the route hands to score(), and what comes back."""
    seen = {}
    real = students_scoring.quantum_score

    def _spy(**kwargs):
        seen["kwargs"] = kwargs
        seen["result"] = real(**kwargs)
        return seen["result"]

    monkeypatch.setattr(students_scoring, "quantum_score", _spy)
    return seen


_AUDIT = (
    "length_match_applied",
    "length_match_mode",
    "length_match_pieces",
    "length_match_deviation_preview",
)


def _without_audit(body):
    return {k: v for k, v in body.items() if k not in _AUDIT}


def _post(token, text=_TEXT):
    r = client.post(f"/students/{_SID}/score", json={"text": text}, headers=_auth(token))
    assert r.status_code == 200, r.text
    return r.json()


def test_flag_off_builds_nothing(lenw_tenant, spy, monkeypatch, caplog):
    monkeypatch.delenv("LENGTH_MATCHED_BASELINE", raising=False)
    with caplog.at_level(logging.INFO, logger=students_scoring.__name__):
        _post(lenw_tenant)
    assert spy["kwargs"]["length_matched_state"] is None
    assert spy["result"].length_match_mode is None
    assert "length_match mode=" not in caplog.text


def test_shadow_hands_the_state_to_score_and_logs_it(lenw_tenant, spy, monkeypatch, caplog):
    monkeypatch.delenv("LENGTH_MATCHED_BASELINE", raising=False)
    off = _post(lenw_tenant)
    monkeypatch.setenv("LENGTH_MATCHED_BASELINE", "shadow")
    with caplog.at_level(logging.INFO, logger=students_scoring.__name__):
        shadow = _post(lenw_tenant)

    handed = spy["kwargs"]["length_matched_state"]
    assert isinstance(handed, LengthMatchedState)
    assert handed.papers_cut == 4
    assert len(handed.piece_vectors) == 16
    lines = [r.getMessage() for r in caplog.records if "length_match mode=" in r.getMessage()]
    assert len(lines) == 1
    assert lines[0].startswith("length_match mode=shadow pieces=16 papers_cut=4 ")
    assert _SID not in lines[0]  # counts only, never a student id
    # Report-only end to end.
    assert shadow["length_match_mode"] == "shadow"
    assert shadow["length_match_applied"] is False
    assert shadow["length_match_pieces"] == 16
    assert shadow["length_match_deviation_preview"] is not None
    assert off["length_match_mode"] is None
    assert _without_audit(shadow) == _without_audit(off)


def test_on_changes_the_score_through_the_route(lenw_tenant, spy, monkeypatch):
    monkeypatch.setenv("LENGTH_MATCHED_BASELINE", "shadow")
    shadow = _post(lenw_tenant)
    monkeypatch.setenv("LENGTH_MATCHED_BASELINE", "on")
    on = _post(lenw_tenant)
    assert spy["result"].length_match_applied is True
    assert on["authorship"]["deviation_score"] != shadow["authorship"]["deviation_score"]
    assert on["authorship"]["deviation_score"] == shadow["length_match_deviation_preview"]
    # The stored student is untouched: still four papers, measured whole.
    stored = get_repository().get(_SID)
    assert not isinstance(stored, LengthMatchedState)
    assert stored.sample_count == 4


def test_a_paper_as_long_as_the_past_ones_is_exactly_off(lenw_tenant, spy, monkeypatch, caplog):
    long_text = _prose(600, 2)
    monkeypatch.delenv("LENGTH_MATCHED_BASELINE", raising=False)
    off = _post(lenw_tenant, long_text)
    monkeypatch.setenv("LENGTH_MATCHED_BASELINE", "on")
    with caplog.at_level(logging.INFO, logger=students_scoring.__name__):
        on = _post(lenw_tenant, long_text)
    assert spy["kwargs"]["length_matched_state"] is None
    assert "length_match mode=on pieces=0 papers_cut=0 " in caplog.text
    assert on == off


_BIBLIOGRAPHY = "\n\nWorks Cited\n" + "\n".join(
    f"Author{i}, A. A Study of River Valleys, Volume {i}. Valley Press, 19{i:02d}."
    for i in range(30)
)


def test_a_bibliography_does_not_count_toward_the_papers_length(
    lenw_tenant, spy, monkeypatch, caplog
):
    """Past papers are cut on their body, so the new paper is measured on its
    body too. Counted raw, a 150-word paper with a long bibliography reads as
    more than half the past papers' 620 words and the match abstains."""
    with_bib = _TEXT + _BIBLIOGRAPHY
    assert len(with_bib.split()) * 2 > 620  # raw, it would abstain
    monkeypatch.setenv("LENGTH_MATCHED_BASELINE", "shadow")
    _post(lenw_tenant, _TEXT)
    body_only = spy["kwargs"]["length_matched_state"]
    with caplog.at_level(logging.INFO, logger=students_scoring.__name__):
        _post(lenw_tenant, with_bib)
    handed = spy["kwargs"]["length_matched_state"]
    assert isinstance(handed, LengthMatchedState)
    assert handed.papers_cut == body_only.papers_cut == 4
    assert len(handed.piece_vectors) == len(body_only.piece_vectors) == 16
    assert " body_words=150 " in caplog.text
    # The paper's raw length still reaches score() unchanged.
    assert spy["kwargs"]["n_tokens"] == len(with_bib.split())


def test_a_failing_build_falls_back_to_flag_off(lenw_tenant, spy, monkeypatch, caplog):
    """Nothing in the new layer may take the scoring endpoint down."""
    from original.quantum import length_match

    monkeypatch.delenv("LENGTH_MATCHED_BASELINE", raising=False)
    off = _post(lenw_tenant)

    def _boom(*_a, **_k):
        raise RuntimeError("extractor broke")

    monkeypatch.setattr(length_match, "build_length_matched_state", _boom)
    monkeypatch.setenv("LENGTH_MATCHED_BASELINE", "on")
    with caplog.at_level(logging.ERROR, logger=students_scoring.__name__):
        on = _post(lenw_tenant)
    assert spy["kwargs"]["length_matched_state"] is None
    assert "length match failed" in caplog.text
    assert on == off


@pytest.mark.parametrize("mode,expect_write", [("off", True), ("shadow", True), ("on", False)])
def test_on_does_not_store_a_length_matched_fidelity(
    lenw_tenant, spy, monkeypatch, mode, expect_write
):
    """A fidelity encoded against the pieces must not enter the student's
    calibration set: the rows outlive the flag."""
    writes = []
    repo = get_repository()
    monkeypatch.setattr(repo, "put_fidelity_score", lambda **kw: writes.append(kw))
    monkeypatch.setenv("AMPLITUDE_SCORING_ENABLED", "1")
    monkeypatch.setenv("LENGTH_MATCHED_BASELINE", mode)
    _post(lenw_tenant)
    assert spy["result"].authorship.quantum_fidelity > 0
    assert bool(writes) is expect_write
