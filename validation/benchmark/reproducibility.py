"""
reproducibility.py — lock the environment so benchmark runs are bit-exact.

A benchmark report is only useful if anyone can re-run it and get the same
numbers. This module is the single place we set the knobs that govern
non-determinism in Original's scoring stack:

    - SECRET_KEY                  : fixed → keyed random unitary is deterministic
    - ADAPTIVE_WEIGHTS_ENABLED    : 0    → fixed-weight version that ships to pilots
    - AMPLITUDE_SCORING_ENABLED   : 0    → no Phase-6 amplitude branch
    - BAYESIAN_PRIOR_ENABLED      : 0    → no cold-start blend
    - LENGTH_ADAPTIVE_WEIGHTS     : 0    → no length-schedule scaling
    - IDENTITY_AXIS               : 0    → no Phase-2 action-matrix branch
    - NULL_MODEL                  : none → no impostor null pool
    - ENVIRONMENT                 : testing → strict-mode flags off
    - ORIGINAL_DB                 : fresh temp file → no cross-run store contamination
    - HF_HUB_OFFLINE              : 1    → semantic backend cannot vary with network/cache discovery
    - TRANSFORMERS_OFFLINE        : 1    → fail fast to the deterministic TF-IDF fallback
    - random.seed / numpy seed    : BENCHMARK_SEED

Every env-var-gated branch in ``original/quantum/scoring.py`` and
``original/quantum/state.py`` is pinned so no cross-shell-leak (a
``LENGTH_ADAPTIVE_WEIGHTS=1`` left over from a prior process, for
example) can change scoring behind our back.

Anyone running a benchmark **must** call ``lock_environment()`` before
loading any ``original.*`` modules — otherwise the random unitary is
generated from a process-startup token and the report won't reproduce.

Idempotent: safe to call multiple times.
"""

from __future__ import annotations

import os
import random
import tempfile
from dataclasses import dataclass

BENCHMARK_SEED = 1729  # Ramanujan's taxicab number — same one calibration.py uses

# One throwaway store per process, created lazily on the first
# lock_environment() call and reused by later calls (flipping the path
# mid-run would drop every profile built so far).
_BENCH_DB_PATH: str | None = None


def _bench_db_path() -> str:
    global _BENCH_DB_PATH
    if _BENCH_DB_PATH is None:
        fd, path = tempfile.mkstemp(prefix="original_bench_", suffix=".db")
        os.close(fd)
        _BENCH_DB_PATH = path
    return _BENCH_DB_PATH


# ── Every env-var-gated scoring flag, mapped to its pinned default. ─────────
# The value is what lock_environment() writes into os.environ. Keep this
# dict in sync with every `os.environ.get(...)` read in original/quantum/.
_SCORING_FLAG_DEFAULTS = {
    "CONTEXT_MANIFEST_ENABLED": "0",  # report metadata only; keep frozen Phase-1 path
    "ADAPTIVE_WEIGHTS_ENABLED": "0",  # Phase 5 context-adaptive weights
    "AMPLITUDE_SCORING_ENABLED": "0",  # Phase 6 amplitude branch
    "BAYESIAN_PRIOR_ENABLED": "0",  # cold-start prior blend
    "LENGTH_ADAPTIVE_WEIGHTS": "0",  # length-schedule scaling
    "RANK_REMEDIATION": "none",  # density-matrix shrinkage ablation
    "STYLE_AUTHORSHIP_ENABLED": "0",  # report-only learned expert
    # Phase 2 identity-axis pair: with IDENTITY_AXIS=1 AND NULL_MODEL=impostor
    # leaked from a shell (run.py --demo sets NULL_MODEL=impostor), the
    # typicality x llr_deviation_score action matrix can CHANGE actions, which
    # would silently move every gate/benchmark number. Runners that study the
    # impostor null on purpose (validation/verify/run_null_model.py) set
    # NULL_MODEL=impostor themselves AFTER locking, so this pin never blocks
    # an intentional enable.
    "IDENTITY_AXIS": "0",
    "NULL_MODEL": "none",
}


@dataclass(frozen=True)
class _EnvLockReport:
    """What lock_environment() set. Returned for visibility / debugging."""

    secret_key: str
    environment: str
    original_db: str
    numpy_seeded: bool
    python_seeded: bool
    model_hub_offline: bool
    scoring_flags: dict  # {flag_name: pinned_value}


def lock_environment(seed: int = BENCHMARK_SEED) -> _EnvLockReport:
    """
    Set every knob that affects scoring determinism. Call BEFORE importing
    any ``original.*`` module — otherwise the keyed random unitary is
    generated from a startup-time random token and your benchmark will not
    reproduce across runs.

    Args:
        seed: integer seed for Python ``random`` and NumPy. Defaults to
              BENCHMARK_SEED (1729) so two callers default to the same seed.

    Returns:
        _EnvLockReport summarising what was set. Useful in the report
        header so a reviewer can see "this is what the benchmark assumed".
    """
    # 1. The SECRET_KEY drives the keyed random unitary in quantum/scoring.py.
    #    If it varies across runs, the projection varies, the deviation
    #    varies, and the benchmark is not reproducible.
    secret = "bench-key-do-not-deploy-01234567890123456789"
    os.environ["SECRET_KEY"] = secret

    # 2. Pin every env-var-gated scoring flag. Even if the current default
    #    is "0", we OVERWRITE from any leaked value in the shell so
    #    identical runs stay identical.
    for name, value in _SCORING_FLAG_DEFAULTS.items():
        os.environ[name] = value

    # 3. ENVIRONMENT=testing disables strict-production checks that would
    #    fail loudly on the test-only SECRET_KEY above.
    os.environ.setdefault("ENVIRONMENT", "testing")

    # 4. Point the student-state store at a throwaway per-process SQLite
    #    file so the benchmark never reads from or writes to the real
    #    profile DB. NOT ":memory:": since WS-6 P6 removed the _STORE
    #    profile cache, store._get_conn() opens a fresh connection per
    #    call, and ":memory:" gives every connection its own empty
    #    database — TestClient-based harnesses would 404 on every score.
    os.environ["ORIGINAL_DB"] = _bench_db_path()

    # 5. Benchmarks must not silently switch feature backends depending on
    # network availability. If the transformer model is already cached it may
    # load locally; otherwise Tier 10 immediately uses its real TF-IDF backend.
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"

    # 6. Seed Python random + NumPy. Some feature extractors use random
    #    for sampling (e.g. character trigram sampling at the limit); some
    #    quantum-state computations use NumPy random. Seed both.
    random.seed(seed)
    try:
        import numpy as np

        np.random.seed(seed)
        numpy_seeded = True
    except Exception:
        numpy_seeded = False

    return _EnvLockReport(
        secret_key=_redacted(secret),
        environment=os.environ["ENVIRONMENT"],
        original_db=os.environ["ORIGINAL_DB"],
        numpy_seeded=numpy_seeded,
        python_seeded=True,
        model_hub_offline=True,
        scoring_flags=dict(_SCORING_FLAG_DEFAULTS),
    )


def _redacted(s: str) -> str:
    """Don't echo the full key into a public report — show prefix + length."""
    return f"{s[:12]}…({len(s)} chars)"
