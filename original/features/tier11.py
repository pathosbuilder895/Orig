"""
features/tier11.py — Error Ecology (Weight 1.4).

The "Proof of Life" tier. Tracks idiosyncratic grammatical and syntactic
stumbles that are characteristic of each writer.  AI ghostwriters reproduce
a student's content but rarely reproduce their error fingerprint.

Error types detected:
  comma_splice   — independent clauses joined by comma (via spaCy dep parse,
                   falling back to heuristic if spaCy unavailable)
  adj_chain      — 3+ adjectives stacked before a noun (spaCy POS, with fallback)
  punct_error    — double/adjacent punctuation marks (regex on raw text)

Mathematics
───────────
Error profile P = {error_type: rate_per_100_words}

error_kl_divergence (comparison):
    S_error = 1 − clip(D_KL(P ∥ Q) / MAX_KL, 0, 1)
    High score → submission error fingerprint matches baseline.

stumble_rate_consistency (comparison):
    1 − |total_sub_rate − total_base_rate| / (total_base_rate + 0.01)
    High score → same overall error density as baseline.

punctuation_error_ratio (comparison):
    1 − |sub_punct_rate − base_punct_rate| / (base_punct_rate + 0.01)
    High score → same punctuation-error density as baseline.

All three are comparison features (require baseline profiles).
"""

import logging
import re
from typing import Dict, List

import numpy as np

from .tier1 import TextDoc

log = logging.getLogger(__name__)

# ── Lazy-loaded spaCy (same pattern as tier5) ─────────────────────────────────

_nlp = None
_spacy_warning_logged = False


def _get_nlp():
    global _nlp, _spacy_warning_logged
    if _nlp is None:
        try:
            import spacy
            _nlp = spacy.load("en_core_web_sm", disable=["ner", "lemmatizer"])
        except (ImportError, OSError):
            _nlp = "unavailable"
            if not _spacy_warning_logged:
                log.warning(
                    "spaCy model unavailable — Tier 11 error-ecology features will "
                    "use regex fallbacks. Run: python -m spacy download en_core_web_sm"
                )
                _spacy_warning_logged = True
    return _nlp


# ── Error profile extraction ──────────────────────────────────────────────────

def _extract_error_profile(doc: TextDoc) -> Dict[str, float]:
    """
    Compute per-100-word rates for three error categories.

    Returns: {"comma_splice": float, "adj_chain": float, "punct_error": float}
    """
    n_words = max(doc.word_count, 1)
    errors = {"comma_splice": 0, "adj_chain": 0, "punct_error": 0}

    nlp = _get_nlp()

    if nlp != "unavailable":
        # ── spaCy-based detection ─────────────────────────────────────────────
        spacy_doc = nlp(doc.raw)

        # Comma splice: comma token whose left neighbour has a root-like dep
        # within the same sentence (independent clause boundary heuristic).
        for sent in spacy_doc.sents:
            tokens = list(sent)
            for i, tok in enumerate(tokens):
                if tok.text == "," and 0 < i < len(tokens) - 1:
                    left = tokens[i - 1]
                    if left.dep_ in ("ROOT", "ccomp", "advcl", "parataxis"):
                        errors["comma_splice"] += 1

        # Front-loaded adjective chains: 3+ ADJ before a NOUN
        for tok in spacy_doc:
            if tok.pos_ == "NOUN":
                adj_run = 0
                for dep in tok.lefts:
                    if dep.pos_ == "ADJ":
                        adj_run += 1
                    elif dep.pos_ not in ("DET", "NUM", "PUNCT"):
                        break
                if adj_run >= 3:
                    errors["adj_chain"] += 1

    else:
        # ── Regex fallback (no spaCy) ─────────────────────────────────────────
        # Comma splice: comma between two clauses — rough heuristic
        # (two non-trivial words separated by comma, both followed by verb-like words)
        for sent in doc.sentences:
            # Simple heuristic: sentence contains ", and" or ", but" — not ideal
            # but gives a baseline reading without a dep parser
            if re.search(r'\b\w{4,}\b\s*,\s*\b(he|she|they|it|we|the|a|an|this|that)\b', sent, re.I):
                errors["comma_splice"] += 1

        # Adj chains: 3+ words ending in -ing/-ed/-ful/-ive/-ous before a noun
        adj_pat = r'(?:\b\w+(?:ing|ed|ful|ive|ous|al|ic)\s+){3,}\w+'
        errors["adj_chain"] = len(re.findall(adj_pat, doc.raw, re.I))

    # ── Regex punctuation errors (applies regardless of spaCy availability) ───
    # Two or more consecutive punctuation chars (e.g. ".," "?!" ",,")
    errors["punct_error"] = len(re.findall(r'[.,;!?]{2,}', doc.raw))

    # Normalise to per-100-word rates
    return {k: (v / n_words) * 100.0 for k, v in errors.items()}


