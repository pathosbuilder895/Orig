"""Rule D (RULE_D_OBSERVATION): a report-only, testing-phase consistency observation.

What these pin:
* the pre-registered formula D = -(B + C + zO)/3, its signs and equal weights;
* the length-setting mapping and the committed calibration thresholds;
* the class-size floor (3 other students, 5 papers) and the short-paper floor are
  "inconclusive" with no index, never a score;
* the frozen vectorizer is plain TF-IDF (parity with scikit-learn on the same vocabulary);
* stored profiles are deleted with the student and when an approval is withdrawn;
* off computes and stores nothing; shadow never attaches; on attaches for staff only;
* deviation_score and the action are identical in every mode (gate G-RD, fed here);
* no explanation ever names a cause, a probability or a misconduct word.
"""
from __future__ import annotations

import re
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from original import rule_d
from original.rule_d import core, explain, service, textprofile as tp
from validation.calibration_gate import evaluate_g_rule_d_report_only
from validation.gate_contracts import GATE_CONTRACTS

ROOT = Path(__file__).resolve().parents[1]
CORPUS = ROOT / "validation" / "public_authors" / "corpus"
AUTHORS = ["mill", "newman", "emerson", "douglass", "chesterton"]


def _words(text: str, start: int, n: int) -> str:
    return " ".join(text.split()[start:start + n])


def _papers(author: str, k: int, n_words: int) -> list[str]:
    files = sorted(f for f in (CORPUS / author).glob("*.txt") if not f.name.startswith("_"))
    text = " ".join(f.read_text(encoding="utf-8", errors="replace") for f in files)
    return [_words(text, 400 + i * (n_words + 50), n_words) for i in range(k)]


def _fake_feature(text: str) -> np.ndarray:
    """A cheap deterministic stand-in for the 109-feature pipeline (unit tests only)."""
    from original.constants import FEATURE_DIM

    rng = np.random.default_rng(len(text) + sum(map(ord, text[:50])))
    return np.clip(0.5 + 0.05 * rng.standard_normal(FEATURE_DIM), 0, 1)


def _profiles(author: str, k: int = 3, n_words: int = 320) -> list[dict]:
    return [core.build_paper_profile(t, _fake_feature(t), f"{author} {i + 1}", _fake_feature)
            for i, t in enumerate(_papers(author, k, n_words))]


# ------------------------------------------------------------------ the formula --
def test_formula_is_minus_the_mean_of_three_equal_thirds():
    assert core.rule_d(1, 1, 1, 1, 1) == pytest.approx(-1.0)
    assert core.rule_d(0, 0, 0, 0, 0) == 0.0
    # B and C are each the mean of centroid and nearest; each component weighs one third.
    assert core.rule_d(3, 0, 0, 0, 0) == pytest.approx(-0.5)
    assert core.rule_d(0, 0, 0, 3, 0) == pytest.approx(-0.5)
    assert core.rule_d(0, 0, 0, 0, 3) == pytest.approx(-1.0)
    # Closer to the claimed student than classmates are (positive z) lowers D.
    assert core.rule_d(2, 2, 2, 2, 2) < core.rule_d(-2, -2, -2, -2, -2)


def test_rel_z_is_class_relative():
    assert core.rel_z(3.0, np.array([1.0, 2.0, 3.0])) == pytest.approx(1 / np.std([1, 2, 3]))
    assert core.rel_z(2.0, np.array([1.0, 2.0, 3.0])) == pytest.approx(0.0)


def test_configuration_maps_to_the_nearest_measured_setting():
    assert core.configuration(1200, [1200, 1300]) == "matched_1200_1200"
    assert core.configuration(800, [300]) == "matched_1200_1200"
    assert core.configuration(300, [1200, 1100, 900]) == "long_past_1200_short_new_300"
    assert core.configuration(300, [300, 400]) == "matched_300_300"
    assert core.configuration(300, []) == "matched_300_300"
    assert set(core.THRESHOLDS) == {"matched_300_300", "matched_1200_1200", "long_past_1200_short_new_300"}
    assert core.THRESHOLDS["long_past_1200_short_new_300"] == -0.919008
    note = core.configuration_note("long_past_1200_short_new_300", 310, [1200, 1180])
    assert "nearest tested setting" in note and "310 words" in note


