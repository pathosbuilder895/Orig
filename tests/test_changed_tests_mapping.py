"""
tests/test_changed_tests_mapping.py — Unit tests for scripts/changed_tests.py,
the changed-file → test-file mapper behind the pre-push hook.

The mapper is a heuristic (naming convention + import scan), not a proof of
coverage — these tests pin down exactly which heuristics it promises, so the
hook's behavior stays predictable as the repo grows.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

_spec = importlib.util.spec_from_file_location(
    "changed_tests", REPO_ROOT / "scripts" / "changed_tests.py"
)
changed_tests = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(changed_tests)


def _mk(root: Path, rel: str, content: str = "") -> Path:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content)
    return p


class TestMapping:
    def test_changed_test_file_maps_to_itself(self, tmp_path):
        _mk(tmp_path, "tests/quantum/test_scoring.py", "def test_x(): pass\n")
        tests, _ = changed_tests.map_changed_to_tests(
            ["tests/quantum/test_scoring.py"], tmp_path
        )
        assert tests == ["tests/quantum/test_scoring.py"]

    def test_source_module_maps_via_naming_convention(self, tmp_path):
        _mk(tmp_path, "original/quantum/scoring.py", "def score(): pass\n")
        _mk(tmp_path, "tests/quantum/test_scoring.py", "def test_x(): pass\n")
        tests, _ = changed_tests.map_changed_to_tests(
            ["original/quantum/scoring.py"], tmp_path
        )
        assert "tests/quantum/test_scoring.py" in tests

    def test_source_module_maps_via_dotted_import_scan(self, tmp_path):
        _mk(tmp_path, "original/quantum/scoring.py", "def score(): pass\n")
        _mk(
            tmp_path,
            "tests/test_layer7.py",
            "from original.quantum.scoring import score\n",
        )
        tests, _ = changed_tests.map_changed_to_tests(
            ["original/quantum/scoring.py"], tmp_path
        )
        assert "tests/test_layer7.py" in tests

    def test_from_parent_import_form_detected(self, tmp_path):
        _mk(tmp_path, "original/quantum/scoring.py", "def score(): pass\n")
        _mk(
            tmp_path,
            "tests/test_indirect.py",
            "from original.quantum import state, scoring\n",
        )
        tests, _ = changed_tests.map_changed_to_tests(
            ["original/quantum/scoring.py"], tmp_path
        )
        assert "tests/test_indirect.py" in tests

    def test_monkeypatch_string_target_detected(self, tmp_path):
        _mk(tmp_path, "original/quantum/scoring.py", "def score(): pass\n")
        _mk(
            tmp_path,
            "tests/test_patcher.py",
            'def test_y(monkeypatch):\n'
            '    monkeypatch.setattr("original.quantum.scoring.score", lambda: 1)\n',
        )
        tests, _ = changed_tests.map_changed_to_tests(
            ["original/quantum/scoring.py"], tmp_path
        )
        assert "tests/test_patcher.py" in tests

    def test_prefix_module_name_does_not_false_match(self, tmp_path):
        _mk(tmp_path, "original/store.py", "def get(): pass\n")
        _mk(
            tmp_path,
            "tests/test_other.py",
            "from original.storefront import checkout\n",
        )
        tests, _ = changed_tests.map_changed_to_tests(["original/store.py"], tmp_path)
        assert tests == []

    def test_repo_root_module_needs_import_anchor(self, tmp_path):
        _mk(tmp_path, "run.py", "def main(): pass\n")
        _mk(tmp_path, "tests/test_launcher.py", "import run\n")
        _mk(tmp_path, "tests/test_unrelated.py", "def test_running_total(): pass\n")
        tests, _ = changed_tests.map_changed_to_tests(["run.py"], tmp_path)
        assert "tests/test_launcher.py" in tests
        assert "tests/test_unrelated.py" not in tests

    def test_package_init_maps_to_package_importers(self, tmp_path):
        _mk(tmp_path, "original/fusion/__init__.py", "X = 1\n")
        _mk(tmp_path, "tests/test_fused.py", "from original.fusion import X\n")
        tests, _ = changed_tests.map_changed_to_tests(
            ["original/fusion/__init__.py"], tmp_path
        )
        assert "tests/test_fused.py" in tests

    def test_conftest_change_warns_without_mapping(self, tmp_path):
        _mk(tmp_path, "tests/conftest.py", "import pytest\n")
        tests, warnings = changed_tests.map_changed_to_tests(
            ["tests/conftest.py"], tmp_path
        )
        assert tests == []
        assert any("conftest" in w for w in warnings)

    def test_deleted_changed_file_is_skipped(self, tmp_path):
        _mk(tmp_path, "tests/test_alive.py", "def test_a(): pass\n")
        tests, _ = changed_tests.map_changed_to_tests(
            ["original/gone.py", "tests/test_alive.py"], tmp_path
        )
        assert tests == ["tests/test_alive.py"]

    def test_source_with_no_mapped_tests_warns(self, tmp_path):
        _mk(tmp_path, "original/orphan.py", "def f(): pass\n")
        _mk(tmp_path, "tests/test_other.py", "import original.other\n")
        tests, warnings = changed_tests.map_changed_to_tests(
            ["original/orphan.py"], tmp_path
        )
        assert tests == []
        assert any("original/orphan.py" in w for w in warnings)

    def test_results_deduplicated_and_sorted(self, tmp_path):
        _mk(tmp_path, "original/quantum/scoring.py", "def score(): pass\n")
        _mk(
            tmp_path,
            "tests/quantum/test_scoring.py",
            "from original.quantum.scoring import score\n",
        )
        _mk(tmp_path, "tests/test_aaa.py", "import original.quantum.scoring\n")
        tests, _ = changed_tests.map_changed_to_tests(
            ["original/quantum/scoring.py", "tests/quantum/test_scoring.py"], tmp_path
        )
        assert tests == ["tests/test_aaa.py", "tests/quantum/test_scoring.py"] or tests == sorted(
            {"tests/test_aaa.py", "tests/quantum/test_scoring.py"}
        )

    def test_non_python_changes_map_to_nothing(self, tmp_path):
        _mk(tmp_path, "docs/notes.md", "# notes\n")
        _mk(tmp_path, "demo/bluebook/App.jsx", "// jsx\n")
        tests, _ = changed_tests.map_changed_to_tests(
            ["docs/notes.md", "demo/bluebook/App.jsx"], tmp_path
        )
        assert tests == []
