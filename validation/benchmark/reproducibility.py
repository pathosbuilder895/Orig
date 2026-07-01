"""
reproducibility.py — lock the environment so benchmark runs are bit-exact.

A benchmark report is only useful if anyone can re-run it and get the same
numbers. This module is the single place we set the knobs that govern
non-determinism in Original's scoring stack:

    - SECRET_KEY                : fixed → keyed random unitary is deterministic
    - ADAPTIVE_WEIGHTS_ENABLED  : 0    → fixed-weight version that ships to pilots
    - ENVIRONMENT               : testing → strict-mode flags off
    - ORIGINAL_DB               : :memory: → no cross-run student-store contamination
    - random.seed / numpy seed  : BENCHMARK_SEED

Anyone running a benchmark **must** call ``lock_environment()`` before
loading any ``original.*`` modules — otherwise the random unitary is
generated from a process-startup token and the report won't reproduce.

Idempotent: safe to call multiple times.
"""

from __future__ import annotations

import os
import random
from dataclasses import dataclass

BENCHMARK_SEED = 1729   # Ramanujan's taxicab number — same one calibration.py uses


@dataclass(frozen=True)
class _EnvLockReport:
    """What lock_environment() set. Returned for visibility / debugging."""
    secret_key: str
    adaptive_weights_enabled: str
    environment: str
    original_db: str
    numpy_seeded: bool
    python_seeded: bool


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

    # 2. Adaptive weights are a per-context modification on top of the fixed
    #    tier weights. The benchmark measures the FIXED model that ships to
    #    pilots — if we leave adaptive weights on, two reviewers comparing
    #    notes will get different numbers depending on the context manifest
    #    that happens to be active.
    os.environ["ADAPTIVE_WEIGHTS_ENABLED"] = "0"

    # 3. ENVIRONMENT=testing disables strict-production checks that would
    #    fail loudly on the test-only SECRET_KEY above.
    os.environ.setdefault("ENVIRONMENT", "testing")

    # 4. Point the student-state store at an in-memory SQLite so the
    #    benchmark never reads from or writes to the real profile DB.
    os.environ["ORIGINAL_DB"] = ":memory:"

    # 5. Seed Python random + NumPy. Some feature extractors use random
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
        adaptive_weights_enabled="0",
        environment=os.environ["ENVIRONMENT"],
        original_db=":memory:",
        numpy_seeded=numpy_seeded,
        python_seeded=True,
    )


def _redacted(s: str) -> str:
    """Don't echo the full key into a public report — show prefix + length."""
    return f"{s[:12]}…({len(s)} chars)"
