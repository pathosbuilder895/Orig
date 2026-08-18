"""Branch tests for original/routers/students_baseline.py (part 2, task 1).

Covers the batch importer (POST /students/{id}/baseline/upload-batch), the
single-sample endpoint (POST /students/{id}/baseline), the Bbook
proctored-baseline request endpoint, and the remaining arms of the
``_existing_text_hashes`` dedup helper.
"""

from __future__ import annotations

import io

BATCH = "/students/{sid}/baseline/upload-batch"
SINGLE = "/students/{sid}/baseline"
REQUEST_BASELINE = "/students/{sid}/request-baseline"

GOOD_TEXT = (
    "The doctrine of vocation, as articulated in the letters, situates daily labor "
    "within a larger account of providence. " * 30
)

# ── Stylistically-uniform baseline texts + a wildly different outlier ─────────
# Used to exercise the Phase 8 drift gate on both the single-add endpoint
# (202 flag_for_review / 409 rebaseline) and the batch endpoint's soft
# per-file drift_holds. Anchor tiers 4 (char/punctuation) and 6 (idiosyncratic)
# are what check_drift compares by default; the outlier leans hard on
# contractions, semicolons, dashes, and quotes to push those tiers past the
# 0.30 magnitude threshold (verified empirically against StudentState.check_drift).
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

# ── Text engineered to produce a non-zero tension-arc catastrophe index ───────
# analyze_tension_arc needs paragraph-to-paragraph variance in resolution ratio:
# one paragraph that raises tension (But/However/Although...) and never
# resolves it, another that raises tension and then explicitly resolves it
# (Therefore/Thus/In conclusion...). Verified empirically to yield
# catastrophe_index > 0 (kappa ~0.108) via original.tension_arc.analyze_tension_arc.
_ARC_UNRESOLVED = (
    "But the committee could not agree on the wording of the final clause. "
    "However the chair pressed forward without a vote, hoping consensus would emerge later. "
    "Although several members objected in the hallway afterward, no formal record was made. "
    "Yet the deadline loomed, and nobody wanted to be the one who delayed the report further. "
    "While some believed the omission was deliberate, others thought it simple oversight. "
    "Despite repeated requests, the missing appendix was never actually produced by anyone. "
)
_ARC_RESOLVED = (
    "But the initial data seemed to contradict the working hypothesis entirely. "
    "However repeated trials under controlled conditions told a different story. "
    "Therefore the team concluded the original anomaly was an instrument error. "
    "Thus the hypothesis was retained, and the paper was submitted for review. "
    "In conclusion the discrepancy resolved itself once the calibration was fixed. "
    "Finally the committee approved the manuscript for publication without further delay. "
)
CATASTROPHE_TEXT = (_ARC_UNRESOLVED + "\n\n" + _ARC_RESOLVED) * 3


def _post_files(client, sid, files, provenance="verified", assignment=""):
    return client.post(
        BATCH.format(sid=sid),
        files=[("files", f) for f in files],
        data={"provenance": provenance, "assignment": assignment},
    )


def _add_baseline(client, sid, text, provenance="verified", **extra):
    payload = {"text": text, "provenance": provenance, "assignment": ""}
    payload.update(extra)
    return client.post(SINGLE.format(sid=sid), json=payload)


class TestUploadBatchBranches:
    def test_unknown_provenance_is_422(self, live_client, store_reset):
        r = _post_files(
            live_client, "s-batch-1",
            [("a.txt", io.BytesIO(GOOD_TEXT.encode()), "text/plain")],
            provenance="notarized",
        )
        assert r.status_code == 422
        assert "provenance" in r.json()["detail"]

    def test_txt_import_and_duplicate_skip(self, live_client, store_reset):
        payload = [("a.txt", io.BytesIO(GOOD_TEXT.encode()), "text/plain")]
        first = _post_files(live_client, "s-batch-2", payload)
        assert first.status_code == 200
        assert first.json()["imported"] == 1

        again = _post_files(
            live_client, "s-batch-2",
            [("b.txt", io.BytesIO(GOOD_TEXT.encode()), "text/plain")],
        )
        body = again.json()
        assert body["imported"] == 0
        assert body["skipped_duplicates"] == 1

    def test_unsupported_extension_is_reported_not_fatal(self, live_client, store_reset):
        r = _post_files(
            live_client, "s-batch-3",
            [
                ("notes.rtf", io.BytesIO(b"whatever"), "application/rtf"),
                ("ok.txt", io.BytesIO(GOOD_TEXT.encode()), "text/plain"),
            ],
        )
        body = r.json()
        assert body["imported"] == 1
        assert any("unsupported type" in e for e in body["errors"])

    def test_empty_text_file_is_reported(self, live_client, store_reset):
        r = _post_files(
            live_client, "s-batch-4",
            [("empty.txt", io.BytesIO(b"   \n"), "text/plain")],
        )
        assert any("no text extracted" in e for e in r.json()["errors"])

    def test_corrupt_docx_hits_the_extraction_error_arm(self, live_client, store_reset):
        r = _post_files(
            live_client, "s-batch-5",
            [("broken.docx", io.BytesIO(b"not a zip archive"), "application/msword")],
        )
        assert any("extraction error" in e for e in r.json()["errors"])

    def test_extensionless_filename_takes_the_no_dot_arm(self, live_client, store_reset):
        r = _post_files(
            live_client, "s-batch-6",
            [("README", io.BytesIO(GOOD_TEXT.encode()), "text/plain")],
        )
        assert any("unsupported type" in e for e in r.json()["errors"])


