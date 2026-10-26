"""
tests/security/test_static_tree.py — "download the database."

docs/testing/04-security-adversarial.md §1.5. The forbidden-path list is
built from ``git ls-files`` plus a filesystem glob (``*.db``, ``*.sqlite*``,
``.env*``), excluding ``tests/``, so a new database file lands in the list
automatically rather than requiring someone to remember to add it here.

``original/api.py:_is_demo_only_static_path`` already gates an explicit list
(``_DEMO_ONLY_STATICS`` includes ``/seed.db``) plus prefixes
(``_DEMO_ONLY_STATIC_PREFIXES``) — this test is red only for paths that list
misses, marked per-``pytest.param`` rather than for the whole test.
"""

from __future__ import annotations

import fnmatch
import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import run as run_mod

pytestmark = pytest.mark.security

REPO_ROOT = Path(__file__).resolve().parents[2]
DEMO_DIR = REPO_ROOT / "demo"
_GLOB_PATTERNS = ("*.db", "*.sqlite*", ".env*")


def _forbidden_paths() -> list[tuple[str, str]]:
    """Return [(repo-relative path, URL under the mount), ...].

    A file that lives under ``demo/`` gets the URL it would actually be
    served at (relative to the mount root). A file elsewhere in the repo
    (e.g. ``.env.example`` at the repo root) gets the URL that path would
    have *if* it were under the mount — which nothing serves, so asserting
    404 there documents the policy rather than detecting an exposure, per
    the task brief.
    """
    tracked = subprocess.run(
        ["git", "ls-files"], capture_output=True, text=True, cwd=REPO_ROOT, check=True
    ).stdout.splitlines()

    # The tracked set is a belt-and-braces seed: the rglob below already finds
    # every matching file on disk (tracked or not), and the pattern filter
    # after it drops any tracked path that does not match the globs.
    candidates: set[str] = set(tracked)
    for pattern in _GLOB_PATTERNS:
        for path in REPO_ROOT.rglob(pattern):
            if path.is_dir():
                continue
            rel = path.relative_to(REPO_ROOT).as_posix()
            if rel.startswith((".venv/", ".git/", "node_modules/")):
                continue
            candidates.add(rel)

    out: list[tuple[str, str]] = []
    for rel in sorted(candidates):
        if rel.startswith("tests/"):
            continue
        base = Path(rel).name
        if not any(fnmatch.fnmatch(base, p) for p in _GLOB_PATTERNS):
            continue
        if rel.startswith("demo/"):
            url = "/" + rel[len("demo/") :]
        else:
            url = "/" + rel
        out.append((rel, url))
    return out


FORBIDDEN = _forbidden_paths()
# Sanity: this environment's known members must actually be in the derived
# list, or the glob logic above is broken rather than the list being empty.
assert any(url == "/seed.db" for _, url in FORBIDDEN), FORBIDDEN
assert any(url == "/.env.example" for _, url in FORBIDDEN), FORBIDDEN


@pytest.fixture
def mounted_app(live_app):
    """The live app with demo/ mounted as static, exactly as ``run.py --demo``
    does (``run.create_demo_app`` re-mounts idempotently onto the same
    session-scoped app ``live_app`` already points at).

    ``run.create_demo_app`` mutates ``live_app`` in place (appends the ``/``
    redirect Route and a StaticFiles Mount, and sets an app.state flag)
    rather than returning a fresh app. Left in place, that Mount breaks every
    later route-inventory test that iterates ``r.methods`` over
    ``live_app.routes`` (test_phone_park, test_bluebook_crud,
    tests/fusion/test_expert) — so the route table and the flag are
    restored on teardown.
    """
    saved_routes = list(live_app.router.routes)
    had_flag = getattr(live_app.state, "_original_demo_frontend_mounted", False)
    yield run_mod.create_demo_app(DEMO_DIR)
    live_app.router.routes[:] = saved_routes
    if not had_flag and hasattr(live_app.state, "_original_demo_frontend_mounted"):
        delattr(live_app.state, "_original_demo_frontend_mounted")


@pytest.fixture
def mounted_client(mounted_app):
    return TestClient(mounted_app)


@pytest.fixture
def mounted_pilot_client(mounted_app, pilot_env):
    return TestClient(mounted_app)


@pytest.mark.parametrize("repo_path,url", FORBIDDEN, ids=[url for _, url in FORBIDDEN])
def test_forbidden_static_paths_404_in_pilot(mounted_pilot_client, repo_path, url):
    """Every db/sqlite/env-file path in the repo 404s under a real deploy.

    Green for every case in this checkout: ``/seed.db`` is covered by
    ``_DEMO_ONLY_STATICS``, and the repo-root files (``.env.example``,
    ``profiles.db``) were never under ``demo/`` to begin with, so nothing
    serves them regardless of the gate. The parametrization exists so a
    *future* db/sqlite/env file lands in this list automatically; if the
    gate ever misses one, mark that case's ``pytest.param`` blocker.
    """
    r = mounted_pilot_client.get(url)
    assert r.status_code == 404, f"{url} (from {repo_path}) -> {r.status_code}: {r.text[:200]}"


