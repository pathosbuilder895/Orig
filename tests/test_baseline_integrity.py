"""Tests for original/baseline_integrity.py — report-only baseline health
diagnostic (T-70). See docs/superpowers/specs/2026-09-20-adversarial-
verification-threat-model-design.md section 5.4.
"""

from __future__ import annotations

import collections
import dataclasses
import uuid

import numpy as np
import pytest

import original.baseline_integrity as baseline_integrity_module
from original.baseline_integrity import BaselineIntegrity, build_baseline_integrity
from original.constants import FEATURE_DIM
from original.quantum.state import BaselineSample, StudentState
from original.style_authorship import MIN_BASELINES


def _sample(
    vector_value: float,
    *,
    provenance: str = "verified",
    auth_weight: float = 1.0,
    submitted_at: str = "2026-01-01",
) -> BaselineSample:
    return BaselineSample(
        text=f"sample text {vector_value}",
        vector=np.full(FEATURE_DIM, vector_value, dtype=np.float64),
        provenance=provenance,
        auth_weight=auth_weight,
        submitted_at=submitted_at,
    )


def _state(samples: list[BaselineSample], student_id: str = "tenant:student-1") -> StudentState:
    return StudentState(student_id=student_id, samples=samples)


def _make_state_tight(n: int = 3) -> StudentState:
    """n baselines clustered tightly around 0.4."""
    samples = [
        _sample(0.40 + 0.001 * i, submitted_at=f"2026-01-{i + 1:02d}") for i in range(n)
    ]
    return _state(samples)


def _make_state_with_outlier() -> StudentState:
    """3 tight samples + 1 far (register-mismatched) sample."""
    samples = [
        _sample(0.40, submitted_at="2026-01-01"),
        _sample(0.401, submitted_at="2026-01-02"),
        _sample(0.399, submitted_at="2026-01-03"),
        _sample(0.95, submitted_at="2026-01-04"),  # far outlier
    ]
    return _state(samples)


class TestReadiness:
    def test_three_tight_baselines_are_ready(self):
        state = _make_state_tight(3)
        bi = build_baseline_integrity(state)
        assert bi is not None
        assert bi.readiness == "ready"
        assert bi.n_baselines == 3
        assert bi.min_required == MIN_BASELINES
        assert bi.loo_outlier_samples == []

    def test_two_samples_is_thin(self):
        state = _make_state_tight(2)
        bi = build_baseline_integrity(state)
        assert bi is not None
        assert bi.readiness == "thin"
        assert bi.n_baselines == 2
        assert f"N={MIN_BASELINES}" in " ".join(bi.notes)

    def test_zero_samples_returns_none(self):
        state = _state([])
        assert build_baseline_integrity(state) is None

    def test_zero_contributing_samples_is_absent(self):
        # Non-empty sample list, but nothing actually contributes to the
        # baseline (auth_weight forced to 0 — e.g. a rejected/discarded
        # sample). This is distinct from "no samples at all", which
        # returns None instead.
        samples = [_sample(0.4, auth_weight=0.0), _sample(0.5, auth_weight=0.0)]
        state = _state(samples)
        bi = build_baseline_integrity(state)
        assert bi is not None
        assert bi.n_baselines == 0
        assert bi.readiness == "absent"
        assert bi.provenance_mix == {}
        assert bi.loo_outlier_samples == []


class TestLooOutliers:
    def test_flags_loo_outlier_baseline(self):
        state = _make_state_with_outlier()
        bi = build_baseline_integrity(state)
        assert bi is not None
        assert any(o["z"] > 3.5 for o in bi.loo_outlier_samples)
        assert "one sample stylistically unlike the others" in bi.notes

    def test_loo_outlier_entries_have_index_and_z(self):
        state = _make_state_with_outlier()
        bi = build_baseline_integrity(state)
        assert bi is not None
        for entry in bi.loo_outlier_samples:
            assert set(entry.keys()) == {"index", "z"}
            assert isinstance(entry["index"], int)
            assert isinstance(entry["z"], float)

    def test_mad_zero_does_not_crash_and_flags_no_outliers(self):
        # All loo distances identical -> MAD == 0. Must not divide by zero,
        # and (since every sample is equally "typical") nothing should be
        # flagged as an outlier.
        samples = [_sample(0.4, submitted_at=f"2026-01-{i + 1:02d}") for i in range(4)]
        state = _state(samples)
        # Confirm the premise: identical vectors -> identical loo distances
        # -> MAD == 0, so this test actually exercises the branch it claims to.
        distances = state.loo_distances
        assert len(distances) == 4
        median = float(np.median(distances))
        mad = float(np.median(np.abs(np.asarray(distances) - median)))
        assert mad == 0.0

        bi = build_baseline_integrity(state)
        assert bi is not None
        assert bi.loo_outlier_samples == []

    def test_fewer_than_two_contributing_samples_has_no_loo_outliers(self):
        state = _make_state_tight(1)
        bi = build_baseline_integrity(state)
        assert bi is not None
        assert bi.loo_outlier_samples == []


