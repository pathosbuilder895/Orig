"""The fictional demo is published from an allowlist, never the whole demo/ tree.

The navy suite (demo/prototypes/navy/) is a cleaned copy of a Claude Design
handoff. These tests hold the NORTH_STAR rules it was cleaned to, so the
removed claims cannot drift back in with a later design refresh."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

from original.constants import (
    ALL_FEATURE_CODES,
    DISABLED_FEATURE_GROUPS,
    FEATURE_GROUPS,
    FEATURE_TIER,
)

ROOT = Path(__file__).resolve().parents[1]
SUITE = ROOT / "demo/prototypes/navy"
SUITE_TEXT = sorted(p for p in SUITE.rglob("*") if p.suffix in {".html", ".css", ".js"})
SUITE_PAGES = sorted(SUITE.glob("*.html"))

# Pages that show an Original result to a teacher or a student (rule 10).
ORIGINAL_RESULT_PAGES = {
    "original-dashboard.html",
    "original-students.html",
    "original-review.html",
    "original-quantum.html",
    "original-flagged.html",
    "original-baseline-voice.html",
    "original-reports.html",
    "original-bluebook-teacher.html",
    "original-voice.html",
    "original-my-work.html",
    "original-bluebook-student.html",
}

# Claims the handoff made that NORTH_STAR rules out, and handoff leftovers.
REMOVED = {
    r"(?i)typing rhythm": "rule 6: no keystroke data",
    r"(?i)keystroke": "rule 6: no keystroke data",
    r"Behavioral Biometrics|tier17|\bTyping\b": "rule 6: Tier 17 is not shown",
    r"\b103\b|17 tiers": "the product has 109 features, 97 active",
    r"\bAI\b|generated prose|\bauthentic\b|to fake": "rule 2: no AI-authorship labels",
    r"always scores near|vouch": "rule 2: unsupported accuracy claim",
    r"[Ee]scalat|Integrity Operations": "rule 1: decision support, not a verdict",
    r"% alike|'alike'": "not doing now: writer-similarity percentages",
    r"banked|BLW-": "sealing never adds to a baseline; no join codes",
    r"sbts|original\.edu": "real institution or invented domain",
    r"googleapis|gstatic|JetBrains": "rule 7: self-hosted fonts only",
    r"original-features\.html|review-manuscript": "page not in the suite",
    r"fetch\(|apiFetch|XMLHttpRequest|sendBeacon|WebSocket": "fictional demo: no API calls",
}

LINK_PATTERNS = (
    r'(?:href|src)="([^"#?:]+)',
    r"url\(['\"]?([^'\")]+)",
    r"(original-[a-z-]+\.html)",
)


def _build(tmp_path: Path) -> Path:
    out = tmp_path / "site"
    subprocess.run(
        ["bash", str(ROOT / "scripts/build_teacher_demo_site.sh"), str(out)], check=True, cwd=ROOT
    )
    return out


def test_build_publishes_only_the_demo_allowlist(tmp_path):
    out = _build(tmp_path)
    files = {p.relative_to(out).as_posix() for p in out.rglob("*") if p.is_file()}
    top = {f for f in files if not f.startswith(("assets/fonts/", "prototypes/navy/"))}
    assert top == {
        "index.html",
        "bluebook/teacher-demo.html",
        "bluebook/teacher-demo.bundle.js",
        "bluebook/teacher-demo.bundle.css",
        "bluebook/fonts.css",
        "assets/codrington-library.jpeg",
    }
    suite = {f for f in files if f.startswith("prototypes/navy/")}
    expected = {
        "prototypes/navy/" + p.relative_to(SUITE).as_posix()
        for p in SUITE.rglob("*")
        if p.is_file()
    }
    assert suite == expected
    assert any(f.endswith(".woff2") for f in files)
    assert any(f.endswith("LICENSE.txt") for f in files)
    assert not any(f.endswith((".db", ".py", ".map")) for f in files)
    assert "prototypes/navy/index.html" in (out / "index.html").read_text()
    assert "../../bluebook/teacher-demo.html" in (SUITE / "index.html").read_text()


def test_every_suite_link_resolves_on_the_published_site(tmp_path):
    out = _build(tmp_path)
    missing = []
    for page in sorted((out / "prototypes/navy").rglob("*")):
        if page.suffix not in {".html", ".css", ".js"}:
            continue
        text = page.read_text()
        refs = {r for pat in LINK_PATTERNS for r in re.findall(pat, text)}
        for ref in refs:
            if "'+" in ref or ref.startswith(("#", "http", "data:", "mailto:")):
                continue  # built at runtime in JS, an in-page SVG id, or not a file
            if not (page.parent / ref).resolve().is_file():
                missing.append(f"{page.relative_to(out)} -> {ref}")
    assert not missing, missing


def test_demo_page_references_no_third_party_hosts():
    for name in ("teacher-demo.html", "teacher-demo.bundle.css", "fonts.css"):
        text = (ROOT / "demo/bluebook" / name).read_text()
        assert "googleapis" not in text and "gstatic" not in text, name
    for path in SUITE_TEXT:
        text = path.read_text()
        assert "googleapis" not in text and "gstatic" not in text, path.name
        assert not re.search(r"(?:src|href)=\"https?://", text), path.name


@pytest.mark.parametrize("page", SUITE_PAGES, ids=lambda p: p.name)
def test_every_suite_page_is_labelled_fictional(page):
    text = page.read_text()
    assert '<div class="demo-ribbon"' in text
    assert "Fictional demonstration" in text
    assert "every person, class, paper and number here is invented" in text
    assert 'href="demo.css"' in text and 'href="fonts.css"' in text


@pytest.mark.parametrize("name", sorted(ORIGINAL_RESULT_PAGES))
def test_original_results_carry_the_testing_phase_notice(name):
    text = (SUITE / name).read_text()
    assert 'class="demo-testing' in text
    assert "Original is not yet validated on real student writing" in text


def test_student_pages_say_sealed_work_may_become_reference_writing():
    for name in ("original-voice.html", "original-my-work.html", "original-bluebook-student.html"):
        text = (SUITE / name).read_text()
        assert "may approve your sealed Bluebook work as reference writing" in text, name
        assert "can undo that approval" in text, name


@pytest.mark.parametrize("pattern,reason", sorted(REMOVED.items()))
def test_removed_claims_stay_removed(pattern, reason):
    hits = [
        f"{p.relative_to(SUITE)}: {m.group(0)!r}"
        for p in SUITE_TEXT
        for m in re.finditer(pattern, p.read_text())
    ]
    assert not hits, f"{reason}: {hits}"


def test_every_suite_image_is_credited():
    credits = (SUITE / "assets/CREDITS.md").read_text()
    credited = credits.split("## Credited", 1)[1].split("\n## ", 1)[0]
    rows = {}
    for line in credited.splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) >= 3 and cells[0].startswith("`"):
            rows[cells[0].strip("`")] = cells
    for image in (SUITE / "assets").iterdir():
        if image.name == "CREDITS.md":
            continue
        assert image.name in rows, f"{image.name} has no row under '## Credited'"
        _, source, licence = rows[image.name][:3]
        assert source and licence, f"{image.name} needs a source and a licence"


def _registry_tier_names() -> dict[int, str]:
    text = (ROOT / "demo/prototypes/feature-registry.generated.js").read_text()
    block = text.split("export const TIER_META", 1)[1].split("});", 1)[0]
    return {int(k): v for k, v in re.findall(r'"(\d+)": "([^"]+)"', block)}


def test_feature_cards_are_exactly_the_active_features():
    text = (SUITE / "js/feature-data.js").read_text()
    tiers_src = text.split("const TIERS = [", 1)[1].split("\n  ];", 1)[0]
    disabled = {c for g in DISABLED_FEATURE_GROUPS for c in FEATURE_GROUPS[g]}
    active = [c for c in ALL_FEATURE_CODES if c not in disabled]
    names = _registry_tier_names()
    seen = []
    for chunk in tiers_src.split("{ key:'")[1:]:
        key = chunk.split("'", 1)[0]
        tier = 0 if key == "tiercomp" else int(key.removeprefix("tier"))
        name = re.search(r"name:'([^']*)'", chunk).group(1)
        assert name == names[tier], f"{key}: {name!r} != {names[tier]!r}"
        for code in re.findall(r"\['([a-z0-9_]+)','", chunk):
            assert FEATURE_TIER[code] == tier, f"{code}: tier {FEATURE_TIER[code]}, shown in {key}"
            seen.append(code)
    assert sorted(seen) == sorted(active)
    assert len(seen) == len(set(seen))
