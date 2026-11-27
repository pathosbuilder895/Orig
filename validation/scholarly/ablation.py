"""Which parts of the learned verifier carried the gain? Development only, a diagnosis.

    python -m validation.scholarly.ablation --collection humanities

Uses the frozen verifier design (``verifier.py``: boosted model pooled across the three
length configurations, 2-fold author-disjoint cross-fit with each probe's source author in
the same fold, probe authors removed from every comparison pool) and changes one thing at a
time:

* ``full``: the frozen design.
* ``minus_<ingredient>``: the full design with one ingredient removed.
* ``plus_<ingredient>``: today's flags-off ``deviation_score`` plus that ingredient alone.
* ``flags_off``: ``deviation_score`` alone, unchanged (no model).
* ``fixed_combination``: an unweighted average of the channels' impostor-relative z values
  (no trained model at all).

Ingredients: 1 length-matched pieces, 2 character channel, 3 topic-masked character channel,
4 function-word channel, 5 part-of-speech channel, 6 impostor comparison (relative to other
authors) versus own-baseline only, 7 nearest-piece similarity versus centroid only,
8 Original's feature z-scores (self and peer).

Calibration is not used and ``locked_test`` is unreachable. Nothing here changes the verifier
design, the product or any flag.
"""
from __future__ import annotations

import argparse
import json
import pickle
import sys
import time
from pathlib import Path

import numpy as np

_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_ROOT))

from . import verifier  # noqa: E402
from .adjust import CONFIGS  # noqa: E402

HERE = Path(__file__).resolve().parent
ROWS_DIR = HERE / "cache" / "verifier"
CHANNELS = ("char", "masked", "pos", "fw")

INGREDIENTS = {
    "1_length_matched": "length-matched baseline pieces",
    "2_char": "character n-gram channel",
    "3_masked": "topic-masked character channel",
    "4_function_words": "function-word channel",
    "5_pos": "part-of-speech channel",
    "6_impostor": "impostor comparison (relative to other authors)",
    "7_nearest_piece": "nearest-piece similarity",
    "8_original_z": "Original's feature z-scores (self and peer)",
}


def drop_mask(names: list[str], ingredient: str) -> np.ndarray:
    """True for the columns that REMAIN when ``ingredient`` is removed from the full design."""
    keep = np.ones(len(names), dtype=bool)
    for i, n in enumerate(names):
        if ingredient == "2_char" and n.startswith("char:"):
            keep[i] = False
        elif ingredient == "3_masked" and n.startswith("masked:"):
            keep[i] = False
        elif ingredient == "4_function_words" and n.startswith("fw:"):
            keep[i] = False
        elif ingredient == "5_pos" and n.startswith("pos:"):
            keep[i] = False
        elif ingredient == "6_impostor" and (n.endswith(":z") or n.endswith(":rank") or n in ("orig:rms_peer", "orig:contrast")
                                            or n.startswith("orig:zcontrast:")):
            keep[i] = False
        elif ingredient == "7_nearest_piece" and ":nearest:" in n:
            keep[i] = False
        elif ingredient == "8_original_z" and n.startswith("orig:"):
            keep[i] = False
    return keep


def alone_mask(names: list[str], ingredient: str) -> np.ndarray:
    """Columns that ARE the ingredient (added to the flags-off deviation_score)."""
    sel = np.zeros(len(names), dtype=bool)
    for i, n in enumerate(names):
        if ingredient == "2_char" and n.startswith("char:"):
            sel[i] = True
        elif ingredient == "3_masked" and n.startswith("masked:"):
            sel[i] = True
        elif ingredient == "4_function_words" and n.startswith("fw:"):
            sel[i] = True
        elif ingredient == "5_pos" and n.startswith("pos:"):
            sel[i] = True
        elif ingredient == "7_nearest_piece" and ":nearest:" in n:
            sel[i] = True
        elif ingredient == "8_original_z" and n.startswith("orig:"):
            sel[i] = True
    return sel


def fixed_combination(row_x: np.ndarray, names: list[str]) -> float:
    """No trained weights: the mean of every channel's impostor-relative z, sign-flipped so a
    higher value means 'less like the claimed author than other authors are'."""
    zs = [row_x[i] for i, n in enumerate(names) if n.split(":")[0] in CHANNELS and n.endswith(":z")]
    return float(-np.mean(zs)) if zs else 0.0


