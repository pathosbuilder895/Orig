"""A teacher's own choice of which parts of a paper are measured
(original/features/part_overrides.py, steps 4-5 of the document-parts plan).

The rule under test: a choice changes only the splitter's measurement
(``matter``), never the default ``v1`` vector, and does nothing at all unless
MATTER_SPLITTER_ENABLED and PAPER_PROFILE_ENABLED are both on. A choice
belongs to one paper (it rides on that paper's text object), never to a
string: a submission whose words equal a past paper's never picks up that
paper's choice. Checked here: the validation (whole lines, a word per range,
the cap against what the rules keep, includes only of the rules' parts, the
PDF tag and page markers never split), the one hook in
``preprocess.body_segments``, caches, storage on both backends, the backfill,
and the score and past-paper routes (staff only, 409 with a switch off).
"""

from __future__ import annotations

import importlib.util
import json
import os
import pickle
import sys
from pathlib import Path

import numpy as np
import pytest

from original import store
from original.constants import FEATURE_DIM
from original.features import feature_flags as ff
from original.features import part_overrides as po
from original.features import preprocess as pre
from original.features.matter import PAGE_MARK, PDF_TAG, find_parts, kept_ranges
from original.quantum.state import BaselineSample, StudentState

ROOT = Path(__file__).resolve().parents[1]
SAMPLES = ROOT / "validation" / "diagnostics" / "document_parts_v2" / "samples"
MLA = (ROOT / "tests" / "fixtures" / "paper_matter" / "mla_docx.txt").read_text(encoding="utf-8")
FIRST = MLA.index("Wendell Berry writes")
SECOND = MLA.index("Critics have often")


def _upload(name: str) -> str:
    from original.upload_utils import extract_text_from_bytes

    return extract_text_from_bytes((SAMPLES / name).read_bytes(), name)


@pytest.fixture(autouse=True)
def _quiet(monkeypatch):
    """Tier 10 on its TF-IDF backend (no model download), rule D off (slow),
    and every switch this file turns on starts off."""
    from original.features import tier10

    monkeypatch.setattr(tier10, "_st_model", None)
    monkeypatch.setattr(tier10, "_st_failed", True)
    monkeypatch.setenv("RULE_D_OBSERVATION", "off")
    for name in ("MATTER_SPLITTER_ENABLED", "PAPER_PROFILE_ENABLED", "UPLOAD_ALSO_MEASURE"):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def switches(monkeypatch):
    monkeypatch.setenv("MATTER_SPLITTER_ENABLED", "1")
    monkeypatch.setenv("PAPER_PROFILE_ENABLED", "1")


def _cut_first() -> po.PartOverride:
    return po.validate(MLA, [[FIRST, SECOND]], None)


# ── validation ───────────────────────────────────────────────────────────────


def test_no_choice_is_none():
    assert po.validate(MLA, None, None) is None
    assert po.validate(MLA, [], []) is None


def test_ranges_are_snapped_to_whole_lines():
    inside = po.validate(MLA, [[FIRST + 10, FIRST + 20]], None)
    line_end = MLA.index("\n", FIRST) + 1
    assert inside.exclude == ((FIRST, line_end),)
    assert inside.to_doc() == {"exclude_ranges": [[FIRST, line_end]], "include_ranges": []}
    assert hash(inside) == hash(po.PartOverride(((FIRST, line_end),), ()))


@pytest.mark.parametrize(
    "exclude, include, words",
    [
        ([[0, len(MLA) + 1]], None, "not within the text"),
        ([[-1, 3]], None, "not within the text"),
        ([[5, 5]], None, "not within the text"),
        ([[20, 30], [0, 5]], None, "sorted"),
        ([[0, 10], [5, 15]], None, "sorted"),
        ([[0, 10, 12]], None, "pairs"),
        ("0-10", None, "pairs"),
        ([[0, True]], None, "whole-number"),
        ([[0.0, 3]], None, "whole-number"),
        ([[i, i + 1] for i in range(65)], None, "more than 64"),
        ([[FIRST - 1, FIRST]], None, "holds no words"),  # a blank line
        (None, [[0, len(MLA)]], "not a part"),  # the whole paper
        (None, [[FIRST, SECOND]], "not a part"),  # prose the rules measure
        ([[1020, 1040]], [[1020, 1290]], "both set aside and measured"),
    ],
)
def test_a_choice_that_does_not_fit_is_refused(exclude, include, words):
    with pytest.raises(po.OverrideError, match=words):
        po.validate(MLA, exclude, include)


