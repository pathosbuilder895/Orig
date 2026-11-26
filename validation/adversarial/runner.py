"""
validation/adversarial/runner.py — real-scoring runner (Task 18).

Connects the offline red-team harness built across Tasks 13-17
(`profiles.VictimProfile` / `build_victim_profiles`,
`generators.MechanicalObfuscation`, `poisoning.poison_profile`) to
`original.*`'s real Born-rule scoring engine, through two paths:

  - "score" (fast): builds a `StudentState` directly from baseline
    `BaselineSample`s and calls `original.quantum.scoring.score()`
    in-process — the exact call pattern `validation/calibration.py`
    already uses (see its lines ~180-260). No HTTP, no drift gate, no
    auth — just the scoring math. NOT the live path: it extracts the
    submission with `compute_full_features(text, baselines)` where the
    live route (manifest off) uses `extract_features`, and the two differ
    on a handful of comparison features (measured 7 on one holdout,
    2026-10-21 review). No gate reads this path; report.py scores every
    cell with path="api".

  - "api" (deployment-shaped): drives the REAL FastAPI app in-process
    via `fastapi.testclient.TestClient` against
    `run.load_legacy_demo_app()` — the same pattern
    `tests/test_baseline_provenance_authz.py` uses. Baseline samples go
    through `POST /students/{id}/baseline` (real provenance
    authorization AND the Phase 8 drift gate — see "Drift gate and the
    API path" below); submissions go through `POST
    /students/{id}/score` (the real router, real auth resolution, real
    response schema). No live server process is started; this is one
    real request/response cycle through the actual ASGI app.

Design decisions
=================

1. Scope of `run_attack` — ONE profile/attack/path per call
-------------------------------------------------------------
The brief's headline metrics ("genuine-holdout FPR at N in {3,5,10}",
"per-action-bar impostor catch rate", ...) are properties of a
POPULATION of victims scored under a given (attack, path, N), not of
any single victim. `run_attack` deliberately knows nothing about N
sweeps or victim populations — it scores exactly the one `VictimProfile`
it is given, once, and returns an `AttackResult` carrying the raw
per-document action lists plus a couple of convenience aggregates
(`holdout_max_action`, `impostor_max_action`). A caller builds profiles
at each N via `build_victim_profiles(n, seed)`, calls `run_attack` once
per (profile, attack, path), and feeds the resulting list of
`AttackResult`s to `aggregate_attack_results()` below, which is where
the brief's actual headline numbers get computed. This keeps
`run_attack` a pure, single-purpose scoring primitive that Task 19's
gates can call directly without inheriting any sweep/aggregation
policy baked into it.

2. The `attack` parameter — five supported strings
-----------------------------------------------------
  - "none": score the genuine holdout / impostor docs exactly as given,
    against the victim's own unmodified baseline. The control case
    every other attack is compared against.
  - "mechanical_obfuscation": applies Task 14's `MechanicalObfuscation`
    to the SUBMISSION being scored (both the genuine holdout and the
    impostor docs), leaving the baseline untouched. Per the threat
    model (docs/superpowers/specs/2026-09-20-adversarial-verification-
    threat-model-design.md §1 "Why this is a verification problem, not
    an attribution problem"): obfuscating a submission is NOT expected
    to help an attacker evade a one-class verifier — it helps Original,
    by making the submission look less like the claimed author's own
    voice. Included anyway as a sanity check: if this attack ever
    showed impostor docs evading MORE than the "none" control, that
    would itself be a finding worth flagging in Task 19/20, not a
    result to expect.
  - "obfuscated_baselines" / "sigma_inflation" / "outsourced_baselines":
    the three real baseline-poisoning attacks from Task 17's
    `poisoning.poison_profile`. Each calls `poison_profile(profile,
    mode)` BEFORE building the scoring baseline, so the state/
    StudentState is built from the POISONED `baselines`, never the
    original. `genuine_holdout` and `impostor_docs` are always scored
    as-is (poisoning.py never touches them — see its module docstring).

3. Imitation success vs. poisoning success
-----------------------------------------------
Both are defined as "fraction of `impostor_docs` that score at
`no_action`" against the baseline actually used for that attack — i.e.
the SAME formula, split into two fields by which side of the system the
attack touches, per the threat-model taxonomy
(docs/superpowers/specs/2026-09-20-adversarial-verification-threat-
model-design.md §1, attacker-taxonomy table rows 1-3):

  - `imitation_success` is populated for attacks that leave the
    baseline untouched ("none", "mechanical_obfuscation") — it answers
    "how often does an impostor document, as submitted (possibly
    obfuscated), pass as the claimed author against their REAL
    baseline?"
  - `poisoning_success` is populated for the three baseline-poisoning
    attacks — it answers "after the baseline itself has been corrupted,
    how often does an impostor document now pass as the claimed
    author?" This is the reading the taxonomy table's own language
    supports directly: row 1 ("a later AI/ghostwritten paper matches"
    the obfuscated baseline), row 2 ("someone else writes the
    baselines" so a ghostwriter's future work matches it), and row 3
    ("shrinking every later z" — a wider baseline_std widens the
    accept band for anything, including impostor material). All three
    describe the poisoned baseline making OTHER people's writing look
    legitimate, not the victim's own recognition of themselves.

    The alternative reading considered — "does poisoning still let the
    victim's OWN genuine holdout score at no_action" (poisoning
    succeeding at not breaking self-recognition while corrupting what
    counts as "them") — is real and worth measuring, but is NOT what
    this field reports as "success": it is a *precondition* for a
    poisoning attack to be worth running at all (an attacker doesn't
    poison their baseline if it makes their own future genuine work get
    flagged), not the attack's payoff. That number is not thrown away —
    `holdout_actions` is always populated (scored against whatever
    baseline was actually used, poisoned or not), so a caller/Task 19
    can compute "did poisoning preserve genuine recognition" directly
    from the raw list without this module needing a second named
    "success" field for it.

    Caveat for Task 19: for `outsourced_baselines` and
    `sigma_inflation`, the donor material comes from
    `build_victim_profiles`'s general impostor/other-author pool
    (`poisoning._other_author_profile` / the variance-maximizing search
    in `_sigma_inflation`), not from a tracked "this specific donor's
    future writing." `impostor_docs` (a handful of OTHER authors'
    documents, not the literal donor) is used as the stand-in for "a
    ghostwriter's future submission in a similar register" — a
    reasonable proxy, but not literally the donor's own subsequent
    work. `poison_profile`'s return value carries no donor identity to
    thread through, and adding that would mean changing `poisoning.py`,
    which is out of this task's scope.

4. The API path and the drift gate
---------------------------------------
`POST /students/{id}/baseline` runs the real Phase 8 drift gate
(`StudentState.check_drift`, `original/routers/students_baseline.py`):
a baseline sample whose anchor-tier features are too far from the
already-accepted baseline mean is HELD (202/409), not admitted. For
"none" and "mechanical_obfuscation" this never fires in practice (the
victim's own baseline documents are, by construction, consistent with
each other). For the three poisoning attacks it can genuinely fire —
`sigma_inflation` and `outsourced_baselines` deliberately mix in a
different author's writing, which is exactly the kind of outlier the
drift gate exists to catch. When a baseline POST comes back 202 or 409
the sample is NOT added to the student's state (mirroring the router's
own behaviour) and `AttackResult.baseline_rejected_count` is
incremented — this is a genuine, reportable difference between the
"score" and "api" paths for poisoning attacks under `path="api"`: the
in-process fast path always scores against every poisoned baseline
document as given (matching `calibration.py`'s direct
`StudentState(samples=...)` construction, which has no drift gate at
all), while the API path may end up scoring against a PARTIALLY
poisoned baseline if the gate held some of the poisoned samples. Task
19 should read `baseline_rejected_count` before comparing "score" vs
"api" numbers for a poisoning attack — a non-zero count means the two
paths were not actually scoring against the same baseline content.

If the gate holds enough of the baseline to leave fewer than
`MIN_BASELINE_SAMPLES` admitted, the score route refuses with a 422
`insufficient_baseline` and the result carries `scoring_refused=True` with
empty action lists: the live system abstained, and a caller must count that
as neither a flag nor a pass.

Student-id isolation: `run_attack` mints a fresh
`f"adv-{victim_id}-{attack}-{uuid4().hex}"` student id for every
`path="api"` call (see `_new_student_id`), so repeated calls — from a
retry, from scoring the same profile under two different attacks, or
from two different test runs against a shared dev database — never
collide with stale state left by a previous call. This is deliberately
NOT a pytest fixture (`runner.py` is product code Task 19/20 will also
call directly, not only from tests); the tests in
`tests/adversarial/test_runner.py` additionally use the repo's
`store_reset` fixture for a fully clean SQLite file per test, but
`run_attack` itself works standalone without it.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

import numpy as np

from original.constants import ACTION_THRESHOLDS, ALL_FEATURE_CODES
from original.features.pipeline import compute_full_features, feature_vector
from original.quantum.scoring import score as quantum_score
from original.quantum.state import BaselineSample, StudentState
from validation.adversarial.generators import MechanicalObfuscation
from validation.adversarial.poisoning import baseline_variance_proxy, poison_profile
from validation.adversarial.profiles import VictimProfile

# Canonical severity-ordered action bars, per the brief: "use
# ACTION_THRESHOLDS.keys() ... as your canonical ordered list of action
# bars". Materialized once as a tuple so index() gives a stable severity
# rank (no_action=0 < monitor=1 < schedule_conversation=2 < escalate=3).
ACTION_ORDER: tuple[str, ...] = tuple(ACTION_THRESHOLDS.keys())

# The full set of `attack` strings run_attack accepts — see module
# docstring §2 for what each one does structurally.
ATTACKS: tuple[str, ...] = (
    "none",
    "mechanical_obfuscation",
    "obfuscated_baselines",
    "sigma_inflation",
    "outsourced_baselines",
)

# The three real poisoning modes, re-exported from poisoning.MODES for a
# single source of truth on which attack strings poison the BASELINE
# (vs. "mechanical_obfuscation", which poisons the SUBMISSION).
_POISONING_ATTACKS = frozenset(("obfuscated_baselines", "sigma_inflation", "outsourced_baselines"))

_PATHS: tuple[str, ...] = ("score", "api")

# HTTP statuses students_baseline.add_baseline returns when the drift
# gate holds a sample instead of admitting it (see module docstring §4).
_DRIFT_HELD_STATUSES = frozenset((202, 409))


@dataclass(frozen=True)
class AttackResult:
    """One (profile, attack, path) scoring outcome.

    All fields describe the SINGLE profile this result came from; see
    the module docstring §1 for why aggregation across profiles/N lives
    in `aggregate_attack_results`, not here.

    Attributes
    ----------
    victim_id, attack, path, n_baselines
        Identify what was run. `n_baselines` is `len(profile.baselines)`
        (before any poisoning attack — poisoning never changes the
        baseline COUNT, only its content) and is the key
        `aggregate_attack_results` groups the "FPR at N" metric by.
    holdout_actions, impostor_actions
        The raw `recommendation.action` string for every genuine-holdout
        / impostor document scored, in `profile.genuine_holdout` /
        `profile.impostor_docs` order. Always scored against whatever
        baseline this (attack, path) combination actually used —
        poisoned, for the three poisoning attacks; the victim's own
        baseline otherwise. The raw material every headline metric in
        `aggregate_attack_results` is built from.
    holdout_max_action, impostor_max_action
        The single most-severe action (by `ACTION_ORDER`) among
        `holdout_actions` / `impostor_actions` respectively. Convenience
        scalars for the common "did anything genuine escalate" / "did
        anything impostor get caught" check; `None` only when the
        corresponding action list is empty (a profile with no
        holdout/impostor documents at all).
    imitation_success, poisoning_success
        Fraction of `impostor_actions` at `no_action` — see module
        docstring §3 for which one is populated for which `attack`, and
        why. Exactly one of the two is non-None whenever
        `impostor_actions` is non-empty; both are `None` when
        `impostor_actions` is empty (nothing to compute a fraction
        over).
    sigma_proxy
        `poisoning.baseline_variance_proxy()` over the baseline text
        SET actually scored against (poisoned, for poisoning attacks;
        the victim's own otherwise) — the raw material for the brief's
        "σ-inflation curve" once aggregated across N by
        `aggregate_attack_results`.
    baseline_rejected_count
        `path="api"` only: how many of the (possibly poisoned) baseline
        documents the real Phase 8 drift gate held (202/409) rather
        than admitting, see module docstring §4. Always `0` for
        `path="score"`, which has no drift gate.
    holdout_scores, impostor_scores
        The `deviation_score` behind each entry of `holdout_actions` /
        `impostor_actions`, same order. The gates' separation legs (an
        AUROC of attack vs. genuine scores) need the continuous score,
        not just the action band it falls in.
    mean_baseline_std
        The real-feature spread of the baseline actually scored against
        (after any drift-gate holds, on the API path): the mean, over the
        features `validation.measurability.measurable_indices()` lists, of
        the per-feature standard deviation across the contributing
        samples, WITHOUT `StudentState.baseline_std`'s `0.15 / sqrt(N)`
        floor. This is what the sigma-inflation gate (G-A5) reads as
        "did sigma grow", as opposed to `sigma_proxy`'s text-level
        stand-in. Floored or dead features would confound it: the floor
        RISES when the drift gate holds a sample (fewer samples admitted),
        so a held injection would read as growth. A fixed feature set
        (not the active mask, which itself changes under poisoning) keeps
        conditions comparable. `None` below two contributing samples.
    baseline_integrity
        The report-only `baseline_integrity` block (dict) for that
        baseline: read from the live `/score` response on the API path,
        built with `original.baseline_integrity.build_baseline_integrity`
        on the fast path. `None` when it abstained.
    held_baseline_indices
        `path="api"` only: positions (into the scored baseline text
        list) of the documents the drift gate held. Lets a caller tell
        whether the gate held the INJECTED document of a poisoned
        baseline or an innocent one.
    scoring_refused
        `path="api"` only: True when the route declined to score at all
        because the drift gate left fewer admitted baselines than
        `MIN_BASELINE_SAMPLES` (a 422 `insufficient_baseline`). The action
        and score lists are then empty: the live system abstained, which
        is neither a false positive nor a catch.
    holdout_probabilities, impostor_probabilities
        `authorship.authorship_probability` per scored document, same
        order. Collections (Bluebook) marks a sealed exam "worth a look"
        from this number, not from the action (`bbSealStatus` in
        demo/bluebook/Exam.jsx), so the report can show that mark too.
    """

    victim_id: str
    attack: str
    path: str
    n_baselines: int
    holdout_actions: tuple[str, ...]
    impostor_actions: tuple[str, ...]
    holdout_max_action: str | None
    impostor_max_action: str | None
    imitation_success: float | None
    poisoning_success: float | None
    sigma_proxy: float | None
    baseline_rejected_count: int = 0
    holdout_scores: tuple[float, ...] = ()
    impostor_scores: tuple[float, ...] = ()
    mean_baseline_std: float | None = None
    baseline_integrity: dict | None = None
    held_baseline_indices: tuple[int, ...] = ()
    scoring_refused: bool = False
    holdout_probabilities: tuple[float, ...] = ()
    impostor_probabilities: tuple[float, ...] = ()


def _max_action(actions: tuple[str, ...]) -> str | None:
    if not actions:
        return None
    return max(actions, key=ACTION_ORDER.index)


def run_attack(
    profile: VictimProfile,
    attack: str,
    path: str = "score",
    *,
    client=None,
) -> AttackResult:
    """Score one victim profile under one attack, via one scoring path.

    Parameters
    ----------
    profile : VictimProfile
        The (unpoisoned) victim material — baselines, genuine holdout,
        impostor docs.
    attack : str
        One of `ATTACKS` — see module docstring §2.
    path : str
        "score" (default) for the fast in-process `original.quantum.
        scoring.score()` path, or "api" for the FastAPI `TestClient`
        deployment-shaped path. See module docstring's top section.
    client : fastapi.testclient.TestClient | None
        Only used when `path="api"`. If omitted, a client is built from
        `run.load_legacy_demo_app()` (module-level cached — see
        `_default_api_client`). Callers that want isolation from
        whatever store that default app is pointed at (tests do, via
        the `store_reset` fixture) should pass their own client.

    Raises
    ------
    ValueError
        If `attack` is not in `ATTACKS`, or `path` is not "score"/"api".
    """
    if attack not in ATTACKS:
        raise ValueError(f"unknown attack {attack!r}; expected one of {ATTACKS}")
    if path not in _PATHS:
        raise ValueError(f"unknown path {path!r}; expected one of {_PATHS}")

    n_baselines = len(profile.baselines)

    if attack in _POISONING_ATTACKS:
        scored_profile = poison_profile(profile, attack)
        baseline_texts = scored_profile.baselines
        obfuscator = None
    elif attack == "mechanical_obfuscation":
        scored_profile = profile
        baseline_texts = profile.baselines
        obfuscator = MechanicalObfuscation(seed=_submission_seed(profile.victim_id))
    else:  # "none"
        scored_profile = profile
        baseline_texts = profile.baselines
        obfuscator = None

    holdout_texts = _maybe_transform(profile.genuine_holdout, obfuscator)
    impostor_texts = _maybe_transform(profile.impostor_docs, obfuscator)

    if path == "score":
        outcome = _run_fast_path(profile.victim_id, baseline_texts, holdout_texts, impostor_texts)
    else:
        outcome = _run_api_path(
            profile.victim_id, attack, baseline_texts, holdout_texts, impostor_texts, client
        )
    holdout_actions = [action for action, _, _ in outcome.holdout]
    impostor_actions = [action for action, _, _ in outcome.impostor]

    imitation_success = None
    poisoning_success = None
    if impostor_actions:
        no_action_fraction = sum(1 for a in impostor_actions if a == "no_action") / len(
            impostor_actions
        )
        if attack in _POISONING_ATTACKS:
            poisoning_success = no_action_fraction
        else:
            imitation_success = no_action_fraction

    return AttackResult(
        victim_id=profile.victim_id,
        attack=attack,
        path=path,
        n_baselines=n_baselines,
        holdout_actions=tuple(holdout_actions),
        impostor_actions=tuple(impostor_actions),
        holdout_max_action=_max_action(tuple(holdout_actions)),
        impostor_max_action=_max_action(tuple(impostor_actions)),
        imitation_success=imitation_success,
        poisoning_success=poisoning_success,
        sigma_proxy=baseline_variance_proxy(baseline_texts),
        baseline_rejected_count=len(outcome.held_indices),
        holdout_scores=tuple(score for _, score, _ in outcome.holdout),
        impostor_scores=tuple(score for _, score, _ in outcome.impostor),
        mean_baseline_std=outcome.mean_baseline_std,
        baseline_integrity=outcome.baseline_integrity,
        held_baseline_indices=tuple(outcome.held_indices),
        scoring_refused=outcome.scoring_refused,
        holdout_probabilities=tuple(p for _, _, p in outcome.holdout),
        impostor_probabilities=tuple(p for _, _, p in outcome.impostor),
    )


@dataclass(frozen=True)
class _PathOutcome:
    """What one scoring path hands back to `run_attack`: (action,
    deviation_score, authorship_probability) per scored document, plus what
    the path can say about the baseline it scored against."""

    holdout: list[tuple[str, float, float]]
    impostor: list[tuple[str, float, float]]
    held_indices: list[int]
    mean_baseline_std: float | None
    baseline_integrity: dict | None
    scoring_refused: bool = False


def _mean_baseline_std(state: StudentState | None) -> float | None:
    """See `AttackResult.mean_baseline_std`."""
    from validation.measurability import measurable_indices

    if state is None:
        return None
    contributing = [s for s in state.samples if s.auth_weight > 0]
    if len(contributing) < 2:
        return None
    vectors = np.stack([s.vector for s in contributing])[:, measurable_indices()]
    return float(vectors.std(axis=0).mean())


def _submission_seed(victim_id: str) -> int:
    """Deterministic seed for the mechanical_obfuscation submission
    transform, namespaced separately from poisoning.py's own
    `_seed_int` (different module, same content-addressed convention:
    a seed derived from victim_id, not wall-clock randomness)."""
    import hashlib

    digest = hashlib.sha256(f"runner_mechanical_obfuscation:{victim_id}".encode()).hexdigest()
    return int(digest[:16], 16)


def _maybe_transform(texts: list[str], obfuscator: MechanicalObfuscation | None) -> list[str]:
    if obfuscator is None:
        return list(texts)
    return [obfuscator.transform(text) for text in texts]


# ── Fast ("score") path ──────────────────────────────────────────────────


def _build_state(victim_id: str, baseline_texts: list[str]) -> StudentState:
    """Build a StudentState directly from baseline text, mirroring
    validation/calibration.py's call pattern exactly (BaselineSample per
    text, provenance="verified", auth_weight=0.7) — no drift gate, no
    router, no auth: just the scoring math."""
    samples = [
        BaselineSample(
            text=text,
            vector=feature_vector(text),
            provenance="verified",
            auth_weight=0.7,
            assignment="baseline",
            submitted_at="2026-01-01T00:00:00",
        )
        for text in baseline_texts
    ]
    return StudentState(student_id=victim_id, samples=samples)


def _score_fast(
    state: StudentState, text: str, baseline_texts: list[str], submission_id: str
) -> tuple[str, float, float]:
    features = compute_full_features(text, baseline_texts)
    sub_vector = np.array([features[c] for c in ALL_FEATURE_CODES], dtype=np.float64)
    result = quantum_score(
        state,
        sub_vector,
        features,
        submission_id=submission_id,
        n_tokens=len(text.split()),
    )
    return (
        result.recommendation.action,
        float(result.authorship.deviation_score),
        float(result.authorship.authorship_probability),
    )


def _run_fast_path(
    victim_id: str,
    baseline_texts: list[str],
    holdout_texts: list[str],
    impostor_texts: list[str],
) -> _PathOutcome:
    from dataclasses import asdict

    from original.baseline_integrity import build_baseline_integrity

    state = _build_state(victim_id, baseline_texts)
    integrity = build_baseline_integrity(state)
    return _PathOutcome(
        holdout=[
            _score_fast(state, text, baseline_texts, f"{victim_id}-holdout-{i}")
            for i, text in enumerate(holdout_texts)
        ],
        impostor=[
            _score_fast(state, text, baseline_texts, f"{victim_id}-impostor-{i}")
            for i, text in enumerate(impostor_texts)
        ],
        held_indices=[],  # no drift gate on this path
        mean_baseline_std=_mean_baseline_std(state),
        baseline_integrity=asdict(integrity) if integrity is not None else None,
    )


# ── API path ──────────────────────────────────────────────────────────────

_DEFAULT_API_CLIENT = None


def _default_api_client():
    """Lazily build (and cache) a TestClient over the real app, for
    callers of `run_attack(..., path="api")` that don't supply their
    own `client`. Cached at module scope because `run.
    load_legacy_demo_app()` already returns a process-wide singleton
    app object (see run.py's own docstring) — wrapping it in a fresh
    TestClient every call would add nothing but overhead."""
    global _DEFAULT_API_CLIENT
    if _DEFAULT_API_CLIENT is None:
        from fastapi.testclient import TestClient

        import run as run_module

        _DEFAULT_API_CLIENT = TestClient(run_module.load_legacy_demo_app())
    return _DEFAULT_API_CLIENT


def _new_student_id(victim_id: str, attack: str) -> str:
    """Fresh, collision-proof student id for one path="api" run_attack
    call — see module docstring §4 on why this (not a pytest fixture)
    is the isolation strategy: run_attack is product code Task 19/20
    calls directly, not only from tests."""
    return f"adv-{victim_id}-{attack}-{uuid.uuid4().hex}"


def _post_baseline(client, student_id: str, text: str, assignment: str) -> bool:
    """POST one baseline sample. Returns True if the drift gate held it
    (202/409) rather than admitting it; raises on any other non-2xx
    status (an unexpected failure, not an expected gate outcome)."""
    resp = client.post(
        f"/students/{student_id}/baseline",
        json={"text": text, "provenance": "verified", "assignment": assignment},
    )
    if resp.status_code in _DRIFT_HELD_STATUSES:
        return True
    if resp.status_code != 200:
        raise RuntimeError(
            f"unexpected baseline POST failure for {student_id!r}: "
            f"{resp.status_code} {resp.text}"
        )
    return False


def _post_score(client, student_id: str, text: str, submission_id: str) -> dict | None:
    """One `/score` call. Returns `None` when the route declines to score
    because too few baselines were admitted (422 `insufficient_baseline`,
    `students_scoring._require_min_baseline`): the drift gate can hold
    enough of a poisoned baseline to drop below the minimum, and the live
    system then abstains. That is an outcome to record, not a crash."""
    resp = client.post(
        f"/students/{student_id}/score",
        json={"text": text, "submission_id": submission_id},
    )
    if resp.status_code == 422:
        detail = resp.json().get("detail")
        if isinstance(detail, dict) and detail.get("code") == "insufficient_baseline":
            return None
    if resp.status_code != 200:
        raise RuntimeError(
            f"unexpected score POST failure for {student_id!r}: {resp.status_code} {resp.text}"
        )
    return resp.json()


def _action_and_score(body: dict) -> tuple[str, float, float]:
    authorship = body["authorship"]
    return (
        body["recommendation"]["action"],
        float(authorship["deviation_score"]),
        float(authorship["authorship_probability"]),
    )


def _run_api_path(
    victim_id: str,
    attack: str,
    baseline_texts: list[str],
    holdout_texts: list[str],
    impostor_texts: list[str],
    client,
) -> _PathOutcome:
    from original.routers._shared import _repo

    if client is None:
        client = _default_api_client()

    student_id = _new_student_id(victim_id, attack)

    held = [
        i
        for i, text in enumerate(baseline_texts)
        if _post_baseline(client, student_id, text, assignment=f"baseline-{i}")
    ]

    holdout_bodies = [
        _post_score(client, student_id, text, submission_id=f"{student_id}-holdout-{i}")
        for i, text in enumerate(holdout_texts)
    ]
    impostor_bodies = [
        _post_score(client, student_id, text, submission_id=f"{student_id}-impostor-{i}")
        for i, text in enumerate(impostor_texts)
    ]
    # The baseline is fixed once the uploads finish, so either every score
    # call was refused or none was.
    refused = any(b is None for b in holdout_bodies + impostor_bodies)
    holdout_bodies = [b for b in holdout_bodies if b is not None]
    impostor_bodies = [b for b in impostor_bodies if b is not None]
    # Scoring never changes the baseline, so every response carries the same
    # integrity block; read it off the first one.
    first = (holdout_bodies + impostor_bodies)[:1]
    return _PathOutcome(
        holdout=[_action_and_score(b) for b in holdout_bodies],
        impostor=[_action_and_score(b) for b in impostor_bodies],
        held_indices=held,
        mean_baseline_std=_mean_baseline_std(_repo().get(student_id)),
        baseline_integrity=first[0].get("baseline_integrity") if first else None,
        scoring_refused=refused,
    )


# ── Aggregation ───────────────────────────────────────────────────────────


def aggregate_attack_results(results: list[AttackResult]) -> dict:
    """Compute the brief's headline metrics from a list of per-profile
    `AttackResult`s (see module docstring §1 for why this — not
    `run_attack` itself — owns the N-sweep/population aggregation).

    Returns a dict with:

      - "n_results": len(results).
      - "impostor_catch_rate": {action: fraction of every
        `impostor_actions` entry across ALL results whose severity is
        AT OR ABOVE that action bar}, keyed by every action in
        `ACTION_ORDER`. E.g. the "escalate" entry is the overall
        impostor catch rate at the escalate bar; "no_action" is always
        1.0 (every action is at-or-above the lowest bar) and is kept
        anyway so the dict always has all four documented keys.
      - "holdout_fpr_by_n": {n_baselines: fraction of that N's pooled
        `holdout_actions` that are NOT "no_action"} — any escalation at
        all on genuine writing counts as a false positive. Keyed by
        whatever `n_baselines` values are actually present in
        `results`, so a caller sweeping N in {3, 5, 10} gets exactly
        those three keys (once results at each N have been passed in).
      - "imitation_success_mean" / "poisoning_success_mean": mean of
        the corresponding `AttackResult` field over results where it is
        not None; `None` if no result populated it.
      - "sigma_curve": {n_baselines: {attack: mean sigma_proxy}} — the
        brief's "σ-inflation curve" once several (attack, N) cells have
        been aggregated. A caller comparing `attack="sigma_inflation"`
        against the `attack="none"` control at the same N reads both
        entries under the same `n_baselines` key.
    """
    catch_counts = {action: 0 for action in ACTION_ORDER}
    total_impostor = 0
    for result in results:
        for action in result.impostor_actions:
            rank = ACTION_ORDER.index(action)
            for bar_index, bar in enumerate(ACTION_ORDER):
                if rank >= bar_index:
                    catch_counts[bar] += 1
            total_impostor += 1
    impostor_catch_rate = {
        bar: (catch_counts[bar] / total_impostor if total_impostor else None)
        for bar in ACTION_ORDER
    }

    holdout_by_n: dict[int, list[str]] = {}
    for result in results:
        holdout_by_n.setdefault(result.n_baselines, []).extend(result.holdout_actions)
    holdout_fpr_by_n = {
        n: sum(1 for a in actions if a != "no_action") / len(actions)
        for n, actions in holdout_by_n.items()
        if actions
    }

    imitation_values = [r.imitation_success for r in results if r.imitation_success is not None]
    poisoning_values = [r.poisoning_success for r in results if r.poisoning_success is not None]

    sigma_curve: dict[int, dict[str, list[float]]] = {}
    for result in results:
        if result.sigma_proxy is None:
            continue
        by_attack = sigma_curve.setdefault(result.n_baselines, {})
        by_attack.setdefault(result.attack, []).append(result.sigma_proxy)
    sigma_curve_means = {
        n: {attack: sum(values) / len(values) for attack, values in by_attack.items()}
        for n, by_attack in sigma_curve.items()
    }

    return {
        "n_results": len(results),
        "impostor_catch_rate": impostor_catch_rate,
        "holdout_fpr_by_n": holdout_fpr_by_n,
        "imitation_success_mean": (
            sum(imitation_values) / len(imitation_values) if imitation_values else None
        ),
        "poisoning_success_mean": (
            sum(poisoning_values) / len(poisoning_values) if poisoning_values else None
        ),
        "sigma_curve": sigma_curve_means,
    }
