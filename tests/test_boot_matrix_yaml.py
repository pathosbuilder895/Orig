"""Structural tests for `.github/workflows/boot-matrix.yml` (T-07).

The boot matrix is the only check that installs a *lockset* and boots the
product the way Render does. Its cells carry Phase A's known-red semantics —
`expect` (what a fixed product does) and `today` (what this branch does) — and
a cell PASSES when the observed outcome equals `today`. That design has one
failure mode nothing else catches: someone quiets a newly-red cell by editing
`today` to match, and the gap silently loses its record. These tests are the
guard rail — a cell may only disagree with `expect` while naming a row that
actually exists in `docs/testing/10-gap-register.md`.

Everything here is static: it parses YAML and greps a table. It never boots
anything, so it costs milliseconds and runs on every PR alongside the matrix
itself.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "boot-matrix.yml"
GAP_REGISTER = REPO_ROOT / "docs" / "testing" / "10-gap-register.md"
BOOT_CHECK = REPO_ROOT / "scripts" / "boot_check.sh"

VALID_OUTCOMES = {"up", "refuse", "down"}
REQUIRED_FIELDS = ("name", "reqs", "env", "expect", "today")


def _load_workflow() -> dict:
    return yaml.safe_load(WORKFLOW.read_text())


def _cells() -> list[dict]:
    workflow = _load_workflow()
    return workflow["jobs"]["boot-matrix"]["strategy"]["matrix"]["include"]


def _registered_gap_ids() -> set[str]:
    """Ids that appear as an actual table ROW in the gap register.

    A prose mention of T-07 is not a register entry; the leading `| T-NN |`
    anchor is what makes it one.
    """
    return set(re.findall(r"^\|\s*(T-\d+)\s*\|", GAP_REGISTER.read_text(), re.MULTILINE))


@pytest.fixture(scope="module")
def cells() -> list[dict]:
    return _cells()


def test_workflow_exists_and_parses():
    assert WORKFLOW.is_file(), f"{WORKFLOW} is missing"
    workflow = _load_workflow()
    assert "boot-matrix" in workflow["jobs"]


def test_triggers_on_pull_request_and_main_push():
    workflow = _load_workflow()
    # PyYAML resolves a bare `on:` key to the boolean True (YAML 1.1); accept
    # either spelling so the test does not depend on that quirk.
    triggers = workflow.get("on", workflow.get(True))
    assert triggers is not None, "workflow declares no triggers"
    assert "pull_request" in triggers
    assert "main" in triggers["push"]["branches"]


def test_matrix_does_not_fail_fast():
    """One red cell must not cancel the other seven — each is its own claim."""
    strategy = _load_workflow()["jobs"]["boot-matrix"]["strategy"]
    assert strategy["fail-fast"] is False


def test_job_has_a_timeout():
    job = _load_workflow()["jobs"]["boot-matrix"]
    assert isinstance(job.get("timeout-minutes"), int)


def test_every_cell_has_the_required_fields(cells):
    for cell in cells:
        missing = [field for field in REQUIRED_FIELDS if field not in cell]
        assert not missing, f"cell {cell.get('name', cell)} is missing {missing}"


def test_cell_names_are_unique(cells):
    names = [cell["name"] for cell in cells]
    assert len(names) == len(set(names)), f"duplicate cell names in {names}"


def test_expect_and_today_are_valid_outcomes(cells):
    for cell in cells:
        for field in ("expect", "today"):
            assert cell[field] in VALID_OUTCOMES, (
                f"cell {cell['name']}: {field}={cell[field]!r} "
                f"is not one of {sorted(VALID_OUTCOMES)}"
            )


def test_known_red_cells_name_a_registered_gap(cells):
    """`today != expect` is only allowed with a real gap-register row.

    This is the test that stops the matrix from being quietly re-baselined:
    editing `today` to silence a red cell forces you to either match `expect`
    (the gap is fixed) or name a register id (the gap is recorded).
    """
    registered = _registered_gap_ids()
    assert "T-07" in registered, "gap register lost its T-07 row"
    for cell in cells:
        if cell["today"] == cell["expect"]:
            continue
        gap = (cell.get("gap") or "").strip()
        assert gap, (
            f"cell {cell['name']}: today={cell['today']} != expect={cell['expect']} "
            "but no gap id is named"
        )
        assert gap in registered, (
            f"cell {cell['name']}: gap {gap!r} is not a row in {GAP_REGISTER.name}"
        )


def test_refuse_cells_carry_a_log_fragment(cells):
    """A refusal is exit-non-zero AND a named check in the log.

    Without the fragment, `boot_check.sh` cannot tell a deliberate refusal from
    a crash — the script enforces this too, but a missing fragment should fail
    in milliseconds here rather than after a venv build in CI.
    """
    for cell in cells:
        if "refuse" not in (cell["expect"], cell["today"]):
            continue
        assert (cell.get("fragment") or "").strip(), (
            f"cell {cell['name']} is a refuse cell but names no log fragment"
        )


def test_every_referenced_lockset_exists(cells):
    for cell in cells:
        reqs = REPO_ROOT / cell["reqs"]
        assert reqs.is_file(), f"cell {cell['name']}: {cell['reqs']} does not exist"


def test_both_locksets_are_covered(cells):
    """The pilot lockset is the one that bricks; the demo lockset is what the
    sandbox ships. A matrix that dropped either would still look busy."""
    covered = {cell["reqs"] for cell in cells}
    assert "requirements-pilot.lock.txt" in covered
    assert "requirements-demo.lock.txt" in covered


def test_matrix_covers_the_spec_table_and_seeding_cell(cells):
    """08 §2's seven cells plus §8's seeding-safety cell."""
    by_env = {cell["name"]: cell["env"] for cell in cells}
    assert len(cells) == 8, f"expected 8 cells, found {len(cells)}: {sorted(by_env)}"

    joined = " || ".join(f"{cell['reqs']} {cell['env']} {cell.get('extra', '')}" for cell in cells)
    for required in (
        "REPO_BACKEND=sqlite",
        "REPO_BACKEND=postgres",
        "REPO_SHADOW=postgres",
        "ALLOWED_ORIGINS=*",
        "GUARD_DESTRUCTIVE=1",
        "--no-skip-seed",
    ):
        assert required in joined, f"no cell exercises {required}"


def test_pilot_cells_set_a_secret_key(cells):
    """`ORIGINAL_ENV=pilot` fails closed without a stable SECRET_KEY
    (api.py lifespan). A pilot cell that forgot it would report `down` for a
    reason that has nothing to do with what the cell is testing."""
    for cell in cells:
        if "ORIGINAL_ENV=pilot" not in cell["env"]:
            continue
        assert "SECRET_KEY=" in cell["env"], (
            f"cell {cell['name']} runs under ORIGINAL_ENV=pilot without a SECRET_KEY"
        )


def test_every_cell_runs_boot_check_from_its_own_venv():
    """The venv is the whole point — a step that pip-installs anything else, or
    calls boot_check.sh without putting `v/bin` first, is testing the runner's
    ambient Python instead of the lockset."""
    steps = _load_workflow()["jobs"]["boot-matrix"]["steps"]
    scripts = "\n".join(step.get("run", "") for step in steps)
    assert "python -m venv v" in scripts
    assert "v/bin/pip install -r" in scripts
    assert 'PATH="$PWD/v/bin:$PATH" scripts/boot_check.sh' in scripts
    assert "requirements.txt" not in scripts, (
        "the boot matrix must never install the full dev requirements"
    )


def test_boot_check_script_is_executable():
    assert BOOT_CHECK.is_file(), f"{BOOT_CHECK} is missing"
    assert BOOT_CHECK.stat().st_mode & 0o111, f"{BOOT_CHECK} is not executable"