# ── Profile extraction (for comparison at scoring time) ──────────────────────

def extract_tier11_profile(doc: TextDoc) -> Dict[str, object]:
    """Return the raw error-rate profile for storage as a baseline profile."""
    return {"_error_profile": _extract_error_profile(doc)}


# ── Comparison features ───────────────────────────────────────────────────────

def compute_tier11_comparison(
    sub_profile: Dict[str, object],
    baseline_profiles: Dict[str, object],
) -> Dict[str, float]:
    """
    Compute all three Error Ecology comparison features.

    sub_profile        — profile dict from extract_tier11_profile(submission_doc)
    baseline_profiles  — aggregated profile dict from build_aggregate_baseline_profiles()
                         must contain "_error_profiles": List[Dict[str, float]]
    """
    sub_err: Dict[str, float] = sub_profile.get("_error_profile", {})
    base_err_list: List[Dict[str, float]] = baseline_profiles.get("_error_profiles", [])

    KEYS = ["comma_splice", "adj_chain", "punct_error"]
    FALLBACK = {
        "error_kl_divergence":      0.5,
        "stumble_rate_consistency": 0.5,
        "punctuation_error_ratio":  0.5,
    }

    if not base_err_list or not sub_err:
        return FALLBACK

    # Aggregate baseline: mean per error type across all baseline samples
    base_avg = {
        k: float(np.mean([e.get(k, 0.0) for e in base_err_list]))
        for k in KEYS
    }

    # ── Feature 1: Error profile KL-divergence ────────────────────────────────
    # D_KL(P ∥ Q) where P = submission error distribution, Q = baseline.
    # Laplace smoothing (ε = 1e-6) prevents log(0).
    # S_error = 1 − clip(D_KL / MAX_KL, 0, 1)
    # High score → submission error distribution ≈ baseline (same "stumble DNA").
    eps = 1e-6
    p = np.array([sub_err.get(k, 0.0) + eps for k in KEYS], dtype=np.float64)
    q = np.array([base_avg.get(k, 0.0) + eps for k in KEYS], dtype=np.float64)
    p /= p.sum()
    q /= q.sum()
    # D_KL(P ∥ Q) = Σ P log₂(P/Q)  — in bits
    kl_div = float(np.sum(p * np.log2(p / q)))
    MAX_KL = 3.0   # bits; expected maximum divergence for 3-class distribution
    error_kl_divergence = float(np.clip(1.0 - kl_div / MAX_KL, 0.0, 1.0))

    # ── Feature 2: Stumble-rate consistency ───────────────────────────────────
    # Compares total error rate (all types summed) between submission and baseline.
    # Normalised by the baseline rate to make it scale-invariant.
    sub_total  = sum(sub_err.get(k, 0.0) for k in KEYS)
    base_total = sum(base_avg.get(k, 0.0) for k in KEYS)
    stumble_rate_consistency = float(np.clip(
        1.0 - abs(sub_total - base_total) / (base_total + 0.01),
        0.0, 1.0,
    ))

    # ── Feature 3: Punctuation-error ratio ────────────────────────────────────
    # Focuses specifically on the punct_error category (double-punctuation).
    # This is the least confounded by topic/length effects.
    punct_sub  = sub_err.get("punct_error", 0.0)
    punct_base = base_avg.get("punct_error", 0.0)
    punctuation_error_ratio = float(np.clip(
        1.0 - abs(punct_sub - punct_base) / (punct_base + 0.01),
        0.0, 1.0,
    ))

    return {
        "error_kl_divergence":      error_kl_divergence,
        "stumble_rate_consistency": stumble_rate_consistency,
        "punctuation_error_ratio":  punctuation_error_ratio,
    }
