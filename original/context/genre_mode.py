"""
original/context/genre_mode.py — GENRE_RESOLVER_V2 mode parsing.

Its own module so both the dispatcher in resolvers.py and the v2 resolver in
genre_v2.py can read the mode without importing each other.
"""

from __future__ import annotations

import os

GENRE_MODES = ("off", "shadow", "on")


def resolve_mode() -> str:
    """
    Parse GENRE_RESOLVER_V2 into "off" | "shadow" | "on".

    "1" is accepted as an alias for "on" so the flag reads like every other
    boolean flag in the table. Anything unrecognised — including "0", "true"
    and the empty string — falls back to "off": an unparseable value must
    never silently enable a path that changes scores. This mirrors
    quantum/scoring.py's _parse_topic_inflation_mode exactly, deliberately,
    so the two score-affecting mode flags in this codebase cannot drift apart
    in how they read their environment.
    """
    value = (os.environ.get("GENRE_RESOLVER_V2") or "").strip().lower()
    if value == "1":
        return "on"
    if value in GENRE_MODES:
        return value
    return "off"
