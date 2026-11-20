#!/usr/bin/env python3
"""
backfill_measurements.py — store a second measurement next to every past paper
(versioned measurements: original/measurement.py, docs/adr/ADR-014).

Each past paper (``BaselineSample``) keeps its ``vector`` (the default "v1"
measurement, untouched by this script). This script measures each paper's
stored text again the way ``--measurement`` names ("fs2", "matter" or
"fs2+matter"; default "fs2+matter") and stores the result in the paper's
``extra_vectors``. Scoring uses that measurement only once every past paper of
a student has it, and only when FEATURE_SET / MATTER_SPLITTER_ENABLED ask for
it (both off by default).

Safety
------
* Dry run by default: measures nothing, writes nothing, reports what it would
  do (``--measure`` in a dry run also runs the extraction, still writing
  nothing, to time it).
* Writing needs both ``--apply`` and ``--confirm <measurement>`` repeating the
  measurement name, so a pasted command cannot write by accident.
* Idempotent: a paper that already has the measurement is skipped; a second
  run writes nothing.
* Never changes ``vector``, any score, any setting, or any paper's text.
* Before each write the student is read again; if their past papers changed
  meanwhile (a paper added or removed) that student is skipped and reported,
  never overwritten. Run it in a quiet window anyway.
* One student at a time (``list_ids`` + ``get``), so memory stays at one
  student's papers plus one extraction.
* Nothing runs it automatically: it is not in render.yaml, any start script or
  any workflow (tests/test_backfill_measurements.py checks).

Backends: the Repository abstraction (``original.repository.get_repository``),
so it works the same on SQLite (default) and Postgres (``REPO_BACKEND=postgres``
and ``DATABASE_URL``). On Postgres, ``list_ids`` returns an empty list on a
scan error, so a report of 0 students must be cross-checked against the roster.

Usage:
    python scripts/backfill_measurements.py                         # dry run
    python scripts/backfill_measurements.py --student tenant:alice  # one student
    python scripts/backfill_measurements.py --apply --confirm fs2+matter

Exit status: 0 on success, 1 if any paper failed to measure or any student
was skipped because their papers changed.
"""

from __future__ import annotations

import argparse
import hashlib
import logging
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np  # noqa: E402

from original.constants import FEATURE_DIM  # noqa: E402
from original.features import feature_flags as ff  # noqa: E402

log = logging.getLogger("backfill_measurements")

CHOICES = tuple(m for m in ff.MEASUREMENTS if m != "v1")


@dataclass
class Report:
    measurement: str
    apply: bool
    students: int = 0
    papers: int = 0
    already: int = 0
    to_measure: int = 0
    measured: int = 0
    written_students: int = 0
    no_text: int = 0
    failed: list[str] = field(default_factory=list)
    changed: list[str] = field(default_factory=list)

    def lines(self) -> list[str]:
        mode = "APPLY" if self.apply else "DRY RUN (nothing written)"
        out = [
            f"backfill {self.measurement}: {mode}",
            f"  students: {self.students}",
            f"  past papers: {self.papers}",
            f"  already measured as {self.measurement}: {self.already}",
            f"  {'measured' if self.apply else 'would measure'}: "
            f"{self.measured if self.apply else self.to_measure}",
            f"  papers with no stored text (cannot be measured; that student "
            f"stays on v1): {self.no_text}",
        ]
        if self.apply:
            out.append(f"  students written: {self.written_students}")
        if self.failed:
            out.append(f"  failed: {len(self.failed)} ({', '.join(self.failed[:10])})")
        if self.changed:
            out.append(
                f"  skipped, papers changed during the run: {', '.join(self.changed[:10])}"
            )
        return out


def _fingerprint(state) -> list[str]:
    return [hashlib.sha256((s.text or "").encode()).hexdigest() for s in state.samples]


def _measure(text: str, measurement: str, extract: Callable) -> np.ndarray:
    with ff.measuring(measurement):
        vector = np.asarray(extract(text), dtype=np.float64)
    if vector.shape != (FEATURE_DIM,):
        raise ValueError(f"vector has shape {vector.shape}, expected ({FEATURE_DIM},)")
    return vector


def backfill(
    repo,
    measurement: str,
    *,
    apply: bool,
    students: Sequence[str] | None = None,
    measure_in_dry_run: bool = False,
    extract: Callable | None = None,
) -> Report:
    if measurement not in CHOICES:
        raise ValueError(f"unknown measurement {measurement!r}; choose one of {CHOICES}")
    if extract is None:
        from original.features.pipeline import feature_vector as extract
    report = Report(measurement, apply)
    ids = list(students) if students else repo.list_ids()
    for student_id in ids:
        state = repo.get(student_id)
        if state is None:
            report.failed.append(f"{student_id} (not found)")
            continue
        report.students += 1
        new: dict[int, np.ndarray] = {}
        for i, sample in enumerate(state.samples):
            report.papers += 1
            if (sample.extra_vectors or {}).get(measurement) is not None:
                report.already += 1
                continue
            if not sample.text:
                report.no_text += 1
                continue
            report.to_measure += 1
            if not (apply or measure_in_dry_run):
                continue
            try:
                new[i] = _measure(sample.text, measurement, extract)
            except Exception as exc:
                log.warning("%s paper %d: measurement failed: %s", student_id, i, exc)
                report.failed.append(f"{student_id}#{i}")
        if not apply or not new:
            continue
        fresh = repo.get(student_id)
        if fresh is None or _fingerprint(fresh) != _fingerprint(state):
            report.changed.append(student_id)
            continue
        for i, vector in new.items():
            sample = fresh.samples[i]
            sample.extra_vectors = {**(sample.extra_vectors or {}), measurement: vector}
        repo.put(fresh)
        report.measured += len(new)
        report.written_students += 1
    return report


def main(argv: Sequence[str] | None = None, repo=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--measurement", default="fs2+matter", choices=CHOICES)
    parser.add_argument("--student", action="append", help="only this student id (repeatable)")
    parser.add_argument("--apply", action="store_true", help="write (needs --confirm)")
    parser.add_argument("--confirm", default=None, help="repeat the measurement name to write")
    parser.add_argument(
        "--measure",
        action="store_true",
        help="in a dry run, also run the extraction (to time it); still writes nothing",
    )
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    if args.apply and args.confirm != args.measurement:
        parser.error(f"--apply needs --confirm {args.measurement} (nothing was written)")
    if repo is None:
        from original.repository import backend_name, get_repository

        repo = get_repository()
        print(f"backend: {backend_name()}")
    report = backfill(
        repo,
        args.measurement,
        apply=args.apply,
        students=args.student,
        measure_in_dry_run=args.measure,
    )
    print("\n".join(report.lines()))
    return 1 if report.failed or report.changed else 0


if __name__ == "__main__":
    sys.exit(main())
