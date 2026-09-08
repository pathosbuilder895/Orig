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

SKIPPED_UNINFORMATIVE_XML = """<?xml version="1.0" encoding="utf-8"?>
<testsuites><testsuite name="pytest" tests="1">
<testcase classname="tests.test_gaps" name="test_one" time="0.01">
<skipped type="pytest.skip" message="uninformative &#8212; sample size floor not met">uninformative — sample size floor not met</skipped>
</testcase>
</testsuite></testsuites>"""

SKIPPED_PLAIN_XML = """<?xml version="1.0" encoding="utf-8"?>
<testsuites><testsuite name="pytest" tests="1">
<testcase classname="tests.test_gaps" name="test_one" time="0.01">
<skipped type="pytest.skip" message="not implemented yet">not implemented yet</skipped>
</testcase>
</testsuite></testsuites>"""

MIXED_PASS_AND_PLAIN_SKIP_XML = """<?xml version="1.0" encoding="utf-8"?>
<testsuites><testsuite name="pytest" tests="2">
<testcase classname="tests.test_gaps" name="test_one" time="0.01" />
<testcase classname="tests.test_gaps" name="test_two" time="0.01">
<skipped type="pytest.skip" message="not implemented yet">not implemented yet</skipped>
</testcase>
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

    def test_skipped_with_uninformative_reason_is_uninformative_and_zero(self):
        results = known_red.parse_junit(SKIPPED_UNINFORMATIVE_XML)
        assert [r.outcome for r in results] == ["uninformative"]
        assert known_red.decide(results) == 0

    def test_skipped_without_uninformative_reason_is_policy_violation(self):
        results = known_red.parse_junit(SKIPPED_PLAIN_XML)
        assert [r.outcome for r in results] == ["skipped"]
        assert known_red.decide(results) == 1

    def test_mix_of_pass_and_plain_skip_is_one(self):
        results = known_red.parse_junit(MIXED_PASS_AND_PLAIN_SKIP_XML)
        assert [r.outcome for r in results] == ["passed", "skipped"]
        assert known_red.decide(results) == 1


class TestReportAndDecideExitHandling:
    """scripts/known_red.py's report_and_decide() turns a pytest run's raw
    (returncode, junit_text, captured_output) into the known-red exit code.
    These never shell out to a real pytest run — the whole point of
    exercising this against hand-built inputs is that the policy is
    provable without needing the run itself to break on demand.
    """

    def test_exit_5_is_zero_with_no_tests_notice(self, capsys):
        # pytest's own "no tests collected" exit code is the legitimate
        # "no blocker tests exist" notice, not an error.
        code = known_red.report_and_decide(5, None, "", REPO_ROOT)
        assert code == 0
        assert "nothing to check" in capsys.readouterr().out

    def test_exit_4_is_a_hard_error(self, capsys):
        # pytest exit 4 (usage error) means the run of the blocker suite
        # itself broke -- never a policy verdict, so it must not be read
        # as "all blockers still red" (0) or silently swallowed.
        code = known_red.report_and_decide(4, None, "some captured output", REPO_ROOT)
        assert code == 2
        out = capsys.readouterr().out
        assert "some captured output" in out
        assert "run broke" in out

    def test_exit_1_with_zero_testcases_is_a_hard_error(self, capsys):
        # Exit 1 normally means "tests ran, at least one failed" -- but if
        # the junit report parsed to zero <testcase> elements, something
        # about the run itself is broken (e.g. a collection error that
        # still exits 1) and this must not be conflated with "nothing to
        # check" (which is reserved for the real exit-5 notice).
        code = known_red.report_and_decide(1, NONE_XML, "collection error", REPO_ROOT)
        assert code == 2
        out = capsys.readouterr().out
        assert "collection error" in out
        assert "run broke" in out

    def test_exit_0_with_results_defers_to_decide(self, capsys):
        code = known_red.report_and_decide(0, ALL_FAIL_XML, "", REPO_ROOT)
        assert code == 0

    def test_exit_1_with_results_defers_to_decide(self, capsys):
        code = known_red.report_and_decide(1, ONE_PASS_XML, "", REPO_ROOT)
        assert code == 1

    def test_missing_junit_file_on_exit_0_is_a_hard_error(self, capsys):
        # Even a "clean" exit code is not trustworthy without a junit
        # report to back it up.
        code = known_red.report_and_decide(0, None, "no report written", REPO_ROOT)
        assert code == 2
        assert "run broke" in capsys.readouterr().out


class TestGapIdExtraction:
    def test_gap_id_found_via_docstring(self, tmp_path):
        (tmp_path / "test_sample.py").write_text(
            "import pytest\n\n"
            "@pytest.mark.blocker\n"
            "def test_thing():\n"
            '    """T-999: some gap."""\n'
            "    assert False\n"
        )
        result = known_red.BlockerResult("test_sample", "test_thing", "failed")
        assert known_red.gap_id_for(result, tmp_path) == "T-999"

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
        # Scoped to "tests/" to match scripts/known_red.py's own scope
        # (it runs "pytest tests/ -m blocker") — a bare, path-less
        # collect-only here would guard a different (wider) set of tests
        # than the script actually enforces.
        proc = subprocess.run(
            [
                sys.executable, "-m", "pytest", "tests/", "--collect-only", "-q",
                "-m", "blocker", "-p", "no:cacheprovider",
            ],
            cwd=REPO_ROOT, capture_output=True, text=True,
        )
        # 0 = tests collected, 5 = none did (both are legitimate outcomes of
        # collection itself); anything else means collection broke.
        assert proc.returncode in (0, 5), (
            f"--collect-only failed unexpectedly (exit {proc.returncode}):\n"
            f"{proc.stdout}\n{proc.stderr}"
        )
        nodeids = [
            line.strip()
            for line in proc.stdout.splitlines()
            if "::" in line and not line.startswith(" ")
        ]
        # Without this, an empty `nodeids` (e.g. the -m blocker filter
        # matching nothing) would make the loop below a no-op and the
        # "every blocker test names its gap" guard would pass vacuously.
        assert nodeids, "expected at least one @pytest.mark.blocker test to be collected"
        offenders = []
        for nodeid in nodeids:
            # Strip the parametrise suffix BEFORE splitting: a param id may
            # itself contain "::" (T-05 probes "http://[::1]").
            base_id = nodeid.split("[", 1)[0]
            file_part, *chain = base_id.split("::")
            if not chain:
                offenders.append(nodeid)
                continue
            base_name = chain[-1]
            dotted_chain = [*chain[:-1], base_name]
            doc = known_red._find_docstring(REPO_ROOT / file_part, dotted_chain)
            first_line = doc.strip().splitlines()[0] if doc else ""
            if not known_red.GAP_ID_RE.search(first_line):
                offenders.append(nodeid)
        assert offenders == [], f"blocker tests missing a T-<n> docstring: {offenders}"