def test_single_spaces_are_not_words():
    """W3: 64 one-space ranges once counted zero words and passed."""
    spaces = [i for i, ch in enumerate(MLA[FIRST:SECOND], FIRST) if ch == " "][:64]
    with pytest.raises(po.OverrideError, match="no words"):
        po.validate(MLA, [[i, i + 1] for i in spaces], None)


def test_the_cap_counts_the_words_the_rules_keep_not_the_whole_text():
    """W2: a long list of sources once let a teacher set aside the whole body
    (under 60% of the text, all of what the rules measure)."""
    padded = (
        MLA
        + "\n"
        + "".join(f"Smith, J{i}. A title of a work. Publisher, 2020.\n\n" for i in range(200))
    )
    body = [(a, b) for a, b in kept_ranges(padded)]
    kept = sum(len(padded[a:b].split()) for a, b in body)
    assert kept < 0.6 * len(padded.split())  # the old cap would have passed it
    with pytest.raises(po.OverrideError, match="60%"):
        po.validate(padded, [[body[0][0], body[-1][1]]], None)
    assert po.validate(padded, [[FIRST, SECOND]], None) is not None  # one paragraph is fine


def test_an_include_must_be_one_of_the_rules_parts():
    parts = find_parts(MLA)
    works = next(r for r in parts.set_aside if r.kind == "back_matter")
    assert po.validate(MLA, None, [[works.start, works.end]]).include == ((works.start, works.end),)
    heading = [r for r in parts.set_aside if r.kind == "front_matter"]
    # Two heading-block lines separated by a blank line are two parts, not one.
    with pytest.raises(po.OverrideError, match="not a part"):
        po.validate(MLA, None, [[heading[0].start, heading[1].end]])
    assert po.validate(MLA, None, [[heading[0].start, heading[0].end]]) is not None


def test_the_pdf_tag_is_never_inside_a_range_and_never_reaches_the_body(switches):
    """W4/finding 6: a range ending on, or reaching into, the PDF tag is cut
    short of it; one holding only the tag holds no words."""
    text = _upload("apa_student.pdf")
    assert text.endswith(PDF_TAG)
    n, end = len(text), len(text) - len(PDF_TAG)
    with pytest.raises(po.OverrideError, match="no words"):
        po.validate(text, [[n - 3, n]], None)
    with pytest.raises(po.OverrideError, match="no words"):
        po.validate(text, [[n - 4, n - 3]], None)
    last = text.rfind("\n", 0, end) + 1
    choice = po.validate(text, [[last + 1, n]], None)
    assert choice.exclude == ((last, end),)
    with ff.measuring("matter"):
        assert PAGE_MARK not in pre._body(po.chosen(text, choice))


@pytest.mark.parametrize("name", ["apa_student.pdf", "apa_student.docx", "turabian.pdf"])
def test_no_page_marker_reaches_the_measured_body_whatever_is_set_aside(switches, name):
    """Every line of the paper set aside on its own (where the cap allows):
    the measured body never carries a page marker or the PDF tag."""
    text = _upload(name)
    starts = [0] + [i + 1 for i, ch in enumerate(text) if ch == "\n"]
    tried = 0
    for a, b in zip(starts, starts[1:] + [len(text)], strict=True):
        if not text[a:b].split():
            continue
        for lo, hi in ((a, b), (max(0, a - 3), min(len(text), b + 3))):
            try:
                choice = po.validate(text, [[lo, hi]], None)
            except po.OverrideError:
                continue
            with ff.measuring("matter"):
                assert PAGE_MARK not in pre._body(po.chosen(text, choice)), (a, b)
            tried += 1
    assert tried > 20


# ── the gate and the hook ────────────────────────────────────────────────────