# ── Step 3: remaining upload_baseline_batch arms ──────────────────────────────


class TestUploadBatchRemainingArms:
    def test_pdf_extraction_error_hits_the_pdf_arm(self, live_client, store_reset):
        """Not a real PDF, but enters the ``elif ext == "pdf"`` branch and is
        caught by the same extraction-error path as the corrupt-docx arm."""
        r = _post_files(
            live_client, "s-batch-pdf",
            [("broken.pdf", io.BytesIO(b"not a pdf file"), "application/pdf")],
        )
        assert any("extraction error" in e for e in r.json()["errors"])

    def test_non_authenticated_provenance_skips_tension_arc_update(self, live_client, store_reset):
        """provenance not in ('proctored', 'verified') must still import the
        sample but skip the tension-arc kappa update (line 436's false arm)."""
        r = _post_files(
            live_client, "s-batch-unverified",
            [("a.txt", io.BytesIO(GOOD_TEXT.encode()), "text/plain")],
            provenance="unverified",
        )
        assert r.status_code == 200, r.text
        assert r.json()["imported"] == 1

    def test_catastrophe_index_positive_updates_baseline_kappa(self, live_client, store_reset):
        """A submission whose tension arc actually resolves/unresolves across
        paragraphs takes the ``catastrophe_index > 0`` arm (line 438 true)."""
        r = _post_files(
            live_client, "s-batch-catastrophe",
            [("arc.txt", io.BytesIO(CATASTROPHE_TEXT.encode()), "text/plain")],
        )
        assert r.status_code == 200, r.text
        assert r.json()["imported"] == 1

    def test_duplicate_within_the_same_batch_is_skipped(self, live_client, store_reset):
        """Two files with identical text in ONE request must dedup against
        each other too, not just against a student's already-persisted
        samples (test_txt_import_and_duplicate_skip, above) — regression
        pin for the seen_hashes fix: it must grow as files are admitted
        within a single call, not only seed from prior requests."""
        r = _post_files(
            live_client, "s-batch-samecall-dup",
            [
                ("x.txt", io.BytesIO(GOOD_TEXT.encode()), "text/plain"),
                ("y.txt", io.BytesIO(GOOD_TEXT.encode()), "text/plain"),
            ],
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["imported"] == 1
        assert body["skipped_duplicates"] == 1

    def test_drift_outlier_is_held_not_imported(self, live_client, store_reset):
        """Three stylistically-uniform baselines establish a baseline_mean;
        a wildly different fourth file trips check_drift (magnitude > 0.30)
        and is recorded in drift_holds instead of being imported."""
        sid = "s-batch-drift"
        baseline_files = [
            (f"u{i}.txt", io.BytesIO(txt.encode()), "text/plain")
            for i, txt in enumerate([U1, U2, U3])
        ]
        setup = _post_files(live_client, sid, baseline_files)
        assert setup.status_code == 200, setup.text
        assert setup.json()["imported"] == 3

        r = _post_files(
            live_client, sid,
            [("outlier.txt", io.BytesIO(OUTLIER_TEXT.encode()), "text/plain")],
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["imported"] == 0
        assert len(body["drift_holds"]) == 1
        assert body["drift_holds"][0]["filename"] == "outlier.txt"
        assert body["drift_holds"][0]["drift"]["recommendation"] in (
            "flag_for_review",
            "rebaseline",
        )


# ── Step 3: add_baseline (single-sample endpoint) remaining arms ─────────────


class TestAddBaselineBranches:
    def test_unknown_provenance_is_422(self, live_client, store_reset):
        r = _add_baseline(live_client, "s-addbase-badprov", GOOD_TEXT, provenance="notarized")
        assert r.status_code == 422
        assert "provenance" in r.json()["detail"]

    def test_catastrophe_index_positive_updates_baseline_kappa(self, live_client, store_reset):
        r = _add_baseline(live_client, "s-addbase-catastrophe", CATASTROPHE_TEXT)
        assert r.status_code == 200, r.text

    def test_drift_check_exception_leaves_drift_result_none(
        self, live_client, store_reset, monkeypatch
    ):
        """check_drift is best-effort: if it raises, the sample is still
        admitted and the response simply omits the "drift" key (line 198's
        false arm) instead of failing the request."""
        from original.quantum.state import StudentState

        def _boom(self, *args, **kwargs):
            raise RuntimeError("simulated check_drift failure")

        monkeypatch.setattr(StudentState, "check_drift", _boom)

        r = _add_baseline(live_client, "s-addbase-drift-exc", GOOD_TEXT)
        assert r.status_code == 200, r.text
        assert "drift" not in r.json()

    def test_authenticated_add_completes_pending_baseline_request(
        self, live_client, store_reset, monkeypatch
    ):
        """An authenticated add must auto-complete any outstanding
        magic-link baseline request for the same student (line 200's true
        arm) — the pending request is created for real through the
        request-baseline endpoint, with Bbook itself stubbed out."""
        import original.bbook_client as bbook_client

        monkeypatch.setattr(bbook_client, "is_enabled", lambda: True)
        result = bbook_client.BaselineRequestResult(
            externalRequestId="ext-complete-1",
            examId="exam-complete-1",
            status="pending",
            expiresAt=None,
            emailDelivered=False,
            magicLink="https://bbook.example/magic/complete",
        )
        monkeypatch.setattr(bbook_client, "request_baseline", lambda **kw: result)

        sid = "s-addbase-complete"
        rb = live_client.post(
            REQUEST_BASELINE.format(sid=sid),
            json={"student_email": "complete@x.edu", "student_name": "Completer"},
        )
        assert rb.status_code == 200, rb.text
        external_id = rb.json()["external_request_id"]

        r = _add_baseline(live_client, sid, GOOD_TEXT)
        assert r.status_code == 200, r.text
        assert r.json().get("completed_baseline_requests") == [external_id]

    def test_seal_replay_guard_returns_duplicate_skip(self, live_client, store_reset):
        """A retried baseline upload carrying the same submission_uuid as a
        prior one must not double-count an identical text as a second
        sample — the seal-replay guard's duplicate-skip return (line 68's
        true arm)."""
        sid = "s-addbase-seal-replay"
        first = _add_baseline(live_client, sid, GOOD_TEXT, submission_uuid="seal-uuid-1")
        assert first.status_code == 200, first.text
        assert first.json().get("skipped") is not True

        again = _add_baseline(live_client, sid, GOOD_TEXT, submission_uuid="seal-uuid-1")
        assert again.status_code == 200, again.text
        body = again.json()
        assert body["skipped"] is True
        assert body["reason"] == "duplicate_text"

    def test_self_asserted_trusted_provenance_flags_downgrade_in_response(
        self, live_client, store_reset
    ):
        """A student token self-asserting a trusted provenance without a
        proctor attestation is downgraded to 'unverified' — the response
        must surface provenance_downgraded/requested_provenance (line 193's
        true arm) so a UI can explain the weaker sample rather than hide it."""
        from original import principal as pr

        sid = "acme:selfassert-addbase"
        token = pr.mint_principal_token(sid, "student", "acme")
        r = live_client.post(
            SINGLE.format(sid=sid),
            json={"text": GOOD_TEXT, "provenance": "verified", "assignment": ""},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["provenance_downgraded"] is True
        assert body["requested_provenance"] == "verified"


class TestAddBaselineDriftHold:
    """Pins the 202 (flag_for_review) / 409 (rebaseline) drift-gate arms on
    the single-add endpoint: three uniform baselines, then an outlier."""

    def _seed_baseline(self, live_client, sid):
        for txt in (U1, U2, U3):
            r = _add_baseline(live_client, sid, txt)
            assert r.status_code == 200, r.text

    def test_first_outlier_returns_202_flag_for_review(self, live_client, store_reset):
        sid = "s-addbase-drift-202"
        self._seed_baseline(live_client, sid)

        r = _add_baseline(live_client, sid, OUTLIER_TEXT)
        assert r.status_code == 202, r.text
        detail = r.json()["detail"]
        assert detail["status"] == "pending_review"
        assert detail["drift"]["recommendation"] == "flag_for_review"

    def test_second_consecutive_outlier_returns_409_rebaseline(self, live_client, store_reset):
        sid = "s-addbase-drift-409"
        self._seed_baseline(live_client, sid)

        first = _add_baseline(live_client, sid, OUTLIER_TEXT)
        assert first.status_code == 202, first.text

        second = _add_baseline(live_client, sid, OUTLIER_TEXT)
        assert second.status_code == 409, second.text
        detail = second.json()["detail"]
        assert detail["status"] == "rebaseline_required"
        assert detail["drift"]["recommendation"] == "rebaseline"


# ── Step 3: request_proctored_baseline (Bbook integration) ───────────────────


class TestRequestProctoredBaseline:
    @staticmethod
    def _stub_result(bbook_client, **overrides):
        base = dict(
            externalRequestId="ext-stub",
            examId="exam-stub",
            status="pending",
            expiresAt=None,
            emailDelivered=False,
            magicLink="https://bbook.example/magic/stub",
        )
        base.update(overrides)
        return bbook_client.BaselineRequestResult(**base)

    def test_disabled_returns_503(self, live_client, store_reset, monkeypatch):
        import original.bbook_client as bbook_client

        monkeypatch.setattr(bbook_client, "is_enabled", lambda: False)

        r = live_client.post(
            REQUEST_BASELINE.format(sid="s-req-disabled"),
            json={"student_email": "d@x.edu", "student_name": "Dee"},
        )
        assert r.status_code == 503
        assert "not configured" in r.json()["detail"]

    def test_success_with_expiry_parses_the_date(self, live_client, store_reset, monkeypatch):
        import original.bbook_client as bbook_client

        monkeypatch.setattr(bbook_client, "is_enabled", lambda: True)
        result = self._stub_result(bbook_client, expiresAt="2026-05-18T12:00:00Z")
        monkeypatch.setattr(bbook_client, "request_baseline", lambda **kw: result)

        r = live_client.post(
            REQUEST_BASELINE.format(sid="s-req-expiry"),
            json={"student_email": "e@x.edu", "student_name": "Em"},
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["bbook_exam_id"] == "exam-stub"
        assert body["expires_at"] is not None
        assert body["expires_at_iso"] is not None

    def test_success_without_expiry_skips_date_parsing(self, live_client, store_reset, monkeypatch):
        import original.bbook_client as bbook_client

        monkeypatch.setattr(bbook_client, "is_enabled", lambda: True)
        result = self._stub_result(bbook_client, expiresAt=None)
        monkeypatch.setattr(bbook_client, "request_baseline", lambda **kw: result)

        r = live_client.post(
            REQUEST_BASELINE.format(sid="s-req-noexpiry"),
            json={"student_email": "n@x.edu", "student_name": "En"},
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["bbook_exam_id"] == "exam-stub"
        assert body["expires_at"] is None


# ── Step 3: _existing_text_hashes remaining arms ──────────────────────────────


class TestExistingTextHashesRemainingArms:
    def test_legacy_sample_without_hash_or_text_is_skipped_during_dedup_scan(
        self, live_client, store_reset
    ):
        """A sample added via the single-add endpoint never carries the
        .text_hash attribute the batch importer stamps on — that's the
        "legacy paste-added" case _existing_text_hashes falls back to hashing
        .text for. An *empty*-text sample additionally has no usable .text
        either, so the loop must skip it cleanly (neither computing nor
        recording a hash) rather than erroring, exercising both remaining
        arms of the helper in one pass."""
        sid = "s-hash-legacy"
        first = _add_baseline(
            live_client, sid, "", provenance="unverified", submission_uuid="uuid-empty-1"
        )
        assert first.status_code == 200, first.text

        second = _add_baseline(
            live_client, sid, GOOD_TEXT, provenance="verified", submission_uuid="uuid-real-1"
        )
        assert second.status_code == 200, second.text
        assert second.json()["sample_index"] == 1
