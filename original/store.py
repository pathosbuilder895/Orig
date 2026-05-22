"""
store.py — Student state store with SQLite persistence.

Keeps a hot in-memory cache for sub-millisecond reads while
durably writing each mutation to a local SQLite database so
baseline profiles survive server restarts.

In production this would be backed by Postgres + pgvector.
"""

from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path
from typing import Dict, List, Optional

import logging

import numpy as np

from .quantum.state import BaselineSample, StudentState
from .constants import FEATURE_DIM

log = logging.getLogger(__name__)

# ── Database path ─────────────────────────────────────────────────────────────

_DB_PATH = Path(os.environ.get(
    "ORIGINAL_DB",
    Path(__file__).parent.parent / "profiles.db"
))

# ── In-memory cache ───────────────────────────────────────────────────────────

_STORE: Dict[str, StudentState] = {}
_loaded = False

# ── Bayesian genre-stats cache ────────────────────────────────────────────────
# get_genre_stats() is O(N×S) — iterates every student and every sample.
# Cache the result keyed on genre; bust on every put() so newly-added baseline
# samples are reflected in the next call. The hot path reads from this dict in
# O(1). Dict clear is thread-safe in CPython (GIL-protected), matching the
# lock-free approach used by _STORE itself.
_GENRE_STATS_CACHE: Dict[str, Optional[Dict]] = {}


# ── SQLite helpers ────────────────────────────────────────────────────────────

def _get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(str(_DB_PATH))
    conn.execute("""
        CREATE TABLE IF NOT EXISTS student_profiles (
            student_id TEXT PRIMARY KEY,
            data       TEXT NOT NULL
        )
    """)
    # Phase 5 audit log — every adaptive scoring run with a manifest
    # appends a row here. Lets us inspect which directives fired against
    # which submissions and how that correlated with action/score, so we
    # can tune `_derive_directives` thresholds with real production data.
    conn.execute("""
        CREATE TABLE IF NOT EXISTS submission_manifests (
            submission_id    TEXT PRIMARY KEY,
            student_id       TEXT NOT NULL,
            created_at       TEXT NOT NULL,
            manifest_json    TEXT NOT NULL,
            divergence_score REAL,
            action           TEXT
        )
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_manifest_student_created
            ON submission_manifests(student_id, created_at)
    """)
    # PR 7: corrections feedback log — instructors flag whether a verdict
    # was right or wrong and (optionally) supply the corrected label. Used
    # by the retraining job (PR 8) to tune verdict thresholds. Foreign-keys
    # logically to submission_manifests, but SQLite FK enforcement is off
    # by default — we keep the relationship in the indexed lookup.
    conn.execute("""
        CREATE TABLE IF NOT EXISTS corrections (
            id                       INTEGER PRIMARY KEY AUTOINCREMENT,
            submission_id            TEXT NOT NULL,
            student_id               TEXT,
            original_verdict         TEXT,
            original_action          TEXT,
            original_divergence_score REAL,
            corrected_verdict        TEXT,
            corrected_action         TEXT,
            is_correct               INTEGER NOT NULL,
            reviewer                 TEXT,
            notes                    TEXT,
            created_at               TEXT NOT NULL
        )
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_corrections_submission
            ON corrections(submission_id)
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_corrections_created
            ON corrections(created_at)
    """)
    # PR 8a: calibration runs — every "Run Calibration" click from the lab
    # dashboard appends a row here. report_json carries the full
    # CalibrationReport (ROC points, threshold metrics, per-author stats)
    # so historical comparisons don't need to re-execute calibrations.
    conn.execute("""
        CREATE TABLE IF NOT EXISTS calibration_runs (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            run_label        TEXT,
            dataset_label    TEXT NOT NULL,
            started_at       TEXT NOT NULL,
            completed_at     TEXT,
            status           TEXT NOT NULL,
            auc              REAL,
            n_essays_scored  INTEGER,
            n_authors        INTEGER,
            config_json      TEXT,
            report_json      TEXT,
            error            TEXT
        )
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_calibration_started
            ON calibration_runs(started_at)
    """)
    # PR 8b: tuned thresholds — every "Apply Suggestions" click writes a
    # new row. The latest row by `created_at` is the active threshold set;
    # in-process scoring reads it on demand. Source can be a calibration
    # run, the corrections feedback loop, or manual override.
    conn.execute("""
        CREATE TABLE IF NOT EXISTS tuned_thresholds_v2 (
            id                 INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at         TEXT NOT NULL,
            source             TEXT NOT NULL,
            source_run_id      INTEGER,
            no_action          REAL NOT NULL,
            monitor            REAL NOT NULL,
            escalate           REAL NOT NULL,
            verdict_authentic_below      REAL,
            verdict_anomalous_at_or_above REAL,
            notes              TEXT,
            provenance_json    TEXT
        )
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_tuned_thresholds_created
            ON tuned_thresholds_v2(created_at)
    """)
    # Production Phase 6: quantum fidelity scores for conformal calibration.
    # Populated by put_fidelity_score() after each scoring call.  Read by
    # get_authentic_fidelities() at scoring time to build the conformal
    # calibration set.  Grows automatically as instructors confirm verdicts
    # via the corrections feedback loop.
    conn.execute("""
        CREATE TABLE IF NOT EXISTS fidelity_scores (
            submission_id    TEXT PRIMARY KEY,
            student_id       TEXT NOT NULL,
            fidelity         REAL NOT NULL,
            is_authentic     INTEGER NOT NULL,
            created_at       TEXT NOT NULL
        )
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_fidelity_student
            ON fidelity_scores(student_id, is_authentic)
    """)
    conn.commit()
    return conn


