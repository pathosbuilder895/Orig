"""Build an author-disjoint Project Gutenberg validation corpus.

The builder selects 100 writers with at least six separately catalogued English
works.  Three works become authenticated baselines and three become probes.
Selection is deterministic from the downloaded Project Gutenberg catalogue;
every retained text is content-hashed in the manifest.

This corpus is validation data, not a production training source.  Historical
literary writing is not representative of an institution, but it supplies a
useful independent domain for detecting calibration overfit to PAN fanfiction.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import io
import json
import re
import time
import urllib.request
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

CATALOG_URL = "https://www.gutenberg.org/cache/epub/feeds/pg_catalog.csv.gz"
TEXT_URL = "https://www.gutenberg.org/cache/epub/{book_id}/pg{book_id}.txt"
USER_AGENT = "Original-Authorship-Validation/1.0 (research benchmark)"
SCHEMA = "original.gutenberg.authorship.v1"

_START = re.compile(r"\*\*\*\s*START OF (?:THE|THIS) PROJECT GUTENBERG EBOOK.*?\*\*\*", re.I | re.S)
_END = re.compile(r"\*\*\*\s*END OF (?:THE|THIS) PROJECT GUTENBERG EBOOK.*", re.I | re.S)
_ROLE = re.compile(r"\[(?:editor|translator|compiler|illustrator|contributor)\]", re.I)
_CORPORATE = (
    "United States.",
    "Great Britain.",
    "Library of Congress",
    "Project Gutenberg",
)


@dataclass(frozen=True)
class CatalogWork:
    book_id: int
    title: str
    author: str
    issued: str


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _fetch(url: str, timeout: int = 45) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read()


def normalize_text(raw: bytes) -> str:
    text = raw.decode("utf-8-sig", errors="replace").replace("\r\n", "\n")
    start = _START.search(text)
    if start:
        text = text[start.end() :]
    end = _END.search(text)
    if end:
        text = text[: end.start()]
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    return text


def eligible_author(author: str) -> bool:
    lowered = author.casefold()
    return bool(author) and ";" not in author and not _ROLE.search(author) and not any(
        marker in lowered for marker in ("anonymous", "unknown", "various", "house name")
    ) and not author.startswith(_CORPORATE)


def parse_catalog(compressed: bytes) -> dict[str, list[CatalogWork]]:
    with gzip.GzipFile(fileobj=io.BytesIO(compressed)) as archive:
        content = io.TextIOWrapper(archive, encoding="utf-8-sig", newline="")
        rows = csv.DictReader(content)
        grouped: dict[str, list[CatalogWork]] = defaultdict(list)
        for row in rows:
            author = row["Authors"].strip()
            if row["Type"] != "Text" or row["Language"] != "en" or not eligible_author(author):
                continue
            grouped[author].append(
                CatalogWork(
                    book_id=int(row["Text#"]),
                    title=row["Title"].strip(),
                    author=author,
                    issued=row["Issued"].strip(),
                )
            )
    return grouped


def candidate_authors(grouped: dict[str, list[CatalogWork]], minimum_works: int = 6) -> list[str]:
    """Return stable candidates, prioritising writers with more distinct works."""
    return sorted(
        (author for author, works in grouped.items() if len(works) >= minimum_works),
        key=lambda author: (-len(grouped[author]), author.casefold()),
    )


def build_corpus(
    output_dir: Path,
    *,
    n_authors: int = 100,
    works_per_author: int = 6,
    minimum_characters: int = 8_000,
    maximum_characters: int = 24_000,
    sleep_seconds: float = 0.10,
    workers: int = 8,
) -> dict:
    output_dir.mkdir(parents=True, exist_ok=True)
    catalog_path = output_dir / "pg_catalog.csv.gz"
    catalog = catalog_path.read_bytes() if catalog_path.exists() else _fetch(CATALOG_URL)
    if not catalog_path.exists():
        catalog_path.write_bytes(catalog)
    grouped = parse_catalog(catalog)

    manifest_path = output_dir / "manifest.json"
    authors: list[dict] = []
    if manifest_path.exists():
        previous = json.loads(manifest_path.read_text(encoding="utf-8"))
        same_protocol = (
            previous.get("schema") == SCHEMA
            and previous.get("catalog_sha256") == sha256_bytes(catalog)
            and previous.get("selection", {}).get("works_per_author") == works_per_author
            and previous.get("selection", {}).get("minimum_characters") == minimum_characters
            and previous.get("selection", {}).get("maximum_characters") == maximum_characters
        )
        if same_protocol:
            authors = list(previous.get("authors", []))[:n_authors]
    seen_hashes = {
        work["sha256"] for author in authors for work in author["works"]
    }
    retained_authors = {author["author"] for author in authors}

    def fetch_work(work: CatalogWork) -> tuple[CatalogWork, str] | None:
        try:
            raw = _fetch(TEXT_URL.format(book_id=work.book_id), timeout=20)
        except Exception:
            return None
        text = normalize_text(raw)
        if len(text) < minimum_characters:
            return None
        text = text[:maximum_characters].rsplit(" ", 1)[0].strip()
        return work, text

    for author in candidate_authors(grouped, works_per_author):
        if len(authors) >= n_authors:
            break
        if author in retained_authors:
            continue
        retained: list[dict] = []
        # Oldest catalogue IDs provide a deterministic ordering and tend to
        # have stable UTF-8 cache files.
        works = sorted(grouped[author], key=lambda item: item.book_id)
        with ThreadPoolExecutor(max_workers=workers) as executor:
            fetched = executor.map(fetch_work, works[: works_per_author + 2])
        for item in fetched:
            if item is None:
                continue
            work, text = item
            digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
            if digest in seen_hashes:
                continue
            retained.append(
                {
                    "book_id": work.book_id,
                    "title": work.title,
                    "issued": work.issued,
                    "sha256": digest,
                    "characters": len(text),
                    "text": text,
                }
            )
            if len(retained) == works_per_author:
                break
        time.sleep(sleep_seconds)
        if len(retained) != works_per_author:
            continue
        seen_hashes.update(item["sha256"] for item in retained)
        authors.append({"author": author, "works": retained})
        if len(authors) == n_authors:
            break

    if len(authors) != n_authors:
        raise RuntimeError(f"only built {len(authors)} of {n_authors} requested authors")
    manifest = {
        "schema": SCHEMA,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "catalog_url": CATALOG_URL,
        "catalog_sha256": sha256_bytes(catalog),
        "selection": {
            "authors": n_authors,
            "works_per_author": works_per_author,
            "baseline_works": 3,
            "probe_works": works_per_author - 3,
            "minimum_characters": minimum_characters,
            "maximum_characters": maximum_characters,
        },
        "authors": authors,
    }
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest


def load_authors(manifest_path: Path):
    """Load the manifest into the common StyleAuthor protocol type."""
    from validation.verify.pan_style_expert import StyleAuthor

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("schema") != SCHEMA:
        raise ValueError("unsupported Gutenberg authorship manifest schema")
    result = []
    for index, author in enumerate(manifest["authors"]):
        works = author["works"]
        if len(works) < 6:
            raise ValueError("each Gutenberg author requires six distinct works")
        if len({work["sha256"] for work in works}) != len(works):
            raise ValueError("duplicate work content within Gutenberg author")
        result.append(
            StyleAuthor(
                author_id=f"gutenberg-{index:03d}",
                baseline_fandom="project-gutenberg-baseline-works",
                probe_fandom="project-gutenberg-probe-works",
                baselines=tuple(work["text"] for work in works[:3]),
                probes=tuple(work["text"] for work in works[3:6]),
            )
        )
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, default=Path(".benchmark_cache/gutenberg_authorship"))
    parser.add_argument("--authors", type=int, default=100)
    parser.add_argument("--sleep-seconds", type=float, default=0.10)
    parser.add_argument("--workers", type=int, default=8)
    args = parser.parse_args()
    result = build_corpus(
        args.output_dir,
        n_authors=args.authors,
        sleep_seconds=args.sleep_seconds,
        workers=args.workers,
    )
    print(json.dumps({"authors": len(result["authors"]), "catalog_sha256": result["catalog_sha256"]}, indent=2))


if __name__ == "__main__":
    main()