def test_mode_defaults_on_and_typed_values_fail_closed(monkeypatch):
    for raw, want in [("off", "off"), ("shadow", "shadow"), ("on", "on"), (" ON ", "on"), ("1", "off"),
                      ("yes", "off"), ("", "off")]:
        monkeypatch.setenv("RULE_D_OBSERVATION", raw)
        assert rule_d.mode() == want
    monkeypatch.delenv("RULE_D_OBSERVATION")
    assert rule_d.mode() == "on"  # on by default while testing (2026-11, owner decision)


# ------------------------------------------------------------------ the floors --
def test_below_the_class_floor_is_inconclusive_with_no_index():
    new = _papers("chesterton", 1, 320)[0]
    claimed = _profiles("mill", 2)
    two_peers = {"p1": _profiles("newman", 3), "p2": _profiles("emerson", 3)}
    obs = core.observe(new, _fake_feature(new), claimed, two_peers)
    assert obs.status == "inconclusive" and obs.index is None and obs.reads_less_like_student is None
    assert "at least 3 other students" in obs.summary and obs.classmates == 2
    # Three students but only four papers between them.
    few = {"p1": _profiles("newman", 2), "p2": _profiles("emerson", 1), "p3": _profiles("douglass", 1)}
    obs = core.observe(new, _fake_feature(new), claimed, few)
    assert obs.status == "inconclusive" and obs.index is None and obs.classmate_papers == 4
    # No approved papers for the claimed student.
    assert core.observe(new, _fake_feature(new), [], few).status == "inconclusive"
    # The service checks the floor before building any profile.
    st = SimpleNamespace(student_id="t:a", samples=[])
    peer = SimpleNamespace(student_id="t:b", samples=[SimpleNamespace(text="x y", auth_weight=1.0)])
    assert service.observe_for(None, st, [peer, st], new, None, _fake_feature).index is None


def test_a_short_paper_is_inconclusive():
    peers = {a: _profiles(a, 2) for a in ("newman", "emerson", "douglass")}
    short = _words(_papers("chesterton", 1, 320)[0], 0, 200)
    obs = core.observe(short, _fake_feature(short), _profiles("mill", 2), peers)
    assert obs.status == "inconclusive" and obs.index is None and "200 words" in obs.reason


# ------------------------------------------------------------------ the vectorizer --
def test_vectorizer_matches_scikit_learn_tfidf_on_the_frozen_vocabulary():
    sk = pytest.importorskip("sklearn.feature_extraction.text")
    text = _papers("mill", 1, 300)[0]
    for name, v in tp.vectorizers().items():
        ref = sk.TfidfVectorizer(analyzer="char", ngram_range=(v.lo, v.hi), lowercase=False,
                                 vocabulary=v.terms, sublinear_tf=True)
        ref.idf_ = np.asarray(v.idf)
        row = ref.transform([v.prepare(text)]).tocoo()
        want = dict(zip(row.col.tolist(), row.data.tolist()))
        got = v.profile(text)
        assert set(got) == set(want), name
        assert max(abs(got[k] - want[k]) for k in want) < 1e-9, name
    meta = tp.artifact_meta()
    assert meta["study_id"] == core.STUDY_ID and meta["collection"] == "humanities"


def test_mask_topic_keeps_function_words_and_punctuation():
    assert tp.mask_topic("The cat, however, sat on 12 mats.") == "The ***, however, *** on ## ****."


def test_centroid_and_dot_handle_empty_input():
    assert tp.centroid([]) == {} and tp.centroid([{}]) == {}
    assert tp.dot({1: 1.0}, {1: 0.5, 2: 1.0}) == pytest.approx(0.5)


# ------------------------------------------------------------------ explanation --
BANNED_RX = re.compile(r"\bAI\b|\bA\.I\.|cheat|probab|plagiar|ghost|dishonest|misconduct|fraud|chatgpt|"
                       r"accura|fingerprint|generated", re.I)


