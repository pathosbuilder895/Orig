"""
tests/context/test_composition_summary.py — persisting the macro-timing
``composition_summary`` blob (ADR-010, T-69/T-74).

``composition_summary`` replaces the raw per-key ``keystroke_data`` blob as
the thing Bluebook's exam client posts: no per-key timing, just session-level
macro metrics (``session_seconds``, ``word_count``, ``paste_attempts``,
``focus_losses``, ``revision_count``, ``started_at``, ``ended_at``,
``exam_config``). The frozen shape is threat-model spec §5.3
(``docs/superpowers/specs/2026-09-20-adversarial-verification-threat-model-design.md``).

This is schema + persistence only (Task 8). ``resolve_composition_mode``
actually consuming the field is Task 9 — out of scope here.

Mirrors the existing ``keystroke_data`` coverage pattern in
``tests/test_keystroke_data_persistence.py`` and
``tests/test_repository_contract.py::TestKeystrokeDataRoundtrip``:

  1. ``BaselineSample.composition_summary`` defaults to None (additive field).
  2. SQLite round-trip (``store._serialize`` / ``_deserialize``).
  3. SQLite backward compatibility: a sample dict serialized before this
     field existed still deserializes, with ``composition_summary=None``.
  4. Postgres round-trip (``PostgresRepository._state_to_doc`` /
     ``_doc_to_state`` — pure functions, no live database required).
  5. Postgres backward compatibility, mirroring (3).
  6. Request schemas (``AddSampleRequest`` / ``ScoreSubmissionRequest``)
     accept and round-trip ``composition_summary`` — minus the deletion-key
     ``revision_count``, which they discard while the ``behavioral`` feature
     group is disabled (tests/test_keystroke_boundary.py).
  7. The ingestion endpoint (``POST /students/{id}/baseline``) threads
     ``req.composition_summary`` onto the persisted sample — the line in
     ``original/routers/students_baseline.py`` that actually makes the
     field reach persistence from a real API call.
"""

from __future__ import annotations

import json

import numpy as np
import pytest

from original.constants import FEATURE_DIM
from original.context import resolvers as r
from original.quantum.state import BaselineSample, StudentState

_COMPOSITION_SUMMARY = {
    "session_seconds": 2700,
    "word_count": 812,
    "paste_attempts": 1,
    "focus_losses": 2,
    "revision_count": 46,
    "started_at": "2026-09-20T14:00:00Z",
    "ended_at": "2026-09-20T14:45:00Z",
    "exam_config": {"block_copy": True, "min_words": 500, "duration_min": 45},
}

# What a request model keeps of _COMPOSITION_SUMMARY while the ``behavioral``
# feature group is disabled (the classroom default): every coarse session key,
# minus the deletion-key ``revision_count`` (tests/test_keystroke_boundary.py).
_COMPOSITION_SUMMARY_AT_BOUNDARY = {
    k: v for k, v in _COMPOSITION_SUMMARY.items() if k != "revision_count"
}


def _baseline_sample(**overrides) -> BaselineSample:
    kwargs = dict(
        text="x",
        vector=np.full(FEATURE_DIM, 0.5, dtype=np.float64),
        provenance="proctored",
        auth_weight=1.0,
    )
    kwargs.update(overrides)
    return BaselineSample(**kwargs)


# ══════════════════════════════════════════════════════════════════════════════
# 1. BaselineSample default
# ══════════════════════════════════════════════════════════════════════════════


class TestBaselineSampleDefault:
    def test_composition_summary_defaults_to_none(self):
        s = _baseline_sample()
        assert s.composition_summary is None

    def test_composition_summary_can_be_set(self):
        s = _baseline_sample(composition_summary=_COMPOSITION_SUMMARY)
        assert s.composition_summary == _COMPOSITION_SUMMARY


# ══════════════════════════════════════════════════════════════════════════════
# 2/3. SQLite: store._serialize / _deserialize
# ══════════════════════════════════════════════════════════════════════════════


