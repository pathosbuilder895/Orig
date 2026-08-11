"""
features/tier17.py — Tier 17: Behavioral Biometrics

Six features derived from live keystroke capture data recorded during exam writing
(supplied by Bbook's secure exam environment).  These features fingerprint HOW a
student types, not what they wrote — making them the most tamper-resistant signal
in the system.

A ghostwriter who delivers finished text cannot replicate the process fingerprint:
  - Typing rhythm and burst patterns are deeply habitual
  - Deletion/revision behaviour reflects individual cognitive editing style
  - Paste events are detectable even when the exam UI blocks them partially

Features
--------
typing_speed_cv      ROBUST coefficient of variation of inter-keystroke intervals:
                     (Q75 - Q25) / (1.349 * median).  Consistent typists → low,
                     hesitant/variable → high.  Deliberately not stdev/mean: the
                     IKI distribution is strongly right-skewed, so a plain CV is
                     dominated by whichever planning pauses happen to fall inside
                     the 30 s cadence window rather than by typing rhythm.  Also
                     deliberately not MAD/median — see typing_speed_cv() for why
                     that one fails on bimodal burst-and-hesitate typing.

burst_ratio          Fraction of keystrokes produced inside pause-delimited
                     production bursts ("P-bursts") of >= 10 keystrokes, where a
                     burst is broken by any pause >= 2 s.  Fluent writers produce
                     long uninterrupted runs; halting writers do not.  Deliberately
                     not "fraction of IKIs under 150 ms": against a 238.7 ms
                     population mean (fast typists 121.7 ms, slow 481.0 ms) that
                     is a gross-speed proxy, saturating at 1.0 for fast typists
                     and 0.0 for slow ones regardless of phrasing.

deletion_rate        Backspace / Delete events as a fraction of all keystrokes.
                     Stable across sessions for a given writer; spikes when
                     copy-editing pasted content.

pause_density        Planning pauses (2 s <= p < 20 s) per 100 words of output.
                     2 s is the keystroke-logging convention; intervals >= 20 s
                     are look-ups or interruptions, not planning, and are counted
                     nowhere.  Measures thinking rhythm; stable per writer, differs
                     markedly between authentic writing and transcript-entry.

paste_event_rate     Paste events per 100 words.
                     Should be ~0 in locked-down exams; even 1–2 events are a flag.
                     Normalised per 100 words to be length-independent.

revision_depth       Mean characters affected per revision (delete/backspace) event.
                     Low = single-char corrections (normal typing).
                     High = large deletions consistent with wholesale rewriting of
                     pasted or AI-generated blocks.

All outputs are in [0, 1] after normalisation via NORM_BOUNDS in constants.py.

If keystroke data is absent (uploaded papers, Canvas imports) this entire tier is
EXCLUDED from density matrix construction — features are not padded with 0.5 so
they do not dilute the baseline.  The scoring engine handles this via the optional
keystroke feature mask.

Per-feature insufficiency (a blob that exists but carries no usable pauses, no
revision records, or too few keystrokes to estimate cadence) is a different case:
those return the feature's NORM_BOUNDS *midpoint*, which `pipeline._normalise`
maps to exactly 0.5 — the same value the disabled-group path writes.  Returning a
bare 0.5 here would be wrong: against bounds (0.0, 1.5) it normalises to 0.33, a
confident low reading rather than "no measurement".

Population anchors used to calibrate the bounds and thresholds below come from
Dhakal et al. (2018), 136.9M keystrokes / 168,960 participants, English sentence
transcription: IKI mean 238.7 ms (SD 111.6), observed physical floor ~60 ms;
backspace/delete 6.31% of keypresses (SD 4.48).  That sample skews young and
typing-interested, and transcription is not composition, so these are guardrails
for rejecting instrument artifacts — NOT denominators.  Per-writer normalisation
against the student's own baseline remains the scoring path.
"""

from __future__ import annotations

import statistics

from ..constants import NORM_BOUNDS

# ── Calibration constants (see module docstring for provenance) ───────────────

MIN_CADENCE_KEYSTROKES = 10  # below this, cadence is unestimable
MIN_PLAUSIBLE_MEDIAN_IKI_MS = 60.0  # observed physical floor; below = clock artifact
MAX_CADENCE_IKI_MS = 30_000.0  # gaps beyond this are focus-loss, not motor cadence
PAUSE_THRESHOLD_MS = 2_000.0  # keystroke-logging convention for a planning pause
INTERRUPTION_THRESHOLD_MS = 20_000.0  # beyond this it is a look-up / interruption
MIN_BURST_KEYSTROKES = 10  # shortest run that counts as a production burst

