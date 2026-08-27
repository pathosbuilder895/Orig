"""Replay TermSim events through the live FastAPI routes."""
from __future__ import annotations

from collections.abc import Callable
from datetime import date, timedelta
import fcntl
import hashlib
from pathlib import Path

import numpy as np

from original.principal import mint_principal_token


def install_vector_cache(cache_dir: Path) -> None:
    """Patch only the harness route bindings; production extraction is untouched."""
    from original.constants import BASE_FEATURE_DIM
    from original.features.pipeline import feature_vector as extract
    from original.routers import students_baseline, students_scoring

    cache_dir.mkdir(parents=True, exist_ok=True)

    def cached(text: str, keystroke_data=None):
        # Behavioral features are request-specific and deliberately bypassed.
        if keystroke_data:
            return extract(text, keystroke_data=keystroke_data)
        key = hashlib.sha256(f"{BASE_FEATURE_DIM}\0{text}".encode()).hexdigest()
        path = cache_dir / f"{key}.npy"
        lock_path = cache_dir / f"{key}.lock"
        with lock_path.open("w") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            if path.exists():
                return np.load(path)
            vector = extract(text)
            temporary = path.with_suffix(".tmp.npy")
            np.save(temporary, vector)
            temporary.replace(path)
            return vector

    students_baseline.feature_vector = cached
    students_scoring.feature_vector = cached


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
            # 202/409 are the drift gate holding the upload — a legitimate
            # deployment outcome this harness exists to measure, not an error.
            if response.status_code not in (200, 202, 409):
                raise RuntimeError(f"baseline HTTP {response.status_code}: {response.text}")
            held = response.status_code != 200
            if not held:
                baseline_counts[student] = baseline_counts.get(student, 0) + 1
            row = dict(event)
            row["drift_gate_held"] = held
            output.append(row)
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
        llr = payload["authorship"].get("llr_deviation_score")
        row = dict(event)
        row.update(
            {
                "action": payload["recommendation"]["action"],
                "deviation_score": payload["authorship"]["deviation_score"],
                "llr_deviation_score": llr,
                "typicality_n": payload.get("typicality_n"),
                "typicality_abstained": not bool(payload.get("typicality_n")),
                "topic_distance": payload.get("topic_distance"),
                "inflation_fired": payload.get("topic_inflation_applied"),
                "null_abstained": llr is None,
                "fused_abstained": payload.get("fused_score") is None,
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
            if accepted.status_code not in (200, 202, 409):
                raise RuntimeError(
                    f"accrete HTTP {accepted.status_code}: {accepted.text}"
                )
            held = accepted.status_code != 200
            if not held:
                baseline_counts[student] = baseline_counts.get(student, 0) + 1
            accrete_row = dict(event)
            accrete_row.update({"kind": "accrete", "drift_gate_held": held})
            output.append(accrete_row)
    return output
