# Ωriginal — Adaptive Scoring Architecture Spec

> **For Claude Code:** This document specifies the next major architectural evolution of the scoring pipeline. Implement in phases, in order. Each phase is independently testable. Do not refactor existing Phase 1 code unless a phase explicitly requires it.

---

## Current State (Phase 1 — in place)

The existing pipeline is **static and context-blind**:

- `original/features/pipeline.py` — extracts ~103 features across 17 tiers
- `original/quantum/state.py` — builds density matrix ρ from baseline samples
- `original/quantum/scoring.py` — computes divergence score via RMS weighted z-score
- `original/constants.py` — defines `TIER_WEIGHTS`, `DISABLED_FEATURE_GROUPS`, `NORM_BOUNDS`

Fixed tier weights are applied identically regardless of submission context (genre, language, length, citation presence). A short blog post and a seminary exegesis paper are scored the same way. This is Phase 1's core limitation.

---

## Target Architecture — 8-Stage Adaptive Pipeline

```
Submission (raw text + metadata)
    │
    ▼
[Stage 1] Pre-processing          — existing preprocess.py (no change)
    │
    ▼
[Stage 2] Parallel Context Resolvers   ← NEW: original/context/resolvers.py
    │  Language · Genre · Topic · Length · Citation · Composition-mode
    ▼
[Stage 3] Context Manifest Assembly    ← NEW: original/context/manifest.py
    │  Single auditable JSON object describing the submission's context
    ▼
[Stage 4] Contextual Baseline Matching ← NEW: original/context/baseline_match.py
    │  Select closest genre/topic cluster from student's baseline corpus
    ▼
[Stage 5] Adaptive Weight Modification ← NEW: original/context/weighting.py
    │  Amplify / attenuate / mute per-tier weights based on manifest
    ▼
[Stage 6] Feature Extraction + Scoring — existing pipeline.py + scoring.py
    │  (modified to accept adaptive weights and matched baseline)
    ▼
[Stage 7] Auditable Report Assembly    ← NEW: original/context/report.py
    │  Divergence score + anchor tier breakdown + narrative explanation
    ▼
[Stage 8] Output
```

**NOTE:** Phases 3 and 4 (baseline matching) must be implemented before or alongside Phase 3 (adaptive weighting). Do not apply adaptive weights against the wrong baseline cluster — the two phases are co-dependent.

---

## Phase 2 — Resolver Layer

**New module:** `original/context/resolvers.py`

Build six context resolvers. Each is a small, independent function that takes the raw text (and optionally metadata) and returns a structured dict. Run all six in parallel (use `concurrent.futures.ThreadPoolExecutor`).

### 2.1 Language Resolver

```python
def resolve_language(text: str) -> dict:
    """
    Chunk-level language tagging.
    Returns primary language, per-language segment proportions, and code_switched flag.
    Critical for theological/academic submissions with Greek, Latin, Hebrew.

    Implementation:
    - Use langdetect or langid on 200-character sliding windows (50% overlap)
    - Aggregate window labels into proportions
    - Flag code_switched=True if any non-primary language > 5%

    Output:
    {
        "primary": "en",
        "segments": {"en": 0.87, "grc": 0.09, "la": 0.04},
        "code_switched": True
    }
    """
```

### 2.2 Genre Classifier

```python
def resolve_genre(text: str) -> dict:
    """
    Multi-class genre classification. Highest-impact resolver downstream.

    Target classes:
        academic_exegesis, scholarly_essay, sermon, personal_essay,
        creative_fiction, correspondence, blog_post, structured_template

    Implementation (in priority order):
    1. Train a TF-IDF + LogisticRegression classifier on labeled examples
       (collect from student baseline corpora + public labeled datasets)
    2. Fallback: rule-based classifier using citation density, first-person rate,
       imperative density, avg sentence length, and T16 signal verbs

    Training data source: use existing baseline texts from profiles.db,
    labeling them by assignment type metadata if available.

    Output:
    {
        "primary": "academic_exegesis",
        "confidence": 0.91,
        "secondary": "scholarly_essay"
    }
    """
```

### 2.3 Topic Resolver