def _rows(collection: str, length_match: bool):
    """Development rows, cached on disk (git-ignored) so the ablation reruns cheaply."""
    path = ROWS_DIR / f"ablation_rows_{collection}_{'lm' if length_match else 'nolm'}.pkl"
    if path.exists():
        return pickle.loads(path.read_bytes())
    rows, _, _ = verifier.build_rows(collection, "development", length_match=length_match,
                                     original_scores=length_match)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(pickle.dumps(rows))
    return rows


def _xs(rows, cols=None, extra=()):
    out = []
    for r in rows:
        parts = [r["x"][cols] if cols is not None else np.zeros(0, dtype=np.float32)]
        parts.append(np.array([r["original"][e] for e in extra], dtype=np.float32))
        onehot = np.array([r["config"] == n for n, _, _ in CONFIGS], dtype=np.float32)
        out.append(np.concatenate(parts + [onehot]))
    return np.stack(out)


def crossfit_scores(rows, cols=None, extra=()) -> np.ndarray:
    """Out-of-fold scores of the frozen model type on the chosen columns."""
    keep = [i for i, r in enumerate(rows) if verifier._fold_ok(r, 0) or verifier._fold_ok(r, 1)]
    R = [rows[i] for i in keep]
    scores = np.full(len(R), np.nan)
    for fold in (0, 1):
        tr = [i for i, r in enumerate(R) if verifier._fold_ok(r, 1 - fold)]
        te = [i for i, r in enumerate(R) if verifier._fold_ok(r, fold)]
        m = verifier._model().fit(_xs([R[i] for i in tr], cols, extra), [R[i]["label"] for i in tr])
        scores[te] = m.predict_proba(_xs([R[i] for i in te], cols, extra))[:, 1]
    return R, scores


def report(R, scores, n_boot):
    out = {}
    for name, _, _ in CONFIGS:
        idx = [i for i, r in enumerate(R) if r["config"] == name]
        out[name] = verifier._report([R[i] for i in idx], scores[idx], n_boot)
    return out


def run(collection: str, n_boot: int) -> dict:
    verifier.MODEL = "boosted"
    names = verifier.column_names()
    rows = _rows(collection, True)
    rows_nolm = _rows(collection, False)
    assert len(names) == rows[0]["x"].shape[0], "column map out of step with build_rows"
    keep = [r for r in rows if verifier._fold_ok(r, 0) or verifier._fold_ok(r, 1)]
    out = {"collection": collection, "partition": "development", "date": time.strftime("%Y-%m-%d"),
           "design": "frozen verifier (boosted, pooled configurations, 2-fold author-disjoint cross-fit)",
           "ingredients": INGREDIENTS, "variants": {}}

    def add(label, R, scores):
        out["variants"][label] = report(R, scores, n_boot)
        r = out["variants"][label]["long_past_1200_short_new_300"]
        print(collection, label, {k: v["catch_at_5pct_honest"] for k, v in r.items()}, flush=True)

    add("full", *crossfit_scores(rows, np.arange(len(names))))
    add("flags_off", keep, np.array([r["original"]["dev_off"] for r in keep]))
    add("fixed_combination", keep, np.array([fixed_combination(r["x"], names) for r in keep]))
    add("minus_1_length_matched", *crossfit_scores(rows_nolm, np.arange(len(names))))
    for ing in INGREDIENTS:
        if ing == "1_length_matched":
            continue
        add(f"minus_{ing}", *crossfit_scores(rows, np.where(drop_mask(names, ing))[0]))
    add("plus_1_length_matched", *crossfit_scores(rows, None, ("dev_off", "dev_lm")))
    add("plus_6_impostor", *crossfit_scores(rows, None, ("dev_off", "llr_off")))
    for ing in INGREDIENTS:
        if ing in ("1_length_matched", "6_impostor"):
            continue
        add(f"plus_{ing}", *crossfit_scores(rows, np.where(alone_mask(names, ing))[0], ("dev_off",)))
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--collection", choices=("humanities", "science"), required=True)
    ap.add_argument("--n-boot", type=int, default=1000)
    a = ap.parse_args(argv)
    res = run(a.collection, a.n_boot)
    out = HERE / f"ablation_{a.collection}_development_{res['date']}.json"
    out.write_text(json.dumps(res, indent=1) + "\n", encoding="utf-8")
    print("wrote", out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