class TestProvenanceMix:
    def test_provenance_mix_counts_contributing_samples(self):
        samples = [
            _sample(0.40, provenance="proctored"),
            _sample(0.41, provenance="verified"),
            _sample(0.42, provenance="verified"),
        ]
        state = _state(samples)
        bi = build_baseline_integrity(state)
        assert bi is not None
        assert bi.provenance_mix == {"proctored": 1, "verified": 2}
        assert isinstance(bi.provenance_mix, dict)
        assert not isinstance(bi.provenance_mix, collections.Counter)


class TestSpanDays:
    def test_span_days_from_min_max_submitted_at(self):
        samples = [
            _sample(0.40, submitted_at="2026-01-01"),
            _sample(0.41, submitted_at="2026-01-10"),
            _sample(0.42, submitted_at="2026-01-20"),
        ]
        state = _state(samples)
        bi = build_baseline_integrity(state)
        assert bi is not None
        assert bi.span_days == 19

    def test_span_days_none_when_dates_unparseable(self):
        samples = [
            _sample(0.40, submitted_at="not-a-date"),
            _sample(0.41, submitted_at=""),
            _sample(0.42, submitted_at="also garbage"),
        ]
        state = _state(samples)
        bi = build_baseline_integrity(state)
        assert bi is not None
        assert bi.span_days is None

    def test_span_days_none_when_fewer_than_two_dated_samples(self):
        samples = [
            _sample(0.40, submitted_at="2026-01-01"),
            _sample(0.41, submitted_at=""),
        ]
        state = _state(samples)
        bi = build_baseline_integrity(state)
        assert bi is not None
        assert bi.span_days is None

    def test_span_days_skips_bad_dates_without_raising(self):
        samples = [
            _sample(0.40, submitted_at="2026-01-01"),
            _sample(0.41, submitted_at="garbage"),
            _sample(0.42, submitted_at="2026-01-15"),
        ]
        state = _state(samples)
        bi = build_baseline_integrity(state)
        assert bi is not None
        assert bi.span_days == 14


class TestSigmaInflation:
    def test_sigma_inflation_none_without_impostor_stats(self):
        state = _make_state_tight(3)
        bi = build_baseline_integrity(state, impostor_stats=None)
        assert bi is not None
        assert bi.sigma_inflation is None
        assert "baseline spread wider than the peer population" not in bi.notes

    def test_sigma_inflation_small_for_tight_baseline_against_wide_pool(self):
        state = _make_state_tight(3)
        # Peer pool sigma is wide relative to this student's tight baseline_std
        # on almost every feature -> low fraction where baseline_std > sigma_null.
        mu_null = np.full(FEATURE_DIM, 0.4, dtype=np.float64)
        sigma_null = np.full(FEATURE_DIM, 1.0, dtype=np.float64)
        bi = build_baseline_integrity(state, impostor_stats=(mu_null, sigma_null))
        assert bi is not None
        assert bi.sigma_inflation is not None
        assert bi.sigma_inflation < 0.1
        assert "baseline spread wider than the peer population" not in bi.notes

    def test_sigma_inflation_high_flags_note(self):
        state = _make_state_tight(3)
        # Peer pool sigma is tiny relative to this student's baseline_std on
        # every feature -> high fraction where baseline_std > sigma_null.
        mu_null = np.full(FEATURE_DIM, 0.4, dtype=np.float64)
        sigma_null = np.full(FEATURE_DIM, 0.001, dtype=np.float64)
        bi = build_baseline_integrity(state, impostor_stats=(mu_null, sigma_null))
        assert bi is not None
        assert bi.sigma_inflation is not None
        assert bi.sigma_inflation > 0.9
        assert "baseline spread wider than the peer population" in bi.notes


