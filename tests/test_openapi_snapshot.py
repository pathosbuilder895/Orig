"""The committed OpenAPI schema snapshot must match what the live app emits.

`test_openapi_stability.py` (subprocess sweep) proves `app.openapi()` is
byte-identical across `PYTHONHASHSEED` values — it does not catch a
deliberate schema *change*. This file diffs the in-process schema against
the committed baseline in `tests/snapshots/openapi.json`, so a schema
change becomes a reviewed diff produced by
`scripts/update_openapi_snapshot.py`, never a silent drift.

Serialisation must match the script exactly: ``json.dumps(app.openapi(),
sort_keys=True, indent=2, ensure_ascii=False) + "\\n"``, snapshot file read
back as UTF-8. Both choices (sort_keys/indent and ensure_ascii=False) are
made once here and mirrored in the script so the two never quietly diverge
in how they serialise the same schema dict.

Version handling: `app.info.version` comes from `_resolve_app_version()`
(`original/api.py`), which reads installed package metadata or falls back
to parsing `version = "..."` out of `pyproject.toml` — it is a small,
manually-bumped literal, not a git SHA or timestamp, so it does not churn
per commit. The snapshot therefore stores the real version string rather
than a placeholder; a second test below independently asserts the snapshot's
`info.version` still equals `_resolve_app_version()`, so the snapshot can't
silently pin a stale version after a version bump lands without the
snapshot being regenerated.
"""

from __future__ import annotations

import difflib
import json
from pathlib import Path

import pytest

from run import load_legacy_demo_app

REPO_ROOT = Path(__file__).resolve().parents[1]
SNAPSHOT_PATH = REPO_ROOT / "tests" / "snapshots" / "openapi.json"

_REGENERATE_MSG = (
    "intentional? run `python scripts/update_openapi_snapshot.py` and review the diff"
)


def _current_schema_text() -> str:
    app = load_legacy_demo_app()
    return json.dumps(app.openapi(), sort_keys=True, indent=2, ensure_ascii=False) + "\n"


@pytest.mark.filterwarnings(
    # These two fire only the first time a process calls app.openapi() in-process
    # (test_openapi_stability.py always shells out to a subprocess, so it never
    # triggers them). Both are pre-existing, already-accepted app behaviour, not
    # something this test is checking for: the operationId collision on
    # /lti/login is the *intentional* pin test_openapi_stability.py itself
    # verifies (`test_lti_login_operation_id_is_pinned`), and the pydantic
    # protected-namespace warning is a naming nit on an unrelated response
    # model. Scoped narrowly so any other warning still surfaces.
    "ignore:.*Duplicate Operation ID lti_login.*:UserWarning",
    "ignore:.*conflict with protected namespace.*:UserWarning",
)
def test_openapi_schema_matches_snapshot():
    """`app.openapi()` must byte-match the committed snapshot."""
    current = _current_schema_text()
    snapshot = SNAPSHOT_PATH.read_text(encoding="utf-8")

    if current != snapshot:
        diff = "\n".join(
            list(
                difflib.unified_diff(
                    snapshot.splitlines(),
                    current.splitlines(),
                    fromfile="tests/snapshots/openapi.json (committed)",
                    tofile="app.openapi() (current)",
                    lineterm="",
                )
            )[:40]
        )
        raise AssertionError(
            "OpenAPI schema no longer matches tests/snapshots/openapi.json.\n"
            f"First 40 lines of unified diff:\n{diff}\n\n{_REGENERATE_MSG}"
        )


def test_snapshot_version_matches_resolved_version():
    """The snapshot's `info.version` must equal the app's resolved version.

    Guards against the snapshot silently pinning a stale version string
    after `pyproject.toml`'s version (or installed package metadata) moves
    on without the snapshot being regenerated.
    """
    from original.api import _resolve_app_version

    snapshot = json.loads(SNAPSHOT_PATH.read_text(encoding="utf-8"))
    assert snapshot["info"]["version"] == _resolve_app_version(), (
        "Snapshot info.version is stale relative to _resolve_app_version(). "
        f"{_REGENERATE_MSG}"
    )
