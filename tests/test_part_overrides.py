"""A teacher's own choice of which parts of a paper are measured
(original/features/part_overrides.py, steps 4-5 of the document-parts plan).

Checked here: (1) the choice is validated against the text, (2) the hook in
``preprocess.body_segments`` wins over the rules only when a choice is in
force, and with none is the identical list, (3) caches never serve a value
measured under another choice, (4) the score route takes the choice from
staff only, (5) a past paper keeps its choice on both storage backends and is
measured again when it changes, and (6) a backfill applies it.
"""

from __future__ import annotations

import importlib.util
import json
import os
import sys
from pathlib import Path

import numpy as np
import pytest

from original import store
from original.constants import FEATURE_DIM
from original.features import feature_flags as ff
from original.features import part_overrides as po
from original.features import preprocess as pre
from original.quantum.state import BaselineSample, StudentState

ROOT = Path(__file__).resolve().parents[1]
SAMPLES = ROOT / "validation" / "diagnostics" / "document_parts_v2" / "samples"
TEXT = "Title Page\n\nThe first paragraph is mine.\n\nThe second paragraph is also mine.\n"


def _apa_docx_text() -> str:
    from original.upload_utils import extract_text_from_bytes

    return extract_text_from_bytes((SAMPLES / "apa_student.docx").read_bytes(), "paper.docx")


@pytest.fixture(autouse=True)
def _tfidf_tier10(monkeypatch):
    """Tier 10 on its TF-IDF backend, so the route tests need no model download."""
    from original.features import tier10

    monkeypatch.setattr(tier10, "_st_model", None)
    monkeypatch.setattr(tier10, "_st_failed", True)
    # Rule D's piece vectors are not what these tests are about, and are slow.
    monkeypatch.setenv("RULE_D_OBSERVATION", "off")


@pytest.fixture
def splitter(monkeypatch):
    monkeypatch.setenv("MATTER_SPLITTER_ENABLED", "1")
    monkeypatch.setenv("PAPER_PROFILE_ENABLED", "1")
    # Past papers carry the splitter's measurement too, so a score uses it.
    monkeypatch.setenv("UPLOAD_ALSO_MEASURE", "matter")


# ── validation ───────────────────────────────────────────────────────────────


def test_no_choice_is_none():
    assert po.validate(TEXT, None, None) is None
    assert po.validate(TEXT, [], []) is None


def test_a_valid_choice_is_kept_sorted_and_hashable():
    o = po.validate(TEXT, [[0, 10], (12, 20)], [[30, 40]])
    assert o == po.PartOverride(((0, 10), (12, 20)), ((30, 40),))
    assert hash(o) == hash(po.PartOverride(((0, 10), (12, 20)), ((30, 40),)))
    assert o.to_doc() == {"exclude_ranges": [[0, 10], [12, 20]], "include_ranges": [[30, 40]]}


@pytest.mark.parametrize(
    "exclude, include, words",
    [
        ([[0, len(TEXT) + 1]], None, "not within the text"),
        ([[-1, 3]], None, "not within the text"),
        ([[5, 5]], None, "not within the text"),
        ([[10, 20], [0, 5]], None, "sorted"),
        ([[0, 10], [5, 15]], None, "sorted"),
        (None, [[0, 10], [9, 15]], "sorted"),
        ([[0, 10]], [[5, 15]], "both set aside and measured"),
        ([[0, 10, 12]], None, "pairs"),
        ("0-10", None, "pairs"),
        ([[0, True]], None, "whole-number"),
        ([[0.0, 3]], None, "whole-number"),
        ([[0, 3]] * 0 + [[i, i + 1] for i in range(65)], None, "more than 64"),
        ([[12, len(TEXT)]], None, "60%"),
    ],
)
def test_a_choice_that_does_not_fit_is_refused(exclude, include, words):
    with pytest.raises(po.OverrideError, match=words):
        po.validate(TEXT, exclude, include)


def test_up_to_sixty_percent_may_be_set_aside():
    text = " ".join(["word"] * 10)
    assert po.validate(text, [[0, len("word " * 6) - 1]], None) is not None  # 6 of 10
    with pytest.raises(po.OverrideError):
        po.validate(text, [[0, len("word " * 7) - 1]], None)  # 7 of 10


def test_a_stored_choice_that_no_longer_fits_is_ignored():
    assert po.PartOverride.from_doc({"exclude_ranges": [[0, 999]]}, "short") is None
    assert po.PartOverride.from_doc("garbage", "short") is None
    assert po.PartOverride.from_doc(None, "short") is None
    sample = BaselineSample(text=TEXT, vector=np.zeros(1), provenance="verified", auth_weight=1.0)
    assert po.of_sample(sample) is None
    sample.part_overrides = {"exclude_ranges": [[0, 10]], "include_ranges": []}
    assert po.of_samples([sample]) == {TEXT: po.PartOverride(((0, 10),), ())}


