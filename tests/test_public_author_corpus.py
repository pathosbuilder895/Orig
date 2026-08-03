"""Guards on the public-author validation corpus caches.

``_full_work_cache.txt`` is read directly by consumers that bypass the
chunking path (``validation/stability/run.py``, ``measure_lift.py``), so the
cache itself must already be free of INDEX/FOOTNOTES back-matter — not just
the chunks derived from it.
"""

from pathlib import Path

import pytest

from validation.public_authors import build_corpus as bc

_CORPUS = Path(__file__).resolve().parents[1] / "validation" / "public_authors" / "corpus"
_CACHES = sorted(_CORPUS.glob("*/_full_work_cache.txt"))


@pytest.mark.parametrize("cache", _CACHES, ids=lambda p: p.parent.name)
def test_committed_cache_has_no_back_matter(cache):
    text = cache.read_text(encoding="utf-8")
    truncated = bc._truncate_back_matter(text)
    assert text == truncated, (
        f"{cache.parent.name}/_full_work_cache.txt carries "
        f"{len(text.split()) - len(truncated.split())} words of back-matter; "
        "cache readers (validation/stability) ingest it verbatim"
    )


def test_build_writes_truncated_cache(tmp_path, monkeypatch):
    prose = (
        "It was the theory of the work that the mind of the reader would "
        "come to rest in the house of the author and find there a settled "
        "account of what had been said before. "
    ) * 200
    index_tail = "\n".join(f"Absolution, {100 + i}" for i in range(50))
    fetched = prose + "\n\nINDEX\n\n" + index_tail

    monkeypatch.setattr(bc, "_CORPUS_DIR", tmp_path)
    monkeypatch.setattr(bc, "FETCH_SLEEP_SEC", 0)
    monkeypatch.setattr(bc, "_fetch_gutenberg", lambda pg_id, title, author: fetched)

    work = bc.GutenbergWork(
        author_id="testauthor",
        author_name="Test Author",
        work_title="Test Work",
        pg_id=99999,
        n_chunks=2,
        n_baseline=1,
    )
    bc._build_from_gutenberg(work, force=True, entries=[], authors={}, skipped=[])

    cached = (tmp_path / "testauthor" / "_full_work_cache.txt").read_text(encoding="utf-8")
    assert "INDEX" not in cached
    assert cached == bc._truncate_back_matter(cached)
