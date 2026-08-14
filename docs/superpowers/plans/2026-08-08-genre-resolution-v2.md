# Genre Resolution v2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace a genre resolver that sorts 86% of all prose into one terminal-`else` bucket with one that abstains honestly and, where it does claim a label, has corpus evidence for it.

**Architecture:** One env flag `GENRE_RESOLVER_V2` (`off`/`shadow`/`on`, default `off`, byte-identical when off). `resolvers.resolve_genre` becomes a thin mode dispatcher; v2 lives in a new `original/context/genre_v2.py`. Stage 1 adds `unknown` + real confidence to the existing rules. Stage 2 replaces the rules with a calibrated multinomial logistic regression, shipped as a **JSON** artifact (coefficients + scaler) so inference is pure numpy.

**Tech Stack:** Python 3.11, numpy, pytest. scikit-learn is used **only** in the offline derivation script, never at inference.

## Global Constraints

- Python is `/Users/andrew/Desktop/Original/.venv/bin/python`. Never system python3.
- `ALL_FEATURE_CODES` ordering and `NORM_BOUNDS` must not change. Genre signals are computed locally in `genre_v2.py`; they are NOT pipeline features.
- `GENRE_LABELS` gains exactly one entry (`unknown`). The existing 8 are untouched, so persisted `sample.genre` values and `get_genre_stats` pooling keys stay valid. No data migration.
- `GENRE_RESOLVER_V2=off` must be byte-identical to today. This is a tested property, not an intention.
- sklearn must not be imported at inference time. It is absent from the base `requirements.txt`.
- Spec: `docs/superpowers/specs/2026-08-08-genre-resolution-design.md`.
- Commit style: `Add ...` / `Fix ...`, one focused commit per task, co-author line `Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>`.
- Full suite: `.venv/bin/python -m pytest tests/ validation/test_tier10_optional.py -q`. Expect `0 failed`.

---

# STAGE 1 — Abstention

## Task 1: Flag, label, and threshold constants

**Files:**
- Modify: `original/constants.py`
- Create: `original/context/genre_mode.py`
- Test: `tests/context/test_genre_mode.py`

**Interfaces:**
- Produces: `GENRE_UNKNOWN: str = "unknown"`, `GENRE_CONFIDENCE_MIN: float = 0.55`, `GENRE_LABELS` (9 entries), `genre_mode.resolve_mode() -> str` returning `"off" | "shadow" | "on"`.

- [ ] **Step 1: Write the failing test**

```python
# tests/context/test_genre_mode.py
import pytest
from original.context.genre_mode import resolve_mode


class TestGenreMode:
    def test_defaults_to_off_when_unset(self, monkeypatch):
        monkeypatch.delenv("GENRE_RESOLVER_V2", raising=False)
        assert resolve_mode() == "off"

    @pytest.mark.parametrize("raw,expected", [
        ("off", "off"), ("shadow", "shadow"), ("on", "on"),
        ("1", "on"), ("ON", "on"), ("  shadow  ", "shadow"),
    ])
    def test_recognised_values(self, monkeypatch, raw, expected):
        monkeypatch.setenv("GENRE_RESOLVER_V2", raw)
        assert resolve_mode() == expected

    @pytest.mark.parametrize("raw", ["", "yes", "true", "2", "garbage", "0"])
    def test_unrecognised_falls_back_to_off(self, monkeypatch, raw):
        """An unparseable value must never silently enable a score-changing
        path — same rule as _parse_topic_inflation_mode."""
        monkeypatch.setenv("GENRE_RESOLVER_V2", raw)
        assert resolve_mode() == "off"


class TestGenreConstants:
    def test_unknown_is_a_label(self):
        from original.constants import GENRE_LABELS, GENRE_UNKNOWN
        assert GENRE_UNKNOWN == "unknown"
        assert GENRE_UNKNOWN in GENRE_LABELS

    def test_the_original_eight_labels_are_untouched(self):
        """Persisted sample.genre values and get_genre_stats pooling keys
        depend on these exact strings."""
        from original.constants import GENRE_LABELS
        assert GENRE_LABELS[:8] == [
            "academic_exegesis", "scholarly_essay", "sermon", "personal_essay",
            "creative_fiction", "correspondence", "blog_post", "structured_template",
        ]
        assert len(GENRE_LABELS) == 9
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/context/test_genre_mode.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'original.context.genre_mode'`

- [ ] **Step 3: Write minimal implementation**

Append to `original/constants.py` (after the existing `GENRE_LABELS` block — append `"unknown"` to the list literal):

```python
# The abstention outcome for resolve_genre v2. Appended rather than
# substituted: the eight labels above are persisted on BaselineSample.genre
# and used as get_genre_stats pooling keys, so changing them would require a
# data migration. See docs/superpowers/specs/2026-08-08-genre-resolution-design.md
GENRE_UNKNOWN = "unknown"

# Minimum calibrated probability required to CLAIM a genre. Below this the
# resolver abstains. Applied only to Stage 2's model output — Stage 1's rule
# hits carry a placeholder confidence and are not thresholded (a placeholder
# compared against a real threshold would abstain on everything).
GENRE_CONFIDENCE_MIN = 0.55
```

Create `original/context/genre_mode.py`:

```python
"""
GENRE_RESOLVER_V2 mode parsing, in its own module so both the dispatcher in
resolvers.py and genre_v2.py can read it without importing each other.
"""
from __future__ import annotations

import os

GENRE_MODES = ("off", "shadow", "on")


def resolve_mode() -> str:
    """
    Parse GENRE_RESOLVER_V2 into "off" | "shadow" | "on".

    "1" is accepted as an alias for "on" so the flag reads like every other
    boolean flag in the table. Anything unrecognised falls back to "off":
    an unparseable value must never silently enable a path that changes
    scores. Mirrors quantum/scoring.py's _parse_topic_inflation_mode exactly.
    """
    value = (os.environ.get("GENRE_RESOLVER_V2") or "").strip().lower()
    if value == "1":
        return "on"
    if value in GENRE_MODES:
        return value
    return "off"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/context/test_genre_mode.py -q`
Expected: PASS (12 tests)

- [ ] **Step 5: Commit**

```bash
git add original/constants.py original/context/genre_mode.py tests/context/test_genre_mode.py
git commit -m "Add GENRE_RESOLVER_V2 mode parsing and the unknown genre label"
```

---

## Task 2: The abstaining rule resolver

**Files:**
- Create: `original/context/genre_v2.py`
- Test: `tests/context/test_genre_v2_rules.py`

**Interfaces:**
- Consumes: `GENRE_UNKNOWN` from Task 1.
- Produces: `genre_v2.resolve(text, citation_data=None) -> dict` with keys `primary`, `confidence`, `secondary`. `genre_v2.looks_structured(text) -> bool`. `genre_v2.RULE_CONFIDENCE = 0.5`, `genre_v2.MARKUP_CONFIDENCE = 1.0`.

- [ ] **Step 1: Write the failing test**

