"""
scripts/add_seminary_essays.py — ingest authentic theology essays into the
validation corpus's `seminary_authentic` pool.

Mirrors scripts/add_ai_essays.py's ingestion CLI (validate through the
manifest schema, assign the next id, copy into validation/corpus/, append to
validation/manifest.json), but for the OTHER side of the AI-likelihood
enablement gate: authentic human writing in the pilot's actual theological
register, as opposed to `add_ai_essays.py`'s AI-generated side.

`scripts/train_ai_detector.py eval-seminary` buckets a manifest entry into
the `seminary_authentic` group (the false-positive rate that gates
`AI_LIKELIHOOD_ENABLED`) purely by:

    label == "authentic" and author_id.startswith("seminary")

`author_id` is therefore an eval-group tag, not a claim that the writer was
literally a seminary student — real historical theologians (Spurgeon,
Murray, ...) belong in this pool exactly as much as the synthetic
`seminary_01..05` essays already there, because what the gate measures is
whether genuine human writing in this doctrinal/devotional register reads
as AI to the detector.

Usage — one call per author identity. Reuse --author-id across multiple
calls to pool several works from the same person under one identity (their
one true author_id continues numbering rather than colliding):

    .venv/bin/python scripts/add_seminary_essays.py /path/to/chunks \\
        --author-name "Charles Haddon Spurgeon" \\
        --author-id seminary_10 \\
        --title "Around the Wicket Gate" \\
        --tradition "Reformed Baptist" \\
        --native-english \\
        --source-note "Project Gutenberg #60669 (https://www.gutenberg.org/ebooks/60669)"
    .venv/bin/python scripts/train_ai_detector.py eval-seminary   # re-check the gate

Each source .txt is assumed to already be an essay-sized, verified excerpt
(see scripts/fetch_seminary_theology_corpus.py, which produces exactly that
via the same fetch/verify/chunk machinery as validation/public_authors/
build_corpus.py). This script does no fetching or chunking of its own — it
only validates and records.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

from validation.corpus_policy import VERIFICATION_MIN_WORDS  # noqa: E402
from validation.manifest_schema import (  # noqa: E402
    AuthorshipLabel,
    CorpusEntry,
    Provenance,
)

DEFAULT_MANIFEST = _ROOT / "validation" / "manifest.json"
DEFAULT_CORPUS = _ROOT / "validation" / "corpus"

_SEMINARY_AUTHOR_RE = re.compile(r"^seminary_(\d+)$")


def _next_seminary_author_id(manifest_entries: list) -> str:
    """Continue the seminary_NN identity numbering from whatever exists."""
    numbers = [0]
    for e in manifest_entries:
        m = _SEMINARY_AUTHOR_RE.match(e["author_id"])
        if m:
            numbers.append(int(m.group(1)))
    return f"seminary_{max(numbers) + 1:02d}"


def _next_seq_for_author(corpus_dir: Path, manifest_entries: list, author_id: str) -> int:
    """Continue this author's seminary_NN_### numbering from whatever exists.

    Scanning both the manifest and the corpus directory (like
    add_ai_essays.py's `_next_ai_number`) means a half-written previous run
    can't cause a collision.
    """
    pattern = re.compile(rf"^{re.escape(author_id)}_(\d+)\.txt$")
    numbers = [0]
    for name in [e["filename"] for e in manifest_entries] + [
        p.name for p in corpus_dir.glob(f"{author_id}_*.txt")
    ]:
        m = pattern.match(name)
        if m:
            numbers.append(int(m.group(1)))
    return max(numbers) + 1


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument(
        "essay_dir", type=Path, help="Directory of .txt essay/excerpt files to ingest (sorted by name)."
    )
    ap.add_argument("--author-name", required=True, help="The real author's name (recorded in notes).")
    ap.add_argument(
        "--author-id",
        default=None,
        help="Manifest author_id, e.g. seminary_10. Omit to auto-assign the next seminary_NN "
        "identity; pass an existing one to pool more works under the same person.",
    )
    ap.add_argument(
        "--title", required=True, help="Source work title (used to build each entry's `prompt`)."
    )
    ap.add_argument(
        "--tradition",
        default=None,
        help="theological_tradition field, e.g. 'Reformed Baptist'. Omit to leave unset.",
    )
    ap.add_argument(
        "--native-english",
        action="store_true",
        default=None,
        help="Set native_english=true on every entry from this run.",
    )
    ap.add_argument(
        "--source-note",
        required=True,
        help="Provenance note (e.g. Gutenberg id + URL) recorded on every entry — this is what "
        "makes the corpus's authenticity claim independently checkable.",
    )
    ap.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    ap.add_argument("--corpus-dir", type=Path, default=DEFAULT_CORPUS)
    ap.add_argument("--dry-run", action="store_true", help="Validate and report, write nothing.")
    args = ap.parse_args(argv)

    if not args.essay_dir.is_dir():
        print(f"[add-seminary-essays] not a directory: {args.essay_dir}", file=sys.stderr)
        return 1
    sources = sorted(args.essay_dir.glob("*.txt"))
    if not sources:
        print(f"[add-seminary-essays] no .txt files in {args.essay_dir}", file=sys.stderr)
        return 1

    manifest = json.loads(args.manifest.read_text())
    entries = manifest["entries"]
    existing_names = {e["filename"] for e in entries}

    author_id = args.author_id or _next_seminary_author_id(entries)
    if not _SEMINARY_AUTHOR_RE.match(author_id):
        print(
            f"[add-seminary-essays] FAIL: --author-id {author_id!r} must match "
            f"seminary_NN — that prefix is what eval-seminary groups on",
            file=sys.stderr,
        )
        return 1
    next_n = _next_seq_for_author(args.corpus_dir, entries, author_id)
    notes = (
        f"Real historical author ({args.author_name}), authentic pre-LLM-era prose. "
        f"Source: {args.source_note}. Ingested via add_seminary_essays.py "
        f"({datetime.now(timezone.utc).date().isoformat()})."
    )

    new_entries = []
    for i, src in enumerate(sources, start=next_n):
        text = src.read_text(encoding="utf-8", errors="replace").strip()
        word_count = len(text.split())
        if word_count == 0:
            print(f"[add-seminary-essays] FAIL: {src.name} is empty", file=sys.stderr)
            return 1
        if word_count < VERIFICATION_MIN_WORDS:
            print(
                f"[add-seminary-essays] WARN: {src.name} is only {word_count} words "
                f"(< verification floor {VERIFICATION_MIN_WORDS}) — short texts weaken the eval",
                file=sys.stderr,
            )

        filename = f"{author_id}_{i:03d}.txt"
        if filename in existing_names or (args.corpus_dir / filename).exists():
            print(
                f"[add-seminary-essays] FAIL: {filename} already exists — refusing to overwrite",
                file=sys.stderr,
            )
            return 1

        entry = CorpusEntry(
            filename=filename,
            author_id=author_id,
            label=AuthorshipLabel.AUTHENTIC,
            prompt=f"{args.title} (excerpt {i - next_n + 1} of {len(sources)})",
            word_count=word_count,
            is_baseline=False,
            theological_tradition=args.tradition,
            native_english=args.native_english,
            provenance=Provenance.REAL_HISTORICAL,
            notes=notes,
        )
        new_entries.append((src, filename, entry))
        print(
            f"[add-seminary-essays] {src.name} → {filename} "
            f"({word_count} words, author_id={author_id})"
        )

    if args.dry_run:
        print(
            f"[add-seminary-essays] dry-run: {len(new_entries)} essay(s) validated, "
            f"nothing written."
        )
        return 0

    for src, filename, entry in new_entries:
        (args.corpus_dir / filename).write_text(
            src.read_text(encoding="utf-8", errors="replace").strip() + "\n", encoding="utf-8"
        )
        entries.append(entry.model_dump(mode="json"))
    manifest["updated_at"] = datetime.now(timezone.utc).isoformat()
    args.manifest.write_text(json.dumps(manifest, indent=2) + "\n")

    print(
        f"[add-seminary-essays] added {len(new_entries)} essay(s) to "
        f"{args.manifest.name} + {args.corpus_dir}/ under author_id={author_id}"
    )
    print("next: .venv/bin/python scripts/train_ai_detector.py eval-seminary")
    return 0


if __name__ == "__main__":
    sys.exit(main())