def test_combine_adds_included_and_removes_excluded_ranges():
    o = po.PartOverride(exclude=((5, 8),), include=((20, 30),))
    assert po.combine([(0, 10), (25, 40)], o) == [(0, 5), (8, 10), (20, 40)]
    assert po.combine([(0, 10)], po.PartOverride(exclude=((0, 10),))) == []


@pytest.mark.parametrize(
    "splitter, profile, measurement",
    [("0", "0", None), ("1", "0", None), ("0", "1", None), ("1", "1", "v1"), ("0", "1", "matter")],
)
def test_a_choice_does_nothing_unless_both_switches_and_the_splitter_measurement(
    monkeypatch, splitter, profile, measurement
):
    monkeypatch.setenv("MATTER_SPLITTER_ENABLED", splitter)
    monkeypatch.setenv("PAPER_PROFILE_ENABLED", profile)
    carried = po.chosen(MLA, _cut_first())

    def measured():
        return pre.body_segments(carried), pre.preprocess(carried)

    if measurement is None:
        assert measured() == (pre.body_segments(MLA), pre.preprocess(MLA))
        assert po.for_text(carried) is None
    else:
        with ff.measuring(measurement):
            assert measured() == (pre.body_segments(MLA), pre.preprocess(MLA))
            assert po.for_text(carried) is None


def test_with_both_switches_on_the_choice_wins_over_the_rules(switches):
    carried = po.chosen(MLA, _cut_first())
    before = pre.preprocess(MLA)[0]
    cut = pre.preprocess(carried)[0]
    assert "Wendell Berry writes" in before and "Wendell Berry writes" not in cut
    assert "Critics have often" in cut
    segments = kept_ranges(MLA)
    assert pre.body_segments(MLA) == segments  # the plain text: the rules alone


def test_measuring_a_title_page_puts_it_back(switches):
    text = _upload("apa_student.docx")
    title = next(r for r in find_parts(text).set_aside if r.kind == "title_page")
    assert "Hannah Price" not in pre.preprocess(text)[0]
    carried = po.chosen(text, po.validate(text, None, [[title.start, title.end]]))
    assert "Hannah Price" in pre.preprocess(carried)[0]


def test_equal_words_are_not_the_same_paper(switches):
    """Finding 3: the choice is the paper's, not the string's."""
    carried = po.chosen(MLA, _cut_first())
    plain = str(carried)
    assert plain == carried and po.for_text(plain) is None
    assert pre.preprocess(plain) == pre.preprocess(MLA) != pre.preprocess(carried)
    assert pickle.loads(pickle.dumps(carried)) == MLA  # never leaves the process with a choice
    assert type(pickle.loads(pickle.dumps(carried))) is str


def test_text_caches_key_on_the_choice(switches):
    calls = []

    @ff.text_cache(maxsize=8)
    def measured(text):
        calls.append(1)
        return "".join(text[a:b] for a, b in pre.body_segments(text))

    plain = measured(MLA)
    carried = po.chosen(MLA, _cut_first())
    assert measured(carried) != plain and measured(MLA) == plain and len(calls) == 2


def test_a_choice_composes_with_a_pdfs_reflow_and_the_evidence_rebuild(switches):
    from original import evidence

    text = _upload("apa_student.pdf")
    assert pre.reflows(text)
    abstract = next(r for r in find_parts(text).set_aside if r.kind == "abstract")
    choice = po.validate(text, None, [[abstract.start, abstract.end]])
    carried = po.chosen(text, choice)
    prose = pre.preprocess(carried)[0]
    assert "This paper studies a funeral sermon" in prose
    assert "This paper studies a funeral sermon" not in pre.preprocess(text)[0]
    view = evidence.engine_view(carried)
    assert view is not None and view.prose.text == prose and PAGE_MARK not in prose


# ── storage ──────────────────────────────────────────────────────────────────


def _sample(text: str = MLA, choice: po.PartOverride | None = None, **kw) -> BaselineSample:
    return BaselineSample(
        text=text,
        vector=np.full(FEATURE_DIM, 0.5),
        provenance="verified",
        auth_weight=1.0,
        part_overrides=po.to_stored(choice, text),
        **kw,
    )