```python
# tests/context/test_genre_v2_rules.py
from original.constants import GENRE_UNKNOWN
from original.context import genre_v2


class TestAbstention:
    def test_ordinary_prose_abstains_rather_than_claiming_correspondence(self):
        """The whole point. Today this text returns "correspondence" at a
        hardcoded 0.5 confidence; correspondence is rule 8's terminal else,
        not a positive class."""
        text = (
            "The argument proceeds by considering the nature of the good, and "
            "whether it can be known apart from its particular instances. "
            "Those who deny this must account for the evident agreement of "
            "ordinary language on the matter, which is not easily set aside. "
        ) * 6
        out = genre_v2.resolve(text)
        assert out["primary"] == GENRE_UNKNOWN
        assert out["confidence"] == 0.0

    def test_empty_text_abstains(self):
        out = genre_v2.resolve("")
        assert out["primary"] == GENRE_UNKNOWN
        assert out["confidence"] == 0.0

    def test_never_returns_the_string_correspondence(self):
        """v2 has no evidence for correspondence and must never claim it."""
        for text in ["", "short.", "The matter is settled. " * 40]:
            assert genre_v2.resolve(text)["primary"] != "correspondence"


class TestStructuredTemplate:
    def test_markup_is_recognised_at_full_confidence(self):
        text = "# Heading\n- first point\n- second point\n- third point\n1. step one\n"
        out = genre_v2.resolve(text)
        assert out["primary"] == "structured_template"
        assert out["confidence"] == genre_v2.MARKUP_CONFIDENCE

    def test_prose_with_one_stray_dash_is_not_structured(self):
        text = "This is ordinary prose about a subject. " * 20 + "\n- one bullet\n"
        assert genre_v2.resolve(text)["primary"] != "structured_template"


class TestCurlyQuoteFix:
    def test_typographic_quotes_are_recognised_as_dialogue(self):
        """v1's regex matched straight quotes only, so Gutenberg-sourced
        prose (Douglass: 0% straight, 64% curly) could never reach the
        creative_fiction branch."""
        straight = 'He said, "we shall go at once," and turned away. ' * 12
        curly = "He said, “we shall go at once,” and turned away. " * 12
        assert genre_v2.dialogue_present(straight) is True
        assert genre_v2.dialogue_present(curly) is True

    def test_no_quotes_is_not_dialogue(self):
        assert genre_v2.dialogue_present("Plain prose without any quotation.") is False


class TestContract:
    def test_returns_the_v1_key_shape(self):
        out = genre_v2.resolve("some text here")
        assert set(out) == {"primary", "confidence", "secondary"}

    def test_confidence_is_always_in_the_unit_interval(self):
        for text in ["", "# h\n- a\n- b\n", "Prose. " * 50]:
            c = genre_v2.resolve(text)["confidence"]
            assert 0.0 <= c <= 1.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/context/test_genre_v2_rules.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'original.context.genre_v2'`

- [ ] **Step 3: Write minimal implementation**

Create `original/context/genre_v2.py`. Copy the rule bodies from `resolvers.resolve_genre` (rules 1–7) verbatim, then replace the rule-8 fallback with abstention:

```python
"""
original/context/genre_v2.py — the abstaining genre resolver.

Stage 1 of docs/superpowers/specs/2026-08-08-genre-resolution-design.md.

v1 (resolvers._resolve_genre_v1) sorts 86% of all prose into rule 8's
terminal `else`, "correspondence", and reports it at a hardcoded confidence
of 0.5. Four of its eight labels are unreachable on real text. This module
keeps the rules that can fire, fixes the one outright bug in them, and
returns GENRE_UNKNOWN instead of inventing a label.

Stage 2 replaces the rule tree below with a calibrated model; the abstention
contract established here does not change.
"""
from __future__ import annotations

import re
from typing import Any

from ..constants import GENRE_LABELS, GENRE_RULES, GENRE_UNKNOWN

# Rule hits are UNCALIBRATED. 0.5 is a placeholder that says "a rule matched",
# not a probability — which is why GENRE_CONFIDENCE_MIN is not applied in
# Stage 1 (see the spec's Stage 1 section). Markup is syntactic certainty.
RULE_CONFIDENCE = 0.5
MARKUP_CONFIDENCE = 1.0

# v1 used r'"[^"]{1,80}"' — straight quotes only. Gutenberg-sourced prose uses
# typographic quotes, so Douglass (0% straight / 64% curly) and the Federalist
# papers (0% / 36%) could never reach the creative_fiction branch.
_DIALOGUE_RE = re.compile(r'"[^"]{1,80}"|“[^”]{1,80}”|‘[^’]{1,80}’')

_STRUCTURE_RE = re.compile(r"^\s*(?:[-*•]|\d+[\.)]|#{1,6}\s|\[\s*[xX ]\s*\])")


def dialogue_present(text: str) -> bool:
    """True when the text contains a quoted span, straight or typographic."""
    return _DIALOGUE_RE.search(text or "") is not None


def looks_structured(text: str) -> bool:
    """Heuristic: text full of headings / numbered lists / bullets."""
    lines = [line for line in (text or "").splitlines() if line.strip()]
    if not lines:
        return False
    return sum(1 for line in lines if _STRUCTURE_RE.match(line)) / len(lines) >= 0.3


def _abstain() -> dict[str, Any]:
    return {"primary": GENRE_UNKNOWN, "confidence": 0.0, "secondary": None}


def resolve(text: str, citation_data=None) -> dict[str, Any]:
    """
    Genre with abstention. Same return shape as resolvers.resolve_genre.

    The markup rule is evaluated FIRST and at full confidence: it keys on
    syntax rather than style, so it is the one label that does not need
    corpus evidence to be trustworthy.
    """
    text = text or ""
    if not text.strip():
        return _abstain()

    if looks_structured(text):
        return {
            "primary": "structured_template",
            "confidence": MARKUP_CONFIDENCE,
            "secondary": None,
        }

    from ..features.preprocess import preprocess
    from ..features.tier1 import TextDoc
    from ..features.tier3 import first_person_ratio, imperative_density
    from .resolvers import _tokenize

    doc = TextDoc(text)
    word_count = max(1, doc.word_count)
    if citation_data is None:
        _, citation_data = preprocess(text)
    cite_total = (
        citation_data.paren_citation_count
        + citation_data.footnote_marker_count
        + citation_data.ibid_count
    )
    cite_density = (cite_total / word_count) * 100.0
    block_quote_ratio = citation_data.block_quote_word_count / word_count
    imp_density = imperative_density(doc)
    fp_ratio = first_person_ratio(doc)
    msl = sum(len(_tokenize(s)) for s in doc.sentences) / max(1, doc.sentence_count)
    signal_verb_total = sum(citation_data.signal_verb_counts.values())

    primary: str | None = None
    if (
        cite_density >= GENRE_RULES["academic_citation_density_min"]
        and msl >= GENRE_RULES["academic_msl_min"]
        and signal_verb_total >= GENRE_RULES["scholarly_signal_verb_min"]
    ):
        primary = "academic_exegesis"
    elif (
        cite_density >= GENRE_RULES["academic_citation_density_min"] * 0.5
        and signal_verb_total >= GENRE_RULES["scholarly_signal_verb_min"]
    ):
        primary = "scholarly_essay"
    elif (
        imp_density >= GENRE_RULES["sermon_imperative_min"]
        and fp_ratio >= GENRE_RULES["sermon_first_person_min"]
        and cite_density < GENRE_RULES["academic_citation_density_min"] * 0.5
    ):
        primary = "sermon"
    elif (
        fp_ratio >= GENRE_RULES["sermon_first_person_min"]
        and cite_density < 0.3
        and msl <= GENRE_RULES["informal_msl_max"] + 4.0
    ):
        primary = "personal_essay"
    elif (
        block_quote_ratio < 0.05
        and signal_verb_total == 0
        and cite_density < 0.1
        and msl < GENRE_RULES["academic_msl_min"]
        and dialogue_present(text)
    ):
        primary = "creative_fiction"

    # No rule 5 (blog_post) and no rule 8 fallback. v2 has no corpus evidence
    # for blog_post or correspondence, so it never claims them — the whole
    # point of the abstention contract.
    if primary is None or primary not in GENRE_LABELS:
        return _abstain()
    return {"primary": primary, "confidence": RULE_CONFIDENCE, "secondary": None}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/context/test_genre_v2_rules.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add original/context/genre_v2.py tests/context/test_genre_v2_rules.py
git commit -m "Add the abstaining genre resolver (v2 rules)"
```

