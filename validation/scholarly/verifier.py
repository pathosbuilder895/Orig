"""A learned same-author verifier built in validation/ only. Nothing in the product changes.

    python -m validation.scholarly.verifier crossfit --collection humanities
    python -m validation.scholarly.verifier freeze-and-check --collection humanities

For each trial (an author's 4 past papers, cut to the new paper's length; 2 new papers by
the author; 5 papers by other authors) it builds a signal vector per new paper:

* scorer features: per-feature |z| against the author's length-matched baseline, and the
  same against a peer pool (other authors' baselines), plus their summaries;
* character 3-5-gram TF-IDF: cosine similarity to the author's baseline centroid, relative
  to the similarity to every other author's baseline (an impostor comparison);
* function-word frequencies (Burrows-style z-scored): distance to the author's baseline,
  relative to other authors.

**Fairness rule.** When the paper is a probe written by author B, author B is removed from
the impostor and peer pools: a ghostwriter is normally not one of the class, so their own
baseline must not be there to make the catch easy.

**Out of sample.** ``crossfit`` splits the development authors into two halves by a hash of
the author id, trains a logistic regression on one half and scores the other, and swaps, so
every reported development score comes from a model that never saw that author.
``freeze-and-check`` trains on all development authors, freezes the model and every
threshold, and scores the calibration partition once. ``locked_test`` is unreachable here.
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

from .adjust import CONFIGS, FeatureStore, catch_at_rate, length_matched, trial_sets  # noqa: E402
from .intended_use import SEEDS, check_partition, reset_research_flags  # noqa: E402

HERE = Path(__file__).resolve().parent
MODEL_DIR = HERE / "cache" / "verifier"
Z_CAP = 6.0

FUNCTION_WORDS = tuple("""a about above after again against all also although am among an and another any are as at
be because been before being below between both but by can could did do does doing down during each either
enough even ever every few for from further had has have having he her here hers herself him himself his how
however i if in indeed into is it its itself just least less many may me might more moreover most much must my
myself neither never no nor not now of off often on once one only or other others otherwise our ours ourselves
out over own perhaps rather same she should since so some still such than that the their theirs them themselves
then there therefore these they this those though through thus to too under until up upon us very was we well
were what whatever when where whereas whether which while who whom whose why will with within without would yet
you your yours""".split())


def split_of(author_id: str) -> int:
    return int(hashlib.sha256(f"verifier-split:{author_id}".encode()).hexdigest(), 16) % 2


def _fw_vector(text: str) -> np.ndarray:
    toks = [t.strip(".,;:!?\"'()[]").lower() for t in text.split()]
    n = max(len(toks), 1)
    idx = {w: i for i, w in enumerate(FUNCTION_WORDS)}
    v = np.zeros(len(FUNCTION_WORDS))
    for t in toks:
        i = idx.get(t)
        if i is not None:
            v[i] += 1
    return v / n


_FW_SET = frozenset(FUNCTION_WORDS)


def mask_topic(text: str) -> str:
    """Text distortion (Stamatatos 2017): keep function words and punctuation, replace every
    letter of every other word with '*' and every digit with '#', so character n-grams see
    style (word shapes, punctuation, function-word sequences) and not subject matter."""
    out = []
    for tok in text.split():
        core = tok.strip(".,;:!?\"'()[]")
        if core.lower() in _FW_SET:
            out.append(tok)
        else:
            out.append("".join("*" if ch.isalpha() else "#" if ch.isdigit() else ch for ch in tok))
    return " ".join(out)


POS_DIR = HERE / "cache" / "features"


class PosTags:
    """Coarse part-of-speech tag strings per text (spaCy en_core_web_sm), cached on disk."""

    def __init__(self, collection: str):
        self.path = POS_DIR / f"pos_{collection}.pkl"
        self.data = pickle.loads(self.path.read_bytes()) if self.path.exists() else {}

    def ensure(self, texts) -> None:
        from .adjust import _key
        todo = list({_key(t): t for t in texts if _key(t) not in self.data}.items())
        if not todo:
            return
        import spacy
        nlp = spacy.load("en_core_web_sm", disable=["parser", "ner", "lemmatizer"])
        for (k, _), doc in zip(todo, nlp.pipe((t for _, t in todo), batch_size=64, n_process=4)):
            self.data[k] = " ".join(tok.pos_ for tok in doc if not tok.is_space)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_bytes(pickle.dumps(self.data))
        tmp.replace(self.path)

    def __getitem__(self, text: str) -> str:
        from .adjust import _key
        return self.data[_key(text)]


def _relative(own: float, others: np.ndarray, higher_is_closer: bool) -> list[float]:
    """own score, its z against the other authors, and its rank among all (1 = closest)."""
    mu, sd = float(others.mean()), float(others.std() + 1e-9)
    z = (own - mu) / sd
    better = (others > own).sum() if higher_is_closer else (others < own).sum()
    return [own, z if higher_is_closer else -z, float(better) / len(others)]


MAX_SAME_FIELD_PROBES = 12


def dominant_subfields(collection: str) -> dict:
    """author id -> dominant OpenAlex subfield of their screened candidates."""
    cand = json.loads((HERE / "candidates" / f"{collection}.json").read_text(encoding="utf-8"))
    return {a["author_id"]: max(a["subfields"], key=a["subfields"].get) if a.get("subfields") else None
            for a in cand["authors"]}


def _hosts(collection: str) -> dict:
    """author id -> set of URL hosts their manifest papers come from (journal / repository)."""
    from urllib.parse import urlparse
    from .loader import load_manifest
    out: dict = {}
    for p in load_manifest(collection).papers:
        out.setdefault(p.author_id, set()).add(urlparse(p.url).netloc.lower())
    return out


def column_names(channels=("char", "masked", "pos")) -> list[str]:
    """Name of every column of a row's signal vector, in order (used by the ablation)."""
    from original.constants import ALL_FEATURE_CODES
    names = ["orig:rms_self", "orig:rms_peer", "orig:contrast"]
    for k in channels:
        for part in ("centroid", "nearest"):
            names += [f"{k}:{part}:own", f"{k}:{part}:z", f"{k}:{part}:rank"]
    names += ["fw:centroid:own", "fw:centroid:z", "fw:centroid:rank"]
    names += [f"orig:zself:{c}" for c in ALL_FEATURE_CODES]
    names += [f"orig:zcontrast:{c}" for c in ALL_FEATURE_CODES]
    return names


