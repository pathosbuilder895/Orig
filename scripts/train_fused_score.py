"""Regenerate original/data/fused_score_v1.json from PAN development authors.

Offline only — may use sklearn; the runtime loader never does. Run:

    .venv/bin/python scripts/train_fused_score.py

Fits the standardizer and logistic on the 120 development authors, runs a
per-channel ablation to decide whether the function-word network ships,
selects the 5%/1% false-alarm thresholds on development genuine trials, and
prints held-out metrics on the 52 locked authors for the record. Nothing
about the held-out authors influences any fitted value.
"""

from __future__ import annotations

import hashlib
import json
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import numpy as np
from sklearn.linear_model import LogisticRegression

from original.constants import FEATURE_DIM
from original.features.pipeline import feature_vector
from original.fusion.channels import (
    CHANNEL_NAMES,
    compressed_size,
    compression_distance,
    diagonal_z_distance,
    function_word_distance,
    function_word_matrix,
)
from validation.verify.pan_style_expert import load_author_partitions

SEED = 20260807
N_REFERENCES = 8
PAN_CACHE = ROOT / ".benchmark_cache" / "pan" / "2020"
OUT_PATH = ROOT / "original" / "data" / "fused_score_v1.json"
ABLATION_MIN_AUC_GAIN = 0.002  # below this a channel is noise and is dropped


# Feature extraction dominates this script's runtime (~1.5s per 2,500-word
# text) and the same texts recur several times over: every probe is extracted
# once as its own author's genuine probe and again as the ring-successor's
# impostor probe, and the first eight development authors' baselines are
# profiled both as trial subjects and as the reference pool. Memoize in
# process, and persist to disk so a re-run — the whole point of committing
# this script — costs seconds instead of forty minutes.
_VEC_CACHE_PATH = ROOT / ".benchmark_cache" / "features" / "fused_train_vectors.npz"
_vec_cache: dict[str, np.ndarray] = {}
_fw_cache: dict[str, np.ndarray] = {}
_vec_cache_dirty = False


def _text_key(text: str) -> str:
    return hashlib.sha256(f"fused_train.v1:{FEATURE_DIM}:{text}".encode()).hexdigest()


def _load_vec_cache() -> None:
    if not _VEC_CACHE_PATH.exists():
        return
    try:
        stored = np.load(_VEC_CACHE_PATH, allow_pickle=False)
        _vec_cache.update(zip([str(k) for k in stored["keys"]], stored["vectors"]))
        print(f"feature cache: loaded {len(_vec_cache)} vectors", flush=True)
    except Exception as exc:  # noqa: BLE001 — a corrupt cache must not block training
        print(f"feature cache unreadable ({exc}); recomputing from scratch", flush=True)


def _save_vec_cache() -> None:
    if not _vec_cache_dirty:
        return
    _VEC_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(
        _VEC_CACHE_PATH,
        keys=np.array(list(_vec_cache)),
        vectors=np.stack(list(_vec_cache.values())),
    )
    print(f"feature cache: saved {len(_vec_cache)} vectors", flush=True)


def _vector(text: str) -> np.ndarray:
    global _vec_cache_dirty
    key = _text_key(text)
    hit = _vec_cache.get(key)
    if hit is None:
        hit = np.asarray(feature_vector(text), dtype=np.float64)
        _vec_cache[key] = hit
        _vec_cache_dirty = True
    return hit


def _fw(text: str) -> np.ndarray:
    key = _text_key(text)
    hit = _fw_cache.get(key)
    if hit is None:
        hit = function_word_matrix(text)
        _fw_cache[key] = hit
    return hit


def _profile(texts: list[str]) -> dict:
    joined = "\n".join(texts)
    vectors = np.stack([_vector(t) for t in texts])
    return {
        "text": joined,
        "size": compressed_size(joined.encode("utf-8", "ignore")),
        "fw": _fw(joined),
        "mean": vectors.mean(axis=0),
        "std": np.maximum(vectors.std(axis=0), max(0.005, 0.15 / np.sqrt(len(texts)))),
    }


def _raw(profile: dict, probe_vec, probe_text, probe_fw) -> list[float]:
    return [
        diagonal_z_distance(probe_vec, profile["mean"], profile["std"]),
        compression_distance(profile["text"], probe_text, baseline_size=profile["size"]),
        function_word_distance(profile["fw"], probe_fw),
    ]


def _trials(authors, reference_pool, rng):
    """(X, y) with y=1 meaning impostor. Ring assignment for impostor probes."""
    profiles = [_profile(list(a.baselines)) for a in authors]
    ref_profiles = [_profile(list(a.baselines)) for a in reference_pool[:N_REFERENCES]]
    order = list(range(len(authors)))
    rng.shuffle(order)
    impostor_of = {order[i]: order[(i + 1) % len(order)] for i in range(len(order))}

    rows, labels = [], []
    for index, author in enumerate(authors):
        probes = [(t, 0) for t in author.probes]
        probes += [(t, 1) for t in authors[impostor_of[index]].probes]
        for text, label in probes:
            vec = _vector(text)
            fw = _fw(text)
            own = _raw(profiles[index], vec, text, fw)
            peer = np.mean([_raw(p, vec, text, fw) for p in ref_profiles], axis=0)
            rows.append(list(np.asarray(own) - peer))
            labels.append(label)
    return np.asarray(rows), np.asarray(labels)


