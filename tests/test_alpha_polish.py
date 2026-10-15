"""The alpha journey's polish (2026-10-15), checked from the files a deploy serves.

- No page a teacher or student can open on a real deploy uses the banned
  wording: "AI detection", "cheating", "authorship verification",
  "fingerprint", or accuracy claims. The check reads each page's visible text
  (markup, scripts and comments stripped) and the committed Collections bundle.
- The Original reference-papers page's minimum (Live.referenceStatus in
  demo/original/live.js): 3 papers and 300 words in all, below which a
  reading is inconclusive. Run for real under node.
- The roster loader carries each student's word total (Live.roster's
  ``words``), which the reference-papers page counts against that minimum.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
DEMO = ROOT / "demo"
LIVE_JS = DEMO / "original" / "live.js"

needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")

# Pages served on a real deploy (original/api.py gates the demo-only ones).
SERVED_PAGES = sorted(
    {
        DEMO / "index.html",
        DEMO / "landing.html",
        DEMO / "bluebook" / "index.html",
        DEMO / "bluebook" / "parked.html",
        DEMO / "_components" / "explainer.html",
        *(DEMO / "original").glob("*.html"),
        *(DEMO / "legal").glob("*.html"),
    }
)

BANNED = [
    re.compile(r"\bai[- ]detect", re.I),
    re.compile(r"\bcheat", re.I),
    re.compile(r"authorship verification", re.I),
    re.compile(r"fingerprint", re.I),
    re.compile(r"\baccura(te|cy)\b", re.I),
]


def _visible(html: str) -> str:
    html = re.sub(r"<!--[\s\S]*?-->", " ", html)
    html = re.sub(r"<(script|style)\b[\s\S]*?</\1>", " ", html, flags=re.I)
    html = re.sub(r"<[^>]+>", " ", html)
    return re.sub(r"\s+", " ", html)


@pytest.mark.parametrize("page", SERVED_PAGES, ids=lambda p: str(p.relative_to(DEMO)))
def test_no_served_page_uses_banned_wording(page: Path):
    text = _visible(page.read_text(encoding="utf-8"))
    found = [m.group(0) for rx in BANNED for m in rx.finditer(text)]
    assert not found, f"{page.relative_to(ROOT)} says {found}"


def test_the_collections_bundle_carries_no_banned_wording():
    bundle = (DEMO / "bluebook" / "bluebook.bundle.js").read_text(encoding="utf-8")
    for phrase in ("AI detection", "authorship verification", "Authorship Verification", "cheating", "fingerprint", "Fingerprint"):
        assert phrase not in bundle, phrase


def test_the_sign_in_page_states_no_feature_count_and_names_no_verification():
    page = (DEMO / "index.html").read_text(encoding="utf-8")
    text = _visible(page)
    assert "Writing consistency · in testing" in text
    assert "Authorship Verification" not in text
    assert not re.search(r"\b10[39]\b", text), "a feature count is not a figure the code supports (NORTH_STAR rule 2)"
    # Off the demo the illustrative panel and badges are hidden with the role pills.
    assert "['demoDivider', 'demoLabel', 'demoRolePills', 'demoVisual', 'trustBadges']" in page


def test_the_explainer_states_no_feature_count():
    text = _visible((DEMO / "_components" / "explainer.html").read_text(encoding="utf-8"))
    assert not re.search(r"\b10[39] stylometric features\b", text)
    assert "seventeen tiers" not in text


# ── The reference-papers minimum ─────────────────────────────────────────────

LIVE_RUN = r"""
const fs = require('fs');
const sc = JSON.parse(fs.readFileSync(0, 'utf8'));
const src = fs.readFileSync(sc.live, 'utf8');
const noop = () => {};
const el = () => ({ addEventListener: noop, classList: { toggle: noop, add: noop, remove: noop }, querySelector: () => null });
const document = { readyState: 'complete', querySelectorAll: () => [], querySelector: () => null, getElementById: el, addEventListener: noop, createElement: el };
const window = { localStorage: { getItem: () => null }, sessionStorage: { getItem: () => null }, location: { replace: noop }, addEventListener: noop };
new Function('window', 'document', src)(window, document);
const out = sc.cases.map(([p, w]) => window.Live.referenceStatus(p, w));
out.push({ words: sc.readiness.map(d => window.Live.referenceWords(d)) });
out.push({ rule: window.Live.REFERENCE_MINIMUM });
process.stdout.write(JSON.stringify(out));
"""


def _live(cases, readiness):
    run = subprocess.run(
        [shutil.which("node"), "-e", LIVE_RUN],
        input=json.dumps({"live": str(LIVE_JS), "cases": cases, "readiness": readiness}),
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert run.returncode == 0, run.stderr
    return json.loads(run.stdout)


@needs_node
def test_reference_minimum_is_three_papers_and_three_hundred_words():
    cases = [[0, 0], [2, 269], [3, 250], [3, 300], [5, 1200], [2, None], [3, None], [None, None]]
    readiness = [
        {"sample_count": 2, "word_stats": {"mean": 134.5}},
        {"sample_count": 0, "word_stats": None},
        {"sample_count": 3},
        {},
    ]
    *statuses, words, rule = _live(cases, readiness)
    none, below, few_words, met, plenty, papers_short_words_unknown, words_unknown, unknown = statuses

    assert rule["rule"] == "at least 3 papers and 300 words in all"
    assert none["met"] is False and none["short"] == "No papers yet"
    assert none["text"] == "No reference papers yet. Add at least 3 papers and 300 words in all."

    assert below["met"] is False and below["tone"] == "warn"
    assert below["need"] == "Needs 1 more paper and at least 31 more words."
    assert below["text"].startswith("2 papers, 269 words. Below the minimum")
    assert "inconclusive" in below["text"]

    assert few_words["met"] is False and few_words["need"] == "Needs at least 50 more words."
    assert met["met"] is True and met["short"] == "Meets the minimum"
    assert plenty["met"] is True
    assert papers_short_words_unknown["met"] is False and papers_short_words_unknown["need"] == "Needs 1 more paper."
    assert words_unknown["met"] is None and words_unknown["short"] == "Words not known"
    assert unknown["met"] is None and unknown["short"] == "Not known"

    # Words are the readiness answer's mean over its papers; 0 for none; null when not said.
    assert words["words"] == [269, 0, None, None]


@needs_node
def test_the_roster_carries_each_students_word_total():
    # Run through the roster harness the suite's own tests use.
    from tests.test_original_suite_static import _roster

    out = _roster(
        students=[200, {"students": ["a", "b"], "roster": None}],
        readiness={
            "a": [200, {"verdict": "developing", "authenticated_count": 2, "sample_count": 2, "word_stats": {"mean": 150.0}}],
            "b": [200, {"verdict": "insufficient", "authenticated_count": 0, "sample_count": 0, "word_stats": None}],
        },
    )
    by_id = {s["id"]: s for s in out["result"]["students"]}
    assert by_id["a"]["samples"] == 2 and by_id["a"]["words"] == 300
    assert by_id["b"]["samples"] == 0 and by_id["b"]["words"] == 0


def test_the_reference_page_shows_the_minimum_per_student_and_for_one_student():
    page = (DEMO / "original" / "baseline.html").read_text(encoding="utf-8")
    # No student chosen: a table of every student's papers, words and standing.
    assert 'id="ref-overview"' in page and "renderOverview(list);" in page
    assert "Live.referenceStatus(s.samples,s.words)" in page
    # One student: a row in the stats card and a note above the add-writing forms.
    assert 'id="s-min"' in page and 'id="add-min"' in page
    assert "Minimum for a reading" in page
