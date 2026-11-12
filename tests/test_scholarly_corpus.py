"""Unit tests for validation/scholarly: no cache, no network, no poppler."""
from __future__ import annotations

import hashlib
import os
import json
import random
from collections import Counter
from pathlib import Path

import pytest
from pydantic import ValidationError

from validation.scholarly import clean, fetch, loader, openalex, policy
from validation.scholarly.schema import ScholarlyManifest, ScholarlyPaper

HERE = Path(__file__).resolve().parent.parent / "validation" / "scholarly"


# ------------------------------------------------------------------ helpers --
def _paper(aid="A1", wid="W1", words=2000, text="x", **kw):
    d = dict(source="openalex", source_paper_id=wid, author_id=aid, year=2010, field="12",
             licence="cc-by", url="https://example.org/p.pdf", word_count=words,
             text_sha256=hashlib.sha256(f"{aid}{wid}{text}".encode()).hexdigest(),
             partition=policy.partition_of(aid))
    d.update(kw)
    return ScholarlyPaper(**d)


def _author_in(partition: str, start: int = 0) -> str:
    i = start
    while policy.partition_of(f"A{i}") != partition:
        i += 1
    return f"A{i}"


# ------------------------------------------------------------------ partition --
def test_partition_is_deterministic_and_pinned():
    assert policy.partition_of("A5012345678") == policy.partition_of("A5012345678")
    # pinned: a change here silently re-partitions every author (and would leak locked_test)
    assert [policy.partition_of(f"A{i}") for i in range(6)] == ["locked_test", "development", "locked_test",
                                                               "calibration", "locked_test", "development"]


def test_partition_proportions_and_disjointness():
    counts = Counter(policy.partition_of(f"A{i}") for i in range(20000))
    n = sum(counts.values())
    assert abs(counts["development"] / n - 0.40) < 0.02
    assert abs(counts["calibration"] / n - 0.30) < 0.02
    assert abs(counts["locked_test"] / n - 0.30) < 0.02
    assert set(counts) == set(policy.PARTITIONS)


def test_partition_ignores_everything_but_author_id():
    # same id -> same partition regardless of anything else; different salt would differ
    assert policy.partition_of("A9") == _paper(aid="A9").partition


# --------------------------------------------------------------------- schema --
def test_paper_schema_accepts_valid():
    assert _paper().word_count == 2000


@pytest.mark.parametrize("bad", [
    dict(text_sha256="abc"), dict(licence="all-rights-reserved"), dict(word_count=1499),
    dict(partition="train"),
])
def test_paper_schema_rejects(bad):
    with pytest.raises(ValidationError):
        _paper(**bad)


def test_partition_must_match_hash():
    aid = "A1"
    wrong = next(p for p in policy.PARTITIONS if p != policy.partition_of(aid))
    with pytest.raises(ValidationError):
        _paper(aid=aid, partition=wrong)


def test_arxiv_tou_licence_allowed():
    assert _paper(licence=policy.ARXIV_TOU).licence == policy.ARXIV_TOU


def _manifest(n_per_author, authors=("A1", "A2")):
    papers = [_paper(aid=a, wid=f"W{a}{i}") for a in authors for i in range(n_per_author)]
    return ScholarlyManifest(collection="humanities", created_at="2026-11-11", papers=papers)


def test_manifest_floor_is_six_papers():
    assert len(_manifest(policy.MIN_USABLE_PAPERS).authors()) == 2
    with pytest.raises(ValidationError, match="fewer than 6"):
        _manifest(policy.MIN_USABLE_PAPERS - 1)


def test_manifest_rejects_duplicates_and_bad_collection():
    ps = [_paper(wid=f"W{i}") for i in range(6)]
    with pytest.raises(ValidationError, match="duplicate papers"):
        ScholarlyManifest(collection="humanities", created_at="x", papers=ps + [ps[0]])
    with pytest.raises(ValidationError, match="text hash"):
        dup = ps[:5] + [_paper(wid="W9", text="x").model_copy(update={"text_sha256": ps[0].text_sha256})]
        ScholarlyManifest(collection="humanities", created_at="x", papers=dup)
    with pytest.raises(ValidationError, match="collection"):
        ScholarlyManifest(collection="mixed", created_at="x", papers=ps)


def test_manifest_authors_in_partition():
    a_dev, a_cal = _author_in("development"), _author_in("calibration")
    m = _manifest(6, authors=(a_dev, a_cal))
    assert m.authors_in("development") == [a_dev]
    assert m.authors_in("calibration") == [a_cal]
    assert m.authors_in("locked_test") == []


# ------------------------------------------------------------------ decide() --
def test_decide_continue_done_abandon():
    assert fetch.decide(0, 0, 10) == "continue"
    assert fetch.decide(12, 12, 20) == "done"                      # cap reached: stop early
    assert fetch.decide(5, 5, 10, min_ok=6, max_ok=12) == "continue"
    assert fetch.decide(2, 5, 8) == "abandon"                      # 2 + 3 remaining < 6
    assert fetch.decide(2, 4, 8) == "continue"                     # 2 + 4 remaining == 6, still reachable
    assert fetch.decide(7, 10, 10) == "done"                       # exhausted with enough