def _serialize(state: StudentState) -> str:
    """Convert StudentState to a JSON string for SQLite storage."""
    samples = [
        {
            "text":         s.text,
            "vector":       s.vector.tolist(),
            "provenance":   s.provenance,
            "auth_weight":  s.auth_weight,
            "assignment":   s.assignment,
            "submitted_at": s.submitted_at,
            # Phase 4 context metadata — null-safe for legacy samples that
            # haven't been backfilled yet (caller persists after lazy
            # ensure_sample_context_metadata()).
            "genre":            s.genre,
            "topic_centroid":   (s.topic_centroid.tolist()
                                  if s.topic_centroid is not None else None),
            "context_manifest": s.context_manifest,
        }
        for s in state.samples
    ]
    return json.dumps({
        "student_id":     state.student_id,
        "samples":        samples,
        "baseline_kappa": state.baseline_kappa,
        "kappa_log":      state.kappa_log,
        # Phase 8 — drift counter survives restarts so a student who got
        # one outlier today + one outlier next week still triggers
        # rebaseline. Defaults to 0 on legacy rows that predate the field.
        "consecutive_drift_count": state._consecutive_drift_count,
    })


def _deserialize(data: str) -> StudentState:
    """Reconstruct a StudentState from a JSON string."""
    d = json.loads(data)
    state = StudentState(
        student_id=d["student_id"],
        baseline_kappa=d.get("baseline_kappa"),
        kappa_log=d.get("kappa_log", []),
    )
    # Phase 8 — restore drift counter; default 0 for legacy rows.
    state._consecutive_drift_count = int(d.get("consecutive_drift_count", 0))
    for s in d.get("samples", []):
        v = np.array(s["vector"], dtype=np.float64)
        if v.shape[0] != FEATURE_DIM:
            # Stored vector has wrong dimension — e.g. 62 (pre-Tier 8–12 expansion),
            # 74 (pre-Tier 13–15 prosodic expansion), or 90 (pre-Tier 16 citation
            # fingerprint).  Pad with 0.5 (neutral mid-range) for missing
            # dimensions so the density matrix construction doesn't crash.
            # Run `python -m original.cli rebuild-baselines` to re-extract accurately.
            log.warning(
                "Baseline vector for student %s has dimension %d; expected %d. "
                "Padding missing dimensions with 0.5. "
                "Run 'rebuild-baselines' to restore full accuracy.",
                d["student_id"], v.shape[0], FEATURE_DIM,
            )
            padded = np.full(FEATURE_DIM, 0.5, dtype=np.float64)
            n = min(v.shape[0], FEATURE_DIM)
            padded[:n] = v[:n]
            v = padded
        # Phase 4 context metadata — None for legacy rows; numpy roundtrip
        # for the centroid.
        topic_centroid_raw = s.get("topic_centroid")
        topic_centroid = (
            np.array(topic_centroid_raw, dtype=np.float64)
            if topic_centroid_raw is not None else None
        )
        state.samples.append(
            BaselineSample(
                text=s["text"],
                vector=v,
                provenance=s["provenance"],
                auth_weight=s["auth_weight"],
                assignment=s.get("assignment", ""),
                submitted_at=s.get("submitted_at", ""),
                genre=s.get("genre"),
                topic_centroid=topic_centroid,
                context_manifest=s.get("context_manifest"),
            )
        )
    return state


def _load_all() -> None:
    """Load all profiles from SQLite into the in-memory cache (once)."""
    global _loaded
    if _loaded:
        return
    try:
        with _get_conn() as conn:
            for row in conn.execute("SELECT student_id, data FROM student_profiles"):
                state = _deserialize(row[1])
                _STORE[state.student_id] = state
    except Exception:
        pass  # Fresh DB or filesystem error — start empty
    _loaded = True