# ── Internal helpers ──────────────────────────────────────────────────────────


def _neutral(code: str) -> float:
    """
    The NORM_BOUNDS midpoint — the only raw value that normalises to 0.5.
    Returned when the instrument gave us nothing to measure.
    """
    lo, hi = NORM_BOUNDS[code]
    return (lo + hi) / 2


def _iki_deltas(
    keystrokes: list[dict], max_gap_ms: float | None = MAX_CADENCE_IKI_MS
) -> list[float]:
    """
    Extract inter-keystroke intervals (IKI) in milliseconds from a list of
    keystroke event dicts.

    Bbook keystroke format:
        { "key": str, "timestamp": int (ms epoch), "elapsed": float (ms since start) }

    We use 'elapsed' if present; fall back to 'timestamp' differences.  The
    presence check is explicit rather than `elapsed or timestamp`: the first
    keystroke of every session legitimately has elapsed == 0.0, which is falsy,
    so the truthiness form either mixed session-relative ms with epoch ms or
    dropped the first real interval outright.

    max_gap_ms bounds what counts as motor cadence.  Pass None to keep long
    gaps — burst segmentation needs them as boundaries.
    """
    if not keystrokes:
        return []
    deltas: list[float] = []
    prev: float | None = None
    for ks in keystrokes:
        t = ks.get("elapsed")
        if t is None:
            t = ks.get("timestamp")
        if t is None:
            continue
        t = float(t)
        if prev is not None:
            d = t - prev
            if d > 0 and (max_gap_ms is None or d < max_gap_ms):
                deltas.append(d)
        prev = t
    return deltas


def _quantile(ordered: list[float], q: float) -> float:
    """Linear-interpolated quantile of an already-sorted list."""
    if not ordered:
        return 0.0
    if len(ordered) == 1:
        return ordered[0]
    pos = (len(ordered) - 1) * q
    lo = int(pos)
    hi = min(lo + 1, len(ordered) - 1)
    return ordered[lo] + (ordered[hi] - ordered[lo]) * (pos - lo)


def _is_deletion(key: str) -> bool:
    return key in ("Backspace", "Delete")


# ── Feature extractors ────────────────────────────────────────────────────────


def typing_speed_cv(keystroke_data: dict) -> float:
    """
    Robust CV of inter-keystroke intervals: (Q75 - Q25) / (1.349 * median).

    Scale-invariant by construction, so a slow typist and a fast typist with
    the same rhythm score identically; and tail-insensitive, so one planning
    pause inside the cadence window does not swamp the estimate.  The 1.349
    divisor is the normal IQR-to-sigma factor, which puts the output on the
    same scale as an ordinary CV: the published IKI moments (mean 238.7 ms,
    SD 111.6) imply 0.451 here versus a raw stdev/mean of 0.468.

    Interquartile rather than MAD/median: burst-and-hesitate typing is
    strongly bimodal, and whenever the split is uneven enough for the median
    to land on the fast mode, over half the intervals sit at distance zero
    from it and MAD reads 0 — scoring the most diagnostic composition rhythm
    in the tier as perfectly metronomic.

    Returns the neutral midpoint when cadence is unestimable (< 10 intervals)
    or when the median interval is below the ~60 ms physical floor, which
    indicates timestamp quantisation or a clock bug rather than fast typing.
    """
    keystrokes = keystroke_data.get("keystrokes", [])
    deltas = _iki_deltas(keystrokes)
    if len(deltas) < MIN_CADENCE_KEYSTROKES:
        return _neutral("typing_speed_cv")
    median = statistics.median(deltas)
    if median < MIN_PLAUSIBLE_MEDIAN_IKI_MS:
        return _neutral("typing_speed_cv")
    ordered = sorted(deltas)
    q25 = _quantile(ordered, 0.25)
    q75 = _quantile(ordered, 0.75)
    return (q75 - q25) / (1.349 * median)


def burst_ratio(keystroke_data: dict) -> float:
    """
    Fraction of keystrokes produced inside pause-delimited production bursts
    of at least MIN_BURST_KEYSTROKES keystrokes.

    Long gaps are kept (max_gap_ms=None) — an interruption still ends a burst
    even though it is excluded from motor-cadence estimates.

    Returns the neutral midpoint when fewer than 10 intervals are available.
    """
    keystrokes = keystroke_data.get("keystrokes", [])
    deltas = _iki_deltas(keystrokes, max_gap_ms=None)
    if len(deltas) < MIN_CADENCE_KEYSTROKES:
        return _neutral("burst_ratio")

    runs: list[int] = []
    current = 1
    for d in deltas:
        if d >= PAUSE_THRESHOLD_MS:
            runs.append(current)
            current = 1
        else:
            current += 1
    runs.append(current)

    total = sum(runs)
    return sum(r for r in runs if r >= MIN_BURST_KEYSTROKES) / total