def _author(n, aid="A1"):
    return {"author_id": aid, "n_candidates": n,
            "papers": [{"work_id": f"W{aid}{i}", "year": 2000 + i, "field": "12", "licence": "cc-by",
                        "url": f"https://example.org/{i}.pdf"} for i in range(n)]}


def _fake(ok_ids=None, fail_reason="http_403"):
    calls = []

    def fetch_one(p):
        calls.append(p["work_id"])
        good = ok_ids is None or p["work_id"] in ok_ids
        return fetch.PaperResult(p["work_id"], "A1", "ok" if good else "fail",
                                 "" if good else fail_reason, 2000 if good else 0, "h" * 64 if good else "")
    return fetch_one, calls


def test_process_author_stops_at_cap():
    f, calls = _fake()
    out = fetch.process_author(_author(30), f, {}, max_ok=12)
    assert out.status == "usable" and len(out.ok) == 12 and len(calls) == 12


def test_process_author_abandons_as_soon_as_hopeless():
    a = _author(8)
    good = {p["work_id"] for p in a["papers"][:2]}
    f, calls = _fake(good)
    out = fetch.process_author(a, f, {})
    assert out.status == "abandoned" and "usable" in out.reason
    assert len(calls) < 8, "must stop before trying every candidate once 6 is unreachable"
    assert len(out.ok) < policy.MIN_USABLE_PAPERS


def test_process_author_all_fail_abandons_after_three_with_eight_candidates():
    f, calls = _fake(set())
    out = fetch.process_author(_author(8), f, {})
    assert out.status == "abandoned" and len(calls) == 3  # 8 - 3 = 5 < 6 remaining


def test_process_author_resumes_from_state_without_refetching():
    a = _author(10)
    first, calls1 = _fake()
    state = {}
    seen = []
    fetch.process_author(a, first, state, on_result=lambda r: (seen.append(r), state.__setitem__(r.work_id, r)), max_ok=6)
    assert len(calls1) == 6
    second, calls2 = _fake()
    out = fetch.process_author(a, second, state, max_ok=6)
    assert calls2 == [] and out.status == "usable" and len(out.ok) == 6


def test_paper_order_is_deterministic_and_not_year_sorted():
    a = _author(20)
    assert [p["work_id"] for p in fetch.paper_order(a)] == [p["work_id"] for p in fetch.paper_order(a)]
    assert [p["work_id"] for p in fetch.paper_order(a)] != [p["work_id"] for p in a["papers"]]


def test_duplicate_versions_detected():
    base = " ".join(f"word{i % 400}x{i}" for i in range(2000))
    other = " ".join(f"zeta{i}q" for i in range(2000))
    assert fetch.is_duplicate(base, [fetch.shingles(base)])
    assert not fetch.is_duplicate(base, [fetch.shingles(other)])
    assert not fetch.is_duplicate("", [fetch.shingles(base)])


def test_build_manifest_drops_short_authors_entirely_and_logs_them():
    good, thin = _author(10, "A1"), _author(10, "A2")
    state = {}
    for a, n_ok in ((good, 8), (thin, 4)):
        for i, p in enumerate(a["papers"]):
            ok = i < n_ok
            state[p["work_id"]] = fetch.PaperResult(p["work_id"], a["author_id"], "ok" if ok else "fail",
                                                    "" if ok else "http_403", 2000 if ok else 0,
                                                    hashlib.sha256(p["work_id"].encode()).hexdigest() if ok else "")
    # fetch order is by hash, so make every paper tried: results exist for all of them
    manifest, dropped = fetch.build_manifest("humanities", [good, thin], state)
    assert set(manifest.authors()) == {"A1"}
    assert [d["author_id"] for d in dropped] == ["A2"] and dropped[0]["usable"] == 4
    assert len(manifest.authors()["A1"]) <= policy.MAX_USABLE_PAPERS


def test_host_limiter_spaces_arxiv_requests(monkeypatch):
    clock = {"t": 0.0}
    slept = []
    monkeypatch.setattr(fetch.time, "monotonic", lambda: clock["t"])
    monkeypatch.setattr(fetch.time, "sleep", lambda s: (slept.append(s), clock.__setitem__("t", clock["t"] + s)))
    lim = fetch.HostLimiter()
    lim.wait("arxiv.org")
    lim.wait("arxiv.org")
    assert slept and slept[-1] >= 3.0       # arXiv: no more than one request per three seconds
    n = len(slept)
    lim.wait("example.org")                 # other hosts are tracked separately
    assert len(slept) == n


# -------------------------------------------------------------------- openalex --
def _work(**over):
    w = {
        "id": "https://openalex.org/W1", "doi": "https://doi.org/10.1/x", "title": "On the nature of things",
        "publication_year": 2012, "type": "article", "language": "en",
        "biblio": {"first_page": "10", "last_page": "30"},
        "authorships": [{"author": {"id": "https://openalex.org/A1", "display_name": "Ann Author",
                                    "orcid": "https://orcid.org/0000-0001-0000-0001",
                                    "observed_orcids": ["https://orcid.org/0000-0001-0000-0001"]},
                         "raw_author_name": "Ann Author", "raw_orcid": None}],
        "primary_topic": {"field": {"id": "https://openalex.org/fields/12"},
                          "subfield": {"id": "https://openalex.org/subfields/1211"}},
        "best_oa_location": {"is_oa": True, "pdf_url": "https://example.org/p.pdf", "license": "cc-by",
                             "source": {"id": "https://openalex.org/S1", "display_name": "J"}, "version": "publishedVersion"},
        "primary_location": None, "locations": [], "is_paratext": False, "is_retracted": False,
    }
    w.update(over)
    return w


