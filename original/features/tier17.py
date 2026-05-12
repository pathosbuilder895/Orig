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
typing_speed_cv      Coefficient of variation of inter-keystroke intervals.
                     Consistent typists → low CV.  Hesitant/variable → high CV.
                     Computed from elapsed-time deltas between successive keystrokes.

burst_ratio          Fraction of keystrokes fired in rapid bursts (< 150 ms gap).
                     Fluent writers type in bursts; AI-assisted copy-paste shows
                     anomalously even spacing.

deletion_rate        Backspace / Delete events as a fraction of all keystrokes.
                     Stable across sessions for a given writer; spikes when
                     copy-editing pasted content.

pause_density        Long pauses (> 3 s) per 100 words of output.
                     Measures thinking rhythm; stable per writer, differs markedly
                     between authentic writing and transcript-entry.

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
"""

from __future__ import annotations

import math
import statistics
from typing import Dict, List, Any, Optional


# ── Internal helpers ──────────────────────────────────────────────────────────

def _iki_deltas(keystrokes: List[Dict]) -> List[float]:
    """
    Extract inter-keystroke intervals (IKI) in milliseconds from a list of
    keystroke event dicts.

    Bbook keystroke format:
        { "key": str, "timestamp": int (ms epoch), "elapsed": float (ms since start) }

    We use 'elapsed' if present; fall back to 'timestamp' differences.
    """
    if not keystrokes:
        return []
    deltas: List[float] = []
    prev: Optional[float] = None
    for ks in keystrokes:
        t = ks.get("elapsed") or ks.get("timestamp")
        if t is None:
            continue
        t = float(t)
        if prev is not None:
            d = t - prev
            if 0 < d < 30_000:   # ignore gaps > 30 s (focus lost)
                deltas.append(d)
        prev = t
    return deltas


def _is_deletion(key: str) -> bool:
    return key in ("Backspace", "Delete")


def _is_paste(event_type: Optional[str], key: str) -> bool:
    return event_type == "paste" or key in ("v",)   # 'v' alone is not enough;
    # Bbook tags paste events in revision records; key-level is a secondary check


# ── Feature extractors ────────────────────────────────────────────────────────

def typing_speed_cv(keystroke_data: Dict) -> float:
    """
    CV (std / mean) of inter-keystroke intervals.

    Returns 0.5 (neutral) when fewer than 10 keystrokes.
    """
    keystrokes = keystroke_data.get("keystrokes", [])
    deltas = _iki_deltas(keystrokes)
    if len(deltas) < 10:
        return 0.5
    mean = statistics.mean(deltas)
    if mean < 1e-6:
        return 0.0
    stdev = statistics.stdev(deltas)
    return stdev / mean


def burst_ratio(keystroke_data: Dict) -> float:
    """
    Fraction of keystrokes with IKI < 150 ms (rapid burst).

    Returns 0.5 (neutral) when fewer than 10 keystrokes.
    """
    keystrokes = keystroke_data.get("keystrokes", [])
    deltas = _iki_deltas(keystrokes)
    if len(deltas) < 10:
        return 0.5
    burst = sum(1 for d in deltas if d < 150)
    return burst / len(deltas)


def deletion_rate(keystroke_data: Dict) -> float:
    """
    Deletion keystrokes / total keystrokes.

    Uses pre-computed deletionRate from Bbook's stylemetry summary if available;
    falls back to computing from raw keystroke array.
    """
    # Prefer pre-computed value from Bbook
    dr = keystroke_data.get("deletionRate")
    if dr is not None:
        return float(dr)
    keystrokes = keystroke_data.get("keystrokes", [])
    if not keystrokes:
        return 0.0
    deletions = sum(1 for ks in keystrokes if _is_deletion(ks.get("key", "")))
    return deletions / len(keystrokes)


def pause_density(keystroke_data: Dict) -> float:
    """
    Long pauses (> 3 000 ms) per 100 words of final output.

    Returns 0.0 when no word-count information available.
    """
    pauses = keystroke_data.get("pauses", [])
    word_count = keystroke_data.get("wordCount") or 0
    if word_count < 1:
        return 0.0
    long_pauses = sum(
        1 for p in pauses
        if (p.get("duration") or p.get("durationMs") or 0) >= 3_000
    )
    return (long_pauses / word_count) * 100


def paste_event_rate(keystroke_data: Dict) -> float:
    """
    Paste events per 100 words.

    Uses revision records tagged with type='paste'; falls back to 0.
    """
    revisions = keystroke_data.get("revisions", [])
    word_count = keystroke_data.get("wordCount") or 0
    paste_events = sum(
        1 for r in revisions
        if (r.get("type") or "") == "paste"
    )
    if word_count < 1:
        return float(paste_events)   # can't normalise; return raw count
    return (paste_events / word_count) * 100


def revision_depth(keystroke_data: Dict) -> float:
    """
    Mean characters affected per deletion/revision event.

    Low (~1): single-char backspacing (normal typing correction).
    High (>10): large block deletions (consistent with rewriting pasted content).

    Returns 0.0 when no revision data is present.
    """
    revisions = keystroke_data.get("revisions", [])
    # Keep only deletion-type revisions
    deletions = [
        r for r in revisions
        if (r.get("type") or "") in ("delete", "backspace", "")
    ]
    if not deletions:
        return 0.0
    chars = [abs(r.get("charsAffected") or 1) for r in deletions]
    return statistics.mean(chars)


# ── Public extractor ──────────────────────────────────────────────────────────

def extract_tier17(keystroke_data: Dict) -> Dict[str, float]:
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
        "typing_speed_cv":   typing_speed_cv(keystroke_data),
        "burst_ratio":       burst_ratio(keystroke_data),
        "deletion_rate":     deletion_rate(keystroke_data),
        "pause_density":     pause_density(keystroke_data),
        "paste_event_rate":  paste_event_rate(keystroke_data),
        "revision_depth":    revision_depth(keystroke_data),
    }