class TestExceptionSafety:
    def test_malformed_impostor_stats_returns_none(self):
        state = _make_state_tight(3)
        # Not unpackable into (mu, sigma) -> internal exception, must not raise.
        bi = build_baseline_integrity(state, impostor_stats=12345)
        assert bi is None

    def test_impostor_stats_shape_mismatch_returns_none(self):
        state = _make_state_tight(3)
        mu_null = np.full(FEATURE_DIM, 0.4, dtype=np.float64)
        sigma_null_wrong_shape = np.full(FEATURE_DIM - 1, 1.0, dtype=np.float64)
        bi = build_baseline_integrity(state, impostor_stats=(mu_null, sigma_null_wrong_shape))
        assert bi is None

    def test_none_state_returns_none(self):
        assert build_baseline_integrity(None) is None

    def test_malformed_impostor_stats_logs_warning(self, caplog):
        state = _make_state_tight(3)
        with caplog.at_level("WARNING", logger="original.baseline_integrity"):
            bi = build_baseline_integrity(state, impostor_stats=12345)
        assert bi is None
        warnings = [
            r for r in caplog.records if r.levelname == "WARNING"
        ]
        assert len(warnings) == 1
        message = warnings[0].getMessage()
        assert "TypeError" in message

    def test_impostor_stats_shape_mismatch_logs_warning(self, caplog):
        state = _make_state_tight(3)
        mu_null = np.full(FEATURE_DIM, 0.4, dtype=np.float64)
        sigma_null_wrong_shape = np.full(FEATURE_DIM - 1, 1.0, dtype=np.float64)
        with caplog.at_level("WARNING", logger="original.baseline_integrity"):
            bi = build_baseline_integrity(state, impostor_stats=(mu_null, sigma_null_wrong_shape))
        assert bi is None
        warnings = [
            r for r in caplog.records if r.levelname == "WARNING"
        ]
        assert len(warnings) == 1
        message = warnings[0].getMessage()
        assert "ValueError" in message


def test_return_type_is_frozen_dataclass_instance():
    state = _make_state_tight(3)
    bi = build_baseline_integrity(state)
    assert isinstance(bi, BaselineIntegrity)
    with pytest.raises(dataclasses.FrozenInstanceError):
        bi.n_baselines = 99  # frozen -> assignment must fail


# ── Task 6: wiring into the score response ─────────────────────────────────
#
# Mirrors tests/fusion/test_wiring.py's report-only-invariant pattern and
# tests/test_style_authorship.py::test_api_flag_is_attach_only, adapted for a
# signal with no env flag: `baseline_integrity` is attempted unconditionally
# by original/routers/_shared.py::_to_response, which re-fetches the
# student's persisted state by id (Layer7Output carries no direct state
# reference) and is defensively wrapped so a failure there can never break
# the primary score response.
#
# A brand-new student with literally zero samples cannot reach a 200 from
# POST /students/{id}/score (score_submission 422s before scoring when
# authenticated_count == 0), so "forced to None" is exercised two other,
# equally real ways: (a) the /test/score playground endpoint, whose
# synthetic in-memory student is never persisted to the repository, so the
# re-fetch inside _to_response naturally comes back None; and (b) directly
# monkeypatching build_baseline_integrity to simulate the signal itself
# abstaining/failing on an otherwise-real, persisted student.

LONG_TEXT = (
    "The doctrine of justification by faith stands at the center of the gospel. "
    "When Paul writes to the Romans, he labors to show that righteousness comes "
    "not by works of the law but through faith in Christ alone. This conviction "
    "shaped the Reformation and continues to shape pastoral practice today. "
    "A careful reader notices how the argument unfolds in stages, each building "
    "on the last, until the conclusion becomes unavoidable. The voice here is "
    "deliberate and measured, favoring long subordinate clauses and a vocabulary "
    "drawn from systematic theology. Such patterns, repeated across many essays, "
    "form a fingerprint as distinctive as handwriting. The seminary student who "
    "writes this way in September will, absent intervention, write this way in "
    "May, and that continuity is precisely what we set out to measure and to "
    "protect with patience and with care."
)
SUBMISSION_TEXT = (
    "Grace and peace are the twin notes that open nearly every Pauline letter, "
    "and their repetition is not accidental but theological. The writer returns "
    "again and again to the same vocabulary, the same cadence, the same habit of "
    "qualifying a bold claim with a gentle clause. Across a semester these habits "
    "compound into a recognizable voice, and it is that voice, not any single "
    "sentence, that the system learns to know and to defend with care and patience."
)


def _seed_student(client, sid: str, n_baselines: int = 3):
    for i in range(n_baselines):
        r = client.post(
            f"/students/{sid}/baseline",
            json={"text": LONG_TEXT, "provenance": "verified", "assignment": f"bl-{i}"},
        )
        assert r.status_code == 200, r.text