def test_compact_work_accepts_a_good_paper():
    c = openalex.compact_work(_work())
    assert c["author_id"] == "A1" and c["licence"] == "cc-by" and c["pages"] == 21
    assert c["field"] == "12" and c["subfield"] == "1211" and c["orcids"] == ["0000-0001-0000-0001"]


@pytest.mark.parametrize("over", [
    dict(authorships=_work()["authorships"] * 2),                  # two authors
    dict(language="de"), dict(type="book-chapter"), dict(is_paratext=True), dict(is_retracted=True),
    dict(title="Book Review: Things"), dict(title="Editorial"), dict(title="Erratum to: On things"),
    dict(biblio={"first_page": "1", "last_page": "3"}),             # 3 pages: a note, not a paper
    dict(best_oa_location={"is_oa": True, "pdf_url": None, "license": "cc-by"}),   # landing page only
    dict(best_oa_location={"is_oa": True, "pdf_url": "https://e.org/p.pdf", "license": None}),  # no licence
    dict(best_oa_location={"is_oa": True, "pdf_url": "https://e.org/p.pdf", "license": "other-oa"}),
])
def test_compact_work_rejects(over):
    assert openalex.compact_work(_work(**over)) is None


def test_compact_work_requires_author_id_and_orcid():
    a = json.loads(json.dumps(_work()["authorships"]))
    a[0]["author"]["orcid"], a[0]["author"]["observed_orcids"] = None, []
    assert openalex.compact_work(_work(authorships=a)) is None
    b = json.loads(json.dumps(_work()["authorships"]))
    b[0]["author"]["id"] = None
    assert openalex.compact_work(_work(authorships=b)) is None


def test_unknown_page_count_is_allowed_and_arxiv_gets_research_class():
    c = openalex.compact_work(_work(biblio={"first_page": "e123", "last_page": None}))
    assert c is not None and c["pages"] is None
    loc = {"is_oa": True, "pdf_url": "https://arxiv.org/pdf/1", "license": None,
           "source": {"id": "https://openalex.org/" + policy.ARXIV_SOURCE_ID, "display_name": "arXiv"}}
    c = openalex.compact_work(_work(best_oa_location=None, locations=[loc]))
    assert c["licence"] == policy.ARXIV_TOU and c["host"] == "arXiv"


def _cp(i, **kw):
    d = {"work_id": f"W{i}", "title": f"Paper number {i} on topic {i}", "year": 2000 + i, "orcids": ["O1"],
         "subfield": "1211"}
    d.update(kw)
    return d


def test_author_verdict_guards():
    ok, why, uniq = openalex.author_verdict([_cp(i) for i in range(8)])
    assert ok and why == "ok" and len(uniq) == 8
    assert openalex.author_verdict([_cp(i) for i in range(7)])[:2] == (False, "too_few_candidates")
    merged = [_cp(i, orcids=["O1"] if i else ["O1", "O2"]) for i in range(8)]
    assert openalex.author_verdict(merged)[:2] == (False, "multiple_orcids")
    spread = [_cp(i, year=1950 + i * 10) for i in range(8)]
    assert openalex.author_verdict(spread)[:2] == (False, "year_span")
    mixed = [_cp(i, subfield=str(1200 + i)) for i in range(8)]
    assert openalex.author_verdict(mixed)[:2] == (False, "unrelated_fields")


def test_author_verdict_collapses_multiple_versions_of_one_paper():
    versions = [_cp(i, title="The Same Paper!") for i in range(5)] + [_cp(10 + i) for i in range(5)]
    ok, why, uniq = openalex.author_verdict(versions)
    assert not ok and why == "too_few_candidates" and len(uniq) == 6


# ----------------------------------------------------------------------- clean --
def _line(text, x0, y0, h=10.0, w=None):
    n = len(text.split())
    w = w or 6.0
    words = []
    x = x0
    for tok in text.split():
        words.append(f'<word xMin="{x}" yMin="{y0}" xMax="{x + w}" yMax="{y0 + h}">{tok}</word>')
        x += w + 2
    return f'<line xMin="{x0}" yMin="{y0}" xMax="{x}" yMax="{y0 + h}">{"".join(words)}</line>'


def _page(blocks, w=600, h=800):
    return f'<page width="{w}" height="{h}">' + "".join(f'<flow><block xMin="0" yMin="0" xMax="1" yMax="1">{b}</block></flow>' for b in blocks) + "</page>"


BODY = ("The argument proceeds in three steps and each step depends on the previous one so that the whole "
        "chain of reasoning can be examined in order by a careful reader.")


