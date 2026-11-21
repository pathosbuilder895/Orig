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
* Splitter rules version (``original/features/matter.py`` ``RULES_VERSION``):
  a splitter measurement ("matter", "fs2+matter", and a teacher's
  ``choice_vectors``) made under other rules than today's counts as missing
  and is measured again; one stored before stamps existed (taken as
  ``UNSTAMPED_RULES_VERSION``) and still current is only stamped, never
  measured again. Every splitter measurement it writes carries the stamp.
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

from original import measurement as _measurement  # noqa: E402
from original.constants import FEATURE_DIM  # noqa: E402
from original.features import feature_flags as ff  # noqa: E402
from original.features import matter, part_overrides  # noqa: E402

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
    stale: int = 0
    to_stamp: int = 0
    stamped: int = 0
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
        if self.stale:
            out.append(f"  made under older splitter rules (measured again): {self.stale}")
        if self.to_stamp or self.stamped:
            out.append(
                f"  {'stamped' if self.apply else 'would stamp'} with splitter rules "
                f"v{matter.RULES_VERSION} (no new measurement): "
                f"{self.stamped if self.apply else self.to_stamp}"
            )
        if self.apply:
            out.append(f"  students written: {self.written_students}")
        if self.failed:
            out.append(f"  failed: {len(self.failed)} ({', '.join(self.failed[:10])})")
        if self.changed:
            out.append(f"  skipped, papers changed during the run: {', '.join(self.changed[:10])}")
        return out


def _fingerprint(state) -> list[str]:
    return [hashlib.sha256((s.text or "").encode()).hexdigest() for s in state.samples]


def _checked(vector) -> np.ndarray:
    vector = np.asarray(vector, dtype=np.float64)
    if vector.shape != (FEATURE_DIM,):
        raise ValueError(f"vector has shape {vector.shape}, expected ({FEATURE_DIM},)")
    return vector


def _same(sample, before, measurement: str) -> bool:
    """``sample`` (read again before writing) still holds the ``measurement``
    vector ``before`` (the first read) held."""
    a = (sample.extra_vectors or {}).get(measurement)
    b = (before.extra_vectors or {}).get(measurement)
    return a is not None and b is not None and np.array_equal(a, b)


def _stamp_rules(sample, measurement: str) -> None:
    """Record that ``sample``'s ``measurement`` was made under today's rules."""
    sample.extra_vector_rules = {
        **(sample.extra_vector_rules or {}),
        measurement: matter.RULES_VERSION,
    }


def _measure(text: str, measurement: str, extract: Callable) -> np.ndarray:
    with ff.measuring(measurement):
        return _checked(extract(text))


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
    splitter = part_overrides.is_splitter(measurement)
    ids = list(students) if students else repo.list_ids()
    for student_id in ids:
        state = repo.get(student_id)
        if state is None:
            report.failed.append(f"{student_id} (not found)")
            continue
        report.students += 1
        new: dict[int, np.ndarray] = {}
        chosen: dict[int, tuple[dict, np.ndarray]] = {}
        stamp: dict[int, tuple[bool, bool]] = {}  # (rules', choice's) stamp only
        for i, sample in enumerate(state.samples):
            report.papers += 1
            stored = (sample.extra_vectors or {}).get(measurement)
            # A splitter measurement made under other rules than today's is
            # stale (original/measurement.py stored_vector): measured again.
            has_rules = _measurement.stored_vector(sample, measurement) is not None
            if stored is not None and not has_rules:
                report.stale += 1
            # A paper with a teacher's stored choice of parts gets both: the
            # rules' own measurement (extra_vectors) and the one made with the
            # choice (original/features/part_overrides.py), whatever the
            # switches say now. Which one a score reads is decided then.
            has_choice = part_overrides.of_sample(sample) is not None and splitter
            choice_now = has_choice and (
                part_overrides.choice_vector(sample, measurement) is not None
            )
            needs_choice = has_choice and not choice_now
            # Current but unstamped (stored before stamps existed): only the
            # stamp is written, so a later RULES_VERSION bump can tell.
            unstamped = (
                splitter and has_rules and measurement not in (sample.extra_vector_rules or {}),
                choice_now and measurement not in (sample.part_overrides.get("choice_rules") or {}),
            )
            if any(unstamped):
                stamp[i] = unstamped
            if has_rules and not needs_choice:
                report.already += 1
                report.to_stamp += any(unstamped)
                continue
            if not sample.text:
                report.no_text += 1
                continue
            report.to_measure += 1
            if not (apply or measure_in_dry_run):
                continue
            try:
                if not has_rules:
                    new[i] = _measure(str(sample.text), measurement, extract)
                if needs_choice:
                    vector = part_overrides.measure_stored_choice(sample, measurement, extract)
                    chosen[i] = (sample.part_overrides, _checked(vector))
            except Exception as exc:
                log.warning("%s paper %d: measurement failed: %s", student_id, i, exc)
                report.failed.append(f"{student_id}#{i}")
                new.pop(i, None)
        if not apply or not (new or chosen or stamp):
            continue
        fresh = repo.get(student_id)
        if fresh is None or _fingerprint(fresh) != _fingerprint(state):
            report.changed.append(student_id)
            continue
        for i, vector in new.items():
            sample = fresh.samples[i]
            sample.extra_vectors = {**(sample.extra_vectors or {}), measurement: vector}
            if splitter:
                _stamp_rules(sample, measurement)
        for i, (doc, vector) in chosen.items():
            sample = fresh.samples[i]
            if sample.part_overrides != doc:  # the teacher changed the choice meanwhile
                report.changed.append(f"{student_id}#{i}")
                continue
            sample.part_overrides = part_overrides.with_choice_vectors(doc, {measurement: vector})
        for i, (rules_only, choice_only) in stamp.items():
            # Only a stamp: written only over exactly what was read (another
            # writer's change meanwhile is reported and left alone).
            sample, before = fresh.samples[i], state.samples[i]
            done = moved = False
            if rules_only and i not in new:
                if _same(sample, before, measurement):
                    _stamp_rules(sample, measurement)
                    done = True
                else:
                    moved = True
            if choice_only and i not in chosen:
                if sample.part_overrides == before.part_overrides:
                    sample.part_overrides = part_overrides.with_choice_rules(
                        sample.part_overrides, measurement
                    )
                    done = True
                else:
                    moved = True
            if moved:
                report.changed.append(f"{student_id}#{i}")
            report.stamped += done
        repo.put(fresh)
        report.measured += len(set(new) | set(chosen))
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
