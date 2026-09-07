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

    def test_unknown_student_is_404(self, live_client, store_reset):
        """students.py:[113,114] — the `if state is None:` True arm, not hit
        by any existing readiness test (they all first create the student)."""
        r = live_client.get("/students/nope-nobody/readiness")

        assert r.status_code == 404
        assert "not found" in r.json()["detail"]

    def test_developing_verdict_with_word_stats_and_a_short_sample(
        self, live_client, store_reset
    ):
        """Two authenticated samples (one under 300 words) →
        [122,123] True (word_stats built), [135,136] True ("developing"
        verdict, auth>=2 but not ready), [141,146] False (auth != 0, skips
        the "first sample" rec), [151,152] True (word_stats.n_below_300 > 0
        rec)."""
        _, sid, _ = _login(live_client, "Readiness Academy Two", "dev@ready.edu")
        _add_sample(live_client, sid, text=GOOD_TEXT, assignment="a1")
        short_text = "A short baseline sample well under the 300-word floor. " * 5
        _add_sample(live_client, sid, text=short_text, assignment="a2")

        r = live_client.get(f"/students/{sid}/readiness")

        assert r.status_code == 200, r.text
        body = r.json()
        assert body["verdict"] == "developing"
        assert body["word_stats"] is not None
        assert body["word_stats"]["n_below_300"] == 1
        assert any("under 300" in rec for rec in body["recommendations"])

    def test_ready_verdict_with_no_recommendations_needed(self, live_client, store_reset):
        """Five authenticated samples across five distinct assignments →
        [133,134] True ("ready" verdict, auth>=5 and eff>=3), [146,151]
        False (auth not < 5, skips the "collect more" rec), and — with
        word_stats.n_below_300 == 0 and >1 distinct assignment — recs ends
        up empty, hitting [162,163] True (the "no action needed" filler)."""
        _, sid, _ = _login(live_client, "Readiness Academy Three", "ready@ready.edu")
        for i in range(5):
            _add_sample(live_client, sid, text=GOOD_TEXT, assignment=f"assignment-{i}")

        r = live_client.get(f"/students/{sid}/readiness")

        assert r.status_code == 200, r.text
        body = r.json()
        assert body["verdict"] == "ready"
        assert body["word_stats"]["n_below_300"] == 0
        assert body["recommendations"] == ["Baseline is in good shape — no action needed."]

    def test_single_assignment_recommendation(self, live_client, store_reset):
        """Three-plus samples that all share one assignment label →
        students.py:[157,158] True (the "collect across different
        assignments" rec)."""
        _, sid, _ = _login(live_client, "Readiness Academy Four", "single@ready.edu")
        for _ in range(3):
            _add_sample(live_client, sid, text=GOOD_TEXT, assignment="Midterm Essay")

        r = live_client.get(f"/students/{sid}/readiness")

        assert r.status_code == 200, r.text
        body = r.json()
        assert any("one assignment" in rec for rec in body["recommendations"])


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


# ── get_formation: read the active/most-recent pathway (never exercised) ────
# students.py:296-297 — the handler body itself, not a branch, but no
# existing test in the suite calls GET /students/{id}/formation at all.


class TestGetFormationReadModel:
    def test_no_open_pathway_returns_null(self, live_client, store_reset):
        _, sid, _ = _login(live_client, "GetFormation Academy", "gf1@getform.edu")

        r = live_client.get(f"/students/{sid}/formation")

        assert r.status_code == 200, r.text
        assert r.json() == {"pathway": None}

    def test_open_pathway_is_returned(self, live_client, store_reset):
        _, sid, _ = _login(live_client, "GetFormation Academy Two", "gf2@getform.edu")
        opened = live_client.post(f"/students/{sid}/formation")
        assert opened.status_code == 201, opened.text

        r = live_client.get(f"/students/{sid}/formation")

        assert r.status_code == 200, r.text
        assert r.json()["pathway"]["status"] == "open"


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

    def test_docx_upload_500s_when_python_docx_is_not_installed(
        self, live_client, store_reset, monkeypatch
    ):
        """students.py:[356,357] — `except ImportError` is only reachable
        when the optional `python-docx` dependency is absent. It IS
        installed in this venv (used by `_docx_bytes` above), so simulate
        its absence the standard way: set `sys.modules["docx"] = None`,
        which forces the next `from docx import Document` to raise
        ImportError (CPython import-system contract — verified empirically
        before writing this test)."""
        import sys

        monkeypatch.setitem(sys.modules, "docx", None)

        r = live_client.post(
            "/students/up-docx-noimport/upload",
            files={
                "file": (
                    "paper.docx",
                    io.BytesIO(b"not a real docx, never parsed"),
                    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                )
            },
        )

        assert r.status_code == 500
        assert "python-docx not installed" in r.json()["detail"]

    def test_pdf_upload_500s_when_pypdf_is_not_installed(
        self, live_client, store_reset, monkeypatch
    ):
        """students.py:[364,365] — same technique as the docx case above,
        for the `pypdf` optional dependency."""
        import sys

        monkeypatch.setitem(sys.modules, "pypdf", None)

        r = live_client.post(
            "/students/up-pdf-noimport/upload",
            files={"file": ("scan.pdf", io.BytesIO(b"not a real pdf"), "application/pdf")},
        )

        assert r.status_code == 500
        assert "pypdf not installed" in r.json()["detail"]


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


