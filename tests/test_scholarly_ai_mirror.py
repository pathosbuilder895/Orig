import hashlib
import inspect
import json
from collections import Counter
from types import SimpleNamespace

import pytest

from validation.scholarly import ai_mirror, loader, policy, rule_d
from validation.scholarly.schema import ScholarlyManifest, ScholarlyPaper


def T(student_id):
    return SimpleNamespace(student_id=student_id)


def test_trial_docs_without_extra_equals_probe_docs(monkeypatch):
    monkeypatch.setattr(rule_d, "probe_docs", lambda *a: [("h", 0, None, "honest")])
    assert rule_d._trial_docs(T("A1"), ["A1"], {}, {}, {}, 7) == [("h", 0, None, "honest")]


def test_trial_docs_appends_only_this_authors_extras(monkeypatch):
    monkeypatch.setattr(rule_d, "probe_docs", lambda *a: [])
    extra = {"A1": [("ai text", 1, None, "ai")], "A2": [("other", 1, None, "ai")]}
    assert rule_d._trial_docs(T("A1"), ["A1", "A2"], {}, {}, {}, 7, extra) == [("ai text", 1, None, "ai")]


def test_build_scores_extra_docs_defaults_to_none():
    assert inspect.signature(rule_d.build_scores).parameters["extra_docs"].default is None


# ----------------------------------------------------------- selection + sheet --
CANDIDATES = json.loads((loader.HERE / "candidates" / "humanities.json").read_text(encoding="utf-8"))
MANIFEST = loader.load_manifest("humanities")
TARGETS = ai_mirror.select_targets(MANIFEST, CANDIDATES)


def _fake_author(partition, start):
    i = start
    while policy.partition_of(f"A{i}") != partition:
        i += 1
    return f"A{i}"


def test_new_paper_for_matches_loader(tmp_path):
    aids, start = [], 0
    for _ in range(3):
        a = _fake_author("development", start)
        aids.append(a)
        start = int(a[1:]) + 1
    papers = []
    for a in aids:
        for i in range(6):
            text = f"{a} paper {i} " + "word " * 1600 + "\n\n"
            d = tmp_path / "humanities" / "texts" / a
            d.mkdir(parents=True, exist_ok=True)
            (d / f"W{a}{i}.txt").write_text(text, encoding="utf-8")
            papers.append(ScholarlyPaper(
                source="openalex", source_paper_id=f"W{a}{i}", author_id=a, year=2010, field="12",
                licence="cc-by", url="https://example.org/p.pdf", word_count=1600,
                text_sha256=hashlib.sha256(text.encode("utf-8")).hexdigest(),
                partition="development"))
    m = ScholarlyManifest(collection="humanities", created_at="2026-11-11", papers=papers)
    ts = loader.load_trials("humanities", "development", past_words=1200, new_words=1200, seed=7,
                            manifest=m, cache=tmp_path)
    assert len(ts.trials) == 3
    for t in ts.trials:
        assert ai_mirror.new_paper_for(m.authors()[t.student_id], 7) == t.honest_ids[0]


def test_new_paper_for_raises_without_new_paper():
    ps = [SimpleNamespace(source_paper_id=f"W{i}", word_count=100) for i in range(6)]
    with pytest.raises(ValueError):
        ai_mirror.new_paper_for(ps, 7)


def test_select_targets_deterministic_locked_only():
    a = ai_mirror.select_targets(loader.load_manifest("humanities"), CANDIDATES)
    assert a == TARGETS
    assert len(a) == 20 and len({t.author_id for t in a}) == 20
    assert all(policy.partition_of(t.author_id) == "locked_test" for t in a)
    assert [t.rank for t in a] == list(range(20))


def test_tools_split_7_7_6():
    assert Counter(t.tool for t in TARGETS) == {"claude": 7, "chatgpt": 7, "gemini": 6}


def test_select_targets_raises_when_paper_not_in_candidates():
    with pytest.raises(KeyError):
        ai_mirror.select_targets(MANIFEST, {"authors": []})


