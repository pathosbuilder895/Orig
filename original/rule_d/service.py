"""Glue between rule D and the live stack: profile upkeep and the per-request observation.

Profiles are derived from each teacher-approved past paper (a baseline sample with text) and
stored in ``rule_d_profiles``, keyed by the SHA-256 of the paper's text. ``sync_profiles``
keeps one student's rows in step with their current approved papers: it removes rows for
papers no longer approved and adds missing ones. It runs only when rule D is not ``off``,
except ``prune_profiles``, which the approval-withdrawal path always calls so a withdrawn
paper's statistics never outlive the approval.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterable

import numpy as np

from . import core

log = logging.getLogger(__name__)


def _label(sample, index: int) -> str:
    title = (getattr(sample, "assignment", "") or "").strip()
    date = (getattr(sample, "submitted_at", "") or "")[:10]
    base = title or f"Approved paper {index + 1}"
    return f"{base} ({date})" if date else base


def _papers(state) -> list[tuple]:
    return [
        (i, s)
        for i, s in enumerate(state.samples)
        if isinstance(getattr(s, "text", None), str) and s.text.strip() and s.auth_weight > 0
    ]


def current_shas(state) -> set:
    return {core.text_sha256(s.text) for _, s in _papers(state)}


def _same_vector(stored, current) -> bool:
    if stored is None or current is None:
        return False
    a, b = np.asarray(stored, dtype=float), np.asarray(current, dtype=float)
    return a.shape == b.shape and bool(np.allclose(a, b, rtol=0, atol=1e-9))


def prune_profiles(repo, state) -> int:
    """Delete stored profiles for papers no longer in the student's approved set."""
    return repo.delete_rule_d_profiles(state.student_id, keep=current_shas(state))


def sync_profiles(repo, state, feature_fn: Callable[[str], np.ndarray]) -> list[dict]:
    """The student's profiles in sample order, creating missing ones and dropping stale ones."""
    stored = repo.get_rule_d_profiles(state.student_id)
    want = {}
    for i, s in _papers(state):
        want.setdefault(core.text_sha256(s.text), (i, s))
    if set(stored) - set(want):
        repo.delete_rule_d_profiles(state.student_id, keep=set(want))
    out = []
    for sha, (i, s) in want.items():
        prof = stored.get(sha)
        if prof is not None and not _same_vector(prof.get("vector"), s.vector):
            prof = None  # features were re-extracted since: rebuild, never compare stale vectors
        if prof is None:
            prof = core.build_paper_profile(s.text, s.vector, _label(s, i), feature_fn)
            repo.put_rule_d_profile(state.student_id, sha, prof)
        out.append(prof)
    return out


def observe_for(
    repo, state, peer_states: Iterable, text: str, vector, feature_fn: Callable[[str], np.ndarray]
) -> core.Observation:
    """Rule D for one scoring call. ``peer_states`` must already be the same workspace's
    students; the claimed student is excluded here."""
    from original.principal import tenant_of

    tenant = tenant_of(state.student_id)
    peers = [
        p
        for p in peer_states
        if p.student_id != state.student_id and tenant_of(p.student_id) == tenant
    ]
    with_text = [p for p in peers if _papers(p)]
    n_papers = sum(len(_papers(p)) for p in with_text)
    if len(with_text) < core.MIN_PEER_STUDENTS or n_papers < core.MIN_PEER_PAPERS:
        return core.inconclusive(
            f"the class needs at least {core.MIN_PEER_STUDENTS} other students with "
            f"{core.MIN_PEER_PAPERS} "
            f"approved papers between them (it has {len(with_text)} and {n_papers}).",
            len(with_text),
            n_papers,
        )
    claimed = sync_profiles(repo, state, feature_fn)
    peer_profiles: dict[str, list[dict]] = {
        p.student_id: sync_profiles(repo, p, feature_fn) for p in with_text
    }
    return core.observe(text, vector, claimed, peer_profiles)
