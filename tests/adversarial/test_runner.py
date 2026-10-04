"""
tests/adversarial/test_runner.py — real-scoring runner (Task 18).

Covers `validation.adversarial.runner.run_attack` and
`aggregate_attack_results`, the piece that finally connects the offline
red-team profiles/generators/poisoning machinery (Tasks 13-17) to
`original.*`'s real Born-rule scoring engine — both the "fast" in-process
path (`original.quantum.scoring.score`, mirroring
`validation/calibration.py`'s call pattern) and the "api" deployment-shaped
path (FastAPI `TestClient` against the real router, mirroring
`tests/test_baseline_provenance_authz.py`).

A hand-built TINY fixture is used for every test here (not the 13-victim
public_authors corpus) so the suite runs in well under a second per
`score()` call — see the module docstring on `run_attack` for why a real
corpus run belongs to Task 19/20, not here.
"""

from __future__ import annotations

import pytest

from validation.adversarial.profiles import VictimProfile
from validation.adversarial.runner import (
    ATTACKS,
    AttackResult,
    aggregate_attack_results,
    run_attack,
)

# Three short baseline documents in one distinctive, consistent voice:
# long subordinate clauses, formal register, semicolons, "one must",
# "it is precisely". A genuine holdout in the SAME voice; a wildly
# different, short, informal impostor document.
_BASELINE_TEXTS = [
    (
        "It is precisely in the quiet discipline of daily labor that one must "
        "locate the truest measure of a life; not in the rare and celebrated "
        "hour, but in the accumulation of ordinary hours faithfully kept. The "
        "careful reader will notice that this claim is neither novel nor "
        "fashionable, and yet it withstands scrutiny precisely because it "
        "refuses the seduction of the exceptional."
    ),
    (
        "One must resist the temptation to mistake motion for progress; the "
        "two are related only by accident, and it is precisely the failure "
        "to distinguish them that accounts for so much wasted effort. A "
        "disciplined mind, examining its own habits with patience, will "
        "generally find that the quiet hours accomplish what the frantic "
        "ones only promise."
    ),
    (
        "The habit of careful revision is, it is precisely argued here, the "
        "single most reliable indicator of a serious mind; one must return "
        "again and again to the same sentence until it yields its final "
        "shape. Those who skip this discipline mistake haste for fluency, "
        "and the careful reader is rarely deceived by the difference."
    ),
]

_GENUINE_HOLDOUT = (
    "It is precisely the unglamorous middle of a project where one must "
    "keep faith with the original intention; the beginning asks for "
    "courage and the end asks for polish, but the middle asks only for "
    "the plain, unremarked discipline of continuing. A careful reader of "
    "one's own work will recognize this stretch by its very lack of "
    "drama, and will not mistake that quiet for failure."
)

_IMPOSTOR_TEXT = (
    "ok so basically i just wing it lol, no plan no notes just vibes. "
    "grind hard, post the reel, check the numbers, repeat, that's the "
    "whole game tbh. overthinking it just kills the momentum ngl, you "
    "gotta move fast and break stuff, worry about the details never."
)


@pytest.fixture
def tiny_profile() -> VictimProfile:
    return VictimProfile(
        victim_id="tiny-fixture-victim",
        baselines=list(_BASELINE_TEXTS),
        genuine_holdout=[_GENUINE_HOLDOUT],
        impostor_docs=[_IMPOSTOR_TEXT],
    )


# ── Fast ("score") path ────────────────────────────────────────────────


def test_genuine_holdout_scores_below_escalate(tiny_profile):
    result = run_attack(tiny_profile, attack="none", path="score")
    assert result.holdout_max_action != "escalate"


def test_blatant_impostor_scores_at_or_above_monitor(tiny_profile):
    result = run_attack(tiny_profile, attack="none", path="score")
    assert result.impostor_max_action in ("monitor", "schedule_conversation", "escalate")


def test_metrics_dict_has_documented_keys(tiny_profile):
    result = run_attack(tiny_profile, attack="none", path="score")
    assert isinstance(result, AttackResult)
    assert result.victim_id == "tiny-fixture-victim"
    assert result.attack == "none"
    assert result.path == "score"
    assert result.n_baselines == 3
    assert result.holdout_actions == (result.holdout_max_action,)
    assert result.impostor_actions == (result.impostor_max_action,)
    assert result.imitation_success == pytest.approx(0.0)
    assert result.poisoning_success is None
    assert result.sigma_proxy is not None and result.sigma_proxy >= 0.0
    assert result.baseline_rejected_count == 0