# ── the hook ─────────────────────────────────────────────────────────────────


def test_combine_adds_included_and_removes_excluded_ranges():
    o = po.PartOverride(exclude=((5, 8),), include=((20, 30),))
    assert po.combine([(0, 10), (25, 40)], o) == [(0, 5), (8, 10), (20, 40)]
    assert po.combine([], po.PartOverride(include=((3, 4),))) == [(3, 4)]
    assert po.combine([(0, 10)], po.PartOverride(exclude=((0, 10),))) == []


def test_without_a_choice_the_rules_ranges_are_returned_untouched(monkeypatch):
    segments = [(0, 4), (9, 12)]
    assert po.apply(TEXT, segments) is segments
    with po.applying({"another paper": po.PartOverride(exclude=((0, 1),))}):
        assert po.apply(TEXT, segments) is segments
    for on in ("0", "1"):
        monkeypatch.setenv("MATTER_SPLITTER_ENABLED", on)
        before = pre.body_segments(TEXT)
        with po.applying({}):
            assert pre.body_segments(TEXT) == before
        assert pre.preprocess(TEXT) == pre.preprocess(TEXT)


@pytest.mark.parametrize("splitter_on", ["0", "1"])
def test_a_choice_wins_over_the_rules_only_while_in_force(monkeypatch, splitter_on):
    monkeypatch.setenv("MATTER_SPLITTER_ENABLED", splitter_on)
    first = TEXT.index("The first")
    second = TEXT.index("The second")
    before = pre.preprocess(TEXT)[0]
    with po.applying({TEXT: po.PartOverride(exclude=((first, second),))}):
        cut = pre.preprocess(TEXT)[0]
        assert "first paragraph" not in cut and "second paragraph" in cut
        with po.applying({TEXT: None}):  # a nested block may lift the choice
            assert pre.preprocess(TEXT)[0] == before
    assert pre.preprocess(TEXT)[0] == before


def test_measuring_the_title_page_puts_it_back(monkeypatch):
    monkeypatch.setenv("MATTER_SPLITTER_ENABLED", "1")
    text = _apa_docx_text()
    from original.features.matter import find_parts

    title = next(r for r in find_parts(text).set_aside if r.kind == "title_page")
    before = pre.preprocess(text)[0]
    assert "Hannah Price" not in before
    with po.applying({text: po.PartOverride(include=((title.start, title.end),))}):
        assert "Hannah Price" in pre.preprocess(text)[0]


def test_the_choice_never_leaks_into_another_context():
    import contextvars

    def inner():
        po.set_in_force({TEXT: po.PartOverride(exclude=((0, 5),))})
        return po.for_text(TEXT)

    assert contextvars.copy_context().run(inner) is not None
    assert po.for_text(TEXT) is None


def test_text_caches_key_on_the_choice(monkeypatch):
    monkeypatch.setenv("MATTER_SPLITTER_ENABLED", "1")
    calls = []

    @ff.text_cache(maxsize=8)
    def measured(text):
        calls.append(1)
        return "".join(text[a:b] for a, b in pre.body_segments(text))

    plain = measured(TEXT)
    assert measured(TEXT) == plain and len(calls) == 1
    with po.applying({TEXT: po.PartOverride(exclude=((0, 12),))}):
        assert measured(TEXT) != plain
    assert measured(TEXT) == plain and len(calls) == 2


def test_evidence_reads_the_same_ranges_as_the_measurement(monkeypatch):
    from original import evidence

    monkeypatch.setenv("MATTER_SPLITTER_ENABLED", "1")
    first = TEXT.index("The first")
    second = TEXT.index("The second")
    with po.applying({TEXT: po.PartOverride(exclude=((first, second),))}):
        prose = pre.preprocess(TEXT)[0]
        view = evidence.engine_view(TEXT)
    assert view is not None and "first paragraph" not in prose


# ── storage ──────────────────────────────────────────────────────────────────


def _sample(text: str = TEXT, choice: dict | None = None) -> BaselineSample:
    return BaselineSample(
        text=text,
        vector=np.full(FEATURE_DIM, 0.5),
        provenance="verified",
        auth_weight=1.0,
        part_overrides=choice,
    )


CHOICE = {"exclude_ranges": [[0, 10]], "include_ranges": []}


def test_a_paper_with_no_choice_stores_exactly_as_before():
    from original.postgres_repository import PostgresRepository

    doc = json.loads(store._serialize(StudentState("t:a", samples=[_sample()])))
    assert "part_overrides" not in doc["samples"][0]
    pg = PostgresRepository._state_to_doc(StudentState("t:a", samples=[_sample()]))
    assert "part_overrides" not in pg["samples"][0]