class TestSqliteSerialization:
    def test_round_trip_carries_composition_summary(self):
        from original.store import _deserialize, _serialize

        state = StudentState(student_id="s", samples=[])
        state.add_sample(_baseline_sample(text="a", composition_summary=_COMPOSITION_SUMMARY))
        state.add_sample(_baseline_sample(text="b"))  # no summary — stays None

        revived = _deserialize(_serialize(state))
        assert revived.samples[0].composition_summary == _COMPOSITION_SUMMARY
        assert revived.samples[1].composition_summary is None

    def test_legacy_row_without_composition_summary_key_defaults_to_none(self):
        """A sample dict serialized before this field existed has no
        "composition_summary" key at all — not even null. Simulate that exact
        pre-migration shape by stripping the key after serializing with the
        *current* _serialize (which does emit it, null or not) and confirm
        _deserialize still loads the row, defaulting the field to None. This
        is the exact shape every pre-this-change production row has."""
        from original.store import _deserialize, _serialize

        state = StudentState(student_id="legacy", samples=[])
        state.add_sample(_baseline_sample(text="a"))

        legacy_payload = json.loads(_serialize(state))
        del legacy_payload["samples"][0]["composition_summary"]
        legacy_str = json.dumps(legacy_payload)

        revived = _deserialize(legacy_str)
        assert revived.samples[0].composition_summary is None


# ══════════════════════════════════════════════════════════════════════════════
# 4/5. Postgres: PostgresRepository._state_to_doc / _doc_to_state
#
# Both are @staticmethod and operate purely on in-memory objects/dicts — no
# live Postgres connection required, so these run unconditionally (not gated
# behind DATABASE_URL / @pytest.mark.postgres).
# ══════════════════════════════════════════════════════════════════════════════


class TestPostgresSerialization:
    def test_round_trip_carries_composition_summary(self):
        from original.repository import PostgresRepository

        state = StudentState(student_id="s", samples=[])
        state.add_sample(_baseline_sample(text="a", composition_summary=_COMPOSITION_SUMMARY))
        state.add_sample(_baseline_sample(text="b"))

        doc = PostgresRepository._state_to_doc(state)
        revived = PostgresRepository._doc_to_state(doc)
        assert revived.samples[0].composition_summary == _COMPOSITION_SUMMARY
        assert revived.samples[1].composition_summary is None

    def test_legacy_doc_without_composition_summary_key_defaults_to_none(self):
        """Mirrors the SQLite legacy test above: strip the key entirely to
        reproduce a doc written before this field existed."""
        from original.repository import PostgresRepository

        state = StudentState(student_id="legacy", samples=[])
        state.add_sample(_baseline_sample(text="a"))

        legacy_doc = PostgresRepository._state_to_doc(state)
        del legacy_doc["samples"][0]["composition_summary"]

        revived = PostgresRepository._doc_to_state(legacy_doc)
        assert revived.samples[0].composition_summary is None


# ══════════════════════════════════════════════════════════════════════════════
# 6. Request schemas accept + round-trip composition_summary
# ══════════════════════════════════════════════════════════════════════════════


class TestRequestSchemas:
    def test_add_sample_request_accepts_composition_summary(self):
        from original.schemas import AddSampleRequest

        req = AddSampleRequest(text="essay body", composition_summary=_COMPOSITION_SUMMARY)
        assert req.composition_summary == _COMPOSITION_SUMMARY_AT_BOUNDARY
        assert "revision_count" not in req.composition_summary

    def test_add_sample_request_composition_summary_defaults_to_none(self):
        from original.schemas import AddSampleRequest

        req = AddSampleRequest(text="essay body")
        assert req.composition_summary is None

    def test_score_submission_request_accepts_composition_summary(self):
        from original.schemas import ScoreSubmissionRequest

        req = ScoreSubmissionRequest(text="essay body", composition_summary=_COMPOSITION_SUMMARY)
        assert req.composition_summary == _COMPOSITION_SUMMARY_AT_BOUNDARY
        assert "revision_count" not in req.composition_summary

    def test_score_submission_request_composition_summary_defaults_to_none(self):
        from original.schemas import ScoreSubmissionRequest

        req = ScoreSubmissionRequest(text="essay body")
        assert req.composition_summary is None


# ══════════════════════════════════════════════════════════════════════════════
# 7. Ingestion endpoint threads composition_summary onto the persisted sample
# ══════════════════════════════════════════════════════════════════════════════


@pytest.fixture
def client(store_reset):
    from fastapi.testclient import TestClient

    import run

    return TestClient(run.load_legacy_demo_app())


