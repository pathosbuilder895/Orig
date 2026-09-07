"""Branch tests for the Bbook HTTP client (part 4, task 1). No network I/O."""

from __future__ import annotations

import pytest

from original import bbook_client


class _FakeResponse:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self._payload = payload or {}

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise bbook_client.httpx.HTTPStatusError(
                "boom", request=None, response=None
            )


class _FakeClient:
    """Records the request; replays a canned response."""

    last_json = None
    response = _FakeResponse()

    def __init__(self, *a, **kw): ...
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def post(self, url, headers=None, json=None):
        type(self).last_json = json
        return type(self).response

    def get(self, url, headers=None):
        return type(self).response


@pytest.fixture
def bbook_env(monkeypatch):
    monkeypatch.setenv("BBOOK_API_URL", "https://bbook.example/")
    monkeypatch.setenv("BBOOK_EXTERNAL_SECRET", "test-secret")
    monkeypatch.setattr(bbook_client.httpx, "Client", _FakeClient)
    _FakeClient.last_json = None
    _FakeClient.response = _FakeResponse(
        200,
        {  # required fields per BaselineRequestResult: externalRequestId, examId, status
            "externalRequestId": "x-1", "examId": "e-1", "status": "pending",
        },
    )


class TestIsEnabled:
    def test_true_when_url_set(self, monkeypatch):
        monkeypatch.setenv("BBOOK_API_URL", "https://bbook.example/")
        assert bbook_client.is_enabled() is True

    def test_false_when_url_unset(self, monkeypatch):
        monkeypatch.delenv("BBOOK_API_URL", raising=False)
        assert bbook_client.is_enabled() is False


class TestHeaders:
    def test_missing_secret_raises(self, monkeypatch):
        monkeypatch.delenv("BBOOK_EXTERNAL_SECRET", raising=False)
        with pytest.raises(RuntimeError, match="BBOOK_EXTERNAL_SECRET"):
            bbook_client._headers()

    def test_secret_present(self, monkeypatch):
        monkeypatch.setenv("BBOOK_EXTERNAL_SECRET", "s")
        assert bbook_client._headers()["x-external-secret"] == "s"


class TestRequestBaseline:
    def test_unset_url_raises(self, monkeypatch):
        monkeypatch.delenv("BBOOK_API_URL", raising=False)
        with pytest.raises(RuntimeError, match="BBOOK_API_URL"):
            bbook_client.request_baseline(student_email="a@b.c", student_name="A")

    def test_minimal_payload_omits_every_optional_field(self, bbook_env):
        bbook_client.request_baseline(student_email="a@b.c", student_name="A")
        sent = _FakeClient.last_json
        assert set(sent) == {
            "externalRequestId", "studentEmail", "studentName",
            "examTitle", "durationMins",
        }

    def test_full_payload_includes_all_optional_fields_and_idempotency_key(self, bbook_env):
        bbook_client.request_baseline(
            student_email="a@b.c", student_name="A",
            institution_name="Sem", requested_by="prof@sem.edu",
            min_word_count=200, max_word_count=800,
            prompt_text="Discuss.", external_request_id="fixed-key",
        )
        sent = _FakeClient.last_json
        assert sent["externalRequestId"] == "fixed-key"
        assert sent["institutionName"] == "Sem"
        assert sent["requestedBy"] == "prof@sem.edu"
        assert sent["minWordCount"] == 200
        assert sent["maxWordCount"] == 800
        assert sent["promptText"] == "Discuss."


class TestFetchStatus:
    def test_404_maps_to_none(self, bbook_env):
        _FakeClient.response = _FakeResponse(404)
        assert bbook_client.fetch_status("nope") is None

    def test_unset_url_raises(self, monkeypatch):
        monkeypatch.delenv("BBOOK_API_URL", raising=False)
        with pytest.raises(RuntimeError):
            bbook_client.fetch_status("x")

    def test_success_returns_status(self, bbook_env):
        _FakeClient.response = _FakeResponse(
            200,
            {
                "externalRequestId": "x-1",
                "examId": "e-1",
                "status": "completed",
                "intendedForEmail": "a@b.c",
                "examTitle": "Proctored Baseline Sitting",
            },
        )
        result = bbook_client.fetch_status("x-1")
        assert isinstance(result, bbook_client.BaselineRequestStatus)
        assert result.status == "completed"
        assert result.intendedForEmail == "a@b.c"