def test_sheet_carries_exact_prompts():
    sheet = ai_mirror.render_sheet(TARGETS)
    for t in TARGETS:
        assert ai_mirror.PROMPT.format(title=t.title, venue=t.venue) in sheet
        assert f"validation/scholarly/ai_mirror/raw/{t.author_id}.txt" in sheet
    assert chr(0x2014) not in sheet and chr(0x2015) not in sheet
    assert ai_mirror.CONTINUE_PROMPT in sheet


def test_prompts_have_no_dashes_and_one_line():
    for s in (ai_mirror.PROMPT, ai_mirror.CONTINUE_PROMPT):
        assert "\n" not in s and chr(0x2014) not in s


def test_load_targets_round_trips_and_main_writes(tmp_path, monkeypatch):
    monkeypatch.setattr(ai_mirror, "AI_DIR", tmp_path)
    ai_mirror.main(["select"])
    data = json.loads((tmp_path / "targets_humanities.json").read_text(encoding="utf-8"))
    assert data["study_id"] == ai_mirror.STUDY_ID and data["seed"] == 7
    assert ai_mirror.load_targets() == TARGETS
    assert ai_mirror.load_targets(tmp_path / "targets_humanities.json") == TARGETS
    assert (tmp_path / "prompts_humanities.md").read_text(encoding="utf-8") == ai_mirror.render_sheet(TARGETS)


# ------------------------------------------------------------- cleaning + intake --
REF1 = ("Smith, John. (2010). A long study of grace and its many consequences in late antiquity. "
        "Oxford University Press, pp. 1-300.")
REF2 = ("Jones, Mary. (2012). Reading the fathers again for a new generation of scholars. "
        "Journal of Early Christian Studies, Vol. 5, doi 10.1000/xyz.")
BODY = " ".join(["grace"] * 20)

RAW = ("# A Study of Grace\n\n**Introduction** " + "word " * 30 + "\n\n## Part two\n\n- "
       + "bullet words " * 10 + "see https://example.org now.\n\nshort para here\n\n"
       "References\n\n" + REF1 + "\n\n" + REF2 + "\n")


def test_normalise_strips_markdown_title_short_paras_and_references():
    out = ai_mirror.normalise_ai_text(RAW, "A Study of Grace")
    for bad in ("#", "**", "A Study of Grace", "References", "Smith, John", "Jones, Mary", "https://", "short para here"):
        assert bad not in out
    assert out.count("\n\n") == 1
    assert not out.lstrip().startswith("-")


def test_normalise_numbered_and_underscore_markers_and_title_with_punctuation():
    raw = ("**A Study, of Grace!**\n\n1. " + "alpha " * 14 + "\n\n_" + "beta " * 13 + "gamma_ done here.\n\n"
           "Works Cited:\n\n" + REF1 + "\n\n" + REF2 + "\n")
    out = ai_mirror.normalise_ai_text(raw, "a study of grace")
    assert out.split("\n\n")[0].startswith("alpha")
    assert "_" not in out and "Works" not in out and "Study" not in out
    assert out.count("\n\n") == 1


def _setup(tmp_path, monkeypatch, raw_words=1500):
    monkeypatch.setattr(ai_mirror, "AI_DIR", tmp_path)
    t = ai_mirror.Target(rank=0, author_id="A1", paper_id="P1", title="T", venue="V", tool="claude")
    (tmp_path / "targets_humanities.json").write_text(
        json.dumps({"targets": [ai_mirror.dataclasses.asdict(t)]}), encoding="utf-8")
    (tmp_path / "raw").mkdir()
    (tmp_path / "raw" / "A1.txt").write_text("para " * raw_words, encoding="utf-8")


