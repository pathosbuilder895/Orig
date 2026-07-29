"""
scripts/measure_genre_prior_scope.py — one-off coverage measurement.

Answers: if get_genre_stats were tenant-scoped, how often would the
BAYESIAN_PRIOR_ENABLED cold-start prior resolve to None that it doesn't today?

Simulates the real gate at original/routers/students_scoring.py:126-134 —
a student is a "cold-start scoring event" when sample_count < 10 and their
most recent sample carries a genre label — then asks, for each such student,
whether a prior would exist under (a) today's cross-tenant pooling and
(b) tenant-scoped pooling.

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

# Floors under evaluation. MIN_VECTORS is today's hardcoded 5.
# MIN_STUDENTS models Task 5's proposed distinct-student floor; set it to 1
# to see the effect of tenant-scoping alone (Tasks 2-4 without Task 5).
MIN_VECTORS = 5
MIN_STUDENTS = 3


def main() -> None:
    repo = get_repository()
    states = repo.all_states()
    print(f"database: {os.environ.get('ORIGINAL_DB', 'profiles.db')}")
    print(f"students: {len(states)}")

    scoped_vectors: dict[tuple[str | None, str], int] = defaultdict(int)
    scoped_students: dict[tuple[str | None, str], set[str]] = defaultdict(set)
    global_vectors: dict[str, int] = defaultdict(int)

    for state in states:
        tenant = tenant_of(state.student_id)
        for sample in state.samples:
            if (getattr(sample, "auth_weight", 0) or 0) <= 0:
                continue
            genre = getattr(sample, "genre", None)
            if not genre:
                continue
            scoped_vectors[(tenant, genre)] += 1
            scoped_students[(tenant, genre)].add(state.student_id)
            global_vectors[genre] += 1

    eligible = 0
    have_global = 0
    have_scoped = 0
    have_scoped_floored = 0
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
        key = (tenant, genre)

        global_ok = global_vectors[genre] >= MIN_VECTORS
        scoped_ok = scoped_vectors[key] >= MIN_VECTORS
        floored_ok = scoped_ok and len(scoped_students[key]) >= MIN_STUDENTS

        have_global += global_ok
        have_scoped += scoped_ok
        have_scoped_floored += floored_ok
        if global_ok and not scoped_ok:
            lost_by_tenant[tenant] += 1

    print()
    print(f"cold-start scoring events with a genre label: {eligible}")
    if eligible:
        print(f"  prior available today (cross-tenant):   {have_global:5d}  ({have_global / eligible:.0%})")
        print(f"  prior available tenant-scoped:          {have_scoped:5d}  ({have_scoped / eligible:.0%})")
        print(f"  ... and with a >={MIN_STUDENTS}-student floor:      {have_scoped_floored:5d}  ({have_scoped_floored / eligible:.0%})")
    else:
        print("  (no eligible events — this dataset cannot answer the question)")

    print()
    print("priors lost to tenant-scoping, by tenant:")
    if lost_by_tenant:
        for tenant, count in sorted(lost_by_tenant.items(), key=lambda kv: -kv[1]):
            print(f"  {tenant!r}: {count}")
    else:
        print("  none")

    print()
    print("(tenant, genre) pools — vectors / distinct students:")
    if scoped_vectors:
        for key in sorted(scoped_vectors, key=lambda k: -scoped_vectors[k]):
            tenant, genre = key
            print(
                f"  {str(tenant)!r:22} {genre:28} "
                f"{scoped_vectors[key]:4d} vec  {len(scoped_students[key]):3d} stu"
            )
    else:
        print("  none — no authenticated samples carry a genre label")


if __name__ == "__main__":
    main()
