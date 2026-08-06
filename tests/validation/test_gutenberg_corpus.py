import csv
import gzip
import io
import json

from validation.verify.gutenberg_corpus import (
    SCHEMA,
    candidate_authors,
    eligible_author,
    load_authors,
    normalize_text,
    parse_catalog,
)


def _catalog(rows):
    buffer = io.BytesIO()
    with gzip.GzipFile(fileobj=buffer, mode="wb") as archive:
        text = io.TextIOWrapper(archive, encoding="utf-8-sig", newline="")
        writer = csv.DictWriter(
            text,
            fieldnames=["Text#", "Type", "Issued", "Title", "Language", "Authors", "Subjects", "LoCC", "Bookshelves"],
        )
        writer.writeheader()
        writer.writerows(rows)
        text.flush()
    return buffer.getvalue()


def test_normalize_text_removes_gutenberg_boilerplate():
    raw = b"header\n*** START OF THE PROJECT GUTENBERG EBOOK SAMPLE ***\nBody  text.\n*** END OF THE PROJECT GUTENBERG EBOOK SAMPLE ***\nfooter"
    assert normalize_text(raw) == "Body text."


def test_author_eligibility_rejects_ambiguous_attribution():
    assert eligible_author("Dickens, Charles, 1812-1870")
    assert not eligible_author("Dickens, Charles, 1812-1870 [Editor]")
    assert not eligible_author("Austen, Jane; Bronte, Charlotte")
    assert not eligible_author("Anonymous")
    assert not eligible_author("United States. Congress")


def test_catalog_candidates_are_stable_and_require_distinct_records():
    rows = []
    for author, count in (("Writer, Prolific", 7), ("Writer, Eligible", 6), ("Writer, Short", 5)):
        for index in range(count):
            rows.append(
                {
                    "Text#": str(len(rows) + 1),
                    "Type": "Text",
                    "Issued": "2000-01-01",
                    "Title": f"Work {index}",
                    "Language": "en",
                    "Authors": author,
                    "Subjects": "",
                    "LoCC": "",
                    "Bookshelves": "",
                }
            )
    grouped = parse_catalog(_catalog(rows))
    assert candidate_authors(grouped) == ["Writer, Prolific", "Writer, Eligible"]


def test_manifest_loader_separates_three_works_from_three_probes(tmp_path):
    works = [
        {"sha256": f"hash-{index}", "text": f"work {index}"}
        for index in range(6)
    ]
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps({"schema": SCHEMA, "authors": [{"author": "A", "works": works}]}))
    authors = load_authors(path)
    assert authors[0].baselines == ("work 0", "work 1", "work 2")
    assert authors[0].probes == ("work 3", "work 4", "work 5")