def test_a_paper_with_no_choice_stores_exactly_as_before():
    from original.postgres_repository import PostgresRepository

    doc = json.loads(store._serialize(StudentState("t:a", samples=[_sample()])))
    assert "part_overrides" not in doc["samples"][0]
    pg = PostgresRepository._state_to_doc(StudentState("t:a", samples=[_sample()]))
    assert "part_overrides" not in pg["samples"][0]


def test_the_choice_round_trips_and_belongs_to_its_own_text():
    from original.postgres_repository import PostgresRepository

    state = StudentState("t:a", samples=[_sample(choice=_cut_first()), _sample("Another.")])
    for back in (
        store._deserialize(store._serialize(state)),
        PostgresRepository._doc_to_state(PostgresRepository._state_to_doc(state)),
    ):
        assert po.of_sample(back.samples[0]) == _cut_first()
        assert back.samples[1].part_overrides is None
    # Moved onto another paper's text, a stored choice is ignored.
    moved = _sample("Another paper entirely.\n" * 40)
    moved.part_overrides = state.samples[0].part_overrides
    assert po.of_sample(moved) is None
    assert po.text_of(moved) == moved.text and po.for_text(po.text_of(moved)) is None


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
    repo.put(StudentState("t:a", samples=[_sample(choice=_cut_first()), _sample("Another.")]))
    got = repo.get("t:a")
    assert po.of_sample(got.samples[0]) == _cut_first() and got.samples[1].part_overrides is None
    got.samples[0].part_overrides = None
    repo.put(got)
    assert repo.get("t:a").samples[0].part_overrides is None


def test_a_backfill_measures_the_splitter_with_the_stored_choice_only(repo, monkeypatch):
    spec = importlib.util.spec_from_file_location(
        "backfill_measurements_po", ROOT / "scripts" / "backfill_measurements.py"
    )
    bf = importlib.util.module_from_spec(spec)
    sys.modules["backfill_measurements_po"] = bf
    spec.loader.exec_module(bf)
    seen = []

    def extract(text):
        seen.append((ff.current_measurement(), po.for_text(text)))
        return np.full(FEATURE_DIM, 0.25)

    repo.put(StudentState("t:a", samples=[_sample(choice=_cut_first()), _sample("Another.")]))
    bf.backfill(repo, "matter", apply=True, extract=extract)
    assert seen == [("matter", None), ("matter", None)]  # switches off: the rules alone
    monkeypatch.setenv("MATTER_SPLITTER_ENABLED", "1")
    monkeypatch.setenv("PAPER_PROFILE_ENABLED", "1")
    seen.clear()
    bf.backfill(repo, "fs2+matter", apply=True, extract=extract)
    assert seen == [("fs2+matter", _cut_first()), ("fs2+matter", None)]
    seen.clear()
    bf.backfill(repo, "fs2", apply=True, extract=extract)  # no splitter: no choice
    assert seen == [("fs2", None), ("fs2", None)]


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


def _seed(sid: str, texts=BASELINES, matter: bool = True) -> None:
    """Counted past papers, stored directly (no extraction); with ``matter``
    each also carries the splitter's measurement, so a score uses it."""
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
                    extra_vectors={"matter": flat.copy()} if matter else None,
                )
                for i, text in enumerate(texts)
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


def test_a_student_session_cannot_choose_parts(live_client, store_reset, switches):
    token, sid = _login(live_client, "Parts Academy", "parts@student.edu")
    auth = {"Authorization": f"Bearer {token}"}
    for body in (
        {"exclude_ranges": [[0, 5]]},
        {"include_ranges": []},
        {"exclude_ranges": None, "include_ranges": [[0, 5]]},
    ):
        r = live_client.post(
            f"/students/{sid}/score", json={"text": BASELINES[0], **body}, headers=auth
        )
        assert r.status_code == 403, r.text[:300]
        assert "staff" in r.json()["detail"].lower()
    for method in ("get", "delete"):
        r = getattr(live_client, method)(f"/students/{sid}/samples/0/parts", headers=auth)
        assert r.status_code == 403
    r = live_client.put(f"/students/{sid}/samples/0/parts", json={}, headers=auth)
    assert r.status_code == 403