---

## Task 3: The mode dispatcher

**Files:**
- Modify: `original/context/resolvers.py` (rename current body to `_resolve_genre_v1`, add dispatcher)
- Test: `tests/context/test_genre_dispatch.py`

**Interfaces:**
- Consumes: `genre_mode.resolve_mode()`, `genre_v2.resolve()`.
- Produces: `resolvers.resolve_genre(text, citation_data=None) -> dict`. In `shadow` the dict gains `shadow_primary` and `shadow_confidence`; `primary` is unchanged.

- [ ] **Step 1: Write the failing test**

```python
# tests/context/test_genre_dispatch.py
from pathlib import Path

import pytest

from original.constants import GENRE_UNKNOWN
from original.context.resolvers import _resolve_genre_v1, resolve_genre

_SAMPLES = sorted(Path("validation/corpus").glob("*.txt"))[:40]


class TestOffIsByteIdentical:
    def test_off_matches_v1_exactly_on_every_sample(self, monkeypatch):
        """The property that makes the default safe by inspection."""
        monkeypatch.setenv("GENRE_RESOLVER_V2", "off")
        for path in _SAMPLES:
            text = path.read_text(errors="ignore")
            assert resolve_genre(text) == _resolve_genre_v1(text), path.name

    def test_unset_behaves_as_off(self, monkeypatch):
        monkeypatch.delenv("GENRE_RESOLVER_V2", raising=False)
        text = _SAMPLES[0].read_text(errors="ignore")
        assert resolve_genre(text) == _resolve_genre_v1(text)


class TestShadowIsInert:
    def test_primary_still_comes_from_v1(self, monkeypatch):
        monkeypatch.setenv("GENRE_RESOLVER_V2", "shadow")
        for path in _SAMPLES:
            text = path.read_text(errors="ignore")
            out = resolve_genre(text)
            assert out["primary"] == _resolve_genre_v1(text)["primary"], path.name
            assert out["confidence"] == _resolve_genre_v1(text)["confidence"]

    def test_shadow_verdict_rides_along(self, monkeypatch):
        monkeypatch.setenv("GENRE_RESOLVER_V2", "shadow")
        out = resolve_genre("The matter is settled beyond dispute. " * 30)
        assert "shadow_primary" in out
        assert "shadow_confidence" in out

    def test_off_carries_no_shadow_keys(self, monkeypatch):
        monkeypatch.setenv("GENRE_RESOLVER_V2", "off")
        out = resolve_genre("The matter is settled beyond dispute. " * 30)
        assert "shadow_primary" not in out


class TestOnUsesV2:
    def test_on_returns_the_v2_verdict(self, monkeypatch):
        monkeypatch.setenv("GENRE_RESOLVER_V2", "on")
        from original.context import genre_v2

        text = "The matter is settled beyond dispute. " * 30
        assert resolve_genre(text)["primary"] == genre_v2.resolve(text)["primary"]

    def test_on_abstains_where_v1_said_correspondence(self, monkeypatch):
        text = "The matter is settled beyond dispute. " * 30
        monkeypatch.setenv("GENRE_RESOLVER_V2", "off")
        assert resolve_genre(text)["primary"] == "correspondence"
        monkeypatch.setenv("GENRE_RESOLVER_V2", "on")
        assert resolve_genre(text)["primary"] == GENRE_UNKNOWN
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/context/test_genre_dispatch.py -q`
Expected: FAIL — `ImportError: cannot import name '_resolve_genre_v1'`

- [ ] **Step 3: Write minimal implementation**

In `original/context/resolvers.py`: rename `def resolve_genre(` to `def _resolve_genre_v1(`, leaving its body untouched. Then add immediately after it:

```python
def resolve_genre(text: str, citation_data: CitationData | None = None) -> dict[str, Any]:
    """
    Genre resolution, dispatched on GENRE_RESOLVER_V2.

    off (default) — v1 rules, byte-identical to every release before this one.
    shadow        — v2 computed and attached as shadow_primary /
                    shadow_confidence; `primary` still comes from v1, so every
                    consumer is unaffected. One INFO line per call carries the
                    pair, because students_baseline.py persists only `primary`
                    and the label-shift distribution has to be recoverable
                    from production logs.
    on            — v2's verdict.

    v2 abstains (GENRE_UNKNOWN) where v1 fell through to "correspondence".
    See docs/superpowers/specs/2026-08-08-genre-resolution-design.md.
    """
    from .genre_mode import resolve_mode

    mode = resolve_mode()
    if mode == "off":
        return _resolve_genre_v1(text, citation_data)

    from .genre_v2 import resolve as _resolve_v2

    v2 = _resolve_v2(text, citation_data)
    if mode == "on":
        return v2

    v1 = _resolve_genre_v1(text, citation_data)
    log.info(
        "genre_shadow v1=%s v2=%s v2_confidence=%.3f",
        v1.get("primary"),
        v2.get("primary"),
        float(v2.get("confidence") or 0.0),
    )
    return {**v1, "shadow_primary": v2.get("primary"), "shadow_confidence": v2.get("confidence")}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/context/test_genre_dispatch.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add original/context/resolvers.py tests/context/test_genre_dispatch.py
git commit -m "Add GENRE_RESOLVER_V2 dispatch with shadow measurement"
```

---

## Task 4: Consumer semantics for `unknown`

**Files:**
- Modify: `original/context/baseline_match.py` (`genre_covered_by_baseline`)
- Modify: `original/store.py` (`get_genre_stats`)
- Test: `tests/context/test_genre_unknown_consumers.py`

**Interfaces:**
- Consumes: `GENRE_UNKNOWN`.
- Produces: no signature changes. `genre_covered_by_baseline` treats `unknown` as unclassified on both sides; `get_genre_stats("unknown", …)` returns `None`.

**Note for the implementer:** two of the four consumers need **no change** — `manifest.py`'s T16 mute and the T8/T13 anchor set are membership tests against literal label sets that `unknown` is not in, and `state.py:427` is the same test. Do not "fix" them. Task 4 pins that with assertions so the safety stays true if someone later edits those sets.

- [ ] **Step 1: Write the failing test**

```python
# tests/context/test_genre_unknown_consumers.py
import types

from original.constants import GENRE_UNKNOWN
from original.context.baseline_match import genre_covered_by_baseline


def _state(*genres):
    return types.SimpleNamespace(
        samples=[types.SimpleNamespace(genre=g) for g in genres]
    )


def _manifest(primary):
    return {"genre": {"primary": primary}}


class TestGenreCoveredByBaseline:
    def test_unknown_submission_is_treated_as_covered(self):
        """Ignorance must never trigger attenuation. Attenuating because we
        cannot classify the submission would change a score on the strength
        of not knowing something."""
        assert genre_covered_by_baseline(_manifest(GENRE_UNKNOWN), _state("sermon")) is True

    def test_baseline_of_only_unknowns_is_treated_as_covered(self):
        assert genre_covered_by_baseline(
            _manifest("sermon"), _state(GENRE_UNKNOWN, GENRE_UNKNOWN)
        ) is True

    def test_confident_mismatch_is_still_reported(self):
        """The gate must keep firing when it genuinely knows both sides."""
        assert genre_covered_by_baseline(_manifest("sermon"), _state("creative_fiction")) is False

    def test_confident_match_is_covered(self):
        assert genre_covered_by_baseline(_manifest("sermon"), _state("sermon")) is True

    def test_unknown_baselines_are_ignored_not_counted_as_a_genre(self):
        """A baseline of {unknown, sermon} must behave as {sermon}."""
        assert genre_covered_by_baseline(
            _manifest("creative_fiction"), _state(GENRE_UNKNOWN, "sermon")
        ) is False


class TestPoolingExcludesUnknown:
    def test_get_genre_stats_refuses_the_unknown_pool(self):
        """Pooling 'we don't know' samples rebuilds correspondence under a new
        name: one bucket holding every genre, with a prior estimated from an
        arbitrary mixture."""
        from original import store

        assert store.get_genre_stats(GENRE_UNKNOWN, tenant="demo", exclude_student_id=None) is None


class TestUntouchedConsumersStaySafe:
    def test_unknown_does_not_mute_tier16(self):
        from original.constants import GENRE_LABELS
        assert "creative_fiction" in GENRE_LABELS
        assert GENRE_UNKNOWN != "creative_fiction"

    def test_unknown_does_not_expand_the_anchor_set(self):
        from original.context.manifest import _PROSODIC_ANCHOR_GENRES
        assert GENRE_UNKNOWN not in _PROSODIC_ANCHOR_GENRES
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/context/test_genre_unknown_consumers.py -q`
Expected: FAIL — `test_unknown_submission_is_treated_as_covered` passes incidentally, but `test_unknown_baselines_are_ignored_not_counted_as_a_genre` and `test_get_genre_stats_refuses_the_unknown_pool` FAIL.

