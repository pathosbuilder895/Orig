"""Rule D: a fixed, untrained comparison rule, tested on the scholarly corpus. Validation only.

    python -m validation.scholarly.rule_d calibrate --collection humanities

For a new paper scored against claimed author A, inside one trial set, with O = every other
author in the same partition and trial set (minus the probe's own author when the paper is a
probe):

* B, character profile: character 3-5-gram TF-IDF. zB_c = (cos(paper, A's centroid) - mean over
  O) / sd over O; zB_n = the same with each author's nearest past paper. B = (zB_c + zB_n) / 2.
* C, topic-masked profile: the same on ``verifier.mask_topic`` text with 3-6-grams.
  C = (zC_c + zC_n) / 2.
* zO, Original's z: r(X) = rms of |z| (capped at 6, active features only) of the paper against
  author X's baseline; zO = -(r(A) - mean over O of r(X)) / sd over O (higher = closer to A).
* D = -(B + C + zO) / 3. Higher = less like A than other authors are. Flag when D > threshold.

Baseline cut, fixed as part of the rule: B and C use the WHOLE past papers (the 4 past-paper
cuts at the configuration's past length, not split; "nearest" = nearest of those 4). zO uses
the past papers cut into pieces of the new paper's length (``adjust.length_matched``). At
300/300 and 1200/1200 the two are identical.

The TF-IDF vectorizers are fit once on development texts (unsupervised, no labels), saved, and
reused unchanged. Thresholds: 95th percentile of calibration honest D per collection and
configuration. No weights are trained anywhere. This module cannot read ``locked_test``.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import pickle
import sys
import time
from pathlib import Path

import numpy as np

_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_ROOT))

from .adjust import CONFIGS, FeatureStore, length_matched, trial_sets  # noqa: E402
from .intended_use import SEEDS, check_partition, reset_research_flags  # noqa: E402
from .verifier import Z_CAP, _hosts, dominant_subfields, mask_topic, probe_docs  # noqa: E402

HERE = Path(__file__).resolve().parent
VEC_DIR = HERE / "cache" / "verifier"
STUDY_ID = "scholarly-rule-d-2026-11-12"
COUNTING_CELLS = (("long_past_1200_short_new_300", "random"), ("long_past_1200_short_new_300", "same_venue"),
                  ("matched_1200_1200", "random"), ("matched_1200_1200", "same_field"),
                  ("matched_1200_1200", "same_venue"))
KINDS = ("random", "same_field", "same_venue")


def rel_z(own: float, others: np.ndarray) -> float:
    return float((own - others.mean()) / (others.std() + 1e-9))


def rule_d(zB_c: float, zB_n: float, zC_c: float, zC_n: float, zO: float) -> float:
    """The rule, exactly: equal weight to the three components, higher = less like the author."""
    B = (zB_c + zB_n) / 2.0
    C = (zC_c + zC_n) / 2.0
    return -(B + C + zO) / 3.0


def rms_against(x: np.ndarray, means: np.ndarray, stds: np.ndarray, active: np.ndarray) -> np.ndarray:
    """r(X) for every author X at once: rms of capped |z| over each author's active features."""
    z = np.clip(np.abs((x[None, :] - means) / stds), 0, Z_CAP) * active
    return np.sqrt((z ** 2).sum(axis=1) / np.maximum(active.sum(axis=1), 1))


# ------------------------------------------------------------------ vectorizers --
def vectorizer_path(collection: str) -> Path:
    return VEC_DIR / f"rule_d_vectorizers_{collection}.pkl"


def fit_or_load_vectorizers(collection: str) -> tuple[dict, str]:
    """Fit once on development texts and freeze; returns (vectorizers, sha256 of the file)."""
    from sklearn.feature_extraction.text import TfidfVectorizer
    path = vectorizer_path(collection)
    if not path.exists():
        texts = []
        for ts in trial_sets(collection, "development").values():
            for t in ts.trials:
                texts += t.baseline + t.honest + t.probes
        uniq = list(dict.fromkeys(texts))
        vecs = {
            "char": TfidfVectorizer(analyzer="char", ngram_range=(3, 5), sublinear_tf=True, min_df=3,
                                    max_features=60000, dtype=np.float32).fit(uniq),
            "masked": TfidfVectorizer(analyzer="char", ngram_range=(3, 6), sublinear_tf=True, min_df=3,
                                      max_features=60000, dtype=np.float32, preprocessor=mask_topic).fit(uniq),
        }
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(pickle.dumps(vecs))
    data = path.read_bytes()
    return pickle.loads(data), hashlib.sha256(data).hexdigest()


