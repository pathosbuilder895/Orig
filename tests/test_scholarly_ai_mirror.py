import inspect
from types import SimpleNamespace

from validation.scholarly import rule_d


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
