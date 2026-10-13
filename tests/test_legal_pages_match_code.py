"""The legal pages say what the code does, and nothing it does not.

`test_legal_release_guard.py` keeps the pages either clearly draft or fully
complete. This file pins their substance: each statement below is one the
2026-10-13 rewrite cites to a code path (see that PR's description), so a
page edit that drops or contradicts one fails here, and so does a code
change that this file's own checks can see (the retention constant, the
mailer's subjects, the absence of an IP column).
"""

from __future__ import annotations

import html
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LEGAL = ROOT / "demo/legal"
PAGES = {name: (LEGAL / name).read_text() for name in ("privacy.html", "terms.html", "student-notice.html")}


def _text(page: str) -> str:
    """The page as a reader sees it: tags removed, entities decoded, spaces collapsed."""
    body = re.sub(r"<(script|style)\b.*?</\1>", " ", page, flags=re.S | re.I)
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", body))).strip()


TEXT = {name: _text(page) for name, page in PAGES.items()}


def test_every_page_opens_with_the_pending_counsel_review_marker():
    for name, page in PAGES.items():
        main = page[page.index("<main>") :]
        first = re.search(r"<p\b[^>]*>(.*?)</p>", main, re.S)
        assert first, name
        marker = _text(first.group(1))
        # The marker reads "DRAFT", an em dash, "pending counsel review" (the
        # pages write the dash as an HTML entity).
        assert marker.startswith("DRAFT " + chr(0x2014) + " pending counsel review"), (name, marker)
        assert re.search(r"""class=["'][^"']*\bdraft\b""", first.group(0)), name


def test_no_page_uses_banned_or_accusatory_wording():
    banned = [
        r"\bAI detect", r"\bcheat", r"authorship verification", r"\bfingerprint",
        r"lie detector", r"\baccura",
    ]
    for name, text in TEXT.items():
        for pattern in banned:
            assert not re.search(pattern, text, re.I), (name, pattern)


def test_no_page_claims_writing_is_never_analysed():
    # NORTH_STAR "Known conflicts": untrue for any workspace where Original is on.
    for name, text in TEXT.items():
        assert not re.search(r"does not analy[sz]e (?:a student's|your) writing style", text, re.I), name


def test_original_is_described_as_off_by_default_and_in_testing():
    for name in ("privacy.html", "student-notice.html"):
        text = TEXT[name]
        assert re.search(r"\boff\b[^.]*\bdefault\b|\bdefault\b[^.]*\boff\b", text, re.I), name
        assert "testing phase" in text.lower(), name
        assert re.search(r"never (?:as )?proof", text, re.I), name


# ── What is collected per sitting ───────────────────────────────────────────


def test_each_sitting_lists_what_is_kept_and_what_is_not():
    """bluebook.py bluebook_record_submission builds the stored row; Exam.jsx
    recordWarning sends five note types, type and time only."""
    for name in ("privacy.html", "student-notice.html"):
        text = TEXT[name].lower()
        for fact in (
            "answers",
            "deadline",
            "word count",
            "moved away from the exam window",
            "background",
            "full screen",
            "printing or saving",
            "paste",
            "only the kind of note and its time",
        ):
            assert fact in text, (name, fact)
        assert re.search(r"no(?:t record)?[^.]*keystroke", text), name
        assert re.search(r"ip address[^.]*not stored in (?:our|the) database", text), name


def test_the_note_cap_and_the_late_grace_period_match_the_code():
    from original import bluebook_rules as rules

    src = (ROOT / "original/routers/bluebook.py").read_text()
    assert "deadline + timedelta(seconds=300)" in src
    assert rules.MAX_WARNINGS == 500
    assert "500 notes" in TEXT["privacy.html"]
    assert "more than 5 minutes after the deadline" in TEXT["privacy.html"]


def test_keystroke_data_is_switched_off_in_the_code_the_pages_describe():
    from original import constants

    assert "behavioral" in constants.DISABLED_FEATURE_GROUPS