def test_a_choice_is_refused_with_a_switch_off(live_client, store_reset, monkeypatch):
    """Finding 2 (W1): with every switch off, ranges once changed the score."""
    sid = "parts_school_off"
    _seed(sid)
    for splitter, profile in (("0", "0"), ("1", "0"), ("0", "1")):
        monkeypatch.setenv("MATTER_SPLITTER_ENABLED", splitter)
        monkeypatch.setenv("PAPER_PROFILE_ENABLED", profile)
        r = live_client.post(
            f"/students/{sid}/score", json={"text": MLA, "exclude_ranges": [[FIRST, SECOND]]}
        )
        assert r.status_code == 409, r.text[:300]
        r = live_client.put(f"/students/{sid}/samples/0/parts", json={"exclude_ranges": [[0, 12]]})
        assert r.status_code == 409
        got = live_client.get(f"/students/{sid}/samples/0/parts").json()
        assert got == {"enabled": False, "index": 0, "parts": []}
    assert store.get(sid).samples[0].part_overrides is None


def test_staff_choice_is_checked_and_moves_only_the_splitter_measurement(
    live_client, store_reset, switches
):
    sid = "parts_school_ana"
    _seed(sid)
    paper = _upload("apa_student.docx")
    url = f"/students/{sid}/score"
    bad = live_client.post(url, json={"text": paper, "include_ranges": [[0, len(paper)]]})
    assert bad.status_code == 422 and "not a part" in bad.json()["detail"]
    plain = live_client.post(url, json={"text": paper, "submission_id": "s1"})
    assert plain.status_code == 200
    assert plain.json()["measurement"]["used"] == "matter"
    profile = plain.json()["evidence"]["paper_profile"]["this_paper"]
    abstract = next(p for p in profile["parts"] if p["kind"] == "abstract")
    assert abstract["status"] == "set_aside" and abstract["by"] == "rules"
    assert profile["choice"] == {"exclude_ranges": [], "include_ranges": []}
    measured = live_client.post(
        url, json={"text": paper, "submission_id": "s1", "include_ranges": abstract["ranges"]}
    )
    assert measured.status_code == 200
    assert measured.json()["feature_vector"] != plain.json()["feature_vector"]
    again = measured.json()["evidence"]["paper_profile"]["this_paper"]
    after = next(p for p in again["parts"] if p["kind"] == "abstract")
    assert (after["status"], after["by"], after["rules_status"]) == (
        "measured",
        "teacher",
        "set_aside",
    )
    assert again["choice"]["include_ranges"] == abstract["ranges"]


def test_a_past_papers_choice_is_its_own(live_client, store_reset, switches):
    """Finding 3's witness: a submission whose words equal a past paper's does
    not pick up that paper's stored choice, and a past paper's choice moves
    only that paper's splitter measurement, never its v1 vector."""
    sid = "parts_school_ben"
    papers = [MLA, *BASELINES[1:]]
    _seed(sid, papers)
    score = lambda: live_client.post(  # noqa: E731
        f"/students/{sid}/score", json={"text": MLA, "submission_id": "same"}
    )
    before = score()
    assert before.status_code == 200
    v1 = store.get(sid).samples[0].vector.copy()
    matter = store.get(sid).samples[0].extra_vectors["matter"].copy()

    r = live_client.put(
        f"/students/{sid}/samples/0/parts", json={"exclude_ranges": [[FIRST, SECOND]]}
    )
    assert r.status_code == 200, r.text[:300]
    sample = store.get(sid).samples[0]
    assert np.array_equal(sample.vector, v1)  # the default measurement is never touched
    assert not np.array_equal(sample.extra_vectors["matter"], matter)
    assert po.of_sample(sample) == _cut_first()
    assert r.json()["exclude_ranges"] == [list(_cut_first().exclude[0])]
    assert r.json()["measurement_in_use"] is True

    after = score()
    assert after.status_code == 200
    assert after.json()["feature_vector"] == before.json()["feature_vector"]
    past = after.json()["evidence"]["paper_profile"]["past_papers"][0]
    assert any(p["by"] == "teacher" for p in past["parts"])  # the past paper keeps its own
    assert all(
        p["by"] == "rules" for p in after.json()["evidence"]["paper_profile"]["this_paper"]["parts"]
    )