class TestIngestEndpointPersistsCompositionSummary:
    def test_proctored_baseline_with_composition_summary_is_persisted(self, client):
        from original import store

        sid = "demo:composition-summary-regression"
        resp = client.post(
            f"/students/{sid}/baseline",
            json={
                "text": "This proctored sitting carries live Bluebook macro-timing "
                "telemetry so the composition-mode resolver can eventually use it. " * 3,
                "provenance": "proctored",
                "assignment": "midterm",
                "composition_summary": _COMPOSITION_SUMMARY,
            },
        )
        assert resp.status_code == 200, resp.text

        state = store.get(sid)
        assert state is not None and state.samples, "sample was not persisted"
        assert state.samples[-1].composition_summary == _COMPOSITION_SUMMARY_AT_BOUNDARY
        assert "revision_count" not in state.samples[-1].composition_summary
        assert state.samples[-1].provenance == "proctored"

    def test_baseline_without_composition_summary_stores_none(self, client):
        """A normal (non-Bluebook) upload must not synthesize a summary."""
        from original import store

        sid = "demo:composition-summary-absent"
        resp = client.post(
            f"/students/{sid}/baseline",
            json={
                "text": "An uploaded paper with no macro-timing telemetry attached "
                "at all. " * 3,
                "provenance": "verified",
                "assignment": "essay1",
            },
        )
        assert resp.status_code == 200, resp.text

        state = store.get(sid)
        assert state is not None and state.samples
        assert state.samples[-1].composition_summary is None


# ══════════════════════════════════════════════════════════════════════════════
# 8. Task 9 — resolve_composition_mode reads composition_summary
#
# Global Constraint (SP1 plan): "no change here may alter deviation_score/
# quantum_fidelity/recommendation.action for an authorized caller with
# unchanged input." A caller that still sends keystroke_data (unchanged) must
# get byte-identical output to before this diff — that is the regression
# test below. composition_summary is a brand-new, additive input path.
#
# Fixture text is deliberately < 200 words (so the text-only "looks_clean"
# heuristic can never fire regardless of punctuation) and has widely varied
# sentence lengths (so "looks_structured" can never fire either) — this
# isolates "mode"/"edit_signature"/"software_mediated" to depend only on the
# keystroke_data / composition_summary signal being compared, for a clean
# equivalence check.
# ══════════════════════════════════════════════════════════════════════════════

_CM_TEXT = (
    "The seminar met on Tuesday. "
    "Professor Alvarez opened the discussion by describing three long-standing "
    "debates within the historiography of the early modern period, each drawing "
    "on distinct methodological traditions that had developed over several "
    "decades of scholarly disagreement. "
    "Students took notes. "
    "One student asked a lengthy and carefully worded question about the "
    "relationship between primary sources and the broader interpretive "
    "frameworks scholars have used to make sense of them. "
    "The room was quiet. "
    "Afterward everyone adjourned to the library where a much longer "
    "conversation continued for nearly two hours, touching on topics ranging "
    "from archival access to translation problems in medieval Latin "
    "manuscripts. "
    "It rained later."
)
_CM_WORD_COUNT = 107  # from original.features.tier1.TextDoc(_CM_TEXT).word_count


def _cm_keystrokes(n=60):
    return [{"key": "a", "timestamp": i, "elapsed": i * 50} for i in range(n)]