- [ ] **Step 3: Write minimal implementation**

In `original/context/baseline_match.py`, replace the body of `genre_covered_by_baseline` after the docstring:

```python
    from ..constants import GENRE_UNKNOWN

    sub_genre = _extract_sub_genre(manifest)
    # GENRE_UNKNOWN is the v2 resolver's abstention, not a genre. Treating it
    # as one would let "we could not classify this" attenuate a real score.
    if sub_genre is None or sub_genre == GENRE_UNKNOWN:
        return True
    samples = getattr(state, "samples", None) or []
    known_genres = {
        s.genre
        for s in samples
        if getattr(s, "genre", None) is not None and s.genre != GENRE_UNKNOWN
    }
    if not known_genres:
        return True
    return sub_genre in known_genres
```

In `original/store.py`, at the top of `get_genre_stats`'s body (after the docstring):

```python
    from .constants import GENRE_UNKNOWN

    # GENRE_UNKNOWN is an abstention, not a genre. Pooling every unclassified
    # sample together would rebuild the "correspondence" dumping ground under
    # a new name and estimate a prior from an arbitrary mixture of genres.
    if genre == GENRE_UNKNOWN:
        return None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/context/test_genre_unknown_consumers.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add original/context/baseline_match.py original/store.py tests/context/test_genre_unknown_consumers.py
git commit -m "Treat the unknown genre as an abstention in every consumer"
```

---

## Task 5: Shadow measurement script and Stage 1 docs

**Files:**
- Create: `validation/genre_2026-08/measure_shadow.py`
- Modify: `CLAUDE.md` (flag table), `validation/README.md`
- Test: `tests/context/test_genre_shadow_measure.py`

**Interfaces:**
- Produces: `measure_shadow.summarise(paths) -> dict` with keys `n`, `v1_distribution`, `v2_distribution`, `abstention_rate`, `shift_matrix`.

- [ ] **Step 1: Write the failing test**

```python
# tests/context/test_genre_shadow_measure.py
import importlib.util
from pathlib import Path

_SPEC = importlib.util.spec_from_file_location(
    "measure_shadow", Path("validation/genre_2026-08/measure_shadow.py")
)


def _module():
    mod = importlib.util.module_from_spec(_SPEC)
    _SPEC.loader.exec_module(mod)
    return mod


class TestSummarise:
    def test_reports_abstention_rate_and_both_distributions(self):
        m = _module()
        paths = sorted(Path("validation/corpus").glob("seminary_*.txt"))[:6]
        out = m.summarise(paths)
        assert out["n"] == len(paths)
        assert 0.0 <= out["abstention_rate"] <= 1.0
        assert sum(out["v1_distribution"].values()) == out["n"]
        assert sum(out["v2_distribution"].values()) == out["n"]

    def test_shift_matrix_accounts_for_every_document(self):
        m = _module()
        paths = sorted(Path("validation/corpus").glob("seminary_*.txt"))[:6]
        out = m.summarise(paths)
        assert sum(out["shift_matrix"].values()) == out["n"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/context/test_genre_shadow_measure.py -q`
Expected: FAIL — the file does not exist.

- [ ] **Step 3: Write minimal implementation**

Create `validation/genre_2026-08/measure_shadow.py`:

```python
"""
What would GENRE_RESOLVER_V2 change? Runs v1 and v2 over a corpus and reports
the label-shift matrix and the abstention rate.

Run:
    .venv/bin/python validation/genre_2026-08/measure_shadow.py

The abstention rate is the number that decides whether Stage 2's class set is
right for the traffic it will see. On the committed corpora it is expected to
be high (v1 puts 86% of documents in the terminal else); on real student
submissions it is unknown until shadow runs in the pilot.
"""
from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_ROOT))

from original.constants import GENRE_UNKNOWN  # noqa: E402
from original.context import genre_v2  # noqa: E402
from original.context.resolvers import _resolve_genre_v1  # noqa: E402


def summarise(paths) -> dict:
    v1_counts: Counter = Counter()
    v2_counts: Counter = Counter()
    shift: Counter = Counter()
    n = 0
    for path in paths:
        text = Path(path).read_text(errors="ignore")
        a = _resolve_genre_v1(text).get("primary")
        b = genre_v2.resolve(text).get("primary")
        v1_counts[a] += 1
        v2_counts[b] += 1
        shift[f"{a}->{b}"] += 1
        n += 1
    return {
        "n": n,
        "v1_distribution": dict(v1_counts),
        "v2_distribution": dict(v2_counts),
        "abstention_rate": (v2_counts[GENRE_UNKNOWN] / n) if n else 0.0,
        "shift_matrix": dict(shift),
    }


def main() -> None:
    paths = sorted((_ROOT / "validation" / "corpus").glob("*.txt"))
    paths += sorted((_ROOT / "validation" / "public_authors" / "corpus").rglob("*.txt"))
    out = summarise(paths)
    print(f"documents: {out['n']}")
    print(f"abstention rate (v2): {out['abstention_rate']:.1%}\n")
    print("v1:", dict(sorted(out["v1_distribution"].items(), key=lambda kv: -kv[1])))
    print("v2:", dict(sorted(out["v2_distribution"].items(), key=lambda kv: -kv[1])))
    print("\ntop shifts:")
    for k, v in sorted(out["shift_matrix"].items(), key=lambda kv: -kv[1])[:12]:
        print(f"  {k:48s} {v}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run test to verify it passes, then run the script**

Run: `.venv/bin/python -m pytest tests/context/test_genre_shadow_measure.py -q`
Expected: PASS

Run: `.venv/bin/python validation/genre_2026-08/measure_shadow.py`
Expected: prints an abstention rate near 90% and a dominant `correspondence->unknown` shift. Record the actual number — Stage 2 Task 12 quotes it.

- [ ] **Step 5: Add the flag-table row and commit**

Add to `CLAUDE.md`'s Environment Flags table:

```markdown
| `GENRE_RESOLVER_V2` | `off` | Genre resolver with abstention. `off` is byte-identical to the v1 rules (tested over the committed corpora). ⚠️ **`on` can change scores**: genre drives tier-16 muting and T8/T13 anchor expansion (`context/manifest.py:223,225`, `quantum/state.py:427`) and is a Bayesian prior pooling key (`store.py:get_genre_stats`). v1 sorts 86% of all prose into rule 8's terminal `else` (`correspondence`) and never produces 4 of its 8 labels — measured 2026-08-08 over 356 committed documents. v2 returns `unknown` instead of inventing a label, and every consumer treats `unknown` as "do nothing": no mute, base anchors `{4,6}`, excluded from pooling, and never a reason to attenuate. `shadow` attaches `shadow_primary`/`shadow_confidence` and logs one `genre_shadow v1=… v2=…` INFO line per call without touching `primary`. **Run `shadow` first** — the abstention rate on real submissions is what decides whether the Stage 2 class set fits student writing. See `docs/superpowers/specs/2026-08-08-genre-resolution-design.md`. |
```

```bash
git add validation/genre_2026-08/measure_shadow.py tests/context/test_genre_shadow_measure.py CLAUDE.md validation/README.md
git commit -m "Add genre shadow measurement and document GENRE_RESOLVER_V2"
```

---

## Task 6: Stage 1 full-suite verification

- [ ] **Step 1: Run the full suite**

Run: `.venv/bin/python -m pytest tests/ validation/test_tier10_optional.py -q`
Expected: `0 failed`.

- [ ] **Step 2: Verify the flag-off byte-identity claim independently**

Run: `.venv/bin/python -c "
from pathlib import Path
from original.context.resolvers import resolve_genre, _resolve_genre_v1
bad = [p.name for p in sorted(Path('validation/corpus').glob('*.txt'))
       if resolve_genre(p.read_text(errors='ignore')) != _resolve_genre_v1(p.read_text(errors='ignore'))]