def test_back_to_the_rules_whatever_the_switches_say(
    live_client, store_reset, switches, monkeypatch
):
    from original.features.pipeline import feature_vector

    sid = "parts_school_cy"
    _seed(sid, [MLA, *BASELINES[1:]])
    url = f"/students/{sid}/samples/0/parts"
    assert live_client.put(url, json={"exclude_ranges": [[FIRST, SECOND]]}).status_code == 200
    monkeypatch.setenv("PAPER_PROFILE_ENABLED", "0")
    assert live_client.delete(url).status_code == 200
    sample = store.get(sid).samples[0]
    assert sample.part_overrides is None
    with ff.measuring("matter"):
        assert np.allclose(sample.extra_vectors["matter"], feature_vector(MLA))
    assert live_client.put(url, json={}).status_code == 200  # already the rules
    assert live_client.get(f"/students/{sid}/samples/9/parts").status_code == 404


def test_the_get_says_when_the_splitter_measurement_is_not_in_use(
    live_client, store_reset, switches
):
    """Finding 7: one past paper without the splitter's measurement, so scores
    use the default; the GET says so, and a PUT measures only that paper's
    splitter measurement (creating it), never its default vector."""
    sid = "parts_school_di"
    _seed(sid, [MLA, *BASELINES[1:]], matter=False)
    url = f"/students/{sid}/samples/0/parts"
    got = live_client.get(url).json()
    assert got["enabled"] is True and got["measurement_in_use"] is False
    assert "3 of 3 past papers" in got["measurement_note"]
    v1 = store.get(sid).samples[0].vector.copy()
    put = live_client.put(url, json={"exclude_ranges": [[FIRST, SECOND]]}).json()
    sample = store.get(sid).samples[0]
    assert np.array_equal(sample.vector, v1) and set(sample.extra_vectors) == {"matter"}
    assert "2 of 3 past papers" in put["measurement_note"]
    assert store.get(sid).samples[1].extra_vectors is None


def test_with_a_switch_off_stored_choices_change_nothing(
    live_client, store_reset, switches, monkeypatch
):
    """Finding 4 (W5): a student with stored choices scores byte-identically
    to one without once a switch is off."""
    _seed("parts_school_x", [MLA, *BASELINES[1:]])
    _seed("parts_school_y", [MLA, *BASELINES[1:]])
    choice = {"exclude_ranges": [[FIRST, SECOND]]}
    for sid in ("parts_school_x", "parts_school_y"):
        r = live_client.put(f"/students/{sid}/samples/0/parts", json=choice)
        assert r.status_code == 200
    # y goes back to the rules: its splitter measurement is then the rules'
    # own, the one x keeps beside its choice.
    assert live_client.delete("/students/parts_school_y/samples/0/parts").status_code == 200
    assert store.get("parts_school_x").samples[0].part_overrides is not None
    assert store.get("parts_school_y").samples[0].part_overrides is None
    for splitter, profile in (("1", "1"), ("0", "0"), ("1", "0"), ("0", "1")):
        monkeypatch.setenv("MATTER_SPLITTER_ENABLED", splitter)
        monkeypatch.setenv("PAPER_PROFILE_ENABLED", profile)
        out = []
        for sid in ("parts_school_x", "parts_school_y"):
            body = live_client.post(
                f"/students/{sid}/score", json={"text": BASELINES[1], "submission_id": "same"}
            ).json()
            for key in ("student_id", "submission_id", "timestamp", "scored_at"):
                body.pop(key, None)
            out.append(
                json.dumps(body, sort_keys=True)
                .replace("parts_school_x", "S")
                .replace("parts_school_y", "S")
            )
        if splitter == profile == "1":  # both on: x's choice is in its measurement
            assert out[0] != out[1]
        else:
            assert out[0] == out[1], (splitter, profile)
