"""
Independent validation of GENRE_INVARIANT_WEIGHTS_ENABLED's tier attenuation.

The tier set (2, 3, 9, 10) was chosen from a tier-ablation on the
Lewis/Chesterton corpus. Re-testing on that same corpus would be circular.
This tests it on DIFFERENT data (the 10-author public_authors corpus) with
DIFFERENT genre labels (the production rule-based resolve_genre, not the
hand-assigned buckets the Lewis study used).

Design, per author A with multi-genre coverage:
  MISMATCH arm (where the attenuation is supposed to help):
    baseline   = A's chunks NOT in genre G
    genuine    = A's chunks in G          (genre never seen in baseline)
    impostor   = other authors' chunks
  MATCHED arm (control -- attenuation should NOT be applied here; measures
  what it would cost if the genre_covered gate were wrong):
    baseline   = 60% of A's chunks in G
    genuine    = 40% of A's chunks in G
    impostor   = other authors' chunks

Compares static tier weights vs the SAME vector with
GENRE_MISMATCH_ATTENUATE_TIERS scaled by ATTENUATE_FACTOR -- isolating the
one intervention from every other manifest directive.
"""
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_ROOT = _HERE.parent.parent
sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(_HERE))

import numpy as np
from sklearn.metrics import roc_auc_score

from original.constants import ALL_FEATURE_CODES, FEATURE_TIER, TIER_WEIGHTS
from original.context.resolvers import resolve_genre
from original.context.weighting import ATTENUATE_FACTOR, GENRE_MISMATCH_ATTENUATE_TIERS
from original.quantum.null_pool import fit_impostor_gaussian
from original.quantum.scoring import ScoringConfig, score
from original.quantum.state import BaselineSample, StudentState

import multi_author_extract as mae

HERE = Path(__file__).parent
MIN_CHUNKS_PER_GENRE = 8


def static_vector() -> np.ndarray:
    return np.array(
        [TIER_WEIGHTS.get(FEATURE_TIER[c], 1.0) for c in ALL_FEATURE_CODES], dtype=np.float64
    )


def attenuated_vector() -> np.ndarray:
    v = static_vector()
    for i, code in enumerate(ALL_FEATURE_CODES):
        if FEATURE_TIER.get(code) in GENRE_MISMATCH_ATTENUATE_TIERS:
            v[i] *= ATTENUATE_FACTOR
    return v


def rebuild_chunk_texts():
    """Re-run the exact chunking multi_author_extract used, to recover texts."""
    out = []
    for author_dir in sorted(mae.CORPUS.iterdir()):
        if not author_dir.is_dir() or author_dir.name in mae.EXCLUDE_AUTHORS:
            continue
        author = author_dir.name
        if author in mae.USE_CACHE:
            text = (author_dir / "_full_work_cache.txt").read_text(
                encoding="utf-8", errors="ignore"
            )
            text = text[int(len(text) * mae.USE_CACHE[author]) :]
            paras = mae.paragraphs_for(text)
        else:
            paras = []
            for f in sorted(author_dir.glob("*.txt")):
                rel = f"{author}/{f.name}"
                if f.name.startswith("_full_work_cache") or rel in mae.EXCLUDE_FILES:
                    continue
                paras.extend(mae.paragraphs_for(f.read_text(encoding="utf-8", errors="ignore")))
        chunks = mae.chunk_paragraphs(paras)
        keep = mae.evenly_spaced(len(chunks), mae.CAP_PER_AUTHOR)
        for j, k in enumerate(keep):
            out.append({"author": author, "chunk_id": f"{author}_{j:03d}", "text": chunks[k]})
    return out


def make_state(items, label):
    st = StudentState(student_id=label)
    for m, v in items:
        st.add_sample(
            BaselineSample(
                text="", vector=v, provenance="proctored", auth_weight=1.0,
                assignment=m["chunk_id"], genre=m.get("genre"),
            )
        )
    return st


def scores_for(state, items, weights, imp_stats):
    out = []
    for m, v in items:
        fdict = {c: float(x) for c, x in zip(ALL_FEATURE_CODES, v)}
        r = score(
            state, v, fdict, submission_id=m["chunk_id"], n_tokens=m["word_count"],
            adaptive_weights=weights, impostor_stats=imp_stats,
            scoring_config=ScoringConfig(null_model="impostor"),
        )
        out.append(r.authorship.llr_deviation_score)
    return out


def auc(g, i):
    return roc_auc_score([0] * len(g) + [1] * len(i), g + i)


