"""
tests/test_tension_arc_integration.py — Integration tests for Tension Arc Analysis.

Tests cover:
  1. analyze_tension_arc returns a valid TensionArcResult
  2. analyze_tension_arc with a student baseline_kappa
  3. update_student_baseline_kappa running-mean helper
  4. Layer7Output has tension_arc field defaulting to None
  5. score endpoint includes tension_arc in the response JSON
"""

from __future__ import annotations

import dataclasses


# ── 1. analyze_tension_arc returns a valid TensionArcResult ──────────────────


def test_analyze_tension_arc_returns_result():
    from original.tension_arc import analyze_tension_arc, TensionArcResult

    # Minimum viable text (200+ words)
    text = (
        "The doctrine of justification by faith alone stands at the heart of Reformed "
        "theology. Luther discovered that the righteousness of God spoken of in Romans "
        "is not the righteousness by which God punishes sinners but the righteousness "
        "by which He graciously acquits them through faith in Jesus Christ. This insight "
        "transformed his understanding of the gospel entirely. For centuries the church "
        "had taught that merit cooperates with grace in securing salvation, yet Luther "
        "found no such teaching in Paul's letter to the Galatians. The anathemas of "
        "the Jerusalem council in Acts 15 confirmed his reading. Whether the reformers "
        "overread Paul or recovered his authentic intention remains disputed among "
        "scholars today, though the exegetical evidence seems strongly in Luther's "
        "favour. The New Perspective on Paul, associated with Sanders, Dunn and Wright, "
        "challenges the traditional framing but does not necessarily undermine the "
        "soteriological conclusion. Justification remains a forensic declaration, not "
        "a process of moral transformation. The two must not be confused, though they "
        "always occur together in the order of salvation. Union with Christ precedes "
        "both and is the ground of each. These distinctions matter because they shape "
        "pastoral practice and the assurance believers may legitimately claim."
    )

    result = analyze_tension_arc(text, baseline_kappa=None)

    assert isinstance(result, TensionArcResult)
    assert isinstance(result.catastrophe_index, float)
    assert 0.0 <= result.catastrophe_index <= 1.0
    assert isinstance(result.tension_series, list)
    assert isinstance(result.arc_flag, str)
    assert result.arc_flag in ("authentic", "ai_typical", "review", "insufficient_length")
    assert isinstance(result.arc_flag_reason, str)
    # authenticity_signal must be None when no baseline supplied
    assert result.authenticity_signal is None


# ── 2. analyze_tension_arc with a baseline_kappa ─────────────────────────────


def test_analyze_tension_arc_with_baseline_kappa():
    from original.tension_arc import analyze_tension_arc

    text = (
        "Atonement theology has generated fierce debate across the centuries. "
        "Anselm's satisfaction theory, which dominated medieval soteriology, holds "
        "that Christ's death satisfies the honour of God violated by human sin. "
        "Abelard countered that the atonement works primarily by evoking love in "
        "the believer, not by addressing divine honour. The Reformation complicated "
        "both positions by emphasising penal substitution: Christ bore the penalty "
        "deserved by sinners, and this forensic transfer is the heart of the gospel. "
        "Contemporary theologians question whether any single theory captures the full "
        "range of New Testament atonement language. Christus Victor, the Girardian "
        "scapegoat reading, and participatory atonement models each illuminate aspects "
        "the others neglect. What remains constant across all serious treatments is the "
        "conviction that atonement is objective: something was accomplished outside and "
        "apart from us that makes reconciliation with God possible. The subjective "
        "appropriation of that reality through faith is a secondary question, however "
        "important for the life of the believer and the integrity of pastoral preaching."
    )

    result = analyze_tension_arc(text, baseline_kappa=0.45)

    assert isinstance(result.arc_flag, str)
    assert result.arc_flag in ("authentic", "ai_typical", "review", "insufficient_length")
    # When baseline_kappa is supplied, authenticity_signal should be set (or None if
    # insufficient_length triggered before reaching the signal computation)
    if result.arc_flag != "insufficient_length":
        # authenticity_signal is computed when kappa > 0 and baseline exists
        # It may still be None if catastrophe_index == 0 (single-paragraph doc)
        assert result.authenticity_signal is None or (
            isinstance(result.authenticity_signal, float)
            and 0.0 <= result.authenticity_signal <= 1.0
        )


# ── 3. update_student_baseline_kappa running-mean helper ─────────────────────


