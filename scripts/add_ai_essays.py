"""
scripts/add_ai_essays.py — ingest AI-generated essays into the validation corpus.

The in-domain enablement evidence is currently single-generator (all 20 AI
theology essays are Claude). This CLI is how essays from OTHER generators
enter the corpus: produce theology essays with whatever tool you have access
to (ChatGPT / Gemini web UIs are fine — that's what real students use), save
each as a .txt file in one directory, then:

    .venv/bin/python scripts/add_ai_essays.py /path/to/essays --provider chatgpt
    .venv/bin/python scripts/train_ai_detector.py eval-seminary   # per-provider gate report

For a controlled comparison, reuse the 20 existing essay topics (listed in
validation/manifest.json under label=ai_generated) via --prompt-map:

    {"my_essay_1.txt": "The Doctrine of Justification in Christian Theology", ...}

Each file is validated through the manifest schema (CorpusEntry), assigned
the next ai_NNN.txt number, copied into validation/corpus/, and appended to
validation/manifest.json. The seminary feature cache self-invalidates (it is
keyed on the manifest sha256), so the next eval-seminary re-extracts.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

from validation.manifest_schema import AIProvider, AuthorshipLabel, CorpusEntry  # noqa: E402

DEFAULT_MANIFEST = _ROOT / "validation" / "manifest.json"
DEFAULT_CORPUS = _ROOT / "validation" / "corpus"
MIN_WORDS_WARN = 150


def _next_ai_number(corpus_dir: Path, manifest_entries: list) -> int:
    """Continue the ai_NNN.txt numbering from whatever exists already."""
    pattern = re.compile(r"^ai_(\d+)\.txt$")
    numbers = [0]
    for name in [e["filename"] for e in manifest_entries] + \
                [p.name for p in corpus_dir.glob("ai_*.txt")]:
        m = pattern.match(name)
        if m:
            numbers.append(int(m.group(1)))
    return max(numbers) + 1


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("essay_dir", type=Path,
                    help="Directory of .txt essays to ingest (sorted by name).")
    ap.add_argument("--provider", required=True,
                    choices=[p.value for p in AIProvider if p != AIProvider.NONE],
                    help="Which generator produced these essays.")
    ap.add_argument("--author-id", default="ai_author",
                    help="Manifest author_id (default: ai_author, pooled with "
                         "the existing AI essays).")
    ap.add_argument("--prompt-map", type=Path, default=None,
                    help="JSON file mapping source filename → essay prompt/topic.")
    ap.add_argument("--default-prompt", default="AI-generated theology essay",
                    help="Prompt used for files not in --prompt-map.")
    ap.add_argument("--notes", default=None,
                    help="Notes string (default records provider + ingest date).")
    ap.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    ap.add_argument("--corpus-dir", type=Path, default=DEFAULT_CORPUS)
    ap.add_argument("--dry-run", action="store_true",
                    help="Validate and report, write nothing.")
    args = ap.parse_args(argv)

    if not args.essay_dir.is_dir():
        print(f"[add-ai-essays] not a directory: {args.essay_dir}", file=sys.stderr)
        return 1
    sources = sorted(args.essay_dir.glob("*.txt"))
    if not sources:
        print(f"[add-ai-essays] no .txt files in {args.essay_dir}", file=sys.stderr)
        return 1

    prompt_map = {}
    if args.prompt_map:
        prompt_map = json.loads(args.prompt_map.read_text())

    manifest = json.loads(args.manifest.read_text())
    entries = manifest["entries"]
    existing_names = {e["filename"] for e in entries}
    next_n = _next_ai_number(args.corpus_dir, entries)
    notes = args.notes or (
        f"AI-generated essay ingested via add_ai_essays.py "
        f"(provider={args.provider}, {datetime.now(timezone.utc).date().isoformat()})"
    )

    new_entries = []
    for src in sources:
        text = src.read_text(encoding="utf-8", errors="replace").strip()
        word_count = len(text.split())
        if word_count == 0:
            print(f"[add-ai-essays] FAIL: {src.name} is empty", file=sys.stderr)
            return 1
        if word_count < MIN_WORDS_WARN:
            print(f"[add-ai-essays] WARN: {src.name} is only {word_count} words "
                  f"(< {MIN_WORDS_WARN}) — short texts weaken the eval", file=sys.stderr)

        filename = f"ai_{next_n:03d}.txt"
        next_n += 1
        if filename in existing_names or (args.corpus_dir / filename).exists():
            print(f"[add-ai-essays] FAIL: {filename} already exists — refusing "
                  f"to overwrite", file=sys.stderr)
            return 1

        entry = CorpusEntry(
            filename=filename,
            author_id=args.author_id,
            label=AuthorshipLabel.AI_GENERATED,
            prompt=prompt_map.get(src.name, args.default_prompt),
            word_count=word_count,
            is_baseline=False,
            ai_provider=AIProvider(args.provider),
            notes=notes,
        )
        new_entries.append((src, filename, entry))
        print(f"[add-ai-essays] {src.name} → {filename} "
              f"({word_count} words, provider={args.provider})")

    if args.dry_run:
        print(f"[add-ai-essays] dry-run: {len(new_entries)} essay(s) validated, "
              f"nothing written.")
        return 0

    for src, filename, entry in new_entries:
        shutil.copyfile(src, args.corpus_dir / filename)
        entries.append(entry.model_dump(mode="json"))
    manifest["updated_at"] = datetime.now(timezone.utc).isoformat()
    args.manifest.write_text(json.dumps(manifest, indent=2) + "\n")

    print(f"[add-ai-essays] added {len(new_entries)} essay(s) to "
          f"{args.manifest.name} + {args.corpus_dir}/")
    print("next: .venv/bin/python scripts/train_ai_detector.py eval-seminary")
    return 0


if __name__ == "__main__":
    sys.exit(main())
