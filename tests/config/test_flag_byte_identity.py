"""T-15 — one byte-identity matrix over every score-affecting flag.

`docs/testing/08-config-deploy-readiness.md` §1. README principle 4 says
that with a flag off, output is bit-for-bit what it was before the flag
existed. That was proved flag-by-flag in scattered files
(`tests/test_flag_matrix.py` covers four; the fusion/AI/blend shadow files
cover theirs). This file makes it one matrix against two committed
snapshots, so "off is really off", "shadow only adds preview fields" and
"on is not inert" are checked in one place, and any change to default
output is a reviewed diff produced by
`scripts/update_score_snapshot.py`.

Two levels, two snapshots
-------------------------
* **Unit** — `tests/snapshots/score_default.json`: the full `Layer7Output`
  from `quantum.scoring.score()` under `ScoringConfig()` (every field at its
  documented default). `score()` never reads `os.environ` (except
  `RANK_REMEDIATION`, which `StudentState.density_matrix` reads), so these
  arms are driven by constructing a `ScoringConfig`.
* **API** — `tests/snapshots/score_default_api.json`: the
  `POST /students/{id}/score` response for the same fixed profile, with
  every flag env var *unset*. Flags that live in the router rather than in
  `ScoringConfig` (`CONTEXT_MANIFEST_ENABLED`, `GENRE_RESOLVER_V2`,
  `FUSED_SCORE_*`, …) can only be exercised here.

Both snapshots are `json.dumps(..., sort_keys=True, indent=2)` plus a
trailing newline. Floats are written at `repr` precision — never rounded —
so a 1-ULP change in the scoring math is a failing diff. numpy scalars are
converted with `.item()` and arrays with `.tolist()`.

Fixed profile
-------------
`tests/config/_flag_corpus.py`. One student, six literal baseline documents
(dated, so `LONGITUDINAL_DRIFT_ENABLED` is eligible) and one literal
submission, plus ten same-tenant peers with three documents each. Every
document clears `fusion.peers.MIN_WORDS` (300), which is the eligibility
floor the fused-score and style-authorship experts share, so those two
flags are exercised rather than abstaining. Ten peers clears
`style_authorship`'s floor and lets `fusion.peers.select_references` pick
its exact eight.

At the unit level the baseline/peer *vectors* are seeded
(`np.random.RandomState`), exactly as `tests/test_flag_matrix.py` does:
that keeps the unit snapshot a pure function of numpy's stable RNG rather
than of the installed spaCy/NLTK models. At the API level the claimed
student's baselines go through `POST /students/{id}/baseline`, so its
vectors are real extractions; the peers are written straight to the store
with seeded vectors because their vectors only ever feed the peer-pool
statistics.

Normalised API fields
---------------------
Exactly one key is normalised out of the API payloads, at every depth:
`created_at` (it appears as `context_manifest.created_at` and
`report.context_manifest.created_at`, and only when
`CONTEXT_MANIFEST_ENABLED=1`, so the committed default snapshot contains no
normalised value at all). `student_id`, `submission_id` and the assignment
labels are fixed literals supplied by this file, so nothing else needed
normalising — proved by `test_api_default_is_reproducible`, which scores
the same submission twice and requires byte-identity.

Per-flag outcome observed on this profile
-----------------------------------------
Recorded honestly, because an inert flag that reads as a pass is the trap
`GENRE_INVARIANT_WEIGHTS_ENABLED` fell into.

Flags whose arms are IDENTICAL when off, and what each does otherwise:

* `CONTEXT_MANIFEST_ENABLED` — on: differs, adds `context_manifest`.
* `ADAPTIVE_WEIGHTS_ENABLED` — on: differs (`deviation_score`).
* `GENRE_INVARIANT_WEIGHTS_ENABLED` — on: **uninformative**. Inert: the
  resolver reports this submission's genre as covered by the baseline, so
  the attenuation never fires. The trap this file exists to make visible.
* `GENRE_RESOLVER_V2` — shadow: preview-only, exactly
  `genre.shadow_primary` + `genre.shadow_confidence`; on: differs
  (`genre.primary`, `genre.confidence`).
* `AMPLITUDE_SCORING_ENABLED` — unit on: differs (`quantum_fidelity`);
  **API on: uninformative**, because `_to_response()` does not copy
  `quantum_fidelity` or `fidelity_conformal_pvalue` onto the response (a
  completeness gap documented in `original/schemas.py`), so no API field
  can move.
* `BAYESIAN_PRIOR_ENABLED` — on: differs (`deviation_score`).
* `COHORT_PRIOR_FALLBACK` — on: **uninformative**. The same-genre prior
  hits on this cohort, so the fallback branch is never reached.
* `PRIOR_WEIGHT` — on (with the prior enabled): differs
  (`deviation_score`).
* `NULL_MODEL` — on: differs, attach-only — exactly
  `llr_deviation_score`, nothing else.
* `LLR_ACTION_MODE` — `gate` (the shipped default) is NOT inert here: it
  takes its documented one-step downgrade against `shadow`. `shadow` is
  attach-only versus flags-off. Measured against `shadow`: `trigger` is
  **uninformative** (nothing sits at `no_action` to upgrade); `blend`
  differs (`action`) at both levels.
* `LENGTH_ADAPTIVE_WEIGHTS` — on: differs (`deviation_score`).
* `TOPIC_VARIANCE_INFLATION` — shadow and on: **uninformative**. The
  submission's topic distance is below `TOPIC_NOVELTY_BOUNDS["low"]`,
  where the mechanism is bit-for-bit identical to off by construction;
  the tests assert the measured distance so the verdict is earned, not
  assumed.
* `CHARACTERISTIC_WEIGHTS` — shadow: preview-only, exactly the four
  `characteristic_*` fields; on: differs (`deviation_score`).
* `RANK_REMEDIATION` — on: differs (`purity`, `von_neumann_entropy`).
* `AI_LIKELIHOOD_SHADOW` / `_ENABLED` — shadow: identical (strictly
  report-only); enabled: differs, adds `ai_likelihood`.
* `FUSED_SCORE_SHADOW` / `_ENABLED` — shadow: identical AND still
  persists a row; enabled: differs, adds `fused_score`.
* `LONGITUDINAL_DRIFT_ENABLED` — on: differs, adds `drift_analysis`.
* `STYLE_AUTHORSHIP_ENABLED` — on: differs, adds `style_authorship`.
* `SECRET_KEY` — never touches `deviation_score` or the action. With
  amplitude on it moves `quantum_fidelity` and nothing else.
* `TYPICALITY_SCORING` — on: differs (typicality fields + `action`).
* `TYPICALITY_POOLED_CALIBRATION` — on: **uninformative**. No
  `pooled_states` reach `score()` from either call site.
* `IDENTITY_AXIS` — unit on: differs (`action`); API on:
  **uninformative**, the 3x3 matrix lands on a cell whose verdict equals
  the one-axis verdict for this profile.

Nothing here is validated against real student submissions; this file
proves wiring and byte-identity, not calibration.
"""