def _persist(state: StudentState) -> None:
    """Write one student's state to SQLite (upsert)."""
    try:
        with _get_conn() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO student_profiles (student_id, data) VALUES (?, ?)",
                (state.student_id, _serialize(state)),
            )
    except Exception:
        pass  # Non-fatal — data is still live in memory


# ── Public API ────────────────────────────────────────────────────────────────

def get(student_id: str) -> Optional[StudentState]:
    _load_all()
    return _STORE.get(student_id)


def get_or_create(student_id: str) -> StudentState:
    _load_all()
    if student_id not in _STORE:
        _STORE[student_id] = StudentState(student_id=student_id)
    return _STORE[student_id]


def put(state: StudentState) -> None:
    """Update the cache and persist to SQLite."""
    _load_all()
    _STORE[state.student_id] = state
    _persist(state)
    # Bust the Bayesian genre-stats cache — a new sample may shift the
    # cross-student genre distribution that get_genre_stats() aggregates.
    _GENRE_STATS_CACHE.clear()


def list_ids() -> List[str]:
    _load_all()
    return list(_STORE.keys())


def count() -> int:
    _load_all()
    return len(_STORE)


def clear() -> None:
    """Clear in-memory cache only (does not wipe SQLite)."""
    _STORE.clear()


# ── Phase 5: manifest audit log ──────────────────────────────────────────────

def put_manifest(
    submission_id: str,
    student_id: str,
    manifest: "object",                  # ContextManifest or its to_dict()
    divergence_score: Optional[float] = None,
    action: Optional[str] = None,
) -> None:
    """
    Append (or replace) a row in the `submission_manifests` audit table.

    Errors are swallowed — the audit log is best-effort and must never
    break the scoring path. The manifest is stored as a JSON string so
    we can `select manifest_json` later without code changes.
    """
    try:
        if hasattr(manifest, "to_json"):
            manifest_json = manifest.to_json()
            created_at = getattr(manifest, "created_at", "") or ""
        elif isinstance(manifest, dict):
            manifest_json = json.dumps(manifest, sort_keys=True)
            created_at = manifest.get("created_at", "") or ""
        else:
            log.warning("put_manifest: unsupported manifest type %r", type(manifest))
            return

        with _get_conn() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO submission_manifests
                    (submission_id, student_id, created_at, manifest_json,
                     divergence_score, action)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (submission_id, student_id, created_at, manifest_json,
                 divergence_score, action),
            )
    except Exception as e:
        log.warning("put_manifest failed for %s: %s", submission_id, e)


def get_manifest(submission_id: str) -> Optional[Dict]:
    """Return the manifest_json + sidecar fields for a submission, or None."""
    try:
        with _get_conn() as conn:
            row = conn.execute(
                "SELECT student_id, created_at, manifest_json, divergence_score, action "
                "FROM submission_manifests WHERE submission_id = ?",
                (submission_id,),
            ).fetchone()
    except Exception:
        return None
    if not row:
        return None
    return {
        "submission_id":    submission_id,
        "student_id":       row[0],
        "created_at":       row[1],
        "manifest":         json.loads(row[2]),
        "divergence_score": row[3],
        "action":           row[4],
    }


# ── PR 7: manifest list / stats queries ──────────────────────────────────────

