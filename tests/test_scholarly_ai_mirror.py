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


class _FakeStore:
    """Deterministic stand-in for adjust.FeatureStore: a seeded vector per text, and a KeyError for
    any text that was never passed to ``ensure`` (as the real store raises). No disk is touched."""

    def __init__(self, collection):
        self.seen = set()

    def ensure(self, texts, workers=4):
        new = set(texts) - self.seen
        self.seen |= new
        return len(new)

    def __getitem__(self, text):
        import numpy as np
        from original.constants import FEATURE_DIM
        if text not in self.seen:
            raise KeyError("text was never ensured")
        seed = int(hashlib.sha256(text.encode("utf-8")).hexdigest()[:16], 16)
        return np.random.default_rng(seed).random(FEATURE_DIM), {}


def _synthetic_paper(vocab, key, paras=3, words=110):
    import random
    r = random.Random(key)
    return "\n\n".join(" ".join(r.choice(vocab) for _ in range(words)) + "." for _ in range(paras))


def _synthetic_sets():
    common = "the of and to in a is that for it as with was on be by this are from or".split()
    vocab = {a: common + [f"{a.lower()}word{i}" for i in range(30)] for a in "ABC"}
    papers = {a: [_synthetic_paper(vocab[a], f"{a}{k}") for k in range(6)] for a in "ABC"}

    def cut(text, n):
        return " ".join(text.split()[:n])
    trials = []
    for a in "ABC":
        others = [o for o in "ABC" if o != a]
        trials.append(loader.ScholarlyTrial(
            student_id=a, baseline=papers[a][:4], honest=[cut(p, 300) for p in papers[a][4:]],
            probes=[cut(papers[o][4], 300) for o in others], baseline_ids=[f"{a}{k}" for k in range(4)],
            honest_ids=[f"{a}4", f"{a}5"], probe_sources=others))
    ts = loader.TrialSet(trials, {})
    ai = cut(_synthetic_paper(common + [f"aiword{i}" for i in range(30)], "ai"), 300)
    return {("matched_300_300", 7): ts, ("matched_300_300", 11): ts}, ai


def test_build_scores_with_extra_docs_end_to_end(monkeypatch):
    import math
    import numpy as np
    from sklearn.feature_extraction.text import TfidfVectorizer
    from validation.scholarly import intended_use
    from validation.scholarly.verifier import mask_topic
    for flag in intended_use.RESEARCH_FLAGS:   # build_scores pops these; keep the process env as it was
        monkeypatch.delenv(flag, raising=False)
    monkeypatch.setattr(rule_d, "FeatureStore", _FakeStore)
    monkeypatch.setattr(rule_d, "dominant_subfields", lambda c: {"A": "x", "B": "x", "C": "y"})
    monkeypatch.setattr(rule_d, "_hosts", lambda c: {"A": {"h1"}, "B": {"h1"}, "C": {"h2"}})
    sets, ai = _synthetic_sets()
    texts = list(dict.fromkeys(x for ts in sets.values() for t in ts.trials
                               for x in t.baseline + t.honest + t.probes))
    vecs = {"char": TfidfVectorizer(analyzer="char", ngram_range=(3, 5), sublinear_tf=True, min_df=1,
                                    dtype=np.float32).fit(texts),
            "masked": TfidfVectorizer(analyzer="char", ngram_range=(3, 6), sublinear_tf=True, min_df=1,
                                      dtype=np.float32, preprocessor=mask_topic).fit(texts)}
    base = rule_d.build_scores("humanities", sets, vecs)
    extra = {("matched_300_300", 7): {"A": [(ai, 1, None, "ai")]}}
    with_ai = rule_d.build_scores("humanities", sets, vecs, extra_docs=extra)
    assert {r["kind"] for r in base} == {"honest", "random", "same_field", "same_venue"}
    assert [r for r in with_ai if r["kind"] != "ai"] == base   # every key and value, same order
    [row] = [r for r in with_ai if r["kind"] == "ai"]
    assert (row["author"], row["config"], row["seed"], row["label"], row["src"]) == (
        "A", "matched_300_300", 7, 1, None)
    assert list(row) == list(base[0]) and math.isfinite(row["D"])


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


def _setup(tmp_path, monkeypatch, raw_words=1500, cont_words=None):
    monkeypatch.setattr(ai_mirror, "AI_DIR", tmp_path)
    t = ai_mirror.Target(rank=0, author_id="A1", paper_id="P1", title="T", venue="V", tool="claude")
    (tmp_path / "targets_humanities.json").write_text(
        json.dumps({"targets": [ai_mirror.dataclasses.asdict(t)]}), encoding="utf-8")
    (tmp_path / "raw").mkdir()
    (tmp_path / "raw" / "A1.txt").write_text("para " * raw_words, encoding="utf-8")
    if cont_words is not None:
        (tmp_path / "raw" / "A1.cont.txt").write_text("more " * cont_words, encoding="utf-8")


