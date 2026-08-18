"""
tests/test_students_router_branches.py — branch-coverage gap-fill for
original/routers/students.py + original/routers/me.py (SDD Part 2, Task 2).

Every test drives the live stack via HTTP (live_client + store_reset — see
tests/test_students_baseline_batch.py for the established idiom). Targets the
22 branch arms the coverage baseline (.superpowers/sdd/coverage-baseline.json)
marks as never taken:

  students.py (19 arms):
    list_students           1 — the `elif tenant_id:` demo/anonymous filter arm
    get_student_readiness   2 — empty word_counts + auth==0 recommendation arm
    get_sample_text         4 — student-not-found / index-out-of-range / found
    delete_student          1 — not-found 404 arm
    student_data_inventory  1 — not-found 404 arm
    open_formation          2 — success + the pathway-is-None 500 arm
    advance_formation       2 — no-open-pathway 404 + success arm
    upload_file             6 — txt / docx / pdf / unsupported-ext arcs

  me.py (3 arms):
    my_voice                1 — unknown-student fallback (empty baseline)
    my_formation_advance    2 — open-if-none arm + reuse-existing-open arm
"""

from __future__ import annotations

import io

import original.student_auth as student_auth

GOOD_TEXT = (
    "The doctrine of vocation, as articulated in the letters, situates daily labor "
    "within a larger account of providence. " * 30
)


