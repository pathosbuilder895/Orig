"""Named TermSim configuration matrix cells."""
from __future__ import annotations

STANDARD = {
    "baseline": {
        "CONTEXT_MANIFEST_ENABLED": "1",
        "ADAPTIVE_WEIGHTS_ENABLED": "1",
        "NULL_MODEL": "impostor",
        "LLR_ACTION_MODE": "gate",
    },
    # Identical flags to `baseline` but the runner never accretes accepted
    # submissions — the accrete-vs-frozen delta is itself a metric (T2's
    # two-mode requirement; the main-path analogue of the fused C1 confound).
    "baseline-frozen": {
        "CONTEXT_MANIFEST_ENABLED": "1",
        "ADAPTIVE_WEIGHTS_ENABLED": "1",
        "NULL_MODEL": "impostor",
        "LLR_ACTION_MODE": "gate",
    },
    "llr-shadow": {
        "CONTEXT_MANIFEST_ENABLED": "1",
        "ADAPTIVE_WEIGHTS_ENABLED": "1",
        "NULL_MODEL": "impostor",
        "LLR_ACTION_MODE": "shadow",
    },
    "no-context": {
        "CONTEXT_MANIFEST_ENABLED": "0",
        "ADAPTIVE_WEIGHTS_ENABLED": "0",
        "NULL_MODEL": "none",
    },
    "topic-inflation": {
        "CONTEXT_MANIFEST_ENABLED": "1",
        "ADAPTIVE_WEIGHTS_ENABLED": "1",
        "NULL_MODEL": "impostor",
        "LLR_ACTION_MODE": "gate",
        "TOPIC_VARIANCE_INFLATION": "on",
    },
    "characteristic-weights": {
        "CONTEXT_MANIFEST_ENABLED": "1",
        "ADAPTIVE_WEIGHTS_ENABLED": "1",
        "NULL_MODEL": "impostor",
        "LLR_ACTION_MODE": "gate",
        "CHARACTERISTIC_WEIGHTS": "on",
    },
    "genre-v2": {
        "CONTEXT_MANIFEST_ENABLED": "1",
        "ADAPTIVE_WEIGHTS_ENABLED": "1",
        "NULL_MODEL": "impostor",
        "LLR_ACTION_MODE": "gate",
        "GENRE_RESOLVER_V2": "on",
    },
}


# Cells the runner replays WITHOUT accreting accepted submissions.
FROZEN_CELLS = frozenset({"baseline-frozen"})


def cells(name="standard") -> dict[str, dict[str, str]]:
    if name != "standard":
        raise ValueError(f"unknown matrix: {name}")
    return {cell: dict(flags) for cell, flags in STANDARD.items()}
