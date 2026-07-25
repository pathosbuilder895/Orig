"""Flag-matrix regression: scoring must be stable and sane under every
pilot-relevant env-flag combination. Guards the WS-5 gap: the pilot runs
with CONTEXT_MANIFEST_ENABLED=1 ADAPTIVE_WEIGHTS_ENABLED=1 NULL_MODEL=impostor,
but the suite only exercised flags-off defaults.

Routes through the same production wiring api.py uses (run_adaptive_pipeline
for the two context flags, ScoringConfig.from_env() + build_impostor_stats
for NULL_MODEL, ScoringConfig for AMPLITUDE_SCORING_ENABLED) rather than
guessing at score()'s internals, so a real wiring regression shows up here.
"""

from __future__ import annotations

import itertools
import os

import numpy as np
import pytest

from original.constants import FEATURE_DIM
from original.context.pipeline import run_adaptive_pipeline
from original.quantum.null_pool import build_impostor_stats
from original.quantum.scoring import Layer7Output, ScoringConfig, score
from original.quantum.state import BaselineSample, StudentState

FLAGS = ["CONTEXT_MANIFEST_ENABLED", "ADAPTIVE_WEIGHTS_ENABLED", "AMPLITUDE_SCORING_ENABLED"]
MATRIX = list(itertools.product("01", repeat=len(FLAGS)))  # 8 combos
NULLS = ["none", "impostor"]

SUBMISSION_TEXT = (
    "The doctrine of justification by faith stands at the center of the gospel. "
    "When Paul writes to the Romans, he labors to show that righteousness comes "
    "not by works of the law but through faith in Christ alone. This conviction "
    "shaped the Reformation and continues to shape pastoral practice today. "
    "A careful reader notices how the argument unfolds in stages, each building "
    "on the last, until the conclusion becomes unavoidable. The voice here is "
    "deliberate and measured, favoring long subordinate clauses and a vocabulary "
    "drawn from systematic theology."
)

BASELINE_TEXTS = [
    "A brief baseline sample discussing systematic theology and its scope.",
    "Another baseline sample, reflecting on pastoral ministry and formation.",
    "A third baseline sample considering the discipline of biblical exegesis.",
]


def _mk_state(student_id: str, texts: list[str], seed: int) -> StudentState:
    samples = [
        BaselineSample(
            text=t,
            vector=np.clip(np.random.RandomState(seed + i).normal(0.5, 0.1, FEATURE_DIM), 0.0, 1.0),
            provenance="proctored",
            auth_weight=1.0,
            assignment=f"a{i}",
        )
        for i, t in enumerate(texts)
    ]
    return StudentState(student_id=student_id, samples=samples)


# Same-tenant peer pool for NULL_MODEL=impostor: 3 peers (>= MIN_IMPOSTOR_STUDENTS)
# x 2 samples each (>= MIN_IMPOSTOR_VECTORS), built once — deterministic, reused
# read-only across every combo so building it doesn't dominate test runtime.
_PEER_STATES = [
    _mk_state(f"matrix:peer{i}", [f"peer sample a{i}", f"peer sample b{i}"], seed=200 + i * 10)
    for i in range(3)
]


def _run(monkeypatch, env: dict) -> Layer7Output:
    """Apply `env` (value=None deletes the var) and run one submission through
    the exact production wiring api.py uses: run_adaptive_pipeline() for the
    context/adaptive flags, then score() with a ScoringConfig built from the
    resulting environment."""
    for key, val in env.items():
        if val is None:
            monkeypatch.delenv(key, raising=False)
        else:
            monkeypatch.setenv(key, val)

    state = _mk_state("matrix:stu", BASELINE_TEXTS, seed=100)

    enable_manifest = os.environ.get("CONTEXT_MANIFEST_ENABLED") == "1"
    enable_adaptive = os.environ.get("ADAPTIVE_WEIGHTS_ENABLED") == "1"
    adaptive = run_adaptive_pipeline(
        SUBMISSION_TEXT,
        state,
        "matrix-submission",
        enable_manifest=enable_manifest,
        enable_adaptive_weights=enable_adaptive,
    )

    scoring_config = ScoringConfig.from_env()
    impostor_stats = None
    if scoring_config.null_model == "impostor":
        impostor_stats = build_impostor_stats(state.student_id, [state, *_PEER_STATES])

    return score(
        state,
        adaptive.vector,
        adaptive.feat_dict,
        submission_id="matrix-submission",
        adaptive_weights=adaptive.adaptive_weights,
        manifest=adaptive.manifest,
        n_tokens=len(SUBMISSION_TEXT.split()),
        impostor_stats=impostor_stats,
        scoring_config=scoring_config,
    )


def _score(monkeypatch, combo, null) -> Layer7Output:
    env = dict(zip(FLAGS, combo, strict=True))
    env["NULL_MODEL"] = null
    return _run(monkeypatch, env)


@pytest.mark.parametrize("combo", MATRIX, ids=["".join(c) for c in MATRIX])
@pytest.mark.parametrize("null", NULLS)
def test_every_combo_scores_in_range_with_action(monkeypatch, combo, null):
    out = _score(monkeypatch, combo, null)
    assert 0.0 <= out.authorship.deviation_score <= 1.0
    assert out.recommendation.action in {
        "no_action",
        "monitor",
        "schedule_conversation",
        "escalate",
    }


def test_default_flags_match_all_off_exactly(monkeypatch):
    """Flags unset must behave byte-identically to explicitly '0'/'none'
    (Phase-1 guarantee)."""
    unset = _run(monkeypatch, dict.fromkeys(FLAGS + ["NULL_MODEL"]))
    explicit = _score(monkeypatch, ("0", "0", "0"), "none")
    assert unset.authorship.deviation_score == pytest.approx(
        explicit.authorship.deviation_score, abs=1e-12
    )
    assert unset.recommendation.action == explicit.recommendation.action


def test_null_model_is_attach_only(monkeypatch):
    """NULL_MODEL=impostor may attach llr_deviation_score but must never
    change deviation_score or the action (documented attach-only contract)."""
    off = _score(monkeypatch, ("1", "1", "0"), "none")
    on = _score(monkeypatch, ("1", "1", "0"), "impostor")
    assert on.authorship.deviation_score == pytest.approx(off.authorship.deviation_score, abs=1e-12)
    assert on.recommendation.action == off.recommendation.action
    assert off.authorship.llr_deviation_score is None
    assert on.authorship.llr_deviation_score is not None