def test_update_student_baseline_kappa():
    from original.tension_arc import update_student_baseline_kappa

    # Single value → mean of one = itself
    result = update_student_baseline_kappa([], 0.5)
    assert abs(result - 0.5) < 1e-9

    # Two values → mean
    result = update_student_baseline_kappa([0.5], 0.7)
    assert 0.5 < result < 0.7

    # Many values → still a float
    result = update_student_baseline_kappa([0.5, 0.6, 0.7], 0.9)
    assert isinstance(result, float)
    # Mean of [0.5, 0.6, 0.7, 0.9] = 0.675
    assert abs(result - 0.675) < 1e-6


# ── 4. Layer7Output has tension_arc field defaulting to None ─────────────────


def test_layer7_output_has_tension_arc_field():
    from original.quantum.scoring import Layer7Output

    fields = {f.name for f in dataclasses.fields(Layer7Output)}
    assert "tension_arc" in fields

    # Verify default is None (field must not be required)
    field_defaults = {f.name: f.default for f in dataclasses.fields(Layer7Output)}
    assert field_defaults["tension_arc"] is None


# ── 5. Live response schema includes tension_arc field ───────────────────────


def test_score_response_includes_tension_arc_field():
    """
    Verifies the LIVE Pydantic response schema (original/schemas.py — the
    v1 schemas_v1 copy this used to check was deleted in WS-6 P6) exposes
    tension_arc as a nullable field. Schema-direct rather than a live API
    call, because the API requires a fully seeded DB with baselines.
    """
    from original.schemas import Layer7OutputResponse, TensionArcOut

    # tension_arc must be a nullable field on the live scoring response
    assert "tension_arc" in Layer7OutputResponse.model_fields
    annotation = Layer7OutputResponse.model_fields["tension_arc"].annotation
    assert type(None) in getattr(annotation, "__args__", ()), (
        "tension_arc must be nullable (TensionArcOut | None) — it is absent "
        "for short submissions"
    )

    # TensionArcOut must have the expected fields
    expected_fields = {
        "catastrophe_index",
        "resolution_ratio_mean",
        "resolution_ratio_std",
        "mean_tension",
        "max_tension",
        "authenticity_signal",
        "arc_flag",
        "arc_flag_reason",
        "tension_series",
        "paragraph_arcs",
    }
    assert expected_fields.issubset(set(TensionArcOut.model_fields.keys()))


# ── 6. An unreachable embedder degrades instead of failing the submission ────


def test_unreachable_embedder_degrades_to_zero_cohesion(monkeypatch, caplog):
    """A missing sentence-transformers model must never 500 a submission.

    `SentenceTransformer("all-MiniLM-L6-v2")` downloads from huggingface.co on
    first use and raises OSError when the host is unreachable and nothing is
    cached — the normal state of a CI runner or an air-gapped deploy. Only
    ImportError used to be caught, so that OSError propagated out of
    `analyze_tension_arc`, through `add_baseline`, and became a 500 on every
    baseline upload. Cohesion is an optional signal: absent weights must fall
    back to 0.0, exactly as an absent package already did.
    """
    import logging

    from original import tension_arc

    monkeypatch.setattr(tension_arc, "_embedder", None)
    monkeypatch.setattr(tension_arc, "_embedder_available", None)

    calls = {"n": 0}

    def _unreachable(*args, **kwargs):
        calls["n"] += 1
        raise OSError("We couldn't connect to 'https://huggingface.co' to load the files")

    import sys
    import types

    fake_module = types.ModuleType("sentence_transformers")
    fake_module.SentenceTransformer = _unreachable
    monkeypatch.setitem(sys.modules, "sentence_transformers", fake_module)

    with caplog.at_level(logging.WARNING):
        assert tension_arc._get_embedder() is None
    assert "cohesion tension will be 0" in caplog.text

    # And the failure is remembered: a second lookup must not retry the same
    # failing download (it would otherwise repeat once per paragraph).
    assert tension_arc._get_embedder() is None
    assert calls["n"] == 1, "a failed model load must not be retried on every call"


# ── 7. Remaining branch arms (p3-task-4 support-module sweep) ────────────────
# The tests above exercise the real spaCy + sentence-transformers happy path
# (via the module-level fixtures other tests trigger first) and the embedder
# import-fallback arm. These close what's left: the spaCy import-fallback arm
# (mirrors #6 but for spaCy, not the embedder), the `_get_nlp` load-trigger
# arm, and a set of small pure helpers that are cleanest to unit-test directly
# with hand-built inputs rather than fishing for real text that happens to
# produce the right internal shape.


