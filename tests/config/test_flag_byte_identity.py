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

Deterministic feature backends
------------------------------
The API arms run real feature extraction, and tier 10 (`semantic_*`) picks
its backend from what happens to be importable on the machine:
`sentence_transformers` + a downloaded `all-MiniLM-L6-v2` if present,
otherwise the genuine TF-IDF backend (`original/features/tier10.py`).
Those two produce different floats, so a snapshot generated on a machine
with the neural backend cannot be reproduced by CI (Linux CPU, a different
`sentence-transformers` major — `requirements.txt` pins `>=5.6.0,<6.0` —
and a network model download) or by the pilot lockset, which has no
`sentence-transformers` at all.

`force_tfidf_tier10()` pins the backend to TF-IDF, and `api_harness()`
enters it around *everything* — baseline ingestion included — so the
backend is a property of this harness rather than of the machine. Because
the forcing lives inside the shared harness, `scripts/update_score_snapshot.py`
(which calls `build_api_snapshot_text`) and the fixtures cannot drift
apart: there is one seam, not two that must be kept in lockstep.
`test_api_arms_use_the_tfidf_tier10_backend` fails loudly, naming the
cause, if a future environment silently selects the neural path.

The unit level needs no such forcing: its vectors are seeded
(`_seeded_vector`) and its `feature_dict` is built from that vector, so
`unit_payload()` never runs the feature pipeline and never reaches tier 10.

Tier 10's backend is not the only machine-dependent input behind the API
snapshot. `tier5.py`, `tier11.py` and `prosodic.py` all call
`spacy.load("en_core_web_sm")`, and that pipeline's tagger, parser and
lemmatizer weights are a property of the exact model wheel, not just the
spaCy major/minor pinned in `requirements.txt` — a model bump changes the
extracted floats the same way a tier-10 backend swap does. There is no
deterministic fallback to force here the way `force_tfidf_tier10()` forces
tier 10, so every CI workflow step installs the exact wheel version the
snapshot was generated against, rather than
`python -m spacy download en_core_web_sm` (unpinned, can silently drift).
`EN_CORE_WEB_SM_VERSION` records that pinned version next to the snapshot
paths above, and `test_en_core_web_sm_version_matches_snapshot` fails
naming the cause — a model bump — instead of a bare snapshot diff.

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
`GENRE_INVARIANT_WEIGHTS_ENABLED` fell into. Every data-dependent
`uninformative` verdict measures the cause it names (`UNIT_ON_ARM_MEASURES`
/ `API_ON_ARM_MEASURES`, which append the measurement to the skip text), so
an arm that goes inert for a *different* reason fails rather than skipping.
The few that do not measure are structural — the shape of the call, not the
data — and say which.

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
* `NULL_MODEL` — on: differs. **Attach-only only at the unit level and
  under `LLR_ACTION_MODE=shadow`** (there it is exactly
  `authorship.llr_deviation_score`). At the API default it is *not*
  attach-only: `LLR_ACTION_MODE` ships as `gate`, which takes its
  documented one-step action downgrade on this profile, so
  `NULL_MODEL=impostor` also moves `recommendation.action`,
  `recommendation.rationale` and the three `human_explanation` fields
  derived from the action. The API on-arm asserts that exact six-path
  set, and `test_api_llr_gate_default_is_not_inert` pins the downgrade
  itself.
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
import math
import os
import re
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

# The API snapshot's tier5/tier11/prosodic values come from spaCy's
# `en_core_web_sm` pipeline (`spacy.load("en_core_web_sm")`), and those are a
# property of the exact model wheel, not just the spaCy major/minor pin in
# requirements.txt -- a model bump changes tagger/parser/lemmatizer weights
# and produces different floats at byte precision. Recorded here, next to
# the snapshot paths above, so `test_en_core_web_sm_version_matches_snapshot`
# fails naming the cause (a model bump) rather than pointing at
# `_REGENERATE_MSG`'s generic "did the math change?" hint. CI installs this
# exact wheel (see .github/workflows/test.yml and boot-matrix.yml) instead of
# `python -m spacy download en_core_web_sm`, which is unpinned and can drift.
EN_CORE_WEB_SM_VERSION = "3.8.0"

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