def build_rows(collection: str, partition: str, char_vectorizer=None, fw_stats=None,
               length_match: bool = True, original_scores: bool = False):
    """Signal vectors for every new paper in every (configuration, seed) trial set.

    Probes come in two kinds: the loader's 5 random other authors (``random``), and up to 5
    other authors from the SAME dominant subfield (``same_field``), the harder and more
    realistic case because topic no longer gives the impostor away."""
    from sklearn.feature_extraction.text import TfidfVectorizer
    from original.quantum.null_pool import fit_impostor_gaussian
    from original.quantum.state import BaselineSample, StudentState

    reset_research_flags()
    check_partition(partition)
    sets = trial_sets(collection, partition)
    store = FeatureStore(collection)
    texts_needed = []
    for (name, _), ts in sets.items():
        new_w = dict((n, w) for n, _, w in CONFIGS)[name]
        for t in ts.trials:
            texts_needed += length_matched(t, new_w).baseline + t.honest + t.probes
    store.ensure(texts_needed)

    pos = PosTags(collection)
    pos.ensure(texts_needed)
    fit_here = char_vectorizer is None
    if fit_here:  # unsupervised fit on this partition's texts (no labels used)
        uniq = list({t: None for t in texts_needed})
        char_vectorizer = {
            "char": TfidfVectorizer(analyzer="char", ngram_range=(3, 5), sublinear_tf=True,
                                    min_df=3, max_features=60000, dtype=np.float32).fit(uniq),
            "masked": TfidfVectorizer(analyzer="char", ngram_range=(3, 6), sublinear_tf=True, min_df=3,
                                      max_features=60000, dtype=np.float32, preprocessor=mask_topic).fit(uniq),
        }
        char_vectorizer["pos"] = TfidfVectorizer(analyzer="word", ngram_range=(1, 3), sublinear_tf=True, min_df=3,
                                                 max_features=40000, dtype=np.float32, lowercase=False,
                                                 token_pattern=r"\S+").fit([pos[t] for t in uniq])
        fw = np.array([_fw_vector(t) for t in uniq])
        fw_stats = (fw.mean(0), fw.std(0) + 1e-6)

    rows = []
    for (name, seed), ts in sorted(sets.items()):
        new_w = dict((n, w) for n, _, w in CONFIGS)[name]
        trials = [length_matched(t, new_w) for t in ts.trials] if length_match else list(ts.trials)
        full = {t.student_id: t for t in ts.trials}   # un-cut baselines, for Original's own scores
        authors = [t.student_id for t in trials]
        a_index = {a: i for i, a in enumerate(authors)}
        # per-author baselines in every representation
        cents, fwc, vecs = {k: [] for k in char_vectorizer}, [], {}
        pieces = {k: [] for k in char_vectorizer}   # every baseline piece, author-contiguous
        starts = []                                  # first piece row of each author
        n_rows = 0
        for t in trials:
            starts.append(n_rows)
            n_rows += len(t.baseline)
            for k, vz in char_vectorizer.items():
                src_texts = [pos[b] for b in t.baseline] if k == "pos" else t.baseline
                X = vz.transform(src_texts)
                c = np.asarray(X.mean(axis=0)).ravel()
                cents[k].append(c / (np.linalg.norm(c) + 1e-12))
                Xd = np.asarray(X.todense())
                pieces[k].append(Xd / (np.linalg.norm(Xd, axis=1, keepdims=True) + 1e-12))
            fwc.append(np.mean([(_fw_vector(b) - fw_stats[0]) / fw_stats[1] for b in t.baseline], axis=0))
            vecs[t.student_id] = [store[b][0] for b in t.baseline]
        cents, fwc = {k: np.array(v) for k, v in cents.items()}, np.array(fwc)
        pieces = {k: np.vstack(v).astype(np.float32) for k, v in pieces.items()}
        starts = np.array(starts)
        states = {}
        for t in trials:
            s = StudentState(student_id=t.student_id)
            for b in t.baseline:
                s.add_sample(BaselineSample(text=b, vector=store[b][0], provenance="verified",
                                            auth_weight=1.0, genre="essay"))
            states[t.student_id] = s
        field = dominant_subfields(collection)
        honest_of = {t.student_id: t.honest[0] for t in trials}
        hosts = _hosts(collection)
        for t in trials:
            st = states[t.student_id]
            active = st.active_feature_mask
            mates = sorted((a for a in authors if a != t.student_id and field.get(a) and field.get(a) == field.get(t.student_id)),
                           key=lambda a: hashlib.sha256(f"{seed}:{t.student_id}>{a}".encode()).hexdigest())
            docs = ([(h, 0, None, "honest") for h in t.honest]
                    + [(p, 1, src, "random") for p, src in zip(t.probes, t.probe_sources)]
                    + [(honest_of[a], 1, a, "same_field") for a in mates[:MAX_SAME_FIELD_PROBES]])
            venue_mates = sorted((a for a in authors if a != t.student_id and hosts.get(a, set()) & hosts.get(t.student_id, set())),
                                 key=lambda a: hashlib.sha256(f"v{seed}:{t.student_id}>{a}".encode()).hexdigest())
            docs += [(honest_of[a], 1, a, "same_venue") for a in venue_mates[:MAX_SAME_FIELD_PROBES]]
            for j, (text, label, src, kind) in enumerate(docs):
                excluded = {t.student_id} | ({src} if src else set())
                others = [a for a in authors if a not in excluded]
                oi = [a_index[a] for a in others]
                mu_n, sd_n = fit_impostor_gaussian([v for a in others for v in vecs[a]])
                x = store[text][0]
                z_self = np.where(active, np.clip(np.abs((x - st.baseline_mean) / st.baseline_std), 0, Z_CAP), 0.0)
                z_peer = np.where(active, np.clip(np.abs((x - mu_n) / np.maximum(sd_n, 0.005)), 0, Z_CAP), 0.0)
                char_feats = []
                for k, vz in char_vectorizer.items():
                    dv = np.asarray(vz.transform([pos[text] if k == "pos" else text]).todense()).ravel()
                    dv = dv / (np.linalg.norm(dv) + 1e-12)
                    sims = cents[k] @ dv
                    char_feats += _relative(float(sims[a_index[t.student_id]]), sims[oi], True)
                    # nearest single piece of each author's past papers
                    nearest = np.maximum.reduceat(pieces[k] @ dv.astype(np.float32), starts)
                    char_feats += _relative(float(nearest[a_index[t.student_id]]), nearest[oi], True)
                fv = (_fw_vector(text) - fw_stats[0]) / fw_stats[1]
                dists = np.abs(fwc - fv).mean(axis=1)
                own_f = float(dists[a_index[t.student_id]])
                n_act = max(int(active.sum()), 1)
                summary = [float(np.sqrt((z_self ** 2).sum() / n_act)), float(np.sqrt((z_peer ** 2).sum() / n_act)),
                           float((z_self ** 2 - z_peer ** 2).sum() / n_act)]
                feat = np.concatenate([summary, char_feats, _relative(own_f, dists[oi], False),
                                       z_self, z_self - z_peer])
                row = {"author": t.student_id, "config": name, "seed": seed, "label": label,
                       "kind": kind, "src": src, "x": feat.astype(np.float32)}
                if original_scores:
                    row["original"] = _original_scores(full[t.student_id], full, others, text, store, new_w, st)
                rows.append(row)
    return rows, char_vectorizer, fw_stats


