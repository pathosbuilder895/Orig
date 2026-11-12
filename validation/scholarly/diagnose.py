"""Step 1: why do honest papers get flagged in the 1200-past / 300-new setup? Validation only.

    python -m validation.scholarly.diagnose --collection humanities

Picks 8 development authors (the 4 with the highest honest false-flag rate under the
shipped scorer, and the 4 whose rate is closest to the collection median), then for every
honest paper of theirs that the shipped scorer flags, lists the top 5 features driving the
deviation (largest |tier weight x z|, active features only) and labels each one.

Labels come from four sensitivity indices measured on ALL development authors of the
collection, so a label is evidence, not a judgement:

* length   : |mean(x_300 - x_1200)| / sd(x_1200), where x_300 is the first 300 words of the
             same 1200-word cut (same author, same text, only the length differs).
* topic    : Spearman correlation between the feature's |z| on honest papers and the
             TF-IDF topic distance of that paper from its baseline.
* section  : |mean(x_start - x_middle)| / sd, a 300-word cut from the opening of a paper
             (abstract, introduction) against one from its middle (body).
* house    : within-author share of variance explained by publishing venue (URL host),
             minus the same share with venue labels shuffled (venue effect beyond chance).

Labelling, in order, for each driving feature of each flagged paper:

1. ``length`` if the feature's |z| at least halves when the SAME past papers are cut into
   300-word pieces (the baseline then matches the new paper's length). This is a direct
   test: only length changes. (The ``length`` index above, a mean shift, is reported for
   context; most of the length effect is spread, not mean.)
2. otherwise ``topic``, ``section`` or ``house``: the one whose index has the highest
   percentile rank across active features, if that rank is at least the 80th percentile;
3. otherwise ``genuine`` (the author really wrote differently on that feature). Nothing is
tuned here and no score is changed.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import random
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_ROOT))

from .adjust import FLAG_ACTIONS, FeatureStore, _state, length_matched, trial_sets  # noqa: E402
from .intended_use import SEEDS, reset_research_flags  # noqa: E402

HERE = Path(__file__).resolve().parent
CONFIG = "long_past_1200_short_new_300"
LABELS = ("length", "topic", "section", "house")
LABEL_PERCENTILE = 0.80
TOP_K = 5


def contributions(state, vec):
    """Per-feature |tier weight x z| on the active features, as the scorer standardises them."""
    from original.quantum.scoring import _TIER_WEIGHT_VECTOR
    z = (vec - state.baseline_mean) / state.baseline_std
    c = np.abs(_TIER_WEIGHT_VECTOR * z)
    c[~state.active_feature_mask] = 0.0
    return z, c


def percentile_ranks(values: np.ndarray, active: np.ndarray) -> np.ndarray:
    """Rank of each active feature's value among active features, in [0, 1]; inactive = 0."""
    out = np.zeros_like(values, dtype=float)
    idx = np.where(active)[0]
    order = np.argsort(np.argsort(values[idx]))
    out[idx] = order / max(len(idx) - 1, 1)
    return out


LENGTH_DROP = 0.5   # |z| under a length-matched baseline at most half the original


def label_feature(i: int, ranks: dict[str, np.ndarray], z_full: float | None = None,
                  z_matched: float | None = None) -> str:
    if z_full is not None and z_matched is not None and abs(z_matched) <= LENGTH_DROP * abs(z_full):
        return "length"
    best = max(("topic", "section", "house"), key=lambda k: ranks[k][i])
    return best if ranks[best][i] >= LABEL_PERCENTILE else "genuine"


def _cut(text: str, start: int, n: int) -> str | None:
    w = text.split()
    return " ".join(w[start:start + n]) if len(w) >= start + n else None


