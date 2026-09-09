"""Fixed literal corpus for the flag byte-identity matrix (T-15).

Every string here is a literal. The baseline/submission documents are
composed from ``SENTENCES`` by fixed index tuples so each document clears
``original.fusion.peers.MIN_WORDS`` (300 words — the eligibility floor the
fused-score and style-authorship experts share) while still differing from
its siblings enough that ``baseline_std`` is a real measurement rather than
the flat uncertainty prior.

Kept in its own module rather than inline in the test so that
``scripts/update_score_snapshot.py`` and the test import the *same* text
and can never drift apart.
"""

from __future__ import annotations

SENTENCES: tuple[str, ...] = (
    "The doctrine of justification by faith stands at the centre of the gospel, and the "
    "apostle labours through several chapters to show that righteousness comes not by works "
    "of the law but through faith alone.",
    "This conviction shaped the Reformation, and it continues to shape pastoral practice "
    "wherever ministers are asked what a troubled conscience ought to do on a Tuesday "
    "afternoon rather than in a lecture hall.",
    "A careful reader notices how the argument unfolds in stages, each building upon the "
    "last, until the conclusion becomes unavoidable to anyone who has followed the reasoning "
    "from its opening premises.",
    "Sanctification follows upon justification, and the older writers laboured to show that "
    "holiness is neither an achievement nor an accident but a cultivated habit watered by "
    "the ordinary means of grace.",
    "The Puritan literature on mortification remains useful, though its idiom can be "
    "forbidding to modern ears, and a reader who persists will find counsel that is neither "
    "sentimental nor needlessly severe.",
    "Ecclesiology has suffered a peculiar neglect in the modern academy, where questions of "
    "personal salvation have crowded out questions concerning the nature and the ordinary "
    "government of the church.",
    "Baptism is a public act, the Supper is a common meal, and discipline presupposes "
    "membership, so that a Christian without a congregation is a figure the apostolic "
    "writings do not recognise.",
    "The relation of exegesis to dogmatics has been contested since the rise of historical "
    "criticism, and the contest is not merely academic, since it determines what a graduate "
    "is actually able to do.",
    "If exegesis is severed from doctrine it becomes a technical craft without a subject, "
    "and if doctrine is severed from exegesis it becomes speculation dressed in a pious "
    "and borrowed vocabulary.",
    "Preaching is the point at which theology becomes audible, and it is therefore the point "
    "at which theological error does the most damage to people who have no way of checking "
    "what they are told.",
    "A sermon is not a lecture with illustrations, nor a devotional essay read aloud, but an "
    "act of proclamation addressed to a particular congregation in a particular and "
    "unrepeatable week of its life.",
    "The question of assurance has troubled sensitive consciences in every generation, and "
    "the pastoral literature on the subject is uneven, veering between anxious introspection "
    "and a comfort that costs nothing.",
    "The better path, mapped by the reformers and refined by their heirs, looks outward "
    "first to the promise and to the person of Christ, and only afterwards to the evidences "
    "of grace within.",
    "Providence consoled the afflicted, and the divines of the period laboured to show that "
    "secondary causes are not abolished by the doctrine but are rather established and given "
    "their proper dignity.",
    "The sacraments have been debated with more heat than light, and the confessional "
    "traditions insisted that sign and thing signified must be neither confused with one "
    "another nor divided from each other.",
    "The recovery of a serious doctrine of vocation would repay the effort, because the "
    "reformers insisted that ordinary work is not a lesser calling than the work of the "
    "cloister or of the study.",
    "Anyone who reads the sermons of that period will see how quickly the argument moved "
    "from the study into the parish, and how little patience its authors had for a piety "
    "that despised the common life.",
    "Their opponents assumed a hierarchy of estates, and the reply turned upon the promise "
    "rather than upon merit, so that the pastoral consequences followed immediately and were "
    "felt in every ordinary household.",
    "Catechesis was not an afterthought in that century but the ordinary shape of "
    "instruction, and the questions were memorised because the answers were expected to be "
    "needed under pressure and at short notice.",
    "Hymnody carried doctrine into the memory of congregations that could not read, which is "
    "why the polemicists of every party took such trouble over what their people were "
    "permitted to sing on Sunday.",
    "The revival preaching of the following century inherited these instincts and coarsened "
    "some of them, and the historians who describe the coarsening rarely ask what the "
    "preachers were trying to accomplish.",
    "A student who reads only the summaries will acquire the vocabulary without the "
    "arguments, and will be unable to say why any particular formulation was preferred to "
    "the several alternatives that were rejected.",
    "The archives of the period are fuller than the printed record suggests, and the "
    "correspondence in particular shows men revising in private the positions they defended "
    "without qualification in public print.",
    "It is therefore worth asking, before we settle any of these questions, what sort of "
    "evidence would count against the position we are inclined to hold, and whether we have "
    "genuinely looked for it.",
)

# Fixed index tuples. Overlapping windows: adjacent baselines share most of
# their sentences (so the ingestion drift gate accepts every one of them),
# while the first and last share none.
_BASELINE_INDICES: tuple[tuple[int, ...], ...] = (
    (0, 1, 2, 3, 4, 5, 6, 7, 8, 9),
    (2, 3, 4, 5, 6, 7, 8, 9, 10, 11),
    (4, 5, 6, 7, 8, 9, 10, 11, 12, 13),
    (6, 7, 8, 9, 10, 11, 12, 13, 14, 15),
    (8, 9, 10, 11, 12, 13, 14, 15, 16, 17),
    (10, 11, 12, 13, 14, 15, 16, 17, 0, 1),
)

# Six sentences that appear in no baseline (18-23), mixed with four that do,
# so the submission is same-author-ish but not a baseline copy.
_SUBMISSION_INDICES: tuple[int, ...] = (18, 1, 19, 9, 20, 12, 21, 15, 22, 23)

# Peer documents draw from the tail of the pool, so peers read as a
# different-but-adjacent cohort rather than as copies of the claimed author.
_PEER_INDICES: tuple[tuple[int, ...], ...] = (
    (19, 20, 21, 22, 23, 18, 5, 6, 7, 14),
    (21, 22, 23, 18, 19, 20, 8, 11, 13, 16),
    (23, 18, 19, 20, 21, 22, 3, 4, 10, 17),
)


def _compose(indices: tuple[int, ...], prefix: str = "") -> str:
    return prefix + " ".join(SENTENCES[i] for i in indices)


BASELINE_TEXTS: tuple[str, ...] = tuple(_compose(ix) for ix in _BASELINE_INDICES)
SUBMISSION_TEXT: str = _compose(_SUBMISSION_INDICES)

# ISO dates, spread over one term: LONGITUDINAL_DRIFT_ENABLED needs
# LONGITUDINAL_MIN_SAMPLES (6) *dated* authenticated samples.
BASELINE_DATES: tuple[str, ...] = (
    "2025-09-02",
    "2025-09-23",
    "2025-10-07",
    "2025-10-28",
    "2025-11-11",
    "2025-12-02",
)

N_PEERS = 10


def peer_texts(peer_index: int) -> tuple[str, ...]:
    """Three >= MIN_WORDS documents for peer ``peer_index``."""
    return tuple(
        _compose(ix, prefix=f"Peer {peer_index:02d}, document {j}. ")
        for j, ix in enumerate(_PEER_INDICES)
    )
