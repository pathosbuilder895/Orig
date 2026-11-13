"""Export the frozen rule D vectorizers (pre-registered study scholarly-rule-d-2026-11-12) to
the plain-JSON artifact ``original/data/rule_d_vectorizer_v1.json.gz`` read by
``original/rule_d/textprofile.py``, so the live app needs no pickle and no scikit-learn.

Provenance: the vectorizers were fit once on the development partition of the scholarly
corpus (``validation/scholarly/rule_d.py`` on the PR #336 branch) and frozen; the locked test
refused to run unless their pickle hash matched. Only n-gram strings and IDF weights are
exported, no paper text. Run from a checkout where ``validation.scholarly.verifier`` imports
(the PR #336 branch), with the frozen pickle path:

    python scripts/export_rule_d_vectorizer.py PATH/rule_d_vectorizers_humanities.pkl
"""
from __future__ import annotations

import gzip
import hashlib
import json
import pickle
import sys
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "original" / "data" / "rule_d_vectorizer_v1.json.gz"


def export(pkl: Path, out: Path = OUT) -> dict:
    raw = pkl.read_bytes()
    vecs = pickle.loads(raw)
    spec = {"version": 1, "study_id": "scholarly-rule-d-2026-11-12", "collection": "humanities",
            "frozen_pickle_sha256": hashlib.sha256(raw).hexdigest(),
            "note": "n-gram vocabularies and IDF weights only; no paper text",
            "vectorizers": {}}
    for name, vz in vecs.items():
        inv = sorted(vz.vocabulary_.items(), key=lambda kv: kv[1])
        assert [i for _, i in inv] == list(range(len(inv)))
        spec["vectorizers"][name] = {
            "ngram_range": list(vz.ngram_range), "lowercase": bool(vz.lowercase and vz.preprocessor is None),
            "masked": vz.preprocessor is not None, "vocabulary": [g for g, _ in inv],
            "idf": [float(x) for x in vz.idf_]}
    with gzip.open(out, "wt", encoding="utf-8") as f:
        json.dump(spec, f, separators=(",", ":"))
    return spec


if __name__ == "__main__":
    s = export(Path(sys.argv[1]))
    print("wrote", OUT, s["frozen_pickle_sha256"])