_FULL_STATES: dict = {}


def _original_scores(trial, full, others, text, store, new_w, lm_state) -> dict:
    """Original's own flags-off scores for one paper: deviation against the un-cut baseline,
    the LLR deviation against a peer pool of ``others`` (probe author already excluded), and
    deviation against the length-matched baseline. Validation only; no flag is set."""
    from original.quantum.null_pool import fit_impostor_gaussian
    from original.quantum.scoring import ScoringConfig
    from original.quantum.scoring import score as quantum_score
    from original.quantum.state import BaselineSample, StudentState
    key = (trial.student_id, tuple(trial.baseline_ids), new_w)
    st = _FULL_STATES.get(key)
    if st is None:
        st = StudentState(student_id=trial.student_id)
        for b in trial.baseline:
            st.add_sample(BaselineSample(text=b, vector=store[b][0], provenance="verified", auth_weight=1.0, genre="essay"))
        _FULL_STATES.clear()
        _FULL_STATES[key] = st
    vec, fd = store[text]
    pool = fit_impostor_gaussian([store[b][0] for a in others for b in full[a].baseline])
    off = quantum_score(state=st, submission_vector=vec, feature_dict=fd, submission_id="abl", n_tokens=new_w,
                        scoring_config=ScoringConfig())
    llr = quantum_score(state=st, submission_vector=vec, feature_dict=fd, submission_id="abl", n_tokens=new_w,
                        impostor_stats=pool, scoring_config=ScoringConfig(null_model="impostor"))
    lm = quantum_score(state=lm_state, submission_vector=vec, feature_dict=fd, submission_id="abl", n_tokens=new_w,
                       scoring_config=ScoringConfig())
    return {"dev_off": float(off.authorship.deviation_score),
            "llr_off": float(llr.authorship.llr_deviation_score) if llr.authorship.llr_deviation_score is not None else float(off.authorship.deviation_score),
            "dev_lm": float(lm.authorship.deviation_score)}


