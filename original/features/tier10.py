"""
features/tier10.py — Semantic Gravity Wells.

Uses sentence embeddings (all-MiniLM-L6-v2) to quantify a writer's
involuntary conceptual attractors — the semantic regions they repeatedly
return to.

Mathematics
───────────
Let E = {e₁, …, eₙ} be the L2-normalised sentence embeddings.

semantic_field_dispersion (standalone):
    Variance of all pairwise cosine distances within the submission.
    High variance → wide semantic range (human exploration).
    Low variance → narrow, uniform semantic coverage (AI typical).

    d_{ij} = 1 − eᵢ · eⱼ
    dispersion = clip(Var({d_{ij}}) / 0.1, 0, 1)

semantic_centroid_proximity (comparison):
    Mean minimum L2 distance from each submission embedding to the
    set of baseline centroids C = {c₁, …, cᴮ} (one centroid per baseline
    sample, computed as the mean of that sample's sentence embeddings).

    D = (1/n) Σᵢ min_{c∈C} ‖eᵢ − c‖
    score = clip(1 − tanh(D), 0, 1)

    Near 0 distance → score ≈ 1.0 (submission lives in student's semantic field).
    Large distance → score ≈ 0.0 (semantic trespasser).
"""

import logging
from typing import Any, Dict, List, Optional

import numpy as np

from .tier1 import TextDoc

log = logging.getLogger(__name__)

# ── Backend selection ─────────────────────────────────────────────────────────
# Priority:
#   1. sentence-transformers + torch (richest semantic embeddings)
#   2. TF-IDF via scikit-learn (lightweight, always available, captures
#      vocabulary clustering — sufficient for stylometric gravity well detection)
#
# The TF-IDF backend is NOT a fallback placeholder; it is a genuine
# implementation of the same semantic gravity well concept using term-frequency
# vectors instead of transformer embeddings.  Pairwise cosine similarity in
# TF-IDF space measures how consistently a writer re-uses the same vocabulary
# clusters across sentences — a reliable stylometric signal.

_st_model: Any = None
_st_failed: bool = False


def _get_st_model() -> Optional[Any]:
    """Load sentence-transformers model if available (requires torch)."""
    global _st_model, _st_failed
    if _st_failed:
        return None
    if _st_model is not None:
        return _st_model
    try:
        from sentence_transformers import SentenceTransformer
        _st_model = SentenceTransformer("all-MiniLM-L6-v2")
        log.info("Tier 10: using sentence-transformers backend (all-MiniLM-L6-v2)")
        return _st_model
    except Exception as e:
        _st_failed = True
        log.info("Tier 10: sentence-transformers unavailable (%s); using TF-IDF backend", e)
        return None


def _tfidf_encode(sentences: List[str], vocab: Optional[Any] = None) -> Optional[np.ndarray]:
    """
    Encode sentences as L2-normalised TF-IDF vectors.

    If vocab is provided (a fitted TfidfVectorizer), uses it for consistent
    feature space between baseline and submission.  Otherwise fits on the
    input sentences.

    Returns (N, V) float32 array or None if fewer than 2 usable sentences.
    """
    if len(sentences) < 2:
        return None
    try:
        from sklearn.feature_extraction.text import TfidfVectorizer
        from sklearn.preprocessing import normalize
        vec = TfidfVectorizer(
            min_df=1, max_features=300,
            sublinear_tf=True, strip_accents="unicode",
        ) if vocab is None else vocab
        if vocab is None:
            M = vec.fit_transform(sentences).toarray()
        else:
            M = vec.transform(sentences).toarray()
        M = normalize(M, norm="l2")  # L2-normalise so cosine sim = dot product
        return M.astype(np.float32)
    except Exception as e:
        log.warning("Tier 10: TF-IDF encode failed: %s", e)
        return None


def _encode_sentences(doc: TextDoc) -> Optional[np.ndarray]:
    """
    Return L2-normalised sentence embeddings (N × D) for sentences > 10 chars.
    Uses sentence-transformers if available; falls back to TF-IDF.
    """
    sents = [s.strip() for s in doc.sentences if len(s.strip()) > 10]
    if len(sents) < 2:
        return None
    model = _get_st_model()
    if model is not None:
        try:
            return model.encode(sents, normalize_embeddings=True)
        except Exception:
            pass
    return _tfidf_encode(sents)


# ── Standalone feature ────────────────────────────────────────────────────────

