"""Compile committed author corpora into deterministic TermSim personas."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUT = ROOT / ".benchmark_cache" / "termsim" / "personas.json"


def chunk_text(text: str, minimum=300, target=900, maximum=1500) -> list[str]:
    paragraphs = [re.sub(r"\s+", " ", p).strip() for p in re.split(r"\n\s*\n", text)]
    paragraphs = [p for p in paragraphs if p]
    chunks: list[str] = []
    current: list[str] = []
    words = 0
    for paragraph in paragraphs:
        p_words = paragraph.split()
        if current and words + len(p_words) > target:
            chunks.append(" ".join(current))
            current, words = [], 0
        # Bound pathological single paragraphs without changing word order.
        while len(p_words) > maximum:
            if current:
                chunks.append(" ".join(current))
                current, words = [], 0
            chunks.append(" ".join(p_words[:maximum]))
            p_words = p_words[maximum:]
        current.extend(p_words)
        words += len(p_words)
    if current:
        if words >= minimum:
            chunks.append(" ".join(current))
        elif chunks and len(chunks[-1].split()) + words <= maximum:
            chunks[-1] += " " + " ".join(current)
    return [chunk for chunk in chunks if minimum <= len(chunk.split()) <= maximum]


def _author_sources(root: Path):
    for source, base in (
        ("public_authors", root / "validation" / "public_authors" / "corpus"),
        ("genre", root / "validation" / "genre_2026-08" / "corpus"),
    ):
        if not base.exists():
            continue
        for author_dir in sorted(p for p in base.iterdir() if p.is_dir()):
            yield source, author_dir


def build_manifest(root: Path = ROOT) -> dict:
    personas = []
    for source, author_dir in _author_sources(root):
        documents = []
        for path in sorted(author_dir.glob("*.txt")):
            if path.name.startswith("_"):
                continue
            for index, text in enumerate(chunk_text(path.read_text(errors="ignore"))):
                documents.append(
                    {
                        "id": f"{path.stem}-{index:03d}",
                        "path": str(path.relative_to(root)),
                        "chunk_index": index,
                        "words": len(text.split()),
                        "sha256": hashlib.sha256(text.encode()).hexdigest(),
                        "genre": None,
                        "provenance": "corpus-derived-synthetic-persona",
                    }
                )
        if len(documents) >= 3:
            personas.append(
                {
                    "id": f"{source}:{author_dir.name}",
                    "source": source,
                    "author": author_dir.name,
                    "documents": documents,
                    "n_docs": len(documents),
                    "genres_available": [],
                    "has_longitudinal_order": False,
                }
            )
    # The mixed committed validation corpus has author-labelled filenames
    # rather than author directories. Keep AI documents for the AI scenario,
    # not as synthetic honest personas.
    mixed: dict[str, list[Path]] = {}
    for path in sorted((root / "validation" / "corpus").glob("*.txt")):
        author = re.sub(r"_\d+$", "", path.stem)
        if author.startswith("ai"):
            continue
        mixed.setdefault(author, []).append(path)
    for author, paths in sorted(mixed.items()):
        documents = []
        for path in paths:
            for index, text in enumerate(chunk_text(path.read_text(errors="ignore"))):
                documents.append(
                    {
                        "id": f"{path.stem}-{index:03d}",
                        "path": str(path.relative_to(root)),
                        "chunk_index": index,
                        "words": len(text.split()),
                        "sha256": hashlib.sha256(text.encode()).hexdigest(),
                        "genre": "seminary-analogue",
                        "provenance": "corpus-derived-synthetic-persona",
                    }
                )
        if len(documents) >= 3:
            personas.append(
                {
                    "id": f"mixed:{author}",
                    "source": "validation_corpus",
                    "author": author,
                    "documents": documents,
                    "n_docs": len(documents),
                    "genres_available": ["seminary-analogue"],
                    "has_longitudinal_order": False,
                }
            )
    manifest = {
        "honesty": (
            "Corpus-derived synthetic students; absolute rates do not transfer to real students. "
            "Only same-script differences between configurations are interpretable."
        ),
        "personas": personas,
    }
    manifest["manifest_sha256"] = hashlib.sha256(
        json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return manifest


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--build", action="store_true")
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    args = parser.parse_args(argv)
    manifest = build_manifest()
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    counts = sorted(p["n_docs"] for p in manifest["personas"])
    median = counts[len(counts) // 2] if counts else 0
    print(f"personas={len(counts)} median_docs={median} manifest={manifest['manifest_sha256']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
