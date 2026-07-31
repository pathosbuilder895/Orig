"""
validation/plato/gate.py — the translator-penetration gate.

Plato wrote in Greek. Original's feature pipeline is hard-locked to English:
roughly 60 of its 103 features are English lexical/surface measures, 14 need
the ``en_core_web_sm`` model, and both prosodic tiers use an English
vowel-cluster stress heuristic. So this study necessarily measures Plato *as
rendered by a translator*, and the obvious objection is that it measures only
the translator.

This gate answers that objection with a variance decomposition. Three
dialogues — Apology, Crito, Phaedo — exist in the corpus twice, translated by
Benjamin Jowett and by Henry Cary. Holding the source text constant while
varying the translator, and vice versa, separates the two sources of variance:

    within              chunks of the same dialogue, same translator (noise floor)
    between_translator  same dialogue, different translator
    between_dialogue    same translator, different dialogue

PASS when ``between_dialogue >= between_translator``: the identity of the
source text moves a chunk at least as far as the identity of the translator,
so there is real authorial signal surviving translation.

FAIL means Original is largely measuring the translator, and no chronology
result computed on this corpus would be interpretable. In that case the
correct output of this whole study is the failure itself.

Deliberately conservative: Apology, Crito and Phaedo sit close together in the
chronology, so this compares near-neighbours. If source signal beats
translator signal here, it will across the full 40-year span.

    python -m validation.plato.gate
"""

from __future__ import annotations

import argparse
import itertools
import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Dict, List

import numpy as np

from validation.plato import features as F
from validation.plato.chronology import CARY_DIALOGUES

_HERE = Path(__file__).resolve().parent


@dataclass
class GateReport:
    n_chunks: int
    n_active_features: int
    dialogues: List[str]
    within: float
    between_translator: float
    between_dialogue: float
    ratio_dialogue_over_translator: float
    passed: bool
    per_dialogue_translator_gap: Dict[str, float]
    interpretation: str


def _mean_pairwise(A: np.ndarray, B: np.ndarray | None = None) -> float:
    """Mean Euclidean distance within A, or between A and B."""
    if B is None:
        if len(A) < 2:
            return float("nan")
        d = [np.linalg.norm(A[i] - A[j]) for i, j in itertools.combinations(range(len(A)), 2)]
    else:
        if len(A) == 0 or len(B) == 0:
            return float("nan")
        d = [np.linalg.norm(a - b) for a in A for b in B]
    return float(np.mean(d))


def run(force: bool = False, normalised: bool = False) -> GateReport:
    manifest = F.load_manifest()
    X, entries = F.build_matrix(manifest, force=force, normalised=normalised)

    # Restrict to the three doubly-translated dialogues.
    idx = [
        i
        for i, e in enumerate(entries)
        if e["slug"] in CARY_DIALOGUES and e["translator"] in ("jowett", "cary")
    ]
    sub_entries = [entries[i] for i in idx]
    Xs = X[idx]

    # Standardise on this subset only — the gate is a self-contained comparison.
    mask = F.informative_mask(Xs)
    Z = F.standardise(Xs, mask)

    groups: Dict[tuple, List[int]] = {}
    for row, e in enumerate(sub_entries):
        groups.setdefault((e["slug"], e["translator"]), []).append(row)

    within_vals, bt_vals, bd_vals = [], [], []
    per_dialogue_gap: Dict[str, float] = {}

    for (slug, tr), rows in groups.items():
        w = _mean_pairwise(Z[rows])
        if not np.isnan(w):
            within_vals.append(w)

    for slug in CARY_DIALOGUES:
        j = groups.get((slug, "jowett"), [])
        c = groups.get((slug, "cary"), [])
        if j and c:
            gap = _mean_pairwise(Z[j], Z[c])
            per_dialogue_gap[slug] = round(gap, 4)
            bt_vals.append(gap)

    for tr in ("jowett", "cary"):
        for a, b in itertools.combinations(CARY_DIALOGUES, 2):
            ra, rb = groups.get((a, tr), []), groups.get((b, tr), [])
            if ra and rb:
                bd_vals.append(_mean_pairwise(Z[ra], Z[rb]))

    within = float(np.mean(within_vals))
    between_translator = float(np.mean(bt_vals))
    between_dialogue = float(np.mean(bd_vals))
    ratio = between_dialogue / between_translator if between_translator else float("nan")
    passed = bool(between_dialogue >= between_translator)

    if passed:
        interpretation = (
            f"PASS. The source text moves a chunk {ratio:.2f}x as far as the translator "
            f"does, so authorial signal survives translation and the chronology analysis "
            f"is interpretable. Note this is measured across three chronologically "
            f"adjacent dialogues, which makes it a conservative test."
        )
    else:
        interpretation = (
            f"FAIL. The translator moves a chunk further than the source text does "
            f"(ratio {ratio:.2f} < 1.0). On this corpus Original is substantially "
            f"measuring the translator's English rather than Plato, and no chronology "
            f"result computed from it would be interpretable. This failure is the "
            f"finding; do not proceed to Arms A and B."
        )

    return GateReport(
        n_chunks=len(sub_entries),
        n_active_features=int(mask.sum()),
        dialogues=list(CARY_DIALOGUES),
        within=round(within, 4),
        between_translator=round(between_translator, 4),
        between_dialogue=round(between_dialogue, 4),
        ratio_dialogue_over_translator=round(ratio, 4),
        passed=passed,
        per_dialogue_translator_gap=per_dialogue_gap,
        interpretation=interpretation,
    )


def render(r: GateReport) -> str:
    lines = [
        "",
        "╭─ Translator-penetration gate ─────────────────────────────────────╮",
        f"│ chunks {r.n_chunks:<3}  active features {r.n_active_features:<3}  "
        f"dialogues: {', '.join(r.dialogues):<22}│",
        "├───────────────────────────────────────────────────────────────────┤",
        f"│ within  (same dialogue, same translator) …… {r.within:>8.4f}  noise  │",
        f"│ between_translator (same dialogue) ………………… {r.between_translator:>8.4f}         │",
        f"│ between_dialogue   (same translator) ……………… {r.between_dialogue:>8.4f}         │",
        "├───────────────────────────────────────────────────────────────────┤",
        f"│ ratio dialogue/translator ……………………………………… {r.ratio_dialogue_over_translator:>8.4f}         │",
        f"│ VERDICT ……………………………………………………………………………………… {'PASS' if r.passed else 'FAIL':>8}         │",
        "╰───────────────────────────────────────────────────────────────────╯",
        "",
        "per-dialogue Jowett↔Cary distance:",
    ]
    for slug, gap in r.per_dialogue_translator_gap.items():
        lines.append(f"  {slug:<10} {gap:>8.4f}")
    lines += ["", r.interpretation, ""]
    return "\n".join(lines)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--force", action="store_true", help="Recompute features, ignore the cache.")
    ap.add_argument("--out", type=Path, help="Write the report JSON here.")
    ap.add_argument(
        "--normalise",
        action="store_true",
        help="Unify edition/transcription conventions before extracting features.",
    )
    a = ap.parse_args(argv)

    r = run(force=a.force, normalised=a.normalise)
    print(render(r))
    if a.out:
        a.out.parent.mkdir(parents=True, exist_ok=True)
        a.out.write_text(json.dumps(asdict(r), indent=2))
        print(f"wrote {a.out}")
    return 0 if r.passed else 1


if __name__ == "__main__":
    sys.exit(main())
