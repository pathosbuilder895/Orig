"""Compile committed author corpora into deterministic TermSim personas.

Personas carry work-group structure: every document belongs to a named work
(a book, a dialogue, a seminary paper), and the groups are what lets the
script distinguish an HONEST term (home-work submissions) from a TRANSFER
term (same author, held-out work) on purpose rather than by accident of
chunk ordering. Genre labels come from validation/genre_2026-08/labels.json
where that study labelled the underlying file; everything else is None.
"""
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


def _genre_labels(root: Path) -> dict[str, str]:
    """Map repo-relative document path -> genre label, from the 2026-08 study."""
    labels_path = root / "validation" / "genre_2026-08" / "labels.json"
    if not labels_path.exists():
        return {}
    data = json.loads(labels_path.read_text())
    return {entry["path"]: entry["label"] for entry in data.get("entries", [])}


def _document_entries(path: Path, root: Path, work: str, genre: str | None) -> list[dict]:
    documents = []
    for index, text in enumerate(chunk_text(path.read_text(errors="ignore"))):
        documents.append(
            {
                "id": f"{path.stem}-{index:03d}",
                "path": str(path.relative_to(root)),
                "chunk_index": index,
                "work": work,
                "words": len(text.split()),
                "sha256": hashlib.sha256(text.encode()).hexdigest(),
                "genre": genre,
                "provenance": "corpus-derived-synthetic-persona",
            }
        )
    return documents


def _grouped(documents: list[dict], work_order: list[str] | None = None) -> list[dict]:
    """Order works largest-first (stable by name) unless an explicit order is given."""
    by_work: dict[str, list[int]] = {}
    for index, document in enumerate(documents):
        by_work.setdefault(document["work"], []).append(index)
    if work_order is None:
        works = sorted(by_work, key=lambda w: (-len(by_work[w]), w))
    else:
        works = [w for w in work_order if w in by_work]
        works += sorted(w for w in by_work if w not in works)
    return [{"work": work, "doc_indices": by_work[work]} for work in works]


def _persona(persona_id: str, source: str, author: str, documents: list[dict],
             work_order: list[str] | None = None, longitudinal: bool = False) -> dict:
    groups = _grouped(documents, work_order)
    genres = sorted({d["genre"] for d in documents if d["genre"]})
    return {
        "id": persona_id,
        "source": source,
        "author": author,
        "documents": documents,
        "n_docs": len(documents),
        "groups": groups,
        "n_groups": len(groups),
        "genres_available": genres,
        "has_longitudinal_order": longitudinal,
    }


def build_manifest(root: Path = ROOT) -> dict:
    genre_of = _genre_labels(root)
    personas = []
    for source, base, work_suffix in (
        ("public_authors", root / "validation" / "public_authors" / "corpus",
         r"_part_\d+$"),
        ("genre", root / "validation" / "genre_2026-08" / "corpus", r"_\d+$"),
    ):
        if not base.exists():
            continue
        for author_dir in sorted(p for p in base.iterdir() if p.is_dir()):
            documents = []
            for path in sorted(author_dir.glob("*.txt")):
                if path.name.startswith("_"):
                    continue
                work = re.sub(work_suffix, "", path.stem)
                documents.extend(_document_entries(
                    path, root, work, genre_of.get(str(path.relative_to(root)))))
            if len(documents) >= 3:
                personas.append(_persona(
                    f"{source}:{author_dir.name}", source, author_dir.name, documents))

    # The mixed committed validation corpus has author-labelled filenames
    # rather than author directories; each file is a distinct paper, so each
    # file is its own work. Keep AI documents for the AI scenario, not as
    # synthetic honest personas.
    mixed: dict[str, list[Path]] = {}
    for path in sorted((root / "validation" / "corpus").glob("*.txt")):
        author = re.sub(r"_\d+$", "", path.stem)
        if author.startswith("ai"):
            continue
        mixed.setdefault(author, []).append(path)
    for author, paths in sorted(mixed.items()):
        documents = []
        for path in paths:
            genre = genre_of.get(str(path.relative_to(root))) or "seminary-analogue"
            documents.extend(_document_entries(path, root, path.stem, genre))
        if len(documents) >= 3:
            personas.append(_persona(f"mixed:{author}", "validation_corpus", author, documents))

    # Plato (Jowett translation) is the one committed longitudinal author:
    # dialogue directories are works, ordered early -> late by the chronology
    # module rather than by size.
    plato_base = root / "validation" / "plato" / "corpus" / "jowett"
    if plato_base.exists():
        try:
            from validation.plato.chronology import ranked
            order = [d.slug for d in ranked()]
        except Exception:
            order = None
        documents = []
        for dialogue_dir in sorted(p for p in plato_base.iterdir() if p.is_dir()):
            for path in sorted(dialogue_dir.glob("*.txt")):
                documents.extend(_document_entries(path, root, dialogue_dir.name, None))
        if len(documents) >= 3:
            personas.append(_persona("plato:jowett", "plato", "plato", documents,
                                     work_order=order, longitudinal=order is not None))

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


