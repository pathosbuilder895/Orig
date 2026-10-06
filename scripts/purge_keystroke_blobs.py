#!/usr/bin/env python3
"""
purge_keystroke_blobs.py — one-off redaction of raw keystroke arrays already
at rest (ADR-010 / T-74: docs/adr/ADR-010-keystroke-macro-only.md).

``original/routers/students_baseline.py`` stops persisting the raw per-key
``keystrokes`` and per-pause ``pauses`` arrays on ingest going forward (see
``_strip_raw_keystroke_arrays`` there). This script is the matching one-way
cleanup for rows written *before* that change — every ``keystroke_data`` blob
already at rest may still carry those two raw arrays.

Works against BOTH backends via the Repository abstraction
(``original.repository.get_repository()`` — SQLite locally/demo, Postgres in
production via ``REPO_BACKEND=postgres``), not raw SQL, since the two
backends store the JSON document differently. ``all_states()`` with no
``tenant_id`` filter is a genuine whole-table scan across every tenant (see
``original.store.all_states`` / ``PostgresRepository.all_states``) — exactly
what a one-off privacy-minimizing purge needs; a per-tenant scoped call would
silently leave other tenants' blobs untouched.

For each ``StudentState``, every ``BaselineSample`` whose ``keystroke_data``
contains ``"keystrokes"`` or ``"pauses"`` is one "sample to purge". Dry-run
(default) only counts and reports, per-student and total, and touches
nothing. ``--apply`` strips those two keys from each affected sample's
``keystroke_data`` (every other key — ``revisions``, ``deletionRate``,
``wordCount``, etc. — is a macro/summary field and is kept) and calls
``repo.put(state)`` once per *student* who has at least one affected sample,
not once per sample — put() rewrites the whole student document, so batching
per student avoids redundant writes when several of their samples are
affected.

The stripping logic is a small, deliberate duplicate of
``original.routers.students_baseline._strip_raw_keystroke_arrays`` rather than
an import of it: that module pulls in FastAPI and the rest of the live
router's dependency graph (bbook_client, student_auth, ...) purely to remove
two dict keys, which is not worth coupling a maintenance script to. The
key set (``keystrokes``, ``pauses``) is frozen by ADR-010, so the two copies
drifting apart is not a realistic maintenance risk.

Usage:
    .venv/bin/python scripts/purge_keystroke_blobs.py            # dry run (default)
    .venv/bin/python scripts/purge_keystroke_blobs.py --apply    # actually rewrite

    # Postgres (production): set REPO_BACKEND=postgres and DATABASE_URL first.
    REPO_BACKEND=postgres DATABASE_URL=postgresql://... \\
        .venv/bin/python scripts/purge_keystroke_blobs.py --apply

CAUTION (operator-facing, code review of T-74 2026-09-21): PostgresRepository
.all_states() fails CLOSED-BUT-SILENT on any scan error (bad connection,
transient DB issue, permissions) — it logs and returns an empty list rather
than raising. A dry-run's "0 sample(s) would be purged" is therefore
indistinguishable from "the scan actually failed" and from "the database is
genuinely already clean". Before trusting a dry-run report of zero on
Postgres, separately confirm the connection is healthy (e.g. check the
process log for a scan-failure entry, or cross-check the reported
student count against a known roster size) — this script does not detect
that condition itself. See docs/testing/10-gap-register.md T-76.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Repo root on sys.path so `original.*` resolves when this script is run
# directly (e.g. `.venv/bin/python scripts/purge_keystroke_blobs.py`) rather
# than imported as a module with the repo root already on sys.path —
# matches the established pattern in scripts/measure_genre_prior_scope.py.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from original.repository import get_repository  # noqa: E402

_RAW_KEYS = ("keystrokes", "pauses")


def _strip_raw_keystroke_arrays(keystroke_data: dict | None) -> dict | None:
    """Mirrors original.routers.students_baseline._strip_raw_keystroke_arrays
    (see module docstring for why this is a duplicate, not an import)."""
    if keystroke_data is None:
        return None
    stripped = dict(keystroke_data)
    for key in _RAW_KEYS:
        stripped.pop(key, None)
    return stripped


def _needs_purge(keystroke_data: dict | None) -> bool:
    """True iff this blob still carries a raw per-key/per-pause array."""
    if not keystroke_data:
        return False
    return any(key in keystroke_data for key in _RAW_KEYS)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--apply", action="store_true", help="actually rewrite (default is a dry run)")
    args = ap.parse_args(argv)

    repo = get_repository()
    states = repo.all_states()  # tenant_id=None — every tenant, by design.

    mode = "APPLY" if args.apply else "DRY RUN"
    print(f"[{mode}] scanning {len(states)} student(s)")

    total_samples = 0
    total_students = 0
    for state in states:
        affected = [s for s in state.samples if _needs_purge(s.keystroke_data)]
        if not affected:
            continue
        total_students += 1
        total_samples += len(affected)
        print(f"  {state.student_id:40} {len(affected):4d} sample(s)")
        if args.apply:
            for sample in affected:
                sample.keystroke_data = _strip_raw_keystroke_arrays(sample.keystroke_data)
            repo.put(state)

    if args.apply:
        print(f"Purged {total_samples} sample(s) across {total_students} student(s).")
    else:
        print(
            f"{total_samples} sample(s) across {total_students} student(s) would be "
            "purged. Re-run with --apply to do it."
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
