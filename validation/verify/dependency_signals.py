"""Candidate dependency-parse / morphosyntactic features (Phase 5A probe).

Validation-only. Nothing here is imported by ``original/``; whether any of
these features ever reaches the production vector is decided by gate G-P5a in
``validation/verify/dependency_probe.py``.

Why these candidates exist
--------------------------
The production pipeline is 109 features over 18 tiers, of which exactly two
are syntax-complexity numbers: ``subordination_ratio`` -- a count of SCONJ
*tokens* divided by sentence count, i.e. a POS tally, not a dependency
relation -- and ``clause_depth_mean``. Meanwhile a full dependency parse is
already computed and thrown away: ``original/features/tier5.py::_get_dep_depths``
walks ``token.children`` for a per-sentence max depth and discards every arc
label, every arc direction, every arc length, and all of ``token.morph``
(which is referenced nowhere in the repository).

The literature's claim -- the one under test -- is that grammatical habits are
comparatively more robust to topic and paraphrase than vocabulary is, because
they are choices about structure rather than about subject matter. This module
only *extracts*; it makes no claim.

Denominator choices, stated up front
------------------------------------
* **Relation rates are per 100 word tokens**, where a word token is any parsed
  token that is neither whitespace nor punctuation.

  - Per *token* rather than per *sentence* because a per-sentence rate is a
    product of the relation's density and the author's sentence length, and
    sentence length is already measured directly in tier 1/3. A per-sentence
    rate would re-measure it and correlate with it by construction.
  - Punctuation is excluded from the denominator because punctuation habits
    are already tier 4's subject; a denominator that counted commas would make
    every dependency rate partly a comma measurement.

* **Tree depth is normalised by sentence length.** ``clause_depth_mean``
  already reports the un-normalised per-sentence max depth, which is dominated
  by how long the author's sentences are. Dividing by the sentence's token
  count asks a different question -- how deeply nested a clause is *for its
  length* -- and the probe measures directly whether that separation survives
  (see the redundancy column of the findings table).

Degenerate input
----------------
Every function returns a finite float inside its declared ``CANDIDATE_RANGES``
entry for any input, including the empty string. The neutral vector is 0.0
everywhere except ``dep_subord_coord_ratio``, which is a bounded ratio whose
denominator can legitimately be zero and whose neutral is therefore 0.5.

Two malformed-parse cases are handled explicitly because both are reachable:

1. **No root.** ``spacy.tokens.Doc`` accepts a head structure in which no
   token heads itself (a cycle). ``tier5._get_dep_depths`` guards this with a
   ``seen`` set; ``_max_depth`` below keeps that guard, because an unguarded
   walk recurses until the interpreter stack dies.
2. **No sentence boundaries.** ``Doc.sents`` raises ``ValueError`` (E030) on a
   Doc that no component has sentencised. The extractor falls back to treating
   the whole Doc as one sentence rather than propagating.

Determinism
-----------
There is no RNG in this module, and spaCy's pipeline is deterministic for a
fixed model, so repeat extraction over the same text is bit-identical. That is
asserted in ``tests/validation/test_dependency_signals.py``.
"""

from __future__ import annotations

import math
from collections import Counter

__all__ = [
    "CANDIDATE_CODES",
    "CANDIDATE_RANGES",
    "dependency_features",
    "dependency_features_from_text",
    "get_nlp",
]

#: Ordered candidate list. Order is the order the findings table reports in;
#: it carries no priority meaning.
CANDIDATE_CODES: tuple[str, ...] = (
    "dep_nsubj_rate",
    "dep_dobj_rate",
    "dep_advcl_rate",
    "dep_ccomp_rate",
    "dep_relcl_rate",
    "dep_conj_rate",
    "dep_amod_rate",
    "dep_pos_pair_entropy",
    "dep_distance_mean",
    "dep_distance_cv",
    "dep_left_branching_ratio",
    "dep_normalized_tree_depth",
    "dep_subord_coord_ratio",
    "dep_morph_entropy",
)

#: Declared operating range per feature. These are *containment* bounds used
#: by the extractor tests, not proposed NORM_BOUNDS -- the probe reports
#: observed percentiles separately for that purpose.
CANDIDATE_RANGES: dict[str, tuple[float, float]] = {
    "dep_nsubj_rate": (0.0, 100.0),
    "dep_dobj_rate": (0.0, 100.0),
    "dep_advcl_rate": (0.0, 100.0),
    "dep_ccomp_rate": (0.0, 100.0),
    "dep_relcl_rate": (0.0, 100.0),
    "dep_conj_rate": (0.0, 100.0),
    "dep_amod_rate": (0.0, 100.0),
    "dep_pos_pair_entropy": (0.0, 12.0),
    "dep_distance_mean": (0.0, 1000.0),
    "dep_distance_cv": (0.0, 50.0),
    "dep_left_branching_ratio": (0.0, 1.0),
    "dep_normalized_tree_depth": (0.0, 1.0),
    "dep_subord_coord_ratio": (0.0, 1.0),
    "dep_morph_entropy": (0.0, 12.0),
}

# spaCy's English models emit the ClearNLP label set (``dobj``, ``relcl``),
# not Universal Dependencies (``obj``, ``acl:relcl``). Both spellings are
# accepted so the extractor does not silently read zero if the model or its
# label scheme is ever swapped.
_RELATION_ALIASES: dict[str, frozenset[str]] = {
    "dep_nsubj_rate": frozenset({"nsubj", "nsubjpass", "nsubj:pass"}),
    "dep_dobj_rate": frozenset({"dobj", "obj"}),
    "dep_advcl_rate": frozenset({"advcl"}),
    "dep_ccomp_rate": frozenset({"ccomp"}),
    "dep_relcl_rate": frozenset({"relcl", "acl:relcl"}),
    "dep_conj_rate": frozenset({"conj"}),
    "dep_amod_rate": frozenset({"amod"}),
}