def test_clean_keeps_body_and_drops_everything_else():
    xml = "<doc>" + _page([
        _line("Running head of the journal", 72, 10),                           # header band
        _line(BODY, 72, 100) + _line(BODY, 72, 112),                            # body
        _line("= ∑ x_i ≤ 3 y 2", 72, 140),                                      # display formula (short)
        _line(BODY, 100, 200) + _line(BODY, 100, 212),                          # indented block quote
        _line("1 Footnote text that is set in a smaller type and should disappear from the prose entirely here", 72, 700, h=7),
        _line("42", 300, 780),                                                  # page number
    ]) + _page([
        _line(BODY, 72, 100),
        _line("References", 72, 300, h=14),
        _line("Smith, J. 2010. A book about things. Oxford: Press. Smith, J. 2010. A book about things.", 72, 320),
    ]) + "</doc>"
    text = clean.clean_pages(clean.parse_bbox(xml))
    assert BODY.split()[0] in text and "three steps" in text
    assert "Footnote" not in text and "Running head" not in text and "∑" not in text
    assert "A book about things" not in text           # references cut
    assert text.count("three steps") == 3              # 2 sentences + 1 sentence of body; the quote (2 more) is excluded


def test_clean_reference_heading_only_counts_in_back_half():
    xml = "<doc>" + _page([_line("Notes", 72, 100, h=10), _line(BODY, 72, 120), _line(BODY, 72, 132)]) + "</doc>"
    assert "three steps" in clean.clean_pages(clean.parse_bbox(xml))   # a front-of-document "Notes" is not a cut


def test_clean_joins_hyphenation_and_page_break_continuation():
    a = "The argument proceeds in three steps and each step depends on the previ-"
    b = "ous one so that the whole chain of reasoning can be examined in order by readers."
    xml = "<doc>" + _page([_line(a, 72, 100) + _line(b, 72, 112)]) + "</doc>"
    assert "previous one" in clean.clean_pages(clean.parse_bbox(xml))


def test_strip_inline_removes_citations_urls_and_math_residue():
    s = "As argued (Smith 2010, p. 4) and [3] and [Jones et al. 1994] see https://x.org/a where x ∈ R and y = 2 it holds."
    out = clean.strip_inline(s)
    assert "2010" not in out and "[3]" not in out and "1994" not in out and "http" not in out
    assert "∈" not in out and " y " not in out and "holds" in out


def test_is_english_and_alpha_fraction():
    assert clean.is_english("the cat is on the mat and it is in the house of the man " * 5)
    assert not clean.is_english("der Hund ist auf dem Tisch und die Katze sitzt unter dem Stuhl " * 5)
    assert clean.alpha_fraction("one two three") == 1.0 and clean.alpha_fraction("1 2 3 =") == 0.0


def test_pdf_bytes_rejects_non_pdf(tmp_path):
    assert clean.pdf_bytes_to_text(b"<html>not a pdf</html>", tmp_path) is None


# ---------------------------------------------------------------------- loader --
def _prose(tag: str, n_words: int) -> str:
    paras, w = [], 0
    i = 0
    while w < n_words:
        p = " ".join(f"{tag}w{(i * 7 + j) % 97}" for j in range(60))
        paras.append(p)
        w += 60
        i += 1
    return "\n\n".join(paras)


@pytest.fixture
def corpus(tmp_path):
    cache = tmp_path / "cache"
    papers, texts = [], {}
    authors = [_author_in("development", 0)]
    for k in range(3):
        authors.append(_author_in("development", int(authors[-1][1:]) + 1))
    authors.append(_author_in("locked_test"))
    for aid in authors:
        for i in range(7):
            wid = f"W{aid}_{i}"
            t = _prose(f"{aid}_{i}", 1800)
            d = cache / "humanities" / "texts" / aid
            d.mkdir(parents=True, exist_ok=True)
            (d / f"{wid}.txt").write_text(t, encoding="utf-8")
            papers.append(_paper(aid=aid, wid=wid, words=len(t.split()), text=t).model_copy(
                update={"text_sha256": hashlib.sha256(t.encode()).hexdigest()}))
    m = ScholarlyManifest(collection="humanities", created_at="2026-11-11", papers=papers)
    return m, cache, authors


def test_loader_builds_disjoint_trials_with_other_author_probes(corpus):
    m, cache, authors = corpus
    ts = loader.load_trials("humanities", "development", manifest=m, cache=cache, n_past=4, n_new=2,
                            past_words=1200, new_words=300, n_probes=2)
    assert len(ts.trials) == 4 and not ts.skipped
    for t in ts.trials:
        assert len(t.baseline) == 4 and len(t.honest) == 2 and len(t.probes) == 2
        assert all(len(x.split()) == 1200 for x in t.baseline) and all(len(x.split()) == 300 for x in t.honest)
        assert set(t.baseline_ids).isdisjoint(t.honest_ids)               # no document on both sides
        assert t.student_id not in t.probe_sources                        # probes are other authors
        own = set(t.baseline) | set(t.honest)
        assert own.isdisjoint(t.probes)
    # shape the existing harnesses read
    assert all(hasattr(t, a) for t in ts.trials for a in ("student_id", "baseline", "honest"))