```python
def resolve_topic(text: str, baseline_texts: list[str]) -> dict:
    """
    TF-IDF cosine distance from student's baseline topic centroid.
    Flags topical novelty so T10/T15 divergence isn't misread as identity drift.

    Implementation:
    - Fit TF-IDF on baseline_texts, transform submission
    - Compute cosine distance from baseline centroid
    - Map to novelty label: low (<0.25), medium (0.25-0.5), high (>0.5)

    Output:
    {
        "domain": "new_testament_studies",   # top LDA topic label
        "baseline_distance": 0.18,
        "novelty": "low"                     # low | medium | high
    }
    """
```

### 2.4 Length-Regime Detector

```python
def resolve_length(text: str) -> dict:
    """
    Token-count bucketing with per-tier reliability flags.
    T7 distributional features degrade below ~500 tokens.

    Regimes:
        micro:    < 150 tokens  — anchor-only scoring; most tiers muted
        short:    150-500       — T7 suppressed; reduce confidence
        standard: 500-3000      — all tiers reliable
        long:     > 3000        — full reliability; T7 most informative

    Output:
    {
        "tokens": 2840,
        "regime": "standard",
        "reliable_tiers": "all",     # or list of reliable tier IDs
        "suppress_tiers": []
    }
    """
```

### 2.5 Citation Detector

```python
def resolve_citations(text: str) -> dict:
    """
    Citation density, format, and block-quote proportion.
    Mutes citation-dependent T16 features when citations absent.
    Isolates block-quoted material from prose fingerprinting.

    Implementation: reuse existing preprocess.py citation extraction logic.

    Output:
    {
        "citations_present": True,
        "density": 0.04,              # citations per 100 words
        "block_quote_ratio": 0.12,    # proportion of text in block quotes
        "format": "chicago"           # chicago | mla | apa | informal | none
    }
    """
```

### 2.6 Composition-Mode Detector

```python
def resolve_composition_mode(text: str) -> dict:
    """
    Infers software mediation (Grammarly-cleaned prose).
    Anomalously low T14 error rates suggest tool-polished text.

    Heuristics:
    - Comma splice rate < 0.001 AND punctuation_error_ratio < 0.002 → likely tool-cleaned
    - Paste-composition signature (requires T17 keystroke data if available)
    - Unusually uniform sentence length variance → structured composition

    Output:
    {
        "mode": "natural_drafted",    # natural_drafted | tool_cleaned | structured
        "edit_signature": "normal",   # normal | heavy | uniform
        "software_mediated": False
    }
    """
```

### 2.7 Resolver Orchestrator

```python
def run_resolvers(
    text: str,
    baseline_texts: list[str],
    metadata: dict | None = None,
) -> dict:
    """
    Run all six resolvers in parallel.
    Returns combined resolver_outputs dict.
    """
```

---

## Phase 3 — Context Manifest Assembly

**New module:** `original/context/manifest.py`

```python
@dataclass
class ContextManifest:
    submission_id: str
    language: dict           # from resolve_language()
    genre: dict              # from resolve_genre()
    topic: dict              # from resolve_topic()
    length_regime: str       # from resolve_length()
    citations: dict          # from resolve_citations()
    composition_mode: dict   # from resolve_composition_mode()

    # Derived directives (computed from above)
    weight_modifications: dict   # {suppress: [], amplify: [], attenuate: [], mute: []}
    anchor_tiers: list[str]      # tier IDs promoted to anchor status
    baseline_match: dict         # {cluster: str, n_samples: int, recency_weighted: bool}

    def to_json(self) -> str: ...
    def to_dict(self) -> dict: ...
```

**Manifest derivation rules** (implement as `_derive_directives(resolver_outputs) -> dict`):

| Condition | Directive |
|-----------|-----------|
| `length_regime == "micro"` | mute all tiers except T4, T6, T13, T14 |
| `length_regime == "short"` | mute T7; suppress T1.ttr; reduce confidence |
| `genre == "creative_fiction"` | mute T16; genre-normalize T2, T3, T15 against creative cluster |
| `citations_present == False` | mute T16 entirely |
| `citations_present == True` | promote T16 to anchor |
| `composition_mode == "tool_cleaned"` | attenuate T11, T14; flag in report |
| `code_switched == True` | segment-score T1, T5, T7 per language |
| `topic.novelty == "high"` | attenuate T10, T15; note topical distance in report |
| always | anchor: T4, T6 (cross-genre stable identity signals) |
| `genre in [exegesis, academic, sermon]` | anchor: T8, T13 (prosodic identity stable) |