MODEL = "logistic"


def _model():
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler
    if MODEL == "boosted":
        from sklearn.ensemble import HistGradientBoostingClassifier
        return HistGradientBoostingClassifier(max_iter=300, learning_rate=0.05, max_leaf_nodes=15,
                                              l2_regularization=1.0, random_state=0)
    from sklearn.linear_model import LogisticRegression
    return make_pipeline(StandardScaler(), LogisticRegression(C=0.1, max_iter=2000, class_weight="balanced"))


def _per_author(rows, scores, kinds=("random", "same_field", "same_venue")):
    out = {}
    for r, s in zip(rows, scores):
        a = out.setdefault(r["author"], {"author": r["author"], "honest": [], "probe": []})
        if not r["label"]:
            a["honest"].append(float(s))
        elif r["kind"] in kinds:
            a["probe"].append(float(s))
    return [out[k] for k in sorted(out)]


def _fold_ok(r, fold: int) -> bool:
    """A row belongs to a fold only if its claimed author AND its probe's source author do."""
    return split_of(r["author"]) == fold and (r["src"] is None or split_of(r["src"]) == fold)


def _report(R, scores, n_boot):
    out = {}
    for label, kinds in (("random_probes", ("random",)), ("same_field_probes", ("same_field",)),
                         ("same_venue_probes", ("same_venue",))):
        pa = [a for a in _per_author(R, scores, kinds) if a["probe"] or a["honest"]]
        if sum(len(a["probe"]) for a in pa):
            out[label] = summarise(pa, n_boot)
    return out