def list_manifests(
    student_id: Optional[str] = None,
    action: Optional[str] = None,
    flag: Optional[str] = None,
    since: Optional[str] = None,
    until: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
) -> Dict:
    """
    Paginated query over the submission_manifests audit table.

    All filters are optional. ``flag`` searches inside the JSON-serialised
    manifest's ``flags`` array — uses LIKE rather than json_extract so we
    don't depend on the SQLite JSON1 extension (not always compiled in on
    macOS Python builds).

    Returns
    -------
    {
        "total":   int,         # rows matching the filter (NOT the page)
        "limit":   int,
        "offset":  int,
        "items":   [
            {
                "submission_id":    str,
                "student_id":       str,
                "created_at":       str,
                "divergence_score": float | None,
                "action":           str | None,
                "flags":            List[str],
                "anchor_tiers":     List[int],
                "length_regime":    str,
            },
            ...
        ],
    }
    """
    where_clauses: List[str] = []
    params: List = []

    if student_id is not None:
        where_clauses.append("student_id = ?")
        params.append(student_id)
    if action is not None:
        where_clauses.append("action = ?")
        params.append(action)
    if since is not None:
        where_clauses.append("created_at >= ?")
        params.append(since)
    if until is not None:
        where_clauses.append("created_at <= ?")
        params.append(until)
    if flag is not None:
        # LIKE against the JSON column. Conservative: matches "flag" anywhere
        # in the JSON string. Good enough for the dashboard's filter UX —
        # collisions are unlikely (flags are short canonical strings).
        where_clauses.append("manifest_json LIKE ?")
        params.append(f'%"{flag}"%')

    where = (" WHERE " + " AND ".join(where_clauses)) if where_clauses else ""

    try:
        with _get_conn() as conn:
            total = conn.execute(
                f"SELECT COUNT(*) FROM submission_manifests{where}", params,
            ).fetchone()[0]
            rows = conn.execute(
                f"""
                SELECT submission_id, student_id, created_at, manifest_json,
                       divergence_score, action
                FROM submission_manifests
                {where}
                ORDER BY created_at DESC
                LIMIT ? OFFSET ?
                """,
                params + [limit, offset],
            ).fetchall()
    except Exception as e:
        log.warning("list_manifests failed: %s", e)
        return {"total": 0, "limit": limit, "offset": offset, "items": []}

    items: List[Dict] = []
    for row in rows:
        try:
            manifest = json.loads(row[3])
        except Exception:
            manifest = {}
        items.append({
            "submission_id":    row[0],
            "student_id":       row[1],
            "created_at":       row[2],
            "divergence_score": row[4],
            "action":           row[5],
            # Stripped-down summary so the list endpoint is cheap to render.
            "flags":            list(manifest.get("flags") or []),
            "anchor_tiers":     list(manifest.get("anchor_tiers") or []),
            "length_regime":    manifest.get("length_regime") or "unknown",
        })

    return {
        "total":  int(total),
        "limit":  limit,
        "offset": offset,
        "items":  items,
    }


def manifest_stats(
    since: Optional[str] = None,
    until: Optional[str] = None,
) -> Dict:
    """
    Roll-up counts over the manifest audit table for the dashboard
    summary cards. Uses one pass through the result set rather than N
    separate aggregation queries — manifests are small JSON blobs and
    we expect O(thousands) of rows in normal use.
    """
    where_clauses: List[str] = []
    params: List = []
    if since is not None:
        where_clauses.append("created_at >= ?")
        params.append(since)
    if until is not None:
        where_clauses.append("created_at <= ?")
        params.append(until)
    where = (" WHERE " + " AND ".join(where_clauses)) if where_clauses else ""

    by_action: Dict[str, int] = {}
    by_flag: Dict[str, int] = {}
    by_length_regime: Dict[str, int] = {}
    divergence_sum = 0.0
    divergence_n   = 0
    total = 0

    try:
        with _get_conn() as conn:
            for row in conn.execute(
                f"SELECT action, manifest_json, divergence_score "
                f"FROM submission_manifests{where}",
                params,
            ):
                total += 1
                action = row[0] or "unknown"
                by_action[action] = by_action.get(action, 0) + 1
                try:
                    m = json.loads(row[1])
                except Exception:
                    m = {}
                for f in (m.get("flags") or []):
                    by_flag[f] = by_flag.get(f, 0) + 1
                regime = m.get("length_regime") or "unknown"
                by_length_regime[regime] = by_length_regime.get(regime, 0) + 1
                if row[2] is not None:
                    divergence_sum += float(row[2])
                    divergence_n += 1
    except Exception as e:
        log.warning("manifest_stats failed: %s", e)

    return {
        "total":               total,
        "by_action":           by_action,
        "by_flag":             by_flag,
        "by_length_regime":    by_length_regime,
        "mean_divergence":     round(divergence_sum / divergence_n, 4) if divergence_n else None,
        "since":               since,
        "until":               until,
    }


# ── Production Phase 6: quantum fidelity store ───────────────────────────────

def put_fidelity_score(
    submission_id: str,
    student_id: str,
    fidelity: float,
    is_authentic: bool,
) -> None:
    """
    Store a quantum fidelity score for conformal calibration.

    Called by the API layer after scoring when AMPLITUDE_SCORING_ENABLED=1.
    The calibration set grows as instructors confirm verdicts — higher-quality
    data over time → tighter conformal p-values.

    Parameters
    ----------
    submission_id : unique submission identifier
    student_id    : student identifier
    fidelity      : quantum_fidelity score ∈ [0, 1]
    is_authentic  : True if the submission was confirmed authentic
    """
    import datetime
    created_at = datetime.datetime.utcnow().isoformat()
    try:
        with _get_conn() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO fidelity_scores
                    (submission_id, student_id, fidelity, is_authentic, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (submission_id, student_id, float(fidelity),
                 1 if is_authentic else 0, created_at),
            )
            conn.commit()
    except Exception:
        log.exception("put_fidelity_score failed for %s", submission_id)