from __future__ import annotations

import contextlib
import dataclasses
import difflib
import json
import os
import tempfile
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from fastapi.testclient import TestClient

from original.constants import ALL_FEATURE_CODES, FEATURE_DIM, TOPIC_NOVELTY_BOUNDS
from original.quantum.null_pool import build_impostor_stats
from original.quantum.scoring import ScoringConfig, score
from original.quantum.state import BaselineSample, StudentState
from tests.config._flag_corpus import (
    BASELINE_DATES,
    BASELINE_TEXTS,
    N_PEERS,
    SUBMISSION_TEXT,
    peer_texts,
)

# Fires once per process, the first time the live app's response models are
# built — a pre-existing naming nit on an unrelated response model, not
# anything this file is checking for. tests/test_openapi_snapshot.py filters
# the same warning for the same reason. Scoped to this one message so any
# other warning still surfaces.
pytestmark = pytest.mark.filterwarnings("ignore:.*conflict with protected namespace.*:UserWarning")

REPO_ROOT = Path(__file__).resolve().parents[2]
UNIT_SNAPSHOT_PATH = REPO_ROOT / "tests" / "snapshots" / "score_default.json"
API_SNAPSHOT_PATH = REPO_ROOT / "tests" / "snapshots" / "score_default_api.json"

_REGENERATE_MSG = "intentional? run `python scripts/update_score_snapshot.py` and review the diff"

STUDENT_ID = "flagbi:alice"
TENANT_ID = "flagbi"
SUBMISSION_ID = "flagbi-sub-001"
BASELINE_SEED = 100
PEER_SEED = 2000
SUBMISSION_SEED = 500

# Every flag this file drives, with the literal each row's "off"/default
# column in CLAUDE.md's table and docs/testing/08 §1 gives it. The API
# harness DELETES all of these (SECRET_KEY is set to "" rather than deleted
# because tests/conftest.py installs a process-wide default) so the
# committed snapshot is the all-unset response, and the off-arms then set
# each literal explicitly — which is what catches an "off" that is not off
# (a `"0"` vs `""` parsing bug).
FLAG_OFF_VALUES: dict[str, str] = {
    "CONTEXT_MANIFEST_ENABLED": "0",
    "ADAPTIVE_WEIGHTS_ENABLED": "0",
    "GENRE_INVARIANT_WEIGHTS_ENABLED": "0",
    "GENRE_RESOLVER_V2": "off",
    "AMPLITUDE_SCORING_ENABLED": "0",
    "BAYESIAN_PRIOR_ENABLED": "0",
    "COHORT_PRIOR_FALLBACK": "0",
    "PRIOR_WEIGHT": "3.0",
    "NULL_MODEL": "none",
    "LLR_ACTION_MODE": "gate",
    "LENGTH_ADAPTIVE_WEIGHTS": "0",
    "TOPIC_VARIANCE_INFLATION": "off",
    "CHARACTERISTIC_WEIGHTS": "off",
    "RANK_REMEDIATION": "none",
    "AI_LIKELIHOOD_ENABLED": "0",
    "AI_LIKELIHOOD_SHADOW": "0",
    "FUSED_SCORE_ENABLED": "0",
    "FUSED_SCORE_SHADOW": "0",
    "LONGITUDINAL_DRIFT_ENABLED": "0",
    "STYLE_AUTHORSHIP_ENABLED": "0",
    "SECRET_KEY": "",
    "TYPICALITY_SCORING": "0",
    "TYPICALITY_POOLED_CALIBRATION": "0",
    "IDENTITY_AXIS": "0",
}


# ── serialisation ─────────────────────────────────────────────────────────────


def _json_default(obj: Any) -> Any:
    """numpy scalars keep full precision via .item(); arrays become lists."""
    if isinstance(obj, np.generic):
        return obj.item()
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    raise TypeError(f"not JSON-serialisable: {type(obj)!r}")


def serialise(payload: dict) -> str:
    """The one serialisation both the tests and the update script use."""
    return json.dumps(payload, sort_keys=True, indent=2, default=_json_default) + "\n"


def _flatten(node: Any, prefix: str = "") -> dict[str, Any]:
    out: dict[str, Any] = {}
    if isinstance(node, dict):
        for key, value in node.items():
            out.update(_flatten(value, f"{prefix}.{key}" if prefix else key))
    elif isinstance(node, list):
        for index, value in enumerate(node):
            out.update(_flatten(value, f"{prefix}[{index}]"))
    else:
        out[prefix] = node
    return out


_MISSING = object()


def changed_paths(reference: dict, candidate: dict) -> set[str]:
    """Dotted paths that differ between two payloads (absence counts)."""
    flat_ref = _flatten(reference)
    flat_cand = _flatten(candidate)
    return {
        path
        for path in set(flat_ref) | set(flat_cand)
        if flat_ref.get(path, _MISSING) != flat_cand.get(path, _MISSING)
    }