def main():
    vectors = np.load(HERE / "pa_vectors.npy")
    meta = json.loads((HERE / "pa_meta.json").read_text())

    print("Recovering chunk texts and running production resolve_genre...", flush=True)
    texts = rebuild_chunk_texts()
    assert len(texts) == len(meta), f"chunk mismatch: {len(texts)} vs {len(meta)}"
    for t, m in zip(texts, meta):
        assert t["chunk_id"] == m["chunk_id"], f"order mismatch: {t['chunk_id']} vs {m['chunk_id']}"

    for n, (t, m) in enumerate(zip(texts, meta)):
        m["genre"] = resolve_genre(t["text"]).get("primary")
        if (n + 1) % 50 == 0:
            print(f"  classified {n+1}/{len(meta)}", flush=True)

    items = [(m, vectors[i]) for i, m in enumerate(meta)]

    print("\n=== Genre distribution per author (production resolve_genre) ===")
    by_author = defaultdict(list)
    for it in items:
        by_author[it[0]["author"]].append(it)
    multi_genre = {}
    for a, its in sorted(by_author.items()):
        c = Counter(x[0]["genre"] for x in its)
        print(f"  {a:12s} {dict(c)}")
        usable = [g for g, n in c.items() if n >= MIN_CHUNKS_PER_GENRE]
        if len(usable) >= 2:
            multi_genre[a] = usable

    if not multi_genre:
        print(f"\nNo author has 2+ genres with >= {MIN_CHUNKS_PER_GENRE} chunks — "
              "cannot run a leave-one-genre-out test on this corpus.")
        return

    print(f"\nMulti-genre authors usable for the test: "
          f"{ {a: v for a, v in multi_genre.items()} }\n")

    w_static = static_vector()
    w_atten = attenuated_vector()

    print(f"{'author':12s} {'held-out genre':22s} {'arm':9s} {'n_gen':>5s} "
          f"{'static':>8s} {'attenuated':>11s} {'delta':>8s}")
    mismatch_deltas, matched_deltas = [], []

    for a, genres in multi_genre.items():
        others = [it for b, its in by_author.items() if b != a for it in its]
        pool = [v for b, its in by_author.items() if b != a for _, v in its]
        imp_stats = fit_impostor_gaussian(pool)

        for g in genres:
            in_g = [it for it in by_author[a] if it[0]["genre"] == g]
            not_g = [it for it in by_author[a] if it[0]["genre"] != g]
            if len(not_g) < 3 or len(in_g) < MIN_CHUNKS_PER_GENRE:
                continue

            # MISMATCH arm — baseline has never seen genre g
            st = make_state(not_g, f"{a}_mismatch_{g}")
            s_auc = auc(scores_for(st, in_g, w_static, imp_stats),
                        scores_for(st, others, w_static, imp_stats))
            a_auc = auc(scores_for(st, in_g, w_atten, imp_stats),
                        scores_for(st, others, w_atten, imp_stats))
            mismatch_deltas.append(a_auc - s_auc)
            print(f"{a:12s} {g:22s} {'MISMATCH':9s} {len(in_g):5d} "
                  f"{s_auc:8.4f} {a_auc:11.4f} {a_auc - s_auc:+8.4f}", flush=True)

            # MATCHED arm — control
            split = max(3, int(len(in_g) * 0.6))
            base_m, test_m = in_g[:split], in_g[split:]
            if len(test_m) < 3:
                continue
            st_m = make_state(base_m, f"{a}_matched_{g}")
            s_auc_m = auc(scores_for(st_m, test_m, w_static, imp_stats),
                          scores_for(st_m, others, w_static, imp_stats))
            a_auc_m = auc(scores_for(st_m, test_m, w_atten, imp_stats),
                          scores_for(st_m, others, w_atten, imp_stats))
            matched_deltas.append(a_auc_m - s_auc_m)
            print(f"{a:12s} {g:22s} {'matched':9s} {len(test_m):5d} "
                  f"{s_auc_m:8.4f} {a_auc_m:11.4f} {a_auc_m - s_auc_m:+8.4f}", flush=True)

    print("\n=== Summary ===")
    if mismatch_deltas:
        print(f"MISMATCH arm (attenuation is APPLIED here): mean delta "
              f"{np.mean(mismatch_deltas):+.4f} over {len(mismatch_deltas)} folds; "
              f"helped in {sum(1 for d in mismatch_deltas if d > 0)}/{len(mismatch_deltas)}")
    if matched_deltas:
        print(f"MATCHED arm  (attenuation is GATED OFF here): mean delta "
              f"{np.mean(matched_deltas):+.4f} over {len(matched_deltas)} folds; "
              f"would have helped in {sum(1 for d in matched_deltas if d > 0)}/{len(matched_deltas)}")
    print("\nPositive MISMATCH delta = the attenuation helps where it fires.")
    print("Negative MATCHED delta   = gating it off for covered genres was correct.")


if __name__ == "__main__":
    main()
