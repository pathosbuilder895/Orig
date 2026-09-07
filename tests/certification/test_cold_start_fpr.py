"""Cold-start false-positive certification (gap T-01).

The pilot-blocking claim, stated so it can fail: a genuine author with the
pilot's modal three authenticated baselines, scored through the production
path with flags off, must not land in ``schedule_conversation`` or
``escalate``. The 2026-09-02 architecture review measured 0.75-0.82 deviation
on exactly that setup by probe; nothing pinned it. This does.

See docs/testing/06-scientific-validation.md §3.
"""

from __future__ import annotations

import statistics

import pytest

from tests.certification.conftest import (
    MIN_AUTHORS,
    provision_and_score,
    record_verdict,
    score_text,
)

#: Pilot-acceptance bar, deliberately looser than gate G1's 0.05: the corpus is
#: small and the purpose is to catch saturation, not to calibrate a threshold.
MAX_FLAG_RATE = 0.10

#: The witness has to clear a bar of its own, or "the harness can detect a
#: failure" is an unfalsifiable claim.
MIN_WITNESS_FLAG_RATE = 0.5


def _summarise(outcomes):
    """(flagged rate, usable outcomes, report payload) for a set of outcomes."""
    usable = [o for o in outcomes if o.usable]
    flagged = [o for o in usable if o.flagged]
    rate = len(flagged) / len(usable) if usable else None
    deviations = [o.deviation_score for o in usable if o.deviation_score is not None]
    payload = {
        "authors_attempted": len(outcomes),
        "authors_usable": len(usable),
        "flagged": len(flagged),
        "deviation_median": statistics.median(deviations) if deviations else None,
        "baselines_held_for_drift": sum(o.baselines_held for o in outcomes),
        "baselines_rejected": sum(o.baselines_rejected for o in outcomes),
        # How many of the scored authors had a holdout that is another section
        # of the SAME work rather than a different work (see Author). Attached
        # to every verdict so the rate is never quoted without it.
        "holdout_same_work_count": sum(1 for o in outcomes if o.holdout_same_work),
        "per_author": [
            {
                "author_id": o.author_id,
                "action": o.action,
                "deviation_score": o.deviation_score,
                "baselines_accepted": o.baselines_accepted,
                "baselines_held": o.baselines_held,
                "baselines_rejected": o.baselines_rejected,
                "authenticated_count": o.authenticated_count,
                "holdout_same_work": o.holdout_same_work,
                "notes": o.notes,
            }
            for o in outcomes
        ],
    }
    return rate, usable, payload


@pytest.mark.certification
@pytest.mark.blocker
@pytest.mark.parametrize("n_baselines", [3, 5, 10])
def test_same_author_action_at_pilot_baseline_counts(
    live_client, store_reset, corpus_authors, n_baselines
):
    """T-01: same-author action at pilot baseline counts.

    Each author's baselines come from one work, and the scored holdout is
    other text by the same author — a genuinely different work for the authors
    that have one, and otherwise a different section of the same work (the
    corpus carries only one work for 8 of its 11 authors). Either way the
    holdout is genuine authorship, so every flag here is a false positive; the
    same-work count travels with the rate in the report
    (`holdout_same_work_count`), because a same-work holdout is the *easier*
    case and cannot be read as inflating the rate. Through the API (baselines
    and score both), default flags, three-valued: below MIN_AUTHORS usable
    authors the verdict is `uninformative` and the test skips rather than
    passing on noise.

    Red on this branch by design — the saturation defect is open.
    """
    name = f"T-01 cold-start FPR (N={n_baselines})"

    # Eligibility is knowable before any API call: an author whose baseline
    # work does not yield N chunks cannot be provisioned at N.
    eligible = [a for a in corpus_authors if len(a.baseline_chunks) >= n_baselines]
    if len(eligible) < MIN_AUTHORS:
        record_verdict(
            name,
            "uninformative",
            value=None,
            n=len(eligible),
            n_baselines=n_baselines,
            reason=(
                f"only {len(eligible)} of {len(corpus_authors)} corpus authors have a "
                f"baseline work long enough for {n_baselines} chunks (floor {MIN_AUTHORS})"
            ),
        )
        pytest.skip(
            f"uninformative — {len(eligible)} authors have {n_baselines} baseline chunks, "
            f"floor is {MIN_AUTHORS}"
        )

    outcomes = [
        provision_and_score(
            live_client, author, n_baselines, f"cert-{author.author_id}-{n_baselines}"
        )
        for author in eligible
    ]
    rate, usable, payload = _summarise(outcomes)

    if len(usable) < MIN_AUTHORS:
        record_verdict(
            name,
            "uninformative",
            value=rate,
            n=len(usable),
            n_baselines=n_baselines,
            reason=f"only {len(usable)} authors scored cleanly (floor {MIN_AUTHORS})",
            **payload,
        )
        pytest.skip(f"uninformative — {len(usable)} authors scored cleanly, floor is {MIN_AUTHORS}")

    record_verdict(
        name,
        "pass" if rate <= MAX_FLAG_RATE else "fail",
        value=rate,
        n=len(usable),
        n_baselines=n_baselines,
        bar=MAX_FLAG_RATE,
        **payload,
    )
    assert rate <= MAX_FLAG_RATE, (
        f"same-author flag rate {rate:.2f} at N={n_baselines} "
        f"({payload['flagged']}/{len(usable)} authors flagged, bar {MAX_FLAG_RATE:.2f}); "
        f"median deviation {payload['deviation_median']}"
    )