# ── me.py: my_work — both downstream-failure except arms ────────────────────
# my_work (me.py:81-125) always attempts add_baseline() first (always
# provenance="unverified", auth_weight=0.5 > 0 — so even an "unverified" add
# counts toward authenticated_count) and then score_submission(), catching an
# HTTPException from either without failing the request. me.py:[105,108] is
# add_baseline's exception; me.py:[114,116] is score_submission's.

U1 = (
    "The doctrine of vocation situates daily labor within a larger account of providence. "
    "Faithful work in an ordinary calling honors the same God who ordained the extraordinary. "
    "Scripture repeatedly affirms that diligence in one's station is itself a form of worship. "
) * 15
U2 = (
    "Systematic theology proceeds by careful attention to the whole counsel of Scripture. "
    "Each doctrine must be weighed against the entire canon rather than isolated proof texts. "
    "The task requires patience, humility, and a willingness to be corrected by the text. "
) * 15
U3 = (
    "Pastoral ministry demands both doctrinal precision and genuine compassion for the flock. "
    "A shepherd who neglects sound teaching fails his people as surely as one lacking mercy. "
    "The two callings, teaching and caring, are never rightly separated in faithful practice. "
) * 15
OUTLIER_TEXT = (
    "OMG!!! ur baseline thing is SOOO weird lol -- like, \"whatever\" (i guess); "
    "idk, u know?? c'mon -- don't u think so; totally, right?! "
    "e.g. this ain't gonna work; i.e. it's kinda broken -- (maybe) \"who knows\"; "
) * 15


class TestMyWorkExceptionArms:
    def test_add_baseline_drift_hold_is_swallowed_and_scoring_still_happens(
        self, live_client, store_reset
    ):
        """A wildly divergent /me/work submission trips the drift gate on
        the (already-established, stylistically-uniform) baseline, so
        add_baseline raises inside my_work — caught at me.py:[105,108] — but
        because authenticated samples already exist, score_submission still
        succeeds normally afterward (the "saved, not scored" fallback is
        NOT reached here; that's the other test below)."""
        token, sid, _ = _login(live_client, "MyWork Academy", "mw1@mywork.edu")
        for text in (U1, U2, U3):
            _add_sample(live_client, sid, text=text)

        r = live_client.post(
            "/me/work",
            headers={"Authorization": f"Bearer {token}"},
            json={"text": OUTLIER_TEXT, "title": "An odd submission"},
        )

        assert r.status_code == 200, r.text
        # Real score came back (not the generic "saved" fallback message),
        # proving score_submission ran against the pre-existing baseline.
        assert r.json()["headline"] != "Saved to your body of work."

    def test_falls_back_to_saved_not_scored_when_both_downstream_calls_fail(
        self, live_client, store_reset, monkeypatch
    ):
        """me.py:[114,116] — score_submission's HTTPException arm. On a
        genuinely fresh student, a successful add_baseline call always
        leaves authenticated_count >= 1 (every AUTH_WEIGHTS value is > 0,
        including "unverified"'s 0.5), so score_submission's own 422 can
        never fire after a real add. The only way to reach this arm is for
        add_baseline itself to fail without adding a sample — monkeypatched
        directly here (the handler's own contract: "if either downstream
        call raises, degrade to a saved-not-scored response" — a
        content-blind check, independent of *why* either call failed)."""
        from fastapi import HTTPException

        import original.routers.me as me_router

        def _boom(*args, **kwargs):
            raise HTTPException(status_code=422, detail="simulated add failure")

        monkeypatch.setattr(me_router, "add_baseline", _boom)

        token, _sid, _ = _login(live_client, "MyWork Academy Two", "mw2@mywork.edu")

        r = live_client.post(
            "/me/work",
            headers={"Authorization": f"Bearer {token}"},
            json={"text": U1, "title": "First ever submission"},
        )

        assert r.status_code == 200, r.text
        body = r.json()
        assert body["headline"] == "Saved to your body of work."
        assert body["review_opportunity"] is False
