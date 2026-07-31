"""
validation/plato/normalise.py — neutralise edition and transcription convention.

Why this exists
---------------
The translator gate failed (Jowett-vs-Cary distance exceeded
dialogue-vs-dialogue distance), and a tier decomposition showed why: 27% of the
translator separation sits in Tier 4 (character trigrams + punctuation) against
only 7% of the chronology separation — a 3.9x over-representation. The top
three contributing features were ``quote_rate`` (11.5%), ``block_quote_rate``
(10.1%) and ``dash_rate`` (9.1%).

Direct measurement confirmed those are edition conventions, not prose:

    Cary        straight quotes 34.1 / 1k words, italic markers 3.9 / 1k
    Jowett      straight quotes  0.0 / 1k words, italic markers 0.0 / 1k

and Jowett's own Gutenberg files are internally inconsistent — the Apology
transcription uses curly quotes and em-dashes, the Crito uses double-hyphens
and 40 double-spaces per 1k words. Different volunteers, different conventions,
same translator.

What is and is not normalised
-----------------------------
Normalised (rendering decisions made by a typesetter or transcriber):

  * speaker labels — ``_Socr._`` and ``SOCRATES:`` denote the same thing and
    are canonicalised to ``SPEAKER:``. The COUNT of turns is preserved, because
    turn density is a genuine genre signal; only the rendering is unified.
  * Gutenberg ``_italic_`` markers
  * dash glyph (``--`` vs ``—``)
  * quote glyph (curly vs straight)
  * footnote reference markers
  * runs of whitespace within a line

Deliberately NOT normalised (genuine authorial or translator style):

  * comma, semicolon, colon and parenthesis DENSITY — real prose rhythm
  * sentence length, vocabulary, syntax — the whole point of the study
  * paragraph structure — Tier 2 reads it

The distinction is: unify how a mark is *drawn*, never how often the prose
*reaches for* it.
"""

from __future__ import annotations

import re

# Cary renders a speaker as an italicised abbreviation at line start: "_Socr._".
_CARY_SPEAKER = re.compile(r"^[ \t]*_([A-Z][^_\n]{0,20})_[ \t]*", re.M)
# Jowett renders it as capitals plus a colon: "SOCRATES:  ".
_JOWETT_SPEAKER = re.compile(r"^[ \t]*[A-Z][A-Z .'’-]{1,28}:[ \t]*", re.M)

_ITALIC = re.compile(r"_([^_\n]{1,200})_")
_FOOTNOTE_REF = re.compile(r"\[\d{1,3}\]")
_INLINE_WS = re.compile(r"[ \t]{2,}")

CANONICAL_SPEAKER = "SPEAKER: "


def normalise(text: str) -> str:
    """Return text with edition/transcription conventions unified.

    Order matters: speaker labels are canonicalised before the generic italic
    strip, because Cary's labels ARE italics and would otherwise become bare
    abbreviations indistinguishable from an ordinary sentence opener.
    """
    # 1. Speaker labels -> one canonical form (count preserved, rendering unified).
    text = _CARY_SPEAKER.sub(CANONICAL_SPEAKER, text)
    text = _JOWETT_SPEAKER.sub(CANONICAL_SPEAKER, text)

    # 2. Remaining italics: keep the words, drop the markup.
    text = _ITALIC.sub(r"\1", text)

    # 3. Footnote reference markers.
    text = _FOOTNOTE_REF.sub("", text)

    # 4. Dash glyph.
    text = text.replace("---", "—").replace("--", "—")

    # 5. Quote glyphs -> straight.
    text = (
        text.replace("“", '"')
        .replace("”", '"')
        .replace("‘", "'")
        .replace("’", "'")
    )

    # 6. Collapse intra-line whitespace runs. Newlines are untouched so that
    #    paragraph structure (which Tier 2 reads) survives.
    text = _INLINE_WS.sub(" ", text)

    return text


def convention_profile(text: str) -> dict:
    """Counts of the markup this module targets. For before/after reporting."""
    words = max(1, len(text.split()))
    per_k = lambda n: round(1000.0 * n / words, 2)  # noqa: E731
    return {
        "italic_markers": per_k(len(_ITALIC.findall(text))),
        "straight_quotes": per_k(text.count('"')),
        "curly_quotes": per_k(text.count("“") + text.count("”")),
        "em_dashes": per_k(text.count("—")),
        "double_hyphens": per_k(text.count("--")),
        "footnote_refs": per_k(len(_FOOTNOTE_REF.findall(text))),
        "double_spaces": per_k(len(_INLINE_WS.findall(text))),
        "speaker_labels": per_k(
            len(_CARY_SPEAKER.findall(text)) + len(_JOWETT_SPEAKER.findall(text))
        ),
    }