def test_loader_is_deterministic_and_seed_sensitive(corpus):
    m, cache, _ = corpus
    a = loader.load_trials("humanities", "development", manifest=m, cache=cache, seed=1)
    b = loader.load_trials("humanities", "development", manifest=m, cache=cache, seed=1)
    c = loader.load_trials("humanities", "development", manifest=m, cache=cache, seed=2)
    assert a.trials == b.trials and a.trials != c.trials


def test_loader_refuses_an_author_with_fewer_than_six_papers(corpus):
    m, cache, authors = corpus
    thin_id = authors[1]
    keep = [p for p in m.papers if p.author_id != thin_id]
    thin = [p for p in m.papers if p.author_id == thin_id][:5]
    bad = ScholarlyManifest.model_construct(collection="humanities", created_at="x", version="1",
                                            policy_version=policy.POLICY_VERSION, papers=keep + thin)
    with pytest.raises(loader.ThinAuthorError, match="floor"):
        loader.load_trials("humanities", "development", manifest=bad, cache=cache)


def test_loader_skips_an_author_with_a_missing_or_tampered_cache_and_says_why(corpus):
    m, cache, authors = corpus
    f = next((cache / "humanities" / "texts" / authors[0]).glob("*.txt"))
    f.write_text("tampered " * 2000, encoding="utf-8")
    ts = loader.load_trials("humanities", "development", manifest=m, cache=cache)
    assert authors[0] in ts.skipped and "hash" in ts.skipped[authors[0]]
    assert authors[0] not in [t.student_id for t in ts.trials] and len(ts.trials) == 3   # the others still load
    f.unlink()
    ts = loader.load_trials("humanities", "development", manifest=m, cache=cache)
    assert "missing" in ts.skipped[authors[0]]


def test_loader_reports_authors_it_cannot_cut_instead_of_dropping_them_silently(corpus):
    m, cache, _ = corpus
    ts = loader.load_trials("humanities", "development", manifest=m, cache=cache, past_words=1900, new_words=1900, n_past=4, n_new=2)
    assert ts.trials == [] and len(ts.skipped) == 4


def test_locked_partition_needs_a_named_study_and_is_logged(corpus, monkeypatch, tmp_path):
    m, cache, _ = corpus
    log = tmp_path / "LOCKED_OPENINGS.tsv"
    monkeypatch.setattr(loader, "LOCKED_LOG", log)
    with pytest.raises(loader.LockedPartitionError):
        loader.load_trials("humanities", "locked_test", manifest=m, cache=cache)
    with pytest.raises(loader.LockedPartitionError):
        loader.load_trials("humanities", "locked_test", manifest=m, cache=cache, allow_locked_for="  ")
    assert not log.exists()
    loader.load_trials("humanities", "locked_test", manifest=m, cache=cache, allow_locked_for="prereg-001", n_probes=0)
    assert "prereg-001" in log.read_text()


def test_loader_argument_validation(corpus):
    m, cache, _ = corpus
    with pytest.raises(ValueError):
        loader.load_trials("humanities", "train", manifest=m, cache=cache)
    with pytest.raises(ValueError):
        loader.load_trials("humanities", "development", manifest=m, cache=cache, n_past=10, n_new=5)
    with pytest.raises(ValueError):
        loader.load_trials("humanities", "development", manifest=m, cache=cache, n_past=0)


def test_cut_words_exact_length_and_error():
    t = _prose("a", 900)
    assert len(loader.cut_words(t, 500, random.Random(1)).split()) == 500
    with pytest.raises(ValueError):
        loader.cut_words(t, 5000, random.Random(1))


# ------------------------------------------------------------------- hygiene --
def test_cache_is_git_ignored_and_no_paper_text_is_tracked():
    root = HERE.parent.parent
    assert "validation/scholarly/cache/" in (root / ".gitignore").read_text()
    assert not list(HERE.glob("*.txt")), "paper text must never live beside the code"


@pytest.mark.parametrize("collection", ["humanities", "science"])
def test_committed_manifests_validate_when_present(collection):
    p = HERE / "manifest" / f"{collection}.json"
    if not p.exists():
        pytest.skip("manifest not built yet")
    m = ScholarlyManifest.model_validate_json(p.read_text(encoding="utf-8"))
    assert all(len(ps) >= policy.MIN_USABLE_PAPERS for ps in m.authors().values())


@pytest.mark.parametrize("collection", ["humanities", "science"])
def test_committed_candidate_lists_are_screened_and_ranked(collection):
    p = HERE / "candidates" / f"{collection}.json"
    if not p.exists():
        pytest.skip("candidate list not built yet")
    d = json.loads(p.read_text(encoding="utf-8"))
    counts = [a["n_candidates"] for a in d["authors"]]
    assert counts == sorted(counts, reverse=True)
    assert all(c >= policy.MIN_SCREEN_CANDIDATES for c in counts)
    assert all(a["partition"] == policy.partition_of(a["author_id"]) for a in d["authors"])
    assert all(policy.MIN_SCREEN_CANDIDATES <= len(a["papers"]) <= a["n_candidates"] for a in d["authors"])