def test_load_models_spacy_unavailable_degrades_to_none(monkeypatch, caplog):
    """Mirrors test_unreachable_embedder_degrades_to_zero_cohesion, but for
    spaCy: `spacy.load("en_core_web_sm")` raising (missing package or missing
    model download) must set `_spacy_available = False` and log a warning,
    never propagate."""
    import logging
    import sys
    import types

    from original import tension_arc

    monkeypatch.setattr(tension_arc, "_nlp", None)
    monkeypatch.setattr(tension_arc, "_spacy_available", None)
    # Don't touch the embedder globals — leave load_models' embedder branch
    # alone so this test only exercises the spaCy try/except.
    monkeypatch.setattr(tension_arc, "_embedder", object())

    def _raise_load(name):
        raise OSError("model 'en_core_web_sm' not found")

    fake_spacy = types.ModuleType("spacy")
    fake_spacy.load = _raise_load
    monkeypatch.setitem(sys.modules, "spacy", fake_spacy)

    with caplog.at_level(logging.WARNING):
        tension_arc.load_models()

    assert tension_arc._spacy_available is False
    assert tension_arc._nlp is None
    assert "spaCy unavailable" in caplog.text


def test_load_models_skips_embedder_block_when_already_loaded(monkeypatch):
    """`if _embedder is None` must be False (and the whole embedder try/except
    skipped) when a previous call already populated it — covers the
    'load_models called a second time' exit arm."""
    from original import tension_arc

    sentinel = object()
    monkeypatch.setattr(tension_arc, "_embedder", sentinel)
    monkeypatch.setattr(tension_arc, "_nlp", object())  # also skip the spaCy branch
    monkeypatch.setattr(tension_arc, "_spacy_available", True)

    tension_arc.load_models()

    assert tension_arc._embedder is sentinel  # untouched — never re-attempted


def test_get_nlp_triggers_load_models_when_unset(monkeypatch):
    """`_get_nlp()` must call `load_models()` itself when `_nlp` is still
    None and spaCy hasn't already been marked unavailable — the lazy-load
    path used by `_analyze_paragraph` on first real use."""
    from original import tension_arc

    monkeypatch.setattr(tension_arc, "_nlp", None)
    monkeypatch.setattr(tension_arc, "_spacy_available", None)

    result = tension_arc._get_nlp()

    # Either spaCy loaded for real (this environment has it, per the other
    # integration tests in this file) or it degraded to unavailable — either
    # way `_spacy_available` must no longer be the untested `None` sentinel.
    assert tension_arc._spacy_available is not None
    assert result is tension_arc._nlp


def test_cosine_near_zero_vector_returns_zero():
    import numpy as np

    from original.tension_arc import _cosine

    assert _cosine(np.zeros(3), np.array([1.0, 2.0, 3.0])) == 0.0
    assert _cosine(np.array([1.0, 0.0]), np.zeros(2)) == 0.0


class _FakeHead:
    def __init__(self, i):
        self.i = i


class _FakeToken:
    def __init__(self, dep_, head_i):
        self.dep_ = dep_
        self.head = _FakeHead(head_i)


class _FakeSent:
    """Minimal stand-in for a spaCy `Span` — only what `_syntactic_tension`
    touches: iteration over tokens, `.start`/`.end`/`.text`."""

    def __init__(self, tokens, start, end, text):
        self._tokens = tokens
        self.start = start
        self.end = end
        self.text = text

    def __iter__(self):
        return iter(self._tokens)


def test_syntactic_tension_unresolved_open_structure_loops_past_it():
    """An open-dependency token whose head lies OUTSIDE the sentence
    boundary must not count as resolved, and the loop must continue past
    it to any remaining tokens — a real spaCy parse essentially never
    produces this shape, so a fake token/sent stands in for it."""
    from original.tension_arc import _syntactic_tension

    unresolved = _FakeToken(dep_="advcl", head_i=99)  # head far outside [0, 5)
    trailing = _FakeToken(dep_="det", head_i=1)  # not an open label — no-op
    sent = _FakeSent([unresolved, trailing], start=0, end=5, text="Some clause here.")

    # open_count=1 (unresolved), resolved_count=0 -> (1 - 0) / max(1, 1) = 1.0
    assert _syntactic_tension(sent) == 1.0