def _unified(expected: str, actual: str, from_label: str, to_label: str) -> str:
    return "\n".join(
        list(
            difflib.unified_diff(
                expected.splitlines(),
                actual.splitlines(),
                fromfile=from_label,
                tofile=to_label,
                lineterm="",
            )
        )[:40]
    )


# ── unit-level fixture profile ────────────────────────────────────────────────


def _seeded_vector(seed: int) -> np.ndarray:
    return np.clip(np.random.RandomState(seed).normal(0.5, 0.1, FEATURE_DIM), 0.0, 1.0)


def _seeded_state(student_id: str, texts: tuple[str, ...], seed: int) -> StudentState:
    return StudentState(
        student_id=student_id,
        samples=[
            BaselineSample(
                text=text,
                vector=_seeded_vector(seed + index),
                provenance="proctored",
                auth_weight=1.0,
                assignment=f"a{index}",
                submitted_at=BASELINE_DATES[index % len(BASELINE_DATES)],
                # The router labels every baseline at ingestion; "correspondence"
                # is what the v1 resolver actually returns for this corpus, so
                # the Bayesian-prior arm sees the same genre key production does.
                genre="correspondence",
            )
            for index, text in enumerate(texts)
        ],
    )


def unit_peer_states() -> list[StudentState]:
    return [
        _seeded_state(f"{TENANT_ID}:peer{i:02d}", peer_texts(i), PEER_SEED + i * 10)
        for i in range(N_PEERS)
    ]


# What `store.get_genre_stats()` hands the router for this cohort: a mean, a
# spread, the pooled sample count and the number of contributing students.
# Written as literals so the unit arm does not depend on the store.
UNIT_GENRE_STATS: dict[str, Any] = {
    "mean": np.full(FEATURE_DIM, 0.46),
    "std": np.full(FEATURE_DIM, 0.11),
    "n_samples": 30,
    "n_students": 10,
}


def unit_payload(*, with_pool: bool = False, **config_kwargs: Any) -> dict:
    """One `score()` call over the fixed profile, as a plain JSON-able dict."""
    state = _seeded_state(STUDENT_ID, BASELINE_TEXTS, BASELINE_SEED)
    impostor_stats = None
    if with_pool:
        impostor_stats = build_impostor_stats(state.student_id, [state, *unit_peer_states()])
    vector = _seeded_vector(SUBMISSION_SEED)
    feature_dict = {code: float(v) for code, v in zip(ALL_FEATURE_CODES, vector, strict=True)}
    output = score(
        state,
        vector,
        feature_dict,
        submission_id=SUBMISSION_ID,
        n_tokens=len(SUBMISSION_TEXT.split()),
        impostor_stats=impostor_stats,
        scoring_config=ScoringConfig(**config_kwargs),
    )
    return json.loads(json.dumps(dataclasses.asdict(output), default=_json_default))


@contextlib.contextmanager
def clean_flag_env() -> Iterator[None]:
    """Every flag unset (SECRET_KEY blanked), restored on exit."""
    saved = {name: os.environ.get(name) for name in FLAG_OFF_VALUES}
    try:
        for name in FLAG_OFF_VALUES:
            os.environ.pop(name, None)
        os.environ["SECRET_KEY"] = ""
        yield
    finally:
        for name, value in saved.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


def build_unit_snapshot_text() -> str:
    with clean_flag_env():
        return serialise(unit_payload())


# ── API-level harness ─────────────────────────────────────────────────────────

_TIMESTAMP_KEYS = frozenset({"created_at"})


def normalise_api(payload: Any) -> Any:
    """Blank the one wall-clock field the response can carry.

    `context_manifest.created_at` (and its copy under `report`) is the only
    non-deterministic value in this endpoint's output; it appears solely
    when `CONTEXT_MANIFEST_ENABLED=1`, so the committed default snapshot
    contains no placeholder at all.
    """
    if isinstance(payload, dict):
        return {
            key: ("<normalised>" if key in _TIMESTAMP_KEYS else normalise_api(value))
            for key, value in payload.items()
        }
    if isinstance(payload, list):
        return [normalise_api(item) for item in payload]
    return payload


def _seed_api_store(client: TestClient) -> None:
    from original import store

    response = client.post(
        "/tenants",
        json={"tenant_id": TENANT_ID, "name": "Flag Byte Identity", "environment": "demo"},
    )
    assert response.status_code in (200, 201), response.text
    for index, (text, date) in enumerate(zip(BASELINE_TEXTS, BASELINE_DATES, strict=True)):
        response = client.post(
            f"/students/{STUDENT_ID}/baseline",
            json={
                "text": text,
                "provenance": "proctored",
                "assignment": f"a{index}",
                "submitted_at": date,
            },
        )
        # A 202/409 here means the ingestion drift gate rejected a baseline:
        # the corpus in _flag_corpus.py is built from overlapping sentence
        # windows precisely so it does not.
        assert response.status_code == 200, (index, response.text[:400])
    for peer in unit_peer_states():
        store.put(peer)