# ------------------------------------------------------------------------ rows --
def _unit_rows(X) -> np.ndarray:
    X = np.asarray(X.todense(), dtype=np.float32)
    return X / (np.linalg.norm(X, axis=1, keepdims=True) + 1e-12)


def build_scores(collection: str, sets: dict, vecs: dict) -> list[dict]:
    """Rule-D score and its components for every new paper in every trial set."""
    from original.quantum.state import BaselineSample, StudentState
    reset_research_flags()
    store = FeatureStore(collection)
    texts = []
    for (name, _), ts in sets.items():
        new_w = dict((n, w) for n, _, w in CONFIGS)[name]
        for t in ts.trials:
            texts += length_matched(t, new_w).baseline + t.honest + t.probes
    store.ensure(texts)
    field, hosts = dominant_subfields(collection), _hosts(collection)
    rows = []
    for (name, seed), ts in sorted(sets.items()):
        new_w = dict((n, w) for n, _, w in CONFIGS)[name]
        trials = list(ts.trials)
        authors = [t.student_id for t in trials]
        idx = {a: i for i, a in enumerate(authors)}
        # B and C: whole past papers; centroid and per-paper vectors per author
        cent, papers = {}, {}
        for k, vz in vecs.items():
            P = [_unit_rows(vz.transform(t.baseline)) for t in trials]
            papers[k] = P
            c = np.stack([p.mean(axis=0) for p in P])
            cent[k] = c / (np.linalg.norm(c, axis=1, keepdims=True) + 1e-12)
        # zO: length-matched baselines through Original's StudentState
        means, stds, act = [], [], []
        for t in trials:
            st = StudentState(student_id=t.student_id)
            for b in length_matched(t, new_w).baseline:
                st.add_sample(BaselineSample(text=b, vector=store[b][0], provenance="verified",
                                             auth_weight=1.0, genre="essay"))
            means.append(st.baseline_mean)
            stds.append(st.baseline_std)
            act.append(st.active_feature_mask.astype(float))
        means, stds, act = np.stack(means), np.stack(stds), np.stack(act)
        honest_of = {t.student_id: t.honest[0] for t in trials}
        for t in trials:
            a = idx[t.student_id]
            for text, label, src, kind in probe_docs(t, authors, honest_of, field, hosts, seed):
                others = np.array([idx[o] for o in authors if o != t.student_id and o != src])
                comps = {}
                for k, vz in vecs.items():
                    d = _unit_rows(vz.transform([text]))[0]   # the masked vectorizer masks via its preprocessor
                    sims_c = cent[k] @ d
                    sims_n = np.array([float((P @ d).max()) for P in papers[k]])
                    comps[f"{k}_c"] = rel_z(float(sims_c[a]), sims_c[others])
                    comps[f"{k}_n"] = rel_z(float(sims_n[a]), sims_n[others])
                r = rms_against(store[text][0], means, stds, act)
                zO = -rel_z(float(r[a]), r[others])
                D = rule_d(comps["char_c"], comps["char_n"], comps["masked_c"], comps["masked_n"], zO)
                rows.append({"author": t.student_id, "config": name, "seed": seed, "label": label,
                             "kind": kind, "src": src, "D": D, "zO": zO, **comps})
    return rows


# --------------------------------------------------------------------- metrics --
def _per_author(rows, kind=None):
    out = {}
    for r in rows:
        a = out.setdefault(r["author"], {"author": r["author"], "honest": [], "probe": []})
        if not r["label"]:
            a["honest"].append(r["D"])
        elif kind is None or r["kind"] == kind:
            a["probe"].append(r["D"])
    return [out[k] for k in sorted(out)]


def threshold_from(rows) -> float:
    h = np.array([r["D"] for r in rows if not r["label"]])
    return float(np.quantile(h, 0.95, method="higher"))