def extract_tier10_standalone(doc: TextDoc) -> Dict[str, float]:
    """
    semantic_field_dispersion: variance of pairwise cosine distances within
    the submission's sentence embeddings.

    High dispersion → writer ranges widely across semantic fields (human).
    Low dispersion → writer stays in a narrow semantic lane (AI-typical).

    Normalisation: typical prose variance ≈ 0.01–0.08;
    clip(Var / 0.1, 0, 1) maps this to [0.1, 0.8] with headroom at both ends.
    """
    embs = _encode_sentences(doc)
    if embs is None or len(embs) < 3:
        return {"semantic_field_dispersion": 0.5}

    # Pairwise cosine distances via dot-product of L2-normalised embeddings
    # sim_matrix[i,j] = eᵢ · eⱼ  (cosine similarity)
    sim_matrix = embs @ embs.T                          # (N, N)
    n = len(embs)
    dists = [
        1.0 - float(sim_matrix[i, j])
        for i in range(n)
        for j in range(i + 1, n)
    ]
    variance = float(np.var(dists))
    dispersion = float(np.clip(variance / 0.1, 0.0, 1.0))
    return {"semantic_field_dispersion": dispersion}


# ── Profile extraction (for comparison at scoring time) ──────────────────────

def extract_tier10_profile(doc: TextDoc) -> Dict[str, object]:
    """
    Extract sentence embeddings for storage as a baseline profile.
    Returns a (N, 384) array, or a (1, 384) zero array if text is too short.
    """
    embs = _encode_sentences(doc)
    if embs is None:
        return {"_semantic_embeddings": np.zeros((1, 384), dtype=np.float32)}
    return {"_semantic_embeddings": embs}


# ── Comparison feature ────────────────────────────────────────────────────────

def compute_tier10_comparison(
    sub_profile: Dict[str, object],
    baseline_profiles: Dict[str, object],
) -> Dict[str, float]:
    """
    semantic_centroid_proximity: how close the submission's sentences are
    to the student's established semantic gravity wells.

    Works with both transformer embeddings and TF-IDF vectors.
    Baseline centroids C = [mean(embs) for embs in baseline_sample_embeddings]
    For each submission sentence eᵢ, compute min_{c∈C} ‖eᵢ − c‖.
    Mean of these minima = D.

    score = clip(1 − tanh(D), 0, 1)
      D≈0  → score≈1.0  (semantically very close to baseline)
      D≈2  → score≈0.03 (semantic trespasser)
    """
    sub_embs = sub_profile.get("_semantic_embeddings")
    base_emb_list = baseline_profiles.get("_semantic_embeddings_list", [])
    base_emb_list = [e for e in base_emb_list if e is not None and e.shape[0] > 0]

    # If pre-computed TF-IDF embeddings have mismatched vocabulary dimensions
    # (each sample was encoded independently with its own vocabulary), clear them
    # so we fall through to the shared-vocabulary re-fit path below.
    if sub_embs is not None and base_emb_list:
        sub_dim = sub_embs.shape[1] if sub_embs.ndim == 2 else None
        base_dim = base_emb_list[0].shape[1] if base_emb_list[0].ndim == 2 else None
        if sub_dim is not None and base_dim is not None and sub_dim != base_dim:
            sub_embs = None
            base_emb_list = []

    if sub_embs is None or len(sub_embs) == 0 or not base_emb_list:
        # Try TF-IDF path: rebuild from raw sentences stored in profiles
        sub_sents = sub_profile.get("_sentences", [])
        base_sents_list = baseline_profiles.get("_sentences_list", [])
        if not sub_sents or not base_sents_list:
            return {"semantic_centroid_proximity": 0.5}

        # Fit vocabulary on all sentences combined for consistent feature space
        all_sents = sub_sents + [s for grp in base_sents_list for s in grp]
        try:
            from sklearn.feature_extraction.text import TfidfVectorizer
            from sklearn.preprocessing import normalize
            vectorizer = TfidfVectorizer(min_df=1, max_features=300, sublinear_tf=True)
            vectorizer.fit(all_sents)
            sub_embs = _tfidf_encode(sub_sents, vocab=vectorizer)
            base_emb_list = [
                _tfidf_encode(grp, vocab=vectorizer)
                for grp in base_sents_list
                if grp
            ]
            base_emb_list = [e for e in base_emb_list if e is not None]
        except Exception:
            return {"semantic_centroid_proximity": 0.5}

    if sub_embs is None or not base_emb_list:
        return {"semantic_centroid_proximity": 0.5}

    centroids = np.stack([np.mean(e, axis=0) for e in base_emb_list])  # (B, D)
    min_dists = []
    for e in sub_embs:
        diffs = centroids - e[None, :]
        l2_dists = np.linalg.norm(diffs, axis=1)
        min_dists.append(float(np.min(l2_dists)))

    D = float(np.mean(min_dists))
    score = float(np.clip(1.0 - float(np.tanh(D)), 0.0, 1.0))
    return {"semantic_centroid_proximity": score}
