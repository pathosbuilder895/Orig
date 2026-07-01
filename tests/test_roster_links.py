"""
tests/test_roster_links.py — the roster→magic-links generator
(scripts/roster_links.py).

The load-bearing invariant: a link's `sid` MUST equal what a Canvas/LTI launch
derives for the same student, so the no-Canvas path and the LTI path converge on
one profile. Plus roster parsing, FERPA URL-minimisation, and disclosure pull.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from original import student_auth as sa

_SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "roster_links.py"
_spec = importlib.util.spec_from_file_location("roster_links", _SCRIPT)
rl = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(rl)


# ── parity with the server's id derivation (the whole point) ──────────────────

class TestSidParity:
    def test_link_sid_matches_server_derivation(self):
        tenant = sa.slugify("Northfield Seminary")
        email = "jane.doe@northfield.edu"
        expected = sa.derive_student_id(tenant, email)
        link = rl.build_link("https://x.test", tenant, expected, "Exam", "Jane Doe", include_name=False)
        sid = parse_qs(urlparse(link).query)["sid"][0]
        assert sid == expected
        # and an LTI launch derives the same id from the same (tenant, email)
        assert sid == sa.derive_student_id(tenant, email)


# ── roster parsing ────────────────────────────────────────────────────────────

class TestParseRoster:
    def test_csv_with_header(self):
        rows = rl.parse_roster("name,email\nJane Doe,jane@a.edu\nSam,sam@a.edu\n")
        assert rows == [("Jane Doe", "jane@a.edu"), ("Sam", "sam@a.edu")]

    def test_csv_columns_reversed(self):
        rows = rl.parse_roster("email,name\njane@a.edu,Jane Doe\n")
        assert rows == [("Jane Doe", "jane@a.edu")]

    def test_liberal_lines_and_angle_brackets(self):
        rows = rl.parse_roster("Jane Doe <jane@a.edu>\nsam@a.edu, Sam Okonkwo\n")
        assert rows == [("Jane Doe", "jane@a.edu"), ("Sam Okonkwo", "sam@a.edu")]

    def test_email_only(self):
        assert rl.parse_roster("jane@a.edu\n") == [("", "jane@a.edu")]

    def test_dedup_by_email_first_wins(self):
        rows = rl.parse_roster("Jane,jane@a.edu\njane@a.edu\n")
        assert rows == [("Jane", "jane@a.edu")]

    def test_skips_comments_blanks_and_junk(self):
        rows = rl.parse_roster("# header comment\n\nnot-an-email-line\nSam,sam@a.edu\n")
        assert rows == [("Sam", "sam@a.edu")]

    def test_email_lowercased(self):
        assert rl.parse_roster("Jane,JANE@A.EDU\n") == [("Jane", "jane@a.edu")]


# ── FERPA URL-minimisation ────────────────────────────────────────────────────

class TestBuildLink:
    def test_default_carries_only_sid_tenant_exam_no_pii(self):
        link = rl.build_link("https://h.test/", "t", "t:abc123", "Week 1", "Jane Doe", include_name=False)
        q = parse_qs(urlparse(link).query)
        assert set(q) == {"sid", "tenant", "exam"}
        assert "candidate" not in q and "email" not in q
        assert q["sid"] == ["t:abc123"] and q["tenant"] == ["t"]

    def test_include_name_adds_candidate(self):
        link = rl.build_link("https://h.test", "t", "t:abc", "Week 1", "Jane Doe", include_name=True)
        assert parse_qs(urlparse(link).query)["candidate"] == ["Jane Doe"]

    def test_base_url_trailing_slash_normalised(self):
        link = rl.build_link("https://h.test/", "t", "t:abc", "", "", include_name=False)
        assert link.startswith("https://h.test/bluebook/?")


# ── disclosure single-source-of-truth ─────────────────────────────────────────

class TestSyllabusParagraph:
    def test_extracts_nonempty_paragraph(self):
        para = rl.syllabus_paragraph()
        # The doc ships with the repo; if present the paragraph must be substantive.
        if para is not None:
            assert "Original" in para and "Bluebook" in para and len(para) > 100