def get_authentic_fidelities(
    student_id: str,
    limit: int = 200,
) -> List[float]:
    """
    Return the most recent ``limit`` confirmed-authentic fidelity scores
    for a student, for use as the conformal calibration set.

    Sources (merged):
    1. ``fidelity_scores`` table — populated by ``put_fidelity_score()`` when
       a submission is logged as authentic after scoring.
    2. Implicit: the corrections table is NOT queried here for simplicity;
       the API layer should call ``put_fidelity_score(..., is_authentic=True)``
       when an instructor correction confirms authenticity.

    Returns an empty list when the calibration set is empty — callers treat
    this as "no conformal data" and fall back to deviation_score only.
    """
    try:
        with _get_conn() as conn:
            rows = conn.execute(
                """
                SELECT fidelity FROM fidelity_scores
                WHERE student_id = ? AND is_authentic = 1
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (student_id, limit),
            ).fetchall()
            return [float(row[0]) for row in rows]
    except Exception:
        log.exception("get_authentic_fidelities failed for %s", student_id)
        return []


# ── Hierarchical Bayesian prior: cross-student genre statistics ───────────────

def get_genre_stats(genre: str) -> Optional[Dict]:
    """
    Compute cross-student mean, std, and sample count for a given writing genre.

    Aggregates feature vectors from all confirmed-authentic baseline samples
    (auth_weight > 0) with matching ``sample.genre`` across every student in
    the in-memory store.  Returns ``None`` when fewer than 5 samples are
    found — the caller treats this as "no prior available" and falls back to
    the student-only baseline.

    This is the population-level reference distribution used by the
    Hierarchical Bayesian cold-start prior in ``scoring.score()``.  It is
    intentionally in-memory only (no DB query) because:
    - The store is always fully loaded before scoring calls arrive.
    - Cross-student density-matrix queries on SQLite are expensive for large N.
    - Genre labels are optional metadata; many legacy samples have genre=None.

    Parameters
    ----------
    genre : genre label (e.g. "argumentative_essay", "lab_report")

    Returns
    -------
    dict with keys "mean" (np.ndarray), "std" (np.ndarray), "n_samples" (int)
    or None if fewer than 5 matching authentic samples are found.
    """
    _load_all()

    # O(1) fast path — return cached result if available.
    # Cache is busted by put() whenever a new baseline sample is stored.
    if genre in _GENRE_STATS_CACHE:
        return _GENRE_STATS_CACHE[genre]

    vectors: List[np.ndarray] = []
    # list() snapshots _STORE.values() to avoid RuntimeError if a concurrent
    # put() call mutates the dict while we iterate (FastAPI uses a thread pool
    # for sync handlers; _STORE is not protected by an explicit lock).
    for student_state in list(_STORE.values()):
        for sample in student_state.samples:
            if (
                sample.auth_weight > 0
                and getattr(sample, "genre", None) == genre
            ):
                vectors.append(sample.vector)

    if len(vectors) < 5:
        _GENRE_STATS_CACHE[genre] = None
        return None

    mat = np.stack(vectors, axis=0)          # shape (N, FEATURE_DIM)
    mean_vec = mat.mean(axis=0)              # shape (FEATURE_DIM,)
    # Use the same 0.005 floor as StudentState.baseline_std to keep the
    # prior std compatible with the per-student sigma floor.
    std_vec = np.maximum(mat.std(axis=0), 0.005)
    result = {
        "mean":      mean_vec,
        "std":       std_vec,
        "n_samples": len(vectors),
    }
    _GENRE_STATS_CACHE[genre] = result
    return result


def update_fidelity_authenticity(submission_id: str, is_authentic: bool) -> None:
    """
    Update the ``is_authentic`` flag on an existing fidelity_scores row.

    Called by the corrections endpoint when an instructor's verdict
    overrides the automated authenticity label written at scoring time.
    This is what actually closes the conformal calibration feedback loop:
    real instructor signals → correct is_authentic labels → conformal set
    quality improves over time → tighter p-values.

    Silently no-ops when no fidelity row exists for this submission
    (i.e. AMPLITUDE_SCORING_ENABLED was off when it was scored).
    """
    try:
        with _get_conn() as conn:
            conn.execute(
                "UPDATE fidelity_scores SET is_authentic = ? WHERE submission_id = ?",
                (1 if is_authentic else 0, submission_id),
            )
            conn.commit()
    except Exception:
        log.exception(
            "update_fidelity_authenticity failed for submission %s", submission_id
        )


def delete_student(student_id: str) -> bool:
    """
    Permanently delete all data for a student (FERPA right-to-erasure).

    Removes the student from:
    - The in-memory store (_STORE)
    - student_profiles      (SQLite — baseline profile)
    - fidelity_scores       (SQLite — conformal calibration data)
    - submission_manifests  (SQLite — adaptive-context audit log)
    - corrections           (SQLite — instructor feedback)

    ``corrections`` rows carry a ``student_id`` column auto-filled from the
    manifest. We delete by that column so orphaned corrections (where
    student_id was never set) are not accidentally removed.

    Returns True if the student existed and was deleted, False if not found.
    """
    _load_all()
    if student_id not in _STORE:
        return False

    # Purge in-memory first so no further reads see stale data
    del _STORE[student_id]
    _GENRE_STATS_CACHE.clear()   # genre stats may have included this student

    try:
        with _get_conn() as conn:
            conn.execute(
                "DELETE FROM student_profiles WHERE student_id = ?", (student_id,)
            )
            conn.execute(
                "DELETE FROM fidelity_scores WHERE student_id = ?", (student_id,)
            )
            conn.execute(
                "DELETE FROM submission_manifests WHERE student_id = ?", (student_id,)
            )
            conn.execute(
                "DELETE FROM corrections WHERE student_id = ?", (student_id,)
            )
            conn.commit()
    except Exception:
        log.exception("delete_student failed for %s — SQLite rows may remain", student_id)

    return True


# ── PR 7: corrections feedback log ───────────────────────────────────────────

def put_correction(
    submission_id: str,
    is_correct: bool,
    *,
    student_id: Optional[str] = None,
    original_verdict: Optional[str] = None,
    original_action: Optional[str] = None,
    original_divergence_score: Optional[float] = None,
    corrected_verdict: Optional[str] = None,
    corrected_action: Optional[str] = None,
    reviewer: Optional[str] = None,
    notes: Optional[str] = None,
    created_at: Optional[str] = None,
) -> Optional[int]:
    """
    Append a correction row. ``is_correct`` is the simplest signal — even
    without a corrected_verdict, "this was wrong" is useful labelled data
    for retraining (PR 8).

    Returns the inserted row id, or None on failure.

    Auto-fills ``original_*`` fields from the manifest audit log when the
    caller doesn't supply them — saves the dashboard from a separate
    lookup round-trip.
    """
    from datetime import datetime, timezone
    if created_at is None:
        created_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    # Auto-fill from manifest if available and not provided.
    if (original_verdict is None or original_action is None
            or original_divergence_score is None or student_id is None):
        existing = get_manifest(submission_id)
        if existing is not None:
            student_id = student_id or existing.get("student_id")
            original_action = original_action or existing.get("action")
            if original_divergence_score is None:
                original_divergence_score = existing.get("divergence_score")
            # Verdict is not in the audit table (it's in the report), so
            # we leave it None unless explicitly provided. The retraining
            # job can re-derive verdict from divergence_score + the same
            # threshold table that was active at scoring time.

    try:
        with _get_conn() as conn:
            cur = conn.execute(
                """
                INSERT INTO corrections (
                    submission_id, student_id,
                    original_verdict, original_action, original_divergence_score,
                    corrected_verdict, corrected_action,
                    is_correct, reviewer, notes, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (submission_id, student_id,
                 original_verdict, original_action, original_divergence_score,
                 corrected_verdict, corrected_action,
                 1 if is_correct else 0, reviewer, notes, created_at),
            )
            return int(cur.lastrowid)
    except Exception as e:
        log.warning("put_correction failed for %s: %s", submission_id, e)
        return None


def list_corrections(
    submission_id: Optional[str] = None,
    student_id: Optional[str] = None,
    is_correct: Optional[bool] = None,
    limit: int = 100,
    offset: int = 0,
) -> Dict:
    """List corrections with optional filters."""
    where_clauses: List[str] = []
    params: List = []
    if submission_id is not None:
        where_clauses.append("submission_id = ?")
        params.append(submission_id)
    if student_id is not None:
        where_clauses.append("student_id = ?")
        params.append(student_id)
    if is_correct is not None:
        where_clauses.append("is_correct = ?")
        params.append(1 if is_correct else 0)
    where = (" WHERE " + " AND ".join(where_clauses)) if where_clauses else ""

    try:
        with _get_conn() as conn:
            total = conn.execute(
                f"SELECT COUNT(*) FROM corrections{where}", params,
            ).fetchone()[0]
            rows = conn.execute(
                f"""
                SELECT id, submission_id, student_id,
                       original_verdict, original_action, original_divergence_score,
                       corrected_verdict, corrected_action,
                       is_correct, reviewer, notes, created_at
                FROM corrections
                {where}
                ORDER BY created_at DESC
                LIMIT ? OFFSET ?
                """,
                params + [limit, offset],
            ).fetchall()
    except Exception as e:
        log.warning("list_corrections failed: %s", e)
        return {"total": 0, "limit": limit, "offset": offset, "items": []}

    items: List[Dict] = []
    for r in rows:
        items.append({
            "id":                        r[0],
            "submission_id":             r[1],
            "student_id":                r[2],
            "original_verdict":          r[3],
            "original_action":           r[4],
            "original_divergence_score": r[5],
            "corrected_verdict":         r[6],
            "corrected_action":          r[7],
            "is_correct":                bool(r[8]),
            "reviewer":                  r[9],
            "notes":                     r[10],
            "created_at":                r[11],
        })

    return {
        "total":  int(total),
        "limit":  limit,
        "offset": offset,
        "items":  items,
    }


# ── PR 8a: calibration runs ──────────────────────────────────────────────────

def start_calibration_run(
    dataset_label: str,
    run_label: Optional[str] = None,
    config: Optional[Dict] = None,
) -> Optional[int]:
    """
    Insert a `running` row and return its row id. The lab UI polls
    ``get_calibration_run`` until status flips to `completed` or `failed`.
    """
    from datetime import datetime, timezone
    started_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    try:
        with _get_conn() as conn:
            cur = conn.execute(
                """
                INSERT INTO calibration_runs (
                    run_label, dataset_label, started_at, status, config_json
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (run_label, dataset_label, started_at, "running",
                 json.dumps(config or {})),
            )
            return int(cur.lastrowid)
    except Exception as e:
        log.warning("start_calibration_run failed: %s", e)
        return None


def complete_calibration_run(
    run_id: int,
    *,
    auc: float,
    n_essays_scored: int,
    n_authors: int,
    report: Dict,
) -> bool:
    """Mark a run completed and store the full report."""
    from datetime import datetime, timezone
    completed_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    try:
        with _get_conn() as conn:
            conn.execute(
                """
                UPDATE calibration_runs
                SET status='completed', completed_at=?, auc=?,
                    n_essays_scored=?, n_authors=?, report_json=?
                WHERE id=?
                """,
                (completed_at, float(auc), int(n_essays_scored),
                 int(n_authors), json.dumps(report), run_id),
            )
            return True
    except Exception as e:
        log.warning("complete_calibration_run %d failed: %s", run_id, e)
        return False


def fail_calibration_run(run_id: int, error: str) -> bool:
    """Mark a run failed and capture the exception message."""
    from datetime import datetime, timezone
    completed_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    try:
        with _get_conn() as conn:
            conn.execute(
                """
                UPDATE calibration_runs
                SET status='failed', completed_at=?, error=?
                WHERE id=?
                """,
                (completed_at, str(error)[:2000], run_id),
            )
            return True
    except Exception as e:
        log.warning("fail_calibration_run %d failed: %s", run_id, e)
        return False


def list_calibration_runs(
    status: Optional[str] = None,
    dataset_label: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
) -> Dict:
    """List calibration runs (newest first), with optional filters."""
    where_clauses: List[str] = []
    params: List = []
    if status is not None:
        where_clauses.append("status = ?")
        params.append(status)
    if dataset_label is not None:
        where_clauses.append("dataset_label = ?")
        params.append(dataset_label)
    where = (" WHERE " + " AND ".join(where_clauses)) if where_clauses else ""

    try:
        with _get_conn() as conn:
            total = conn.execute(
                f"SELECT COUNT(*) FROM calibration_runs{where}", params,
            ).fetchone()[0]
            rows = conn.execute(
                f"""
                SELECT id, run_label, dataset_label, started_at, completed_at,
                       status, auc, n_essays_scored, n_authors, error
                FROM calibration_runs
                {where}
                ORDER BY started_at DESC
                LIMIT ? OFFSET ?
                """,
                params + [limit, offset],
            ).fetchall()
    except Exception as e:
        log.warning("list_calibration_runs failed: %s", e)
        return {"total": 0, "limit": limit, "offset": offset, "items": []}

    items: List[Dict] = []
    for r in rows:
        items.append({
            "id":               r[0],
            "run_label":        r[1],
            "dataset_label":    r[2],
            "started_at":       r[3],
            "completed_at":     r[4],
            "status":           r[5],
            "auc":              r[6],
            "n_essays_scored":  r[7],
            "n_authors":        r[8],
            "error":            r[9],
        })
    return {
        "total":  int(total),
        "limit":  limit,
        "offset": offset,
        "items":  items,
    }


def get_calibration_run(run_id: int, include_report: bool = True) -> Optional[Dict]:
    """Fetch one run; ``include_report=False`` skips the heavy JSON column."""
    cols = ("id, run_label, dataset_label, started_at, completed_at, status, "
            "auc, n_essays_scored, n_authors, config_json, error")
    if include_report:
        cols += ", report_json"
    try:
        with _get_conn() as conn:
            row = conn.execute(
                f"SELECT {cols} FROM calibration_runs WHERE id=?",
                (run_id,),
            ).fetchone()
    except Exception:
        return None
    if not row:
        return None
    out = {
        "id":               row[0],
        "run_label":        row[1],
        "dataset_label":    row[2],
        "started_at":       row[3],
        "completed_at":     row[4],
        "status":           row[5],
        "auc":              row[6],
        "n_essays_scored":  row[7],
        "n_authors":        row[8],
        "config":           json.loads(row[9] or "{}"),
        "error":            row[10],
    }
    if include_report:
        try:
            out["report"] = json.loads(row[11] or "{}")
        except Exception:
            out["report"] = {}
    return out


# ── PR 8b: tuned thresholds (versioned) ──────────────────────────────────────

def put_tuned_thresholds(
    *,
    no_action: float,
    monitor: float,
    escalate: float,
    source: str,
    source_run_id: Optional[int] = None,
    verdict_authentic_below: Optional[float] = None,
    verdict_anomalous_at_or_above: Optional[float] = None,
    notes: Optional[str] = None,
    provenance: Optional[Dict] = None,
) -> Optional[int]:
    """
    Append a new active-thresholds row. The latest row (by ``created_at``)
    is the active set; older rows are preserved for audit. ``source`` is
    one of {"manual", "calibration_run", "correction_retrain"}.
    """
    from datetime import datetime, timezone
    created_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    try:
        with _get_conn() as conn:
            cur = conn.execute(
                """
                INSERT INTO tuned_thresholds_v2 (
                    created_at, source, source_run_id,
                    no_action, monitor, escalate,
                    verdict_authentic_below, verdict_anomalous_at_or_above,
                    notes, provenance_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (created_at, source, source_run_id,
                 float(no_action), float(monitor), float(escalate),
                 verdict_authentic_below, verdict_anomalous_at_or_above,
                 notes, json.dumps(provenance or {})),
            )
            return int(cur.lastrowid)
    except Exception as e:
        log.warning("put_tuned_thresholds failed: %s", e)
        return None


def get_active_tuned_thresholds() -> Optional[Dict]:
    """Most-recent row in ``tuned_thresholds_v2`` (the in-effect active set)."""
    try:
        with _get_conn() as conn:
            row = conn.execute(
                """
                SELECT id, created_at, source, source_run_id,
                       no_action, monitor, escalate,
                       verdict_authentic_below, verdict_anomalous_at_or_above,
                       notes, provenance_json
                FROM tuned_thresholds_v2
                ORDER BY created_at DESC
                LIMIT 1
                """,
            ).fetchone()
    except Exception:
        return None
    if not row:
        return None
    return {
        "id":                            row[0],
        "created_at":                    row[1],
        "source":                        row[2],
        "source_run_id":                 row[3],
        "no_action":                     row[4],
        "monitor":                       row[5],
        "escalate":                      row[6],
        "verdict_authentic_below":       row[7],
        "verdict_anomalous_at_or_above": row[8],
        "notes":                         row[9],
        "provenance":                    json.loads(row[10] or "{}"),
    }


def list_tuned_thresholds(limit: int = 50, offset: int = 0) -> Dict:
    """Audit list of historical threshold sets."""
    try:
        with _get_conn() as conn:
            total = conn.execute(
                "SELECT COUNT(*) FROM tuned_thresholds_v2",
            ).fetchone()[0]
            rows = conn.execute(
                """
                SELECT id, created_at, source, source_run_id,
                       no_action, monitor, escalate,
                       verdict_authentic_below, verdict_anomalous_at_or_above,
                       notes
                FROM tuned_thresholds_v2
                ORDER BY created_at DESC
                LIMIT ? OFFSET ?
                """,
                (limit, offset),
            ).fetchall()
    except Exception:
        return {"total": 0, "limit": limit, "offset": offset, "items": []}
    return {
        "total":  int(total),
        "limit":  limit,
        "offset": offset,
        "items":  [
            {
                "id":                            r[0],
                "created_at":                    r[1],
                "source":                        r[2],
                "source_run_id":                 r[3],
                "no_action":                     r[4],
                "monitor":                       r[5],
                "escalate":                      r[6],
                "verdict_authentic_below":       r[7],
                "verdict_anomalous_at_or_above": r[8],
                "notes":                         r[9],
            }
            for r in rows
        ],
    }
