from validation.public_authors.build_corpus import _chunk_text
import hashlib
import json

from validation.public_authors.build_cross_work import CORPUS, MANIFEST, WORKS, _sample_windows


def test_chunker_rejects_toc_sized_chapters() -> None:
    tiny_toc = "\nCHAPTER I\nOne\nCHAPTER II\nTwo\nCHAPTER III\nThree"
    chunks = _chunk_text(tiny_toc, 3)
    # It falls back to paragraph buckets instead of blessing tiny headings as
    # stylometric documents. A real builder then rejects sub-300-word output.
    assert not all(len(chunk.split()) < 3 for chunk in chunks)


def test_cross_work_sources_do_not_cross_split() -> None:
    roles = {}
    for work in WORKS:
        key = (work.author_id, work.title)
        assert key not in roles
        roles[key] = work.role
    for author in {work.author_id for work in WORKS}:
        assert {work.role for work in WORKS if work.author_id == author} == {"baseline", "probe"}


def test_cross_work_includes_named_authors_and_multiple_essayists() -> None:
    authors = {work.author_id for work in WORKS}
    assert {"dickens", "christie", "chesterton"} <= authors
    essayists = {work.author_id for work in WORKS if work.genre == "essay"}
    assert {"chesterton", "emerson", "mill", "thoreau"} <= essayists


def test_cross_work_windows_are_fixed_length_and_spaced() -> None:
    text = " ".join(f"w{i}" for i in range(1000))
    windows = _sample_windows(text, 3, words_per_window=100)
    assert [len(window.split()) for window in windows] == [100, 100, 100]
    assert windows[0].split()[0] == "w0"
    assert windows[-1].split()[-1] == "w999"


def test_cross_work_hash_contract_is_content_addressed() -> None:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    assert manifest["version"] == "3.0-six-author-cross-work"
    source_hashes = {}
    for entry in manifest["entries"]:
        text = (CORPUS / entry["filename"]).read_text(encoding="utf-8")
        assert hashlib.sha256(text.encode("utf-8")).hexdigest() == entry["text_sha256"]
        work = (entry["author_id"], entry["work_id"])
        source_hashes.setdefault(work, entry["source_body_sha256"])
        assert source_hashes[work] == entry["source_body_sha256"]