def deletion_rate(keystroke_data: dict) -> float:
    """
    Deletion keystrokes / total keystrokes, as a fraction in [0, 1].

    Uses pre-computed deletionRate from Bbook's stylemetry summary if available;
    falls back to computing from raw keystroke array.

    Bbook's field has been observed in both fractional and percentage form, and
    the two differ by 100x against a bound of 0.20 — a percentage read as a
    fraction saturates every sample.  Values in (1, 100] are therefore treated
    as percentages; anything outside [0, 100] is uninterpretable and returns
    neutral rather than a confident wrong number.  Exactly 1.0 is ambiguous and
    is read as a fraction (100% deletions), which the caller will see as an
    obvious outlier either way.
    """
    dr = keystroke_data.get("deletionRate")
    if dr is not None:
        try:
            dr = float(dr)
        except (TypeError, ValueError):
            return _neutral("deletion_rate")
        if 0.0 <= dr <= 1.0:
            return dr
        if 1.0 < dr <= 100.0:
            return dr / 100.0
        return _neutral("deletion_rate")

    keystrokes = keystroke_data.get("keystrokes", [])
    if not keystrokes:
        return _neutral("deletion_rate")
    deletions = sum(1 for ks in keystrokes if _is_deletion(ks.get("key", "")))
    return deletions / len(keystrokes)


def pause_density(keystroke_data: dict) -> float:
    """
    Planning pauses (2 s <= p < 20 s) per 100 words of final output.

    Intervals at or beyond INTERRUPTION_THRESHOLD_MS are look-ups, interruptions
    or task-switches rather than composition planning, and are excluded.

    Returns the neutral midpoint when there is no word count to normalise by —
    0.0 would read as "this writer never pauses".
    """
    word_count = keystroke_data.get("wordCount") or 0
    if word_count < 1:
        return _neutral("pause_density")
    pauses = keystroke_data.get("pauses", [])
    planning = sum(
        1
        for p in pauses
        if PAUSE_THRESHOLD_MS
        <= (p.get("duration") or p.get("durationMs") or 0)
        < INTERRUPTION_THRESHOLD_MS
    )
    return (planning / word_count) * 100


def paste_event_rate(keystroke_data: dict) -> float:
    """
    Paste events per 100 words.

    Uses revision records tagged with type='paste'.  Returns the neutral
    midpoint without a word count — the previous fallback returned a raw event
    count, which is a different unit silently scored on the same scale.
    """
    word_count = keystroke_data.get("wordCount") or 0
    if word_count < 1:
        return _neutral("paste_event_rate")
    revisions = keystroke_data.get("revisions", [])
    paste_events = sum(1 for r in revisions if (r.get("type") or "") == "paste")
    return (paste_events / word_count) * 100


def revision_depth(keystroke_data: dict) -> float:
    """
    Mean characters affected per deletion/revision event.

    Low (~1): single-char backspacing (normal typing correction).
    High (>10): large block deletions (consistent with rewriting pasted content).

    Returns the neutral midpoint when no revision data is present — 0.0 is a
    real reading here ("only single-character corrections"), not "no instrument".
    """
    revisions = keystroke_data.get("revisions", [])
    # Keep only deletion-type revisions
    deletions = [r for r in revisions if (r.get("type") or "") in ("delete", "backspace", "")]
    if not deletions:
        return _neutral("revision_depth")
    chars = [abs(r.get("charsAffected") or 1) for r in deletions]
    return statistics.mean(chars)


# ── Public extractor ──────────────────────────────────────────────────────────


def extract_tier17(keystroke_data: dict) -> dict[str, float]:
    """
    Compute all 6 Tier 17 behavioral biometric features from Bbook keystroke data.

    Returns raw values in natural units; normalisation to [0, 1] is applied by
    pipeline.py via NORM_BOUNDS.

    Args:
        keystroke_data: The 'stylemetry' JSON blob from Bbook's submission payload.
                        Expected keys: keystrokes, pauses, revisions, deletionRate,
                        wordCount, avgWpm, avgPauseMs, sessionDurationSec.

    Returns:
        Dict of {feature_code: raw_value}.
    """
    return {
        "typing_speed_cv": typing_speed_cv(keystroke_data),
        "burst_ratio": burst_ratio(keystroke_data),
        "deletion_rate": deletion_rate(keystroke_data),
        "pause_density": pause_density(keystroke_data),
        "paste_event_rate": paste_event_rate(keystroke_data),
        "revision_depth": revision_depth(keystroke_data),
    }
