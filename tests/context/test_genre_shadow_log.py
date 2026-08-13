"""
tests/context/test_genre_shadow_log.py — reading the pilot shadow log.

GENRE_RESOLVER_V2=shadow emits one INFO line per resolver call. This is the
reader that turns a production log into the one number the rollout waits on:
the abstention rate on REAL student submissions. Committed with tests so the
measurement is a single command whenever the pilot log becomes available,
rather than a scripting exercise done under time pressure.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_SPEC = importlib.util.spec_from_file_location(
    "read_shadow_log", Path("validation/genre_2026-08/read_shadow_log.py")
)


@pytest.fixture(scope="module")
def mod():
    module = importlib.util.module_from_spec(_SPEC)
    _SPEC.loader.exec_module(module)
    return module


_REAL_LINE = (
    "INFO:original.context.resolvers:genre_shadow v1=correspondence "
    "v2=academic_exegesis v2_confidence=1.000"
)


class TestParsing:
    def test_parses_the_line_the_resolver_actually_emits(self, mod):
        """Pinned against a line captured from the live ingestion path, not
        one written to match the parser."""
        parsed = mod.parse_line(_REAL_LINE)
        assert parsed == ("correspondence", "academic_exegesis", 1.0)

    def test_tolerates_surrounding_log_furniture(self, mod):
        """Render prefixes timestamps and stream names; the parser must not
        depend on the line starting where pytest's caplog puts it."""
        line = (
            "2026-08-08T11:02:44.123Z app[web.1]: INFO original.context.resolvers "
            "genre_shadow v1=personal_essay v2=narrative_prose v2_confidence=0.874"
        )
        assert mod.parse_line(line) == ("personal_essay", "narrative_prose", 0.874)

    def test_ignores_unrelated_lines(self, mod):
        for line in ("", "INFO: something else entirely", "genre_shadow malformed"):
            assert mod.parse_line(line) is None

    def test_ignores_other_shadow_channels(self, mod):
        """bayesian_prior and topic-inflation shadow lines share the log."""
        assert mod.parse_line("INFO bayesian_prior outcome=hit genre=x tenant=y") is None


class TestSummarise:
    def test_reports_abstention_and_the_shift_matrix(self, mod):
        lines = [
            _REAL_LINE,
            "genre_shadow v1=correspondence v2=unknown v2_confidence=0.000",
            "genre_shadow v1=correspondence v2=unknown v2_confidence=0.000",
            "genre_shadow v1=blog_post v2=narrative_prose v2_confidence=0.910",
        ]
        out = mod.summarise(lines)
        assert out["n"] == 4
        assert out["abstention_rate"] == 0.5
        assert out["shift_matrix"]["correspondence -> unknown"] == 2
        assert out["v2_distribution"]["unknown"] == 2

    def test_reports_confidence_quantiles_for_claimed_labels_only(self, mod):
        """An abstention carries confidence 0.0 by construction; averaging it
        into the claimed-label distribution would drag every quantile down
        and make a confident model look uncertain."""
        lines = [
            "genre_shadow v1=x v2=unknown v2_confidence=0.000",
            "genre_shadow v1=x v2=narrative_prose v2_confidence=0.800",
            "genre_shadow v1=x v2=narrative_prose v2_confidence=0.900",
        ]
        out = mod.summarise(lines)
        assert out["claimed_confidence_median"] == pytest.approx(0.85)

    def test_an_empty_log_does_not_divide_by_zero(self, mod):
        out = mod.summarise([])
        assert out["n"] == 0
        assert out["abstention_rate"] == 0.0

    def test_a_log_with_no_shadow_lines_is_reported_as_such(self, mod):
        """Distinguishes "shadow ran and never abstained" from "shadow was
        never on" — the two look identical in a bare abstention rate, and
        only one of them is a measurement."""
        out = mod.summarise(["INFO: unrelated", "WARNING: also unrelated"])
        assert out["n"] == 0
        assert out["no_shadow_lines_found"] is True

    def test_a_real_measurement_is_not_flagged_as_missing(self, mod):
        out = mod.summarise([_REAL_LINE])
        assert out["no_shadow_lines_found"] is False