def test_classify_move_concession_claim_and_evidence_arms():
    from original.tension_arc import _classify_move

    assert _classify_move("Admittedly this could be improved.") == "K"
    assert _classify_move("Clearly this argument holds up.") == "C"
    assert _classify_move("The council convened in 1517 to address the matter.") == "E"


def test_find_peaks_detects_boundary_peaks():
    from original.tension_arc import TENSION_THRESHOLD, _find_peaks

    assert TENSION_THRESHOLD < 0.5
    vals = [0.5, 0.1, 0.1, 0.5]
    peaks = _find_peaks(vals)
    # Both the first and last elements qualify as boundary peaks.
    assert peaks == [0, 3]


def test_analyze_paragraph_returns_neutral_arc_when_spacy_unavailable(monkeypatch):
    from original.tension_arc import _analyze_paragraph

    monkeypatch.setattr("original.tension_arc._nlp", None)
    monkeypatch.setattr("original.tension_arc._spacy_available", False)

    arc = _analyze_paragraph("Some paragraph text of no particular consequence at all.", 0)

    assert arc.sentences == []
    assert arc.resolution_ratio == 1.0
    assert arc.peak_count == 0


def test_analyze_paragraph_returns_neutral_arc_when_no_sentences():
    """spaCy parses the paragraph but finds zero sentence spans (e.g. an
    empty string) — a distinct arm from 'spaCy unavailable'."""
    from original import tension_arc

    tension_arc.load_models()
    if tension_arc._nlp is None:
        import pytest

        pytest.skip("spaCy not available in this environment")

    arc = tension_arc._analyze_paragraph("", 0)
    assert arc.sentences == []
    assert arc.resolution_ratio == 1.0


def test_authenticity_signal_near_zero_baseline_returns_one():
    from original.tension_arc import _authenticity_signal

    assert _authenticity_signal(0.5, 0.0) == 1.0
    assert _authenticity_signal(0.5, 0.0005) == 1.0


def test_authenticity_signal_computes_relative_deviation():
    from original.tension_arc import _authenticity_signal

    # Submission kappa matches the baseline exactly -> full agreement.
    assert _authenticity_signal(0.4, 0.4) == 1.0
    # Submission kappa is maximally far from the baseline -> clipped to 0.
    assert _authenticity_signal(0.0, 0.4) == 0.0


def test_arc_flag_authenticity_deviation_branch():
    from original.tension_arc import _arc_flag

    flag, reason = _arc_flag(
        kappa=0.1,
        mu_rho=0.5,
        mean_tension=0.2,
        max_tension=0.25,
        authenticity=0.5,  # < 0.70 -> baseline-deviation branch wins outright
        num_rho_values=5,
    )
    assert flag == "review"
    assert "baseline" in reason.lower()


def test_arc_flag_kappa_based_ai_typical_branch():
    from original.tension_arc import _arc_flag

    flag, reason = _arc_flag(
        kappa=0.05,
        mu_rho=0.9,
        mean_tension=0.15,
        max_tension=0.20,  # not < 0.18, so the flat-amplitude branch is skipped
        authenticity=None,
        num_rho_values=3,  # >= 3, enabling the kappa-based signal
    )
    assert flag == "ai_typical"
    assert "catastrophe index" in reason.lower()


def test_analyze_tension_arc_returns_review_when_paragraphs_split_to_empty():
    """>= 200 words overall, but every blank-line-separated chunk is under
    the 30-char paragraph floor — `_split_paragraphs` filters all of them
    out, so `paragraphs` comes back empty despite passing the word-count
    gate. Distinct from the `insufficient_length` short-circuit."""
    from original.tension_arc import analyze_tension_arc

    text = "\n\n".join(["word"] * 250)  # 250 words, each its own tiny "paragraph"
    result = analyze_tension_arc(text)

    assert result.paragraph_arcs == []
    assert result.arc_flag == "review"
    assert result.arc_flag_reason == "Insufficient text structure for tension arc analysis."


# NOTE on original/tension_arc.py's `if __name__ == "__main__":` block
# (module lines ~574-648): this is a manual CLI self-test/demo script (loads
# real models, runs two hard-coded examples, prints a comparison table — no
# assertions). It only executes when the module is run directly
# (`python -m original.tension_arc` / `python original/tension_arc.py`),
# never on import, so pytest's coverage of this module can never reach it —
# there's no unit to assert against, and driving it via subprocess would
# require a real network-fetched sentence-transformers model (or a redundant
# duplicate of the fallback tests above) for zero additional verification
# value. Left uncovered deliberately; no pragma added per policy — this note
# is the justification.