def test_unknown_attack_raises(tiny_profile):
    with pytest.raises(ValueError):
        run_attack(tiny_profile, attack="not-a-real-attack", path="score")


def test_unknown_path_raises(tiny_profile):
    with pytest.raises(ValueError):
        run_attack(tiny_profile, attack="none", path="not-a-real-path")


def test_attacks_constant_documents_all_supported_strings():
    assert set(ATTACKS) == {
        "none",
        "mechanical_obfuscation",
        "obfuscated_baselines",
        "sigma_inflation",
        "outsourced_baselines",
    }


# ── Poisoning attacks (fast path) ──────────────────────────────────────


def test_outsourced_baselines_scores_against_poisoned_baseline(tiny_profile, monkeypatch):
    """outsourced_baselines must call poison_profile and score against the
    POISONED baseline text, not profile.baselines verbatim."""
    calls = []
    from validation.adversarial import runner as runner_mod

    real_poison_profile = runner_mod.poison_profile

    def _spy(profile, mode):
        calls.append((profile.victim_id, mode))
        return real_poison_profile(profile, mode)

    monkeypatch.setattr(runner_mod, "poison_profile", _spy)

    result = run_attack(tiny_profile, attack="outsourced_baselines", path="score")

    assert calls == [("tiny-fixture-victim", "outsourced_baselines")]
    assert result.attack == "outsourced_baselines"
    assert result.poisoning_success is not None
    assert result.imitation_success is None
    # The scored baseline text differs from the original victim's own —
    # sigma_proxy is computed over the poisoned baseline set actually used.
    from validation.adversarial.poisoning import baseline_variance_proxy, poison_profile

    poisoned = poison_profile(tiny_profile, "outsourced_baselines")
    assert poisoned.baselines != tiny_profile.baselines
    assert result.sigma_proxy == pytest.approx(baseline_variance_proxy(poisoned.baselines))


def test_mechanical_obfuscation_transforms_submissions_not_baseline(tiny_profile):
    result = run_attack(tiny_profile, attack="mechanical_obfuscation", path="score")
    assert result.attack == "mechanical_obfuscation"
    # Baseline is untouched by this attack — sigma_proxy over the ORIGINAL
    # baselines, same as the "none" control.
    none_result = run_attack(tiny_profile, attack="none", path="score")
    assert result.sigma_proxy == pytest.approx(none_result.sigma_proxy)
    assert result.poisoning_success is None
    assert result.imitation_success is not None


# ── Aggregation helper ──────────────────────────────────────────────────


def test_aggregate_attack_results_computes_headline_metrics(tiny_profile):
    none_result = run_attack(tiny_profile, attack="none", path="score")
    poisoned_result = run_attack(tiny_profile, attack="sigma_inflation", path="score")

    agg = aggregate_attack_results([none_result, poisoned_result])

    assert agg["n_results"] == 2
    assert set(agg["impostor_catch_rate"]) == {
        "no_action",
        "monitor",
        "schedule_conversation",
        "escalate",
    }
    assert 3 in agg["holdout_fpr_by_n"]
    assert agg["poisoning_success_mean"] == pytest.approx(poisoned_result.poisoning_success)
    assert agg["imitation_success_mean"] == pytest.approx(none_result.imitation_success)
    assert 3 in agg["sigma_curve"]
    assert "sigma_inflation" in agg["sigma_curve"][3]


def test_aggregate_attack_results_empty_list():
    agg = aggregate_attack_results([])
    assert agg["n_results"] == 0
    assert agg["imitation_success_mean"] is None
    assert agg["poisoning_success_mean"] is None


# ── API path ─────────────────────────────────────────────────────────────


@pytest.fixture
def api_client(store_reset):
    from fastapi.testclient import TestClient

    import run as run_module

    app = run_module.load_legacy_demo_app()
    return TestClient(app)


def test_api_path_genuine_holdout_and_impostor(tiny_profile, api_client):
    result = run_attack(tiny_profile, attack="none", path="api", client=api_client)

    assert result.path == "api"
    assert result.holdout_max_action != "escalate"
    assert result.impostor_max_action in ("monitor", "schedule_conversation", "escalate")
    assert result.baseline_rejected_count == 0


def test_api_path_uses_isolated_student_id_per_call(tiny_profile, api_client):
    """Two calls for the same profile must not collide — each gets its own
    fresh student_id so repeated runs don't inherit stale baseline state."""
    first = run_attack(tiny_profile, attack="none", path="api", client=api_client)
    second = run_attack(tiny_profile, attack="none", path="api", client=api_client)

    assert first.holdout_actions == second.holdout_actions
    assert first.impostor_actions == second.impostor_actions
