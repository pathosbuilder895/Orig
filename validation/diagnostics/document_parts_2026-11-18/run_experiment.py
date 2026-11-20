"""Document parts experiment (ADR-015). How much does a cover letter, a title block or a bibliography move a genuine paper's
score? Same author, same four past papers, the fifth paper scored plain and with
front/back matter added. In-process TestClient on the demo app, pilot-like flags."""
import json, os, sys, glob, statistics
from pathlib import Path
sys.modules["sentence_transformers"] = None  # the pilot lockfile has no sentence-transformers: Tier 10 and the tension arc use their fallbacks, as live
os.environ["ORIGINAL_DB"] = ":memory:"
for k in ("CONTEXT_MANIFEST_ENABLED", "ADAPTIVE_WEIGHTS_ENABLED"):
    os.environ[k] = "0"
os.environ["NULL_MODEL"] = "none"
os.environ["DRIFT_GATE"] = "advisory"
ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
import run as R
from fastapi.testclient import TestClient
c = TestClient(R.load_legacy_demo_app())

COVER = """Dear Professor Hartley,

Please find attached my paper for the third assignment of the semester. I chose this
topic because it connects with what we discussed in seminar two weeks ago, and I hope
the argument is clearer than in my last draft. I would be grateful for any comments you
have on the second section in particular, which I found difficult to organise.

Thank you for your patience with the late submission; I was unwell for most of last week.

Sincerely,
Jordan Reyes
"""
TITLE = """Jordan Reyes
Professor Hartley
PHIL 210: Moral and Political Philosophy
14 March 2026

"""
BIB = """

Works Cited

Arendt, Hannah. The Human Condition. 2nd ed., University of Chicago Press, 1998.
Berlin, Isaiah. "Two Concepts of Liberty." Four Essays on Liberty, Oxford UP, 1969, pp. 118-72.
Gray, John. Mill on Liberty: A Defence. 2nd ed., Routledge, 1996.
Hobbes, Thomas. Leviathan. Edited by Richard Tuck, Cambridge UP, 1996.
Kant, Immanuel. Groundwork of the Metaphysics of Morals. Translated by Mary Gregor, Cambridge UP, 1998.
Locke, John. Two Treatises of Government. Edited by Peter Laslett, Cambridge UP, 1988.
Mill, John Stuart. On Liberty. Edited by Elizabeth Rapaport, Hackett, 1978.
Nussbaum, Martha C. Creating Capabilities. Belknap Press of Harvard UP, 2011.
Rawls, John. A Theory of Justice. Revised ed., Belknap Press of Harvard UP, 1999.
Riley, Jonathan. Routledge Philosophy Guidebook to Mill on Liberty. Routledge, 1998.
Sandel, Michael J. Liberalism and the Limits of Justice. 2nd ed., Cambridge UP, 1998.
Skorupski, John. Why Read Mill Today? Routledge, 2006.
Taylor, Charles. Sources of the Self. Harvard UP, 1989.
Williams, Bernard. Ethics and the Limits of Philosophy. Harvard UP, 1985.
"""
FOOT = """

Notes

1. See Berlin 131 for the distinction between negative and positive liberty.
2. Gray argues the opposite reading; compare Riley 44-47.
3. Rawls, Theory of Justice, sec. 32.
4. All quotations from On Liberty follow the Hackett edition.
"""
VARIANTS_A = {
    "plain": lambda t: t,
    "title block": lambda t: TITLE + t,
    "cover letter": lambda t: COVER + "\n\n" + t,
    "bibliography": lambda t: t + BIB,
    "notes + bibliography": lambda t: t + FOOT + BIB,
    "all front and back matter": lambda t: COVER + "\n\n" + TITLE + t + FOOT + BIB,
}

BIB_COLON = BIB.replace("\n\nWorks Cited\n", "\n\nWorks Cited:\n")
BIB_APA = """

## References

Berlin, I. (1969). Two concepts of liberty. In Four essays on liberty (pp. 118-172). Oxford University Press.
Gray, J. (1996). Mill on liberty: A defence (2nd ed.). Routledge.
Nussbaum, M. C. (2011). Creating capabilities. Belknap Press.
Rawls, J. (1999). A theory of justice (Rev. ed.). Belknap Press.
Riley, J. (1998). Routledge philosophy guidebook to Mill on liberty. Routledge.
Skorupski, J. (2006). Why read Mill today? Routledge.
Taylor, C. (1989). Sources of the self. Harvard University Press.
Williams, B. (1985). Ethics and the limits of philosophy. Harvard University Press.
"""
SHORT = lambda t: t[:2600]
VARIANTS_B = {
    "plain": lambda t: t,
    "bibliography 'Works Cited:'": lambda t: t + BIB_COLON,
    "bibliography '## References' (APA)": lambda t: t + BIB_APA,
    "short plain": SHORT,
    "short + cover letter": lambda t: COVER + "\n\n" + SHORT(t),
    "short + title + 'Works Cited:'": lambda t: TITLE + SHORT(t) + BIB_COLON,
}

CORPUS = str(ROOT / "validation" / "public_authors" / "corpus")
authors = [a for a in sorted(os.listdir(CORPUS)) if len(glob.glob(f"{CORPUS}/{a}/*part_0*.txt")) >= 5]
SET = os.environ.get("FB_SET", "A")
VARIANTS = VARIANTS_A if SET == "A" else VARIANTS_B
W, NW = int(os.environ.get("FB_WORKER", "0")), int(os.environ.get("FB_WORKERS", "1"))
authors = authors[W::NW]
rows = []
for a in authors:
    files = sorted(glob.glob(f"{CORPUS}/{a}/*part_0*.txt"))[:5]
    texts = [open(f, encoding="utf-8", errors="replace").read()[:9000] for f in files]
    base, probe = texts[:4], texts[4]
    for vname, fn in VARIANTS.items():
        sid = f"demo:fb{SET}_{a}_{list(VARIANTS).index(vname)}"
        for i, t in enumerate(base):
            r = c.post(f"/students/{sid}/baseline", json={"text": t, "provenance": "verified", "submitted_at": f"2026-01-{i+1:02d}"})
            assert r.status_code == 200, (r.status_code, r.text[:200])
        r = c.post(f"/students/{sid}/score", json={"text": fn(probe), "submission_id": f"{a}-{list(VARIANTS).index(vname)}"})
        assert r.status_code == 200, (r.status_code, r.text[:300])
        d = r.json()
        rows.append({"author": a, "variant": vname, "deviation": d["authorship"]["deviation_score"],
                     "action": d["recommendation"]["action"],
                     "top": [f["code"] for f in d["interference"]["destructive_features"]],
                     "fv": d["feature_vector"],
                     "measured_share": (d.get("evidence") or {}).get("measured", {}).get("share") if isinstance(d.get("evidence"), dict) else None,
                     "set_aside": [s.get("text", "")[:60] for s in ((d.get("evidence") or {}).get("measured", {}) or {}).get("set_aside", [])] if isinstance(d.get("evidence"), dict) else None})
    print(a, "done", flush=True)
json.dump(rows, open(Path(__file__).with_name(f"rows_{SET}_{W}.json"), "w"))
