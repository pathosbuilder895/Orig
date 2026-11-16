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