# -------------------------------------------------------------------- baseline --
def test_baseline_metrics_and_author_bootstrap():
    from validation.scholarly import baseline
    per = [{"author": f"A{i}", "honest": [0.2, 0.3], "honest_flag": [False, i % 2 == 0],
            "probe": [0.5, 0.6, 0.7], "probe_flag": [True, True, False]} for i in range(6)]
    m = baseline.metrics(per)
    assert m["auc"] == 1.0 and m["n_honest"] == 12 and m["n_probe"] == 18
    assert m["honest_flag_rate"] == pytest.approx(0.25) and m["other_writer_catch_rate"] == pytest.approx(2 / 3)
    ci = baseline.bootstrap(per, n_boot=50, seed=1)
    assert set(ci) == {"honest_flag_rate", "other_writer_catch_rate", "auc"}
    assert all(lo <= hi for lo, hi in ci.values())
    assert baseline.bootstrap(per, 50, 1) == ci   # seeded


def test_baseline_never_touches_locked_partition():
    import inspect
    from validation.scholarly import baseline
    src = inspect.getsource(baseline)
    assert "allow_locked_for" not in src          # no way to open the locked partition from here
    assert src.count('"development"') >= 2        # the only partition it loads


def test_clean_drops_footnote_markers_and_other_language_paragraphs():
    assert clean.strip_inline("It ended at Ravenna.1 The two fleets were large, see Dan 1-6.") == \
        "It ended at Ravenna. The two fleets were large, see Dan 1-6."
    # digits glued to letters are NOT footnote markers (v1 turned p53 into p and dropped it)
    assert clean.strip_inline("The p53 protein and log2 scale and mp3 files were used here") == \
        "The p53 protein and log2 scale and mp3 files were used here"
    afr = ("Die verhale in die Danielboek vertoon nie apokaliptiese eienskappe nie, met die uitsondering van "
           "Daniel wat oor Nebukadnesar se droom handel en die groter geheel van die boek.")
    xml = "<doc>" + _page([_line(BODY, 72, 100) + _line(BODY, 72, 112), _line(afr, 72, 160) + _line(afr, 72, 172)]) + "</doc>"
    text = clean.clean_pages(clean.parse_bbox(xml))
    assert "three steps" in text and "Danielboek" not in text


def test_post_rules_drop_foreign_titles_and_excluded_hosts():
    ok = {"title": "Morality in Africa: yesterday and today", "host": "Some Journal"}
    assert openalex.post_rules(ok)
    assert not openalex.post_rules({"title": "Christusprediking uit die Ou Testament", "host": "x"})
    assert not openalex.post_rules({"title": "Достоевский и мировая культура", "host": "x"})
    assert not openalex.post_rules({**ok, "host": next(iter(policy.EXCLUDED_HOSTS))})


def test_paper_order_tries_non_arxiv_hosts_first():
    a = _author(6)
    a["papers"][0]["url"] = "https://arxiv.org/pdf/1"
    a["papers"][3]["url"] = "https://export.arxiv.org/pdf/2"
    order = [p["url"] for p in fetch.paper_order(a)]
    assert all("arxiv.org" in u for u in order[-2:]) and not any("arxiv.org" in u for u in order[:-2])


def test_build_manifest_drops_a_text_that_two_authors_share():
    a1, a2 = _author(8, "A1"), _author(8, "A2")
    state = {}
    for a in (a1, a2):
        for p in a["papers"]:
            sha = hashlib.sha256(b"shared").hexdigest() if (a is a2 and p["work_id"].endswith("0")) \
                else hashlib.sha256(p["work_id"].encode()).hexdigest()
            state[p["work_id"]] = fetch.PaperResult(p["work_id"], a["author_id"], "ok", "", 2000, sha)
    state[a1["papers"][0]["work_id"]] = fetch.PaperResult(a1["papers"][0]["work_id"], "A1", "ok", "", 2000,
                                                          hashlib.sha256(b"shared").hexdigest())
    manifest, _ = fetch.build_manifest("humanities", [a1, a2], state)
    assert len({p.text_sha256 for p in manifest.papers}) == len(manifest.papers)
    assert len(manifest.authors()) == 2


def test_post_rules_science_only_exclusions():
    c = {"title": "A good title", "host": "arXiv", "url": "https://link.springer.com/x.pdf", "subfield": "2601"}
    assert openalex.post_rules(c, "humanities") and not openalex.post_rules(c, "science")
    d = {"title": "A good title", "host": "arXiv", "url": "https://arxiv.org/pdf/1", "subfield": "2607"}
    assert not openalex.post_rules(d, "science")


def test_verify_and_restore_round_trip(corpus, tmp_path, monkeypatch):
    m, cache, authors = corpus
    mdir = tmp_path / "manifest"
    mdir.mkdir()
    (mdir / "humanities.json").write_text(m.model_dump_json(), encoding="utf-8")
    assert fetch.verify("humanities", cache, mdir)["ok"] == len(m.papers)
    # lose one text and tamper with another
    files = sorted((cache / "humanities" / "texts" / authors[0]).glob("*.txt"))
    wanted = files[0].read_text(encoding="utf-8")
    files[0].unlink()
    files[1].write_text("changed", encoding="utf-8")
    v = fetch.verify("humanities", cache, mdir)
    assert v["missing"] == 1 and v["hash_mismatch"] == 1 and v["ok"] == len(m.papers) - 2
    # restore re-creates only the missing one, and only when the hash matches
    url_text = {p.url: None for p in m.papers}
    monkeypatch.setattr(fetch.clean, "pdf_bytes_to_text", lambda body, tmp, name="": body.decode())
    r = fetch.restore("humanities", cache, 2, mdir, fetch_url=lambda u: wanted.encode())
    assert r["restored"] == 1 and r["mismatch"] == 0 and r["already_present"] == len(m.papers) - 1
    monkeypatch.setattr(fetch.clean, "pdf_bytes_to_text", lambda body, tmp, name="": "other text")
    files[0].unlink()
    r = fetch.restore("humanities", cache, 2, mdir, fetch_url=lambda u: b"x")
    assert r["restored"] == 0 and r["mismatch"] == 1 and not files[0].exists()