---

## Phase 4 — Contextual Baseline Matching

**New module:** `original/context/baseline_match.py`

Rather than comparing against a single merged baseline, select the closest contextual cluster within the student's corpus.

```python
def match_baseline_cluster(
    manifest: ContextManifest,
    baseline_profiles: list[dict],   # each has genre, topic, text, features
) -> list[dict]:
    """
    Score each baseline sample against the submission's manifest:
        score = 0.4 * genre_similarity
              + 0.4 * topic_similarity
              + 0.2 * recency_weight

    genre_similarity: 1.0 if same genre label, 0.5 if same genre family, 0.0 otherwise
    topic_similarity: 1 - cosine_distance(submission_tfidf, sample_tfidf)
    recency_weight: normalized position in corpus (most recent = 1.0)

    Return top-N samples (N=3 default, minimum 2).
    If no samples score > 0.5 similarity: fall back to anchor-tier-only scoring
    (set manifest.baseline_match.anchor_only = True).

    The returned cluster replaces the monolithic baseline in scoring.py.
    """
```

**Integration point:** `compute_full_features()` in `pipeline.py` receives the matched cluster instead of all baseline texts.

**Fallback:** When `anchor_only=True`, scoring uses only the anchor tiers defined in the manifest. Confidence is reduced and flagged in the report.

---

## Phase 5 — Adaptive Weight Modification

**New module:** `original/context/weighting.py`

```python
def build_adaptive_weight_vector(
    manifest: ContextManifest,
    base_weights: dict[str, float],   # from constants.TIER_WEIGHTS
    all_feature_codes: list[str],     # from constants.ALL_FEATURE_CODES
) -> np.ndarray:
    """
    Apply manifest directives to base tier weights.
    Returns a per-feature weight array (same shape as the scoring z-score vector).

    Operations:
        amplify:   weight *= 1.15  (anchor tier confirmed reliable in this context)
        attenuate: weight *= 0.6   (context introduces noise)
        mute:      weight  = 0.0   (feature meaningless in this context)
        normalize: weight unchanged (compared against genre-matched baseline only)

    This vector replaces _TIER_WEIGHT_VECTOR in scoring.py for this submission.
    """
```

**Integration:** Modify `scoring.score()` to accept an optional `adaptive_weights: np.ndarray` parameter. When provided, use it in place of `_TIER_WEIGHT_VECTOR`. When absent, fall back to static weights (preserves Phase 1 behavior).

```python
# In scoring.py — modified signature:
def score(
    submission_vector: np.ndarray,
    state: StudentState,
    adaptive_weights: np.ndarray | None = None,   # NEW
) -> ScoringResult:
    weight_vector = adaptive_weights if adaptive_weights is not None else _TIER_WEIGHT_VECTOR
    ...
```

---

## Phase 6 — Report Assembly

**New module:** `original/context/report.py`

```python
@dataclass
class ScoringReport:
    submission_id: str
    divergence_score: float        # 0.0 = identical to baseline, 1.0 = maximally different
    verdict: str                   # "authentic" | "uncertain" | "anomalous"
    confidence: str                # "high" | "medium" | "low" | "insufficient_data"
    context_manifest: dict         # the full manifest (auditable)
    anchor_tier_scores: dict       # {tier_id: consistency_score} for anchor tiers only
    narrative: str                 # auto-generated natural language explanation
    flags: list[str]               # ["software_mediated", "anchor_only_scoring", ...]
    baseline_cluster: list[str]    # sample IDs used for comparison

def generate_narrative(manifest: ContextManifest, result: ScoringResult) -> str:
    """
    Template-based narrative generator.
    Fills slots from manifest and anchor tier scores.

    Example output:
    "Submission scores 0.087 against a context-matched baseline of 3 academic
    exegesis samples. All five anchor tiers show consistency above 0.89.
    Greek and Latin segments scored against language-specific sub-baseline at 0.92.
    Topical distance from baseline (0.18) is within normal academic range and does
    not affect identity score. Software-mediation signals absent."
    """
```

