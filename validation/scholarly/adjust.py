"""Candidate comparison adjustments, tested on the scholarly corpus. Validation only.

Nothing here changes the product: every adjustment is either a different way of building
the inputs (length-matched baseline cuts, a topic-distance manifest, a peer pool) or a
``ScoringConfig`` field passed explicitly to ``quantum.scoring.score``. No environment flag
is set and nothing under ``original/`` is modified.

    python -m validation.scholarly.adjust features --collection humanities --partition development
    python -m validation.scholarly.adjust evaluate --collection humanities --partition development \
        --candidates flags_off a_length_matched ...

Features are extracted once per text and cached (git-ignored) so candidates are compared on
identical inputs. Only ``development`` and ``calibration`` can be read; ``locked_test`` is
unreachable from this module.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import pickle
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass, replace
from pathlib import Path

import numpy as np

_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_ROOT))

from .intended_use import SEEDS, check_partition, reset_research_flags  # noqa: E402

HERE = Path(__file__).resolve().parent
FEATURE_DIR = HERE / "cache" / "features"
FLAG_ACTIONS = ("schedule_conversation", "escalate")
CONFIGS = (("matched_300_300", 300, 300), ("matched_1200_1200", 1200, 1200),
           ("long_past_1200_short_new_300", 1200, 300))


@dataclass(frozen=True)
class Candidate:
    """One adjustment, or a combination. Every field defaults to the flags-off scorer."""
    name: str
    reason: str
    length_matched: bool = False        # (a) cut each past paper into pieces of the new paper's length
    length_adaptive: bool = False       # (b) ScoringConfig.length_adaptive_weights
    topic_inflation: bool = False       # (c) ScoringConfig.topic_variance_inflation="on" + topic manifest
    characteristic: bool = False        # (d) ScoringConfig.characteristic_weights="on" + peer pool
    llr: bool = False                   # (e) NULL_MODEL=impostor via ScoringConfig; decide on llr_deviation_score

    @property
    def needs_pool(self) -> bool:
        return self.characteristic or self.llr


CANDIDATES = {
    "flags_off": Candidate("flags_off", "reference: the shipped default scorer"),
    "a_length_matched": Candidate(
        "a_length_matched", "past papers cut into pieces the size of the new paper, so the baseline "
        "mean and spread are estimated at the length being compared", length_matched=True),
    "b_length_adaptive": Candidate(
        "b_length_adaptive", "rescales per-feature weights by submission length", length_adaptive=True),
    "c_topic_inflation": Candidate(
        "c_topic_inflation", "widens expected spread in proportion to topic distance from the baseline",
        topic_inflation=True),
    "d_characteristic": Candidate(
        "d_characteristic", "weights features by how stable they are for this author relative to peers",
        characteristic=True),
    "e_impostor_llr": Candidate(
        "e_impostor_llr", "decides on how much more like the author than like peers the paper is",
        llr=True),
}


def register_combination(name: str, reason: str, *parts: str) -> Candidate:
    """(f) A combination of earlier candidates, named after the diagnosis that motivates it."""
    fields = {k: any(getattr(CANDIDATES[p], k) for p in parts)
              for k in ("length_matched", "length_adaptive", "topic_inflation", "characteristic", "llr")}
    c = Candidate(name, reason, **fields)
    CANDIDATES[name] = c
    return c


# ------------------------------------------------------------------- features --
def _key(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _extract(text: str):
    from original.features.pipeline import extract_features, feature_vector
    return _key(text), (feature_vector(text), extract_features(text))


class FeatureStore:
    def __init__(self, collection: str):
        self.path = FEATURE_DIR / f"{collection}.pkl"
        self.data: dict = pickle.loads(self.path.read_bytes()) if self.path.exists() else {}

    def ensure(self, texts, workers: int = 4) -> int:
        todo = list({_key(t): t for t in texts if _key(t) not in self.data}.values())
        if todo:
            with ProcessPoolExecutor(max_workers=workers) as ex:
                for k, v in ex.map(_extract, todo, chunksize=8):
                    self.data[k] = v
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_bytes(pickle.dumps(self.data))
            tmp.replace(self.path)
        return len(todo)

    def __getitem__(self, text: str):
        return self.data[_key(text)]


# --------------------------------------------------------------------- trials --
def length_matched(trial, piece_words: int):
    """Each past paper cut into consecutive pieces of ``piece_words`` (the new paper's length)."""
    pieces, ids = [], []
    for text, pid in zip(trial.baseline, trial.baseline_ids):
        w = text.split()
        for i in range(0, len(w) - piece_words + 1, piece_words):
            pieces.append(" ".join(w[i:i + piece_words]))
            ids.append(f"{pid}#{i // piece_words}")
    return replace(trial, baseline=pieces, baseline_ids=ids)


def trial_sets(collection: str, partition: str, seeds=SEEDS) -> dict:
    from .loader import load_trials
    check_partition(partition)
    out = {}
    for name, past_w, new_w in CONFIGS:
        for seed in seeds:
            out[(name, seed)] = load_trials(collection, partition, n_past=4, n_new=2, past_words=past_w,
                                            new_words=new_w, n_probes=5, seed=seed)
    return out


def all_texts(sets: dict) -> list[str]:
    texts = []
    for (name, _), ts in sets.items():
        new_w = dict((n, w) for n, _, w in CONFIGS)[name]
        past_w = dict((n, w) for n, w, _ in CONFIGS)[name]
        for t in ts.trials:
            texts += t.baseline + t.honest + t.probes
            if past_w > new_w:
                texts += length_matched(t, new_w).baseline
    return texts


# -------------------------------------------------------------------- scoring --
def _state(trial, feats):
    from original.quantum.state import BaselineSample, StudentState
    s = StudentState(student_id=trial.student_id)
    for t in trial.baseline:
        s.add_sample(BaselineSample(text=t, vector=feats[t][0], provenance="verified", auth_weight=1.0,
                                    genre="essay"))
    return s


def _pools(trials, feats) -> dict:
    """Per author: (mu, sigma) of every OTHER author's past-paper vectors in the same trial set,
    mirroring the product's same-tenant peer pool (null_pool.build_impostor_stats)."""
    from original.quantum.null_pool import fit_impostor_gaussian
    vecs = {t.student_id: [feats[x][0] for x in t.baseline] for t in trials}
    return {a: fit_impostor_gaussian([v for b, vs in vecs.items() if b != a for v in vs]) for a in vecs}


def score_trial(trial, feats, cand: Candidate, new_w: int, pool=None) -> dict:
    from original.context.resolvers import resolve_topic
    from original.quantum.scoring import ScoringConfig
    from original.quantum.scoring import score as quantum_score
    if cand.length_matched:
        trial = length_matched(trial, new_w)
    state = _state(trial, feats)
    cfg = ScoringConfig(length_adaptive_weights=cand.length_adaptive,
                        null_model="impostor" if cand.llr else "none",
                        topic_variance_inflation="on" if cand.topic_inflation else "off",
                        characteristic_weights="on" if cand.characteristic else "off")
    row = {"author": trial.student_id, "honest": [], "honest_flag": [], "probe": [], "probe_flag": [],
           "honest_dev": [], "probe_dev": [], "llr_missing": 0}
    for kind, texts in (("honest", trial.honest), ("probe", trial.probes)):
        for j, text in enumerate(texts):
            vec, fd = feats[text]
            manifest = {"topic": resolve_topic(text, trial.baseline)} if cand.topic_inflation else None
            r = quantum_score(state=state, submission_vector=vec, feature_dict=fd,
                              submission_id=f"{kind}:{trial.student_id}:{j}", manifest=manifest,
                              n_tokens=new_w, impostor_stats=pool if cand.needs_pool else None,
                              scoring_config=cfg)
            a = r.authorship
            stat = a.deviation_score
            if cand.llr:
                if a.llr_deviation_score is None:
                    row["llr_missing"] += 1
                else:
                    stat = a.llr_deviation_score
            row[kind].append(float(stat))
            row[f"{kind}_dev"].append(float(a.deviation_score))
            row[f"{kind}_flag"].append(r.recommendation.action in FLAG_ACTIONS)
    return row


def _score_job(args):
    trials_and_pools, cand, new_w, feat_path = args
    feats = _FEATS_CACHE.get(feat_path)
    if feats is None:
        feats = _load_feats(feat_path)
    return [score_trial(t, feats, cand, new_w, pool) for t, pool in trials_and_pools]


_FEATS_CACHE: dict = {}


def _load_feats(path):
    class _F(dict):
        def __getitem__(self, text):
            return dict.__getitem__(self, _key(text))
    d = _F(pickle.loads(Path(path).read_bytes()))
    _FEATS_CACHE[path] = d
    return d


def score_set(ts, cand: Candidate, new_w: int, store: FeatureStore, workers: int = 4) -> list[dict]:
    trials = ts.trials
    pools = {}
    if cand.needs_pool:
        feats = _load_feats(str(store.path))
        base = [length_matched(t, new_w) if cand.length_matched else t for t in trials]
        pools = _pools(base, feats)
    jobs = [(trials[i::workers], ) for i in range(workers)]
    args = [([(t, pools.get(t.student_id)) for t in chunk], cand, new_w, str(store.path)) for (chunk,) in jobs]
    with ProcessPoolExecutor(max_workers=workers) as ex:
        out = [row for part in ex.map(_score_job, args) for row in part]
    return sorted(out, key=lambda r: r["author"])


# -------------------------------------------------------------------- metrics --
def catch_at_rate(per_author: list[dict], rate: float = 0.05) -> dict:
    """Catch rate when the threshold is set so that ``rate`` of honest documents score above it."""
    h = np.array([s for a in per_author for s in a["honest"]], dtype=float)
    p = np.array([s for a in per_author for s in a["probe"]], dtype=float)
    thr = float(np.quantile(h, 1.0 - rate, method="higher"))
    return {"threshold": thr, "honest_above": float((h > thr).mean()), "catch": float((p > thr).mean())}


def bootstrap_catch(per_author: list[dict], rate: float = 0.05, n_boot: int = 1000, seed: int = 0) -> list[float]:
    """Author-level interval for catch@rate; the threshold is re-set inside every resample."""
    rng = np.random.default_rng(seed)
    n = len(per_author)
    vals = [catch_at_rate([per_author[j] for j in rng.integers(0, n, n)], rate)["catch"] for _ in range(n_boot)]
    return [round(float(np.quantile(vals, 0.025)), 4), round(float(np.quantile(vals, 0.975)), 4)]


def summarise(per_author: list[dict], n_boot: int) -> dict:
    from .baseline import bootstrap, metrics
    m = metrics(per_author)            # honest_flag_rate, other_writer_catch_rate (product bands), AUC of stat
    c = catch_at_rate(per_author)
    return {
        "catch_at_5pct_honest": round(c["catch"], 4),
        "catch_at_5pct_ci95": bootstrap_catch(per_author, n_boot=n_boot),
        "product_honest_flag_rate": round(m["honest_flag_rate"], 4),
        "product_catch_rate": round(m["other_writer_catch_rate"], 4),
        "auc": round(m["auc"], 4),
        "ci95_author_bootstrap": bootstrap(per_author, n_boot, 0),
        "n_authors": len(per_author), "n_honest": m["n_honest"], "n_probe": m["n_probe"],
        "llr_missing": int(sum(a.get("llr_missing", 0) for a in per_author)),
    }


def evaluate(collection: str, partition: str, names: list[str], workers: int, n_boot: int,
             seeds=SEEDS, keep_rows: bool = False) -> dict:
    from .intended_use import pool_by_author
    reset_research_flags()
    sets = trial_sets(collection, partition, seeds)
    store = FeatureStore(collection)
    added = store.ensure(all_texts(sets), workers)
    out = {"collection": collection, "partition": partition, "date": time.strftime("%Y-%m-%d"),
           "seeds": list(seeds), "features_extracted_now": added, "skipped": {}, "candidates": {}}
    for (name, seed), ts in sets.items():
        out["skipped"].update({f"{name}/seed{seed}/{a}": why for a, why in ts.skipped.items()})
    for cname in names:
        cand = CANDIDATES[cname]
        res = {"reason": cand.reason, "configs": {}}
        for name, _, new_w in CONFIGS:
            t0 = time.time()
            runs = [score_set(sets[(name, s)], cand, new_w, store, workers) for s in seeds]
            pooled = pool_by_author(runs)
            res["configs"][name] = {"pooled": summarise(pooled, n_boot), "seconds": round(time.time() - t0)}
            if keep_rows:
                res["configs"][name]["rows"] = runs
            print(cname, name, json.dumps(res["configs"][name]["pooled"]), flush=True)
        out["candidates"][cname] = res
    return out


def calibrate(collection: str, names: list[str], workers: int, n_boot: int) -> dict:
    """Step 4: for the chosen candidates only, fix a threshold per configuration on the
    calibration partition (5% honest flags there), report calibration once, then apply the
    same thresholds to development as a transfer check. Nothing is chosen after this."""
    from .intended_use import bootstrap_at, pool_by_author, rates_at
    cal = evaluate(collection, "calibration", names, workers, n_boot, keep_rows=True)
    dev = evaluate(collection, "development", names, workers, n_boot, keep_rows=True)
    out = {"collection": collection, "date": cal["date"], "candidates": {},
           "skipped": {"calibration": cal["skipped"], "development": dev["skipped"]},
           "rule": "threshold = 95th percentile of calibration honest decision statistic (seeds pooled); "
                   "flag = strictly above"}
    thresholds = {}
    for c in names:
        res = {"reason": CANDIDATES[c].reason, "configs": {}}
        for name, _, _ in CONFIGS:
            cal_pool = pool_by_author(cal["candidates"][c]["configs"][name].pop("rows"))
            dev_pool = pool_by_author(dev["candidates"][c]["configs"][name].pop("rows"))
            thr = catch_at_rate(cal_pool)["threshold"]
            thresholds.setdefault(c, {})[name] = round(thr, 6)
            res["configs"][name] = {
                "threshold": round(thr, 6),
                "calibration": {**cal["candidates"][c]["configs"][name]["pooled"],
                                "at_threshold": {**{k: round(v, 4) for k, v in rates_at(cal_pool, thr).items()},
                                                 "ci95_author_bootstrap": bootstrap_at(cal_pool, thr, n_boot)}},
                "development_at_calibration_threshold": {
                    **{k: round(v, 4) for k, v in rates_at(dev_pool, thr).items()},
                    "ci95_author_bootstrap": bootstrap_at(dev_pool, thr, n_boot)},
            }
        out["candidates"][c] = res
    out["thresholds"] = thresholds
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("step", choices=("features", "evaluate", "calibrate"))
    ap.add_argument("--collection", choices=("humanities", "science"), required=True)
    ap.add_argument("--partition", default="development")
    ap.add_argument("--candidates", nargs="+", default=["flags_off"])
    ap.add_argument("--combo", nargs="+", default=[], help="NAME:part1+part2:reason (registered before evaluating)")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--n-boot", type=int, default=1000)
    ap.add_argument("--out", type=Path, default=None)
    a = ap.parse_args(argv)
    check_partition(a.partition)
    for spec in a.combo:
        name, parts, reason = spec.split(":", 2)
        register_combination(name, reason, *parts.split("+"))
    if a.step == "features":
        reset_research_flags()
        sets = trial_sets(a.collection, a.partition)
        print("extracted", FeatureStore(a.collection).ensure(all_texts(sets), a.workers))
        return 0
    if a.step == "calibrate":
        res = calibrate(a.collection, a.candidates, a.workers, a.n_boot)
        out = a.out or HERE / f"adjust_{a.collection}_calibration_{res['date']}.json"
        out.write_text(json.dumps(res, indent=1) + "\n", encoding="utf-8")
        print("wrote", out)
        return 0
    res = evaluate(a.collection, a.partition, a.candidates, a.workers, a.n_boot)
    out = a.out or HERE / f"adjust_{a.collection}_{a.partition}_{res['date']}.json"
    out.write_text(json.dumps(res, indent=1) + "\n", encoding="utf-8")
    print("wrote", out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