def cell_report(rows, thr: float, kind: str, n_boot: int) -> dict:
    from .baseline import _auc
    from .intended_use import bootstrap_at
    pa = _per_author(rows, kind)
    pa = [a for a in pa if a["honest"] or a["probe"]]
    h = np.array([v for a in pa for v in a["honest"]])
    p = np.array([v for a in pa for v in a["probe"]])
    ci = bootstrap_at(pa, thr, n_boot)
    rng = np.random.default_rng(0)
    aucs = []
    for _ in range(n_boot):
        pick = [pa[i] for i in rng.integers(0, len(pa), len(pa))]
        hh = np.array([v for a in pick for v in a["honest"]])
        pp = np.array([v for a in pick for v in a["probe"]])
        if hh.size and pp.size:
            aucs.append(_auc(hh, pp))
    return {"honest_flag_rate": round(float((h > thr).mean()), 4), "honest_ci95": ci["honest_flag_rate"],
            "catch_rate": round(float((p > thr).mean()), 4), "catch_ci95": ci["other_writer_catch_rate"],
            "auc": round(_auc(h, p), 4),
            "auc_ci95": [round(float(np.quantile(aucs, q)), 4) for q in (0.025, 0.975)],
            "n_authors": len(pa), "n_honest": int(h.size), "n_probe": int(p.size)}


def passes(cell: dict) -> dict:
    """The pre-registered bar: catch >= 85%, catch CI low >= 80%, honest CI high <= 10%."""
    checks = {"catch_at_least_85": cell["catch_rate"] >= 0.85,
              "catch_ci_low_at_least_80": cell["catch_ci95"][0] >= 0.80,
              "honest_ci_high_at_most_10": cell["honest_ci95"][1] <= 0.10}
    return {**checks, "pass": all(checks.values())}


def partition_author_counts(collection: str) -> dict:
    """Authors per partition, from the manifest only (no text is read)."""
    from collections import Counter
    from .loader import load_manifest
    m = load_manifest(collection)
    return dict(Counter(ps[0].partition for ps in m.authors().values()))


def calibrate(collection: str, n_boot: int) -> dict:
    check_partition("calibration")
    vecs, vec_sha = fit_or_load_vectorizers(collection)
    sets = trial_sets(collection, "calibration")
    rows = build_scores(collection, sets, vecs)
    out = {"collection": collection, "partition": "calibration", "date": time.strftime("%Y-%m-%d"),
           "rule": "D = -(B + C + zO)/3; see module docstring", "vectorizers_sha256": vec_sha,
           "seeds": list(SEEDS), "authors_per_partition": partition_author_counts(collection),
           "skipped": {f"{n}/seed{s}/{a}": why for (n, s), ts in sets.items() for a, why in ts.skipped.items()},
           "thresholds": {}, "cells": {}}
    for name, _, _ in CONFIGS:
        R = [r for r in rows if r["config"] == name]
        thr = threshold_from(R)
        out["thresholds"][name] = round(thr, 6)
        out["cells"][name] = {}
        for kind in KINDS:
            cell = cell_report(R, thr, kind, n_boot)
            cell["counts_toward_goal"] = (name, kind) in COUNTING_CELLS
            if cell["counts_toward_goal"]:
                cell["would_pass_bar_here"] = passes(cell)
            out["cells"][name][kind] = cell
            print(collection, name, kind, json.dumps({k: cell[k] for k in ("honest_flag_rate", "catch_rate",
                                                                             "catch_ci95", "auc")}), flush=True)
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("step", choices=("calibrate",))
    ap.add_argument("--collection", choices=("humanities", "science"), required=True)
    ap.add_argument("--n-boot", type=int, default=1000)
    a = ap.parse_args(argv)
    res = calibrate(a.collection, a.n_boot)
    (HERE / f"rule_d_thresholds_{a.collection}.json").write_text(json.dumps({
        "collection": a.collection, "study_id": STUDY_ID, "chosen_on": "calibration",
        "rule": "95th percentile of calibration honest D (seeds 7, 11, 23 pooled); flag = D strictly above",
        "vectorizers_sha256": res["vectorizers_sha256"], "thresholds": res["thresholds"]}, indent=1) + "\n",
        encoding="utf-8")
    out = HERE / f"rule_d_{a.collection}_calibration_{res['date']}.json"
    out.write_text(json.dumps(res, indent=1) + "\n", encoding="utf-8")
    print("wrote", out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
