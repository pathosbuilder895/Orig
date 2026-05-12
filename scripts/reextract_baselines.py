#!/usr/bin/env python3
"""
reextract_baselines.py — Re-extract all baseline feature vectors to current 74-dim pipeline.

Run this after updating the feature extraction code to ensure all stored baselines
are compatible with the current model. Safe to run multiple times (idempotent).

Usage:
    python scripts/reextract_baselines.py [--dry-run] [--student STUDENT_ID]

Options:
    --dry-run       Show what would be updated without writing changes
    --student ID    Process only a specific student ID
"""

import argparse
import logging
import sys
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)s %(message)s'
)
log = logging.getLogger(__name__)

from original import store
from original.features.pipeline import feature_vector
from original.constants import FEATURE_DIM


def reextract_student(student_id: str, dry_run: bool = False) -> tuple:
    """
    Re-extract feature vectors for all baseline samples of a student.

    Returns: (n_updated, n_errors)
    """
    state = store.get(student_id)
    if state is None:
        log.warning("Student %s not found in store", student_id)
        return 0, 1

    n_updated = 0
    n_errors = 0

    for i, sample in enumerate(state.samples):
        try:
            # Re-extract feature vector from stored text
            new_vector = feature_vector(sample.text)

            # Verify dimension
            if new_vector.shape[0] != FEATURE_DIM:
                log.error(
                    "Student %s sample %d: extracted vector has dimension %d, "
                    "expected %d. Skipping.",
                    student_id, i, new_vector.shape[0], FEATURE_DIM
                )
                n_errors += 1
                continue

            # Check if vector changed
            old_dim = sample.vector.shape[0]
            if old_dim != FEATURE_DIM:
                log.info(
                    "Student %s sample %d: updating vector from dimension %d to %d",
                    student_id, i, old_dim, FEATURE_DIM
                )
                if not dry_run:
                    sample.vector = new_vector
                n_updated += 1
            else:
                # Same dimension, check if content changed
                import numpy as np
                if not np.allclose(sample.vector, new_vector, rtol=1e-9):
                    log.info(
                        "Student %s sample %d: vector content updated",
                        student_id, i
                    )
                    if not dry_run:
                        sample.vector = new_vector
                    n_updated += 1
                else:
                    log.debug(
                        "Student %s sample %d: vector unchanged",
                        student_id, i
                    )

        except Exception as e:
            log.error(
                "Student %s sample %d: feature extraction failed — %s",
                student_id, i, e
            )
            n_errors += 1
            continue

    # Persist if any updates and not dry-run
    if n_updated > 0 and not dry_run:
        try:
            store.put(state)
            log.info("Student %s: persisted %d updated samples", student_id, n_updated)
        except Exception as e:
            log.error("Student %s: failed to persist — %s", student_id, e)
            n_errors += 1

    return n_updated, n_errors


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dry-run', action='store_true',
                        help='Show what would be updated without writing changes')
    parser.add_argument('--student', default=None,
                        help='Process only a specific student ID')
    args = parser.parse_args()

    log.info("Starting baseline re-extraction (dry_run=%s)", args.dry_run)

    if args.student:
        # Process single student
        log.info("Processing student: %s", args.student)
        n_updated, n_errors = reextract_student(args.student, dry_run=args.dry_run)
        log.info(
            "Done. Samples updated: %d, Errors: %d",
            n_updated, n_errors
        )
        return 0 if n_errors == 0 else 1

    # Process all students
    student_ids = store.list_ids()
    log.info("Found %d students in store", len(student_ids))

    n_students_processed = 0
    n_samples_updated = 0
    n_total_errors = 0

    for student_id in student_ids:
        log.info("Processing student %d/%d: %s",
                 n_students_processed + 1, len(student_ids), student_id)
        n_updated, n_errors = reextract_student(student_id, dry_run=args.dry_run)
        if n_updated > 0 or n_errors > 0:
            n_students_processed += 1
            n_samples_updated += n_updated
            n_total_errors += n_errors

    log.info(
        "Done. Students processed: %d, Samples updated: %d, Errors: %d",
        n_students_processed, n_samples_updated, n_total_errors
    )

    return 0 if n_total_errors == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