@pytest.mark.certification
def test_harness_flags_a_different_author(live_client, store_reset, corpus_authors):
    """Witness for T-01: the same harness flags impostor holdouts, and separates.

    Identical provisioning at N=5, but every author is scored against the
    *next* author's holdout. If this were also unflagged the certification
    above could not fail for a real reason, and its red would prove nothing.

    Two assertions, because the first alone is weak. A product that flags
    *everything* would pass "impostors are flagged" while discriminating
    nothing, which is close to what the certification measures. So each
    student here is scored TWICE off the same baselines — once on the
    impostor holdout, once on its own — and the impostor median must exceed
    the genuine median. The second score is one extra ``POST /score`` per
    author and no extra baseline extraction; ``POST /students/{id}/score``
    does not write to the profile, so the two are order-independent.

    Deliberately not coupled to the blocker test above: its own students, its
    own provisioning, its own numbers. Green on this branch; not a blocker.
    """
    n_baselines = 5
    eligible = [a for a in corpus_authors if len(a.baseline_chunks) >= n_baselines]
    if len(eligible) < MIN_AUTHORS:
        record_verdict(
            "T-01 witness: impostor holdout",
            "uninformative",
            value=None,
            n=len(eligible),
            n_baselines=n_baselines,
            reason=f"only {len(eligible)} eligible authors (floor {MIN_AUTHORS})",
        )
        pytest.skip(f"uninformative — {len(eligible)} eligible authors, floor is {MIN_AUTHORS}")

    outcomes = [
        provision_and_score(
            live_client,
            author,
            n_baselines,
            f"witness-{author.author_id}-{n_baselines}",
            holdout=eligible[(index + 1) % len(eligible)].holdout,
        )
        for index, author in enumerate(eligible)
    ]
    rate, usable, payload = _summarise(outcomes)

    # Second score per student, off the baselines already posted above: the
    # author's OWN holdout. Only for students that provisioned cleanly — an
    # unusable outcome has no profile at N to score against.
    genuine_by_author = {}
    for index, author in enumerate(eligible):
        if not outcomes[index].usable:
            continue
        deviation = score_text(
            live_client, f"witness-{author.author_id}-{n_baselines}", author.holdout
        )
        if deviation is not None:
            genuine_by_author[author.author_id] = deviation

    if len(usable) < MIN_AUTHORS:
        record_verdict(
            "T-01 witness: impostor holdout",
            "uninformative",
            value=rate,
            n=len(usable),
            n_baselines=n_baselines,
            reason=f"only {len(usable)} authors scored cleanly (floor {MIN_AUTHORS})",
            **payload,
        )
        pytest.skip(f"uninformative — {len(usable)} authors scored cleanly, floor is {MIN_AUTHORS}")

    impostor_deviations = [o.deviation_score for o in usable if o.deviation_score is not None]
    genuine_deviations = [
        genuine_by_author[o.author_id] for o in usable if o.author_id in genuine_by_author
    ]
    impostor_median = statistics.median(impostor_deviations) if impostor_deviations else None
    genuine_median = statistics.median(genuine_deviations) if genuine_deviations else None
    separated = (
        impostor_median is not None
        and genuine_median is not None
        and impostor_median > genuine_median
    )

    record_verdict(
        "T-01 witness: impostor holdout",
        "pass" if rate >= MIN_WITNESS_FLAG_RATE and separated else "fail",
        value=rate,
        n=len(usable),
        n_baselines=n_baselines,
        bar=MIN_WITNESS_FLAG_RATE,
        impostor_deviation_median=impostor_median,
        genuine_deviation_median=genuine_median,
        genuine_scored=len(genuine_deviations),
        **payload,
    )
    assert rate >= MIN_WITNESS_FLAG_RATE, (
        f"harness flagged only {rate:.2f} of impostor holdouts at N={n_baselines} "
        f"({payload['flagged']}/{len(usable)}); the certification's red would be meaningless"
    )
    assert genuine_median is not None, (
        "no genuine holdout scored against a witness profile; the separation "
        "assertion has nothing to compare"
    )
    assert impostor_median > genuine_median, (
        f"impostor median deviation {impostor_median:.3f} is not above genuine median "
        f"{genuine_median:.3f} over the same {len(genuine_deviations)} profiles at "
        f"N={n_baselines}; the harness flags without discriminating, so its green "
        f"witnesses the flag path firing and nothing more"
    )