class TestResolveCompositionModeSummaryEquivalence:
    """For an equivalent real-world scenario, the composition_summary path
    must land on the same {mode, edit_signature, software_mediated} as the
    keystroke_data path did before this diff.

    The paste case is a genuine equivalence: composition_summary's
    paste_attempts is the same underlying count as keystroke_data's
    paste-type revisions, through the same per-100-words formula. The heavy
    edit case is NOT that kind of equivalence — composition_summary has no
    per-event character-affected data, so `revision_count` and
    `deletionRate` are unrelated units; each side's inputs are independently
    chosen to cross its own threshold, demonstrating that both paths CAN
    reach "heavy" for illustrative inputs, not that the same real editing
    behavior produces it on both paths."""

    def test_natural_scenario_matches_across_both_paths(self):
        keystroke_data = {
            "keystrokes": _cm_keystrokes(),
            "pauses": [],
            "revisions": [],
            "deletionRate": 0.02,
            "wordCount": _CM_WORD_COUNT,
        }
        composition_summary = {
            "word_count": _CM_WORD_COUNT,
            "paste_attempts": 0,
            "revision_count": 3,  # 3/107*100 ~= 2.8/100 words, well under heavy
        }

        out_keystroke = r.resolve_composition_mode(_CM_TEXT, keystroke_data=keystroke_data)
        out_summary = r.resolve_composition_mode(_CM_TEXT, composition_summary=composition_summary)

        assert out_keystroke == {
            "mode": "natural_drafted",
            "edit_signature": "normal",
            "software_mediated": False,
        }
        assert out_summary == out_keystroke

    def test_mediated_paste_scenario_matches_across_both_paths(self):
        keystroke_data = {
            "keystrokes": _cm_keystrokes(),
            "pauses": [],
            "revisions": [{"type": "paste", "charsAffected": 200}],
            "deletionRate": 0.05,
            "wordCount": _CM_WORD_COUNT,
        }
        composition_summary = {
            "word_count": _CM_WORD_COUNT,
            "paste_attempts": 1,  # same underlying count as the one paste revision
            "revision_count": 3,
        }

        out_keystroke = r.resolve_composition_mode(_CM_TEXT, keystroke_data=keystroke_data)
        out_summary = r.resolve_composition_mode(_CM_TEXT, composition_summary=composition_summary)

        assert out_keystroke == {
            "mode": "tool_cleaned",
            "edit_signature": "normal",
            "software_mediated": True,
        }
        assert out_summary == out_keystroke

    def test_heavy_edit_scenario_matches_across_both_paths(self):
        keystroke_data = {
            "keystrokes": _cm_keystrokes(),
            "pauses": [],
            "revisions": [],
            "deletionRate": 0.25,  # > 0.20 -> heavy on the keystroke path
            "wordCount": _CM_WORD_COUNT,
        }
        composition_summary = {
            "word_count": _CM_WORD_COUNT,
            "paste_attempts": 0,
            "revision_count": 20,  # 20/107*100 ~= 18.7/100 words -> heavy
        }

        out_keystroke = r.resolve_composition_mode(_CM_TEXT, keystroke_data=keystroke_data)
        out_summary = r.resolve_composition_mode(_CM_TEXT, composition_summary=composition_summary)

        assert out_keystroke == {
            "mode": "natural_drafted",
            "edit_signature": "heavy",
            "software_mediated": False,
        }
        assert out_summary == out_keystroke

    def test_composition_summary_preferred_when_both_supplied(self):
        # When both are present, composition_summary wins (ADR-010: it is
        # the intended replacement path) even though the keystroke_data here
        # alone would signal heavy editing and paste-mediation.
        keystroke_data = {
            "keystrokes": _cm_keystrokes(),
            "pauses": [],
            "revisions": [{"type": "paste", "charsAffected": 500}],
            "deletionRate": 0.9,
            "wordCount": _CM_WORD_COUNT,
        }
        composition_summary = {
            "word_count": _CM_WORD_COUNT,
            "paste_attempts": 0,
            "revision_count": 3,
        }

        out = r.resolve_composition_mode(
            _CM_TEXT, keystroke_data=keystroke_data, composition_summary=composition_summary
        )
        assert out == {
            "mode": "natural_drafted",
            "edit_signature": "normal",
            "software_mediated": False,
        }

    def test_composition_summary_falls_back_to_resolver_word_count_when_missing(self):
        # word_count omitted from the summary -> falls back to the
        # resolver's own text-derived word count (_CM_WORD_COUNT), not a
        # ZeroDivisionError / raw-count misread.
        composition_summary = {"paste_attempts": 1, "revision_count": 3}
        out = r.resolve_composition_mode(_CM_TEXT, composition_summary=composition_summary)
        assert out["software_mediated"] is True
        assert out["mode"] == "tool_cleaned"


class TestResolveCompositionModeKeystrokePathUnchanged:
    """Regression: an existing keystroke_data-only caller (no
    composition_summary — today's real callers) must see byte-identical
    output to before this diff. Expected values below were computed by hand
    from the *unmodified* resolve_composition_mode logic against this exact
    fixture text and keystroke_data blob."""

    def test_keystroke_only_call_output_unchanged(self):
        keystroke_data = {
            "keystrokes": _cm_keystrokes(),
            "pauses": [],
            "revisions": [{"type": "paste", "charsAffected": 200}],
            "deletionRate": 0.05,
            "wordCount": _CM_WORD_COUNT,
        }
        out = r.resolve_composition_mode(_CM_TEXT, keystroke_data=keystroke_data)
        assert out == {
            "mode": "tool_cleaned",
            "edit_signature": "normal",
            "software_mediated": True,
        }

    def test_keystroke_only_natural_call_output_unchanged(self):
        keystroke_data = {
            "keystrokes": _cm_keystrokes(),
            "pauses": [],
            "revisions": [],
            "deletionRate": 0.02,
            "wordCount": _CM_WORD_COUNT,
        }
        out = r.resolve_composition_mode(_CM_TEXT, keystroke_data=keystroke_data)
        assert out == {
            "mode": "natural_drafted",
            "edit_signature": "normal",
            "software_mediated": False,
        }