def _strings(obs) -> list[str]:
    d = obs.as_dict()
    return [d["summary"], d["configuration_note"], d["confidence_note"], d["testing_phase_label"],
            d["reason"] or "", *d["reads_like"], *d["reads_less_like"]]


@pytest.mark.parametrize("probe", [False, True])
def test_explanations_give_reasons_both_ways_and_never_accuse(probe):
    peers = {a: _profiles(a, 2, 360) for a in ("newman", "emerson", "douglass", "chesterton")}
    claimed = _profiles("mill", 3, 360)
    new = _papers("chesterton" if probe else "mill", 4, 360)[3]
    obs = core.observe(new, _fake_feature(new), claimed, peers)
    assert obs.status == "observed" and obs.index is not None
    assert obs.threshold == core.THRESHOLDS[obs.configuration]
    assert obs.reads_less_like_student == (obs.index > obs.threshold)
    assert obs.reads_like and obs.reads_like[0].startswith("Its closest match")
    assert "Not yet validated on student writing" in obs.confidence_note
    assert obs.testing_phase_label.startswith("Testing phase")
    for s in _strings(obs):
        assert not BANNED_RX.search(s), s
        assert "%" not in s or "-" in s  # only the measured ranges carry a percent sign
    assert not any(w in " ".join(_strings(obs)).lower() for w in explain.BANNED if w != "ai")


def test_inconclusive_wording_is_clean_too():
    obs = core.inconclusive("the class needs more students.")
    for s in _strings(obs):
        assert not BANNED_RX.search(s)


def test_explanation_notes_a_much_shorter_paper_and_topic_and_genre_gaps():
    obs = core.Observation(status="observed", reads_less_like_student=True,
                           components={"character_profile": -1.0, "word_shape_profile": 0.2,
                                       "original_features": -0.5})
    claimed = [{"label": "Essay one", "char": {}, "punct": {"semicolons": 4.0}, "words": 1200}]
    sims = {"char": (np.array([0.1, 0.3, 0.4]), np.array([0.1, 0.3, 0.4]))}
    explain.explain(obs, new_text="word " * 300, new_profiles={"char": {}}, claimed=claimed, sims=sims,
                    words=300, own_centroid={}, class_mean={})
    text = " ".join(obs.reads_less_like)
    assert "much shorter" in text and "follows the topic" in text
    assert "closer to the past papers of 2 of 2 classmates" in text
    assert "semicolons much less often" in text
    assert obs.summary.startswith("Reads less like")
    obs2 = core.Observation(status="observed", reads_less_like_student=True,
                            components={"character_profile": 0.5, "word_shape_profile": 0.4,
                                        "original_features": -0.5})
    explain.explain(obs2, new_text="a; " * 400, new_profiles={"char": {}}, claimed=claimed, sims=sims,
                    words=400, own_centroid={}, class_mean={})
    joined = " ".join(obs2.reads_less_like)
    assert "type of assignment or genre" in joined and "semicolons much more often" in joined


# ------------------------------------------------------------------ persistence --
def test_sqlite_profiles_sync_prune_and_delete_with_the_student(store_reset):
    from original.quantum.state import BaselineSample, StudentState
    from original.repository import SqliteRepository

    repo = SqliteRepository()
    papers = _papers("mill", 3, 320)
    st = StudentState(student_id="ws:alice")
    for t in papers:
        st.add_sample(BaselineSample(text=t, vector=_fake_feature(t), provenance="verified", auth_weight=1.0,
                                     genre="essay"))
    store_reset.put(st)
    out = service.sync_profiles(repo, st, _fake_feature)
    assert len(out) == 3 and set(repo.get_rule_d_profiles("ws:alice")) == service.current_shas(st)
    stored = next(iter(repo.get_rule_d_profiles("ws:alice").values()))
    assert "text" not in stored and set(stored) >= {"char", "masked", "vector", "pieces", "punct"}
    inv = repo.student_data_inventory("ws:alice")
    assert inv["data_categories"]["rule_d_profiles"]["count"] == 3
    # Withdrawing an approval: the paper's row goes on the next prune.
    st.samples = st.samples[:2]
    assert service.prune_profiles(repo, st) == 1
    assert len(repo.get_rule_d_profiles("ws:alice")) == 2
    # A stale row is also dropped by sync.
    repo.put_rule_d_profile("ws:alice", "f" * 64, {"words": 1})
    assert len(service.sync_profiles(repo, st, _fake_feature)) == 2
    assert "f" * 64 not in repo.get_rule_d_profiles("ws:alice")
    # Deleting the student deletes every profile.
    repo.delete_student("ws:alice")
    assert repo.get_rule_d_profiles("ws:alice") == {}