def test_the_choice_round_trips_through_both_documents():
    from original.postgres_repository import PostgresRepository

    state = StudentState("t:a", samples=[_sample(choice=CHOICE), _sample("Another.")])
    back = store._deserialize(store._serialize(state))
    assert [s.part_overrides for s in back.samples] == [CHOICE, None]
    pg_back = PostgresRepository._doc_to_state(PostgresRepository._state_to_doc(state))
    assert [s.part_overrides for s in pg_back.samples] == [CHOICE, None]


def _postgres_available() -> bool:
    if not os.environ.get("DATABASE_URL", "").startswith("postgresql"):
        return False
    from original.db import postgres_session

    try:
        postgres_session.reset_engine()
        with postgres_session.get_engine().connect():
            return True
    except Exception:
        return False


@pytest.fixture(params=["sqlite", pytest.param("postgres", marks=pytest.mark.postgres)])
def repo(request, store_reset):
    from original.repository import get_repository, reset_repository

    reset_repository()
    if request.param == "sqlite":
        yield get_repository()
    else:
        if not _postgres_available():
            pytest.skip("uninformative, no reachable Postgres; set DATABASE_URL to run")
        from original.db import postgres_session
        from original.db.models.live import LiveBase
        from original.postgres_repository import PostgresRepository

        engine = postgres_session.get_engine()
        LiveBase.metadata.create_all(bind=engine)
        with engine.begin() as conn:
            for table in reversed(LiveBase.metadata.sorted_tables):
                conn.execute(table.delete())
        yield PostgresRepository()
    reset_repository()


def test_the_choice_survives_the_repository(repo):
    repo.put(StudentState("t:a", samples=[_sample(choice=CHOICE), _sample("Another one.")]))
    got = repo.get("t:a")
    assert [s.part_overrides for s in got.samples] == [CHOICE, None]
    got.samples[0].part_overrides = None
    repo.put(got)
    assert repo.get("t:a").samples[0].part_overrides is None


def test_a_backfill_measures_with_the_stored_choice(repo):
    spec = importlib.util.spec_from_file_location(
        "backfill_measurements_po", ROOT / "scripts" / "backfill_measurements.py"
    )
    bf = importlib.util.module_from_spec(spec)
    sys.modules["backfill_measurements_po"] = bf
    spec.loader.exec_module(bf)
    seen = []

    def extract(text):
        seen.append(po.for_text(text))
        return np.full(FEATURE_DIM, 0.25)

    repo.put(StudentState("t:a", samples=[_sample(choice=CHOICE), _sample("Another one.")]))
    bf.backfill(repo, "matter", apply=True, extract=extract)
    assert seen == [po.PartOverride(((0, 10),), ()), None]
    assert repo.get("t:a").samples[0].part_overrides == CHOICE


# ── the routes ───────────────────────────────────────────────────────────────

BASELINES = [
    (
        "Running Head\n\nOn the river at dawn the boats move slowly, and the men who row them "
        "speak little. I have watched them for years and I still cannot say what they think. "
        "The water is grey, the light is thin, and every stroke sounds the same as the last. "
    )
    * 6,
    (
        "My Second Paper\n\nIn the market the sellers call out prices that nobody believes. "
        "I walk past them slowly, because I like the noise and the smell of bread. Nobody "
        "minds a slow walker there, and I have never been asked to hurry along. "
    )
    * 6,
    (
        "A Third Paper\n\nThe library was quiet when I came in, and the clock over the desk "
        "was ten minutes slow. I found a seat by the window and read until it was dark. "
        "Nobody spoke to me, and I was glad of it, because I had a great deal to read. "
    )
    * 6,
]


def _seed(sid: str) -> None:
    """Three counted past papers, stored directly (no extraction), each also
    carrying the splitter's measurement so a score with it switched on uses it."""
    from original.constants import AUTH_WEIGHTS

    flat = np.full(FEATURE_DIM, 0.5)
    store.put(
        StudentState(
            sid,
            samples=[
                BaselineSample(
                    text=text,
                    vector=flat.copy(),
                    provenance="proctored",
                    auth_weight=AUTH_WEIGHTS["proctored"],
                    assignment=f"Paper {i + 1}",
                    extra_vectors={"matter": flat.copy()},
                )
                for i, text in enumerate(BASELINES)
            ],
        )
    )


def _login(client, institution, email):
    r = client.post(
        "/student-auth/login", json={"email": email, "institution": institution, "name": email}
    )
    assert r.status_code == 200, r.text
    body = r.json()
    return body["token"], body["student_id"]