def _score(client, sid: str) -> dict:
    r = client.post(
        f"/students/{sid}/score",
        json={"text": SUBMISSION_TEXT, "submission_id": f"bi-{uuid.uuid4().hex[:8]}"},
    )
    assert r.status_code == 200, r.text
    return r.json()


class TestWiringIntoScoreResponse:
    def test_populated_for_a_real_persisted_student(self, live_client, store_reset):
        sid = f"baseline-integrity-{uuid.uuid4().hex[:8]}"
        _seed_student(live_client, sid, n_baselines=3)
        body = _score(live_client, sid)

        attached = body.get("baseline_integrity")
        assert attached is not None
        assert attached["n_baselines"] == 3
        assert attached["readiness"] == "ready"
        assert attached["min_required"] == MIN_BASELINES
        assert attached["provenance_mix"] == {"verified": 3}
        assert isinstance(attached["notes"], list)
        assert attached["loo_outlier_samples"] == []
        assert attached["sigma_inflation"] is None  # no impostor pool wired here

    def test_none_for_the_unpersisted_playground_student(self, live_client, store_reset):
        """/test/score never writes to the repository (see its docstring), so
        the state re-fetch inside _to_response comes back None and
        baseline_integrity is naturally absent -- with no monkeypatching."""
        r = live_client.post(
            "/test/score",
            json={"text": SUBMISSION_TEXT, "baseline_texts": [LONG_TEXT, LONG_TEXT, LONG_TEXT]},
        )
        assert r.status_code == 200, r.text
        assert r.json()["layer7"]["baseline_integrity"] is None

    def test_report_only_invariant_populated_vs_forced_none(
        self, live_client, store_reset, monkeypatch
    ):
        """THE load-bearing test: whether baseline_integrity is present or
        forced to None, the rest of the score response is byte-identical."""
        sid = f"baseline-integrity-{uuid.uuid4().hex[:8]}"
        _seed_student(live_client, sid, n_baselines=3)

        populated = _score(live_client, sid)
        assert populated["baseline_integrity"] is not None

        monkeypatch.setattr(
            baseline_integrity_module, "build_baseline_integrity", lambda *a, **k: None
        )
        forced_none = _score(live_client, sid)
        assert forced_none["baseline_integrity"] is None

        populated.pop("baseline_integrity")
        forced_none.pop("baseline_integrity")
        # submission_id differs per call (uuid4-suffixed) -- not part of the
        # invariant under test.
        populated.pop("submission_id")
        forced_none.pop("submission_id")
        assert populated == forced_none

    def test_call_site_failure_does_not_break_scoring(self, live_client, store_reset, monkeypatch):
        """A raise from build_baseline_integrity itself (not just an internal
        abstention) must still leave the primary score response intact --
        the call-site try/except, not just the function's own internal
        try/except, is what's under test here."""
        sid = f"baseline-integrity-{uuid.uuid4().hex[:8]}"
        _seed_student(live_client, sid, n_baselines=3)

        def _boom(*_args, **_kwargs):
            raise RuntimeError("simulated failure")

        monkeypatch.setattr(baseline_integrity_module, "build_baseline_integrity", _boom)
        body = _score(live_client, sid)
        assert body["baseline_integrity"] is None
        assert "authorship" in body and "deviation_score" in body["authorship"]

    def test_repo_lookup_failure_does_not_break_scoring(
        self, live_client, store_reset, monkeypatch
    ):
        """A raise from the repository re-fetch itself (not the build call)
        is the other half of the call-site's defensiveness. score_submission
        itself does one `_repo().get(student_id)` before scoring even
        starts (original/routers/students_scoring.py:38); only the SECOND
        lookup -- the defensive re-fetch inside _to_response -- should be
        made to fail here, so the first pass-through call count matters."""
        from original.repository import get_repository

        sid = f"baseline-integrity-{uuid.uuid4().hex[:8]}"
        _seed_student(live_client, sid, n_baselines=3)

        repo = get_repository()
        real_get = repo.get
        calls = {"n": 0}

        def _flaky(student_id):
            if student_id == sid:
                calls["n"] += 1
                if calls["n"] >= 2:
                    raise RuntimeError("simulated repo failure")
            return real_get(student_id)

        monkeypatch.setattr(repo, "get", _flaky)
        body = _score(live_client, sid)
        assert body["baseline_integrity"] is None
        assert "authorship" in body and "deviation_score" in body["authorship"]
        assert calls["n"] >= 2, "the defensive re-fetch inside _to_response must have run"
