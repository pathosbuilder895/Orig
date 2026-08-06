"""Smoke-run the Ross-style Dirichlet-multinomial drift model against real,
dated single-author prose.

Distinct from `validation.longitudinal.run`, which exercises the *production*
ridge-trend model (`original/quantum/longitudinal.py`, tiers 1/4/5/6/11 of the
109-feature vector). This script exercises the OTHER drift primitive —
`validation/longitudinal/dirichlet_multinomial.py`, the paper-faithful
Dirichlet-multinomial + BIC model this repository actually cites as "Ross
(2020)" — which had never been run against anything but 4-category toy
matrices before this. Its only prior bug (an unbounded scipy `maxfun` that
silently forced every real-vocabulary fit to report "constant" regardless of
evidence) would not have been visible from those toy tests, or from this
runner's sibling.

Run from the repository root:
    .venv/bin/python -m validation.longitudinal.dm_smoke_run
"""

from __future__ import annotations

import json
from pathlib import Path

from validation.longitudinal.dirichlet_multinomial import (
    compare_constant_and_drift,
    count_function_words,
    permutation_false_selection_rate,
)

ROOT = Path(__file__).resolve().parents[2]
MANIFEST = Path(__file__).with_name("smoke_manifest.json")
CORPUS = Path(__file__).with_name("smoke_corpus")
OUTPUT = Path(__file__).with_name("dm_smoke_report.json")


def main() -> None:
    manifest = json.loads(MANIFEST.read_text())
    entries = sorted(manifest["entries"], key=lambda e: e["submitted_at"])

    texts = [(CORPUS / e["filename"]).read_text(encoding="utf-8") for e in entries]
    counts = [count_function_words(t) for t in texts]
    import numpy as np

    matrix = np.stack(counts).astype(float)
    years = [int(e["submitted_at"][:4]) for e in entries]

    comparison = compare_constant_and_drift(matrix, times=np.array(years, dtype=float))
    false_selection_rate = permutation_false_selection_rate(matrix, repeats=200)

    report = {
        "model": "validation.longitudinal.dirichlet_multinomial (Ross 2020 style)",
        "corpus": "8 Mark Twain novels, real publication years 1869-1896 (see build_smoke_corpus.py)",
        "vocabulary_size": matrix.shape[1],
        "n_documents": matrix.shape[0],
        "comparison": comparison.to_dict(),
        "chronology_permutation_false_selection_rate": false_selection_rate,
        "note": (
            "false_selection_rate is Ross's own diagnostic: how often shuffling "
            "the document order still selects gradual_drift. A low rate here "
            "means the model isn't just selecting drift because it always does "
            "at this vocabulary width -- it needs real chronological structure."
        ),
    }
    OUTPUT.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    print(f"\nwrote {OUTPUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
