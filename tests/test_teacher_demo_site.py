"""The fictional demo is published from an allowlist, never the whole demo/ tree."""

from __future__ import annotations

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_build_publishes_only_the_demo_allowlist(tmp_path):
    out = tmp_path / "site"
    subprocess.run(
        ["bash", str(ROOT / "scripts/build_teacher_demo_site.sh"), str(out)], check=True, cwd=ROOT
    )
    files = {p.relative_to(out).as_posix() for p in out.rglob("*") if p.is_file()}
    top = {f for f in files if not f.startswith("assets/fonts/")}
    assert top == {
        "index.html",
        "bluebook/teacher-demo.html",
        "bluebook/teacher-demo.bundle.js",
        "bluebook/teacher-demo.bundle.css",
        "bluebook/fonts.css",
        "assets/codrington-library.jpeg",
    }
    assert any(f.endswith(".woff2") for f in files)
    assert any(f.endswith("LICENSE.txt") for f in files)
    assert not any(f.endswith((".db", ".py", ".map")) for f in files)
    assert "bluebook/teacher-demo.html" in (out / "index.html").read_text()


def test_demo_page_references_no_third_party_hosts():
    for name in ("teacher-demo.html", "teacher-demo.bundle.css", "fonts.css"):
        text = (ROOT / "demo/bluebook" / name).read_text()
        assert "googleapis" not in text and "gstatic" not in text, name