def test_no_database_table_has_a_column_for_a_network_address():
    from original.db.models import live  # noqa: F401  (registers the tables)
    from original.db.base import Base

    suspicious = re.compile(r"(^|_)(ip|ip_address|remote_addr|client_ip|user_agent)($|_)")
    for table in Base.metadata.tables.values():
        for column in table.columns:
            assert not suspicious.search(column.name), f"{table.name}.{column.name}"


# ── Retention ───────────────────────────────────────────────────────────────


def test_retention_defaults_are_stated_with_what_the_code_does_today():
    """365 days for work and 35 for backups are the stated defaults. Nothing
    in the live stack deletes work on a schedule yet (render.yaml's only cron
    is the backup), so the page must say automatic deletion is not on. When a
    deletion job lands, this test fails until the page is updated."""
    text = TEXT["privacy.html"]
    assert "365 days" in text and "35 days" in text
    crons = re.findall(r"- type: cron\s+name: (\S+)", (ROOT / "render.yaml").read_text())
    if crons == ["original-pg-backup"]:
        assert "not switched on yet" in text


def test_link_and_phone_parking_lifetimes_match_the_code():
    from original import invites
    from original.routers import proctor

    assert invites.INVITE_TTL.days == 14
    assert proctor.PARK_RETENTION_SECONDS == 24 * 3600
    assert "14 days" in TEXT["privacy.html"]
    assert "24 hours" in TEXT["privacy.html"] and "24 hours" in TEXT["student-notice.html"]


# ── Subprocessors ───────────────────────────────────────────────────────────


def test_subprocessors_are_named_with_what_each_receives():
    text = TEXT["privacy.html"]
    for name in ("Render", "Cloudflare R2", "SendGrid"):
        assert name in text, name
    assert "Oregon" in text
    assert re.findall(r"region: (\w+)", (ROOT / "render.yaml").read_text()) == ["oregon"] * 3


def test_email_goes_out_only_for_invitations_and_password_resets():
    src = (ROOT / "original/mailer.py").read_text()
    assert re.findall(r"^def (send_\w+)", src, re.M) == ["send_invite", "send_professor_invite", "send_reset"]
    assert "invitation and password-reset emails only" in TEXT["privacy.html"]


def test_backups_are_encrypted_before_they_leave_the_server():
    src = (ROOT / "scripts/pg_backup_offbox.py").read_text()
    assert "Fernet" in src
    assert "encrypted with a key we hold before" in TEXT["privacy.html"]


# ── Security and limits ─────────────────────────────────────────────────────


def test_password_storage_matches_the_code():
    from original import users

    assert users._ITERATIONS == 240_000
    assert "pbkdf2_hmac" in (ROOT / "original/users.py").read_text()
    assert "240,000" in TEXT["privacy.html"]


def test_the_free_workspace_limits_match_the_code():
    from original import bluebook_rules as rules

    text = TEXT["terms.html"]
    assert f"{rules.MAX_ENROLLED_STUDENTS} students" in text
    assert f"{rules.MAX_EXAMS} exams" in text
    assert f"{rules.MAX_SUBMISSIONS_PER_MONTH} submissions a month" in text


def test_the_app_sets_no_cookies():
    assert not re.search(r"set_cookie\(", "".join(
        p.read_text() for p in (ROOT / "original").rglob("*.py")
    ))
    assert "no cookies" in TEXT["privacy.html"].lower()


def test_the_exam_app_and_legal_pages_load_nothing_from_other_companies():
    """NORTH_STAR rule 7, and the privacy page's "no fonts, scripts or
    trackers from other companies"."""
    pages = [*(LEGAL.glob("*.html")), LEGAL / "legal.css", ROOT / "demo/bluebook/index.html",
             ROOT / "demo/bluebook/fonts.css", ROOT / "demo/bluebook/bluebook.bundle.css"]
    for page in pages:
        refs = re.findall(r"""(?:src|href)=["'](https?:)?//|url\((?:["'])?(?:https?:)?//""", page.read_text())
        assert not refs, page.name