def test_intake_records_hash_and_word_count(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    e = ai_mirror.intake("A1", "GPT-x", "2026-11-17", "app", False)
    text = (tmp_path / "texts" / "A1.txt").read_text(encoding="utf-8")
    assert e["words"] == len(text.split())
    assert e["sha256"] == hashlib.sha256(text.encode("utf-8")).hexdigest()
    assert e["raw_sha256"] == hashlib.sha256((tmp_path / "raw" / "A1.txt").read_bytes()).hexdigest()
    assert (e["paper_id"], e["tool"], e["route"], e["continued"]) == ("P1", "claude", "app", False)
    m = ai_mirror.load_ai_manifest()
    assert m["study_id"] == ai_mirror.STUDY_ID and m["collection"] == "humanities"
    assert m["papers"]["A1"] == e


def test_intake_upserts_and_is_stable(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    ai_mirror.intake("A1", "m1", "2026-11-17", "app", False)
    ai_mirror.intake("A1", "m2", "2026-11-18", "subagent", True)
    m = ai_mirror.load_ai_manifest()
    assert list(m["papers"]) == ["A1"] and m["papers"]["A1"]["model"] == "m2"
    assert (tmp_path / "manifest_humanities.json").read_text(encoding="utf-8").endswith("}\n")


def test_load_ai_manifest_empty_when_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(ai_mirror, "AI_DIR", tmp_path)
    assert ai_mirror.load_ai_manifest() == {
        "study_id": ai_mirror.STUDY_ID, "collection": "humanities", "papers": {}}


def test_intake_rejects_unknown_author_bad_route_and_missing_raw(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    with pytest.raises(ValueError):
        ai_mirror.intake("NOPE", "m", "2026-11-17", "app", False)
    with pytest.raises(ValueError):
        ai_mirror.intake("A1", "m", "2026-11-17", "web", False)
    (tmp_path / "raw" / "A1.txt").unlink()
    with pytest.raises(ValueError):
        ai_mirror.intake("A1", "m", "2026-11-17", "app", False)


def test_intake_reminds_to_continue_when_short(tmp_path, monkeypatch, capsys):
    _setup(tmp_path, monkeypatch, raw_words=100)
    ai_mirror.intake("A1", "m", "2026-11-17", "app", False)
    assert "continue" in capsys.readouterr().out.lower()
    ai_mirror.intake("A1", "m", "2026-11-17", "app", True)
    assert capsys.readouterr().out == ""


def test_intake_cli(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    assert ai_mirror.main(["intake", "--author", "A1", "--model", "m", "--date", "2026-11-17",
                           "--route", "subagent", "--continued"]) == 0
    assert ai_mirror.load_ai_manifest()["papers"]["A1"]["continued"] is True


@pytest.mark.parametrize("head", [
    "**References**", "**References:**", "## References", "7. References", "Reference List",
    "**Works Cited**", "Select Bibliography", "Sources", "**Bibliography**"])
def test_formatted_reference_headings_cut_entries(head):
    out = ai_mirror.normalise_ai_text(f"{BODY}\n\n{head}\n\n{REF1}\n\n{REF2}\n", "Zed")
    assert out == BODY
    assert "Smith" not in out and "Jones" not in out


def test_headingless_trailing_references_cut_and_counted(tmp_path, monkeypatch):
    raw = f"{BODY}\n\n{REF1}\n\n{REF2}\n"
    text, cut = ai_mirror._normalise(raw, "Zed")
    assert text == BODY and cut == 2
    _setup(tmp_path, monkeypatch)
    (tmp_path / "raw" / "A1.txt").write_text(raw, encoding="utf-8")
    assert ai_mirror.intake("A1", "m", "2026-11-17", "app", True)["cut_reference_paragraphs"] == 2


def test_reference_like_paragraph_before_body_is_kept():
    out = ai_mirror.normalise_ai_text(f"{REF1}\n\n{BODY}\n", "Zed")
    assert "Smith" in out and BODY in out


def test_intake_rejects_empty_cleaned_text(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    (tmp_path / "raw" / "A1.txt").write_text("too short\n", encoding="utf-8")
    with pytest.raises(ValueError):
        ai_mirror.intake("A1", "m", "2026-11-17", "app", False)
    assert not (tmp_path / "texts" / "A1.txt").exists()
