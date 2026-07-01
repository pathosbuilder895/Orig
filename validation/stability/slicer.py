"""
slicer.py — word-level sliding window slicer for the stability study.

The whole point of the study is to ask "how does feature X behave when
the input is N words?". So we need to chop a full work into a set of
N-word windows and treat each window as an independent sample.

By default the windows are NON-OVERLAPPING — that's what variance
estimation expects. The ``overlap`` knob is exposed for ad-hoc
exploration; the default ``run.py`` invocation always uses overlap=0.
"""

from __future__ import annotations

import re
from typing import List


_WORD = re.compile(r"\S+")


def words_of(text: str) -> List[str]:
    """Whitespace-tokenise ``text`` into a list of words."""
    return _WORD.findall(text)


def slide(
    text: str,
    window_size: int,
    *,
    overlap: float = 0.0,
) -> List[str]:
    """
    Split ``text`` into ``window_size``-word chunks.

    Args:
        text:        the full source text.
        window_size: number of words per window (must be ≥ 1).
        overlap:     fraction of consecutive windows that overlap, in [0, 1).
                     0 = non-overlapping (the default; correct for variance
                     estimation). 0.5 = each window shares half its words
                     with the previous one.

    Returns:
        List of window strings. The trailing remainder (shorter than
        ``window_size``) is dropped so every returned window has exactly
        ``window_size`` words — important for the per-(feature, length)
        variance to mean the same thing.

    Raises:
        ValueError on a non-positive window or out-of-range overlap.
    """
    if window_size < 1:
        raise ValueError(f"window_size must be ≥ 1, got {window_size}")
    if not (0.0 <= overlap < 1.0):
        raise ValueError(f"overlap must be in [0, 1), got {overlap}")

    words = words_of(text)
    if len(words) < window_size:
        return []

    step = max(1, int(round(window_size * (1.0 - overlap))))
    windows: List[str] = []
    for start in range(0, len(words) - window_size + 1, step):
        windows.append(" ".join(words[start:start + window_size]))
    return windows