def _login(client, institution, email, name=""):
    r = client.post(
        "/student-auth/login",
        json={"email": email, "institution": institution, "name": name or email},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    return body["token"], body["student_id"], body["tenant_id"]


def _add_sample(client, sid, text=GOOD_TEXT, provenance="verified", assignment=""):
    r = client.post(
        f"/students/{sid}/baseline",
        json={"text": text, "provenance": provenance, "assignment": assignment},
    )
    assert r.status_code == 200, r.text
    return r


def _docx_bytes(paragraphs: list[str]) -> bytes:
    from docx import Document

    doc = Document()
    for p in paragraphs:
        doc.add_paragraph(p)
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


def _blank_pdf_bytes() -> bytes:
    from pypdf import PdfWriter

    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()


# ── list_students: the anonymous/demo `elif tenant_id:` filter arm ───────────
# (students.py:48-49). The first branch — an authenticated, non-super
# principal always scoped to its own tenant — is already exercised elsewhere;
# what's missing is the *unauthenticated* (demo) caller explicitly passing
# ?tenant_id=. No Authorization header ⇒ resolve_principal() returns the
# anonymous demo principal (is_demo=True), so the first `if` is false and the
# `elif tenant_id:` arm is the one under test.


class TestListStudentsFilterArm:
    def test_anonymous_tenant_id_query_param_filters_roster(self, live_client, store_reset):
        _, sid, tenant_id = _login(live_client, "Filter Academy", "student@filter.edu")

        r = live_client.get("/students", params={"tenant_id": tenant_id})

        assert r.status_code == 200, r.text
        body = r.json()
        assert sid in body["students"]
        assert body["roster"] is not None
        assert any(row["id"] == sid for row in body["roster"])


# ── get_student_readiness: empty word_counts + auth==0 recommendation ────────
# A brand-new student (created via login, no baseline samples yet) has
# word_counts == [] (skips the BaselineWordStats construction, students.py:122
# false arm) and authenticated_count == 0 (students.py:141 true arm) in the
# same call.


class TestGetStudentReadinessMissingArms:
    def test_fresh_student_zero_samples_hits_both_missing_arms(self, live_client, store_reset):
        _, sid, _ = _login(live_client, "Readiness Academy", "fresh@ready.edu")

        r = live_client.get(f"/students/{sid}/readiness")

        assert r.status_code == 200, r.text
        body = r.json()
        assert body["verdict"] == "insufficient"
        assert body["word_stats"] is None
        assert any(
            "first proctored writing sample" in rec for rec in body["recommendations"]
        )


# ── get_sample_text: student-not-found / index-out-of-range / found ─────────


class TestGetSampleTextArms:
    def test_unknown_student_is_404(self, live_client, store_reset):
        r = live_client.get("/students/nope-nobody/samples/0/text")

        assert r.status_code == 404
        assert "not found" in r.json()["detail"]

    def test_index_out_of_range_is_404(self, live_client, store_reset):
        _, sid, _ = _login(live_client, "Sample Academy", "s1@sample.edu")
        _add_sample(live_client, sid)

        r = live_client.get(f"/students/{sid}/samples/5/text")

        assert r.status_code == 404
        assert "out of range" in r.json()["detail"]

    def test_valid_index_returns_the_retained_sample_text(self, live_client, store_reset):
        _, sid, _ = _login(live_client, "Sample Academy Two", "s2@sample.edu")
        _add_sample(live_client, sid, assignment="Essay 1")

        r = live_client.get(f"/students/{sid}/samples/0/text")

        assert r.status_code == 200, r.text
        body = r.json()
        assert body["text"] == GOOD_TEXT
        assert body["assignment"] == "Essay 1"
        assert body["word_count"] == len(GOOD_TEXT.split())
        assert body["char_count"] == len(GOOD_TEXT)


# ── delete_student: the not-found arm ────────────────────────────────────────


class TestDeleteStudentNotFoundArm:
    def test_deleting_unknown_student_is_404(self, live_client, store_reset):
        r = live_client.delete("/students/does-not-exist-at-all")

        assert r.status_code == 404
        assert "nothing to delete" in r.json()["detail"]


# ── student_data_inventory: the not-found arm ────────────────────────────────


class TestStudentDataInventoryArm:
    def test_unknown_student_is_404(self, live_client, store_reset):
        r = live_client.get("/students/nobody-here/data-inventory")

        assert r.status_code == 404
        assert "not found" in r.json()["detail"]


# ── open_formation: success + the pathway-is-None 500 arm ───────────────────


class TestOpenFormationArms:
    def test_opens_a_new_pathway_returns_201(self, live_client, store_reset):
        _, sid, _ = _login(live_client, "Formation Academy", "f1@formation.edu")

        r = live_client.post(f"/students/{sid}/formation")

        assert r.status_code == 201, r.text
        pathway = r.json()["pathway"]
        assert pathway["status"] == "open"
        assert pathway["current_step"] == 0

    def test_store_failure_surfaces_as_500(self, live_client, store_reset, monkeypatch):
        """open_formation_pathway returns None only when the underlying store
        write fails (a swallowed exception) — simulate that directly rather
        than trying to break real SQLite, mirroring the check_drift-exception
        idiom in test_students_baseline_batch.py."""
        from original import store as store_mod

        monkeypatch.setattr(store_mod, "open_formation_pathway", lambda *a, **kw: None)

        r = live_client.post("/students/f2-fail/formation")

        assert r.status_code == 500
        assert "Could not open formation pathway" in r.json()["detail"]


# ── advance_formation: no-open-pathway 404 + success arm ────────────────────


class TestAdvanceFormationArms:
    def test_no_open_pathway_is_404(self, live_client, store_reset):
        r = live_client.post("/students/never-opened/formation/advance")

        assert r.status_code == 404
        assert "No open formation pathway" in r.json()["detail"]

    def test_advances_an_open_pathway_returns_200(self, live_client, store_reset):
        _, sid, _ = _login(live_client, "Advance Academy", "a1@advance.edu")
        opened = live_client.post(f"/students/{sid}/formation")
        assert opened.status_code == 201, opened.text

        r = live_client.post(f"/students/{sid}/formation/advance")

        assert r.status_code == 200, r.text
        assert r.json()["pathway"]["current_step"] == 1


# ── upload_file (single-file extraction): txt / docx / pdf / unsupported ────


class TestUploadFileArms:
    def test_txt_extension_extracts_text(self, live_client, store_reset):
        r = live_client.post(
            "/students/up-txt/upload",
            files={"file": ("essay.txt", io.BytesIO(GOOD_TEXT.encode()), "text/plain")},
        )

        assert r.status_code == 200, r.text
        body = r.json()
        assert body["text"] == GOOD_TEXT
        assert body["filename"] == "essay.txt"
        assert body["word_count"] == len(GOOD_TEXT.split())

    def test_docx_extension_extracts_text(self, live_client, store_reset):
        raw = _docx_bytes(["First paragraph.", "Second paragraph."])

        r = live_client.post(
            "/students/up-docx/upload",
            files={
                "file": (
                    "paper.docx",
                    io.BytesIO(raw),
                    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                )
            },
        )

        assert r.status_code == 200, r.text
        body = r.json()
        assert body["text"] == "First paragraph.\n\nSecond paragraph."

    def test_pdf_extension_extracts_text(self, live_client, store_reset):
        raw = _blank_pdf_bytes()

        r = live_client.post(
            "/students/up-pdf/upload",
            files={"file": ("scan.pdf", io.BytesIO(raw), "application/pdf")},
        )

        assert r.status_code == 200, r.text
        body = r.json()
        assert body["filename"] == "scan.pdf"
        assert body["text"] == ""  # blank page ⇒ no extractable text, still 200
        assert body["word_count"] == 0

    def test_unsupported_extension_is_422(self, live_client, store_reset):
        r = live_client.post(
            "/students/up-bad/upload",
            files={"file": ("notes.rtf", io.BytesIO(b"whatever"), "application/rtf")},
        )

        assert r.status_code == 422
        assert "Unsupported file type" in r.json()["detail"]

    def test_extensionless_filename_is_422(self, live_client, store_reset):
        r = live_client.post(
            "/students/up-nodot/upload",
            files={"file": ("README", io.BytesIO(GOOD_TEXT.encode()), "text/plain")},
        )

        assert r.status_code == 422
        assert "Unsupported file type" in r.json()["detail"]

    def test_empty_txt_file_is_a_zero_word_count_not_an_error(self, live_client, store_reset):
        r = live_client.post(
            "/students/up-empty/upload",
            files={"file": ("empty.txt", io.BytesIO(b"   \n"), "text/plain")},
        )

        assert r.status_code == 200, r.text
        assert r.json()["word_count"] == 0


# ── me.py: my_voice unknown-student fallback ─────────────────────────────────
# A signed session token is self-contained (student_auth.mint_session doesn't
# touch the store), so a token can be valid for a student id the store has
# never seen — e.g. a session that outlived a FERPA deletion, or a token
# minted before the first /me/work call created the record. `_repo().get(sid)`
# returns None and my_voice must fall back to a neutral, empty-baseline view
# rather than 404/500.


class TestMyVoiceFallbackArm:
    def test_unknown_student_id_falls_back_to_neutral_baseline(self, live_client, store_reset):
        token = student_auth.mint_session("ghost-tenant:never-persisted", "Ghost Student")

        r = live_client.get("/me/voice", headers={"Authorization": f"Bearer {token}"})

        assert r.status_code == 200, r.text
        body = r.json()
        assert len(body["fingerprint"]) == 7
        assert all(dim["value"] == 0.5 for dim in body["fingerprint"])
        assert body["milestones"]  # still renders the 3 named milestones, all "upcoming"


# ── me.py: my_formation_advance — open-if-none vs. reuse-existing-open ──────


class TestMyFormationAdvanceArms:
    def test_opens_a_pathway_when_none_exists(self, live_client, store_reset):
        token, _sid, _ = _login(live_client, "MeFormation Academy", "mf1@meform.edu")

        r = live_client.post(
            "/me/formation/advance", headers={"Authorization": f"Bearer {token}"}
        )

        assert r.status_code == 200, r.text
        formation = r.json()["formation"]
        assert formation["active"] is True
        assert formation["current_step"] == 1

    def test_reuses_an_already_open_pathway(self, live_client, store_reset):
        token, sid, _ = _login(live_client, "MeFormation Academy Two", "mf2@meform.edu")
        opened = live_client.post(f"/students/{sid}/formation")
        assert opened.status_code == 201, opened.text
        advanced_once = live_client.post(f"/students/{sid}/formation/advance")
        assert advanced_once.status_code == 200, advanced_once.text
        assert advanced_once.json()["pathway"]["current_step"] == 1

        r = live_client.post(
            "/me/formation/advance", headers={"Authorization": f"Bearer {token}"}
        )

        assert r.status_code == 200, r.text
        # If the "no pathway" branch were wrongly taken, open_formation_pathway
        # would be idempotent-return the existing open pathway at current_step
        # 1 unchanged, then advance to 2 anyway — so the real discriminator is
        # that current_step reaches 2 via ONE additional advance, not a reset
        # to 0 followed by an advance to 1.
        assert r.json()["formation"]["current_step"] == 2