def _mechanical_paraphrase(text: str) -> str:
    """Deterministic mechanical-paraphrase PROXY (labelled as such everywhere).

    Reverses sentence order and flattens semicolons/dashes: discourse-level
    reshuffling that keeps the author's own lexicon and within-sentence
    style. This is NOT an LLM-paraphrase claim — same honesty rule as G2b.
    """
    sentences = re.split(r"(?<=[.!?])\s+", text)
    reshuffled = " ".join(reversed(sentences))
    return reshuffled.replace("; ", ". ").replace(" — ", ", ").replace("—", ", ")


class CorpusTextResolver:
    """Resolve script events to committed text without copying corpus payloads.

    Events name an intent — a role ("home" = the persona's main body of work,
    "away" = a held-out work by the same author) and an ordinal — and the
    resolver maps it deterministically onto the manifest. Home and away pools
    are disjoint whenever the persona has at least two works, which is what
    makes TRANSFER a controlled contrast rather than an accident of ordering.
    """

    def __init__(self, manifest: dict, root: Path = ROOT):
        self.root = root
        self.personas = {p["id"]: p for p in manifest["personas"]}
        self._chunk_cache: dict[str, list[str]] = {}
        self.ai = []
        for path in sorted((root / "validation" / "corpus").glob("ai_*.txt")):
            self.ai.extend(chunk_text(path.read_text(errors="ignore")))

    def _pools(self, persona: dict) -> tuple[list[int], list[int]]:
        groups = persona["groups"]
        if len(groups) >= 2:
            away = groups[-1]["doc_indices"]
            home = [i for g in groups[:-1] for i in g["doc_indices"]]
            return home, away
        only = groups[0]["doc_indices"]
        return only, only

    def _chunks(self, path: str) -> list[str]:
        if path not in self._chunk_cache:
            self._chunk_cache[path] = chunk_text(
                (self.root / path).read_text(errors="ignore"))
        return self._chunk_cache[path]

    def __call__(self, event: dict) -> str:
        number = event.get("doc_number", 0)
        if event.get("source_kind") == "ai" and self.ai:
            return self.ai[number % len(self.ai)]
        persona = self.personas[event["source_persona"]]
        home, away = self._pools(persona)
        pool = away if event.get("doc_role") == "away" else home
        document = persona["documents"][pool[number % len(pool)]]
        text = self._chunks(document["path"])[document["chunk_index"]]
        if event.get("source_kind") == "mechanical-paraphrase":
            text = _mechanical_paraphrase(text)
        return text


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
    multi = sum(1 for p in manifest["personas"] if p["n_groups"] >= 2)
    print(f"personas={len(counts)} median_docs={median} multi_work={multi} "
          f"manifest={manifest['manifest_sha256']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