print('mismatches:', bad or 'NONE')"`
Expected: `mismatches: NONE`

- [ ] **Step 3: Confirm shadow does not leak into scoring**

Run: `GENRE_RESOLVER_V2=shadow .venv/bin/python -m pytest tests/quantum/ tests/context/ -q`
Expected: `0 failed`.

- [ ] **Step 4: Commit any fixes, then tag the stage**

```bash
git commit -am "Fix Stage 1 verification findings" || echo "nothing to fix"
```

---

# STAGE 2 — Discrimination

## Task 7: The codebook (committed before any labelling)

**Files:**
- Create: `validation/genre_2026-08/CODEBOOK.md`

**Note:** this task exists to be committed **on its own, before Task 8**. Git history is the evidence that labels were not fitted to a classifier's behaviour. Do not combine this commit with any other.

- [ ] **Step 1: Write the codebook**

`validation/genre_2026-08/CODEBOOK.md` must contain, for each of the five classes (`academic_exegesis`, `scholarly_essay`, `sermon`, `personal_essay`, `creative_fiction`): a one-paragraph definition, three inclusion criteria, three exclusion criteria, two named worked examples from the committed corpora, and the nearest-neighbour class it is most likely to be confused with plus the deciding test.

It must also record these two judgement calls explicitly:

- **Plato is labelled `creative_fiction`** under the dialogue criterion. Socratic dialogue is philosophical argument in dramatic form and a reasonable labeller could call it `scholarly_essay`. Because Plato is 263 of the available documents, this single decision would dominate class balance — so Plato's contribution is capped at the size of the next-largest class (Task 8), and Task 12 reports sensitivity to the choice.
- **`blog_post` and `correspondence` are not labelled at all.** No corpus evidence exists for either; they stay in `GENRE_LABELS` for stored-value compatibility and are never predicted.

- [ ] **Step 2: Commit — alone**

```bash
git add validation/genre_2026-08/CODEBOOK.md
git commit -m "Add the genre labelling codebook

Committed before any document is labelled and before the classifier exists,
so the git history is the evidence that labels were not fitted to a model's
behaviour. The labeller and the implementer are the same agent, which makes
that ordering the only structural guarantee available."
```

---

## Task 8: The labelled corpus (committed before the classifier)

**Files:**
- Create: `validation/genre_2026-08/build_labels.py`, `validation/genre_2026-08/labels.json`
- Test: `tests/validation/test_genre_labels.py`

**Interfaces:**
- Produces: `labels.json` — `{"version": 1, "codebook_sha256": str, "entries": [{"path": str, "author": str, "label": str, "split": "derivation"|"holdout"}]}`.

- [ ] **Step 1: Write the failing test**

```python
# tests/validation/test_genre_labels.py
import hashlib
import json
from collections import Counter
from pathlib import Path

import pytest

_LABELS = Path("validation/genre_2026-08/labels.json")
_CODEBOOK = Path("validation/genre_2026-08/CODEBOOK.md")
_CLASSES = {"academic_exegesis", "scholarly_essay", "sermon", "personal_essay", "creative_fiction"}


@pytest.fixture(scope="module")
def labels():
    return json.loads(_LABELS.read_text())


class TestLabelIntegrity:
    def test_every_label_is_in_the_class_set(self, labels):
        assert {e["label"] for e in labels["entries"]} <= _CLASSES

    def test_every_referenced_file_exists(self, labels):
        missing = [e["path"] for e in labels["entries"] if not Path(e["path"]).exists()]
        assert missing == []

    def test_labels_pin_the_codebook_they_were_written_against(self, labels):
        """If the codebook changes, the labels must be re-examined rather
        than silently inheriting a new definition."""
        actual = hashlib.sha256(_CODEBOOK.read_bytes()).hexdigest()
        assert labels["codebook_sha256"] == actual


class TestSplitDiscipline:
    def test_the_split_is_author_disjoint(self, labels):
        """Chesterton appears as both essayist and novelist. A document-level
        split would let the model score well by recognising the author."""
        by_split = {}
        for e in labels["entries"]:
            by_split.setdefault(e["split"], set()).add(e["author"])
        assert by_split["derivation"].isdisjoint(by_split["holdout"])

    def test_both_splits_are_non_empty(self, labels):
        counts = Counter(e["split"] for e in labels["entries"])
        assert counts["derivation"] > 0 and counts["holdout"] > 0

    def test_no_class_is_carried_by_a_single_author(self, labels):
        """A class evidenced by one author is an author detector, not a genre
        detector."""
        authors_per_class = {}
        for e in labels["entries"]:
            authors_per_class.setdefault(e["label"], set()).add(e["author"])
        thin = {k: v for k, v in authors_per_class.items() if len(v) < 2}
        assert thin == {}, f"single-author classes: {thin}"

    def test_no_class_exceeds_half_the_corpus(self, labels):
        """Plato alone could supply 263 creative_fiction documents."""
        counts = Counter(e["label"] for e in labels["entries"])
        n = sum(counts.values())
        over = {k: v for k, v in counts.items() if v > n / 2}
        assert over == {}, f"class dominates the corpus: {over}"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/validation/test_genre_labels.py -q`
Expected: FAIL — `labels.json` does not exist.

- [ ] **Step 3: Build the labelled set**

Write `build_labels.py` to enumerate candidate documents by provenance group, then assign labels **by reading the codebook criteria against each group**, capping any single group's contribution at the size of the next-largest class. Assign `split` by author: hold out roughly a third of the authors in each class, chosen deterministically by sorted author name so the split is reproducible and not chosen to flatter a result.

Every group's label assignment must be recorded in `build_labels.py` as an explicit mapping with a one-line justification per group referencing the codebook criterion it satisfies — not inferred at runtime.

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/validation/test_genre_labels.py -q`
Expected: PASS

- [ ] **Step 5: Commit — before any classifier code exists**

```bash
git add validation/genre_2026-08/build_labels.py validation/genre_2026-08/labels.json tests/validation/test_genre_labels.py
git commit -m "Add the hand-labelled genre corpus