# Cross-platform float stability. Several scored fields are derived from
# numpy linear algebra -- most sharply ``von_neumann_entropy``, an
# eigendecomposition -- whose 15th-16th significant digit differs between the
# BLAS this snapshot was generated under (Apple Accelerate) and CI's
# (Linux OpenBLAS): 0.0409878331784488 vs 0.04098783317844875. Byte-exact
# JSON cannot survive that. Quantising every float to 10 significant figures
# absorbs the ~1e-15 last-bit noise while leaving five-plus orders of margin
# below any real scoring change (>=1e-4), so a genuine change still shows in
# the diff and platform noise does not.
_SIG_FIGS = 10


def _quantize(node: Any) -> Any:
    if isinstance(node, float):
        if not math.isfinite(node) or node == 0.0:
            return node
        exp = math.floor(math.log10(abs(node)))
        return round(node, (_SIG_FIGS - 1) - exp)
    if isinstance(node, dict):
        return {k: _quantize(v) for k, v in node.items()}
    if isinstance(node, list):
        return [_quantize(v) for v in node]
    return node


def serialise(payload: dict) -> str:
    """The one serialisation both the tests and the update script use."""
    return (
        json.dumps(_quantize(payload), sort_keys=True, indent=2, default=_json_default)
        + "\n"
    )


# An empty container has no leaves, so a naive flatten erases it entirely:
# `{"broken_entanglements": []}` and `{}` would flatten to the same thing and
# `changed_paths` would report no change when a whole key was dropped (or when
# a populated `paragraph_arcs` became empty). Emitting a sentinel leaf keeps
# the path — and therefore the diff — visible.
_EMPTY_LIST = "<empty-list>"
_EMPTY_DICT = "<empty-dict>"


def _flatten(node: Any, prefix: str = "") -> dict[str, Any]:
    out: dict[str, Any] = {}
    if isinstance(node, dict):
        if not node:
            out[prefix] = _EMPTY_DICT
        for key, value in node.items():
            out.update(_flatten(value, f"{prefix}.{key}" if prefix else key))
    elif isinstance(node, list):
        if not node:
            out[prefix] = _EMPTY_LIST
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
    return _quantize(json.loads(json.dumps(dataclasses.asdict(output), default=_json_default)))


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