# ------------------------------------------------------------------ the route --
def _approve(client, sid, texts):
    for t in texts:
        r = client.post(f"/students/{sid}/baseline", json={"text": t, "provenance": "verified"})
        assert r.status_code == 200, r.text[:300]


def _canon(obj):
    """The byte-identity matrix's normalisation: only ``created_at`` is volatile."""
    import json

    def strip(o):
        if isinstance(o, dict):
            return {k: strip(v) for k, v in o.items() if k != "created_at"}
        if isinstance(o, list):
            return [strip(v) for v in o]
        return o
    return json.dumps(strip(obj), sort_keys=True)


def _score(client, sid, text, n):
    r = client.post(f"/students/{sid}/score", json={"text": text, "submission_id": f"rd{n}"})
    assert r.status_code == 200, r.text[:300]
    return r.json()


def test_route_modes_off_shadow_on_and_gate(live_client, store_reset, monkeypatch, caplog):
    from original.repository import SqliteRepository

    repo = SqliteRepository()
    monkeypatch.setenv("RULE_D_OBSERVATION", "off")
    # Four students in one (flat) workspace: the claimed one plus three classmates, 6 papers.
    _approve(live_client, "rd_alice", _papers("mill", 2, 320))
    for a in ("newman", "emerson", "douglass"):
        _approve(live_client, f"rd_{a}", _papers(a, 2, 320))
    new = _papers("mill", 4, 320)[3]

    off = _score(live_client, "rd_alice", new, 1)
    assert off["rule_d"] is None
    assert repo.get_rule_d_profiles("rd_alice") == {}  # off: nothing computed or stored

    monkeypatch.setenv("RULE_D_OBSERVATION", "shadow")
    with caplog.at_level("INFO"):
        shadow = _score(live_client, "rd_alice", new, 1)
    # Shadow with a real computed observation: the whole response is byte-identical to off.
    assert _canon(shadow) == _canon(off)
    assert shadow["rule_d"] is None
    assert any("rule_d_observation mode=shadow status=observed" in m for m in caplog.messages)
    assert not any("rd_alice" in m for m in caplog.messages if "rule_d_observation" in m)
    assert len(repo.get_rule_d_profiles("rd_alice")) == 2

    monkeypatch.setenv("RULE_D_OBSERVATION", "on")
    on = _score(live_client, "rd_alice", new, 3)
    rd = on["rule_d"]
    assert rd["status"] == "observed" and rd["classmates"] == 3 and rd["classmate_papers"] == 6
    assert rd["testing_phase_label"] == core.TESTING_LABEL

    # Below the floor: delete two classmates (their profiles go with them).
    assert len(repo.get_rule_d_profiles("rd_newman")) == 2
    for a in ("newman", "emerson"):
        assert live_client.delete(f"/students/rd_{a}").status_code in (200, 204)
        assert repo.get_rule_d_profiles(f"rd_{a}") == {}
    lone = _score(live_client, "rd_alice", new, 4)["rule_d"]

    by_mode = {m: (r["authorship"]["deviation_score"], r["recommendation"]["action"])
               for m, r in (("off", off), ("shadow", shadow), ("on", on))}
    result = evaluate_g_rule_d_report_only(by_mode, lone)
    assert result.verdict == "pass", result.current_value
    assert lone["status"] == "inconclusive" and lone["index"] is None