def test_intake_records_hash_and_word_count(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    e = ai_mirror.intake("A1", "GPT-x", "2026-11-17", "app", False)
    text = (tmp_path / "texts" / "A1.txt").read_text(encoding="utf-8")
    assert e["words"] == len(text.split())
    assert e["sha256"] == hashlib.sha256(text.encode("utf-8")).hexdigest()
    assert e["raw_sha256"] == hashlib.sha256((tmp_path / "raw" / "A1.txt").read_bytes()).hexdigest()
    assert (e["paper_id"], e["tool"], e["route"], e["continued"]) == ("P1", "claude", "app", False)
    assert (e["cont_sha256"], e["cut_reference_paragraphs"], e["cut_wrapper_paragraphs"]) == (None, 0, 0)
    m = ai_mirror.load_ai_manifest()
    assert m["study_id"] == ai_mirror.STUDY_ID and m["collection"] == "humanities"
    assert m["papers"]["A1"] == e


def test_intake_upserts_and_is_stable(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch, cont_words=50)
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
    _setup(tmp_path, monkeypatch, raw_words=100, cont_words=100)
    ai_mirror.intake("A1", "m", "2026-11-17", "app", False)
    out = capsys.readouterr().out
    assert "continue" in out.lower() and "raw/A1.cont.txt" in out and "--continued" in out
    ai_mirror.intake("A1", "m", "2026-11-17", "app", True)
    assert capsys.readouterr().out == ""


def test_intake_continued_requires_the_continuation_file(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch, raw_words=100)
    with pytest.raises(ValueError, match=r"A1\.cont\.txt"):
        ai_mirror.intake("A1", "m", "2026-11-17", "app", True)
    assert not (tmp_path / "texts" / "A1.txt").exists()


def test_intake_cleans_reply_and_continuation_separately(tmp_path, monkeypatch):
    # reply 1 ends in a reference heading, which must not swallow the continuation
    _setup(tmp_path, monkeypatch)
    raw1 = f"{BODY}\n\nReferences\n\n{REF1}\n"
    more = " ".join(["more"] * 700)
    cont = f"{LEAD}\n\n{more}\n\n{REF2}\n\n{SIGN}\n"
    (tmp_path / "raw" / "A1.txt").write_text(raw1, encoding="utf-8")
    (tmp_path / "raw" / "A1.cont.txt").write_text(cont, encoding="utf-8")
    e = ai_mirror.intake("A1", "m", "2026-11-17", "app", True)
    text = (tmp_path / "texts" / "A1.txt").read_text(encoding="utf-8")
    assert text == f"{BODY}\n\n{more}" and e["words"] == 720
    assert e["raw_sha256"] == hashlib.sha256(raw1.encode("utf-8")).hexdigest()
    assert e["cont_sha256"] == hashlib.sha256(cont.encode("utf-8")).hexdigest()
    assert (e["cut_reference_paragraphs"], e["cut_wrapper_paragraphs"]) == (1, 2)
    assert e["continued"] is True


def test_intake_cut_counts_are_summed_over_both_replies(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    (tmp_path / "raw" / "A1.txt").write_text(f"{LEAD}\n\n{BODY}\n\n{REF1}\n", encoding="utf-8")
    (tmp_path / "raw" / "A1.cont.txt").write_text(f"{LEAD}\n\n{BODY}\n\n{REF2}\n\n{SIGN}\n", encoding="utf-8")
    e = ai_mirror.intake("A1", "m", "2026-11-17", "app", True)
    assert (e["cut_reference_paragraphs"], e["cut_wrapper_paragraphs"]) == (2, 3)
    assert (tmp_path / "texts" / "A1.txt").read_text(encoding="utf-8") == f"{BODY}\n\n{BODY}"


def test_intake_cli(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch, cont_words=50)
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
    text, cut, wrapper = ai_mirror._normalise(raw, "Zed")
    assert text == BODY and cut == 2 and wrapper == 0
    _setup(tmp_path, monkeypatch)
    (tmp_path / "raw" / "A1.txt").write_text(raw, encoding="utf-8")
    assert ai_mirror.intake("A1", "m", "2026-11-17", "app", False)["cut_reference_paragraphs"] == 2


def test_reference_like_paragraph_before_body_is_kept():
    out = ai_mirror.normalise_ai_text(f"{REF1}\n\n{BODY}\n", "Zed")
    assert "Smith" in out and BODY in out


# closing body paragraphs the substring markers used to cut: "ed." in "restored.", "doi" in "doing"
CLOSING_1563 = ("The council ended its work in 1563. What it left behind was a church reshaped in doctrine "
                "and discipline, and the unity of the West was never fully restored.")
CLOSING_LUTHER = ("Luther (1520) argued that the church is always in need of reform, and that claim remains "
                  "the best account of what it means for the church to be doing its theology.")
ENTRY = ("Smith, J. (2010). Title of the book on grace and its many consequences. Oxford: Oxford "
         "University Press, pp. 1-20.")


@pytest.mark.parametrize("closing,ending", [(CLOSING_1563, "never fully restored."),
                                            (CLOSING_LUTHER, "doing its theology.")])
def test_dated_closing_body_paragraph_is_kept(closing, ending):
    text, cut, _ = ai_mirror._normalise(f"{BODY}\n\n{closing}\n", "Zed")
    assert cut == 0 and text.startswith(BODY + "\n\n") and text.endswith(ending)


def test_real_reference_entry_in_trailing_block_is_cut():
    text, cut, _ = ai_mirror._normalise(f"{BODY}\n\n{CLOSING_1563}\n\n{ENTRY}\n", "Zed")
    assert cut == 1 and "Smith" not in text and text.endswith("never fully restored.")


@pytest.mark.parametrize("para,ref", [
    ("Trent, the city, closed the council in 1563. It was never fully restored.", False),   # ed.
    ("Trent, the city, closed the council in 1563. It is what the church still needs.", False),   # eds.
    ("Trent, the city, closed the council in 1563. It went on doing so.", False),   # doi
    ("Trent, the city, closed the council in 1563. It is not an app.", False),   # pp.
    ("Trent, the city, closed the council in 1563. Oxford University Press.", True),
    ("Trent, the city, closed the council in 1563. pp. 1-20.", True),
    ("Trent, the city, closed the council in 1563. Smith and Jones, eds. Rome.", True),
    ("Trent, the city, closed the council in 1563. doi 10.1000/xyz.", True),
    ("The council closed in 1563, see Oxford University Press, pp. 1-20.", False),   # no entry-like start
    ("Smith, J. Title of the book. Oxford: Oxford University Press, pp. 1-20.", False),   # no year
])
def test_reference_like_needs_entry_start_year_and_word_bounded_marker(para, ref):
    assert ai_mirror._reference_like(para) is ref


# chat-app wrapper text around the article
LEAD = "Certainly! Here is an original scholarly journal article of about 1,600 words on that topic."
SIGN = "Let me know if you would like me to adjust the tone, length or focus of any part of this article."


def test_wrapper_lead_in_and_sign_off_are_removed_and_counted():
    text, cut, wrapper = ai_mirror._normalise(f"{LEAD}\n\n{BODY}\n\n{BODY}\n\n{SIGN}\n", "Zed")
    assert text == f"{BODY}\n\n{BODY}" and (cut, wrapper) == (0, 2)


@pytest.mark.parametrize("lead", [
    "**Sure.** Below is the article you asked for.", "Of course. The article follows.",
    "Absolutely, here it is.", "HERE IS the article, written as continuous prose in paragraphs.",
    "Here’s an original article on the topic you named.", "Here's the article.",
    "Below is an original article.", "I’ve written an original article for you.",
    "I have written the article in continuous prose as you asked.",
    "The article follows, written as continuous academic prose in paragraphs as requested:"])
def test_wrapper_lead_ins(lead):
    text, _, wrapper = ai_mirror._normalise(f"{lead}\n\n{BODY}\n", "Zed")
    assert text == BODY and wrapper == 1


def test_wrapper_sign_offs_are_dropped_repeatedly_from_the_end():
    tail = ("I hope this article gives you a useful sense of the debate and its main lines of argument.\n\n"
            "If you’d like, I can also add an abstract or expand any of the paragraphs above for you.\n\n"
            "Would you like me to change anything?")
    text, _, wrapper = ai_mirror._normalise(f"{BODY}\n\n{tail}\n", "Zed")
    assert text == BODY and wrapper == 3


@pytest.mark.parametrize("first", [
    "The council of Trent closed in 1563, and its decrees shaped the church for four centuries after.",
    "Surely the council of Trent did more to shape the modern church than any other gathering did.",
    "Certainty about the council's aims is hard to come by, since its sessions spanned eighteen years."])
def test_ordinary_first_body_paragraph_is_kept(first):
    text, _, wrapper = ai_mirror._normalise(f"{first}\n\n{BODY}\n", "Zed")
    assert text == f"{first}\n\n{BODY}" and wrapper == 0


def test_offer_phrase_in_a_middle_paragraph_is_kept():
    mid = "Erasmus was happy to leave the dispute to others, and he said so in letters to many friends."
    text, _, wrapper = ai_mirror._normalise(f"{BODY}\n\n{mid}\n\n{BODY}\n", "Zed")
    assert mid in text and wrapper == 0


def test_intake_rejects_empty_cleaned_text(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    (tmp_path / "raw" / "A1.txt").write_text("too short\n", encoding="utf-8")
    with pytest.raises(ValueError):
        ai_mirror.intake("A1", "m", "2026-11-17", "app", False)
    assert not (tmp_path / "texts" / "A1.txt").exists()


COMMITTED = {"matched_300_300": -0.529301, "matched_1200_1200": -1.244517,
             "long_past_1200_short_new_300": -0.919008}


def test_thresholds_match_equal_at_six_decimals():
    assert ai_mirror.thresholds_match({**COMMITTED, "matched_300_300": -0.5293014}, COMMITTED) == []


def test_thresholds_match_reports_difference_and_missing():
    r = {"matched_300_300": -0.529302, "matched_1200_1200": -1.244517}
    assert ai_mirror.thresholds_match(r, COMMITTED) == ["long_past_1200_short_new_300", "matched_300_300"]


FP = {"python": "3.11.9", "numpy": "1.26.4", "scikit_learn": "1.5.0", "sentence_transformers": False,
      "platform": "Linux-x86_64", "pdftotext": "pdftotext version 24.02.0", "git_head": "a" * 40}


def _env(monkeypatch, tmp_path, thresholds):
    monkeypatch.setattr(ai_mirror, "AI_DIR", tmp_path / "out")
    monkeypatch.setattr(ai_mirror.fetch, "verify", lambda c, cache: {"ok": True})
    monkeypatch.setattr(rule_d, "fit_or_load_vectorizers", lambda c: ({}, "deadbeef"))
    monkeypatch.setattr(ai_mirror, "_fingerprint", lambda: dict(FP))
    calls = []
    monkeypatch.setattr(rule_d, "calibrate", lambda c, n: calls.append(c) or {
        "thresholds": thresholds, "vectorizers_sha256": "deadbeef"})
    return calls


def _committed_doc():
    return json.loads((rule_d.HERE / "rule_d_thresholds_humanities.json").read_text(encoding="utf-8"))


def test_committed_thresholds_pin_equals_the_committed_file():
    assert ai_mirror.COMMITTED_THRESHOLDS == COMMITTED == _committed_doc()["thresholds"]
    assert ai_mirror.THRESHOLDS_PATH == rule_d.HERE / "rule_d_thresholds_humanities.json"


def test_check_environment_passes_when_thresholds_equal(monkeypatch, tmp_path):
    doc = _committed_doc()
    _env(monkeypatch, tmp_path, dict(doc["thresholds"]))
    res = ai_mirror.check_environment(3)
    assert res["passed"] is True and res["mismatches"] == []
    assert res["sha_matches_committed"] == (doc["vectorizers_sha256"] == "deadbeef")
    assert res["committed"] == ai_mirror.COMMITTED_THRESHOLDS
    assert res["fingerprint"] == FP and res["owner_approved"] is False
    written = json.loads((tmp_path / "out" / "environment_humanities.json").read_text())
    assert written == res
    assert set(written) == {"date", "verify", "vectorizers_sha256", "sha_matches_committed",
                            "recomputed", "committed", "mismatches", "passed", "fingerprint",
                            "owner_approved"}


def _thresholds_file(tmp_path, thresholds):
    path = tmp_path / "rule_d_thresholds_humanities.json"
    doc = {**_committed_doc()}
    if thresholds is None:
        return path   # missing file
    doc["thresholds"] = thresholds
    path.write_text(json.dumps(doc), encoding="utf-8")
    return path


BROKEN_THRESHOLDS = {
    "recalibrated": {**COMMITTED, "matched_1200_1200": -1.2},
    "empty": {},
    "key_missing": {k: v for k, v in COMMITTED.items() if k != "matched_300_300"},
    "extra_key": {**COMMITTED, "matched_600_600": -1.0},
    "rounded": {**COMMITTED, "matched_300_300": -0.5293014},
    "file_missing": None,
}


@pytest.mark.parametrize("broken", sorted(BROKEN_THRESHOLDS))
def test_check_environment_refuses_when_thresholds_file_is_not_the_pin(broken, monkeypatch, tmp_path):
    thr = BROKEN_THRESHOLDS[broken]
    # recomputed equals whatever the file now says: the vacuous comparison the pin exists to stop
    calls = _env(monkeypatch, tmp_path, dict(thr or {}))
    monkeypatch.setattr(ai_mirror, "THRESHOLDS_PATH", _thresholds_file(tmp_path, thr))
    with pytest.raises(SystemExit, match="do not equal the pinned COMMITTED_THRESHOLDS"):
        ai_mirror.check_environment(3)
    assert calls == [] and not (tmp_path / "out" / "environment_humanities.json").exists()


def _previous_env(tmp_path, monkeypatch, passed, committed):
    out = tmp_path / "out"
    out.mkdir(parents=True, exist_ok=True)
    (out / "environment_humanities.json").write_text(json.dumps({"passed": passed}), encoding="utf-8")
    monkeypatch.setattr(ai_mirror, "_uncommitted", lambda p: not committed)


def test_check_environment_refuses_to_rerun_over_a_committed_failed_gate(monkeypatch, tmp_path):
    calls = _env(monkeypatch, tmp_path, dict(COMMITTED))
    _previous_env(tmp_path, monkeypatch, passed=False, committed=True)
    with pytest.raises(SystemExit, match="owner") as exc:
        ai_mirror.check_environment(3)
    assert "--owner-approved" in str(exc.value) and calls == []
    res = ai_mirror.check_environment(3, owner_approved=True)
    assert res["passed"] is True and res["owner_approved"] is True and calls == ["humanities"]


@pytest.mark.parametrize("passed,committed", [(False, False), (True, True)])
def test_check_environment_reruns_over_an_uncommitted_or_passed_gate(passed, committed, monkeypatch, tmp_path):
    calls = _env(monkeypatch, tmp_path, dict(COMMITTED))
    _previous_env(tmp_path, monkeypatch, passed=passed, committed=committed)
    assert ai_mirror.check_environment(3)["passed"] is True and calls == ["humanities"]


def test_check_env_cli_passes_owner_approval(monkeypatch, capsys):
    got = []
    monkeypatch.setattr(ai_mirror, "check_environment", lambda n_boot=10, owner_approved=False: got.append(
        (n_boot, owner_approved)) or {"passed": True, "verify": {"missing": 0, "hash_mismatch": 0}})
    assert ai_mirror.main(["check-env"]) == 0
    assert ai_mirror.main(["check-env", "--n-boot", "4", "--owner-approved"]) == 0
    assert got == [(10, False), (4, True)]


def test_fingerprint_records_versions_platform_tools_and_head():
    import platform
    import numpy
    import sklearn
    fp = ai_mirror._fingerprint()
    assert set(fp) == {"python", "numpy", "scikit_learn", "sentence_transformers", "platform",
                       "pdftotext", "git_head"}
    assert (fp["python"], fp["numpy"], fp["scikit_learn"]) == (
        platform.python_version(), numpy.__version__, sklearn.__version__)
    assert isinstance(fp["sentence_transformers"], bool) and fp["platform"] == platform.platform()
    assert fp["pdftotext"] is None or isinstance(fp["pdftotext"], str)
    assert fp["git_head"] is None or (len(fp["git_head"]) == 40 and int(fp["git_head"], 16) >= 0)


def test_first_output_line_is_none_for_a_missing_tool():
    assert ai_mirror._first_output_line(["no-such-tool-for-ai-mirror-test", "-v"]) is None
    assert ai_mirror._first_output_line(["git", "--version"]).startswith("git version")


def test_check_environment_fails_on_one_difference(monkeypatch, tmp_path):
    doc = _committed_doc()
    th = dict(doc["thresholds"])
    name = sorted(th)[0]
    th[name] += 0.001
    _env(monkeypatch, tmp_path, th)
    res = ai_mirror.check_environment(3)
    assert res["passed"] is False and res["mismatches"] == [name]


# ------------------------------------------------- scoring summary + the opening --
def test_wilson_and_decide():
    assert tuple(round(x, 3) for x in ai_mirror.wilson(19, 20)) == (0.764, 0.991)
    assert round(ai_mirror.wilson(20, 20)[0], 3) == 0.839
    assert ai_mirror.wilson(20, 20)[1] <= 1.0 and ai_mirror.wilson(0, 20)[0] >= 0.0
    assert ai_mirror.decide(17, 20) == "below_95" and ai_mirror.decide(18, 20) == "95_not_ruled_out"
    assert ai_mirror.wilson(0, 0) == (0.0, 1.0) and ai_mirror.decide(0, 0) == "no_papers"


def test_ai_cut_single_paragraph():
    text = " ".join(["word"] * 1250)
    assert len(ai_mirror.ai_cut(text, 1200, "A1").split()) == 1200
    assert ai_mirror.ai_cut(text, 1200, "A1") == ai_mirror.ai_cut(text, 1200, "A1")


def test_ai_cut_is_seeded_by_author():
    text = "\n\n".join(f"p{i} " + " ".join(["w"] * 99) for i in range(30))
    cuts = {aid: ai_mirror.ai_cut(text, 300, aid) for aid in ("A1", "A2", "A3", "A4", "A5")}
    assert all(len(c.split()) == 300 for c in cuts.values())
    assert len(set(cuts.values())) > 1


def test_short_ai_text_enters_only_300_configs():
    extra, left_out = ai_mirror.ai_extra_docs({"A1": " ".join(["w"] * 800)})
    assert "A1" not in extra[("matched_1200_1200", 7)]
    assert "A1" in extra[("matched_300_300", 7)] and "A1" in extra[("long_past_1200_short_new_300", 7)]
    assert left_out["matched_1200_1200"] == ["A1"]


def test_ai_extra_docs_shape_and_lengths():
    texts = {"A1": " ".join(["a"] * 1400), "A2": " ".join(["b"] * 1250)}
    extra, left_out = ai_mirror.ai_extra_docs(texts)
    assert set(extra) == {(name, 7) for name, _, _ in rule_d.CONFIGS}
    for name, _, new_w in rule_d.CONFIGS:
        assert left_out[name] == []
        for aid in texts:
            [(text, label, src, kind)] = extra[(name, 7)][aid]
            assert (label, src, kind) == (1, None, "ai")
            assert text == ai_mirror.ai_cut(texts[aid], new_w, aid) and len(text.split()) == new_w


def _tgt(rank, aid, tool):
    return ai_mirror.Target(rank=rank, author_id=aid, paper_id=f"P{rank}", title="T", venue="V", tool=tool)


THR = {"matched_300_300": 0.0, "matched_1200_1200": -1.0, "long_past_1200_short_new_300": 0.0}


def _row(author, config, D, label=1, kind="ai", seed=7):
    return {"author": author, "config": config, "seed": seed, "label": label, "kind": kind,
            "src": None, "D": D}


def test_summarise_reports_missing_author():
    # targets A1 (claude), A2 (gemini); only A1 has an ai row, D above threshold
    targets = [_tgt(0, "A1", "claude"), _tgt(1, "A2", "gemini")]
    rows = [_row("A1", "matched_1200_1200", -0.5)]
    s = ai_mirror.summarise_ai(rows, THR, targets, {})
    c = s["matched_1200_1200"]
    assert (c["caught"], c["n"], c["missing_authors"]) == (1, 1, ["A2"])
    assert c["wilson95"] == list(ai_mirror.wilson(1, 1))
    assert c["rate"] == 1.0 and c["outcome"] == ai_mirror.decide(1, 1)
    assert c["per_tool"] == {"claude": [1, 1], "chatgpt": [0, 0], "gemini": [0, 0]}
    assert c["papers"] == [{"author": "A1", "tool": "claude", "D": -0.5, "caught": True}]
    e = s["matched_300_300"]
    assert (e["caught"], e["n"], e["rate"], e["outcome"]) == (0, 0, None, "no_papers")
    assert e["missing_authors"] == ["A1", "A2"] and e["wilson95"] == [0.0, 1.0]


def test_summarise_counts_only_seed7_target_ai_rows_and_strict_threshold():
    targets = [_tgt(1, "A2", "gemini"), _tgt(0, "A1", "claude")]   # out of rank order on purpose
    name = "matched_1200_1200"
    rows = [_row("A1", name, -1.0),                 # exactly at threshold: not caught
            _row("A2", name, 2.0),                  # caught
            _row("A2", name, 9.0, seed=11),         # other seed: ignored
            _row("ZZ", name, 9.0),                  # not a target: ignored
            _row("A1", name, 9.0, kind="random"),   # an ordinary probe: ignored
            _row("A1", name, -0.5, label=0, kind="honest"),   # honest, flagged
            _row("A1", name, -2.0, label=0, kind="honest"),   # honest, not flagged
            _row("A2", name, 3.0, label=0, kind="honest", seed=11),   # other seed: ignored
            _row("ZZ", name, 3.0, label=0, kind="honest")]            # not a target: ignored
    s = ai_mirror.summarise_ai(rows, THR, targets, {name: ["A3"]})
    c = s[name]
    assert (c["caught"], c["n"], c["missing_authors"]) == (1, 2, [])
    assert [p["author"] for p in c["papers"]] == ["A1", "A2"]
    assert [p["caught"] for p in c["papers"]] == [False, True]
    assert c["per_tool"]["gemini"] == [1, 1] and c["per_tool"]["claude"] == [0, 1]
    assert c["left_out_short"] == ["A3"]
    assert s["honest_same_authors"][name] == {"flagged": 1, "n": 2}
    assert s["honest_same_authors"]["matched_300_300"] == {"flagged": 0, "n": 0}
    assert set(s) == {n for n, _, _ in rule_d.CONFIGS} | {"honest_same_authors"}


def test_reproduction_diff():
    pub = {"matched_1200_1200": {"random": {"catch_rate": 0.9477, "auc": 0.98}}}
    new = {"matched_1200_1200": {"random": {"catch_rate": 0.9478, "auc": 0.98}}}
    assert ai_mirror.reproduction_diff(new, pub) == ["matched_1200_1200/random/catch_rate"]


def test_reproduction_diff_reports_missing_cells_and_keys():
    pub = {"matched_300_300": {"random": {"auc": 0.9, "n_honest": 10, "honest_ci95": [0, 1]}},
           "matched_1200_1200": {"same_field": {"auc": 0.8}}}
    new = {"matched_300_300": {"random": {"auc": 0.9, "honest_ci95": [0, 0.5]}}}
    assert ai_mirror.reproduction_diff(new, pub) == [
        "matched_300_300/random/n_honest", "matched_1200_1200/same_field/auc"]
    assert ai_mirror.reproduction_diff(pub, pub) == []


class _Opened(Exception):
    """Raised by the stubbed opening: the guards let the call through."""


def _locked_fixture(tmp_path, monkeypatch):
    """A fixture every guard passes; ``load_trial_grid`` fails the test if it is reached."""
    ai_dir, res = tmp_path / "ai", tmp_path / "results"
    (ai_dir / "texts").mkdir(parents=True)
    res.mkdir()
    monkeypatch.setattr(ai_mirror, "AI_DIR", ai_dir)
    monkeypatch.setattr(ai_mirror, "RESULTS_DIR", res)
    targets = [_tgt(0, "A1", "claude"), _tgt(1, "A2", "chatgpt")]
    monkeypatch.setattr(ai_mirror, "N_TARGETS", len(targets))   # the count guard reads it at call time
    (ai_dir / "targets_humanities.json").write_text(json.dumps(
        {"targets": [ai_mirror.dataclasses.asdict(t) for t in targets]}), encoding="utf-8")
    papers = {}
    for t in targets:
        text = "\n\n".join(" ".join([t.author_id.lower()] * 700) for _ in range(2))
        (ai_dir / "texts" / f"{t.author_id}.txt").write_text(text, encoding="utf-8")
        papers[t.author_id] = {"author_id": t.author_id, "paper_id": t.paper_id, "tool": t.tool,
                               "words": 1400, "continued": False,
                               "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest()}
    (ai_dir / "manifest_humanities.json").write_text(json.dumps(
        {"study_id": ai_mirror.STUDY_ID, "collection": "humanities", "papers": papers}), encoding="utf-8")
    (ai_dir / "environment_humanities.json").write_text(
        json.dumps({"passed": True, "vectorizers_sha256": "vecsha", "fingerprint": FP}), encoding="utf-8")
    monkeypatch.setattr(ai_mirror, "_fingerprint", lambda: dict(FP))
    monkeypatch.setattr(ai_mirror, "THRESHOLDS_PATH", _thresholds_file(tmp_path, dict(COMMITTED)))
    monkeypatch.setattr(ai_mirror, "ROWS_DIR", tmp_path / "rows")   # never the repo's cache
    monkeypatch.setattr(ai_mirror, "_git_head", lambda: "c" * 40)
    monkeypatch.setattr(ai_mirror, "_uncommitted", lambda p: False)
    monkeypatch.setattr(rule_d, "fit_or_load_vectorizers", lambda c: ({"char": "VEC"}, "vecsha"))
    log = tmp_path / "LOCKED_OPENINGS.tsv"   # earlier openings, none by this study for humanities
    log.write_text("# header\n2026-11-12T21:56:08\thumanities\tscholarly-rule-d-2026-11-12\n"
                   f"2026-11-17T09:00:00\tscience\t{ai_mirror.STUDY_ID}\n", encoding="utf-8")
    monkeypatch.setattr(loader, "LOCKED_LOG", log)

    def never(*a, **k):
        pytest.fail("load_trial_grid was called: the locked partition would have been opened")
    monkeypatch.setattr(loader, "load_trial_grid", never)
    return ai_dir, res


# broken fixture -> a substring found only in that guard's own message
GUARD_CASES = {
    "wrong_study": "may only be opened here for the pre-registered study",
    "result_exists": "ai_mirror_humanities_locked_test_2026-11-17.json exists",
    "already_opened": "already records an opening",
    "env_missing": "is missing: run check-env",
    "env_failed": "does not record passed: true",
    "fingerprint_differs": "fingerprint differs from the one check-env recorded",
    "thresholds_not_pinned": "do not equal the pinned COMMITTED_THRESHOLDS",
    "vectorizers_differ": "differs from the one that passed the gate",
    "target_count": "pre-registered target count",
    "no_ai_paper": "has no entry in the AI manifest",
    "protocol_mismatch": "but its target has",
    "text_missing": "A2.txt for target A2 is missing",
    "text_hash_differs": "does not match the sha256 in its manifest entry",
    "uncommitted": "uncommitted changes under",
}


def _edit_json(path, edit):
    data = json.loads(path.read_text(encoding="utf-8"))
    edit(data)
    path.write_text(json.dumps(data), encoding="utf-8")


@pytest.mark.parametrize("broken", sorted(GUARD_CASES))
def test_open_locked_guards(broken, tmp_path, monkeypatch):
    ai_dir, res = _locked_fixture(tmp_path, monkeypatch)
    env_path, manifest_path = ai_dir / "environment_humanities.json", ai_dir / "manifest_humanities.json"
    study = ai_mirror.STUDY_ID
    if broken == "wrong_study":
        study = "scholarly-rule-d-2026-11-12"
    elif broken == "result_exists":
        (res / "ai_mirror_humanities_locked_test_2026-11-17.json").write_text("{}", encoding="utf-8")
    elif broken == "env_missing":
        env_path.unlink()
    elif broken == "env_failed":   # sha and fingerprint still match: only `passed` is broken
        _edit_json(env_path, lambda e: e.update(passed=False))
    elif broken == "fingerprint_differs":
        _edit_json(env_path, lambda e: e["fingerprint"].update(numpy="2.0.0"))
    elif broken == "thresholds_not_pinned":   # as a `rule_d calibrate` run would leave it
        _edit_json(ai_mirror.THRESHOLDS_PATH, lambda d: d["thresholds"].update(matched_1200_1200=-1.2))
    elif broken == "target_count":
        _edit_json(ai_dir / "targets_humanities.json", lambda d: d["targets"].pop())
    elif broken == "no_ai_paper":
        _edit_json(manifest_path, lambda m: m["papers"].pop("A2"))
    elif broken == "protocol_mismatch":
        _edit_json(manifest_path, lambda m: m["papers"]["A2"].update(tool="gemini"))
    elif broken == "text_missing":
        (ai_dir / "texts" / "A2.txt").unlink()
    elif broken == "text_hash_differs":
        with (ai_dir / "texts" / "A2.txt").open("a", encoding="utf-8") as f:
            f.write(" edited")
    elif broken == "already_opened":
        with loader.LOCKED_LOG.open("a", encoding="utf-8") as f:
            f.write(f"2026-11-18T10:00:00\thumanities\t{ai_mirror.STUDY_ID}\n")
    elif broken == "vectorizers_differ":
        _edit_json(env_path, lambda e: e.update(vectorizers_sha256="othersha"))
    elif broken == "uncommitted":
        monkeypatch.setattr(ai_mirror, "_uncommitted", lambda p: True)
    with pytest.raises(SystemExit) as exc:
        ai_mirror.open_locked(study)
    msg = str(exc.value)
    assert GUARD_CASES[broken] in msg
    assert not [k for k, v in GUARD_CASES.items() if k != broken and v in msg], msg
    if broken == "already_opened":
        assert ai_mirror.STUDY_ID in str(exc.value) and "approval" in str(exc.value)
    assert not list(res.glob("ai_mirror_humanities_locked_test_*.json")) or broken == "result_exists"


def test_open_locked_guards_pass_through_to_the_opening(tmp_path, monkeypatch):
    _locked_fixture(tmp_path, monkeypatch)
    calls = []

    def opened(*a, **k):
        calls.append((a, k))
        raise _Opened
    monkeypatch.setattr(loader, "load_trial_grid", opened)
    with pytest.raises(_Opened):
        ai_mirror.open_locked(ai_mirror.STUDY_ID)
    [(args, kwargs)] = calls
    assert args == ("humanities", "locked_test",
                    [(n, pw, nw, s) for n, pw, nw in rule_d.CONFIGS for s in rule_d.SEEDS])
    assert kwargs == {"allow_locked_for": ai_mirror.STUDY_ID, "n_past": 4, "n_new": 2, "n_probes": 5}


MEASURED_ON = "published humanities scholarship, not student writing"


def test_open_locked_writes_result(tmp_path, monkeypatch, capsys):
    ai_dir, res = _locked_fixture(tmp_path, monkeypatch)
    published = json.loads((rule_d.HERE / "rule_d_humanities_locked_test_2026-11-12.json")
                           .read_text(encoding="utf-8"))["cells"]
    monkeypatch.setattr(loader, "load_trial_grid", lambda c, p, grid, **k: {
        (n, s): loader.TrialSet([], {"AX": "unusable cache"} if s == 7 else {}) for n, _, _, s in grid})
    seen = {}

    loads = []
    monkeypatch.setattr(rule_d, "fit_or_load_vectorizers",
                        lambda c: loads.append(c) or ({"char": "VEC"}, "vecsha"))

    def scores(collection, sets, vecs, extra_docs=None):
        seen["extra"], seen["vecs"] = extra_docs, vecs
        rows = []
        for name, _, _ in rule_d.CONFIGS:
            rows += [_row("A1", name, 50.0),
                     _row("A1", name, -50.0, label=0, kind="honest"),
                     _row("A2", name, 50.0, label=0, kind="honest")]
        seen["rows"] = rows
        return rows
    monkeypatch.setattr(rule_d, "build_scores", scores)

    def cell(R, thr, kind, n_boot):
        assert R and all(r["kind"] != "ai" for r in R) and n_boot == 7
        return dict(published[R[0]["config"]][kind])
    monkeypatch.setattr(rule_d, "cell_report", cell)
    out = ai_mirror.open_locked(ai_mirror.STUDY_ID, n_boot=7)
    [path] = res.glob("ai_mirror_humanities_locked_test_*.json")
    assert path.name == f"ai_mirror_humanities_locked_test_{out['date']}.json"
    assert json.loads(path.read_text(encoding="utf-8")) == out
    assert out["study_id"] == ai_mirror.STUDY_ID and out["vectorizers_sha256"] == "vecsha"
    assert out["thresholds"] == _committed_doc()["thresholds"]
    assert out["reproduction"]["equal"] is True and out["reproduction"]["diffs"] == []
    assert out["targets_sha256"] == hashlib.sha256(
        (ai_dir / "targets_humanities.json").read_bytes()).hexdigest()
    assert out["ai_manifest_sha256"] == hashlib.sha256(
        (ai_dir / "manifest_humanities.json").read_bytes()).hexdigest()
    assert out["skipped"] == {f"{n}/seed7/AX": "unusable cache" for n, _, _ in rule_d.CONFIGS}
    assert set(seen["extra"]) == {(n, 7) for n, _, _ in rule_d.CONFIGS}
    assert loads == ["humanities"] and seen["vecs"] == {"char": "VEC"}
    assert set(seen["extra"][("matched_1200_1200", 7)]) == {"A1", "A2"}
    c = out["ai"]["matched_1200_1200"]
    assert (c["caught"], c["n"], c["missing_authors"]) == (1, 1, ["A2"])
    assert out["ai"]["honest_same_authors"]["matched_1200_1200"] == {"flagged": 1, "n": 2}
    assert out["measured_on"] == MEASURED_ON and out["git_head"] == "c" * 40
    assert out["roles"] == {"matched_1200_1200": "primary", "long_past_1200_short_new_300": "secondary",
                            "matched_300_300": "reported only"}
    saved = json.loads((tmp_path / "rows" / f"ai_mirror_rows_{out['date']}.json").read_text(encoding="utf-8"))
    assert saved["rows"] == seen["rows"] and saved["study_id"] == ai_mirror.STUDY_ID
    printed = [ln for ln in capsys.readouterr().out.splitlines()
               if ln.split(" ")[0].rstrip(":") in out["roles"] or ln.startswith("reproduction")]
    assert len(printed) == 4 and all(ln.endswith(MEASURED_ON) for ln in printed), printed
    with pytest.raises(SystemExit):   # a second opening is refused
        ai_mirror.open_locked(ai_mirror.STUDY_ID)


def test_open_locked_goes_on_when_rows_cannot_be_saved(tmp_path, monkeypatch, capsys):
    _, res = _locked_fixture(tmp_path, monkeypatch)
    (tmp_path / "blocked").write_text("a file, not a directory", encoding="utf-8")
    monkeypatch.setattr(ai_mirror, "ROWS_DIR", tmp_path / "blocked")
    monkeypatch.setattr(loader, "load_trial_grid", lambda c, p, grid, **k: {
        (n, s): loader.TrialSet([], {}) for n, _, _, s in grid})
    monkeypatch.setattr(rule_d, "build_scores", lambda *a, **k: [])
    monkeypatch.setattr(rule_d, "cell_report", lambda R, thr, kind, n_boot: {})
    ai_mirror.open_locked(ai_mirror.STUDY_ID, n_boot=3)
    assert "warning: could not save the rows" in capsys.readouterr().out
    assert len(list(res.glob("ai_mirror_humanities_locked_test_*.json"))) == 1


def test_rows_dir_is_the_git_ignored_cache():
    import subprocess
    assert ai_mirror.ROWS_DIR == rule_d.HERE / "cache"
    probe = ai_mirror.ROWS_DIR / "ai_mirror_rows_2026-11-20.json"
    assert subprocess.run(["git", "check-ignore", "-q", str(probe)], cwd=ai_mirror._REPO).returncode == 0


def test_open_locked_saves_rows_before_summarising(tmp_path, monkeypatch):
    _locked_fixture(tmp_path, monkeypatch)
    monkeypatch.setattr(loader, "load_trial_grid", lambda c, p, grid, **k: {
        (n, s): loader.TrialSet([], {}) for n, _, _, s in grid})
    rows = [_row("A1", n, 0.5) for n, _, _ in rule_d.CONFIGS]
    monkeypatch.setattr(rule_d, "build_scores", lambda *a, **k: rows)

    def crash(*a, **k):
        raise RuntimeError("summary crashed")
    monkeypatch.setattr(rule_d, "cell_report", crash)
    with pytest.raises(RuntimeError):
        ai_mirror.open_locked(ai_mirror.STUDY_ID, n_boot=3)
    [path] = (tmp_path / "rows").glob("ai_mirror_rows_*.json")
    assert json.loads(path.read_text(encoding="utf-8"))["rows"] == rows


def test_open_locked_reports_reproduction_differences(tmp_path, monkeypatch):
    _, res = _locked_fixture(tmp_path, monkeypatch)
    monkeypatch.setattr(loader, "load_trial_grid", lambda c, p, grid, **k: {
        (n, s): loader.TrialSet([], {}) for n, _, _, s in grid})
    monkeypatch.setattr(rule_d, "build_scores", lambda *a, **k: [
        _row("A1", n, 0.0, label=0, kind="honest") for n, _, _ in rule_d.CONFIGS])
    monkeypatch.setattr(rule_d, "cell_report", lambda R, thr, kind, n_boot: {
        "honest_flag_rate": 0.5, "catch_rate": 0.5, "auc": 0.5,
        "n_authors": 1, "n_honest": 1, "n_probe": 0})
    out = ai_mirror.open_locked(ai_mirror.STUDY_ID, n_boot=3)
    assert out["reproduction"]["equal"] is False
    assert "matched_1200_1200/random/catch_rate" in out["reproduction"]["diffs"]
    assert out["reproduction"]["cells"]["matched_1200_1200"]["random"]["catch_rate"] == 0.5


def _reach_opening(monkeypatch):
    def opened(*a, **k):
        raise _Opened
    monkeypatch.setattr(loader, "load_trial_grid", opened)


@pytest.mark.parametrize("key,value", [("python", "3.12.1"), ("numpy", "2.0.0"),
                                       ("scikit_learn", "1.6.1"), ("sentence_transformers", True)])
def test_open_locked_refuses_each_compared_fingerprint_field(key, value, tmp_path, monkeypatch):
    ai_dir, _ = _locked_fixture(tmp_path, monkeypatch)
    _edit_json(ai_dir / "environment_humanities.json", lambda e: e["fingerprint"].update({key: value}))
    with pytest.raises(SystemExit, match="fingerprint differs") as exc:
        ai_mirror.open_locked(ai_mirror.STUDY_ID)
    assert key in str(exc.value)


def test_open_locked_refuses_when_no_fingerprint_was_recorded(tmp_path, monkeypatch):
    ai_dir, _ = _locked_fixture(tmp_path, monkeypatch)
    _edit_json(ai_dir / "environment_humanities.json", lambda e: e.pop("fingerprint"))
    with pytest.raises(SystemExit, match="fingerprint differs"):
        ai_mirror.open_locked(ai_mirror.STUDY_ID)


def test_open_locked_only_records_platform_pdftotext_and_head(tmp_path, monkeypatch):
    ai_dir, _ = _locked_fixture(tmp_path, monkeypatch)
    _edit_json(ai_dir / "environment_humanities.json", lambda e: e["fingerprint"].update(
        platform="macOS-15", pdftotext=None, git_head="b" * 40))
    _reach_opening(monkeypatch)
    with pytest.raises(_Opened):
        ai_mirror.open_locked(ai_mirror.STUDY_ID)


def test_protocol_notes_list_short_entries_without_a_continuation():
    targets = [_tgt(0, "A1", "claude"), _tgt(1, "A2", "chatgpt"), _tgt(2, "A3", "gemini")]
    papers = {"A1": {"words": 1400, "continued": False}, "A2": {"words": 900, "continued": False},
              "A3": {"words": 1100, "continued": True}}
    [note] = ai_mirror.protocol_notes(targets, papers)
    assert note.startswith("A2: 900 cleaned words") and "1,300" in note


def test_open_locked_records_and_prints_protocol_notes(tmp_path, monkeypatch, capsys):
    ai_dir, _ = _locked_fixture(tmp_path, monkeypatch)
    _edit_json(ai_dir / "manifest_humanities.json", lambda m: m["papers"]["A2"].update(words=900))
    monkeypatch.setattr(loader, "load_trial_grid", lambda c, p, grid, **k: {
        (n, s): loader.TrialSet([], {}) for n, _, _, s in grid})
    monkeypatch.setattr(rule_d, "build_scores", lambda *a, **k: [
        _row("A1", n, 0.0, label=0, kind="honest") for n, _, _ in rule_d.CONFIGS])
    monkeypatch.setattr(rule_d, "cell_report", lambda R, thr, kind, n_boot: {})
    out = ai_mirror.open_locked(ai_mirror.STUDY_ID, n_boot=3)
    assert out["protocol_notes"] == ai_mirror.protocol_notes(
        ai_mirror.load_targets(), ai_mirror.load_ai_manifest()["papers"])
    [note] = out["protocol_notes"]
    assert note.startswith("A2: 900") and note in capsys.readouterr().out


def test_uncommitted_sees_untracked_and_clean(tmp_path, monkeypatch):
    import subprocess
    repo = tmp_path / "repo"
    sub = repo / "ai"
    sub.mkdir(parents=True)
    git = ["git", "-c", "user.name=t", "-c", "user.email=t@example.org",
           "-c", "commit.gpgsign=false", "-c", "core.hooksPath=/dev/null"]
    subprocess.run(git + ["init", "-q"], cwd=repo, check=True)
    monkeypatch.setattr(ai_mirror, "_REPO", repo)
    assert ai_mirror._uncommitted(sub) is False
    (sub / "a.txt").write_text("x", encoding="utf-8")
    assert ai_mirror._uncommitted(sub) is True
    subprocess.run(git + ["add", "."], cwd=repo, check=True)
    subprocess.run(git + ["commit", "-q", "-m", "c"], cwd=repo, check=True)
    assert ai_mirror._uncommitted(sub) is False
    (sub / "a.txt").write_text("y", encoding="utf-8")
    assert ai_mirror._uncommitted(sub) is True


def test_uncommitted_refuses_when_git_fails(tmp_path, monkeypatch):
    monkeypatch.setattr(ai_mirror, "_REPO", tmp_path)
    monkeypatch.setenv("GIT_DIR", str(tmp_path / "not-a-repo"))
    with pytest.raises(SystemExit, match="git status failed"):
        ai_mirror._uncommitted(tmp_path)


def test_locked_cli(monkeypatch):
    got = []
    monkeypatch.setattr(ai_mirror, "open_locked", lambda study, n_boot=1000: got.append((study, n_boot)) or {})
    assert ai_mirror.main(["locked", "--study", "x"]) == 0
    assert ai_mirror.main(["locked", "--study", "y", "--n-boot", "5"]) == 0
    assert got == [("x", 1000), ("y", 5)]


def test_opened_before_reads_the_log_at_call_time(tmp_path, monkeypatch):
    monkeypatch.setattr(loader, "LOCKED_LOG", tmp_path / "absent.tsv")
    assert ai_mirror._opened_before() is False
    log = tmp_path / "log.tsv"
    log.write_text(f"# c\n2026-11-12T00:00:00\thumanities\tother\n"
                   f"2026-11-12T00:00:00\tscience\t{ai_mirror.STUDY_ID}\n", encoding="utf-8")
    monkeypatch.setattr(loader, "LOCKED_LOG", log)
    assert ai_mirror._opened_before() is False
    with log.open("a", encoding="utf-8") as f:
        f.write(f"2026-11-18T00:00:00\thumanities\t{ai_mirror.STUDY_ID}\n")
    assert ai_mirror._opened_before() is True