Committed before genre_v2 gains any model code. The split is author-disjoint,
no class rests on a single author, and no class exceeds half the corpus."
```

---

## Task 9: Signal extraction

**Files:**
- Modify: `original/context/genre_v2.py`
- Test: `tests/context/test_genre_signals.py`

**Interfaces:**
- Produces: `genre_v2.SIGNAL_ORDER: tuple[str, ...]` (10 names) and `genre_v2.extract_signals(text, citation_data=None) -> dict[str, float]`.

- [ ] **Step 1: Write the failing test**

```python
# tests/context/test_genre_signals.py
import math

from original.context import genre_v2


class TestSignalContract:
    def test_signal_order_is_a_fixed_ten(self):
        assert genre_v2.SIGNAL_ORDER == (
            "mean_sentence_length", "sentence_length_dispersion", "first_person_ratio",
            "second_person_ratio", "dialogue_density", "citation_density",
            "imperative_density", "signal_verb_rate", "question_rate", "mean_word_length",
        )

    def test_extract_returns_every_signal_finite(self):
        out = genre_v2.extract_signals("A sentence. Another sentence here. " * 20)
        assert set(out) == set(genre_v2.SIGNAL_ORDER)
        assert all(math.isfinite(v) for v in out.values())

    def test_empty_text_is_all_zeros_not_a_crash(self):
        out = genre_v2.extract_signals("")
        assert all(v == 0.0 for v in out.values())


class TestSignalsDiscriminate:
    def test_dialogue_density_separates_narrative_from_exposition(self):
        narrative = 'He said, "we go now." She replied, "not yet." ' * 15
        exposition = "The argument depends upon the premise stated above. " * 15
        assert (genre_v2.extract_signals(narrative)["dialogue_density"]
                > genre_v2.extract_signals(exposition)["dialogue_density"])

    def test_second_person_separates_address_from_description(self):
        address = "You must consider your own heart before you judge. " * 15
        description = "The heart of the matter is seldom considered at all. " * 15
        assert (genre_v2.extract_signals(address)["second_person_ratio"]
                > genre_v2.extract_signals(description)["second_person_ratio"])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/context/test_genre_signals.py -q`
Expected: FAIL — `AttributeError: module 'original.context.genre_v2' has no attribute 'SIGNAL_ORDER'`

- [ ] **Step 3: Write minimal implementation**

Append to `original/context/genre_v2.py`:

```python
SIGNAL_ORDER: tuple[str, ...] = (
    "mean_sentence_length",
    "sentence_length_dispersion",
    "first_person_ratio",
    "second_person_ratio",
    "dialogue_density",
    "citation_density",
    "imperative_density",
    "signal_verb_rate",
    "question_rate",
    "mean_word_length",
)

# Second-person pronouns are a strong homiletic signal ("you must…") and are
# computed here rather than added to tier3: ALL_FEATURE_CODES ordering is
# frozen, and genre signals are not pipeline features.
_SECOND_PERSON = {"you", "your", "yours", "yourself", "yourselves", "thou", "thee", "thy", "thine"}