def summarise(per_author, n_boot=1000) -> dict:
    from .adjust import bootstrap_catch
    from .baseline import _auc
    h = np.array([s for a in per_author for s in a["honest"]])
    p = np.array([s for a in per_author for s in a["probe"]])
    c = catch_at_rate(per_author)
    rng = np.random.default_rng(0)
    aucs = []
    for _ in range(n_boot):
        pick = [per_author[i] for i in rng.integers(0, len(per_author), len(per_author))]
        aucs.append(_auc(np.array([s for a in pick for s in a["honest"]]), np.array([s for a in pick for s in a["probe"]])))
    return {"catch_at_5pct_honest": round(c["catch"], 4), "catch_at_5pct_ci95": bootstrap_catch(per_author, n_boot=n_boot),
            "auc": round(_auc(h, p), 4), "auc_ci95": [round(float(np.quantile(aucs, q)), 4) for q in (0.025, 0.975)],
            "n_authors": len(per_author), "n_honest": int(h.size), "n_probe": int(p.size)}


POOL_CONFIGS = False


def _with_config(r):
    onehot = np.array([r["config"] == n for n, _, _ in CONFIGS], dtype=np.float32)
    return np.concatenate([r["x"], onehot])


def crossfit(collection: str, n_boot: int = 1000) -> dict:
    rows, _, _ = build_rows(collection, "development")
    if POOL_CONFIGS:
        return _crossfit_pooled(collection, rows, n_boot)
    out = {"collection": collection, "partition": "development", "date": time.strftime("%Y-%m-%d"),
           "method": "2-fold author-disjoint cross-fit; logistic regression per configuration", "configs": {}}
    for name, _, _ in CONFIGS:
        R = [r for r in rows if r["config"] == name and (_fold_ok(r, 0) or _fold_ok(r, 1))]
        scores = np.zeros(len(R))
        for fold in (0, 1):
            tr = [i for i, r in enumerate(R) if _fold_ok(r, 1 - fold)]
            te = [i for i, r in enumerate(R) if _fold_ok(r, fold)]
            m = _model().fit(np.stack([R[i]["x"] for i in tr]), [R[i]["label"] for i in tr])
            scores[te] = m.predict_proba(np.stack([R[i]["x"] for i in te]))[:, 1]
        out["configs"][name] = _report(R, scores, n_boot)
        print(collection, name, json.dumps(out["configs"][name]), flush=True)
    return out


def _crossfit_pooled(collection, rows, n_boot):
    """One model trained across the three configurations (configuration one-hot as input),
    still author-disjoint 2-fold; reported per configuration."""
    out = {"collection": collection, "partition": "development", "date": time.strftime("%Y-%m-%d"),
           "method": "2-fold author-disjoint cross-fit; one boosted model across configurations", "configs": {}}
    R = [r for r in rows if _fold_ok(r, 0) or _fold_ok(r, 1)]
    scores = np.zeros(len(R))
    for fold in (0, 1):
        tr = [i for i, r in enumerate(R) if _fold_ok(r, 1 - fold)]
        te = [i for i, r in enumerate(R) if _fold_ok(r, fold)]
        m = _model().fit(np.stack([_with_config(R[i]) for i in tr]), [R[i]["label"] for i in tr])
        scores[te] = m.predict_proba(np.stack([_with_config(R[i]) for i in te]))[:, 1]
    for name, _, _ in CONFIGS:
        idx = [i for i, r in enumerate(R) if r["config"] == name]
        out["configs"][name] = _report([R[i] for i in idx], scores[idx], n_boot)
        print(collection, name, json.dumps(out["configs"][name]), flush=True)
    return out