def test_bluebook_sourcemap_404_in_pilot(mounted_pilot_client):
    """T-06: the demo static tree serves build artifacts it shouldn't under pilot.

    ``/bluebook/bluebook.bundle.js.map`` is a real, committed file
    (``demo/bluebook/bluebook.bundle.js.map``, ~1.2MB) and is covered by
    neither ``_DEMO_ONLY_STATICS`` nor ``_DEMO_ONLY_STATIC_PREFIXES``
    (``original/api.py:313``), so a real deploy serves the full source map —
    original source paths, unminified structure — to anyone who asks.
    """
    r = mounted_pilot_client.get("/bluebook/bluebook.bundle.js.map")
    assert r.status_code == 404, f"-> {r.status_code}, {len(r.content)} bytes served"


def test_seed_db_served_in_demo(mounted_client):
    """Documents the policy contrast: /seed.db IS served in plain demo mode.

    Demo mode is the anonymous sales sandbox — seed.db there is synthetic
    fixture data, not FERPA-protected student records — so this is the
    allowed counterpart to the pilot-mode 404 above, not a hole.
    """
    r = mounted_client.get("/seed.db")
    assert r.status_code == 200, r.text[:200]


def test_root_opens_bluebook_on_a_real_deploy(mounted_pilot_client):
    """The public self-serve site's front door is Bluebook, not Original's
    professor page (which a signed-out visitor could not use anyway)."""
    r = mounted_pilot_client.get("/", follow_redirects=False)
    assert r.status_code in (302, 307)
    assert r.headers["location"] == "/bluebook/"


def test_root_keeps_the_original_tour_in_the_demo(mounted_client):
    r = mounted_client.get("/", follow_redirects=False)
    assert r.headers["location"] == "/professor.html"


def test_collections_path_serves_the_app(mounted_pilot_client):
    """/collections/ is the user-facing path for the Collections app; it
    serves the same SPA as /bluebook/ (which stays live for emails and LTI)."""
    r = mounted_pilot_client.get("/collections/")
    assert r.status_code == 200
    assert "bluebook.bundle.js" in r.text
    assert mounted_pilot_client.get("/collections/bluebook.bundle.js").status_code == 200
    r = mounted_pilot_client.get("/collections?invite=x", follow_redirects=False)
    assert r.status_code == 307 and r.headers["location"] == "/collections/?invite=x"


def test_collections_sourcemap_404_in_pilot(mounted_pilot_client):
    assert mounted_pilot_client.get("/collections/bluebook.bundle.js.map").status_code == 404


# The classic Original student pages (demo/student.html and the Focus Coach it
# opens) use wording students should not meet ("diverges from your
# established voice", "monitored environment", "Verification Session") and
# load Google Fonts. Students on a real deploy use Collections and the navy
# Original pages (demo/original/voice.html, my-work.html), so these stay in
# the demo only. Served from the real demo/ tree, so a 404 here is the gate,
# not a missing file.
CLASSIC_STUDENT_PAGES = ("/student.html", "/student-coach.html")


@pytest.mark.parametrize("url", CLASSIC_STUDENT_PAGES)
def test_classic_student_pages_404_in_pilot(mounted_pilot_client, url):
    r = mounted_pilot_client.get(url)
    assert r.status_code == 404, f"{url} -> {r.status_code}"


@pytest.mark.parametrize("url", CLASSIC_STUDENT_PAGES)
def test_classic_student_pages_served_in_demo(mounted_client, url):
    assert mounted_client.get(url).status_code == 200


def test_the_pages_students_use_stay_reachable_in_pilot(mounted_pilot_client):
    for url in ("/bluebook/", "/original/voice.html", "/original/my-work.html", "/legal/student-notice.html"):
        assert mounted_pilot_client.get(url).status_code == 200, url


# StaticFiles splits the URL path on "/" and normalises the join, so an empty
# or dot segment still reaches the gated file. Before the gates compared the
# resolved path (``original/api.py:_static_lookup_path``), every spelling
# below was served on a real deploy: ``//seed.db`` returned the database,
# ``/bluebook//bluebook.bundle.js.map`` the source map, ``//prototypes/`` the
# prototype index. ``/%2F`` decodes to ``//`` before the middleware sees it.
GATE_BYPASS_SPELLINGS = (
    "//seed.db",
    "/%2Fseed.db",
    "/./seed.db",
    "/x/../seed.db",
    "//student.html",
    "/bluebook//bluebook.bundle.js.map",
    "/collections//bluebook.bundle.js.map",
    "//prototypes/",
    "//app/index.html",
    "/./app/index.html",
)


@pytest.mark.parametrize("url", GATE_BYPASS_SPELLINGS)
def test_gate_bypass_spellings_404_in_pilot(mounted_pilot_client, url):
    r = mounted_pilot_client.get("http://testserver" + url, follow_redirects=False)
    assert r.status_code == 404, f"{url} -> {r.status_code}, {len(r.content)} bytes served"


@pytest.mark.parametrize(
    "path,resolved",
    [
        ("/", "/"),
        ("//seed.db", "/seed.db"),
        ("/./app/", "/app"),
        ("/x/../seed.db", "/seed.db"),
        ("/bluebook//bluebook.bundle.js.map", "/bluebook/bluebook.bundle.js.map"),
        ("/prototypes-public/", "/prototypes-public"),
    ],
)
def test_static_lookup_path_matches_what_staticfiles_serves(path, resolved):
    import original.api as api_mod

    assert api_mod._static_lookup_path(path) == resolved