def extract_signals(text: str, citation_data=None) -> dict[str, float]:
    """Ten interpretable signals, all already computable from the existing
    pipeline. Returns zeros for empty input rather than raising."""
    import statistics

    from ..features.preprocess import preprocess
    from ..features.tier1 import TextDoc
    from ..features.tier3 import first_person_ratio, imperative_density
    from .resolvers import _tokenize

    text = text or ""
    if not text.strip():
        return dict.fromkeys(SIGNAL_ORDER, 0.0)

    doc = TextDoc(text)
    word_count = max(1, doc.word_count)
    sentences = doc.sentences or [text]
    lengths = [len(_tokenize(s)) for s in sentences] or [0]
    if citation_data is None:
        _, citation_data = preprocess(text)

    tokens = [t.lower() for t in _tokenize(text)]
    cite_total = (
        citation_data.paren_citation_count
        + citation_data.footnote_marker_count
        + citation_data.ibid_count
    )
    n_dialogue = len(_DIALOGUE_RE.findall(text))

    return {
        "mean_sentence_length": float(statistics.fmean(lengths)),
        "sentence_length_dispersion": float(statistics.pstdev(lengths)) if len(lengths) > 1 else 0.0,
        "first_person_ratio": float(first_person_ratio(doc)),
        "second_person_ratio": sum(1 for t in tokens if t in _SECOND_PERSON) / word_count,
        "dialogue_density": n_dialogue / len(sentences),
        "citation_density": (cite_total / word_count) * 100.0,
        "imperative_density": float(imperative_density(doc)),
        "signal_verb_rate": (sum(citation_data.signal_verb_counts.values()) / word_count) * 100.0,
        "question_rate": sum(1 for s in sentences if s.strip().endswith("?")) / len(sentences),
        "mean_word_length": sum(len(t) for t in tokens) / max(1, len(tokens)),
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/context/test_genre_signals.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add original/context/genre_v2.py tests/context/test_genre_signals.py
git commit -m "Add genre signal extraction"
```

---

## Task 10: Offline derivation → JSON artifact

**Files:**
- Create: `validation/genre_2026-08/derive.py`, `original/data/genre_model_v1.json`
- Test: `tests/validation/test_genre_artifact.py`

**Interfaces:**
- Produces: artifact JSON with keys `schema_version` (1), `signal_order` (list, must equal `SIGNAL_ORDER`), `classes` (list[str]), `mean` / `scale` (len-10 lists), `coef` (n_classes × 10), `intercept` (n_classes), `reference_signals` (≥3 × 10), `reference_probabilities`, `confidence_min`, `codebook_sha256`, `labels_sha256`.

**Why JSON and not joblib** (a deliberate deviation from `style_authorship.py`): the artifact is committed to git, so no pickle; inference becomes pure numpy, so `genre_v2` gains **no sklearn runtime dependency** — sklearn is absent from the base `requirements.txt`; and the coefficients stay diffable in review.

- [ ] **Step 1: Write the failing test**

```python
# tests/validation/test_genre_artifact.py
import json
from pathlib import Path

import pytest

from original.context import genre_v2

_ARTIFACT = Path("original/data/genre_model_v1.json")


@pytest.fixture(scope="module")
def artifact():
    return json.loads(_ARTIFACT.read_text())


class TestArtifactShape:
    def test_schema_version_is_pinned(self, artifact):
        assert artifact["schema_version"] == 1

    def test_signal_order_matches_the_extractor(self, artifact):
        """A reordered extractor silently feeds the model shuffled columns."""
        assert tuple(artifact["signal_order"]) == genre_v2.SIGNAL_ORDER

    def test_coefficient_matrix_matches_classes_and_signals(self, artifact):
        assert len(artifact["coef"]) == len(artifact["classes"])
        assert all(len(row) == len(genre_v2.SIGNAL_ORDER) for row in artifact["coef"])
        assert len(artifact["intercept"]) == len(artifact["classes"])

    def test_scaler_is_the_right_width_and_has_no_zero_scale(self, artifact):
        assert len(artifact["mean"]) == len(genre_v2.SIGNAL_ORDER)
        assert len(artifact["scale"]) == len(genre_v2.SIGNAL_ORDER)
        assert all(s > 0 for s in artifact["scale"])

    def test_classes_exclude_blog_post_and_correspondence(self, artifact):
        assert "blog_post" not in artifact["classes"]
        assert "correspondence" not in artifact["classes"]

    def test_reference_predictions_are_present_for_drift_detection(self, artifact):
        assert len(artifact["reference_signals"]) >= 3
        assert len(artifact["reference_probabilities"]) == len(artifact["reference_signals"])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/validation/test_genre_artifact.py -q`
Expected: FAIL — artifact does not exist.

- [ ] **Step 3: Write the derivation script and run it**

`derive.py` loads `labels.json`, extracts signals for the **derivation split only**, standardises, fits `LogisticRegression(max_iter=2000, class_weight="balanced")`, selects `confidence_min` as the smallest threshold on the derivation split at which **minimum per-class precision ≥ 0.80**, and writes the artifact. `reference_signals` are three derivation rows chosen deterministically (first row of each of the three largest classes) with their predicted probabilities, so the loader can detect numeric drift.

The hold-out split must not be read by this script at all. Add an assertion that fails loudly if a hold-out path is touched.

Run: `.venv/bin/python validation/genre_2026-08/derive.py`

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/validation/test_genre_artifact.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add validation/genre_2026-08/derive.py original/data/genre_model_v1.json tests/validation/test_genre_artifact.py
git commit -m "Derive the genre classifier and commit its JSON artifact"
```

---

## Task 11: Fail-closed loader and model inference

**Files:**
- Modify: `original/context/genre_v2.py`
- Test: `tests/context/test_genre_model.py`

**Interfaces:**
- Produces: `genre_v2.predict(text, citation_data=None) -> dict` and `genre_v2._load_artifact()`. `resolve()` uses the model when it loads and falls back to **abstention**, never to the rules.

- [ ] **Step 1: Write the failing test**

```python
# tests/context/test_genre_model.py
import json

import pytest

from original.constants import GENRE_UNKNOWN
from original.context import genre_v2


@pytest.fixture(autouse=True)
def _reset():
    genre_v2._reset_artifact_for_test()
    yield
    genre_v2._reset_artifact_for_test()


class TestFailClosed:
    def test_missing_artifact_abstains_and_does_not_fall_back_to_rules(self, monkeypatch, tmp_path):
        """Silently swapping mechanisms is how a measurement stops meaning
        what its label says."""
        monkeypatch.setenv("GENRE_MODEL_PATH", str(tmp_path / "nope.json"))
        out = genre_v2.predict("Any text at all. " * 20)
        assert out["primary"] == GENRE_UNKNOWN
        assert out["confidence"] == 0.0

    @pytest.mark.parametrize("mutation", ["schema_version", "signal_order", "reference"])
    def test_drifted_artifact_is_refused(self, monkeypatch, tmp_path, mutation):
        good = json.loads(open("original/data/genre_model_v1.json").read())
        if mutation == "schema_version":
            good["schema_version"] = 99
        elif mutation == "signal_order":
            good["signal_order"] = list(reversed(good["signal_order"]))
        else:
            good["reference_probabilities"] = [
                [p + 0.5 for p in row] for row in good["reference_probabilities"]
            ]
        path = tmp_path / "drifted.json"
        path.write_text(json.dumps(good))
        monkeypatch.setenv("GENRE_MODEL_PATH", str(path))
        assert genre_v2.predict("Any text. " * 20)["primary"] == GENRE_UNKNOWN


class TestInference:
    def test_probabilities_sum_to_one(self):
        p = genre_v2._class_probabilities(genre_v2.extract_signals("Prose here. " * 30))
        assert abs(sum(p.values()) - 1.0) < 1e-9

    def test_low_confidence_abstains(self, monkeypatch):
        monkeypatch.setattr(genre_v2, "_confidence_min", lambda: 0.999)
        out = genre_v2.predict("Ambiguous prose of no clear kind. " * 20)
        assert out["primary"] == GENRE_UNKNOWN

    def test_a_confident_prediction_is_claimed(self, monkeypatch):
        monkeypatch.setattr(genre_v2, "_confidence_min", lambda: 0.0)
        out = genre_v2.predict("He said, “we go now.” She replied nothing. " * 20)
        assert out["primary"] != GENRE_UNKNOWN
        assert 0.0 < out["confidence"] <= 1.0

    def test_no_sklearn_import_at_inference(self, monkeypatch):
        """sklearn is not in the base requirements.txt."""
        import sys
        monkeypatch.setitem(sys.modules, "sklearn", None)
        genre_v2.predict("Prose. " * 30)  # must not raise
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/context/test_genre_model.py -q`
Expected: FAIL — `_reset_artifact_for_test` does not exist.

- [ ] **Step 3: Write minimal implementation**

Add to `genre_v2.py`: module-level `_UNLOADED/_READY/_FAILED` state with a lock (mirroring `style_authorship.py`), `_artifact_path()` reading `GENRE_MODEL_PATH` with a packaged default, `_load_artifact()` validating schema version, signal order, scaler width, non-zero scale, coefficient shape, and reference-prediction drift (`max|got - expected| > 1e-8` → fail), `_class_probabilities()` doing `softmax((x - mean)/scale @ coef.T + intercept)` in numpy, `_confidence_min()`, `predict()`, and `_reset_artifact_for_test()`. On any failure log a warning and return abstention.

Then change `resolve()` so that after the markup rule it calls `predict()` rather than the rule tree. Keep the rule tree as `_resolve_by_rules()` for Stage-1-only use and for the shadow comparison in Task 12.

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/context/test_genre_model.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add original/context/genre_v2.py tests/context/test_genre_model.py
git commit -m "Add the fail-closed genre model loader and inference"
```

---

## Task 12: Hold-out evaluation and the author-shuffled control

**Files:**
- Create: `validation/genre_2026-08/evaluate.py`
- Test: `tests/validation/test_genre_evaluation.py`

**Interfaces:**
- Produces: `evaluate.evaluate_holdout() -> dict` with `per_class_precision`, `min_precision`, `abstention_rate`, `n_holdout`; `evaluate.shuffled_control(seed=1729) -> dict` with `accuracy`, `chance`.

- [ ] **Step 1: Write the failing test**

```python
# tests/validation/test_genre_evaluation.py
import importlib.util
from pathlib import Path

import pytest

_SPEC = importlib.util.spec_from_file_location(
    "genre_evaluate", Path("validation/genre_2026-08/evaluate.py")
)


@pytest.fixture(scope="module")
def mod():
    m = importlib.util.module_from_spec(_SPEC)
    _SPEC.loader.exec_module(m)
    return m


class TestHoldout:
    def test_reports_per_class_precision_and_abstention(self, mod):
        out = mod.evaluate_holdout()
        assert out["n_holdout"] > 0
        assert 0.0 <= out["abstention_rate"] <= 1.0
        assert out["min_precision"] == min(out["per_class_precision"].values())

    def test_precision_is_computed_over_claimed_labels_only(self, mod):
        """Abstentions are not wrong answers; counting them as errors would
        punish the honesty the design is built on."""
        out = mod.evaluate_holdout()
        assert "unknown" not in out["per_class_precision"]


class TestShuffledControl:
    def test_permuted_genre_labels_collapse_accuracy(self, mod):
        """The direct test for 'this is secretly an author classifier'."""
        out = mod.shuffled_control(seed=1729)
        assert out["accuracy"] <= out["chance"] + 0.10
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/validation/test_genre_evaluation.py -q`
Expected: FAIL — file does not exist.

- [ ] **Step 3: Write the evaluator**

`evaluate_holdout()` scores the hold-out split through `genre_v2.predict`, computing precision per claimed class (`correct claims / total claims`), the minimum across classes, and the abstention rate. `shuffled_control(seed)` permutes genre labels **across authors** with a fixed seed, re-fits by calling `derive.fit_from_entries`, re-scores, and returns accuracy against `chance = 1 / n_classes`.

- [ ] **Step 4: Run test to verify it passes, and record the numbers**

Run: `.venv/bin/python validation/genre_2026-08/evaluate.py`
Expected: prints per-class precision, minimum precision, abstention rate, and shuffled-control accuracy. **Record all four — Task 13's gate quotes them.** If minimum precision is below 0.80, raise `confidence_min` in `derive.py`, re-derive, and re-run; do **not** adjust anything against the hold-out numbers other than reporting them.

- [ ] **Step 5: Commit**

```bash
git add validation/genre_2026-08/evaluate.py tests/validation/test_genre_evaluation.py
git commit -m "Add genre hold-out evaluation and the author-shuffled control"
```

---

## Task 13: Gate G8 and its falsifiability contract

**Files:**
- Modify: `validation/calibration_gate.py`, `validation/gate_contracts.py`
- Test: `tests/test_calibration_gate.py`, `tests/test_gate_falsifiability.py`

**Interfaces:**
- Produces: `evaluate_g8_genre_discrimination(min_class_precision, abstention_rate, shuffled_accuracy, n_classes=5, n_holdout=None, informational=None) -> GateResult`.

- [ ] **Step 1: Write the failing test**

```python
# append to tests/test_calibration_gate.py
class TestG8GenreDiscrimination:
    def test_passes_when_all_three_legs_clear(self):
        r = calibration_gate.evaluate_g8_genre_discrimination(0.85, 0.40, 0.22)
        assert r.verdict == "pass"
        assert r.name == "G8"

    def test_fails_on_a_single_weak_class(self):
        """Minimum per-class precision, not macro-average: an average lets one
        class sit at 0.4 while the mean clears the bar, and the consequence of
        a wrong label is per-class."""
        r = calibration_gate.evaluate_g8_genre_discrimination(0.55, 0.40, 0.22)
        assert r.verdict == "fail"
        assert r.detail["precision_leg_passed"] is False

    def test_fails_when_it_abstains_on_almost_everything(self):
        """Perfect precision by classifying nothing is the degenerate win."""
        r = calibration_gate.evaluate_g8_genre_discrimination(1.0, 0.95, 0.22)
        assert r.verdict == "fail"
        assert r.detail["abstention_leg_passed"] is False

    def test_fails_when_the_shuffled_control_still_predicts(self):
        r = calibration_gate.evaluate_g8_genre_discrimination(0.85, 0.40, 0.75)
        assert r.verdict == "fail"
        assert r.detail["control_leg_passed"] is False

    def test_bars_are_inclusive_at_the_spec_values(self):
        assert calibration_gate.evaluate_g8_genre_discrimination(0.80, 0.50, 0.30).verdict == "pass"

    def test_a_thin_holdout_downgrades_a_pass(self):
        r = calibration_gate.evaluate_g8_genre_discrimination(0.85, 0.40, 0.22, n_holdout=8)
        assert r.verdict == "uninformative"

    def test_a_thin_holdout_never_upgrades_a_failure(self):
        r = calibration_gate.evaluate_g8_genre_discrimination(0.20, 0.99, 0.90, n_holdout=8)
        assert r.verdict == "fail"
```

```python
# append to tests/test_gate_falsifiability.py, inside TestWitnessesFailForTheRightReason
    def test_g8_fails_because_one_class_is_weak_not_because_of_the_other_legs(self):
        result = GATE_CONTRACTS["evaluate_g8_genre_discrimination"].failure_witness()
        assert result.detail["precision_leg_passed"] is False
        assert result.detail["abstention_leg_passed"] is True
        assert result.detail["control_leg_passed"] is True

    def test_g8_label_destruction_is_the_shuffled_control(self):
        result = GATE_CONTRACTS["evaluate_g8_genre_discrimination"].label_destruction()
        assert result.verdict != "pass"
        assert result.detail["control_leg_passed"] is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_calibration_gate.py -k G8 tests/test_gate_falsifiability.py -q`
Expected: FAIL — `evaluate_g8_genre_discrimination` does not exist, and `test_no_unregistered_gates` fails once it does.

- [ ] **Step 3: Write minimal implementation**

Add `_G8_PRECISION_BAR = 0.80`, `_G8_ABSTENTION_BAR = 0.50`, `_G8_CONTROL_MARGIN = 0.10`, a `_G8_CRITERION` string naming all three, and the evaluator: three-leg conjunction, `verdict = "fail"` if any leg misses, otherwise `pass`, downgraded to `uninformative` for a would-be pass when `n_holdout` is supplied and the Wilson interval on `min_class_precision` straddles 0.80 (reuse `validation.power.bar_decidable`, requiring `"above"`). Only a would-be pass may be downgraded.

Register in `gate_contracts.py`: failure witness `evaluate_g8_genre_discrimination(min_class_precision=0.55, abstention_rate=0.40, shuffled_accuracy=0.22)` — isolates the precision leg. Label destruction `evaluate_g8_genre_discrimination(min_class_precision=0.85, abstention_rate=0.40, shuffled_accuracy=0.85)` — under permuted genre labels a model that still predicts confidently is recognising authors; a shuffled accuracy far above chance can never pass. Pass every argument by keyword.

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_calibration_gate.py tests/test_gate_falsifiability.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add validation/calibration_gate.py validation/gate_contracts.py tests/test_calibration_gate.py tests/test_gate_falsifiability.py
git commit -m "Add calibration gate G8 (genre discrimination)"
```

---

## Task 14: Wire G8 into run_all, update docs, full verification

**Files:**
- Modify: `validation/calibration_gate.py` (`run_all`, `render` header, `main` thresholds), `CLAUDE.md`, `validation/README.md`, `original/context/weighting.py`

- [ ] **Step 1: Wire G8 into run_all**

Add after G7, in the same machinery-error wrapper style. G8's inputs come from `validation/genre_2026-08/evaluate.py`; when `labels.json` or the artifact is absent, return a loud uninformative skip naming the regeneration command — the same convention `_g7_skip_result` uses. Update the `render()` header to `(G1-G8)` and add `g8_min_class_precision`, `g8_abstention`, `g8_control` to `main`'s thresholds dict.

- [ ] **Step 2: Update the stale claims in weighting.py and CLAUDE.md**

`original/context/weighting.py:76-91` states that `resolve_genre` cannot discriminate and that the tier attenuation is blocked on it. Replace with the current position: v2 abstains rather than mislabelling; the attenuation gate now fires only on a confident mismatch; the tier set (2/3/9/10) remains independently unvalidated, so `GENRE_INVARIANT_WEIGHTS_ENABLED` stays off pending its own measurement.

In `CLAUDE.md`, update the `GENRE_INVARIANT_WEIGHTS_ENABLED` row to say the classifier blocker is resolved and name what still blocks the flag.

- [ ] **Step 3: Run the full suite**

Run: `.venv/bin/python -m pytest tests/ validation/test_tier10_optional.py -q`
Expected: `0 failed`.

- [ ] **Step 4: Run the gate suite**

Run: `.venv/bin/python -m validation.calibration_gate --strict`
Expected: G8 reports a real verdict (its corpus IS committed, unlike G7's). Record it.

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "Wire G8 into the gate suite and refresh the genre documentation"
```

---

## Self-Review Notes

**Spec coverage:** flag/dispatcher → T1, T3. Abstention → T2. Consumer semantics (all four) → T4. Shadow measurement → T5. Codebook → T7. Labels, author-disjoint split, class balance → T8. Signals → T9. Model + confidence floor → T10. Fail-closed loader → T11. Hold-out + author-shuffled control → T12. G8 + witness → T13. Byte-identity → T3, T6. Docs → T5, T14.

**Known deviation from the spec:** the artifact is JSON rather than joblib. Rationale recorded in Task 10 — no pickle in git, no sklearn at inference, diffable coefficients.

**Ordering constraint:** Task 7 must be committed alone and before Task 8; Task 8 must be committed before Task 11. That ordering is the only structural evidence that labels were not fitted to the model.