---

## Phase 7 — Sliding-Window Blend Detection

**New module:** `original/context/blend.py` *(implement last)*

```python
def detect_blend(
    text: str,
    state: StudentState,
    window_tokens: int = 300,
    overlap: float = 0.5,
) -> BlendResult:
    """
    Score overlapping windows of the submission.
    Detect mid-document fingerprint shifts that suggest:
        - Collaborative authorship
        - AI-generated sections
        - Advisor-edited passages

    Output:
    {
        "blend_detected": bool,
        "blend_index": float,          # 0.0 = uniform, 1.0 = maximally blended
        "shift_positions": list[int],  # token positions of detected transitions
        "per_section": [               # one entry per window
            {"start": 0, "end": 300, "score": 0.08, "confidence": "high"},
            ...
        ]
    }
    """
```

---

## Phase 8 — Drift Detection and Rebaseline

**Extend:** `original/quantum/state.py`

```python
def check_drift(self, new_sample: BaselineSample, threshold: float = 0.25) -> DriftResult:
    """
    Compare new_sample against the existing density matrix.
    If anchor-tier deviation exceeds threshold across 2+ consecutive samples:
        - Flag for rebaseline review
        - Do not auto-add to density matrix until reviewed

    DriftResult:
        {
            "drift_detected": bool,
            "drift_magnitude": float,
            "anchor_tier_deviations": dict,
            "recommendation": "accept" | "flag_for_review" | "rebaseline"
        }
    """
```

---

## File Structure After Full Implementation

```
original/
├── context/                    ← NEW package
│   ├── __init__.py
│   ├── resolvers.py            ← Phase 2: six context resolvers
│   ├── manifest.py             ← Phase 3: ContextManifest dataclass + derivation
│   ├── baseline_match.py       ← Phase 4: cluster retrieval
│   ├── weighting.py            ← Phase 5: adaptive weight vector
│   ├── report.py               ← Phase 6: ScoringReport + narrative
│   └── blend.py                ← Phase 7: sliding-window blend detection
├── features/
│   └── pipeline.py             ← modified: accepts matched baseline cluster
├── quantum/
│   ├── scoring.py              ← modified: accepts adaptive_weights parameter
│   └── state.py                ← extended: check_drift() method
└── constants.py                ← extended: genre classifier labels, resolver thresholds
```

---

## Key Design Constraints

1. **Backward compatibility:** All changes to `scoring.py` and `pipeline.py` must be additive (optional parameters with existing behavior as default). Phase 1 API must not break.

2. **Auditability:** Every scoring run that uses adaptive weights must store the `ContextManifest` alongside the score. The manifest is the audit trail explaining why weights were modified.

3. **Graceful degradation:** If any resolver fails (import error, model not loaded, etc.), fall back to Phase 1 static weights and log a warning. Never surface resolver failures to the API caller as errors.

4. **Genre classifier training data:** The genre classifier (Phase 2) is the critical dependency. If labeled training data is not yet available, implement the rule-based fallback first (citation density + first-person rate + imperative density heuristics) and upgrade to a trained classifier when data is collected.

5. **Phase 4+5 co-dependency:** Do not ship Phase 5 (adaptive weighting) without Phase 4 (baseline cluster matching). Amplifying weights against the wrong baseline cluster is worse than static weights. These two phases must land together.

---

## Testing

Each phase should have its own test file in `tests/`:

- `tests/context/test_resolvers.py` — unit test each resolver in isolation
- `tests/context/test_manifest.py` — test directive derivation logic for each scenario
- `tests/context/test_baseline_match.py` — test cluster selection with mock corpora
- `tests/context/test_weighting.py` — verify weight vector shape and muting logic
- `tests/context/test_report.py` — test narrative generation and report assembly
- `tests/context/test_integration.py` — end-to-end: text → manifest → weights → score → report

The integration test should cover all 10 scenario types from the design doc:
`short_uncited`, `creative_fiction`, `multilingual_exegesis`, `formal_academic`,
`correspondence`, `sermon`, `software_mediated`, `developmental_drift`,
`collaborative_edited`, `format_constrained`.
