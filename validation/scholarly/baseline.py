"""One descriptive baseline on the ``development`` partition. Not a gate.

    python -m validation.scholarly.baseline --collection humanities

Runs the existing flags-off score (``ScoringConfig()`` defaults, research flags
unset) over trials from ``loader.load_trials(..., "development")`` and reports,
per length configuration, the honest flag rate, the other-writer catch rate and
the AUC of ``deviation_score``, each with an author-level bootstrap interval.

This is a description of how the existing scorer behaves on academic prose:
  * nothing is tuned on it, nothing is registered in validation/calibration_gate.py;
  * only the ``development`` partition is read (``locked_test`` is unreachable here);
  * academics are not students, and formal academic prose is the register where
    published stylometric methods are weakest.
"flagged" = the recommended action is schedule_conversation or escalate (the
product's flag floor); the AUC uses the raw deviation_score.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from pathlib import Path

import numpy as np

_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_ROOT))

from .loader import load_trials  # noqa: E402

HERE = Path(__file__).resolve().parent
FLAG_ACTIONS = ("schedule_conversation", "escalate")
# (name, past paper words, new paper words)
CONFIGS = [("matched_300_300", 300, 300), ("matched_1200_1200", 1200, 1200), ("long_past_1200_short_new_300", 1200, 300)]
_CACHE: dict = {}


def _auc(h: np.ndarray, i: np.ndarray) -> float:
    return float(((i[:, None] > h[None, :]).sum() + 0.5 * (i[:, None] == h[None, :]).sum()) / (i.size * h.size))


def metrics(per_author: list[dict]) -> dict:
    h = np.array([s for a in per_author for s in a["honest"]])
    i = np.array([s for a in per_author for s in a["probe"]])
    hf = np.array([f for a in per_author for f in a["honest_flag"]], dtype=float)
    pf = np.array([f for a in per_author for f in a["probe_flag"]], dtype=float)
    return {"honest_flag_rate": float(hf.mean()), "other_writer_catch_rate": float(pf.mean()),
            "auc": _auc(h, i), "n_honest": int(h.size), "n_probe": int(i.size)}


def bootstrap(per_author: list[dict], n_boot: int = 1000, seed: int = 0) -> dict:
    """Resample AUTHORS (the independent unit), carrying each author's own documents."""
    rng = np.random.default_rng(seed)
    n = len(per_author)
    out = {"honest_flag_rate": [], "other_writer_catch_rate": [], "auc": []}
    for _ in range(n_boot):
        m = metrics([per_author[j] for j in rng.integers(0, n, n)])
        for k in out:
            out[k].append(m[k])
    return {k: [round(float(np.quantile(v, 0.025)), 4), round(float(np.quantile(v, 0.975)), 4)] for k, v in out.items()}


def _score_all(trial, n_tokens: int) -> dict:
    from original.features.pipeline import extract_features, feature_vector
    from original.quantum.scoring import ScoringConfig
    from original.quantum.scoring import score as quantum_score
    from original.quantum.state import BaselineSample, StudentState

    def feats(t: str):
        k = hashlib.sha256(t.encode()).hexdigest()
        if k not in _CACHE:
            _CACHE[k] = (feature_vector(t), extract_features(t))
        return _CACHE[k]

    state = StudentState(student_id=trial.student_id)
    for t in trial.baseline:
        state.add_sample(BaselineSample(text=t, vector=feats(t)[0], provenance="verified",
                                        auth_weight=1.0, genre="essay"))

    def one(text: str, sid: str):
        vec, fd = feats(text)
        r = quantum_score(state=state, submission_vector=vec, feature_dict=fd, submission_id=sid,
                          n_tokens=n_tokens, scoring_config=ScoringConfig())
        return float(r.authorship.deviation_score), r.recommendation.action in FLAG_ACTIONS

    h = [one(t, f"h:{trial.student_id}:{j}") for j, t in enumerate(trial.honest)]
    p = [one(t, f"p:{trial.student_id}:{j}") for j, t in enumerate(trial.probes)]
    return {"author": trial.student_id, "honest": [x for x, _ in h], "honest_flag": [f for _, f in h],
            "probe": [x for x, _ in p], "probe_flag": [f for _, f in p]}


def run(collection: str, max_authors: int, n_boot: int, seed: int) -> dict:
    for flag in ("CONTEXT_MANIFEST_ENABLED", "ADAPTIVE_WEIGHTS_ENABLED"):
        os.environ[flag] = "0"
    result = {"collection": collection, "partition": "development", "scorer": "ScoringConfig() defaults, research flags off",
              "date": time.strftime("%Y-%m-%d"), "n_past": 4, "n_new": 2, "n_probes": 5, "configs": {}}
    for name, past_w, new_w in CONFIGS:
        ts = load_trials(collection, "development", n_past=4, n_new=2, past_words=past_w, new_words=new_w,
                         n_probes=5, seed=seed, max_authors=max_authors)
        t0 = time.time()
        per_author = [_score_all(t, new_w) for t in ts.trials]
        m = metrics(per_author)
        m.update({"n_authors": len(per_author), "authors_skipped_for_length": len(ts.skipped),
                  "ci95_author_bootstrap": bootstrap(per_author, n_boot, seed), "seconds": round(time.time() - t0)})
        result["configs"][name] = m
        print(name, json.dumps(m), flush=True)
    return result


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--collection", choices=("humanities", "science"), required=True)
    ap.add_argument("--max-authors", type=int, default=None)
    ap.add_argument("--n-boot", type=int, default=1000)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--out", type=Path, default=None)
    a = ap.parse_args(argv)
    res = run(a.collection, a.max_authors, a.n_boot, a.seed)
    out = a.out or HERE / f"baseline_{a.collection}_{time.strftime('%Y-%m-%d')}.json"
    out.write_text(json.dumps(res, indent=1) + "\n", encoding="utf-8")
    print("wrote", out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
