"""Plain-English reasons for a rule D observation, both ways.

Every sentence is a consistency observation about writing habits: which past paper the new one
is closest to, the character sequences and punctuation habits it shares or does not share, how
it compares with classmates' writing, and where a gap is likely to come from (length, topic,
type of assignment). Nothing here judges the student, estimates a probability, or names a
cause such as outside help; ``BANNED`` lists words the tests forbid in any output.
"""

from __future__ import annotations

import statistics

from . import textprofile as tp

BANNED = (
    "ai",
    "a.i.",
    "cheat",
    "probab",
    "plagiar",
    "ghost",
    "dishonest",
    "misconduct",
    "fraud",
    "chatgpt",
)
_PUNCT = set(".,;:!?()[]\"'\u2014\u2013-")
_FW = tp._FW_SET


def _style_bearing(gram: str) -> bool:
    """Readable habit-bearing sequences: they start and end at a word or punctuation boundary
    (so a teacher sees whole pieces such as ``', or '`` or ``' \u2013 '``, never a word
    fragment) and contain punctuation or a whole function word."""
    edge = set(" ") | _PUNCT
    if len(gram) < 3 or gram[0] not in edge or gram[-1] not in edge or not gram.strip():
        return False
    if any(c in _PUNCT for c in gram):
        return True
    return any(t in _FW for t in gram.split(" ") if t)


def _pick(scores: dict[int, float], terms: list[str], k: int = 4) -> list[str]:
    out: list[str] = []
    for j, s in sorted(scores.items(), key=lambda kv: -kv[1]):
        if s <= 0:
            break
        g = terms[j]
        if not _style_bearing(g) or any(g in o or o in g for o in out):
            continue
        out.append(g)
        if len(out) == k:
            break
    return out


def _quote(grams: list[str]) -> str:
    return ", ".join("“" + g.replace("\n", " ").strip() + "”" for g in grams)


def explain(
    obs,
    *,
    new_text: str,
    new_profiles: dict,
    claimed: list[dict],
    sims: dict,
    words: int,
    own_centroid: dict[int, float],
    class_mean: dict[int, float],
) -> None:
    vec = tp.vectorizers()["char"]
    new = new_profiles["char"]
    own = own_centroid
    # what is characteristic of THIS student compared with the class (not just common English)
    distinct = {j: v - class_mean.get(j, 0.0) for j, v in own.items()}
    peers_c = sims["char"][0][1:]
    own_c = float(sims["char"][0][0])
    n_peers = len(peers_c)
    n_below = int((peers_c < own_c).sum())
    like, less = obs.reads_like, obs.reads_less_like

    # nearest past paper
    per_paper = [tp.dot(new, {int(k): v for k, v in p["char"].items()}) for p in claimed]
    best = max(range(len(claimed)), key=lambda i: per_paper[i])
    like.append(
        f"Its closest match among this student's approved papers is “{claimed[best]['label']}”."
    )

    # how it ranks against classmates (a count, never a percentage)
    if n_below > n_peers / 2:
        like.append(
            f"Its character patterns are closer to this student's past papers than to the past "
            f"papers of {n_below} of {n_peers} classmates."
        )
    else:
        less.append(
            f"Its character patterns are closer to the past papers of {n_peers - n_below} of "
            f"{n_peers} classmates than to this student's own past papers."
        )

    # shared and differing character sequences
    shared = _pick({j: v * distinct.get(j, 0.0) for j, v in new.items()}, vec.terms)
    if shared:
        like.append(
            f"It shares sequences that are characteristic of this student compared with the class, "
            f"such as {_quote(shared)}."
        )
    new_only = _pick(
        {j: v - own.get(j, 0.0) for j, v in new.items() if own.get(j, 0.0) < v / 4}, vec.terms, 3
    )
    if new_only:
        less.append(
            "It uses sequences that are rare in this student's past papers, such as "
            f"{_quote(new_only)}."
        )
    missing = _pick({j: d for j, d in distinct.items() if new.get(j, 0.0) == 0.0}, vec.terms, 3)
    if missing:
        less.append(
            f"Some of this student's habitual sequences do not appear, such as {_quote(missing)}."
        )

    # punctuation habits
    from .core import punctuation_rates

    now = punctuation_rates(new_text)
    for name, rate in now.items():
        past = [p.get("punct", {}).get(name, 0.0) for p in claimed]
        lo, hi, mean = min(past), max(past), statistics.mean(past)
        if mean >= 1.0 and rate > 0 and lo <= rate <= hi:
            like.append(
                f"It uses {name} about as often as this student usually does "
                f"({rate:.1f} per 1,000 words; past papers {lo:.1f}-{hi:.1f})."
            )
        elif rate > 2 * hi and rate - hi >= 2.0:
            less.append(
                f"It uses {name} much more often than this student's past papers "
                f"({rate:.1f} per 1,000 words; past papers {lo:.1f}-{hi:.1f})."
            )
        elif lo >= 2.0 and rate < lo / 2:
            less.append(
                f"It uses {name} much less often than this student's past papers "
                f"({rate:.1f} per 1,000 words; past papers {lo:.1f}-{hi:.1f})."
            )

    # where a gap is likely to come from
    median_past = statistics.median(p["words"] for p in claimed)
    if words < 0.5 * median_past:
        less.append(
            f"The new paper ({words} words) is much shorter than the past papers (about "
            f"{int(median_past)} words). Short papers are where this comparison is weakest, so "
            f"differences here say less."
        )
    c = obs.components
    if c["word_shape_profile"] >= 0 > c["character_profile"]:
        less.append(
            "Word shapes and punctuation stay close to this student's papers; the difference is "
            "mostly in vocabulary, which often follows the topic rather than the writer."
        )
    if c["original_features"] < 0 and c["original_features"] < min(
        c["character_profile"], c["word_shape_profile"]
    ):
        less.append(
            "Original's sentence- and word-level measures differ more than the character patterns "
            "do; a different type of assignment or genre can cause this."
        )

    if obs.reads_less_like_student:
        obs.summary = (
            "Reads less like this student's earlier writing than is usual in this class. "
            "This is a reason to look more closely and talk with the student, not evidence of "
            "anything."
        )
    else:
        obs.summary = (
            "Reads like this student's earlier writing, compared with the rest of the class."
        )