def run(collection: str, workers: int) -> dict:
    reset_research_flags()
    from original.constants import ALL_FEATURE_CODES, FEATURE_NAMES
    from original.context.resolvers import resolve_topic
    from original.quantum.scoring import ScoringConfig
    from original.quantum.scoring import score as quantum_score
    from .fetch import DEFAULT_CACHE
    from .loader import load_manifest

    sets = {k: v for k, v in trial_sets(collection, "development").items() if k[0] == CONFIG}
    store = FeatureStore(collection)
    manifest = load_manifest(collection)
    dev_papers = [p for p in manifest.papers if p.partition == "development"]

    # section cuts: opening 300 words vs 300 words from the middle of each development paper
    sec_pairs = []
    for p in dev_papers:
        text = (DEFAULT_CACHE / collection / "texts" / p.author_id / f"{p.source_paper_id}.txt").read_text(encoding="utf-8")
        n = len(text.split())
        a, b = _cut(text, 0, 300), _cut(text, max(n // 2 - 150, 300), 300)
        if a and b:
            sec_pairs.append((p, a, b))
    texts = [t for _, a, b in sec_pairs for t in (a, b)]
    for ts in sets.values():
        for t in ts.trials:
            texts += t.baseline + t.honest + length_matched(t, 300).baseline
    store.ensure(texts, workers)
    F = lambda t: store[t][0]  # noqa: E731

    # ---- sensitivity indices (all development authors) --------------------------------
    d_len, x1200 = [], []
    for ts in sets.values():
        for t in ts.trials:
            lm = length_matched(t, 300)
            for full, pid in zip(t.baseline, t.baseline_ids):
                first = lm.baseline[lm.baseline_ids.index(f"{pid}#0")]
                d_len.append(F(first) - F(full))
                x1200.append(F(full))
    sd = np.maximum(np.std(x1200, axis=0), 1e-6)
    length_idx = np.abs(np.mean(d_len, axis=0)) / sd

    d_sec = np.array([F(a) - F(b) for _, a, b in sec_pairs])
    sec_sd = np.maximum(np.std([F(a) for _, a, _ in sec_pairs] + [F(b) for _, _, b in sec_pairs], axis=0), 1e-6)
    section_idx = np.abs(d_sec.mean(axis=0)) / sec_sd

    from urllib.parse import urlparse
    by_author = defaultdict(list)
    for p, a, b in sec_pairs:
        by_author[p.author_id].append((urlparse(p.url).netloc.lower(), (F(a) + F(b)) / 2))
    rng = random.Random(7)

    def eta2(groups, X):
        X = np.array(X)
        tot = ((X - X.mean(0)) ** 2).sum(0)
        btw = sum(((X[[i for i, g in enumerate(groups) if g == u]].mean(0) - X.mean(0)) ** 2)
                  * groups.count(u) for u in set(groups))
        return np.where(tot > 0, btw / np.maximum(tot, 1e-12), 0.0)

    obs, perm, n_auth_venue = [], [], 0
    for rows in by_author.values():
        hosts = [h for h, _ in rows]
        if len(set(hosts)) < 2 or len(rows) < 4:
            continue
        n_auth_venue += 1
        X = [x for _, x in rows]
        obs.append(eta2(hosts, X))
        shuffled = hosts[:]
        rng.shuffle(shuffled)
        perm.append(eta2(shuffled, X))
    house_idx = (np.mean(obs, 0) - np.mean(perm, 0)) if obs else np.zeros_like(length_idx)

    # per-feature honest |z| vs topic distance, plus the per-author false-flag rates
    zs, dists = [], []
    per_author = defaultdict(lambda: {"honest": 0, "flagged": 0})
    flagged_docs = []
    cfg = ScoringConfig()
    for (_, seed), ts in sorted(sets.items()):
        for t in ts.trials:
            st = _state(t, store)
            st_lm = _state(length_matched(t, 300), store)
            for j, h in enumerate(t.honest):
                vec, fd = store[h]
                z, c = contributions(st, vec)
                z_lm, _ = contributions(st_lm, vec)
                d = resolve_topic(h, t.baseline)
                zs.append(np.abs(z))
                dists.append(d["baseline_distance"])
                r = quantum_score(state=st, submission_vector=vec, feature_dict=fd,
                                  submission_id=f"h:{t.student_id}:{j}", n_tokens=300, scoring_config=cfg)
                flag = r.recommendation.action in FLAG_ACTIONS
                per_author[t.student_id]["honest"] += 1
                per_author[t.student_id]["flagged"] += flag
                if flag:
                    flagged_docs.append({"author": t.student_id, "seed": seed, "paper": t.honest_ids[j],
                                         "deviation_score": round(float(r.authorship.deviation_score), 4),
                                         "action": r.recommendation.action, "topic_distance": round(d["baseline_distance"], 4),
                                         "_c": c, "_z": z, "_zlm": z_lm})
    from scipy.stats import spearmanr  # noqa: E402  (scipy ships with scikit-learn)
    Z, D = np.array(zs), np.array(dists)
    topic_idx = np.array([spearmanr(Z[:, i], D).statistic if np.std(Z[:, i]) > 0 else 0.0 for i in range(Z.shape[1])])
    topic_idx = np.nan_to_num(topic_idx)

    active = _state(next(iter(sets.values())).trials[0], store).active_feature_mask
    ranks = {"length": percentile_ranks(length_idx, active), "topic": percentile_ranks(topic_idx, active),
             "section": percentile_ranks(section_idx, active), "house": percentile_ranks(house_idx, active)}

    # ---- choose the 8 authors -----------------------------------------------------------
    rates = {a: v["flagged"] / v["honest"] for a, v in per_author.items()}
    worst = sorted(rates, key=lambda a: (-rates[a], a))[:4]
    med = float(np.median(list(rates.values())))
    typical = sorted((a for a in rates if a not in worst),
                     key=lambda a: (abs(rates[a] - med), hashlib.sha256(a.encode()).hexdigest()))[:4]
    chosen = worst + typical

    rows, counts = [], Counter()
    for doc in flagged_docs:
        if doc["author"] not in chosen:
            continue
        c, z, z_lm = doc.pop("_c"), doc.pop("_z"), doc.pop("_zlm")
        top = np.argsort(-c)[:TOP_K]
        feats = []
        for i in top:
            lab = label_feature(int(i), ranks, float(z[i]), float(z_lm[i]))
            counts[lab] += 1
            feats.append({"code": ALL_FEATURE_CODES[i], "name": FEATURE_NAMES.get(ALL_FEATURE_CODES[i], ""),
                          "weighted_abs_z": round(float(c[i]), 3), "z": round(float(z[i]), 2),
                          "z_length_matched": round(float(z_lm[i]), 2), "label": lab,
                          "ranks": {k: round(float(ranks[k][i]), 2) for k in LABELS}})
        rows.append({**doc, "group": "highest" if doc["author"] in worst else "typical", "top_features": feats})
    for doc in flagged_docs:
        for k in ("_c", "_z", "_zlm"):
            doc.pop(k, None)

    return {
        "collection": collection, "partition": "development", "config": CONFIG, "seeds": list(SEEDS),
        "date": time.strftime("%Y-%m-%d"),
        "selection": {"highest_false_flag": {a: round(rates[a], 3) for a in worst},
                      "typical": {a: round(rates[a], 3) for a in typical},
                      "median_rate": round(med, 3), "n_authors": len(rates)},
        "label_rule": f"label of the highest percentile-ranked index if >= {LABEL_PERCENTILE}, else genuine",
        "label_counts_in_top5": dict(counts),
        "n_flagged_docs_chosen": len(rows),
        "venue_index_authors": n_auth_venue,
        "section_pairs": len(sec_pairs),
        "most_sensitive": {k: [ALL_FEATURE_CODES[i] for i in np.argsort(-v)[:8] if active[i]]
                           for k, v in (("length", length_idx), ("topic", topic_idx),
                                        ("section", section_idx), ("house", house_idx))},
        "flagged_docs": rows,
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--collection", choices=("humanities", "science"), required=True)
    ap.add_argument("--workers", type=int, default=4)
    a = ap.parse_args(argv)
    res = run(a.collection, a.workers)
    out = HERE / f"diagnosis_{a.collection}_{res['date']}.json"
    out.write_text(json.dumps(res, indent=1) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in res.items() if k != "flagged_docs"}, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
