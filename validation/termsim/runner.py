"""Replay TermSim events through the live FastAPI routes."""
from __future__ import annotations

from collections.abc import Callable
from datetime import date, timedelta

from original.principal import mint_principal_token


def run_events(
    client, events: list[dict], text_for: Callable[[dict], str], accrete=False
) -> list[dict]:
    """Execute an already-generated script; no scoring internals are called."""
    output = []
    baseline_counts: dict[str, int] = {}
    headers: dict[str, dict[str, str]] = {}
    start = date(2026, 1, 12)
    for event in events:
        text = text_for(event)
        submitted_at = (start + timedelta(weeks=event["week"])).isoformat()
        student = event["student"]
        tenant = event["tenant"]
        if tenant not in headers:
            client.post(
                "/tenants",
                json={"tenant_id": tenant, "name": f"TermSim {tenant}", "environment": "demo"},
            )
            token = mint_principal_token(f"prof-{tenant}", "professor", tenant)
            headers[tenant] = {"Authorization": f"Bearer {token}"}
        if event["kind"] == "baseline":
            response = client.post(
                f"/students/{student}/baseline",
                json={"text": text, "provenance": "verified", "submitted_at": submitted_at},
                headers=headers[tenant],
            )
            if response.status_code != 200:
                raise RuntimeError(f"baseline HTTP {response.status_code}: {response.text}")
            baseline_counts[student] = baseline_counts.get(student, 0) + 1
            continue

        response = client.post(
            f"/students/{student}/score",
            json={"text": text, "submission_id": f"termsim-{student}-{event['week']}",
                  "submitted_at": submitted_at},
            headers=headers[tenant],
        )
        if response.status_code != 200:
            raise RuntimeError(f"score HTTP {response.status_code}: {response.text}")
        payload = response.json()
        row = dict(event)
        row.update(
            {
                "action": payload["recommendation"]["action"],
                "deviation_score": payload["authorship"]["deviation_score"],
                "llr_deviation_score": payload.get("llr_deviation_score"),
                "typicality_n": payload.get("typicality_n"),
                "topic_distance": payload.get("topic_distance"),
                "baseline_count": baseline_counts.get(student, 0),
            }
        )
        output.append(row)
        if accrete:
            accepted = client.post(
                f"/students/{student}/baseline",
                json={"text": text, "provenance": "verified", "submitted_at": submitted_at},
                headers=headers[tenant],
            )
            if accepted.status_code == 200:
                baseline_counts[student] = baseline_counts.get(student, 0) + 1
    return output
