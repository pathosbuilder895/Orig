"""
tests/test_known_red_policy.py — Unit tests for scripts/known_red.py, the
policy check behind the `known-red` CI job (Testing Phase A).

Two things are pinned here:
  1. The pass/fail decision, against hand-built junit XML — never against a
     real pytest run — so the CI policy ("every blocker test must still be
     red; the day one passes, the job fails") is provable without needing an
     actual blocker test to exist yet.
  2. Every real test in the suite carrying `@pytest.mark.blocker` has a
     docstring whose first line names the gap id it pins (`T-\\d+`), so the
     table `scripts/known_red.py` prints is never a wall of "?" and the
     register (docs/testing/10-gap-register.md) can be cross-checked by eye.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

_spec = importlib.util.spec_from_file_location(
    "known_red", REPO_ROOT / "scripts" / "known_red.py"
)
known_red = importlib.util.module_from_spec(_spec)
# Register before exec: known_red.py's @dataclass looks itself up in
# sys.modules by __module__ name, which fails if the module isn't there yet.
sys.modules[_spec.name] = known_red
_spec.loader.exec_module(known_red)


ALL_FAIL_XML = """<?xml version="1.0" encoding="utf-8"?>
<testsuites><testsuite name="pytest" tests="2">
<testcase classname="tests.test_gaps" name="test_one" time="0.01">
<failure message="assert False">boom</failure>
</testcase>
<testcase classname="tests.test_gaps" name="test_two" time="0.01">
<error message="RuntimeError">boom</error>
</testcase>
</testsuite></testsuites>"""

ONE_PASS_XML = """<?xml version="1.0" encoding="utf-8"?>
<testsuites><testsuite name="pytest" tests="2">
<testcase classname="tests.test_gaps" name="test_one" time="0.01">
<failure message="assert False">boom</failure>
</testcase>
<testcase classname="tests.test_gaps" name="test_two" time="0.01" />
</testsuite></testsuites>"""

NONE_XML = """<?xml version="1.0" encoding="utf-8"?>
<testsuites><testsuite name="pytest" tests="0">
</testsuite></testsuites>"""


class TestParseAndDecide:
    def test_all_failed_or_errored_is_zero(self):
        results = known_red.parse_junit(ALL_FAIL_XML)
        assert [r.outcome for r in results] == ["failed", "error"]
        assert known_red.decide(results) == 0

    def test_one_pass_among_failures_is_one(self):
        results = known_red.parse_junit(ONE_PASS_XML)
        assert [r.outcome for r in results] == ["failed", "passed"]
        assert known_red.decide(results) == 1

    def test_zero_collected_is_zero(self):
        results = known_red.parse_junit(NONE_XML)
        assert results == []
        assert known_red.decide(results) == 0


class TestGapIdExtraction:
    def test_gap_id_found_via_docstring(self, tmp_path):
        (tmp_path / "test_sample.py").write_text(
            "import pytest\n\n"
            "@pytest.mark.blocker\n"
            "def test_thing():\n"
            '    """T-42: some gap."""\n'
            "    assert False\n"
        )
        result = known_red.BlockerResult("test_sample", "test_thing", "failed")
        assert known_red.gap_id_for(result, tmp_path) == "T-42"

    def test_gap_id_found_for_method_in_class(self, tmp_path):
        (tmp_path / "test_sample.py").write_text(
            "import pytest\n\n"
            "class TestThing:\n"
            "    @pytest.mark.blocker\n"
            "    def test_method(self):\n"
            '        """T-07: a class-scoped gap."""\n'
            "        assert False\n"
        )
        result = known_red.BlockerResult(
            "test_sample.TestThing", "test_method", "failed"
        )
        assert known_red.gap_id_for(result, tmp_path) == "T-07"

    def test_gap_id_missing_docstring_is_unknown(self, tmp_path):
        (tmp_path / "test_sample.py").write_text(
            "def test_thing():\n    assert False\n"
        )
        result = known_red.BlockerResult("test_sample", "test_thing", "failed")
        assert known_red.gap_id_for(result, tmp_path) == "?"

    def test_gap_id_unresolvable_classname_is_unknown(self, tmp_path):
        result = known_red.BlockerResult("nope.does.not.exist", "test_x", "failed")
        assert known_red.gap_id_for(result, tmp_path) == "?"


class TestEveryBlockerTestNamesItsGap:
    """Collection-driven: every @pytest.mark.blocker test in the real suite
    must have a docstring whose first line contains a T-<digits> gap id.
    """

    def test_blocker_tests_have_gap_id_docstrings(self):
        proc = subprocess.run(
            [
                sys.executable, "-m", "pytest", "--collect-only", "-q",
                "-m", "blocker", "-p", "no:cacheprovider",
            ],
            cwd=REPO_ROOT, capture_output=True, text=True,
        )
        nodeids = [
            line.strip()
            for line in proc.stdout.splitlines()
            if "::" in line and not line.startswith(" ")
        ]
        offenders = []
        for nodeid in nodeids:
            file_part, *chain = nodeid.split("::")
            if not chain:
                offenders.append(nodeid)
                continue
            base_name = chain[-1].split("[", 1)[0]
            dotted_chain = [*chain[:-1], base_name]
            doc = known_red._find_docstring(REPO_ROOT / file_part, dotted_chain)
            first_line = doc.strip().splitlines()[0] if doc else ""
            if not known_red.GAP_ID_RE.search(first_line):
                offenders.append(nodeid)
        assert offenders == [], f"blocker tests missing a T-<n> docstring: {offenders}"