_SUBORDINATE_DEPS = frozenset(
    {"advcl", "ccomp", "xcomp", "csubj", "csubjpass", "csubj:pass", "acl", "relcl", "acl:relcl"}
)
_COORDINATION_DEPS = frozenset({"conj", "cc"})

_NEUTRAL: dict[str, float] = {code: 0.0 for code in CANDIDATE_CODES}
_NEUTRAL["dep_subord_coord_ratio"] = 0.5

_nlp = None


def get_nlp():
    """Load ``en_core_web_sm`` once, with tier 5's disable list.

    Matching tier 5's ``disable=["ner", "lemmatizer"]`` matters: it is the
    pipeline a shared-parse production implementation would actually inherit,
    so the cost number the probe reports is the cost that would be paid. The
    morphologizer and attribute_ruler stay enabled -- they are what populates
    ``token.morph``.
    """
    global _nlp
    if _nlp is None:
        import spacy

        _nlp = spacy.load("en_core_web_sm", disable=["ner", "lemmatizer"])
    return _nlp


def _shannon_entropy(counter: Counter) -> float:
    """Shannon entropy in bits. Mirrors ``tier5._shannon_entropy`` exactly so
    the entropy candidates are on the same scale as ``pos_bigram_entropy``."""
    total = sum(counter.values())
    if total == 0:
        return 0.0
    entropy = 0.0
    for count in counter.values():
        if count > 0:
            p = count / total
            entropy -= p * math.log2(p)
    return entropy


def _max_depth(token, seen: set) -> int:
    """Depth of the subtree rooted at ``token``, cycle-guarded.

    The ``seen`` set is not defensive decoration: ``Doc`` accepts head
    structures with cycles, and this walk would otherwise not terminate.
    """
    if token.i in seen:
        return 0
    seen.add(token.i)
    child_depths = [_max_depth(child, seen) for child in token.children if child.i not in seen]
    return 1 + max(child_depths) if child_depths else 1


def _sentences(doc):
    """``doc.sents`` when available, else the whole Doc as one span.

    ``Doc.sents`` raises ValueError E030 when nothing has set sentence
    boundaries (an unparsed Doc). Returning the whole document keeps every
    downstream per-sentence quantity defined.
    """
    try:
        return list(doc.sents)
    except ValueError:
        return [doc[:]] if len(doc) else []


def dependency_features(doc) -> dict[str, float]:
    """Extract every candidate from an already-parsed spaCy ``Doc``.

    Takes a Doc rather than text so the probe can share one parse across the
    whole candidate set -- and so the cost measurement can separate "parse"
    from "extract", which is the number that decides whether this tier is
    affordable in production.
    """
    words = [t for t in doc if not t.is_space and not t.is_punct]
    n_words = len(words)
    values = dict(_NEUTRAL)
    if n_words == 0:
        return values

    # ── Relation rates, per 100 word tokens ─────────────────────────────────
    dep_counts: Counter = Counter(t.dep_ for t in words)
    for code, labels in _RELATION_ALIASES.items():
        hits = sum(dep_counts[label] for label in labels)
        values[code] = hits / n_words * 100.0

    # ── Arc-level quantities (exclude self-headed tokens: no arc) ───────────
    arcs = [t for t in words if t.head.i != t.i]
    if arcs:
        pair_counts: Counter = Counter((t.head.pos_, t.pos_) for t in arcs)
        values["dep_pos_pair_entropy"] = _shannon_entropy(pair_counts)

        distances = [abs(t.i - t.head.i) for t in arcs]
        mean_distance = sum(distances) / len(distances)
        values["dep_distance_mean"] = mean_distance
        if mean_distance > 0:
            variance = sum((d - mean_distance) ** 2 for d in distances) / len(distances)
            values["dep_distance_cv"] = math.sqrt(variance) / mean_distance

        left = sum(1 for t in arcs if t.i < t.head.i)
        values["dep_left_branching_ratio"] = left / len(arcs)

    # ── Subordination vs coordination, as dependency arcs ───────────────────
    subordinate = sum(dep_counts[label] for label in _SUBORDINATE_DEPS)
    coordinate = sum(dep_counts[label] for label in _COORDINATION_DEPS)
    if subordinate + coordinate > 0:
        values["dep_subord_coord_ratio"] = subordinate / (subordinate + coordinate)

    # ── Length-normalised tree depth ────────────────────────────────────────
    ratios = []
    for sent in _sentences(doc):
        span = [t for t in sent if not t.is_space]
        if not span:
            continue
        roots = [t for t in sent if t.head.i == t.i]
        start = roots[0] if roots else span[0]
        ratios.append(_max_depth(start, set()) / len(span))
    if ratios:
        values["dep_normalized_tree_depth"] = min(1.0, sum(ratios) / len(ratios))

    # ── Morphological feature diversity ─────────────────────────────────────
    morph_counts: Counter = Counter()
    for token in words:
        for pair in str(token.morph).split("|"):
            if pair:
                morph_counts[pair] += 1
    values["dep_morph_entropy"] = _shannon_entropy(morph_counts)

    return values


def dependency_features_from_text(text: str, nlp=None) -> dict[str, float]:
    """Convenience wrapper: parse ``text`` and extract. Parses on every call --
    the probe uses ``dependency_features`` with a cached Doc instead."""
    if not text or not text.strip():
        return dict(_NEUTRAL)
    nlp = nlp or get_nlp()
    return dependency_features(nlp(text))