def freeze_and_check(collection: str, n_boot: int = 1000) -> dict:
    """Freeze the development-selected verifier (boosted, pooled across configurations) and
    score the calibration partition once.

    Threshold per configuration = 95th percentile of the development OUT-OF-FOLD honest scores
    (so it is set where the frozen pipeline would put it, without seeing calibration). The
    final model is trained on all development authors. Calibration is then scored unchanged."""
    from .intended_use import bootstrap_at
    dev_rows, vec, fw_stats = build_rows(collection, "development")
    cal_rows, _, _ = build_rows(collection, "calibration", char_vectorizer=vec, fw_stats=fw_stats)
    R = [r for r in dev_rows if _fold_ok(r, 0) or _fold_ok(r, 1)]
    oof = np.zeros(len(R))
    for fold in (0, 1):
        tr = [i for i, r in enumerate(R) if _fold_ok(r, 1 - fold)]
        te = [i for i, r in enumerate(R) if _fold_ok(r, fold)]
        m = _model().fit(np.stack([_with_config(R[i]) for i in tr]), [R[i]["label"] for i in tr])
        oof[te] = m.predict_proba(np.stack([_with_config(R[i]) for i in te]))[:, 1]
    final = _model().fit(np.stack([_with_config(r) for r in dev_rows]), [r["label"] for r in dev_rows])
    cal_scores = final.predict_proba(np.stack([_with_config(r) for r in cal_rows]))[:, 1]
    out = {"collection": collection, "date": time.strftime("%Y-%m-%d"), "model": MODEL, "pooled_configs": True,
           "rule": "threshold = 95th percentile of development out-of-fold honest scores per configuration; "
                   "final model trained on all development authors; calibration scored once, unchanged",
           "configs": {}}
    thresholds = {}
    for name, _, _ in CONFIGS:
        idx = [i for i, r in enumerate(R) if r["config"] == name]
        thr = catch_at_rate(_per_author([R[i] for i in idx], oof[idx]))["threshold"]
        thresholds[name] = round(float(thr), 6)
        cidx = [i for i, r in enumerate(cal_rows) if r["config"] == name]
        C, s = [cal_rows[i] for i in cidx], cal_scores[cidx]
        res = {"threshold_from_development": thresholds[name]}
        for label, kinds in (("random_probes", ("random",)), ("same_field_probes", ("same_field",)),
                             ("same_venue_probes", ("same_venue",))):
            pa = _per_author(C, s, kinds)
            h = np.array([v for a in pa for v in a["honest"]])
            p = np.array([v for a in pa for v in a["probe"]])
            if p.size:
                res[label] = {"at_frozen_threshold": {"honest_flag_rate": round(float((h > thr).mean()), 4),
                                                      "catch_rate": round(float((p > thr).mean()), 4),
                                                      "n_honest": int(h.size), "n_probe": int(p.size),
                                                      "ci95_author_bootstrap": bootstrap_at(pa, thr, n_boot)},
                              "rate_matched_5pct": summarise(pa, n_boot)}
        out["configs"][name] = res
        print(collection, name, json.dumps(res), flush=True)
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    (MODEL_DIR / f"{collection}_frozen.pkl").write_bytes(pickle.dumps({"model": final, "thresholds": thresholds}))
    out["thresholds"] = thresholds
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("step", choices=("crossfit", "freeze-and-check"))
    ap.add_argument("--collection", choices=("humanities", "science"), required=True)
    ap.add_argument("--n-boot", type=int, default=1000)
    ap.add_argument("--out", type=Path, default=None)
    ap.add_argument("--model", choices=("logistic", "boosted"), default="logistic")
    ap.add_argument("--pool-configs", action="store_true")
    a = ap.parse_args(argv)
    global MODEL, POOL_CONFIGS
    MODEL, POOL_CONFIGS = a.model, a.pool_configs
    res = crossfit(a.collection, a.n_boot) if a.step == "crossfit" else freeze_and_check(a.collection, a.n_boot)
    tag = "development_crossfit" if a.step == "crossfit" else "calibration_frozen"
    out = a.out or HERE / f"verifier_{a.collection}_{tag}_{res['date']}.json"
    out.write_text(json.dumps(res, indent=1) + "\n", encoding="utf-8")
    print("wrote", out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
