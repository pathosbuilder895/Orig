"""Copy priority fixes (Oct 2026): banned landing wording, Collections naming,
and the writing-consistency toggle defaulting off."""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LANDING = (ROOT / "demo" / "landing.html").read_text(encoding="utf-8")


def _visible(html: str) -> str:
    html = re.sub(r"<!--.*?-->", " ", html, flags=re.S)
    html = re.sub(r"<(script|style)\b.*?</\1>", " ", html, flags=re.S | re.I)
    return re.sub(r"<[^>]+>", " ", html)


def test_landing_has_no_banned_wording():
    text = _visible(LANDING).lower()
    for banned in ("ai detector", "fingerprint", "lie detector", "cheating", "probability of"):
        assert banned not in text, banned


def test_landing_uses_collections_anchor_and_path():
    assert 'id="collections"' in LANDING
    assert "#bluebook" not in LANDING and 'id="bluebook"' not in LANDING
    assert "03b Bluebook" not in LANDING
    assert 'href="collections/"' in LANDING and 'href="bluebook/"' not in LANDING


def test_writing_consistency_toggle_defaults_off():
    src = (ROOT / "demo" / "bluebook" / "NewExam.jsx").read_text(encoding="utf-8")
    assert re.search(r"\[aiDetect,\s+setAiDetect\]\s+=\s+useNEState\(false\)", src)
    assert 'label="Writing consistency (in testing)"' in src
    assert "Authorship comparison" not in src
    exam = (ROOT / "demo" / "bluebook" / "Exam.jsx").read_text(encoding="utf-8")
    assert re.search(r"aiDetect:\s+false,", exam)
    assert "withOriginal && cfg.aiDetect && seal.aiScore === undefined" in exam
