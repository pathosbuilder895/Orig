"""
scripts/measure_genre_prior_scope.py — genre-prior coverage measurement.

Answers: with BAYESIAN_PRIOR_ENABLED on, how often would the cold-start prior
actually resolve, and how often would it fall back to the student-only
baseline? CLAUDE.md names this script as the pre-flight step before enabling
that flag, so it models CURRENT behaviour, not any earlier revision of it:

  * tenant-scoped     — the pool is same-tenant only (tenant_of of the scored
                        student's id; None, the legacy-flat cohort, is its own)
  * self-excluding    — the scored student is removed from their own pool
  * two floors        — MIN_GENRE_VECTORS vectors AND MIN_GENRE_STUDENTS
                        distinct contributing students, checked against what
                        remains after the exclusion

The "pre-fix (cross-tenant, no floors)" column is kept only as the historical
baseline the tenant-scoping change moved away from — it is NOT what the code
does now.

Simulates the real gate at original/routers/students_scoring.py — a student is
a "cold-start scoring event" when sample_count < 10 and their most recent
sample carries a genre label.

Run against whichever database ORIGINAL_DB / DATABASE_URL points at:

    ORIGINAL_DB=profiles.db .venv/bin/python scripts/measure_genre_prior_scope.py
"""

from __future__ import annotations

import os
import sys
from collections import defaultdict
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

from original.principal import tenant_of  # noqa: E402
from original.repository import get_repository  # noqa: E402

# Imported, not re-declared, so this measurement cannot drift from the floors
# the scorer actually applies.
from original.store import MIN_GENRE_STUDENTS, MIN_GENRE_VECTORS  # noqa: E402


def main() -> None:
    repo = get_repository()
    states = repo.all_states()
    print(f"database: {os.environ.get('ORIGINAL_DB', 'profiles.db')}")
    print(f"students: {len(states)}")
    print(f"floors: {MIN_GENRE_VECTORS} vectors, {MIN_GENRE_STUDENTS} distinct students")

    # (tenant, genre) -> {student_id: authenticated same-genre vector count}
    pools: dict[tuple[str | None, str], dict[str, int]] = defaultdict(dict)
    global_vectors: dict[str, int] = defaultdict(int)

    for state in states:
        tenant = tenant_of(state.student_id)
        for sample in state.samples:
            if (getattr(sample, "auth_weight", 0) or 0) <= 0:
                continue
            genre = getattr(sample, "genre", None)
            if not genre:
                continue
            per_student = pools[(tenant, genre)]
            per_student[state.student_id] = per_student.get(state.student_id, 0) + 1
            global_vectors[genre] += 1

    eligible = 0
    have_prefix = 0  # historical: cross-tenant, vector floor only, no exclusion
    have_current = 0  # what the code does now
    lost_by_tenant: dict[str | None, int] = defaultdict(int)

    for state in states:
        # Mirrors students_scoring.py's gate exactly.
        if state.sample_count >= 10 or not state.samples:
            continue
        genre = getattr(state.samples[-1], "genre", None)
        if not genre:
            continue
        eligible += 1
        tenant = tenant_of(state.student_id)
        per_student = pools[(tenant, genre)]

        # Self-exclusion: the scored student's own contribution never counts
        # toward either floor — this is the step that makes the numbers below
        # match what the scorer will really do.
        peers = {sid: n for sid, n in per_student.items() if sid != state.student_id}
        peer_vectors = sum(peers.values())

        prefix_ok = global_vectors[genre] >= MIN_GENRE_VECTORS
        current_ok = peer_vectors >= MIN_GENRE_VECTORS and len(peers) >= MIN_GENRE_STUDENTS

        have_prefix += prefix_ok
        have_current += current_ok
        if prefix_ok and not current_ok:
            lost_by_tenant[tenant] += 1

    print()
    print(f"cold-start scoring events with a genre label: {eligible}")
    if eligible:
        print(
            f"  prior available, CURRENT behaviour:     "
            f"{have_current:5d}  ({have_current / eligible:.0%})"
        )
        print(
            f"  (historical pre-fix cross-tenant pool:  "
            f"{have_prefix:5d}  ({have_prefix / eligible:.0%}) — not what runs now)"
        )
    else:
        print("  (no eligible events — this dataset cannot answer the question)")

    print()
    print("priors lost vs the pre-fix pool, by tenant:")
    if lost_by_tenant:
        for tenant, count in sorted(lost_by_tenant.items(), key=lambda kv: -kv[1]):
            print(f"  {tenant!r}: {count}")
    else:
        print("  none")

    print()
    print("(tenant, genre) pools — vectors / distinct students (before exclusion):")
    if pools:
        for key in sorted(pools, key=lambda k: -sum(pools[k].values())):
            tenant, genre = key
            print(
                f"  {str(tenant)!r:22} {genre:28} "
                f"{sum(pools[key].values()):4d} vec  {len(pools[key]):3d} stu"
            )
    else:
        print("  none — no authenticated samples carry a genre label")


if __name__ == "__main__":
    main()
