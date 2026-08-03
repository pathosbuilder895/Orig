"""
validation/federalist/build_manifest.py — build a public_authors-shaped
manifest + corpus tree for the Federalist Papers.

Why this corpus. The 2026-07-31 attribution benchmark ran on 22 held-out
essays and could not decide its own 0.7 bar: the 95% Wilson interval on any
plausible result straddled it (see validation/benchmarks/2026-07-31/
public_authors/INVALID.md, which also records that that corpus turned out to
be contaminated). The Federalist Papers fix three separate problems at once:

  1. Each paper is a genuine standalone document — no chunker, so none of
     the table-of-contents / boilerplate / back-matter failure modes that
     have bitten this project twice can occur by construction.
  2. Authorship is externally established rather than asserted by us:
     Hamilton, Madison and Jay signed 70 papers, and Mosteller & Wallace
     (1963) attributed the 12 long-disputed papers to Madison — a result the
     scholarly consensus has held for sixty years.
  3. Those 12 disputed papers are a real external validity check. An engine
     that scores well on the 70 known papers and then attributes the
     disputed 12 to Madison has reproduced a landmark result; one that
     scatters them has not, whatever its headline accuracy says.

Source files are the already-committed validation/corpus/fed_*.txt.

Excluded deliberately:
  * fed_joint  — 3 papers of contested joint authorship. A single-label
                 attribution task cannot express "both", so scoring them
                 would manufacture errors that mean nothing.
  * fed_jay    — 5 papers only, below ATTRIBUTION_MIN_BASELINE_DOCS=3 once
                 a held-out split is taken. Kept OUT of the candidate pool
                 rather than silently half-included; noted in the report.
  * any paper carrying Project Gutenberg boilerplate (license blocks,
    transcriber notes). Detected, not assumed — see _BOILERPLATE.

Run:
    python -m validation.federalist.build_manifest
"""

from __future__ import annotations

import json
import re
import shutil
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_ROOT = _HERE.parent.parent
sys.path.insert(0, str(_ROOT))

_SRC = _ROOT / "validation" / "corpus"
_CORPUS = _HERE / "corpus"
_MANIFEST = _HERE / "manifest.json"

# Authors with enough papers to be candidates. jay/joint deliberately absent.
_AUTHORS = {
    "hamilton": {"name": "Alexander Hamilton", "native_english": True},
    "madison": {"name": "James Madison", "native_english": True},
}

_BASELINE_PER_AUTHOR = 3  # matches ATTRIBUTION_MIN_BASELINE_DOCS

_BOILERPLATE = re.compile(
    r"produced by|proofreading team|project gutenberg|gutenberg-tm|transcriber|"
    r"distributed proofread|images generously|\*\*\*\s*(start|end) of",
    re.I,
)


def _is_clean(text: str) -> bool:
    """Reject Gutenberg apparatus. Two papers carry a trailing licence block."""
    return not (_BOILERPLATE.search(text[:400]) or len(_BOILERPLATE.findall(text)) >= 3)


def build() -> dict:
    if _CORPUS.exists():
        shutil.rmtree(_CORPUS)
    entries: list[dict] = []
    skipped: list[str] = []

    for author_id in _AUTHORS:
        srcs = sorted(_SRC.glob(f"fed_{author_id}_*.txt"))
        kept = []
        for s in srcs:
            text = s.read_text(errors="ignore")
            if not _is_clean(text):
                skipped.append(s.name)
                continue
            kept.append((s, text))
        if len(kept) < _BASELINE_PER_AUTHOR + 1:
            raise SystemExit(f"{author_id}: only {len(kept)} clean papers — too few to split")

        dest_dir = _CORPUS / author_id
        dest_dir.mkdir(parents=True, exist_ok=True)
        for i, (s, text) in enumerate(kept):
            rel = f"{author_id}/{s.stem}.txt"
            (_CORPUS / rel).write_text(text)
            entries.append(
                {
                    "filename": rel,
                    "author_id": author_id,
                    "label": "authentic",
                    "prompt": s.stem.replace("fed_", "Federalist "),
                    "word_count": len(text.split()),
                    # First N papers are the baseline; the rest are scored.
                    "is_baseline": i < _BASELINE_PER_AUTHOR,
                    "ai_provider": "none",
                    "theological_tradition": None,
                    "native_english": True,
                    "notes": f"Federalist Papers, source {s.name}",
                }
            )

    manifest = {
        "version": "1.0",
        "created_at": "2026-08-02T00:00:00Z",
        "description": (
            "Federalist Papers attribution corpus. Each paper is a standalone "
            "document (no chunking). Hamilton and Madison only: jay has 5 papers "
            "and joint-authored papers cannot be expressed as a single label. "
            "Gutenberg-boilerplate papers excluded. The 12 disputed papers are "
            "NOT in this manifest -- they are a separate held-out challenge, see "
            "validation/federalist/run_disputed.py."
        ),
        "authors": _AUTHORS,
        "entries": entries,
    }
    _MANIFEST.write_text(json.dumps(manifest, indent=2) + "\n")
    return {"entries": len(entries), "skipped": skipped, "manifest": str(_MANIFEST)}


if __name__ == "__main__":
    r = build()
    print(f"wrote {r['manifest']}: {r['entries']} entries")
    if r["skipped"]:
        print(f"  excluded for Gutenberg boilerplate: {r['skipped']}")
