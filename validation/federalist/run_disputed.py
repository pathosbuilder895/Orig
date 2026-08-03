"""
validation/federalist/run_disputed.py — the external validity check.

Every accuracy this project reports is measured against ground truth we
assembled ourselves, so a systematic error in how the corpus was built shows
up as a good score rather than a bad one. That failure has already happened
twice here (table-of-contents stubs standing in for essays; a French novel
standing in for Jonathan Edwards). The Federalist Papers offer the one thing
an internally-scored benchmark cannot: a published answer nobody involved in
this project produced.

The 12 disputed Federalist papers (49-58, 62, 63) were claimed by both
Hamilton and Madison. Mosteller & Wallace (1963), using function-word
frequencies and Bayesian analysis, attributed all 12 to Madison; that
conclusion has been the scholarly consensus for sixty years and has been
reproduced repeatedly with independent methods.

So this is a falsifiable prediction rather than another accuracy number:
an engine trained on the undisputed papers should attribute the disputed 12
to Madison. Scoring well on the undisputed set and then scattering these is
evidence the engine is fitting something other than authorship.

Reported per engine, with the count out of 12 and a binomial p-value against
a coin flip. Deliberately NOT folded into any gate: this is external
evidence about the engines, not a pass/fail criterion for a release.

Run:
    python -m validation.federalist.run_disputed
"""

from __future__ import annotations

import json
import re
import sys
from math import comb
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_ROOT = _HERE.parent.parent
sys.path.insert(0, str(_ROOT))

_SRC = _ROOT / "validation" / "corpus"

# Mosteller & Wallace (1963); consensus attribution: Madison, all twelve.
CONSENSUS_AUTHOR = "madison"
DISPUTED_NUMBERS = [49, 50, 51, 52, 53, 54, 55, 56, 57, 58, 62, 63]

_BOILERPLATE = re.compile(
    r"produced by|proofreading team|project gutenberg|gutenberg-tm|transcriber|"
    r"distributed proofread|images generously|\*\*\*\s*(start|end) of",
    re.I,
)


def load_disputed() -> dict[str, str]:
    """{paper_id: text} for the disputed papers actually present and clean."""
    out: dict[str, str] = {}
    for p in sorted(_SRC.glob("fed_disputed_*.txt")):
        text = p.read_text(errors="ignore")
        if _BOILERPLATE.search(text[:400]) or len(_BOILERPLATE.findall(text)) >= 3:
            continue
        out[p.stem] = text
    return out


def binomial_p_at_least(k: int, n: int, p: float = 0.5) -> float:
    """P(X >= k) under a fair coin — how surprising is k-of-n by chance?"""
    return sum(comb(n, i) * p**i * (1 - p) ** (n - i) for i in range(k, n + 1))


def main() -> int:
    import numpy as np

    from original.features.pipeline import feature_vector
    from validation.attribution.delta import cosine_delta_attribution, mfw_delta_attribution
    from validation.measurability import measurable_indices

    manifest = json.loads((_HERE / "manifest.json").read_text())
    corpus = _HERE / "corpus"

    # Train on EVERY undisputed paper, baseline flag included -- there is no
    # held-out split to protect here, since the disputed papers are the test.
    texts: dict[str, list[str]] = {}
    for e in manifest["entries"]:
        texts.setdefault(e["author_id"], []).append((corpus / e["filename"]).read_text())

    disputed = load_disputed()
    if not disputed:
        print("no clean disputed papers found", file=sys.stderr)
        return 2
    print(f"Training on {sum(len(v) for v in texts.values())} undisputed papers "
          f"({', '.join(f'{a}={len(v)}' for a, v in sorted(texts.items()))})")
    print(f"Testing {len(disputed)} disputed papers against the "
          f"Mosteller & Wallace consensus ({CONSENSUS_AUTHOR}).\n")

    idx = measurable_indices("public_authors")
    matrices = {a: np.vstack([feature_vector(t) for t in v]) for a, v in texts.items()}

    votes: dict[str, list[str]] = {"cosine_delta": [], "mfw_delta": []}
    for pid, text in sorted(disputed.items()):
        cos, _ = cosine_delta_attribution(matrices, np.asarray(feature_vector(text)), idx)
        mfw, _ = mfw_delta_attribution(texts, text)
        votes["cosine_delta"].append(cos)
        votes["mfw_delta"].append(mfw)
        print(f"  {pid:22} cosine_delta={cos:9}  mfw_delta={mfw}")

    print()
    results = {}
    n = len(disputed)
    for engine, vs in votes.items():
        k = sum(1 for v in vs if v == CONSENSUS_AUTHOR)
        p = binomial_p_at_least(k, n)
        results[engine] = {"agrees_with_consensus": k, "n": n, "binomial_p": p}
        print(f"  {engine:14} {k}/{n} agree with Mosteller & Wallace  (p={p:.4f} vs a coin flip)")

    out = _ROOT / "validation" / "benchmarks" / "2026-08-02" / "federalist" / "disputed.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(
        {"consensus_author": CONSENSUS_AUTHOR, "n_disputed": n,
         "per_engine": results,
         "per_paper": {p: {e: votes[e][i] for e in votes}
                       for i, p in enumerate(sorted(disputed))}}, indent=2) + "\n")
    print(f"\nwrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