def _auc(scores, labels) -> float:
    scores, labels = np.asarray(scores, float), np.asarray(labels)
    pos, neg = scores[labels == 1], scores[labels == 0]
    if not len(pos) or not len(neg):
        return float("nan")
    diff = pos[:, None] - neg[None, :]
    return float(((diff > 0).sum() + 0.5 * (diff == 0).sum()) / diff.size)


def _fit(X, y):
    mu, sd = X.mean(axis=0), X.std(axis=0) + 1e-12
    model = LogisticRegression(C=1e6, max_iter=5000).fit((X - mu) / sd, y)
    return mu, sd, model


def main() -> None:
    _load_vec_cache()
    rng = np.random.default_rng(SEED)
    partitions = load_author_partitions(cache_dir=PAN_CACHE)
    development = partitions["development"]
    held_out = partitions["calibration"] + partitions["locked"]
    print(f"development={len(development)} held_out={len(held_out)}", flush=True)

    X_dev, y_dev = _trials(development, development, np.random.default_rng(SEED + 1))
    X_eval, y_eval = _trials(held_out, development, np.random.default_rng(SEED + 2))

    # Ablation: keep a channel only if dropping it costs more than the floor.
    mu, sd, model = _fit(X_dev, y_dev)
    full_auc = _auc(model.decision_function((X_dev - mu) / sd), y_dev)
    keep = []
    for index, name in enumerate(CHANNEL_NAMES):
        columns = [i for i in range(len(CHANNEL_NAMES)) if i != index]
        m2, s2, reduced = _fit(X_dev[:, columns], y_dev)
        without = _auc(reduced.decision_function((X_dev[:, columns] - m2) / s2), y_dev)
        gain = full_auc - without
        print(f"ablation {name:24s} dev AUC without = {without:.4f}  gain = {gain:+.4f}")
        if gain >= ABLATION_MIN_AUC_GAIN:
            keep.append(index)
    if not keep:
        raise SystemExit("ablation dropped every channel — refusing to write an empty model")
    channel_order = [CHANNEL_NAMES[i] for i in keep]
    print(f"shipping channels: {channel_order}", flush=True)

    mu, sd, model = _fit(X_dev[:, keep], y_dev)
    weights = model.coef_[0]
    intercept = float(model.intercept_[0])

    dev_scores = ((X_dev[:, keep] - mu) / sd) @ weights + intercept
    genuine = np.sort(dev_scores[y_dev == 0])
    threshold_fa5 = float(genuine[int(round(0.95 * (len(genuine) - 1)))])
    threshold_fa1 = float(genuine[int(round(0.99 * (len(genuine) - 1)))])
    if not threshold_fa5 < threshold_fa1:
        threshold_fa1 = threshold_fa5 + 1e-6

    eval_scores = ((X_eval[:, keep] - mu) / sd) @ weights + intercept
    print(f"\nHELD-OUT AUC  = {_auc(eval_scores, y_eval):.4f}")
    for name, bar in (("fa5", threshold_fa5), ("fa1", threshold_fa1)):
        caught = float(np.mean(eval_scores[y_eval == 1] >= bar))
        false_alarm = float(np.mean(eval_scores[y_eval == 0] >= bar))
        print(f"  at {name}: catch = {caught:.3f}  false alarms = {false_alarm:.3f}")

    reference_inputs = X_dev[:5, keep]
    reference_outputs = [
        float(np.dot((row - mu) / sd, weights) + intercept) for row in reference_inputs
    ]
    payload = {
        "schema_version": 1,
        "channel_order": channel_order,
        "mu": [float(v) for v in mu],
        "sd": [float(v) for v in sd],
        "weights": [float(v) for v in weights],
        "intercept": intercept,
        "threshold_fa5": threshold_fa5,
        "threshold_fa1": threshold_fa1,
        "reference_inputs": [[float(v) for v in row] for row in reference_inputs],
        "reference_outputs": reference_outputs,
        "provenance": {
            "dataset": "PAN 2020 cross-fandom authorship verification",
            "n_development_authors": len(development),
            "n_references": N_REFERENCES,
            "trained": date.today().isoformat(),
            "seed": SEED,
        },
    }
    OUT_PATH.write_text(json.dumps(payload, indent=2) + "\n")
    _save_vec_cache()
    print(f"\nwrote {OUT_PATH}", flush=True)


if __name__ == "__main__":
    main()