def test_attach_is_staff_only():
    from original.routers import students_scoring as ss

    obs = core.inconclusive("nothing here.")
    for request in (None, SimpleNamespace(state=SimpleNamespace(principal=SimpleNamespace(role="student")))):
        resp = SimpleNamespace(rule_d=None)
        ss._attach_rule_d(resp, request, obs)
        assert resp.rule_d is None
    resp = SimpleNamespace(rule_d=None)
    ss._attach_rule_d(resp, SimpleNamespace(state=SimpleNamespace(principal=SimpleNamespace(role="professor"))), obs)
    assert resp.rule_d.status == "inconclusive"


def test_a_failing_observation_never_fails_scoring(live_client, store_reset, monkeypatch):
    monkeypatch.setenv("RULE_D_OBSERVATION", "on")
    monkeypatch.setattr("original.rule_d.service.observe_for", lambda *a, **k: 1 / 0)
    _approve(live_client, "rd_err", _papers("mill", 2, 320))
    assert _score(live_client, "rd_err", _papers("mill", 3, 320)[2], 9)["rule_d"] is None
    # A failure while attaching (e.g. a field the schema rejects) is caught too.
    monkeypatch.setattr("original.rule_d.service.observe_for", lambda *a, **k: core.inconclusive("x."))
    monkeypatch.setattr("original.routers.students_scoring._attach_rule_d", lambda *a, **k: 1 / 0)
    assert _score(live_client, "rd_err", _papers("mill", 3, 320)[2], 10)["rule_d"] is None


def test_profiles_rebuild_when_features_were_re_extracted(store_reset):
    from original.quantum.state import BaselineSample, StudentState
    from original.repository import SqliteRepository

    repo = SqliteRepository()
    st = StudentState(student_id="ws:carol")
    t = _papers("newman", 1, 320)[0]
    st.add_sample(BaselineSample(text=t, vector=_fake_feature(t), provenance="verified", auth_weight=1.0,
                                 genre="essay"))
    first = service.sync_profiles(repo, st, _fake_feature)[0]
    assert service.sync_profiles(repo, st, _fake_feature)[0] == first
    st.samples[0].vector = np.asarray(st.samples[0].vector) + 0.01
    again = service.sync_profiles(repo, st, _fake_feature)[0]
    assert np.allclose(again["vector"], st.samples[0].vector)


# ------------------------------------------------------------------ the gate --
def test_gate_witness_fails_on_each_leg_alone():
    same = {"off": (0.4, "monitor"), "shadow": (0.4, "monitor"), "on": (0.4, "monitor")}
    ok = {"status": "inconclusive", "index": None}
    assert evaluate_g_rule_d_report_only(same, ok).verdict == "pass"
    moved = dict(same, on=(0.4, "schedule_conversation"))
    r = evaluate_g_rule_d_report_only(moved, ok)
    assert r.verdict == "fail" and r.detail["changed_modes"] == ["on"]
    r = evaluate_g_rule_d_report_only(same, {"status": "observed", "index": 0.1})
    assert r.verdict == "fail" and r.detail["changed_modes"] == []
    assert evaluate_g_rule_d_report_only({}, ok).verdict == "uninformative"
    assert GATE_CONTRACTS["evaluate_g_rule_d_report_only"].failure_witness().verdict == "fail"


def test_long_papers_use_whole_past_papers_for_original_features():
    peers = {a: _profiles(a, 2, 800) for a in ("newman", "emerson", "douglass")}
    new = _papers("mill", 3, 800)[2]
    obs = core.observe(new, _fake_feature(new), _profiles("mill", 2, 800), peers)
    assert obs.configuration == "matched_1200_1200" and obs.threshold == core.THRESHOLDS["matched_1200_1200"]
    assert "Strongest setting" in obs.confidence_note


def test_pick_stops_at_non_positive_scores_and_skips_fragments():
    terms = [" of ", "the", ", or ", " of"]
    assert explain._pick({0: 0.5, 1: 0.4, 2: 0.3, 3: 0.0}, terms) == [" of ", ", or "]
    assert explain._pick({0: -1.0}, terms) == []


def test_same_vector_treats_missing_or_reshaped_vectors_as_stale():
    assert not service._same_vector(None, [0.5])
    assert not service._same_vector([0.5], None)
    assert not service._same_vector([0.5, 0.5], [0.5])
    assert service._same_vector([0.5, 0.25], np.array([0.5, 0.25]))