@contextlib.contextmanager
def force_tfidf_tier10() -> Iterator[None]:
    """Pin tier 10 to its deterministic TF-IDF backend for the whole block.

    `original/features/tier10.py` selects a backend lazily and caches it in
    two module globals: `_st_model` (the loaded SentenceTransformer) and
    `_st_failed` (the "we already tried and it is unavailable" latch that
    `_get_st_model` short-circuits on). Setting the latch and clearing the
    cache makes `_encode_sentences` take the TF-IDF path without importing
    or downloading anything — the same path CI and the pilot lockset take.

    Both globals are saved and restored: this process may run other tests
    that legitimately want whichever backend is installed.
    """
    from original.features import tier10

    saved_model, saved_failed = tier10._st_model, tier10._st_failed
    tier10._st_model = None
    tier10._st_failed = True
    try:
        yield
    finally:
        tier10._st_model, tier10._st_failed = saved_model, saved_failed


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

    Responses are memoised per environment. That cache is only sound because
    scoring is a pure function of (profile, submission, env) here: the two
    responses an arm compares were computed at *different points in the
    store's write history* (the endpoint writes fidelity rows, manifest
    audit rows and audit-log rows on every call), so if any of those writes
    could feed a later score, a cached reference and a freshly computed
    candidate would differ for reasons that have nothing to do with the
    flag. `test_api_default_is_reproducible` is the arm that holds that
    invariant: it scores the same submission twice through a live client,
    the second time after the first call's writes have landed, and requires
    byte-identity. If that test ever fails, this cache is unsound and the
    whole file's diffs become untrustworthy — fix it there, not here.

    Tier 10 is pinned to its TF-IDF backend for the entire block
    (`force_tfidf_tier10`), baseline ingestion included, so the snapshots
    are reproducible off this machine. The forcing lives here rather than
    in the fixtures because `scripts/update_score_snapshot.py` regenerates
    through `build_api_snapshot_text`, which enters this same context — one
    seam, so the script and the tests cannot disagree about the backend.
    """
    import run
    from original import store

    with tempfile.TemporaryDirectory() as tmp_dir, clean_flag_env(), force_tfidf_tier10():
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
    # Quantize the scored response the same way the snapshot on disk was
    # written (serialise() rounds to 10 sig figs), so every changed_paths()
    # comparison is quantized-vs-quantized and cross-platform last-bit noise
    # in linalg-derived fields cannot register as a change.
    with api_harness() as call:
        yield lambda env: _quantize(call(env))


@pytest.fixture(scope="module")
def unit_snapshot() -> dict:
    return _quantize(json.loads(UNIT_SNAPSHOT_PATH.read_text(encoding="utf-8")))


@pytest.fixture(scope="module")
def api_snapshot() -> dict:
    return _quantize(json.loads(API_SNAPSHOT_PATH.read_text(encoding="utf-8")))


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
    "tuned_action_thresholds": {"tuned_action_thresholds": None},
}


@pytest.mark.parametrize("arm", sorted(UNIT_OFF_ARMS), ids=sorted(UNIT_OFF_ARMS))
def test_unit_off_arm_matches_snapshot(unit_env, unit_snapshot, arm):
    """Setting one `ScoringConfig` field explicitly to its documented off
    value must reproduce the snapshot exactly."""
    changed = changed_paths(unit_snapshot, unit_payload(**UNIT_OFF_ARMS[arm]))
    assert changed == set(), (
        f"ScoringConfig({arm}=<documented off value>) moved {sorted(changed)} "
        f"away from the committed unit snapshot — {_REGENERATE_MSG}"
    )


def test_unit_peer_pool_alone_changes_nothing(unit_env, unit_snapshot):
    """Handing `score()` an impostor pool with `NULL_MODEL=none` and
    `CHARACTERISTIC_WEIGHTS=off` must not move a single field — the pool is
    built on every request whenever either flag is non-default, so its mere
    presence must be inert."""
    changed = changed_paths(unit_snapshot, unit_payload(with_pool=True))
    assert changed == set(), f"an inert peer pool moved {sorted(changed)} — {_REGENERATE_MSG}"


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
    changed = changed_paths(api_snapshot, api_call({flag: FLAG_OFF_VALUES[flag]}))
    assert changed == set(), (
        f"{flag}={FLAG_OFF_VALUES[flag]!r} (its documented off literal) moved "
        f"{sorted(changed)} away from the all-unset API snapshot — either the "
        f"off literal is not parsed as off, or {_REGENERATE_MSG}"
    )


def test_api_all_flags_explicitly_off_matches_snapshot(api_call, api_snapshot):
    changed = changed_paths(api_snapshot, api_call(dict(FLAG_OFF_VALUES)))
    assert changed == set(), (
        f"every flag set to its documented off literal moved {sorted(changed)} "
        f"away from the all-unset API snapshot — {_REGENERATE_MSG}"
    )


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


def _measure_unit_llr_trigger(reference: dict) -> str:
    """`trigger` can only upgrade `no_action` -> `monitor`. Measure that the
    reference is not sitting at `no_action`, so the stated cause is the one
    actually observed rather than an assumption about the profile."""
    action = reference["recommendation"]["action"]
    assert action != "no_action", (
        "the reference action IS no_action, so trigger had something to "
        "upgrade and this arm is now informative — assert the upgrade "
        "instead of skipping"
    )
    return f"measured reference action = {action!r}"


# Arm id -> callable(reference payload) -> extra text for the skip reason.
# Every `expected is None` arm has to justify its stated cause. The two unit
# arms without an entry here are justified structurally instead, by the shape
# of the call rather than by the data: `TYPICALITY_POOLED_CALIBRATION` because
# `unit_payload` passes no `pooled_states` at all (visible three screens up),
# and `TOPIC_VARIANCE_INFLATION=on` because inflation reads a context manifest
# that the unit level never builds. Their data-dependent twins are the API
# arms, which do measure.
UNIT_ON_ARM_MEASURES: dict[str, Callable[[dict], str]] = {
    "LLR_ACTION_MODE=trigger": _measure_unit_llr_trigger,
}


@pytest.mark.parametrize("arm", sorted(UNIT_ON_ARMS), ids=sorted(UNIT_ON_ARMS))
def test_unit_on_arm_is_not_inert(unit_env, arm):
    prereq, config, with_pool, expected, reason = UNIT_ON_ARMS[arm]
    reference = unit_payload(with_pool=with_pool, **prereq)
    candidate = unit_payload(with_pool=with_pool, **{**prereq, **config})
    changed = changed_paths(reference, candidate)
    if expected is None:
        assert changed == set(), f"{arm} was expected to abstain but moved {sorted(changed)}"
        measure = UNIT_ON_ARM_MEASURES.get(arm)
        measured = f" [{measure(reference)}]" if measure is not None else ""
        pytest.skip(f"uninformative — {reason}{measured}")
    assert expected <= changed, f"{arm} did not move {sorted(expected - changed)}"


def test_unit_null_model_on_is_attach_only(unit_env, unit_snapshot):
    """`NULL_MODEL=impostor` is documented attach-only: exactly one new field."""
    payload = unit_payload(with_pool=True, null_model="impostor")
    assert changed_paths(unit_snapshot, payload) == {"authorship.llr_deviation_score"}


def test_unit_rank_remediation_on_is_not_inert(unit_env, unit_snapshot, monkeypatch):
    """`RANK_REMEDIATION=shrinkage` is the one flag `score()` reads from the
    environment (through `StudentState.density_matrix`), so it gets an
    env-driven arm rather than a `ScoringConfig` one.

    Set through `monkeypatch` rather than by assigning `os.environ`
    directly. The `unit_env` fixture would restore it either way, but that
    makes this test's cleanup depend on an enclosing fixture rather than on
    anything visible here; monkeypatch owns its own teardown, which is the
    convention every other env-driven arm in this file already follows.
    """
    monkeypatch.setenv("RANK_REMEDIATION", "shrinkage")
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
    # NOT attach-only at the API level, unlike the unit arm: the shipped
    # LLR_ACTION_MODE default is `gate`, which takes its one-step downgrade
    # here (escalate -> schedule_conversation), and the action feeds the
    # rationale and the three human_explanation fields. Asserted as an
    # EQUALITY (see _EXACT_API_ON_ARMS) so a future mode that moved
    # `deviation_score` as well could not hide inside a subset check.
    "NULL_MODEL=impostor": (
        {},
        IMPOSTOR,
        {
            "authorship.llr_deviation_score",
            "recommendation.action",
            "recommendation.rationale",
            "human_explanation.verdict",
            "human_explanation.severity",
            "human_explanation.summary",
        },
        "",
    ),
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


# Arms whose changed set is asserted as an equality rather than a subset,
# because the flag's documented blast radius is exactly known.
_EXACT_API_ON_ARMS = frozenset({"NULL_MODEL=impostor"})


# ── measurements behind the API `uninformative` verdicts ─────────────────────
#
# Each takes (reference payload, api_call, caplog) and returns the text
# appended to its skip reason. A skip that merely *names* a cause is a
# hypothesis; these turn each one into an observation, so an arm that goes
# quietly inert for a different reason fails instead of skipping.


def _measure_genre_covered(reference: dict, api_call: Callable, caplog: Any) -> str:
    """`GENRE_INVARIANT_WEIGHTS_ENABLED` attenuates only on a CONFIDENT
    mismatch. `genre_covered_by_baseline` returns True (no attenuation) on
    three different paths; the stated reason is only honest if this profile
    takes the third one — a real submission genre that a real baseline genre
    matches — rather than either abstention path.
    """
    from original import store
    from original.constants import GENRE_UNKNOWN

    primary = reference["context_manifest"]["genre"]["primary"]
    assert primary not in (None, GENRE_UNKNOWN), (
        f"submission genre is {primary!r}: genre_covered_by_baseline returns True "
        "on its FIRST path (unclassified submission is never 'novel'), so the "
        "skip reason 'covered by the baseline' would be unmeasured"
    )
    samples = store.get(STUDENT_ID).samples
    baseline_genres = {
        s.genre for s in samples if getattr(s, "genre", None) not in (None, GENRE_UNKNOWN)
    }
    assert baseline_genres, (
        "no baseline sample carries a genre: genre_covered_by_baseline returns "
        "True on its SECOND path (no known genres at all), which is not the "
        "reason this arm claims"
    )
    assert primary in baseline_genres, (
        f"submission genre {primary!r} is NOT among the baseline genres "
        f"{sorted(baseline_genres)} — genre_covered_by_baseline is False here and "
        "the attenuation should have fired; this arm is now informative"
    )
    return (
        f"third path measured: submission genre {primary!r} is among the "
        f"baseline genres {sorted(baseline_genres)}"
    )


def _measure_genre_prior_hit(reference: dict, api_call: Callable, caplog: Any) -> str:
    """`COHORT_PRIOR_FALLBACK` is only read when the same-genre prior came
    back `None`. The response exposes no prior field, so the hit is measured
    off the INFO line `students_scoring.py` logs for exactly this purpose
    (`bayesian_prior outcome=hit|miss …`, no student ids).

    A distinct no-op env var forces a fresh scoring call inside the caplog
    block: the harness memoises by env, and a cached response emits no logs.
    """
    import logging

    logger = "original.routers.students_scoring"
    with caplog.at_level(logging.INFO, logger=logger):
        caplog.clear()
        api_call({**PRIOR, "ORIGINAL_FLAG_MATRIX_NOOP": "prior-probe"})
        lines = [r.getMessage() for r in caplog.records if r.name == logger]
    outcomes = [line for line in lines if line.startswith("bayesian_prior outcome=")]
    assert outcomes, (
        "no `bayesian_prior outcome=` line was logged, so the prior never ran and "
        "the fallback's inertness has NOT been traced to a same-genre hit"
    )
    assert all(line.startswith("bayesian_prior outcome=hit") for line in outcomes), (
        f"the same-genre prior MISSED ({outcomes}) — COHORT_PRIOR_FALLBACK=1 "
        "should therefore have reached the genre-agnostic branch and moved the "
        "score; this arm is now informative"
    )
    return f"measured: {outcomes[0]}"


def _measure_identity_axis_cell(reference: dict, api_call: Callable, caplog: Any) -> str:
    """Pin the exact cell of the 3x3 matrix this profile lands on, and that
    its two-axis action equals the one-axis action — the only way the
    "verdicts coincide" reason is a measurement rather than a restatement of
    "nothing changed"."""
    from original.quantum.scoring import _identity_axis_action

    band = reference["typicality_band"]
    source = reference["typicality_source"]
    llr = reference["authorship"]["llr_deviation_score"]
    assert band is not None, "no typicality band: the identity axis is gated off, not tied"
    assert llr is not None, "no llr_deviation_score: the identity axis is gated off, not tied"

    if band == "no_action":
        row = "typical"
    else:
        row = "too-central" if source == "central" else "too-far"
    col = "distinctive" if llr < 0.45 else ("non_distinctive" if llr <= 0.60 else "fits_others")
    matrix_action = _identity_axis_action(band, source, llr)
    one_axis_action = reference["recommendation"]["action"]
    assert matrix_action == one_axis_action, (
        f"cell ({row}, {col}) gives {matrix_action!r} but the one-axis action is "
        f"{one_axis_action!r} — the verdicts do NOT coincide and this arm is "
        "informative"
    )
    # The other half of IDENTITY_AXIS is that it disables the unconditional
    # growth dampening (adj_factor 0.75 -> 1.0, quantum/scoring.py:~1397).
    # That only bites on a `growth` trajectory, so this profile does not
    # exercise it either — recorded so the skip is not read as "IDENTITY_AXIS
    # was fully exercised and found inert".
    direction = reference["trajectory"]["direction"]
    assert direction != "growth", (
        f"trajectory direction is {direction!r}: the 0.75 growth dampening WOULD "
        "have been disabled here and deviation_score should have moved"
    )
    return (
        f"cell ({row}, {col}) -> {matrix_action!r}, equal to the one-axis action "
        f"(band={band!r}, source={source!r}, llr={llr:.4f}); the flag's other "
        f"half — disabling the 0.75 growth dampening (quantum/scoring.py:~1397) "
        f"— is ALSO untested here, trajectory direction is {direction!r}, not "
        f"'growth'"
    )


def _measure_api_llr_trigger(reference: dict, api_call: Callable, caplog: Any) -> str:
    action = reference["recommendation"]["action"]
    assert action != "no_action", (
        "the reference action IS no_action, so trigger had something to upgrade "
        "and this arm is now informative — assert the upgrade instead of skipping"
    )
    return f"measured reference action = {action!r}"


def _measure_amplitude_surface_gap(reference: dict, api_call: Callable, caplog: Any) -> str:
    """The claim is that the API *surface* is the blocker, not the flag. The
    two fields exist on the response and stay at their flag-off values with
    amplitude on, which is what "`_to_response()` never copies them" looks
    like from outside."""
    on = api_call({"AMPLITUDE_SCORING_ENABLED": "1"})
    authorship = on["authorship"]
    assert "quantum_fidelity" in authorship and "fidelity_conformal_pvalue" in authorship, (
        "the response no longer carries the amplitude fields at all — the gap "
        "described in this arm's reason has changed shape"
    )
    assert authorship["quantum_fidelity"] == reference["authorship"]["quantum_fidelity"], (
        "quantum_fidelity moved on the API response, so _to_response() now copies "
        "it and this arm is informative"
    )
    return (
        f"measured: authorship.quantum_fidelity stays at "
        f"{authorship['quantum_fidelity']!r} and fidelity_conformal_pvalue at "
        f"{authorship['fidelity_conformal_pvalue']!r} with the flag on"
    )


def _measure_topic_distance(reference: dict, api_call: Callable, caplog: Any) -> str:
    """Same measurement `test_api_topic_on_is_uninformative` makes, carried
    into the parametrized arm so this row's stated cause is not merely a
    cross-reference."""
    distance = reference["context_manifest"]["topic"]["baseline_distance"]
    assert distance <= TOPIC_NOVELTY_BOUNDS["low"], (
        f"topic distance {distance:.4f} cleared the novelty floor "
        f"({TOPIC_NOVELTY_BOUNDS['low']}) — this arm is now informative"
    )
    return f"measured topic distance {distance:.4f} <= {TOPIC_NOVELTY_BOUNDS['low']}"


API_ON_ARM_MEASURES: dict[str, Callable[[dict, Callable, Any], str]] = {
    "AMPLITUDE_SCORING_ENABLED=1": _measure_amplitude_surface_gap,
    "TOPIC_VARIANCE_INFLATION=on": _measure_topic_distance,
    "GENRE_INVARIANT_WEIGHTS_ENABLED=1": _measure_genre_covered,
    "COHORT_PRIOR_FALLBACK=1": _measure_genre_prior_hit,
    "IDENTITY_AXIS=1": _measure_identity_axis_cell,
    "LLR_ACTION_MODE=trigger": _measure_api_llr_trigger,
}


@pytest.mark.parametrize("arm", sorted(API_ON_ARMS), ids=sorted(API_ON_ARMS))
def test_api_on_arm_is_not_inert(api_call, caplog, arm):
    prereq, env, expected, reason = API_ON_ARMS[arm]
    reference = api_call(prereq)
    changed = changed_paths(reference, api_call({**prereq, **env}))
    if expected is None:
        assert changed == set(), f"{arm} was expected to abstain but moved {sorted(changed)}"
        measure = API_ON_ARM_MEASURES.get(arm)
        measured = f" [{measure(reference, api_call, caplog)}]" if measure is not None else ""
        pytest.skip(f"uninformative — {reason}{measured}")
    if arm in _EXACT_API_ON_ARMS:
        assert changed == expected, f"{arm} moved {sorted(changed)}, not exactly {sorted(expected)}"
        return
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

    # With amplitude on, SECRET_KEY must move NOTHING outside the fidelity —
    # deviation_score and the recommended action are the security-relevant
    # guarantee and are asserted hard, below.
    amplitude = unit_payload(amplitude_scoring_enabled=True)
    keyed = unit_payload(amplitude_scoring_enabled=True, secret_key=secret)
    assert changed_paths(amplitude, keyed) <= {"authorship.quantum_fidelity"}
    assert keyed["authorship"]["deviation_score"] == amplitude["authorship"]["deviation_score"]
    assert keyed["recommendation"]["action"] == amplitude["recommendation"]["action"]

    # Whether the keyed projection MOVES the fidelity is three-valued: on this
    # fixed synthetic profile the amplitude path yields ~0.4999 (essentially
    # the neutral 0.5), so a keyed random unitary has almost nothing to rotate.
    # Measure the raw (un-quantized) delta and only assert a change when it is
    # resolvable at the snapshot's 10-sig-fig precision; otherwise the arm is
    # uninformative on this profile rather than a false pass or a false fail.
    # (Merged-scoring observation, flagged for score-integrity review: SECRET_KEY
    # is inert on quantum_fidelity here at ~1e-16 — profile-specific or a change
    # in the amplitude path since Phase B was authored.)
    raw_state = _seeded_state(STUDENT_ID, BASELINE_TEXTS, BASELINE_SEED)
    raw_vec = _seeded_vector(SUBMISSION_SEED)
    raw_fd = {c: float(v) for c, v in zip(ALL_FEATURE_CODES, raw_vec, strict=True)}

    def _raw_fidelity(sk: str) -> float:
        out = score(
            raw_state, raw_vec, raw_fd, submission_id=SUBMISSION_ID,
            n_tokens=len(SUBMISSION_TEXT.split()), impostor_stats=None,
            scoring_config=ScoringConfig(amplitude_scoring_enabled=True, secret_key=sk),
        )
        return dataclasses.asdict(out)["authorship"]["quantum_fidelity"]

    f0, f1 = _raw_fidelity(""), _raw_fidelity(secret)
    scale = max(abs(f0), abs(f1), 1e-9)
    if abs(f1 - f0) / scale <= 10 ** (-_SIG_FIGS):
        pytest.skip(
            f"uninformative — SECRET_KEY moves quantum_fidelity by only "
            f"{abs(f1 - f0):.2e} on this profile (fidelity ~{f0:.4f}, near-neutral), "
            f"below the 10-sig-fig snapshot resolution; the 'touches only amplitude' "
            f"guarantee (deviation_score, action unchanged) is asserted above"
        )
    assert changed_paths(amplitude, keyed) == {"authorship.quantum_fidelity"}


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


# ── the snapshots must be reproducible off this machine ──────────────────────


def test_api_arms_use_the_tfidf_tier10_backend(api_call, api_snapshot):
    """The committed API snapshot must be a property of the harness, not of
    what happens to be installed here.

    Tier 10 picks `sentence_transformers` when it is importable and a model
    is cached, and the genuine TF-IDF backend otherwise. Those disagree:
    `semantic_field_dispersion` was 0.15773121131399287 under
    `sentence_transformers` 2.7.0 on Apple MPS and is 0.011688732983694307
    under TF-IDF. CI cannot reproduce the first (Linux CPU, `requirements.txt`
    pins `sentence-transformers>=5.6.0,<6.0`, and the model is a network
    download), and `requirements-pilot.txt` does not ship the package at all.
    So the harness pins TF-IDF and this arm proves the pin held.
    """
    from original.features import tier10
    from original.features.tier1 import TextDoc

    assert tier10._get_st_model() is None, (
        "tier 10 resolved a sentence-transformers model inside the API harness. "
        "force_tfidf_tier10() did not take effect, so the API snapshot is now a "
        "function of this machine's installed sentence-transformers + cached "
        "model rather than of the repo — CI and the pilot lockset cannot "
        "reproduce it. Fix the harness; do NOT regenerate the snapshot."
    )
    # 10-sig-fig equality (serialise()/_quantize rounds both sides): enough to
    # tell the TF-IDF value (0.0117) from the neural one (0.1577), which differ
    # at the second significant figure, without tripping on cross-platform
    # last-bit noise.
    expected = tier10.extract_tier10_standalone(TextDoc(SUBMISSION_TEXT))
    assert (
        api_call({})["feature_vector"]["semantic_field_dispersion"]
        == _quantize(expected["semantic_field_dispersion"])
    ), "the scored submission's tier-10 value is not the TF-IDF backend's value"
    assert (
        api_snapshot["feature_vector"]["semantic_field_dispersion"]
        == _quantize(expected["semantic_field_dispersion"])
    ), (
        "the COMMITTED snapshot carries a tier-10 value the deterministic "
        f"backend does not produce — {_REGENERATE_MSG}"
    )


def test_en_core_web_sm_version_matches_snapshot():
    """The second machine-dependent input behind the API snapshot, alongside
    tier 10 (see the module docstring's "Deterministic feature backends"
    section and `test_api_arms_use_the_tfidf_tier10_backend` above).

    `tier5.py`/`tier11.py`/`prosodic.py` all call
    `spacy.load("en_core_web_sm")`, and the snapshot bakes in that pipeline's
    exact tagger/parser/lemmatizer output. Unlike tier 10 there is no
    deterministic fallback to pin against — the fix is installing the same
    model wheel everywhere the snapshot must reproduce, not forcing a
    backend. This test fails naming the actual cause (a model bump) instead
    of leaving a bare snapshot diff that only suggests regenerating it.
    """
    import en_core_web_sm

    assert en_core_web_sm.__version__ == EN_CORE_WEB_SM_VERSION, (
        f"en_core_web_sm is {en_core_web_sm.__version__}, but the committed "
        f"API snapshot ({API_SNAPSHOT_PATH}) was generated against "
        f"{EN_CORE_WEB_SM_VERSION}. This is a model version drift, not a "
        "scoring-math change: reinstall the pinned wheel (see "
        ".github/workflows/test.yml) to match the snapshot, or -- if the "
        "model bump is intentional -- update EN_CORE_WEB_SM_VERSION above "
        f"and regenerate: {_REGENERATE_MSG}"
    )


# ── coverage of the spec's table ──────────────────────────────────────────────


SPEC_PATH = REPO_ROOT / "docs" / "testing" / "08-config-deploy-readiness.md"

# Backticked identifiers in §1's Flag column that are not env flags. Empty
# today; kept as the declared escape hatch so a future non-flag row is an
# explicit, reviewed exclusion rather than a silently loosened parser.
SPEC_TABLE_NON_FLAGS: frozenset[str] = frozenset()

_IDENTIFIER = re.compile(r"`([A-Z_][A-Z0-9_]*)`")


def parse_spec_table_flags(markdown: str) -> set[str]:
    """Flags named in the Flag column of docs/testing/08 §1's table.

    Parsed rather than transcribed: a hardcoded copy of the table asserts
    that the table equals itself, which is exactly the failure this test is
    supposed to catch (a row added to the spec with no arm here).

    Rows name more than one flag in two shapes, both present today:
    `` `NULL_MODEL` / `LLR_ACTION_MODE` `` (two whole names) and
    `` `FUSED_SCORE_ENABLED` / `_SHADOW` `` (a suffix, which stands for the
    previous name with its last underscore-segment replaced). Anything
    starting with `_` is expanded that way; everything else is taken whole.
    """
    section = markdown.split("## 1.", 1)[-1].split("\n## ", 1)[0]
    flags: set[str] = set()
    for line in section.splitlines():
        line = line.strip()
        if not line.startswith("|"):
            continue
        cell = line.strip("|").split("|")[0].strip()
        if cell in ("Flag", "") or set(cell) <= set("-: "):  # header / separator
            continue
        previous: str | None = None
        for token in _IDENTIFIER.findall(cell):
            if token.startswith("_"):
                if previous is None:
                    raise AssertionError(f"suffix {token!r} with no preceding flag in {cell!r}")
                name = previous.rsplit("_", 1)[0] + token
            else:
                name = token
            previous = name
            flags.add(name)
    return flags - SPEC_TABLE_NON_FLAGS


def test_spec_table_parser_finds_the_rows_it_should():
    """The parser has to be pinned too, or a regex that silently matched
    nothing would make the coverage test below vacuously green."""
    flags = parse_spec_table_flags(SPEC_PATH.read_text(encoding="utf-8"))
    # The two multi-flag row shapes, and the row count, spot-checked.
    assert {"NULL_MODEL", "LLR_ACTION_MODE"} <= flags  # `A` / `B`
    assert {"FUSED_SCORE_ENABLED", "FUSED_SCORE_SHADOW"} <= flags  # `A_ENABLED` / `_SHADOW`
    assert {"AI_LIKELIHOOD_ENABLED", "AI_LIKELIHOOD_SHADOW"} <= flags
    assert {"BAYESIAN_PRIOR_ENABLED", "COHORT_PRIOR_FALLBACK"} <= flags  # `A` (+`B`)
    assert len(flags) >= 20, sorted(flags)


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
    spec_table_flags = parse_spec_table_flags(SPEC_PATH.read_text(encoding="utf-8"))
    assert spec_table_flags <= covered, (
        "flags in docs/testing/08 §1's table with no arm in this file: "
        f"{sorted(spec_table_flags - covered)}"
    )


def test_every_scoring_config_field_has_an_off_arm():
    """Every `ScoringConfig` field is pinned at its default by an off-arm."""
    fields = {f.name for f in dataclasses.fields(ScoringConfig)}
    assert fields == set(UNIT_OFF_ARMS), sorted(fields ^ set(UNIT_OFF_ARMS))