def test_a_student_session_cannot_choose_parts(live_client, store_reset):
    token, sid = _login(live_client, "Parts Academy", "parts@student.edu")
    for body in (
        {"exclude_ranges": [[0, 5]]},
        {"include_ranges": []},
        {"exclude_ranges": None, "include_ranges": [[0, 5]]},
    ):
        r = live_client.post(
            f"/students/{sid}/score",
            json={"text": BASELINES[0], **body},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r.status_code == 403, r.text[:300]
        assert "staff" in r.json()["detail"].lower()
    r = live_client.get(
        f"/students/{sid}/samples/0/parts", headers={"Authorization": f"Bearer {token}"}
    )
    assert r.status_code == 403


def test_staff_choice_is_validated_and_changes_the_measurement(live_client, store_reset, splitter):
    sid = "parts_school_ana"
    _seed(sid)
    paper = _apa_docx_text()
    url = f"/students/{sid}/score"
    bad = live_client.post(url, json={"text": paper, "exclude_ranges": [[0, len(paper) + 5]]})
    assert bad.status_code == 422
    plain = live_client.post(url, json={"text": paper, "submission_id": "s1"})
    assert plain.status_code == 200

    parts = plain.json()["evidence"]["paper_profile"]["this_paper"]["parts"]
    abstract = next(p for p in parts if p["kind"] == "abstract")
    assert abstract["status"] == "set_aside" and abstract["by"] == "rules"
    measured = live_client.post(
        url, json={"text": paper, "submission_id": "s1", "include_ranges": abstract["ranges"]}
    )
    assert measured.status_code == 200
    assert measured.json()["feature_vector"] != plain.json()["feature_vector"]
    again = measured.json()["evidence"]["paper_profile"]["this_paper"]["parts"]
    after = next(p for p in again if p["kind"] == "abstract")
    assert (after["status"], after["by"], after["rules_status"]) == (
        "measured",
        "teacher",
        "set_aside",
    )


def test_a_past_paper_choice_is_stored_and_measured_again(live_client, store_reset, splitter):
    sid = "parts_school_ben"
    _seed(sid)
    url = f"/students/{sid}/samples/0/parts"
    got = live_client.get(url)
    assert got.status_code == 200 and got.json()["enabled"] is True
    assert got.json()["exclude_ranges"] == [] and got.json()["include_ranges"] == []
    before = store.get(sid).samples[0].vector.copy()

    head = len("Running Head\n\n")
    cut = [head, head + 200]  # the opening sentences of the paper
    r = live_client.put(url, json={"exclude_ranges": [cut]})
    assert r.status_code == 200, r.text[:300]
    sample = store.get(sid).samples[0]
    assert sample.part_overrides == {"exclude_ranges": [cut], "include_ranges": []}
    assert r.json()["exclude_ranges"] == [cut]
    chosen = [p for p in r.json()["parts"] if p["by"] == "teacher"]
    assert chosen and all(p["status"] == "set_aside" for p in chosen)
    assert sample.vector.shape == before.shape and not np.allclose(sample.vector, before)
    assert set(sample.extra_vectors) == {"matter"}
    measured_once = sample.vector.copy()
    # Back to the rules: the choice is gone and the paper measures as an upload would.
    r = live_client.put(url, json={"exclude_ranges": [], "include_ranges": []})
    assert r.status_code == 200
    sample = store.get(sid).samples[0]
    assert sample.part_overrides is None and not np.allclose(sample.vector, measured_once)
    from original.features.pipeline import feature_vector

    with ff.measuring("v1"):
        assert np.allclose(sample.vector, feature_vector(BASELINES[0]))

    assert live_client.put(url, json={"exclude_ranges": [[0, 10**6]]}).status_code == 422
    assert live_client.get(f"/students/{sid}/samples/9/parts").status_code == 404
    assert live_client.get("/students/parts_school_nobody/samples/0/parts").status_code == 404


def test_the_past_paper_control_is_off_with_either_switch_off(
    live_client, store_reset, monkeypatch
):
    sid = "parts_school_cy"
    _seed(sid)
    for splitter_on, profile_on in (("0", "1"), ("1", "0"), ("0", "0")):
        monkeypatch.setenv("MATTER_SPLITTER_ENABLED", splitter_on)
        monkeypatch.setenv("PAPER_PROFILE_ENABLED", profile_on)
        got = live_client.get(f"/students/{sid}/samples/0/parts")
        assert got.status_code == 200 and got.json() == {"enabled": False, "index": 0, "parts": []}
        put = live_client.put(f"/students/{sid}/samples/0/parts", json={"exclude_ranges": [[0, 4]]})
        assert put.status_code == 409
    assert store.get(sid).samples[0].part_overrides is None
