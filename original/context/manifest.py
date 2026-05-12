"""
context/manifest.py — Phase 3: Context Manifest assembly.

Consumes the resolver outputs from `original/context/resolvers.py` and produces
a `ContextManifest`: an auditable, JSON-serialisable record describing the
submission's context plus the per-feature-code directives that downstream
phases (4 baseline matching, 5 adaptive weighting) will apply.

Phase 3 attaches the manifest to `Layer7Output.context_manifest` for inspection
when `CONTEXT_MANIFEST_ENABLED=1` is set; **scoring weights remain static**.
This lets us collect real-world manifests in production and validate resolver
outputs without touching the score itself.

Directive table (from the implementation plan)
==============================================

| Condition                             | Directive                              |
|---------------------------------------|----------------------------------------|
| length_regime == "micro"              | mute T1,2,3,5,7,9,10,11,15,16,17       |
|                                       |  → keep T4,6,13,14                     |
| length_regime == "short"              | mute T7; attenuate type_token_ratio    |
| genre == "creative_fiction"           | mute T16                               |
| citations.citations_present is False  | mute T16                               |
| citations.citations_present is True   | anchor T16                             |
| composition_mode.mode == "tool_cleaned" | attenuate T11+T14; flag software_mediated |
| language.code_switched is True        | flag code_switched                     |
| topic.novelty == "high"               | attenuate T10+T15; flag topic_novelty_high|
| always                                | anchor T4, T6                          |
| genre in {academic_*, sermon}         | anchor T8, T13                         |
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set

from ..constants import (
    TIER1_CODES, TIER2_CODES, TIER3_CODES, TIER4_CODES, TIER5_CODES,
    TIER6_CODES, TIER7_CODES, TIER8_CODES, TIER9_CODES, TIER10_CODES,
    TIER11_CODES, TIER13_CODES, TIER14_CODES, TIER15_CODES, TIER16_CODES,
    TIER17_CODES,
)


# Tier index → list of feature codes — used to expand tier-level directives
# from the table above into the per-feature-code working set.
_TIER_TO_CODES: Dict[int, List[str]] = {
    1:  TIER1_CODES,
    2:  TIER2_CODES,
    3:  TIER3_CODES,
    4:  TIER4_CODES,
    5:  TIER5_CODES,
    6:  TIER6_CODES,
    7:  TIER7_CODES,
    8:  TIER8_CODES,
    9:  TIER9_CODES,
    10: TIER10_CODES,
    11: TIER11_CODES,
    13: TIER13_CODES,
    14: TIER14_CODES,
    15: TIER15_CODES,
    16: TIER16_CODES,
    17: TIER17_CODES,
}


# Genres that retain their prosodic identity even under context shift —
# they get T8 (prosody) and T13 (prosodic depth) promoted to anchor status.
_PROSODIC_ANCHOR_GENRES: Set[str] = {
    "academic_exegesis",
    "scholarly_essay",
    "sermon",
}


# ══════════════════════════════════════════════════════════════════════════════
# ContextManifest dataclass
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class ContextManifest:
    """
    Auditable record of a submission's resolved context + the directives
    that the adaptive layer will apply to its scoring run.

    All resolver outputs are stored verbatim (resolver dicts) so the audit
    log is complete: a manifest read from disk is enough to reproduce why
    weights were modified, without re-running the resolvers.
    """

    submission_id: str

    # Verbatim resolver outputs.
    language: Dict[str, Any]
    genre: Dict[str, Any]
    topic: Dict[str, Any]
    length_regime: str
    citations: Dict[str, Any]
    composition_mode: Dict[str, Any]

    # Derived directives, applied at the per-feature-code level so Phase 5
    # weight-vector construction is a trivial dict lookup.
    weight_modifications: Dict[str, List[str]] = field(default_factory=dict)
    anchor_tiers: List[int] = field(default_factory=list)

    # Filled by Phase 4 baseline matching; left empty in Phase 3.
    baseline_match: Dict[str, Any] = field(default_factory=dict)

    # Human-readable flags, useful for the report narrative + UI surfacing.
    flags: List[str] = field(default_factory=list)

    # ISO 8601 UTC timestamp.
    created_at: str = ""

    # ── Convenience accessors ────────────────────────────────────────────────

    @property
    def amplify_codes(self) -> List[str]:
        return list(self.weight_modifications.get("amplify_codes", []))

    @property
    def attenuate_codes(self) -> List[str]:
        return list(self.weight_modifications.get("attenuate_codes", []))

    @property
    def mute_codes(self) -> List[str]:
        return list(self.weight_modifications.get("mute_codes", []))

    # ── Serialisation ────────────────────────────────────────────────────────

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), sort_keys=True)

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "ContextManifest":
        # Filter unknown keys (forward-compat) and ensure list/dict defaults.
        known = {f for f in cls.__dataclass_fields__}
        clean = {k: v for k, v in d.items() if k in known}
        clean.setdefault("weight_modifications", {})
        clean.setdefault("anchor_tiers", [])
        clean.setdefault("baseline_match", {})
        clean.setdefault("flags", [])
        clean.setdefault("created_at", "")
        return cls(**clean)


# ══════════════════════════════════════════════════════════════════════════════
# Directive derivation
# ══════════════════════════════════════════════════════════════════════════════

def _codes_in_tiers(tiers: List[int]) -> List[str]:
    """Flatten a list of tier indices into the union of their feature codes."""
    out: List[str] = []
    for t in tiers:
        out.extend(_TIER_TO_CODES.get(t, []))
    return out


def _derive_directives(resolver_outputs: Dict[str, Dict]) -> Dict[str, Any]:
    """
    Apply the directive table to resolver outputs.

    Returns
    -------
    {
        "weight_modifications": {
            "amplify_codes":   [...],   # currently always empty (anchors live in anchor_tiers)
            "attenuate_codes": [...],
            "mute_codes":      [...],
        },
        "anchor_tiers":  [int, ...],     # always includes 4, 6
        "flags":         ["software_mediated", ...],
    }

    Sets are used internally to dedupe; the public dict converts back to
    sorted lists for stable serialisation.
    """
    mute: Set[str] = set()
    attenuate: Set[str] = set()
    amplify: Set[str] = set()
    anchors: Set[int] = {4, 6}     # always-on anchors
    flags: Set[str] = set()

    length = resolver_outputs.get("length", {}) or {}
    genre = resolver_outputs.get("genre", {}) or {}
    topic = resolver_outputs.get("topic", {}) or {}
    citations = resolver_outputs.get("citations", {}) or {}
    composition_mode = resolver_outputs.get("composition_mode", {}) or {}
    language = resolver_outputs.get("language", {}) or {}

    # ── Length regime ────────────────────────────────────────────────────────
    regime = length.get("regime")
    if regime == "micro":
        # Mute everything except T4 (char/punct), T6 (idiosyncratic),
        # T13 (prosodic depth), T14 (error topology). Tiers 0 and 12 are
        # bookkeeping (comparison + tension arc) — leave them alone.
        mute.update(_codes_in_tiers([1, 2, 3, 5, 7, 9, 10, 11, 15, 16, 17]))
    elif regime == "short":
        mute.update(TIER7_CODES)
        if "type_token_ratio" in TIER1_CODES:
            attenuate.add("type_token_ratio")

    # ── Genre ────────────────────────────────────────────────────────────────
    genre_label = genre.get("primary")
    if genre_label == "creative_fiction":
        mute.update(TIER16_CODES)
    if genre_label in _PROSODIC_ANCHOR_GENRES:
        anchors.update({8, 13})

    # ── Citations ────────────────────────────────────────────────────────────
    if citations.get("citations_present"):
        anchors.add(16)
    else:
        mute.update(TIER16_CODES)

    # ── Composition mode ─────────────────────────────────────────────────────
    if composition_mode.get("mode") == "tool_cleaned":
        attenuate.update(TIER11_CODES)
        attenuate.update(TIER14_CODES)
        flags.add("software_mediated")

    # ── Language ─────────────────────────────────────────────────────────────
    if language.get("code_switched"):
        flags.add("code_switched")

    # ── Topic ────────────────────────────────────────────────────────────────
    if topic.get("novelty") == "high":
        attenuate.update(TIER10_CODES)
        attenuate.update(TIER15_CODES)
        flags.add("topic_novelty_high")

    # ── Resolve mute/attenuate/amplify precedence ────────────────────────────
    # A code that is both attenuated AND muted should end up muted (mute is
    # strictly stronger). Likewise, a code that is amplified AND muted is
    # muted. We never amplify a code that's also attenuated.
    attenuate -= mute
    amplify -= mute
    amplify -= attenuate

    return {
        "weight_modifications": {
            "amplify_codes":   sorted(amplify),
            "attenuate_codes": sorted(attenuate),
            "mute_codes":      sorted(mute),
        },
        "anchor_tiers": sorted(anchors),
        "flags":        sorted(flags),
    }


# ══════════════════════════════════════════════════════════════════════════════
# Public builder
# ══════════════════════════════════════════════════════════════════════════════

def build_manifest(
    submission_id: str,
    resolver_outputs: Dict[str, Dict],
) -> ContextManifest:
    """
    Construct a `ContextManifest` from a `run_resolvers()` output dict.

    Resolver outputs that are missing or empty (e.g. a resolver raised and
    landed in `_errors`) are tolerated: derivation falls back to safe
    defaults (no muting, no flags, default anchors {4, 6}).

    Phase 3 leaves `baseline_match` empty; Phase 4 fills it.
    """
    directives = _derive_directives(resolver_outputs)

    return ContextManifest(
        submission_id=submission_id,
        language=resolver_outputs.get("language", {}) or {},
        genre=resolver_outputs.get("genre", {}) or {},
        topic=resolver_outputs.get("topic", {}) or {},
        length_regime=(resolver_outputs.get("length", {}) or {}).get("regime", "unknown"),
        citations=resolver_outputs.get("citations", {}) or {},
        composition_mode=resolver_outputs.get("composition_mode", {}) or {},
        weight_modifications=directives["weight_modifications"],
        anchor_tiers=directives["anchor_tiers"],
        baseline_match={},   # filled in Phase 4
        flags=directives["flags"],
        created_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    )


__all__ = ["ContextManifest", "build_manifest"]