@contextlib.contextmanager
def api_harness() -> Iterator[Callable[[dict[str, str]], dict]]:
    """Seed a throwaway store, yield `call(env) -> normalised response`.

    Responses are memoised per environment: the endpoint recomputes on every
    request and its only writes (fidelity rows, manifest audit rows, the
    audit log) cannot feed a later score on this profile — held by
    `test_api_default_is_reproducible`, which scores twice through the live
    client and requires byte-identity.
    """
    import run
    from original import store

    with tempfile.TemporaryDirectory() as tmp_dir, clean_flag_env():
        db_path = Path(tmp_dir) / "flag_byte_identity.db"
        saved_db_env = os.environ.get("ORIGINAL_DB")
        saved_db_path = store._DB_PATH
        os.environ["ORIGINAL_DB"] = str(db_path)
        store._DB_PATH = db_path
        store._GENRE_STATS_CACHE.clear()
        try:
            client = TestClient(run.load_legacy_demo_app())
            _seed_api_store(client)
            cache: dict[tuple[tuple[str, str], ...], dict] = {}

            def call(env: dict[str, str] | None = None) -> dict:
                env = dict(env or {})
                key = tuple(sorted(env.items()))
                if key not in cache:
                    with pytest.MonkeyPatch.context() as mp:
                        for name, value in env.items():
                            mp.setenv(name, value)
                        response = client.post(
                            f"/students/{STUDENT_ID}/score",
                            json={"text": SUBMISSION_TEXT, "submission_id": SUBMISSION_ID},
                        )
                    assert response.status_code == 200, response.text[:400]
                    cache[key] = normalise_api(response.json())
                return cache[key]

            yield call
        finally:
            store._GENRE_STATS_CACHE.clear()
            store._DB_PATH = saved_db_path
            if saved_db_env is None:
                os.environ.pop("ORIGINAL_DB", None)
            else:
                os.environ["ORIGINAL_DB"] = saved_db_env


def build_api_snapshot_text() -> str:
    with api_harness() as call:
        return serialise(call({}))


# ── fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture
def unit_env() -> Iterator[None]:
    """Every flag env var unset for the duration of one unit-level test.

    `score()` reads the environment in exactly one place — `RANK_REMEDIATION`,
    via `StudentState.density_matrix` — so this fixture is what keeps the
    unit arms a function of `ScoringConfig` alone.
    """
    with clean_flag_env():
        yield


@pytest.fixture(scope="module")
def api_call() -> Iterator[Callable[[dict[str, str]], dict]]:
    with api_harness() as call:
        yield call


