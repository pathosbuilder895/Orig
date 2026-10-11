"""Static guards on Bluebook screens and on the CI check that keeps the bundles honest.

The behaviour itself is asserted in the professor-journey e2e (a graded exam is
"reviewed"); these keep the sources and the workflow from drifting back.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BLUEBOOK = ROOT / "demo" / "bluebook"
WORKFLOW = ROOT / ".github" / "workflows" / "test.yml"


def test_results_counts_reviewed_by_graded_at_like_the_suite_does():
    # The server only ever stores SUBMITTED or FLAGGED, never REVIEWED, so a count or a
    # filter keyed to the stored status would always read zero.
    results = (BLUEBOOK / "Results.jsx").read_text(encoding="utf-8")
    assert "const isReviewed = r => !!r.graded_at;" in results
    assert "REVIEWED:  isReviewed," in results
    assert "r.status === 'REVIEWED'" not in results
    assert "status: 'REVIEWED'" not in results and "status:'REVIEWED'" not in results


def test_the_dead_dashboard_overview_is_gone_and_nothing_says_flagged_review_required():
    dashboard = (BLUEBOOK / "Dashboard.jsx").read_text(encoding="utf-8")
    assert "DashboardScreen" not in dashboard and "StatCard" not in dashboard
    for path in sorted(BLUEBOOK.glob("*.jsx")):
        text = path.read_text(encoding="utf-8")
        assert "review required" not in text, path.name
        assert 'label="Flagged"' not in text, path.name
    # Nothing else may import what was removed.
    for path in sorted(BLUEBOOK.glob("*.jsx")):
        assert not re.search(r"\bDashboardScreen\b", path.read_text(encoding="utf-8")), path.name


def test_ci_checks_every_committed_bluebook_bundle_not_only_the_app_js():
    workflow = WORKFLOW.read_text(encoding="utf-8")
    assert "git status --porcelain -- *.bundle.*" in workflow
    assert "git diff --exit-code -- bluebook.bundle.js" not in workflow
    # The files that glob covers are all committed, so a stale one fails the check.
    committed = {p.name for p in BLUEBOOK.glob("*.bundle.*")}
    assert {
        "bluebook.bundle.js",
        "bluebook.bundle.js.map",
        "bluebook.bundle.css",
        "bluebook.bundle.css.map",
        "teacher-demo.bundle.js",
        "teacher-demo.bundle.css",
    } <= committed