def test_host_limiter_never_overlaps_two_requests_on_one_host():
    import threading, time as _t
    lim = fetch.HostLimiter(intervals={"h": 0.0}, default=0.0)
    active, peak, lock = [0], [0], threading.Lock()

    def req():
        with lim.slot("h"):
            with lock:
                active[0] += 1
                peak[0] = max(peak[0], active[0])
            _t.sleep(0.02)
            with lock:
                active[0] -= 1

    ts = [threading.Thread(target=req) for _ in range(8)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert peak[0] == 1


def test_duplicate_detection_survives_a_one_word_offset():
    base = " ".join(f"tok{i % 997}z{i}" for i in range(2000))
    shifted = "Running head " + base           # same paper, two extra leading words
    assert fetch.is_duplicate(shifted, [fetch.shingles(base)])


def test_restore_warns_when_papers_were_cleaned_by_an_older_cleaner(corpus, tmp_path):
    m, cache, _ = corpus
    mdir = tmp_path / "manifest"
    mdir.mkdir()
    (mdir / "humanities.json").write_text(m.model_dump_json(), encoding="utf-8")  # papers default to cleaner v1
    r = fetch.restore("humanities", cache, 1, mdir, fetch_url=lambda u: None)
    assert "warning" in r and "older cleaner" in r["warning"]


# ---------------------------------------------------------------- intended use --
def _pa(author, honest, probe):
    return {"author": author, "honest": honest, "honest_flag": [False] * len(honest),
            "probe": probe, "probe_flag": [True] * len(probe)}


def test_intended_use_refuses_locked_and_unknown_partitions():
    from validation.scholarly import intended_use
    assert intended_use.check_partition("development") == "development"
    for bad in ("locked_test", "test", ""):
        with pytest.raises(ValueError):
            intended_use.check_partition(bad)
    import inspect
    assert "allow_locked_for" not in inspect.getsource(intended_use)


def test_intended_use_pools_seeds_by_author():
    from validation.scholarly import intended_use
    s1 = [_pa("A1", [0.1], [0.5]), _pa("A2", [0.2], [0.6])]
    s2 = [_pa("A1", [0.3], [0.7])]
    pooled = intended_use.pool_by_author([s1, s2])
    assert [a["author"] for a in pooled] == ["A1", "A2"]
    assert pooled[0]["honest"] == [0.1, 0.3] and pooled[0]["probe"] == [0.5, 0.7]


def test_intended_use_threshold_gives_target_rate_and_transfers():
    from validation.scholarly import intended_use
    cal = [_pa(f"A{i}", [i / 100], [1.5]) for i in range(100)]
    thr = intended_use.pick_threshold(cal, 0.05)
    r = intended_use.rates_at(cal, thr)
    assert r["honest_flag_rate"] <= 0.05 and r["other_writer_catch_rate"] == 1.0
    dev = [_pa("B", [thr + 0.01, thr - 0.01], [thr - 0.5, thr + 0.5])]
    assert intended_use.rates_at(dev, thr) == {"honest_flag_rate": 0.5, "other_writer_catch_rate": 0.5}
    ci = intended_use.bootstrap_at(cal, thr, n_boot=50)
    assert ci["honest_flag_rate"][0] <= ci["honest_flag_rate"][1]
    with pytest.raises(ValueError):
        intended_use.pick_threshold([_pa("C", [], [0.1])])


def test_intended_use_reset_clears_research_flags(monkeypatch):
    from validation.scholarly import intended_use
    monkeypatch.setenv("NULL_MODEL", "impostor")
    monkeypatch.setenv("RANK_REMEDIATION", "shrinkage")
    removed = intended_use.reset_research_flags()
    assert set(removed) >= {"NULL_MODEL", "RANK_REMEDIATION"} and "NULL_MODEL" not in os.environ


# --------------------------------------------------------------- adjustments --
def test_length_matched_cuts_past_papers_into_new_paper_sized_pieces():
    from validation.scholarly import adjust
    t = loader.ScholarlyTrial("A1", [" ".join(f"w{i}" for i in range(1200))] * 2, ["n " * 300], [],
                              baseline_ids=["P1", "P2"], honest_ids=["P3"])
    lm = adjust.length_matched(t, 300)
    assert len(lm.baseline) == 8 and all(len(x.split()) == 300 for x in lm.baseline)
    assert lm.baseline_ids[:2] == ["P1#0", "P1#1"] and lm.honest == t.honest
    assert set(lm.baseline_ids).isdisjoint(t.honest_ids)


def test_catch_at_rate_and_its_bootstrap():
    from validation.scholarly import adjust
    per = [{"author": f"A{i}", "honest": [i / 100], "probe": [2.0]} for i in range(100)]
    c = adjust.catch_at_rate(per, 0.05)
    assert c["honest_above"] <= 0.05 and c["catch"] == 1.0
    lo, hi = adjust.bootstrap_catch(per, n_boot=30)
    assert lo <= hi == 1.0


def test_candidates_default_to_flags_off_and_combinations_merge():
    from validation.scholarly import adjust
    base = adjust.CANDIDATES["flags_off"]
    assert not any([base.length_matched, base.length_adaptive, base.topic_inflation, base.characteristic, base.llr])
    c = adjust.register_combination("f_test", "because", "a_length_matched", "e_impostor_llr")
    assert c.length_matched and c.llr and c.needs_pool and not c.topic_inflation
    adjust.CANDIDATES.pop("f_test")


def test_adjust_refuses_locked_partition():
    from validation.scholarly import adjust
    with pytest.raises(ValueError):
        adjust.trial_sets("humanities", "locked_test")


def test_diagnosis_labels_need_the_80th_percentile():
    import numpy as np
    from validation.scholarly import diagnose
    active = np.array([True, True, True, True, True, False])
    r = diagnose.percentile_ranks(np.array([5.0, 1.0, 3.0, 2.0, 4.0, 99.0]), active)
    assert r[0] == 1.0 and r[1] == 0.0 and r[5] == 0.0
    ranks = {"length": np.array([0.9, 0.1]), "topic": np.array([0.5, 0.79]),
             "section": np.array([0.2, 0.3]), "house": np.array([0.95, 0.0])}
    assert diagnose.label_feature(0, ranks) == "house" and diagnose.label_feature(1, ranks) == "genuine"
    assert diagnose.label_feature(1, ranks, z_full=4.0, z_matched=1.5) == "length"     # excess vanishes at matched length
    assert diagnose.label_feature(0, ranks, z_full=4.0, z_matched=3.0) == "house"


# ------------------------------------------------------------------- verifier --
def test_mask_topic_keeps_function_words_and_shapes_only():
    from validation.scholarly import verifier
    out = verifier.mask_topic("The Eucharist, in 1999, was central to the theology of Calvin.")
    assert out.startswith("The ") and "Eucharist" not in out and "Calvin" not in out
    assert "*********," in out and "####," in out and " to the " in out


def test_relative_rank_and_z():
    import numpy as np
    from validation.scholarly import verifier
    own, z, rank = verifier._relative(0.9, np.array([0.1, 0.2, 0.3]), higher_is_closer=True)
    assert own == 0.9 and z > 0 and rank == 0.0
    own, z, rank = verifier._relative(0.5, np.array([0.1, 0.2, 0.3]), higher_is_closer=False)
    assert z < 0 and rank == 1.0


def test_fold_rule_keeps_probe_source_in_the_same_fold():
    from validation.scholarly import verifier
    a = next(f"A{i}" for i in range(100) if verifier.split_of(f"A{i}") == 0)
    b = next(f"A{i}" for i in range(100) if verifier.split_of(f"A{i}") == 1)
    assert verifier._fold_ok({"author": a, "src": None}, 0)
    assert not verifier._fold_ok({"author": a, "src": b}, 0) and not verifier._fold_ok({"author": a, "src": b}, 1)
    assert verifier.split_of(a) == verifier.split_of(a)


def test_per_author_tallies_by_probe_kind():
    from validation.scholarly import verifier
    rows = [{"author": "A", "label": 0, "kind": "honest"}, {"author": "A", "label": 1, "kind": "random"},
            {"author": "A", "label": 1, "kind": "same_field"}]
    pa = verifier._per_author(rows, [0.1, 0.8, 0.6], kinds=("same_field",))
    assert pa == [{"author": "A", "honest": [0.1], "probe": [0.6]}]


def test_verifier_cannot_read_locked_test():
    from validation.scholarly import verifier
    with pytest.raises(ValueError):
        verifier.build_rows("humanities", "locked_test")


# ------------------------------------------------------------------- ablation --
def test_ablation_column_masks_and_fixed_combination():
    import numpy as np
    from validation.scholarly import ablation, verifier
    names = verifier.column_names()
    assert len(names) == 3 + 3 * 6 + 3 + 2 * 109
    full = np.ones(len(names), dtype=bool)
    for ing in ablation.INGREDIENTS:
        if ing == "1_length_matched":
            continue
        keep = ablation.drop_mask(names, ing)
        assert 0 < keep.sum() < full.sum(), ing
    assert not any(n.startswith("pos:") for n, k in zip(names, ablation.drop_mask(names, "5_pos")) if k)
    imp = ablation.drop_mask(names, "6_impostor")
    assert all(not (n.endswith(":z") or n.endswith(":rank")) for n, k in zip(names, imp) if k)
    assert ablation.alone_mask(names, "7_nearest_piece").sum() == 9
    x = np.zeros(len(names))
    x[names.index("char:centroid:z")] = 2.0
    assert ablation.fixed_combination(x, names) < 0      # closer to the author than peers = more honest-looking