@pytest.fixture(scope="module")
def unit_snapshot() -> dict:
    return json.loads(UNIT_SNAPSHOT_PATH.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def api_snapshot() -> dict:
    return json.loads(API_SNAPSHOT_PATH.read_text(encoding="utf-8"))


# ── (a) the reference vectors ─────────────────────────────────────────────────


def test_unit_default_matches_snapshot(unit_env):
    """`ScoringConfig()` over the fixed profile must byte-match the snapshot."""
    current = serialise(unit_payload())
    snapshot = UNIT_SNAPSHOT_PATH.read_text(encoding="utf-8")
    if current != snapshot:
        raise AssertionError(
            "Default scoring output no longer matches "
            "tests/snapshots/score_default.json.\nFirst 40 lines of unified diff:\n"
            + _unified(
                snapshot,
                current,
                "tests/snapshots/score_default.json (committed)",
                "score(ScoringConfig()) (current)",
            )
            + f"\n\n{_REGENERATE_MSG}"
        )


def test_api_default_matches_snapshot(api_call):
    """`POST /students/{id}/score` with every flag unset must byte-match."""
    current = serialise(api_call({}))
    snapshot = API_SNAPSHOT_PATH.read_text(encoding="utf-8")
    if current != snapshot:
        raise AssertionError(
            "Default API scoring response no longer matches "
            "tests/snapshots/score_default_api.json.\n"
            "First 40 lines of unified diff:\n"
            + _unified(
                snapshot,
                current,
                "tests/snapshots/score_default_api.json (committed)",
                "POST /students/{id}/score (current)",
            )
            + f"\n\n{_REGENERATE_MSG}"
        )


def test_api_default_is_reproducible():
    """Scoring the same submission twice through a live client is identical.

    This is what licenses `api_harness`'s response cache and the claim that
    `created_at` is the only field needing normalisation: a second call runs
    after the first has written its fidelity/manifest/audit rows.
    """
    with api_harness() as call:
        first = serialise(call({}))
        # A distinct env dict, so the cache cannot serve the first answer back.
        second = serialise(call({"ORIGINAL_FLAG_MATRIX_NOOP": "1"}))
    assert first == second


# ── (b) one-flag-off arms ─────────────────────────────────────────────────────

# Every `ScoringConfig` field, at the default CLAUDE.md documents for it.
UNIT_OFF_ARMS: dict[str, dict[str, Any]] = {
    "bayesian_prior_enabled": {"bayesian_prior_enabled": False},
    "prior_weight": {"prior_weight": 3.0},
    "length_adaptive_weights": {"length_adaptive_weights": False},
    "null_model": {"null_model": "none"},
    "amplitude_scoring_enabled": {"amplitude_scoring_enabled": False},
    "secret_key": {"secret_key": ""},
    "typicality_scoring_enabled": {"typicality_scoring_enabled": False},
    "typicality_pooled_calibration": {"typicality_pooled_calibration": False},
    "identity_axis_enabled": {"identity_axis_enabled": False},
    "llr_action_mode": {"llr_action_mode": "gate"},
    "topic_variance_inflation": {"topic_variance_inflation": "off"},
    "characteristic_weights": {"characteristic_weights": "off"},
    "authentic_fidelities": {"authentic_fidelities": None},
    "genre_stats": {"genre_stats": None},
}


@pytest.mark.parametrize("arm", sorted(UNIT_OFF_ARMS), ids=sorted(UNIT_OFF_ARMS))
def test_unit_off_arm_matches_snapshot(unit_env, unit_snapshot, arm):
    """Setting one `ScoringConfig` field explicitly to its documented off
    value must reproduce the snapshot exactly."""
    assert changed_paths(unit_snapshot, unit_payload(**UNIT_OFF_ARMS[arm])) == set()


def test_unit_peer_pool_alone_changes_nothing(unit_env, unit_snapshot):
    """Handing `score()` an impostor pool with `NULL_MODEL=none` and
    `CHARACTERISTIC_WEIGHTS=off` must not move a single field — the pool is
    built on every request whenever either flag is non-default, so its mere
    presence must be inert."""
    assert changed_paths(unit_snapshot, unit_payload(with_pool=True)) == set()


def test_from_env_off_literals_equal_the_dataclass_defaults():
    """`ScoringConfig.from_env()` with every documented off literal in the
    environment must equal `ScoringConfig()`.

    This is the arm that catches a parsing bug — `"0"` read as truthy, or an
    unrecognised mode string silently falling through to something other than
    off — which comparing two dataclass constructions could never catch."""
    with clean_flag_env():
        for name, value in FLAG_OFF_VALUES.items():
            os.environ[name] = value
        parsed = ScoringConfig.from_env()
    assert parsed == ScoringConfig()


@pytest.mark.parametrize("flag", sorted(FLAG_OFF_VALUES), ids=sorted(FLAG_OFF_VALUES))
def test_api_off_arm_matches_snapshot(api_call, api_snapshot, flag):
    """Each flag set explicitly to its off literal must reproduce the API
    snapshot, which was generated with every one of them *unset*."""
    assert changed_paths(api_snapshot, api_call({flag: FLAG_OFF_VALUES[flag]})) == set()


def test_api_all_flags_explicitly_off_matches_snapshot(api_call, api_snapshot):
    assert changed_paths(api_snapshot, api_call(dict(FLAG_OFF_VALUES))) == set()


# ── (c) shadow arms — exact added-key sets ────────────────────────────────────


def test_unit_characteristic_shadow_adds_exactly_its_previews(unit_env, unit_snapshot):
    payload = unit_payload(with_pool=True, characteristic_weights="shadow")
    assert changed_paths(unit_snapshot, payload) == {
        "characteristic_mode",
        "characteristic_factor_dispersion",
        "characteristic_rms_z_preview",
        "characteristic_deviation_preview",
    }
    assert payload["characteristic_mode"] == "shadow"
    assert payload["characteristic_weighting_applied"] is False
    # A shadow soak that never gets a factor learns nothing; pin that this
    # arm actually exercised the mechanism.
    assert payload["characteristic_factor_dispersion"] > 0.0


def test_unit_llr_shadow_is_attach_only(unit_env, unit_snapshot):
    """`NULL_MODEL=impostor` + `LLR_ACTION_MODE=shadow` may attach
    `llr_deviation_score` and must change nothing else."""
    payload = unit_payload(with_pool=True, null_model="impostor", llr_action_mode="shadow")
    assert changed_paths(unit_snapshot, payload) == {"authorship.llr_deviation_score"}
    assert payload["authorship"]["llr_deviation_score"] is not None


def test_unit_topic_shadow_is_uninformative(unit_env, unit_snapshot):
    """Structural, not incidental: topic inflation reads the *manifest*, and
    `CONTEXT_MANIFEST_ENABLED` is off at the unit level's documented default,
    so there is no topic distance for shadow to preview."""
    assert changed_paths(unit_snapshot, unit_payload(topic_variance_inflation="shadow")) == set()
    pytest.skip(
        "uninformative — TOPIC_VARIANCE_INFLATION=shadow cannot attach a preview "
        "without a context manifest; the informative arm is "
        "test_api_topic_shadow_is_uninformative, which measures the real distance"
    )


API_SHADOW_ARMS: dict[str, tuple[dict[str, str], dict[str, str], set[str]]] = {
    # id: (prerequisite env, arm env, exact set of changed paths)
    "GENRE_RESOLVER_V2=shadow (no manifest)": ({}, {"GENRE_RESOLVER_V2": "shadow"}, set()),
    "GENRE_RESOLVER_V2=shadow": (
        {"CONTEXT_MANIFEST_ENABLED": "1"},
        {"GENRE_RESOLVER_V2": "shadow"},
        {
            "context_manifest.genre.shadow_primary",
            "context_manifest.genre.shadow_confidence",
            "report.context_manifest.genre.shadow_primary",
            "report.context_manifest.genre.shadow_confidence",
        },
    ),
    "AI_LIKELIHOOD_SHADOW=1": ({}, {"AI_LIKELIHOOD_SHADOW": "1"}, set()),
    "FUSED_SCORE_SHADOW=1": ({}, {"FUSED_SCORE_SHADOW": "1"}, set()),
    "CHARACTERISTIC_WEIGHTS=shadow": (
        {},
        {"CHARACTERISTIC_WEIGHTS": "shadow"},
        {
            "characteristic_mode",
            "characteristic_factor_dispersion",
            "characteristic_rms_z_preview",
            "characteristic_deviation_preview",
        },
    ),
    "LLR_ACTION_MODE=shadow": (
        {},
        {"NULL_MODEL": "impostor", "LLR_ACTION_MODE": "shadow"},
        {"authorship.llr_deviation_score"},
    ),
}


@pytest.mark.parametrize("arm", sorted(API_SHADOW_ARMS), ids=sorted(API_SHADOW_ARMS))
def test_api_shadow_arm_adds_exactly_its_preview_fields(api_call, arm):
    prereq, env, expected = API_SHADOW_ARMS[arm]
    reference = api_call(prereq)
    assert changed_paths(reference, api_call({**prereq, **env})) == expected


def test_api_fused_shadow_persists_without_attaching(api_call):
    """`FUSED_SCORE_SHADOW=1` is byte-identical *and* still does its job —
    otherwise "identical" would also pass on a shadow mode that computed
    nothing at all."""
    from original import store

    api_call({"FUSED_SCORE_SHADOW": "1"})
    rows = store.get_fused_scores(student_id=STUDENT_ID)
    assert rows, "shadow mode attached nothing AND persisted nothing"
    assert api_call({"FUSED_SCORE_SHADOW": "1"})["fused_score"] is None


def test_api_topic_shadow_is_uninformative(api_call):
    """Records the real reason, measured rather than assumed: this
    submission's topic distance sits below `TOPIC_NOVELTY_BOUNDS["low"]`,
    where the mechanism is bit-for-bit identical to off by construction."""
    manifest_env = {"CONTEXT_MANIFEST_ENABLED": "1"}
    reference = api_call(manifest_env)
    distance = reference["context_manifest"]["topic"]["baseline_distance"]
    assert distance <= TOPIC_NOVELTY_BOUNDS["low"], (
        "topic distance cleared the novelty floor — this arm is now informative "
        "and must assert the preview fields instead of skipping"
    )
    assert (
        changed_paths(reference, api_call({**manifest_env, "TOPIC_VARIANCE_INFLATION": "shadow"}))
        == set()
    )
    pytest.skip(
        f"uninformative — measured topic distance {distance:.4f} <= "
        f"TOPIC_NOVELTY_BOUNDS['low'] ({TOPIC_NOVELTY_BOUNDS['low']}), so "
        "TOPIC_VARIANCE_INFLATION is a structural no-op on this profile"
    )


# ── (d) on arms — inertness check, three-valued ───────────────────────────────
#
# `expected` is the set of documented fields the flag must move. `None`
# means the flag legitimately abstains on this profile: the arm asserts the
# output is unchanged and then records `uninformative` via pytest.skip, so
# an inert flag can never be read as a pass.

UNIT_ON_ARMS: dict[str, tuple[dict[str, Any], dict[str, Any], bool, set[str] | None, str]] = {
    "LENGTH_ADAPTIVE_WEIGHTS=1": (
        {},
        {"length_adaptive_weights": True},
        False,
        {"authorship.deviation_score"},
        "",
    ),
    "AMPLITUDE_SCORING_ENABLED=1": (
        {},
        {"amplitude_scoring_enabled": True},
        False,
        {"authorship.quantum_fidelity"},
        "",
    ),
    "TYPICALITY_SCORING=1": (
        {},
        {"typicality_scoring_enabled": True},
        False,
        {
            "typicality_p_far",
            "typicality_p_central",
            "typicality_band",
            "typicality_n",
            "typicality_source",
            "typicality_calibration",
        },
        "",
    ),
    "BAYESIAN_PRIOR_ENABLED=1": (
        {},
        {"bayesian_prior_enabled": True, "genre_stats": UNIT_GENRE_STATS},
        False,
        {"authorship.deviation_score"},
        "",
    ),
    "PRIOR_WEIGHT=10.0": (
        {"bayesian_prior_enabled": True, "genre_stats": UNIT_GENRE_STATS},
        {"prior_weight": 10.0},
        False,
        {"authorship.deviation_score"},
        "",
    ),
    "IDENTITY_AXIS=1": (
        {"typicality_scoring_enabled": True, "null_model": "impostor"},
        {"identity_axis_enabled": True},
        True,
        {"recommendation.action"},
        "",
    ),
    "LLR_ACTION_MODE=blend": (
        {"null_model": "impostor", "llr_action_mode": "shadow"},
        {"llr_action_mode": "blend"},
        True,
        {"recommendation.action"},
        "",
    ),
    "CHARACTERISTIC_WEIGHTS=on": (
        {},
        {"characteristic_weights": "on"},
        True,
        {"authorship.deviation_score", "characteristic_weighting_applied"},
        "",
    ),
    "LLR_ACTION_MODE=trigger": (
        {"null_model": "impostor", "llr_action_mode": "shadow"},
        {"llr_action_mode": "trigger"},
        True,
        None,
        "trigger may only upgrade no_action -> monitor, and this profile scores "
        "well above no_action; there is nothing for it to upgrade. Referenced "
        "against `shadow`, the mode defined to be byte-identical to flags-off, "
        "rather than against the shipped `gate` default",
    ),
    "TYPICALITY_POOLED_CALIBRATION=1": (
        {"typicality_scoring_enabled": True},
        {"typicality_pooled_calibration": True},
        False,
        None,
        "pooled calibration needs `pooled_states`, which neither this call site "
        "nor the scoring router supplies",
    ),
    "TOPIC_VARIANCE_INFLATION=on": (
        {},
        {"topic_variance_inflation": "on"},
        False,
        None,
        "topic inflation reads the context manifest, which is off at the "
        "documented default; see test_api_topic_on_is_uninformative for the "
        "manifest-enabled measurement",
    ),
}


@pytest.mark.parametrize("arm", sorted(UNIT_ON_ARMS), ids=sorted(UNIT_ON_ARMS))
def test_unit_on_arm_is_not_inert(unit_env, arm):
    prereq, config, with_pool, expected, reason = UNIT_ON_ARMS[arm]
    reference = unit_payload(with_pool=with_pool, **prereq)
    candidate = unit_payload(with_pool=with_pool, **{**prereq, **config})
    changed = changed_paths(reference, candidate)
    if expected is None:
        assert changed == set(), f"{arm} was expected to abstain but moved {sorted(changed)}"
        pytest.skip(f"uninformative — {reason}")
    assert expected <= changed, f"{arm} did not move {sorted(expected - changed)}"


def test_unit_null_model_on_is_attach_only(unit_env, unit_snapshot):
    """`NULL_MODEL=impostor` is documented attach-only: exactly one new field."""
    payload = unit_payload(with_pool=True, null_model="impostor")
    assert changed_paths(unit_snapshot, payload) == {"authorship.llr_deviation_score"}


def test_unit_rank_remediation_on_is_not_inert(unit_env, unit_snapshot):
    """`RANK_REMEDIATION=shrinkage` is the one flag `score()` reads from the
    environment (through `StudentState.density_matrix`), so it gets an
    env-driven arm rather than a `ScoringConfig` one."""
    os.environ["RANK_REMEDIATION"] = "shrinkage"
    changed = changed_paths(unit_snapshot, unit_payload())
    assert {"baseline_confidence.purity", "baseline_confidence.von_neumann_entropy"} <= changed


MANIFEST = {"CONTEXT_MANIFEST_ENABLED": "1"}
ADAPTIVE = {"CONTEXT_MANIFEST_ENABLED": "1", "ADAPTIVE_WEIGHTS_ENABLED": "1"}
IMPOSTOR = {"NULL_MODEL": "impostor"}
TYPICALITY = {"TYPICALITY_SCORING": "1"}
PRIOR = {"BAYESIAN_PRIOR_ENABLED": "1"}
LLR_SHADOW = {"NULL_MODEL": "impostor", "LLR_ACTION_MODE": "shadow"}

API_ON_ARMS: dict[str, tuple[dict[str, str], dict[str, str], set[str] | None, str]] = {
    "CONTEXT_MANIFEST_ENABLED=1": (
        {},
        MANIFEST,
        {"context_manifest", "context_manifest.genre.primary"},
        "",
    ),
    "ADAPTIVE_WEIGHTS_ENABLED=1": (
        MANIFEST,
        {"ADAPTIVE_WEIGHTS_ENABLED": "1"},
        {"authorship.deviation_score"},
        "",
    ),
    "GENRE_RESOLVER_V2=on": (
        MANIFEST,
        {"GENRE_RESOLVER_V2": "on"},
        {"context_manifest.genre.primary", "context_manifest.genre.confidence"},
        "",
    ),
    "BAYESIAN_PRIOR_ENABLED=1": ({}, PRIOR, {"authorship.deviation_score"}, ""),
    "PRIOR_WEIGHT=10.0": (PRIOR, {"PRIOR_WEIGHT": "10.0"}, {"authorship.deviation_score"}, ""),
    "NULL_MODEL=impostor": ({}, IMPOSTOR, {"authorship.llr_deviation_score"}, ""),
    "LENGTH_ADAPTIVE_WEIGHTS=1": (
        {},
        {"LENGTH_ADAPTIVE_WEIGHTS": "1"},
        {"authorship.deviation_score"},
        "",
    ),
    "CHARACTERISTIC_WEIGHTS=on": (
        {},
        {"CHARACTERISTIC_WEIGHTS": "on"},
        {"authorship.deviation_score", "characteristic_weighting_applied"},
        "",
    ),
    "RANK_REMEDIATION=shrinkage": (
        {},
        {"RANK_REMEDIATION": "shrinkage"},
        {"baseline_confidence.purity", "baseline_confidence.von_neumann_entropy"},
        "",
    ),
    "AI_LIKELIHOOD_ENABLED=1": (
        {},
        {"AI_LIKELIHOOD_ENABLED": "1"},
        {"ai_likelihood", "ai_likelihood.probability"},
        "",
    ),
    "FUSED_SCORE_ENABLED=1": (
        {},
        {"FUSED_SCORE_ENABLED": "1"},
        {"fused_score", "fused_score.probability_different_author"},
        "",
    ),
    "LONGITUDINAL_DRIFT_ENABLED=1": (
        {},
        {"LONGITUDINAL_DRIFT_ENABLED": "1"},
        {"drift_analysis", "drift_analysis.eligible"},
        "",
    ),
    "STYLE_AUTHORSHIP_ENABLED=1": (
        {},
        {"STYLE_AUTHORSHIP_ENABLED": "1"},
        {"style_authorship", "style_authorship.probability_same_author"},
        "",
    ),
    "TYPICALITY_SCORING=1": (
        {},
        TYPICALITY,
        {"typicality_band", "typicality_p_far", "recommendation.action"},
        "",
    ),
    "GENRE_INVARIANT_WEIGHTS_ENABLED=1": (
        ADAPTIVE,
        {"GENRE_INVARIANT_WEIGHTS_ENABLED": "1"},
        None,
        "the attenuation only fires on a CONFIDENT genre mismatch, and this "
        "submission's genre is covered by the baseline — the documented trap "
        "this flag is the cautionary precedent for",
    ),
    "AMPLITUDE_SCORING_ENABLED=1": (
        {},
        {"AMPLITUDE_SCORING_ENABLED": "1"},
        None,
        "the flag does move quantum_fidelity (see the unit arm), but the API's "
        "_to_response() does not copy quantum_fidelity or "
        "fidelity_conformal_pvalue onto the response (documented completeness "
        "gap in original/schemas.py), so no API field can move",
    ),
    "COHORT_PRIOR_FALLBACK=1": (
        PRIOR,
        {"COHORT_PRIOR_FALLBACK": "1"},
        None,
        "the same-genre prior HITS on this cohort, so the genre-agnostic "
        "fallback branch is never reached",
    ),
    "TYPICALITY_POOLED_CALIBRATION=1": (
        TYPICALITY,
        {"TYPICALITY_POOLED_CALIBRATION": "1"},
        None,
        "the scoring router passes no pooled_states, so pooled calibration has "
        "no tenant-wide reference to switch to",
    ),
    "IDENTITY_AXIS=1": (
        {**TYPICALITY, **IMPOSTOR},
        {"IDENTITY_AXIS": "1"},
        None,
        "the 3x3 identity/typicality matrix lands on a cell whose verdict "
        "equals the one-axis verdict for this profile",
    ),
    # Referenced against `shadow` — the mode defined to be byte-identical to
    # flags-off — not against the shipped `gate` default, which DOES move the
    # action on this profile (test_api_llr_gate_default_is_not_inert).
    "LLR_ACTION_MODE=trigger": (
        LLR_SHADOW,
        {"LLR_ACTION_MODE": "trigger"},
        None,
        "trigger may only upgrade no_action -> monitor; nothing on this profile "
        "sits at no_action",
    ),
    "LLR_ACTION_MODE=blend": (
        LLR_SHADOW,
        {"LLR_ACTION_MODE": "blend"},
        {"recommendation.action"},
        "",
    ),
    "TOPIC_VARIANCE_INFLATION=on": (
        MANIFEST,
        {"TOPIC_VARIANCE_INFLATION": "on"},
        None,
        "the submission's topic distance is below TOPIC_NOVELTY_BOUNDS['low'], "
        "where inflation is bit-for-bit identical to off by construction",
    ),
}


@pytest.mark.parametrize("arm", sorted(API_ON_ARMS), ids=sorted(API_ON_ARMS))
def test_api_on_arm_is_not_inert(api_call, arm):
    prereq, env, expected, reason = API_ON_ARMS[arm]
    reference = api_call(prereq)
    changed = changed_paths(reference, api_call({**prereq, **env}))
    if expected is None:
        assert changed == set(), f"{arm} was expected to abstain but moved {sorted(changed)}"
        pytest.skip(f"uninformative — {reason}")
    assert expected <= changed, f"{arm} did not move {sorted(expected - changed)}"


def test_api_topic_on_is_uninformative(api_call):
    """The manifest-enabled twin of the unit arm, with the distance measured."""
    reference = api_call(MANIFEST)
    distance = reference["context_manifest"]["topic"]["baseline_distance"]
    assert distance <= TOPIC_NOVELTY_BOUNDS["low"]
    assert (
        changed_paths(reference, api_call({**MANIFEST, "TOPIC_VARIANCE_INFLATION": "on"})) == set()
    )
    pytest.skip(
        f"uninformative — measured topic distance {distance:.4f} <= "
        f"TOPIC_NOVELTY_BOUNDS['low'] ({TOPIC_NOVELTY_BOUNDS['low']})"
    )


def test_api_llr_gate_default_is_not_inert(api_call):
    """`LLR_ACTION_MODE=gate` is the shipped default and it is *not* a no-op
    here: against the byte-identical `shadow` mode it takes the documented
    one-step downgrade. This is the arm that stops the three no-op `trigger`
    /`blend` skips above from reading as "llr does nothing"."""
    shadow = api_call({**IMPOSTOR, "LLR_ACTION_MODE": "shadow"})
    gate = api_call({**IMPOSTOR, "LLR_ACTION_MODE": "gate"})
    assert "recommendation.action" in changed_paths(shadow, gate)
    severity = ["no_action", "monitor", "schedule_conversation", "escalate"]
    assert severity.index(gate["recommendation"]["action"]) == (
        severity.index(shadow["recommendation"]["action"]) - 1
    ), "gate may only downgrade by exactly one severity step"


# ── (e) SECRET_KEY never touches the score or the action ──────────────────────


def test_unit_secret_key_touches_only_the_amplitude_path(unit_env, unit_snapshot):
    """TermSim finding, pinned because the docs imply otherwise: `SECRET_KEY`
    is a keyed projection inside the amplitude path only."""
    secret = "flag-byte-identity-secret-key-0123456789"

    # With amplitude off it is inert everywhere.
    assert changed_paths(unit_snapshot, unit_payload(secret_key=secret)) == set()

    # With amplitude on it moves the fidelity and nothing else.
    amplitude = unit_payload(amplitude_scoring_enabled=True)
    keyed = unit_payload(amplitude_scoring_enabled=True, secret_key=secret)
    assert changed_paths(amplitude, keyed) == {"authorship.quantum_fidelity"}
    assert keyed["authorship"]["deviation_score"] == amplitude["authorship"]["deviation_score"]
    assert keyed["recommendation"]["action"] == amplitude["recommendation"]["action"]
    assert keyed["authorship"]["quantum_fidelity"] != amplitude["authorship"]["quantum_fidelity"]


def test_api_secret_key_changes_nothing(api_call, api_snapshot):
    secret = "flag-byte-identity-secret-key-0123456789"
    assert changed_paths(api_snapshot, api_call({"SECRET_KEY": secret})) == set()
    with_amplitude = api_call({"AMPLITUDE_SCORING_ENABLED": "1"})
    assert (
        changed_paths(
            with_amplitude, api_call({"AMPLITUDE_SCORING_ENABLED": "1", "SECRET_KEY": secret})
        )
        == set()
    )


# ── coverage of the spec's table ──────────────────────────────────────────────


def test_every_flag_in_the_spec_table_has_an_arm():
    """Every row of docs/testing/08 §1's table is represented above.

    A flag that gains a row in the spec but no arm here would otherwise
    leave the matrix quietly incomplete.
    """
    covered: set[str] = set(FLAG_OFF_VALUES)
    for prereq, env, _ in API_SHADOW_ARMS.values():
        covered |= set(prereq) | set(env)
    for prereq, env, _, _ in API_ON_ARMS.values():
        covered |= set(prereq) | set(env)
    spec_table_flags = {
        "CONTEXT_MANIFEST_ENABLED",
        "ADAPTIVE_WEIGHTS_ENABLED",
        "GENRE_INVARIANT_WEIGHTS_ENABLED",
        "GENRE_RESOLVER_V2",
        "AMPLITUDE_SCORING_ENABLED",
        "BAYESIAN_PRIOR_ENABLED",
        "COHORT_PRIOR_FALLBACK",
        "NULL_MODEL",
        "LLR_ACTION_MODE",
        "LENGTH_ADAPTIVE_WEIGHTS",
        "TOPIC_VARIANCE_INFLATION",
        "CHARACTERISTIC_WEIGHTS",
        "RANK_REMEDIATION",
        "AI_LIKELIHOOD_ENABLED",
        "AI_LIKELIHOOD_SHADOW",
        "FUSED_SCORE_ENABLED",
        "FUSED_SCORE_SHADOW",
        "LONGITUDINAL_DRIFT_ENABLED",
        "STYLE_AUTHORSHIP_ENABLED",
        "SECRET_KEY",
    }
    assert spec_table_flags <= covered, sorted(spec_table_flags - covered)


def test_every_scoring_config_field_has_an_off_arm():
    """Every `ScoringConfig` field is pinned at its default by an off-arm."""
    fields = {f.name for f in dataclasses.fields(ScoringConfig)}
    assert fields == set(UNIT_OFF_ARMS), sorted(fields ^ set(UNIT_OFF_ARMS))
